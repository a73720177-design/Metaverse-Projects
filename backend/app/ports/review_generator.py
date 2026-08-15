from typing import Any, Protocol
from uuid import UUID

from app.models.review import ReviewCreateRequest


class ReviewGeneratorError(RuntimeError):
    pass


class ReviewGenerator(Protocol):
    async def generate(
        self, agent_id: UUID, request: ReviewCreateRequest
    ) -> dict[str, Any]: ...
