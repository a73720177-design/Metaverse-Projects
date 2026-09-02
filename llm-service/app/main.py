"""
LLM 서비스 API 서버.

실행:
    uvicorn app.main:app --reload --port 8001

사전 조건:
    - Ollama가 로컬에서 실행 중이어야 함 (ollama serve)
    - qwen3:14b 모델이 pull 되어 있어야 함

/extract-concepts, /generate-questions는 Backend의 legacy_questions 호환
모드가 쓰는 임시 API다. /api/v1/personas, /reviews, /chat이 정식 계약이며,
Backend가 legacy_questions에서 v1으로 전환하면 legacy 엔드포인트는 제거한다.
"""

import json
import logging
import math
import os
import re
from typing import TypeVar

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from app.llm_client import (
    LLMError,
    CHAT_MODEL,
    call_llm,
    check_ollama_health,
    stream_llm,
)
from app.prompts import (
    CHAT_PROMPT,
    CONCEPT_EXTRACTION_PROMPT,
    FREE_CHAT_PROMPT,
    PERSONA_GENERATION_PROMPT,
    QUESTION_GENERATION_PROMPT,
    REVIEW_GENERATION_PROMPT,
)
from app.schemas import (
    ConceptExtractionRequest,
    ConceptExtractionResponse,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)
