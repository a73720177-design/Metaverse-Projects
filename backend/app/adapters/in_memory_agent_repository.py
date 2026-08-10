from uuid import UUID

from app.models.persona import PersonaProfile


class InMemoryAgentRepository:
    """Development adapter. The DB team can replace it via dependencies.py."""

    def __init__(self) -> None:
        self._agents: dict[UUID, PersonaProfile] = {}

    async def save(self, persona: PersonaProfile) -> None:
        self._agents[persona.agent_id] = persona

    async def get(self, agent_id: UUID) -> PersonaProfile | None:
        return self._agents.get(agent_id)
