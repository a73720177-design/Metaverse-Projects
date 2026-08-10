from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatRequest, ChatResponse
from app.ports.chat_generator import ChatGenerator, ChatGeneratorError


class ChatServiceError(RuntimeError):
    pass


class ChatService:
    def __init__(self, generator: ChatGenerator) -> None:
        self.generator = generator

    async def reply(self, agent_id: UUID, request: ChatRequest) -> ChatResponse:
        try:
            generated = await self.generator.generate(agent_id, request)
            return ChatResponse.model_validate(
                {**generated, "message_id": uuid4(), "agent_id": agent_id}
            )
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc
