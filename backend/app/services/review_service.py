from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.document import DocumentParseResponse
from app.models.review import ReviewCreateRequest, ReviewResult
from app.integrations.llm.contracts import (
    DocumentIndexError,
    DocumentIndexer,
    DocumentNotIndexedError,
    ReviewGenerator,
    ReviewGeneratorError,
)
from app.models.persona import PersonaProfile
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository


class ReviewServiceError(RuntimeError):
    pass


class ReviewResourceNotFoundError(RuntimeError):
    pass


class ReviewService:
    """문서 업로드 직후 1회 수행하는 평가입니다.

    자료 검색은 LLM 서비스가 담당하므로 Backend는 소유권을 확인한 document_id만
    넘깁니다.
    """

    def __init__(
        self,
        generator: ReviewGenerator,
        repository: ReviewRepository,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
        indexer: DocumentIndexer | None = None,
    ) -> None:
        self.generator = generator
        self.repository = repository
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.indexer = indexer

    async def create(
        self, agent_id: UUID, request: ReviewCreateRequest, owner_id: UUID
    ) -> ReviewResult:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ReviewResourceNotFoundError("Agent not found")
        document = await self.document_repository.get(request.document_id, owner_id)
        if document is None:
            raise ReviewResourceNotFoundError("Document not found")
        try:
            generated = await self._generate(persona, document, request.instructions)
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

    async def _generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
    ) -> dict:
        try:
            return await self.generator.generate(
                persona, document.document_id, instructions
            )
        except DocumentNotIndexedError:
            # LLM 서비스가 재시작되어 인덱스가 비었을 때만 발생한다. 문서를 다시
            # 밀어넣고 한 번 재시도한다.
            if self.indexer is None:
                raise ReviewServiceError("Document index is unavailable")
            try:
                await self.indexer.index(document)
            except DocumentIndexError as exc:
                raise ReviewServiceError("Document indexing failed") from exc
            return await self.generator.generate(
                persona, document.document_id, instructions
            )

    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None:
        return await self.repository.get(review_id, owner_id)
