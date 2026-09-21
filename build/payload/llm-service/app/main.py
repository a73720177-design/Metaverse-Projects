"""
LLM 서비스 API 서버.

실행:
    uvicorn app.main:app --reload --port 8001

사전 조건:
    - Ollama가 로컬에서 실행 중이어야 함 (ollama serve)
    - qwen3:4b 모델이 pull 되어 있어야 함

API 계약은 /api/v1 하나뿐이다(personas, reviews, practice/questions,
summaries, embeddings, chat). 프리픽스 없는 /health는 프로세스 생존만 보는
헬스체크라 그대로 둔다 — integration/check_services.py가 쓴다.
"""

import json
import logging
import re
from typing import TypeVar

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from app.context_budget import prompt_fits, require_prompt_fits
from app.llm_client import (
    LLMError,
    CHAT_MODEL,
    OLLAMA_REVIEW_MODEL,
    OLLAMA_QUESTION_MODEL,
    OLLAMA_SUMMARY_MODEL,
    OLLAMA_EMBEDDING_MODEL,
    OLLAMA_MAX_OUTPUT_TOKENS,
    embed_texts,
    call_llm,
    check_ollama_health,
    get_runtime_diagnostics,
    stream_llm_async as stream_llm,
)
from app.prompts import (
    build_effective_chat_prompt,
    build_persona_prompt,
    build_review_prompt,
    build_expected_question_prompt,
    build_summary_prompt,
    trim_context_to_chunks,
    retrieved_context_text,
    document_text,
    RAG_CONTEXT_MAX_CHARS,
)
from app.review_pipeline import generate_review_map_reduce, should_use_map_reduce
from app.response_sanitizer import clean_chat_text, extract_json_object, ReasoningFilter, sanitize_payload
from app.summary_pipeline import (
    generate_summary_map_reduce,
    should_use_map_reduce as should_use_summary_map_reduce,
    style_max_tokens,
)
from app.schemas_v1 import (
    ChatGenerationRequest,
    ChatGenerationResponse,
    PersonaGenerationRequest,
    PersonaGenerationResponse,
    ReviewGenerationRequest,
    ReviewGenerationResponse,
    ReviewCoverage,
    ExpectedQuestionGenerationResponse,
    ExpectedQuestionGenerationRequest,
    EmbeddingRequest,
    EmbeddingResponse,
    SummaryGenerationRequest,
    SummaryGenerationResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_HAN_CHARACTER_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]"
)
_LANGUAGE_RETRY_RULE = (
    "\n\n[출력 언어 재확인]\n앞선 결과를 폐기하고 처음부터 다시 작성하세요. "
    "중국어·일본어 문장과 한자 문자를 하나도 사용하지 말고, 고유명사와 "
    "전문 용어는 한글 또는 영문으로 표기하세요. JSON 키와 근거 ID는 그대로 유지하세요."
)
_QUOTED_SOURCE_KEYS = {"sources", "evidence", "excerpt", "reference_context"}

app = FastAPI(
    title="LLM Service",
    description="발표 자료 기반 페르소나/리뷰/요약/채팅 생성 API",
    version="0.1.0",
)

@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


def _call_llm_as_json(
    prompt: str, response_schema: dict, max_tokens: int | None = None,
    model: str | None = None, *, think: bool = False,
) -> dict:
    require_prompt_fits(prompt, max_tokens or OLLAMA_MAX_OUTPUT_TOKENS)
    current_prompt = prompt
    for attempt in range(2):
        try:
            raw = call_llm(
                current_prompt, model=model, response_schema=response_schema,
                max_tokens=max_tokens, think=think,
            )
        except LLMError:
            # 로그와 응답 모두 내부 주소·예외 원문을 제외한다.
            logger.error("Ollama 호출 실패")
            raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")

        try:
            data = sanitize_payload(
                extract_json_object(raw, response_schema.get("required", []))
            )
        except (json.JSONDecodeError, TypeError, AttributeError):
            # 모델 원본 출력 전체를 로그에 남기지 않는다 (문서 내용이 섞여 있을 수 있음).
            if attempt == 0:
                logger.warning("구조화 응답 재시도: JSON 형식 불일치")
                continue
            logger.error("LLM 응답이 JSON 형식이 아님")
            raise HTTPException(status_code=502, detail="LLM 응답을 해석할 수 없습니다.")
        if not _generated_payload_contains_han(data):
            return data
        if attempt == 0:
            current_prompt = prompt + _LANGUAGE_RETRY_RULE
    logger.warning("한자가 포함된 구조화 응답을 재생성 후 차단함")
    raise HTTPException(status_code=502, detail="한국어 응답을 생성하지 못했습니다. 다시 시도하세요.")


