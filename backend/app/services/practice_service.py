import asyncio
import logging
import re
from uuid import UUID
from app.models.coverage import Coverage
from app.services.content_budget import assess_content
from app.services.source_evidence import select_excerpts
from app.models.practice import PracticeSession
from app.repositories.practice_repository import InMemoryPracticeRepository

from app.integrations.llm.contracts import QuestionGenerator, ReviewGeneratorError
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
_GENERIC_QUESTION_PREFIXES = (
    "발표", "자료", "내용", "본문", "질문", "답변", "설명", "근거", "검증",
    "방법", "이유", "과정", "결과", "계획", "목표", "성과", "프로젝트",
    "부분", "사항", "관련", "관점", "의견", "생각", "구체", "실제", "전체",
    "무엇", "어떻", "어떤", "왜", "한계", "위험", "문제", "개선", "차별",
    "사용자", "고객", "서비스", "기술", "전략",
)
_GENERIC_WORD_SUFFIXES = {
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "으로", "로",
    "와", "과", "도", "만", "한", "하는", "하고", "된", "되는", "해", "해서",
    "적인", "적으로", "입니까", "인가요", "인가", "일까요", "습니까", "나요", "까요", "게",
}


def _evidence_terms(text: str) -> set[str]:
    # Korean particles must not make “전환율의” unrelated to source “전환율”.
    terms = set(_QUESTION_TERMS.findall(text.lower()))
    return terms | {re.sub(r"(?:에서|으로|은|는|이|가|을|를|의|에)$", "", word)
                    for word in terms if len(word) >= 3}


def _usable_question(value: object) -> str | None:
    # Structured-output drift must not become a visible Python-dict question.
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or _PLACEHOLDER.fullmatch(raw) or _FORBIDDEN_SCRIPT.search(raw):
        return None
    cleaned = _QUESTION_PREFIX.sub("", raw).strip()
    # Small models occasionally emit a valid Korean interrogative with a full
    # stop. Normalise that punctuation instead of discarding the whole item.
    if cleaned.endswith(".") and re.search(
        r"(?:습니까|입니까|인가요|나요|까요|무엇인가요|어떻게인가요)\.$", cleaned
    ):
        cleaned = cleaned[:-1] + "?"
    if len(cleaned) < 12 or cleaned in {"...", "…"} or not cleaned.endswith(("?", "？")):
        return None
    return cleaned[:-1] + "?" if cleaned.endswith("？") else cleaned


def _specific_evidence_terms(question: str, source_text: str, filenames: list[str]) -> set[str]:
    """Return source-backed anchors after removing generic wording and filenames."""
    filename_terms = set().union(*(_evidence_terms(name) for name in filenames))
    shared = _evidence_terms(question).intersection(_evidence_terms(source_text))

    def generic(term: str) -> bool:
        return any(
            term == base or (
                term.startswith(base)
                and term[len(base):] in _GENERIC_WORD_SUFFIXES
            )
            for base in _GENERIC_QUESTION_PREFIXES
        )

    return {
        term for term in shared
        if term not in filename_terms
        and not generic(term)
    }


def _supported_quantities(question: str, source_text: str) -> bool:
    source_quantities = {re.sub(r"\s+", "", item) for item in _QUANTITY.findall(source_text)}
    return all(
        re.sub(r"\s+", "", item) in source_quantities
        for item in _QUANTITY.findall(question)
    )


def _too_similar(question: str, accepted: list[str], *, threshold: float = 0.65) -> bool:
    terms = set(_QUESTION_TERMS.findall(question.lower()))
    for previous in accepted:
        other = set(_QUESTION_TERMS.findall(previous.lower()))
        union = terms | other
        if union and len(terms & other) / len(union) >= threshold:
            return True
    return False


