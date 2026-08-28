from typing import Protocol
from uuid import UUID

from app.models.persona import PersonaProfile
from app.db.database import get_session_factory
from app.db.tables import AgentTable


class AgentRepository(Protocol):
    """Backend가 DB 팀에 요구하는 평가자 저장 계약입니다."""

    async def save(self, persona: PersonaProfile) -> None: ...
    async def get(self, agent_id: UUID) -> PersonaProfile | None: ...


class InMemoryAgentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._agents: dict[UUID, PersonaProfile] = {}

    async def save(self, persona: PersonaProfile) -> None:
        self._agents[persona.agent_id] = persona

    async def get(self, agent_id: UUID) -> PersonaProfile | None:
        return self._agents.get(agent_id)


class PostgresAgentRepository:
    async def save(self, persona: PersonaProfile) -> None:
        data = persona.model_dump(mode="json")
        row = AgentTable(
            agent_id=persona.agent_id,
            name=persona.name,
            description=persona.description,
            role=persona.role,
            expertise=data["expertise"],
            evaluation_style=data["evaluation_style"],
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, agent_id: UUID) -> PersonaProfile | None:
        async with get_session_factory()() as session:
            row = await session.get(AgentTable, agent_id)
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