def _generate(
    prompt: str, response_model: type[T], max_tokens: int | None = None,
    model: str | None = None, *, think: bool = False,
) -> T:
    data = _call_llm_as_json(
        prompt, response_model.model_json_schema(), max_tokens=max_tokens,
        model=model, think=think,
    )
    try:
        return response_model.model_validate(data)
    except ValidationError:
        logger.error("%s 응답 스키마 불일치", response_model.__name__)
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")


def _call_llm_as_text(
    prompt: str, *, model: str | None = None, max_tokens: int | None = None
) -> str:
    current_prompt = prompt
    for attempt in range(2):
        try:
            raw = call_llm(current_prompt, model=model, max_tokens=max_tokens)
        except LLMError:
            logger.error("Ollama 채팅 호출 실패")
            raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")
        if not isinstance(raw, str):
            raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")
        answer = clean_chat_text(raw)
        if answer and not _contains_chinese_text(answer):
            return answer
        if attempt == 0:
            current_prompt = prompt + _LANGUAGE_RETRY_RULE
    if not answer:
        raise HTTPException(status_code=502, detail="LLM이 빈 답변을 반환했습니다.")
    logger.warning("중국어가 포함된 채팅 응답을 차단함")
    raise HTTPException(status_code=502, detail="한국어 답변을 생성하지 못했습니다. 다시 시도하세요.")


def _contains_chinese_text(value: str) -> bool:
    """Reject Han ideographs so accidental Chinese output never reaches the UI."""
    return _HAN_CHARACTER_RE.search(value) is not None


def _generated_payload_contains_han(value, key: str | None = None) -> bool:
    """Inspect generated prose while leaving quoted source evidence untouched."""
    if key in _QUOTED_SOURCE_KEYS:
        return False
    if isinstance(value, dict):
        return any(_generated_payload_contains_han(item, item_key)
                   for item_key, item in value.items())
    if isinstance(value, list):
        return any(_generated_payload_contains_han(item, key) for item in value)
    return isinstance(value, str) and _contains_chinese_text(value)


async def _collect_validated_stream_answer(
    prompt: str, *, model: str, max_tokens: int,
) -> str:
    """Buffer before SSE emission so rejected language can never leak to the UI."""
    from contextlib import aclosing

    current_prompt = prompt
    last_answer = ""
    for attempt in range(2):
        reasoning = ReasoningFilter()
        visible_parts: list[str] = []
        output_chars = 0
        async with aclosing(stream_llm(
            current_prompt, model=model, max_tokens=max_tokens
        )) as tokens:
            async for token in tokens:
                output_chars += len(token)
                if output_chars > 200_000:
                    raise LLMError("출력 한도 초과")
                visible = reasoning.feed(token)
                if visible:
                    visible_parts.append(visible)
        tail = reasoning.feed("", final=True)
        if tail:
            visible_parts.append(tail)
        last_answer = clean_chat_text("".join(visible_parts))
        if last_answer and not _contains_chinese_text(last_answer):
            return last_answer
        if attempt == 0:
            current_prompt = prompt + _LANGUAGE_RETRY_RULE
    if not last_answer:
        raise LLMError("유효한 답변 없음")
    raise LLMError("한국어 답변 생성 실패")


v1_router = APIRouter(prefix="/api/v1")


@v1_router.get("/health")
def health_check_v1():
    """Backend가 LLM 서비스와 Ollama 상태를 확인할 때 호출.

    정식 서비스 계약에 따라 이 프로세스뿐 아니라 Ollama 연결까지 확인한다.
    프리픽스 없는 `/health`는 프로세스 생존만 확인하는 단순 버전이다.
    """
    if not check_ollama_health():
        raise HTTPException(status_code=503, detail="Ollama에 연결할 수 없습니다.")
    return {"status": "ok"}


@v1_router.get("/diagnostics")
def runtime_diagnostics():
    """Developer status only; never expose provider URLs or credentials."""
    return get_runtime_diagnostics()


