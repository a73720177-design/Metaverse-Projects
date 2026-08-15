from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.review import ReviewCreateRequest, ReviewResult
from app.ports.review_generator import ReviewGenerator, ReviewGeneratorError
from app.ports.review_repository import ReviewRepository


class ReviewServiceError(RuntimeError):
    pass


class ReviewService:
    def __init__(self, generator: ReviewGenerator, repository: ReviewRepository) -> None:
        self.generator = generator
        self.repository = repository

    async def create(self, agent_id: UUID, request: ReviewCreateRequest) -> ReviewResult:
        try:
            generated = await self.generator.generate(agent_id, request)
            review = ReviewResult.model_validate(
                {
                    **generated,
                    "review_id": uuid4(),
                    "agent_id": agent_id,
                    "document_id": request.document_id,
                }
            )
        except (ReviewGeneratorError, ValidationError) as exc:
            raise ReviewServiceError("Review generator returned an invalid response") from exc
        await self.repository.save(review)
        return review

    async def get(self, review_id: UUID) -> ReviewResult | None:
        return await self.repository.get(review_id)