from app.schemas_v1 import (
    ChatGenerationRequest,
    ChatGenerationResponse,
    PersonaGenerationRequest,
    PersonaGenerationResponse,
    PersonaProfileIn,
    ReviewGenerationRequest,
    ReviewGenerationResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

app = FastAPI(
    title="LLM Service",
    description="발표 자료/대본 기반 개념 추출 및 비판 질문 생성 API",
    version="0.1.0",
)

# response_schema로 구조화 출력을 강제해도, Ollama 버전에 따라 강제가 안 통하는
# 경우를 대비한 방어적 처리로 코드펜스 제거는 남겨둔다.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


def _build_concept_prompt(paper_text: str) -> str:
    return CONCEPT_EXTRACTION_PROMPT.format(paper_text=paper_text)


def _build_question_prompt(request: QuestionGenerationRequest) -> str:
    concepts_json = json.dumps(
        [c.model_dump() for c in request.concepts], ensure_ascii=False
    )
    return QUESTION_GENERATION_PROMPT.format(
        critical_points=request.critical_points,
        concepts_json=concepts_json,
        script_text=request.script_text,
    )


def _call_llm_as_json(
    prompt: str, response_schema: dict, max_tokens: int | None = None
) -> dict:
    try:
        raw = call_llm(
            prompt, response_schema=response_schema, max_tokens=max_tokens
        )
    except LLMError:
        # 내부 호스트 주소 등 민감할 수 있는 세부 정보는 서버 로그에만 남기고,
        # 클라이언트에는 일반화된 메시지만 반환한다.
        logger.exception("Ollama 호출 실패")
        raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")

    cleaned = _CODE_FENCE_RE.sub("", raw).strip()
    try:
        data, _end = json.JSONDecoder().raw_decode(cleaned)
        if not isinstance(data, dict):
            raise json.JSONDecodeError("root is not an object", cleaned, 0)
        return data
    except json.JSONDecodeError:
        # 모델 원본 출력 전체를 로그에 남기지 않는다 (문서 내용이 섞여 있을 수 있음).
        logger.error("LLM 응답이 JSON 형식이 아님 (길이=%d)", len(raw))
        raise HTTPException(status_code=502, detail="LLM 응답을 해석할 수 없습니다.")


def _generate(
    prompt: str, response_model: type[T], max_tokens: int | None = None
) -> T:
    data = _call_llm_as_json(
        prompt, response_model.model_json_schema(), max_tokens=max_tokens
    )
    try:
        return response_model.model_validate(data)
    except ValidationError:
        logger.error("%s 응답 스키마 불일치", response_model.__name__)
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")


def _call_llm_as_text(
    prompt: str, *, model: str | None = None, max_tokens: int | None = None
) -> str:
    try:
        answer = call_llm(prompt, model=model, max_tokens=max_tokens).strip()
    except LLMError:
        logger.exception("Ollama 채팅 호출 실패")
        raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")
    if not answer:
        raise HTTPException(status_code=502, detail="LLM이 빈 답변을 반환했습니다.")
    return answer


@app.post("/extract-concepts", response_model=ConceptExtractionResponse)
def extract_concepts(request: ConceptExtractionRequest) -> ConceptExtractionResponse:
    return _generate(_build_concept_prompt(request.paper_text), ConceptExtractionResponse)


@app.post("/generate-questions", response_model=QuestionGenerationResponse)
def generate_questions(request: QuestionGenerationRequest) -> QuestionGenerationResponse:
    return _generate(_build_question_prompt(request), QuestionGenerationResponse)


def _persona_json(persona: PersonaProfileIn) -> str:
    return json.dumps(persona.model_dump(mode="json"), ensure_ascii=False)


def _build_persona_prompt(request: PersonaGenerationRequest) -> str:
    return PERSONA_GENERATION_PROMPT.format(
        name=request.name, description=request.description
    )


def _build_review_prompt(request: ReviewGenerationRequest) -> str:
    return REVIEW_GENERATION_PROMPT.format(
        persona_json=_persona_json(request.persona),
        filename=request.document.filename,
        full_text=request.document.full_text,
        instructions=request.instructions or "(없음)",
    )


def _build_chat_prompt(request: ChatGenerationRequest) -> str:
    document_block = (
        f"파일명: {request.document.filename}\n{request.document.full_text}"
        if request.document is not None
        else "(제공된 문서 없음)"
    )
    return CHAT_PROMPT.format(
        persona_json=_persona_json(request.persona),
        document_block=document_block,
        message=request.message,
        answer_guidance=_answer_guidance(request.max_output_tokens),
    )


v1_router = APIRouter(prefix="/api/v1")


@v1_router.get("/health")
def health_check_v1():
    """Backend가 LLM 서비스와 Ollama 상태를 확인할 때 호출.

    정식 서비스 계약에 따라 이 프로세스뿐 아니라 Ollama 연결까지 확인한다.
    legacy `/health`는 프로세스 생존만 확인하는 단순 버전으로 남겨둔다.
    """
    if not check_ollama_health():
        raise HTTPException(status_code=503, detail="Ollama에 연결할 수 없습니다.")
    return {"status": "ok"}


@v1_router.post("/personas", response_model=PersonaGenerationResponse)
def generate_persona(request: PersonaGenerationRequest) -> PersonaGenerationResponse:
    return _generate(
        _build_persona_prompt(request), PersonaGenerationResponse, max_tokens=512
    )


_DOCUMENT_TOPIC_MARKERS = (
    "발표", "자료", "문서", "슬라이드", "첨부", "내용", "주장", "근거",
    "평가", "요약", "분석", "페이지", "개선", "질문", "document", "slide",
    "presentation", "evidence", "source", "summary",
)
_FREE_CHAT_MARKERS = (
    "안녕", "반가", "고마", "너는 누구", "넌 누구", "정체가", "날씨", "농담",
    "hello", "thank", "who are you", "weather", "tell me a joke",
)


def _is_off_topic(request: ChatGenerationRequest) -> bool:
    """Classify obvious cases locally so chat latency does not double."""
    message = " ".join(request.message.lower().split())
    has_document_topic = any(marker in message for marker in _DOCUMENT_TOPIC_MARKERS)
    if request.document is not None:
        if has_document_topic:
            return False
        if any(marker in message for marker in _FREE_CHAT_MARKERS):
            return True
        # With selected context, ambiguous questions should stay grounded.
        return False
    # Without a document, explicit presentation questions retain the evaluator
    # prompt while everything else uses concise free conversation.
    return not has_document_topic


def _build_effective_chat_prompt(request: ChatGenerationRequest) -> str:
    if not _is_off_topic(request):
        return _build_chat_prompt(request)
    return FREE_CHAT_PROMPT.format(
        persona_json=_persona_json(request.persona),
        message=request.message,
        answer_guidance=_answer_guidance(request.max_output_tokens),
    )


def _answer_guidance(max_output_tokens: int) -> str:
    if max_output_tokens <= 512:
        return "핵심 결론을 먼저 말하고 1~3문장 안에서 답하세요."
    if max_output_tokens <= 1024:
        return "핵심 결론과 이유를 나누어 설명하되 불필요한 반복 없이 답하세요."
    return (
        "핵심 결론, 문서 근거, 개선 제안 순서로 충분히 설명하세요. "
        "내용이 끝나면 최대 길이를 채우지 말고 즉시 종료하세요."
    )


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.") from exc
    if value < 1:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.")
    return value


def _fit_chat_context(request: ChatGenerationRequest) -> ChatGenerationRequest:
    """Reserve output/KV budget and trim only retrieved document context."""
    if request.document is None:
        return request

    max_model_len = _positive_env_int("LLM_MAX_MODEL_LEN", 8192)
    safety_tokens = _positive_env_int("LLM_CONTEXT_SAFETY_TOKENS", 512)
    try:
        chars_per_token = float(os.getenv("LLM_APPROX_CHARS_PER_TOKEN", "2.0"))
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail="LLM_APPROX_CHARS_PER_TOKEN 설정이 올바르지 않습니다."
        ) from exc
    if chars_per_token <= 0:
        raise HTTPException(
            status_code=500, detail="LLM_APPROX_CHARS_PER_TOKEN 설정이 올바르지 않습니다."
        )

    input_budget = max_model_len - request.max_output_tokens - safety_tokens
    if input_budget < 256:
        raise HTTPException(
            status_code=422,
            detail="출력 길이가 모델 컨텍스트에 비해 너무 큽니다.",
        )

    empty_document = request.document.model_copy(update={"full_text": ""})
    base_request = request.model_copy(update={"document": empty_document})
    base_tokens = math.ceil(len(_build_effective_chat_prompt(base_request)) / chars_per_token)
    available_document_tokens = input_budget - base_tokens
    if available_document_tokens < 1:
        raise HTTPException(
            status_code=422,
            detail="질문과 페르소나가 모델 컨텍스트 한도를 초과했습니다.",
        )

    max_document_chars = max(1, math.floor(available_document_tokens * chars_per_token))
    if len(request.document.full_text) <= max_document_chars:
        return request
    trimmed_document = request.document.model_copy(
        update={"full_text": request.document.full_text[:max_document_chars]}
    )
    return request.model_copy(update={"document": trimmed_document})


