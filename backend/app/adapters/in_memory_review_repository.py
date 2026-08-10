from uuid import UUID

from app.models.review import ReviewResult


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._reviews: dict[UUID, ReviewResult] = {}

    async def save(self, review: ReviewResult) -> None:
        self._reviews[review.review_id] = review

    async def get(self, review_id: UUID) -> ReviewResult | None:
        return self._reviews.get(review_id)
