from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from app.models.review import ReviewResult
from app.db.database import get_session_factory
from app.db.tables import ReviewTable


class ReviewRepository(Protocol):
    """Backend가 DB 팀에 요구하는 리뷰 저장 계약입니다."""

    async def save(self, review: ReviewResult, owner_id: UUID) -> None: ...
    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None: ...


class InMemoryReviewRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._reviews: dict[UUID, tuple[UUID, ReviewResult]] = {}

    async def save(self, review: ReviewResult, owner_id: UUID) -> None:
        self._reviews[review.review_id] = (owner_id, review)

    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None:
        stored = self._reviews.get(review_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None


class PostgresReviewRepository:
    async def save(self, review: ReviewResult, owner_id: UUID) -> None:
        data = review.model_dump(mode="json")
        row = ReviewTable(
            review_id=review.review_id,
            owner_id=owner_id,
            agent_id=review.agent_id,
            document_id=review.document_id,
            claims=data["claims"],
            feedback=data["feedback"],
            questions=data["questions"],
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(ReviewTable).where(
                    ReviewTable.review_id == review_id,
                    ReviewTable.owner_id == owner_id,
                )
            )
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
