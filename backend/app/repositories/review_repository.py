from typing import Protocol
from uuid import UUID

from app.models.review import ReviewResult
from app.db.database import AsyncSessionLocal
from app.db.tables import ReviewTable


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


class PostgresReviewRepository:
    async def save(self, review: ReviewResult) -> None:
        data = review.model_dump(mode="json")
        row = ReviewTable(
            review_id=review.review_id,
            agent_id=review.agent_id,
            document_id=review.document_id,
            claims=data["claims"],
            feedback=data["feedback"],
            questions=data["questions"],
        )
        async with AsyncSessionLocal() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, review_id: UUID) -> ReviewResult | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(ReviewTable, review_id)
        if row is None:
            return None
        return ReviewResult.model_validate(
            {
                "review_id": row.review_id,
                "agent_id": row.agent_id,
                "document_id": row.document_id,
                "claims": row.claims,
                "feedback": row.feedback,
                "questions": row.questions,
            }
        )
