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
    OLLAMA_REVIEW_MODEL,
    OLLAMA_QUESTION_MODEL,
    OLLAMA_SUMMARY_MODEL,
    OLLAMA_EMBEDDING_MODEL,
    embed_texts,
    call_llm,
    check_ollama_health,
    stream_llm,
)
from app.prompts import (
    SUMMARY_GENERATION_PROMPT,
    build_effective_chat_prompt,
    build_persona_prompt,
    build_review_prompt,
    build_expected_question_prompt,
    trim_context_to_chunks,
)
from app.review_pipeline import generate_review_map_reduce, should_use_map_reduce
from app.response_sanitizer import clean_chat_text, extract_json_object, safe_stream, sanitize_payload
from app.summary_pipeline import (
    generate_summary_map_reduce,
    persona_block,
    should_use_map_reduce as should_use_summary_map_reduce,
    style_guidance,
    style_max_tokens,
)
from app.schemas_v1 import (
    ChatGenerationRequest,
    ChatGenerationResponse,
    PersonaGenerationRequest,
    PersonaGenerationResponse,
    ReviewGenerationRequest,
    ReviewGenerationResponse,
    ExpectedQuestionGenerationResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    SummaryGenerationRequest,
    SummaryGenerationResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

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
    try:
        raw = call_llm(
            prompt, model=model, response_schema=response_schema,
            max_tokens=max_tokens, think=think,
        )
    except LLMError:
        # 내부 호스트 주소 등 민감할 수 있는 세부 정보는 서버 로그에만 남기고,
        # 클라이언트에는 일반화된 메시지만 반환한다.
        logger.exception("Ollama 호출 실패")
        raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")

    try:
        return sanitize_payload(extract_json_object(raw, response_schema.get("required", [])))
    except (json.JSONDecodeError, TypeError, AttributeError):
        # 모델 원본 출력 전체를 로그에 남기지 않는다 (문서 내용이 섞여 있을 수 있음).
        logger.error("LLM 응답이 JSON 형식이 아님")
        raise HTTPException(status_code=502, detail="LLM 응답을 해석할 수 없습니다.")


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
            logger.exception("Ollama 채팅 호출 실패")
            raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")
        if not isinstance(raw, str):
            raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")
        answer = clean_chat_text(raw)
        if answer and not _contains_chinese_text(answer):
            return answer
        if attempt == 0:
            current_prompt = (
                prompt
                + "\n\n[출력 언어 재확인]\n중국어 한자를 사용하지 말고 반드시 한국어로만 "
                "최종 답변을 다시 작성하세요."
            )
    if not answer:
        raise HTTPException(status_code=502, detail="LLM이 빈 답변을 반환했습니다.")
    logger.warning("중국어가 포함된 채팅 응답을 차단함")
    raise HTTPException(status_code=502, detail="한국어 답변을 생성하지 못했습니다. 다시 시도하세요.")


def _contains_chinese_text(value: str) -> bool:
    """Reject CJK ideographs so accidental Chinese output never reaches the UI."""
    return re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value) is not None


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


@v1_router.post("/personas", response_model=PersonaGenerationResponse)
def generate_persona(request: PersonaGenerationRequest) -> PersonaGenerationResponse:
    # PERSONA_GENERATION_PROMPT의 개수/길이 상한(전문 분야·평가 스타일 각
    # 2~4개, evidence 1개·60자 이내)이면 512 토큰 안에 충분히 들어온다.
    return _generate(
        build_persona_prompt(request), PersonaGenerationResponse, max_tokens=512
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
    max_model_len = _positive_env_int("LLM_MAX_MODEL_LEN", 8192)
    safety_tokens = _positive_env_int("LLM_CONTEXT_SAFETY_TOKENS", 512)
    try:
        chars_per_token = float(os.getenv("LLM_APPROX_CHARS_PER_TOKEN", "2.0"))
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail="LLM_APPROX_CHARS_PER_TOKEN 설정이 올바르지 않습니다."
        ) from exc
    if not math.isfinite(chars_per_token) or chars_per_token <= 0:
        raise HTTPException(
            status_code=500, detail="LLM_APPROX_CHARS_PER_TOKEN 설정이 올바르지 않습니다."
        )

    input_budget = max_model_len - request.max_output_tokens - safety_tokens
    if input_budget < 256:
        raise HTTPException(
            status_code=422,
            detail="출력 길이가 모델 컨텍스트에 비해 너무 큽니다.",
        )

    empty_document = (
        request.document.model_copy(update={"full_text": "", "sections": []})
        if request.document is not None else None
    )
    base_request = request.model_copy(update={"document": empty_document})
    base_tokens = math.ceil(len(build_effective_chat_prompt(base_request)) / chars_per_token)
    available_document_tokens = input_budget - base_tokens
    if available_document_tokens < 1:
        raise HTTPException(
            status_code=422,
            detail="질문과 페르소나가 모델 컨텍스트 한도를 초과했습니다.",
        )

    if request.document is None:
        return request

    max_document_chars = max(1, math.floor(available_document_tokens * chars_per_token))
    trimmed_full_text = trim_context_to_chunks(request.document.full_text, max_document_chars)
    if trimmed_full_text == request.document.full_text:
        return request
    # sections는 이미 트리밍된 full_text와 어긋나므로 비운다. 전달되는
    # 라벨은 항상 full_text(Backend가 붙였거나 위에서 자른 것) 기준이다.
    trimmed_document = request.document.model_copy(
        update={"full_text": trimmed_full_text, "sections": []}
    )
    return request.model_copy(update={"document": trimmed_document})


