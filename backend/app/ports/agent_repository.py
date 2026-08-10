from typing import Protocol
from uuid import UUID

from app.models.persona import PersonaProfile


class AgentRepository(Protocol):
    async def save(self, persona: PersonaProfile) -> None: ...

    async def get(self, agent_id: UUID) -> PersonaProfile | None: ...