@v1_router.post("/personas", response_model=PersonaGenerationResponse)
def generate_persona(request: PersonaGenerationRequest) -> PersonaGenerationResponse:
    # Trait metadata and quoted evidence also consume the JSON output budget.
    while not prompt_fits(build_persona_prompt(request) + _LANGUAGE_RETRY_RULE, 1536):
        if len(request.reference_context) > 160:
            request = request.model_copy(update={"reference_context": request.reference_context[:len(request.reference_context) * 3 // 4]})
        elif len(request.description) > 300:
            request = request.model_copy(update={"description": request.description[:len(request.description) * 3 // 4]})
        else:
            require_prompt_fits(build_persona_prompt(request) + _LANGUAGE_RETRY_RULE, 1536)
    return _generate(
        build_persona_prompt(request), PersonaGenerationResponse, max_tokens=1536,
        model=request.model,
    )


def _fit_chat_context(request: ChatGenerationRequest) -> ChatGenerationRequest:
    """Reserve output budget; discard old history before rejecting current input."""
    # Budget exactly the rendered prompt, including section labels and wrappers.
    # Normalize sections first so the renderer cannot restore text already trimmed.
    if request.document is not None:
        document = request.document.model_copy(update={
            "full_text": retrieved_context_text(request.document), "sections": [],
        })
        request = request.model_copy(update={"document": document})

    def fits(candidate: ChatGenerationRequest) -> bool:
        return prompt_fits(build_effective_chat_prompt(candidate), request.max_output_tokens)

    if fits(request):
        return request
    empty_document = (request.document.model_copy(update={"full_text": ""})
                      if request.document is not None else None)
    while not fits(request.model_copy(update={"document": empty_document})) and request.history:
        request = request.model_copy(update={
            "history": request.history[1:], "history_truncated": True,
        })
    base = request.model_copy(update={"document": empty_document})
    if not fits(base):
        raise HTTPException(status_code=422, detail="질문과 페르소나가 모델 컨텍스트 한도를 초과했습니다.")
    if request.document is None:
        return request

    # Binary search whole-chunk prefixes, checking actual prompt overhead each time.
    text = request.document.full_text
    low, high = 0, min(len(text), RAG_CONTEXT_MAX_CHARS)
    best = base
    while low <= high:
        middle = (low + high) // 2
        document = request.document.model_copy(update={
            "full_text": trim_context_to_chunks(text, middle),
        })
        candidate = request.model_copy(update={"document": document})
        if fits(candidate):
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


@v1_router.post("/reviews", response_model=ReviewGenerationResponse)
def generate_review(request: ReviewGenerationRequest) -> ReviewGenerationResponse:
    if (should_use_map_reduce(document_text(request.document))
            or not prompt_fits(build_review_prompt(request), 1536)):
        return generate_review_map_reduce(
            persona=request.persona,
            document=request.document,
            instructions=request.instructions,
            generate=_generate,
            model=request.model,
        )
    # claims를 3~5개(스키마 상한 20보다 훨씬 보수적으로)로 제한해도, 근거
    # 인용(excerpt)·questions까지 더하면 기존 1024 토큰은 여유가 빠듯해
    # 502(JSON 파싱 실패)로 이어지기 쉬웠다. 1536으로 올려 여유를 둔다.
    response = _generate(
        build_review_prompt(request), ReviewGenerationResponse,
        max_tokens=2048, model=request.model,
    )
    total = len([s for s in request.document.sections if s.text.strip()]) or 1
    return response.model_copy(update={"coverage": ReviewCoverage(
        total_chunks=total, analyzed_chunks=total, truncated=False, selection_method="full")})


def _fit_question_request(request, max_tokens):
    # Exclusions are hints, not evidence. Backend enforces full deduplication.
    # Previously only evidence was reduced, leaving retry hints over budget.
    persona = request.persona.model_copy(update={
        "description": request.persona.description[:500],
        "expertise": [t.model_copy(update={"value": t.value[:160]}) for t in request.persona.expertise[:4]],
        "evaluation_style": [t.model_copy(update={"value": t.value[:160]}) for t in request.persona.evaluation_style[:4]],
    })
    request = request.model_copy(update={
        "persona": persona,
        "excluded_questions": [q[:200] for q in request.excluded_questions[-3:]],
        "instructions": (request.instructions or "")[:600],
    })
    evidence = list(request.evidence)
    while not prompt_fits(build_expected_question_prompt(request.model_copy(update={"evidence": evidence})) + _LANGUAGE_RETRY_RULE, max_tokens):
        if request.excluded_questions:
            request = request.model_copy(update={"excluded_questions": request.excluded_questions[1:]})
            continue
        longest = max(range(len(evidence)), key=lambda i: len(evidence[i].text))
        item = evidence[longest]
        if len(item.text) > 160:
            evidence[longest] = item.model_copy(update={"text": item.text[:len(item.text) // 2] + "\n…(이하 생략)"})
        else:
            # Keep at least one presentation source; never fabricate evidence IDs.
            removable = next((i for i in range(len(evidence) - 1, -1, -1)
                              if evidence[i].scope == "persona_reference"), None)
            if removable is None and sum(e.scope == "presentation" for e in evidence) > 1:
                removable = len(evidence) - 1
            if removable is None:
                require_prompt_fits(build_expected_question_prompt(request.model_copy(update={"evidence": evidence})) + _LANGUAGE_RETRY_RULE, max_tokens)
            evidence.pop(removable)
    return request.model_copy(update={"evidence": evidence})


@v1_router.post("/practice/questions", response_model=ExpectedQuestionGenerationResponse)
def generate_expected_questions(
    request: ExpectedQuestionGenerationRequest,
) -> ExpectedQuestionGenerationResponse:
    if not any(item.scope == "presentation" for item in request.evidence):
        return ExpectedQuestionGenerationResponse(questions=[])
    # Also bound direct API callers; the backend replenishes remaining questions.
    request = request.model_copy(update={"question_count": min(3, request.question_count)})
    max_tokens = 512 + 256 * request.question_count
    fitted = _fit_question_request(request, max_tokens)
    return _generate(
        build_expected_question_prompt(fitted),
        ExpectedQuestionGenerationResponse,
        # Reserve output for the requested count, including evidence IDs and focus.
        max_tokens=max_tokens,
        model=request.model,
    )


@v1_router.post("/summaries", response_model=SummaryGenerationResponse)
def generate_summary(request: SummaryGenerationRequest) -> SummaryGenerationResponse:
    if (should_use_summary_map_reduce(document_text(request.document))
            or not prompt_fits(build_summary_prompt(request), style_max_tokens(request.style))):
        return generate_summary_map_reduce(
            document=request.document,
            style=request.style,
            persona=request.persona,
            generate=_generate,
            model=OLLAMA_SUMMARY_MODEL,
            topic_limit=request.topic_limit,
        )
    response = _generate(
        build_summary_prompt(request), SummaryGenerationResponse,
        max_tokens=style_max_tokens(request.style), model=OLLAMA_SUMMARY_MODEL,
    )
    total = len([s for s in request.document.sections if s.text.strip()]) or 1
    return response.model_copy(update={"key_topics": response.key_topics[:request.topic_limit], "coverage": ReviewCoverage(
        total_chunks=total, analyzed_chunks=total, truncated=False, selection_method="full")})


@v1_router.post("/embeddings", response_model=EmbeddingResponse)
def generate_embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    try:
        embeddings = embed_texts(request.texts)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="임베딩 모델을 사용할 수 없습니다.") from exc
    dimension = len(embeddings[0]) if embeddings else 0
    if dimension == 0 or any(len(vector) != dimension for vector in embeddings):
        logger.error("임베딩 응답의 차원이 일정하지 않음")
        raise HTTPException(status_code=502, detail="임베딩 응답 형식이 올바르지 않습니다.")
    return EmbeddingResponse(
        model=OLLAMA_EMBEDDING_MODEL,
        dimension=dimension,
        embeddings=embeddings,
    )


@v1_router.post("/chat", response_model=ChatGenerationResponse)
def generate_chat(request: ChatGenerationRequest) -> ChatGenerationResponse:
    # Chat sources are selected and attached by Backend, which already owns
    # document retrieval. Avoid JSON-schema generation here: on CPU Ollama it
    # can consume the full output budget even for a one-line answer.
    effective_request = _fit_chat_context(request)
    return ChatGenerationResponse(
        answer=_call_llm_as_text(
            build_effective_chat_prompt(effective_request),
            model=request.model,
            max_tokens=request.max_output_tokens,
        ),
        sources=[],
    )


@v1_router.post("/chat/stream")
async def stream_chat(request: ChatGenerationRequest) -> StreamingResponse:
    effective_request = _fit_chat_context(request)

    async def events():
        try:
            answer = await _collect_validated_stream_answer(
                build_effective_chat_prompt(effective_request),
                model=request.model,
                max_tokens=request.max_output_tokens,
            )
            lines = answer.splitlines(keepends=True) or [answer]
            for line in lines:
                yield "event: token\ndata: " + json.dumps(
                    {"token": line}, ensure_ascii=False
                ) + "\n\n"
            yield "event: done\ndata: {}\n\n"
        except (LLMError, ValueError):
            logger.error("Chat stream failed")
            yield 'event: error\ndata: {"message":"답변 생성에 실패했습니다. 다시 시도해 주세요."}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.include_router(v1_router)