@v1_router.post("/reviews", response_model=ReviewGenerationResponse)
def generate_review(request: ReviewGenerationRequest) -> ReviewGenerationResponse:
    return _generate(
        _build_review_prompt(request), ReviewGenerationResponse, max_tokens=2048
    )


@v1_router.post("/chat", response_model=ChatGenerationResponse)
def generate_chat(request: ChatGenerationRequest) -> ChatGenerationResponse:
    # Chat sources are selected and attached by Backend, which already owns
    # document retrieval. Avoid JSON-schema generation here: on CPU Ollama it
    # can consume the full output budget even for a one-line answer.
    effective_request = _fit_chat_context(request)
    return ChatGenerationResponse(
        answer=_call_llm_as_text(
            _build_effective_chat_prompt(effective_request),
            model=CHAT_MODEL,
            max_tokens=request.max_output_tokens,
        ),
        sources=[],
    )


@v1_router.post("/chat/stream")
def stream_chat(request: ChatGenerationRequest) -> StreamingResponse:
    effective_request = _fit_chat_context(request)

    def events():
        try:
            for token in stream_llm(
                _build_effective_chat_prompt(effective_request),
                model=CHAT_MODEL,
                max_tokens=request.max_output_tokens,
            ):
                data = json.dumps({"token": token}, ensure_ascii=False)
                yield f"event: token\ndata: {data}\n\n"
            yield "event: done\ndata: {}\n\n"
        except LLMError:
            logger.exception("Ollama 채팅 스트리밍 실패")
            data = json.dumps({"message": "LLM 서버에 연결할 수 없습니다."}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(v1_router)
