from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select

from app.models.persona import PersonaProfile
from app.db.database import get_session_factory
from app.db.tables import AgentTable, ReviewTable


class AgentRepository(Protocol):
    """Backend가 DB 팀에 요구하는 평가자 저장 계약입니다."""

    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None: ...
    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None: ...
    async def list(self, owner_id: UUID) -> list[PersonaProfile]: ...
    async def delete(self, agent_id: UUID, owner_id: UUID) -> bool: ...


class InMemoryAgentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._agents: dict[UUID, tuple[UUID, PersonaProfile]] = {}

    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None:
        self._agents[persona.agent_id] = (owner_id, persona)

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        stored = self._agents.get(agent_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None

    async def list(self, owner_id: UUID) -> list[PersonaProfile]:
        return [persona for stored_owner_id, persona in self._agents.values() if stored_owner_id == owner_id]

    async def delete(self, agent_id: UUID, owner_id: UUID) -> bool:
        stored = self._agents.get(agent_id)
        if stored is None or stored[0] != owner_id:
            return False
        del self._agents[agent_id]
        return True


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
                )
            )
        if row is None:
            return None
        return PersonaProfile.model_validate(
            {
                "agent_id": row.agent_id,
                "name": row.name,
                "description": row.description,
                "role": row.role,
                "expertise": row.expertise,
                "evaluation_style": row.evaluation_style,
            }
        )

    async def list(self, owner_id: UUID) -> list[PersonaProfile]:
        async with get_session_factory()() as session:
            rows = (await session.scalars(
                select(AgentTable)
                .where(AgentTable.owner_id == owner_id)
                .order_by(AgentTable.created_at, AgentTable.name)
            )).all()
        return [
            PersonaProfile.model_validate(
                {
                    "agent_id": row.agent_id,
                    "name": row.name,
                    "description": row.description,
                    "role": row.role,
                    "expertise": row.expertise,
                    "evaluation_style": row.evaluation_style,
                }
            )
            for row in rows
        ]

    async def delete(self, agent_id: UUID, owner_id: UUID) -> bool:
        async with get_session_factory()() as session:
            existing = await session.scalar(
                select(AgentTable.agent_id).where(
                    AgentTable.agent_id == agent_id,
                    AgentTable.owner_id == owner_id,
                )
            )
            if existing is None:
                return False
            await session.execute(
                delete(ReviewTable).where(
                    ReviewTable.agent_id == agent_id,
                    ReviewTable.owner_id == owner_id,
                )
            )
            result = await session.execute(
                delete(AgentTable).where(
                    AgentTable.agent_id == agent_id,
                    AgentTable.owner_id == owner_id,
                )
            )
            await session.commit()
            return result.rowcount > 0
