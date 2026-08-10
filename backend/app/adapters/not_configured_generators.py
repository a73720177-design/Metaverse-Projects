from typing import Any
from uuid import UUID

from app.models.chat import ChatRequest
from app.models.review import ReviewCreateRequest
from app.ports.chat_generator import ChatGeneratorError
from app.ports.review_generator import ReviewGeneratorError


class NotConfiguredReviewGenerator:
    async def generate(self, agent_id: UUID, request: ReviewCreateRequest) -> dict[str, Any]:
        raise ReviewGeneratorError("Review generator is not configured")


class NotConfiguredChatGenerator:
    async def generate(self, agent_id: UUID, request: ChatRequest) -> dict[str, Any]:
        raise ChatGeneratorError("Chat generator is not configured")
