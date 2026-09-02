from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select

from app.db.database import get_session_factory
from app.db.tables import AgentDocumentTable, AgentTable
from app.models.persona import PersonaHistoryItem, PersonaProfile


class AgentRepository(Protocol):
    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None: ...
    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None: ...
    async def list(self, owner_id: UUID, *, deleted: bool) -> list[PersonaHistoryItem]: ...
    async def set_deleted(self, agent_id: UUID, owner_id: UUID, *, deleted: bool) -> PersonaHistoryItem | None: ...
    async def permanently_delete(self, agent_id: UUID, owner_id: UUID) -> bool: ...
    async def unlink_document(self, document_id: UUID, owner_id: UUID) -> None: ...


class InMemoryAgentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._agents: dict[UUID, tuple[UUID, PersonaHistoryItem]] = {}

    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None:
        self._agents[persona.agent_id] = (
            owner_id,
            PersonaHistoryItem.model_validate(persona.model_dump()),
        )

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        stored = self._agents.get(agent_id)
        if stored is None or stored[0] != owner_id or stored[1].deleted_at is not None:
            return None
        return PersonaProfile.model_validate(stored[1].model_dump())

    async def list(self, owner_id: UUID, *, deleted: bool) -> list[PersonaHistoryItem]:
        personas = [
            persona
            for stored_owner, persona in self._agents.values()
            if stored_owner == owner_id and (persona.deleted_at is not None) == deleted
        ]
        return sorted(personas, key=lambda persona: persona.created_at, reverse=True)

    async def set_deleted(self, agent_id: UUID, owner_id: UUID, *, deleted: bool) -> PersonaHistoryItem | None:
        stored = self._agents.get(agent_id)
        if stored is None or stored[0] != owner_id:
            return None
        now = datetime.now(timezone.utc)
        persona = stored[1].model_copy(update={"deleted_at": now if deleted else None, "updated_at": now})
        self._agents[agent_id] = (owner_id, persona)
        return persona

    async def permanently_delete(self, agent_id: UUID, owner_id: UUID) -> bool:
        stored = self._agents.get(agent_id)
        if stored is None or stored[0] != owner_id or stored[1].deleted_at is None:
            return False
        del self._agents[agent_id]
        return True

    async def unlink_document(self, document_id: UUID, owner_id: UUID) -> None:
        for agent_id, (stored_owner, persona) in list(self._agents.items()):
            if stored_owner != owner_id or document_id not in persona.document_ids:
                continue
            self._agents[agent_id] = (
                stored_owner,
                persona.model_copy(update={
                    "document_ids": [
                        item for item in persona.document_ids if item != document_id
                    ]
                }),
            )


def _to_history(row: AgentTable) -> PersonaHistoryItem:
    return PersonaHistoryItem.model_validate(
        {
            "agent_id": row.agent_id,
            "name": row.name,
            "description": row.description,
            "role": row.role,
            "expertise": row.expertise,
            "evaluation_style": row.evaluation_style,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
            "document_ids": [],
        }
    )


class PostgresAgentRepository:
    async def _document_ids(self, session, agent_id: UUID) -> list[UUID]:
        return list((await session.scalars(
            select(AgentDocumentTable.document_id)
            .where(AgentDocumentTable.agent_id == agent_id)
            .order_by(AgentDocumentTable.created_at, AgentDocumentTable.document_id)
        )).all())

    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None:
        data = persona.model_dump(mode="json")
        row = AgentTable(
            agent_id=persona.agent_id,
            owner_id=owner_id,
            name=persona.name,
            description=persona.description,
            role=persona.role,
            expertise=data["expertise"],
            evaluation_style=data["evaluation_style"],
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.execute(
                delete(AgentDocumentTable).where(AgentDocumentTable.agent_id == persona.agent_id)
            )
            session.add_all(
                AgentDocumentTable(agent_id=persona.agent_id, document_id=document_id)
                for document_id in persona.document_ids
            )
            await session.commit()

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(AgentTable).where(
                    AgentTable.agent_id == agent_id,
                    AgentTable.owner_id == owner_id,
                    AgentTable.deleted_at.is_(None),
                )
            )
            document_ids = await self._document_ids(session, agent_id) if row else []
        if row is None:
            return None
        return PersonaProfile.model_validate(
            {**_to_history(row).model_dump(), "document_ids": document_ids}
        )

    async def list(self, owner_id: UUID, *, deleted: bool) -> list[PersonaHistoryItem]:
        condition = AgentTable.deleted_at.is_not(None) if deleted else AgentTable.deleted_at.is_(None)
        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(AgentTable)
                    .where(AgentTable.owner_id == owner_id, condition)
                    .order_by(AgentTable.created_at.desc())
                )
            ).all()
            document_ids_by_agent = {
                row.agent_id: await self._document_ids(session, row.agent_id) for row in rows
            }
        return [
            _to_history(row).model_copy(update={"document_ids": document_ids_by_agent[row.agent_id]})
            for row in rows
        ]

    async def set_deleted(self, agent_id: UUID, owner_id: UUID, *, deleted: bool) -> PersonaHistoryItem | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(AgentTable).where(
                    AgentTable.agent_id == agent_id,
                    AgentTable.owner_id == owner_id,
                )
            )
            if row is None:
                return None
            row.deleted_at = datetime.now(timezone.utc) if deleted else None
            await session.commit()
            await session.refresh(row)
            document_ids = await self._document_ids(session, row.agent_id)
            return _to_history(row).model_copy(update={"document_ids": document_ids})

    async def permanently_delete(self, agent_id: UUID, owner_id: UUID) -> bool:
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(AgentTable).where(
                    AgentTable.agent_id == agent_id,
                    AgentTable.owner_id == owner_id,
                    AgentTable.deleted_at.is_not(None),
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def unlink_document(self, document_id: UUID, owner_id: UUID) -> None:
        async with get_session_factory()() as session:
            owned_agent_ids = select(AgentTable.agent_id).where(
                AgentTable.owner_id == owner_id
            )
            await session.execute(
                delete(AgentDocumentTable).where(
                    AgentDocumentTable.document_id == document_id,
                    AgentDocumentTable.agent_id.in_(owned_agent_ids),
                )
            )
            await session.commit()
