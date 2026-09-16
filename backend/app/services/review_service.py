from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.review import ReviewCreateRequest, ReviewResult
from app.integrations.llm.contracts import ReviewGenerator, ReviewGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository


class ReviewServiceError(RuntimeError):
    pass


class ReviewSourceUnavailableError(RuntimeError):
    pass


class ReviewResourceNotFoundError(RuntimeError):
    pass


class ReviewService:
    def __init__(
        self,
        generator: ReviewGenerator,
        repository: ReviewRepository,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
    ) -> None:
        self.generator = generator
        self.repository = repository
        self.agent_repository = agent_repository
        self.document_repository = document_repository

    async def create(
        self, agent_id: UUID, request: ReviewCreateRequest, owner_id: UUID
    ) -> ReviewResult:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ReviewResourceNotFoundError("Agent not found")
        document = await self.document_repository.get(request.document_id, owner_id)
        if document is None:
            raise ReviewResourceNotFoundError("Document not found")
        if len(document.sections) > 1000 or len(document.full_text) > 2_000_000:
            raise ReviewSourceUnavailableError("문서 분석 한도(1,000개 구간·200만 자)를 초과했습니다.")
        if not document.full_text.strip():
            raise ReviewSourceUnavailableError("분석할 텍스트가 없습니다. 텍스트를 포함한 자료를 업로드해주세요.")
        try:
            generated = await self.generator.generate(
                persona, document, request.instructions
            )
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
        await self.repository.save(review, owner_id)
        return review

    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None:
        return await self.repository.get(review_id, owner_id)
