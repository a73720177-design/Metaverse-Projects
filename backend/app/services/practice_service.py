import asyncio
import base64
import html
import logging
import re
from uuid import UUID

from app.integrations.llm.contracts import ReviewGenerator, ReviewGeneratorError
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.practice import (
    ExpectedQuestion,
    ExpectedQuestionRequest,
    ExpectedQuestionResponse,
    PersonaQuestionResult,
)
from app.models.review import ReviewSource
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.services.rag_service import DocumentContextSelector, combine_document_contexts
from app.services.vector_rag import VectorRag, vector_enabled


logger = logging.getLogger(__name__)


class PracticeResourceNotFoundError(RuntimeError):
    pass


class PracticeServiceError(RuntimeError):
    pass


_QUESTION_PREFIX = re.compile(
    r"^(?:q(?:uestion)?|질문)(?:\s*\d+)?\s*[:.)-]?\s*", re.IGNORECASE
)
_PLACEHOLDER = re.compile(r"^(?:q(?:uestion)?|질문)\s*\d*\s*[:.)-]?\s*(?:\.{3,})?$", re.IGNORECASE)
_FORBIDDEN_SCRIPT = re.compile(r"[\u0400-\u04ff\u3040-\u30ff]")
_QUANTITY = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|퍼센트|명|개|분|시간|원|만원|억원|년|개월|회)")
_QUESTION_TERMS = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _usable_question(value: object) -> str | None:
    # Structured-output drift must not become a visible Python-dict question.
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or _PLACEHOLDER.fullmatch(raw) or _FORBIDDEN_SCRIPT.search(raw):
        return None
    cleaned = _QUESTION_PREFIX.sub("", raw).strip()
    if len(cleaned) < 12 or cleaned in {"...", "…"}:
        return None
    return cleaned


def _supported_quantities(question: str, source_text: str) -> bool:
    source_quantities = {re.sub(r"\s+", "", item) for item in _QUANTITY.findall(source_text)}
    return all(
        re.sub(r"\s+", "", item) in source_quantities
        for item in _QUANTITY.findall(question)
    )


def _too_similar(question: str, accepted: list[str]) -> bool:
    terms = set(_QUESTION_TERMS.findall(question.lower()))
    for previous in accepted:
        other = set(_QUESTION_TERMS.findall(previous.lower()))
        union = terms | other
        if union and len(terms & other) / len(union) >= 0.65:
            return True
    return False


def _fallback_questions(persona, documents, count: int) -> list[str]:
    filenames = ", ".join(document.filename for document in documents[:3])
    topic = filenames or "제공된 발표 자료"
    focus = persona.description.strip() or persona.role
    evidence = []
    for document in documents:
        normalized = " ".join(document.full_text.split())
        if normalized:
            evidence.append((document.filename, normalized[:80]))
    while len(evidence) < 3:
        evidence.append((topic, "자료에서 제시한 핵심 주장"))
    first, second, third = evidence[:3]
    candidates = [
        f"{persona.name}의 {focus} 관점에서 {first[0]}의 「{first[1]}」 내용을 뒷받침하는 측정 근거는 무엇입니까?",
        f"{persona.name}의 평가 기준으로 {second[0]}의 「{second[1]}」 내용을 실제 환경에서 검증하는 방법은 무엇입니까?",
        f"{third[0]}의 「{third[1]}」 제안이 기존 대안보다 낫다고 판단할 비교 기준은 무엇입니까?",
        f"{topic}에서 제시한 방법의 실행 과정에서 {focus}와 관련된 가장 큰 위험과 대응 방안은 무엇입니까?",
        f"{persona.name} 관점에서 현재 자료에 근거가 부족한 부분과 이를 보완할 추가 자료는 무엇입니까?",
        f"{focus} 기준으로 예상 성과가 나오지 않을 때 원인을 구분할 핵심 지표는 무엇입니까?",
        f"{persona.name}이 이 발표의 주장을 재현하기 위해 추가로 확인해야 할 조건은 무엇입니까?",
        f"{focus} 관점에서 실제 사용자 적용 시 발생할 수 있는 부작용을 어떻게 검증할 계획입니까?",
        f"{persona.name}의 판단을 바꿀 수 있는 반대 근거나 실패 조건은 무엇입니까?",
        f"{focus} 기준으로 확장 단계의 비용과 품질 우선순위를 어떻게 결정할 계획입니까?",
    ]
    return candidates[:count]


