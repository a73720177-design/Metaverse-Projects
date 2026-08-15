from typing import Protocol
from uuid import UUID

from app.models.review import ReviewResult


class ReviewRepository(Protocol):
    """Backend가 DB 팀에 요구하는 리뷰 저장 계약입니다."""

    async def save(self, review: ReviewResult) -> None: ...
    async def get(self, review_id: UUID) -> ReviewResult | None: ...


class InMemoryReviewRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._reviews: dict[UUID, ReviewResult] = {}

    async def save(self, review: ReviewResult) -> None:
        self._reviews[review.review_id] = review

    async def get(self, review_id: UUID) -> ReviewResult | None:
        return self._reviews.get(review_id)
