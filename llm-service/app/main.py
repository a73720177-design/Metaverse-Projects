"""
LLM 서비스 API 서버.

실행:
    uvicorn app.main:app --reload --port 8001

사전 조건:
    - Ollama가 로컬에서 실행 중이어야 함 (ollama serve)
    - qwen3:8b, qwen3:4b, bge-m3 모델이 pull 되어 있어야 함

RAG(bge-m3 검색)가 모든 답변 경로의 공통 기반 레이어다. 답변을 생성하기 전에
항상 관련 자료 조각을 검색해서 프롬프트에 넣는다. 경로마다 다른 것은 "검색
여부"가 아니라 "검색 후 추론(think) 여부"다.

    /documents/index  임베딩 생성          bge-m3
    /personas         검색 없음, 추론 없음  qwen3:4b
    /reviews          검색 + 추론          qwen3:8b
    /chat             검색 + 추론          qwen3:8b
      ├ 인사말        검색 생략, 추론 없음  qwen3:4b
      └ 유사도 미달   검색만, 생성 없음     코드 템플릿

문서 전문은 Backend가 업로드 시점에 /documents/index로 한 번만 밀어넣는다.
평가와 채팅 요청에는 document_id만 실린다. 인덱스가 없으면 409를 반환하고,
Backend가 문서를 다시 밀어넣은 뒤 재시도한다.
"""

import json
import logging
import re
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from app import rag
from app.llm_client import (
    LLMError,
    OLLAMA_CHAT_MODEL,
    OLLAMA_MODEL,
    call_llm,
    check_ollama_health,
)
from app.prompts import (
    CHAT_PROMPT,
    FREE_CHAT_PROMPT,
    NEEDS_MORE_MATERIAL_TEMPLATE,
    PERSONA_GENERATION_PROMPT,
    REVIEW_GENERATION_PROMPT,
)
from app.schemas_v1 import (
    ChatGenerationRequest,
    ChatGenerationResponse,
    DocumentIn,
    DocumentIndexResponse,
    PersonaGenerationRequest,
    PersonaGenerationResponse,
    PersonaProfileIn,
    ReviewGenerationRequest,
    ReviewGenerationResponse,
    ReviewSource,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

app = FastAPI(
    title="LLM Service",
    description="발표 자료 RAG 검색 기반 평가·피드백 API",
    version="1.0.0",
)

# response_schema로 구조화 출력을 강제해도, Ollama 버전에 따라 강제가 안 통하는
# 경우를 대비한 방어적 처리로 코드펜스 제거는 남겨둔다.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# 인사·감사 같은 짧은 상투어만 검색을 건너뛴다. 이보다 넓게 잡으면 자료에
# 근거해야 할 질문까지 근거 없는 잡담 응답으로 새어 나간다.
_SMALL_TALK_RE = re.compile(
    r"^(안녕(?:하세요)?|반가워(?:요)?|고마워(?:요)?|감사(?:합니다|해요)?|"
    r"잘\s*부탁(?:드립니다|해요|합니다)?|잘가(?:요)?|수고(?:하셨습니다|하세요)?|"
    r"좋은\s*(아침|오후|저녁)(?:이에요|입니다)?|"
    r"hi|hello|hey|thanks|thank\s*you)[!?.\s]*$",
    re.IGNORECASE,
)

# 최초 평가에서 자료를 넓게 훑기 위한 기본 질의. instructions가 있으면 그쪽을 쓴다.
_REVIEW_DEFAULT_QUERY = "발표의 핵심 주장과 근거"

_MAX_SOURCES = 10


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


def _call_llm_as_json(
    prompt: str,
    response_schema: dict,
    *,
    model: str | None = None,
    think: bool = False,
    max_tokens: int | None = None,
) -> dict:
    try:
        raw = call_llm(
            prompt,
            model=model,
            response_schema=response_schema,
            think=think,
            max_tokens=max_tokens,
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
    prompt: str,
    response_model: type[T],
    *,
    model: str | None = None,
    think: bool = False,
    max_tokens: int | None = None,
) -> T:
    data = _call_llm_as_json(
        prompt,
        response_model.model_json_schema(),
        model=model,
        think=think,
        max_tokens=max_tokens,
    )
    try:
        return response_model.model_validate(data)
    except ValidationError:
        logger.error("%s 응답 스키마 불일치", response_model.__name__)
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")


def _call_llm_as_text(
    prompt: str,
    *,
    model: str | None = None,
    think: bool = False,
    max_tokens: int | None = None,
) -> str:
    try:
        answer = call_llm(
            prompt, model=model, think=think, max_tokens=max_tokens
        ).strip()
    except LLMError:
        logger.exception("Ollama 채팅 호출 실패")
        raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")
    if not answer:
        raise HTTPException(status_code=502, detail="LLM이 빈 답변을 반환했습니다.")
    return answer


def _search(document_ids: list, query: str, top_k: int | None = None) -> rag.SearchResult:
    """공통 RAG 검색. 인덱스가 없으면 Backend가 재인덱싱하도록 409로 알린다."""
    try:
        return rag.store.search(document_ids, query, top_k=top_k)
    except rag.DocumentNotIndexedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_not_indexed",
                "document_id": str(exc.document_id),
            },
        )
    except rag.RagError:
        logger.exception("RAG 검색 실패")
        raise HTTPException(status_code=503, detail="자료 검색에 실패했습니다.")