def _avatar_data_url(name: str, role: str, gender: str, age: int | None) -> str:
    label = html.escape((name.strip() or role.strip() or "AI")[:2])
    hue = sum(ord(char) for char in f"{name}:{role}:{gender}:{age}") % 360
    hair = {
        "male": '<path d="M48 58c3-30 61-38 67 3-18-13-45-15-67-3" fill="#24202b"/>',
        "female": '<path d="M44 73c-5-48 77-57 75 2l-7 42-13-18c17-48-53-46-38 0l-13 18z" fill="#302535"/>',
        "other": '<path d="M45 65c7-35 62-39 72-3-22-8-48-7-72 3" fill="#332944"/>',
        "unspecified": '<path d="M48 60c9-27 55-31 66 0-23-9-44-9-66 0" fill="#2b2932"/>',
    }[gender]
    age_marks = "" if age is None or age < 45 else '<path d="M58 77h10M92 77h10M67 101c8 4 18 4 26 0" stroke="white" stroke-opacity=".36" stroke-width="2" fill="none"/>'
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">'
        f'<defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="hsl({hue} 72% 60%)"/>'
        f'<stop offset="1" stop-color="hsl({(hue + 55) % 360} 72% 42%)"/></linearGradient></defs>'
        '<rect width="160" height="160" rx="80" fill="url(#g)"/>'
        f'{hair}'
        '<circle cx="80" cy="61" r="29" fill="white" fill-opacity=".28"/>'
        f'{age_marks}'
        '<path d="M32 139c7-31 25-46 48-46s41 15 48 46" fill="white" fill-opacity=".23"/>'
        f'<text x="80" y="91" text-anchor="middle" font-family="sans-serif" font-size="34" '
        f'font-weight="700" fill="white">{label}</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class PracticeService:
    def __init__(
        self,
        generator: ReviewGenerator,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
        max_concurrent_personas: int = 1,
    ) -> None:
        if max_concurrent_personas < 1:
            raise ValueError("max_concurrent_personas must be at least 1")
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.max_concurrent_personas = max_concurrent_personas

    async def generate_expected_questions(
        self, request: ExpectedQuestionRequest, owner_id: UUID
    ) -> ExpectedQuestionResponse:
        personas = await asyncio.gather(*(
            self.agent_repository.get(persona_id, owner_id)
            for persona_id in request.persona_ids
        ))
        if any(persona is None for persona in personas):
            raise PracticeResourceNotFoundError("선택한 페르소나를 찾을 수 없습니다.")

        presentation_documents = await asyncio.gather(*(
            self.document_repository.get(document_id, owner_id)
            for document_id in request.presentation_document_ids
        ))
        if any(document is None for document in presentation_documents):
            raise PracticeResourceNotFoundError("선택한 발표 자료를 찾을 수 없습니다.")

        # Match outgoing HTTP concurrency to the LLM's real generation slots.
        # Otherwise queued requests consume their timeout before generation starts.
        generation_slots = asyncio.Semaphore(self.max_concurrent_personas)

        async def generate_for_persona(persona) -> PersonaQuestionResult:
            reference_documents = await asyncio.gather(*(
                self.document_repository.get(document_id, owner_id)
                for document_id in persona.document_ids
            ))
            valid_references = [item for item in reference_documents if item is not None]
            blocks: list[str] = []
            sections: list[DocumentSection] = []
            sources: list[ReviewSource] = []
            index = 1
            for scope, documents in (
                ("발표 자료", presentation_documents),
                ("질문자 참고자료", valid_references),
            ):
                for document in documents:
                    text = document.full_text.strip()
                    if not text:
                        continue
                    block = f"[{scope}: {document.filename}]\n{text}"
                    blocks.append(block)
                    sections.append(DocumentSection(index=index, text=block))
                    sources.append(
                        ReviewSource(
                            document_id=document.document_id,
                            filename=document.filename,
                            excerpt=text[:500],
                        )
                    )
                    index += 1
            instructions = (
                f"예상 질문을 {request.question_count_per_persona}개 생성하세요. "
                "발표 자료는 검토 대상이고 질문자 참고자료는 평가 관점의 근거입니다. "
                "두 종류를 혼동하지 말고 질문자가 실제로 물을 법한 질문을 작성하세요."
            )
            combined = "\n\n".join(blocks)
            # The LLM service performs the final token-aware trim. This first
            # guard prevents an unbounded HTTP payload when many files exist.
            combined = combined[:80_000]
            synthetic = DocumentParseResponse(
                document_id=presentation_documents[0].document_id,
                filename="발표 프로젝트 통합 자료",
                document_type="collection",
                saved_path=presentation_documents[0].saved_path,
                sections=sections,
                full_text=combined,
            )
            all_documents = [*presentation_documents, *valid_references]
            retrieval_query = " ".join(
                value
                for value in (
                    persona.role,
                    persona.description,
                    instructions,
                )
                if value and value.strip()
            )
            # Persona reference material is the strongest signal that makes a
            # professor, investor and technical reviewer retrieve different
            # presentation evidence. Keep the query bounded for embedding.
            reference_signal = "\n".join(
                document.full_text[:1200]
                for document in valid_references
                if document.full_text.strip()
            )[:2400]
            if reference_signal:
                retrieval_query = f"{retrieval_query}\n{reference_signal}"
            retrieved = None
            if vector_enabled():
                try:
                    vector_rag = VectorRag()
                    if await vector_rag.has_complete_index(all_documents, owner_id):
                        retrieved = await vector_rag.select_context(
                            all_documents, retrieval_query, owner_id
                        )
                    else:
                        logger.info(
                            "Expected-question vector index is incomplete; using bounded overview"
                        )
                except Exception:
                    logger.warning(
                        "Expected-question vector search failed; using lexical document context",
                        exc_info=True,
                    )
            if retrieved is not None:
                presentation_ids = {
                    document.document_id for document in presentation_documents
                }
                labelled_sections = []
                for section in retrieved.sections:
                    source_id = section.source_document_id
                    scope = "발표 자료" if source_id in presentation_ids else "질문자 참고자료"
                    filename = section.source_filename or retrieved.filename
                    labelled_sections.append(section.model_copy(update={
                        "text": f"[{scope}: {filename}]\n{section.text}"
                    }))
                synthetic = retrieved.model_copy(update={
                    "sections": labelled_sections,
                    "full_text": "\n\n".join(section.text for section in labelled_sections),
                })
            else:
                # 예상 질문은 특정 사실 검색이 아니라 발표 전체 개요 작업이다.
                # 파일별로 예산을 공정하게 나눠 긴 첫 발표자료가 뒤쪽의 대본과
                # 질문자 참고자료를 밀어내지 않게 한다. 이전에는 모든 파일을
                # 하나의 synthetic 문서로 먼저 합쳐 첫 대형 PDF만 남았다.
                selector = DocumentContextSelector()
                synthetic = combine_document_contexts(
                    all_documents, selector.max_context_chars
                )
                if synthetic is not None:
                    presentation_ids = {
                        document.document_id for document in presentation_documents
                    }
                    labelled_sections = [
                        section.model_copy(update={
                            "text": (
                                "[발표 자료: "
                                if section.source_document_id in presentation_ids
                                else "[질문자 참고자료: "
                            )
                            + f"{section.source_filename or synthetic.filename}]\n"
                            + section.text
                        })
                        for section in synthetic.sections
                    ]
                    synthetic = synthetic.model_copy(update={
                        "sections": labelled_sections,
                        "full_text": "\n\n".join(
                            section.text for section in labelled_sections
                        ),
                    })
            if synthetic is None:
                raise PracticeServiceError(
                    "발표 자료에서 질문 생성에 사용할 텍스트를 찾을 수 없습니다."
                )
            try:
                async with generation_slots:
                    generated = await self.generator.generate(persona, synthetic, instructions)
            except ReviewGeneratorError as exc:
                raise PracticeServiceError("예상 질문 생성에 실패했습니다.") from exc
            unique: list[str] = []
            source_text = "\n".join(document.full_text for document in all_documents)
            for question in generated.get("questions", []):
                normalized = _usable_question(question)
                if (
                    normalized
                    and normalized not in unique
                    and _supported_quantities(normalized, source_text)
                    and not _too_similar(normalized, unique)
                ):
                    unique.append(normalized)
                if len(unique) == request.question_count_per_persona:
                    break
            for question in _fallback_questions(
                persona, all_documents,
                request.question_count_per_persona,
            ):
                if len(unique) == request.question_count_per_persona:
                    break
                if question not in unique:
                    unique.append(question)
            return PersonaQuestionResult(
                persona_id=persona.agent_id,
                persona_name=persona.name,
                persona_role=persona.role,
                avatar_data_url=_avatar_data_url(
                    persona.name, persona.role, persona.gender, persona.age
                ),
                questions=[ExpectedQuestion(question=item, sources=sources) for item in unique],
            )

        results = await asyncio.gather(*(generate_for_persona(persona) for persona in personas))
        return ExpectedQuestionResponse(results=list(results))
