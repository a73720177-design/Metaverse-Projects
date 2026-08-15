from typing import Protocol
from uuid import UUID

from app.models.review import ReviewResult


class ReviewRepository(Protocol):
    async def save(self, review: ReviewResult) -> None: ...

    async def get(self, review_id: UUID) -> ReviewResult | None: ...
