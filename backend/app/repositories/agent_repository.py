from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select

from app.db.database import get_session_factory
from app.db.tables import AgentTable
from app.models.persona import PersonaHistoryItem, PersonaProfile


class AgentRepository(Protocol):
    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None: ...
    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None: ...
    async def list(self, owner_id: UUID, *, deleted: bool) -> list[PersonaHistoryItem]: ...
    async def set_deleted(self, agent_id: UUID, owner_id: UUID, *, deleted: bool) -> PersonaHistoryItem | None: ...
    async def permanently_delete(self, agent_id: UUID, owner_id: UUID) -> bool: ...


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
        }
    )


class PostgresAgentRepository:
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
        return PersonaProfile.model_validate(_to_history(row).model_dump()) if row else None

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
        return [_to_history(row) for row in rows]

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
            return _to_history(row)

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