@v1_router.post("/reviews", response_model=ReviewGenerationResponse)
def generate_review(request: ReviewGenerationRequest) -> ReviewGenerationResponse:
    if should_use_map_reduce(request.document.full_text):
        return generate_review_map_reduce(
            persona=request.persona,
            document=request.document,
            instructions=request.instructions,
            generate=_generate,
            model=OLLAMA_REVIEW_MODEL,
        )
    # claims를 3~5개(스키마 상한 20보다 훨씬 보수적으로)로 제한해도, 근거
    # 인용(excerpt)·questions까지 더하면 기존 1024 토큰은 여유가 빠듯해
    # 502(JSON 파싱 실패)로 이어지기 쉬웠다. 1536으로 올려 여유를 둔다.
    return _generate(
        build_review_prompt(request), ReviewGenerationResponse,
        max_tokens=1536, model=OLLAMA_REVIEW_MODEL,
    )


@v1_router.post("/practice/questions", response_model=ExpectedQuestionGenerationResponse)
def generate_expected_questions(
    request: ReviewGenerationRequest,
) -> ExpectedQuestionGenerationResponse:
    return _generate(
        build_expected_question_prompt(request),
        ExpectedQuestionGenerationResponse,
        # Five focused questions fit within this budget. Letting CPU-based
        # structured generation run to 1024 caused repetition and timeouts.
        max_tokens=640,
        model=OLLAMA_QUESTION_MODEL,
    )


def _build_summary_prompt(request: SummaryGenerationRequest) -> str:
    return SUMMARY_GENERATION_PROMPT.format(
        persona_block=persona_block(request.persona),
        filename=request.document.filename,
        full_text=request.document.full_text,
        style_guidance=style_guidance(request.style),
    )


@v1_router.post("/summaries", response_model=SummaryGenerationResponse)
def generate_summary(request: SummaryGenerationRequest) -> SummaryGenerationResponse:
    if should_use_summary_map_reduce(request.document.full_text):
        return generate_summary_map_reduce(
            document=request.document,
            style=request.style,
            persona=request.persona,
            generate=_generate,
            model=OLLAMA_SUMMARY_MODEL,
        )
    return _generate(
        _build_summary_prompt(request), SummaryGenerationResponse,
        max_tokens=style_max_tokens(request.style), model=OLLAMA_SUMMARY_MODEL,
    )


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
            tokens = list(safe_stream(stream_llm(
                build_effective_chat_prompt(effective_request),
                model=CHAT_MODEL,
                max_tokens=request.max_output_tokens,
            )))
            if _contains_chinese_text("".join(tokens)):
                tokens = [_call_llm_as_text(
                    build_effective_chat_prompt(effective_request),
                    model=CHAT_MODEL,
                    max_tokens=request.max_output_tokens,
                )]
            emitted = False
            for token in tokens:
                emitted = emitted or bool(token.strip())
                data = json.dumps({"token": token}, ensure_ascii=False)
                yield f"event: token\ndata: {data}\n\n"
            if not emitted:
                data = json.dumps({"message": "LLM이 빈 답변을 반환했습니다."}, ensure_ascii=False)
                yield f"event: error\ndata: {data}\n\n"
                return
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
