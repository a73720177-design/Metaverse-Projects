from typing import Any, Protocol
from uuid import UUID

from app.models.chat import ChatRequest


class ChatGeneratorError(RuntimeError):
    pass


class ChatGenerator(Protocol):
    async def generate(self, agent_id: UUID, request: ChatRequest) -> dict[str, Any]: ...