def _persona_json(persona: PersonaProfileIn) -> str:
    return json.dumps(persona.model_dump(mode="json"), ensure_ascii=False)


def _sources(result: rag.SearchResult) -> list[ReviewSource]:
    return [
        ReviewSource(
            document_id=item.chunk.document_id,
            filename=item.chunk.filename,
            page=(
                item.chunk.index
                if item.chunk.document_type in {"pdf", "pptx"}
                else None
            ),
            excerpt=item.chunk.text[:500],
        )
        for item in result.chunks[:_MAX_SOURCES]
    ]


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


@v1_router.post("/documents/index", response_model=DocumentIndexResponse)
def index_document(request: DocumentIn) -> DocumentIndexResponse:
    """문서를 청킹·임베딩해 보관한다.

    Backend가 업로드 직후 한 번 호출한다. 같은 내용이면 재계산하지 않는다.
    """
    try:
        chunk_count, reused = rag.store.index(
            document_id=request.document_id,
            filename=request.filename,
            document_type=request.document_type,
            sections=[(section.index, section.text) for section in request.sections],
            full_text=request.full_text,
        )
    except rag.RagError as exc:
        logger.exception("문서 인덱싱 실패 (document_id=%s)", request.document_id)
        raise HTTPException(status_code=503, detail=str(exc))
    return DocumentIndexResponse(
        document_id=request.document_id, chunk_count=chunk_count, reused=reused
    )


@v1_router.delete("/documents/{document_id}/index", status_code=204)
def delete_document_index(document_id: UUID) -> None:
    """문서를 지울 때 임베딩과 디스크 캐시에 남은 본문까지 함께 지운다."""
    rag.store.forget(document_id)


@v1_router.post("/personas", response_model=PersonaGenerationResponse)
def generate_persona(request: PersonaGenerationRequest) -> PersonaGenerationResponse:
    return _generate(
        PERSONA_GENERATION_PROMPT.format(
            name=request.name, description=request.description
        ),
        PersonaGenerationResponse,
        model=OLLAMA_CHAT_MODEL,
        max_tokens=512,
    )


@v1_router.post("/reviews", response_model=ReviewGenerationResponse)
def generate_review(request: ReviewGenerationRequest) -> ReviewGenerationResponse:
    """문서 업로드 직후 1회 수행하는 평가. 주장 검증이 필요해 추론을 켠다."""
    try:
        filename, _document_type = rag.store.describe(request.document_id)
    except rag.DocumentNotIndexedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_not_indexed",
                "document_id": str(exc.document_id),
            },
        )

    result = _search(
        [request.document_id],
        request.instructions or _REVIEW_DEFAULT_QUERY,
        top_k=rag.RAG_REVIEW_TOP_K,
    )
    return _generate(
        REVIEW_GENERATION_PROMPT.format(
            persona_json=_persona_json(request.persona),
            filename=filename,
            context_block=result.as_context(),
            instructions=request.instructions or "(없음)",
        ),
        ReviewGenerationResponse,
        model=OLLAMA_MODEL,
        think=True,
        max_tokens=2048,
    )


@v1_router.post("/chat", response_model=ChatGenerationResponse)
def generate_chat(request: ChatGenerationRequest) -> ChatGenerationResponse:
    """평가 이후의 대화. 발표자의 답변에 페르소나 관점으로 피드백한다."""
    message = request.message.strip()

    # 인사·상투어는 근거로 삼을 자료가 필요 없다. 검색과 추론을 모두 건너뛴다.
    if _SMALL_TALK_RE.fullmatch(message):
        return ChatGenerationResponse(
            answer=_call_llm_as_text(
                FREE_CHAT_PROMPT.format(
                    persona_json=_persona_json(request.persona), message=message
                ),
                model=OLLAMA_CHAT_MODEL,
                max_tokens=160,
            ),
            sources=[],
        )

    result = _search(request.document_ids, message)

    # 근거가 없는 상태에서 생성하면 없는 내용을 지어낸다. 모델을 부르지 않고
    # 자료 추가를 요청한다.
    if not result.is_relevant():
        return ChatGenerationResponse(
            answer=NEEDS_MORE_MATERIAL_TEMPLATE.format(name=request.persona.name),
            sources=[],
            needs_more_material=True,
        )

    return ChatGenerationResponse(
        answer=_call_llm_as_text(
            CHAT_PROMPT.format(
                persona_json=_persona_json(request.persona),
                context_block=result.as_context(),
                message=message,
            ),
            model=OLLAMA_MODEL,
            think=True,
            max_tokens=1536,
        ),
        sources=_sources(result),
    )


app.include_router(v1_router)