class PracticeService:
    def __init__(
        self,
        generator: QuestionGenerator,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
        max_concurrent_personas: int = 1,
        session_repository=None,
    ) -> None:
        if max_concurrent_personas < 1:
            raise ValueError("max_concurrent_personas must be at least 1")
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.max_concurrent_personas = max_concurrent_personas
        self.session_repository = session_repository or InMemoryPracticeRepository()

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

        async def generate_for_persona(persona) -> PersonaQuestionResult:
            reference_documents = await asyncio.gather(*(
                self.document_repository.get(document_id, owner_id)
                for document_id in persona.document_ids
            ))
            valid_references = [item for item in reference_documents if item is not None]
            instructions = (
                f"예상 질문은 최대 {request.question_count_per_persona}개이며, "
                "가능하면 요청한 개수를 서로 다른 질문으로 모두 채우세요. "
                "발표 자료는 검토 대상이고 질문자 참고자료는 평가 관점의 근거입니다. "
                "두 종류를 혼동하지 말고 질문자가 실제로 물을 법한 질문을 작성하세요. "
                "'근거가 무엇입니까', '방법을 설명해 주세요' 같은 범용 질문은 제외하고, "
                "각 질문에 발표 근거의 고유 용어·수치·대상·방법명을 직접 넣으세요."
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
                sampled = []
                for document in all_documents:
                    share = selector.max_context_chars // max(1, len(all_documents))
                    budget = max(1, share - min(600, share // 3))
                    sampled.append(document.model_copy(update={"sections":
                        select_excerpts(document, budget, retrieval_query)}))
                synthetic = combine_document_contexts(sampled, selector.max_context_chars)
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

            presentation_ids = {d.document_id for d in presentation_documents}
            evidence = {f"e{i}": section for i, section in enumerate(synthetic.sections, 1)
                        if section.source_document_id in presentation_ids}
            if not evidence:
                raise PracticeServiceError("선택한 발표 자료에 질문 생성에 사용할 텍스트가 없습니다.")
            questions: list[ExpectedQuestion] = []
            accepted_for_persona: list[str] = []
            rejected_questions: list[str] = []
            warnings = list(persona.warnings)
            # The selected context is deliberately bounded for the LLM, but it
            # must not also lower the requested count. Assess the complete
            # presentation; persona reference documents do not fund questions.
            presentation_texts: list[str] = []
            for document in presentation_documents:
                section_texts = [
                    section.text for section in document.sections if section.text.strip()
                ]
                presentation_texts.extend(
                    section_texts or ([document.full_text] if document.full_text.strip() else [])
                )
            assessment = assess_content(presentation_texts, max_output=10)
            requested_count = request.question_count_per_persona
            count = min(requested_count, assessment.output_limit)
            if count < requested_count:
                warnings.append(f"중복을 제외한 발표 근거의 내용량에 따라 질문 상한을 {requested_count}개에서 {count}개로 조정했습니다.")
            def accept(text, ids, focus, origin):
                question = _usable_question(text)
                if not question or len(question) > 500 or not ids or any(key not in evidence for key in ids):
                    return False
                sections = [evidence[key] for key in dict.fromkeys(ids)]
                body = "\n".join(section.text.split("\n", 1)[-1] for section in sections)
                filenames = [section.source_filename or synthetic.filename for section in sections]
                if not _specific_evidence_terms(question, body, filenames) and not _QUANTITY.search(question):
                    return False
                normalized = question
                for p in personas:
                    normalized = normalized.replace(p.name, "")
                if not _supported_quantities(question, body):
                    return False
                # Questions from one presentation naturally share core terms.
                # A higher threshold removes near-copies without discarding
                # distinct concerns that use the same source-specific anchor.
                if _too_similar(normalized, accepted_for_persona, threshold=0.82):
                    return False
                sources = [ReviewSource(document_id=section.source_document_id,
                    filename=section.source_filename or synthetic.filename,
                    page=section.index if section.source_document_type in {"pdf", "pptx"} else None,
                    excerpt=section.text.split("\n", 1)[-1][:500]) for section in sections]
                questions.append(ExpectedQuestion(question=question, sources=sources, focus=focus[:150], origin=origin))
                accepted_for_persona.append(normalized)
                return True

            # Three bounded attempts let the model replace candidates rejected
            # for invalid evidence, generic wording or duplication. On retries,
            # request a small surplus without exceeding the wire contract.
            for attempt in range(3 if count else 0):
                remaining = count - len(questions)
                candidate_count = min(10, remaining + min(3, len(rejected_questions)))
                attempt_instructions = instructions
                if attempt:
                    attempt_instructions += (
                        f" 이전 응답에서 유효 질문이 {len(questions)}개만 남았습니다. "
                        f"제외 질문을 반복하지 말고 남은 {remaining}개 이상을 서로 다른 발표 근거와 관점으로 보완하세요."
                    )
                try:
                    generated = await self.generator.generate(
                        persona, synthetic, attempt_instructions,
                        question_count=candidate_count,
                        excluded_questions=([*accepted_for_persona[-20:], *rejected_questions[-20:]])[-40:],
                        model=request.model,
                    )
                except ReviewGeneratorError:
                    warnings.append("모델 응답을 받지 못했습니다. 잠시 후 다시 생성해 주세요.")
                    break
                for candidate in generated.get("questions", []):
                    if isinstance(candidate, dict):
                        ids = candidate.get("presentation_evidence_ids", [])
                        focus = candidate.get("focus", "")
                        if isinstance(ids, list) and all(isinstance(key, str) for key in ids) and isinstance(focus, str):
                            candidate_text = candidate.get("question")
                            if not accept(candidate_text, ids, focus, "model") and isinstance(candidate_text, str):
                                rejected_questions.append(candidate_text.strip()[:500])
                    if len(questions) == count:
                        break
                if len(questions) == count:
                    break
            if len(questions) < requested_count:
                warnings.append("근거가 확인되고 중복되지 않는 질문만 제공했습니다. 구체적인 주장·검증 결과·사례를 추가하면 질문 범위를 넓힐 수 있습니다.")
            total = sum(len([x for x in d.sections if x.text.strip()]) or bool(d.full_text.strip()) for d in all_documents)
            analyzed = len({(s.source_document_id, s.index) for s in synthetic.sections})
            original_chars = sum(sum(len(s.text) for s in d.sections) or len(d.full_text) for d in all_documents)
            selected_chars = sum(len(s.text.split("\n", 1)[-1]) for s in synthetic.sections)
            if analyzed < total or selected_chars < original_chars:
                warnings.append("전체 원문 중 선택한 발췌만 질문 생성에 사용했습니다. 선택되지 않은 내용은 평가하지 않았습니다.")
            return PersonaQuestionResult(
                persona_id=persona.agent_id, persona_name=persona.name,
                questions=questions, requested_count=requested_count, generated_count=len(questions),
                assessment=assessment,
                status="partial" if len(questions) < requested_count else "complete",
                warnings=warnings,
                coverage=Coverage(total_chunks=total, analyzed_chunks=analyzed,
                    truncated=analyzed < total or selected_chars < original_chars,
                    selection_method="vector" if retrieved else "overview_and_relevance"),
            )

        # Keep result ordering stable while limiting expensive model calls.
        # Each persona owns its question/deduplication state, so concurrent
        # completion order cannot reduce another persona's result count.
        slots = asyncio.Semaphore(self.max_concurrent_personas)

        async def generate_limited(persona) -> PersonaQuestionResult:
            async with slots:
                return await generate_for_persona(persona)

        results = list(await asyncio.gather(*(
            generate_limited(persona) for persona in personas
        )))
        response = ExpectedQuestionResponse(results=results)
        session = PracticeSession(request=request, response=response)
        response.session_id = session.session_id
        await self.session_repository.save(session, owner_id)
        return response

    async def list_sessions(self, owner_id):
        return await self.session_repository.list(owner_id)

    async def get_session(self, session_id, owner_id):
        session = await self.session_repository.get(session_id, owner_id)
        if session is None:
            raise PracticeResourceNotFoundError("연습 기록을 찾을 수 없습니다.")
        active = {p.agent_id for p in await self.agent_repository.list(owner_id, deleted=False)}
        documents = {d.document_id for d in await self.document_repository.list(owner_id)}
        if set(session.request.persona_ids) - active or set(session.request.presentation_document_ids) - documents:
            session.warnings.append("삭제되었거나 휴지통에 있는 질문자·자료는 복구 대상에서 제외했습니다.")
        session.response.results = [r for r in session.response.results if r.persona_id in active]
        for result in session.response.results:
            for question in result.questions:
                question.sources = [source for source in question.sources if source.document_id in documents]
        return session
