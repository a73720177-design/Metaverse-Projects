from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.summary import SummaryCreateRequest, SummaryResult, SummaryStyle
from app.integrations.llm.contracts import SummaryGenerator, SummaryGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.summary_repository import SummaryRepository


class SummaryServiceError(RuntimeError):
    pass


class SummaryResourceNotFoundError(RuntimeError):
    pass


class SummaryService:
    def __init__(
        self,
        generator: SummaryGenerator,
        repository: SummaryRepository,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
    ) -> None:
        self.generator = generator
        self.repository = repository
        self.agent_repository = agent_repository
        self.document_repository = document_repository

    async def create(
        self,
        document_id: UUID,
        request: SummaryCreateRequest,
        owner_id: UUID,
        *,
        refresh: bool = False,
    ) -> SummaryResult:
        document = await self.document_repository.get(document_id, owner_id)
        if document is None:
            raise SummaryResourceNotFoundError("Document not found")
        persona = None
        if request.agent_id is not None:
            persona = await self.agent_repository.get(request.agent_id, owner_id)
            if persona is None:
                raise SummaryResourceNotFoundError("Agent not found")

        existing = await self.repository.find_cached(
            document_id, request.style, request.agent_id, owner_id
        )
        if existing is not None and not refresh:
            return existing

        try:
            generated = await self.generator.generate(document, request.style, persona)
            summary = SummaryResult.model_validate(
                {
                    **generated,
                    "summary_id": existing.summary_id if existing else uuid4(),
                    "document_id": document_id,
                    "agent_id": request.agent_id,
                    "style": request.style,
                }
            )
        except (SummaryGeneratorError, ValidationError) as exc:
            raise SummaryServiceError("Summary generator returned an invalid response") from exc
        await self.repository.save(summary, owner_id)
        return summary

    async def get(self, document_id: UUID, owner_id: UUID) -> SummaryResult | None:
        document = await self.document_repository.get(document_id, owner_id)
        if document is None:
            raise SummaryResourceNotFoundError("Document not found")
        return await self.repository.find_cached(
            document_id, SummaryStyle.BRIEF, None, owner_id
        )
