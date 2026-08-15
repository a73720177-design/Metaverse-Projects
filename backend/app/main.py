from fastapi import Depends, FastAPI, HTTPException

from app.adapters.http_llm_client import (
    HttpLlmClient,
    LlmServiceConnectionError,
    LlmServiceResponseError,
)
from app.api.agent import router as agent_router
from app.api.chat import router as chat_router
from app.api.document import router as document_router
from app.api.review import router as review_router
from app.error_handlers import register_error_handlers
from app.dependencies import get_llm_client


app = FastAPI(
    title="로컬 AI 발표자료 평가 백엔드",
    version="0.1.0",
    description=(
        "PPTX·PDF·DOCX 문서를 로컬에서 처리하고, 평가자 페르소나 기반 리뷰와 "
        "대화를 제공하는 팀 프로젝트용 API입니다. 백엔드는 요청 검증과 서비스 조합을 "
        "담당하며, LLM 및 DB 구현은 담당 팀원의 어댑터를 통해 연결합니다."
    ),
    openapi_tags=[
        {"name": "시스템", "description": "서버 실행 상태와 기본 정보를 확인합니다."},
        {"name": "평가자", "description": "평가자 페르소나를 생성하고 조회합니다."},
        {"name": "문서", "description": "발표자료를 업로드하고 텍스트를 추출합니다."},
        {"name": "리뷰", "description": "특정 평가자 관점의 근거 기반 리뷰를 요청하고 조회합니다."},
        {"name": "대화", "description": "평가자 페르소나 관점으로 질문하고 답변을 받습니다."},
    ],
)

app.include_router(agent_router)
app.include_router(document_router)
app.include_router(review_router)
app.include_router(chat_router)
register_error_handlers(app)


@app.get(
    "/",
    tags=["시스템"],
    summary="백엔드 기본 정보 확인",
    description="백엔드 서버에 접속할 수 있는지 확인하는 가장 간단한 엔드포인트입니다.",
)
def root() -> dict[str, str]:
    return {"message": "Local AI Review Backend"}


@app.get(
    "/health",
    tags=["시스템"],
    summary="서버 상태 확인",
    description="프론트엔드 또는 배포 환경에서 백엔드 프로세스가 정상인지 확인합니다.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/llm",
    tags=["시스템"],
    summary="LLM 서비스 연결 상태 확인",
    description="백엔드에서 독립 LLM 서비스의 `/api/v1/health`를 실제 호출합니다.",
)
async def llm_health(
    client: HttpLlmClient = Depends(get_llm_client),
) -> dict[str, object]:
    try:
        detail = await client.get_json("/health")
    except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "llm_service": detail}
