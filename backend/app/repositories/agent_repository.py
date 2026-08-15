from typing import Protocol
from uuid import UUID

from app.models.persona import PersonaProfile


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
