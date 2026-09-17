from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.review import ReviewCreateRequest, ReviewResult, ClaimVerdict
from app.services.source_evidence import verified_sources
from app.services.practice_service import _usable_question, _supported_quantities, _evidence_terms, _too_similar
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
                persona, document, request.instructions, request.model
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
        self._verify_review(review, document)
        await self.repository.save(review, owner_id)
        return review

    @staticmethod
    def _verify_review(review, document):
        warnings = []
        for claim in review.claims:
            original_count = len(claim.sources)
            claim.sources = verified_sources(claim.sources, document)
            if len(claim.sources) != original_count:
                warnings.append("원문과 일치하지 않는 주장 인용을 제거했습니다.")
            if (not claim.sources or not _supported_quantities(
                    claim.claim, "\n".join(s.excerpt for s in claim.sources))) and claim.verdict != ClaimVerdict.NOT_VERIFIABLE:
                claim.verdict = ClaimVerdict.INSUFFICIENT_EVIDENCE
                claim.confidence = 0
                warnings.append("유효한 인용이 없거나 수치가 일치하지 않는 주장은 근거 부족으로 처리했습니다.")
        for kind in ("positive", "negative"):
            sources = verified_sources(getattr(review.feedback, kind + "_sources"), document)
            setattr(review.feedback, kind + "_sources", sources)
            if not sources:
                setattr(review.feedback, kind, "원문 인용을 확인할 수 없어 이 항목의 평가를 보류했습니다.")
                warnings.append("근거를 확인하지 못한 피드백을 보류했습니다.")
            elif not _supported_quantities(getattr(review.feedback, kind),
                                          "\n".join(s.excerpt for s in sources)):
                setattr(review.feedback, kind, "인용에 없는 수치가 포함되어 이 항목의 평가를 보류했습니다.")
                warnings.append("인용으로 확인되지 않는 수치를 포함한 피드백을 보류했습니다.")
        body = "\n".join(s.text for s in document.sections) or document.full_text
        accepted = []
        for value in review.questions:
            question = _usable_question(value)
            if (question and _evidence_terms(question).intersection(_evidence_terms(body))
                    and _supported_quantities(question, body) and not _too_similar(question, accepted)):
                accepted.append(question)
        if len(accepted) != len(review.questions):
            warnings.append("원문과 연결되지 않거나 수치가 맞지 않는 질문·중복 질문을 제외했습니다.")
        review.questions = accepted
        review.feedback.verification_warnings = list(dict.fromkeys(warnings))
        review.feedback.source_check_performed = True

    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None:
        return await self.repository.get(review_id, owner_id)
