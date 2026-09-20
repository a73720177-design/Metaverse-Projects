import asyncio
from contextlib import asynccontextmanager          #시작, 종료시 실행할 작업 정의

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    get_db_auto_create,
    get_frontend_origin_regex,
    get_frontend_origins,
    get_object_storage_mode,
    get_practice_max_concurrent_personas,
    get_repository_mode,
    get_rag_mode,
    validate_runtime_contract,
)
from app.controllers.agent_controller import router as agent_router
from app.controllers.auth_controller import router as auth_router
from app.controllers.chat_controller import router as chat_router
from app.controllers.document_controller import router as document_router
from app.controllers.review_controller import router as review_router
from app.controllers.practice_controller import router as practice_router
from app.dependencies import get_llm_client, get_object_storage
from app.db.database import check_db, close_db, init_db, inspect_db_contract
from app.error_handlers import register_error_handlers
from app.integrations.llm.client import (
    HttpLlmClient,
    LlmServiceConnectionError,
    LlmServiceResponseError,
)


@asynccontextmanager
async def lifespan(_: FastAPI): # 아래의 작업  FastAPI에 등록
    validate_runtime_contract()
    postgres_enabled = get_repository_mode() == "postgres"
    if postgres_enabled and get_db_auto_create():
        await init_db()
    try:
        yield
    finally:
        if postgres_enabled:
            await close_db()


app = FastAPI(
    title="로컬 AI 발표자료 평가 백엔드",
    version="0.2.0",
    lifespan=lifespan,
    description=(
        "PPTX·PDF·DOCX 문서를 처리하고 평가자 페르소나 기반 리뷰와 대화를 "
        "제공하는 API입니다. Backend는 요청 검증과 서비스 조합을 담당하고, "
        "LLM과 DB는 정해진 계약을 통해 연결합니다."
    ),
    openapi_tags=[
        {"name": "시스템", "description": "Backend와 LLM 서비스 상태를 확인합니다."},
        {"name": "로그인", "description": "로컬 계정을 생성하고 JWT로 로그인합니다."},
        {"name": "평가자", "description": "평가자 페르소나를 생성하고 조회합니다."},
        {"name": "문서", "description": "발표 자료를 업로드하고 텍스트를 추출합니다."},
        {"name": "리뷰", "description": "평가자 관점의 문서 리뷰를 생성하고 조회합니다."},
        {"name": "대화", "description": "평가자 페르소나 관점으로 질문하고 답변받습니다."},
    ],
)

register_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_origin_regex=get_frontend_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(document_router)
app.include_router(review_router)
app.include_router(chat_router)
app.include_router(practice_router)


@app.get(
    "/",
    tags=["시스템"],
    summary="Backend 기본 정보",
    description="Backend 서버 접속 여부를 확인하는 가장 간단한 엔드포인트입니다.",
)
def root() -> dict[str, str]:
    return {"message": "Local AI Review Backend"}


@app.get(
    "/health",
    tags=["시스템"],
    summary="Backend 상태 확인",
    description="Backend 프로세스가 정상적으로 요청을 처리하는지 확인합니다.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/db",
    tags=["시스템"],
    summary="DB 연결 상태 확인",
    description="현재 Repository 모드와 PostgreSQL 연결 가능 여부를 확인합니다.",
)
async def db_health() -> dict[str, object]:
    repository_mode = get_repository_mode()
    if repository_mode == "memory":
        return {
            "status": "ok",
            "repository_mode": "memory",
            "database": "not_configured",
        }
    try:
        await check_db()
        contract = await inspect_db_contract(require_vector=get_rag_mode() == "vector")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL 연결을 확인할 수 없습니다.",
        ) from exc
    if contract["status"] != "ok":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DB_SCHEMA_MISMATCH",
                "message": "Backend가 요구하는 DB migration이 적용되지 않았습니다.",
                "contract": contract,
            },
        )
    return {
        "status": "ok",
        "repository_mode": "postgres",
        "database": "connected",
        "contract": contract,
    }


@app.get(
    "/health/llm",
    tags=["시스템"],
    summary="LLM 서비스 연결 상태 확인",
    description="현재 계약 모드에 맞춰 Backend에서 LLM 서비스의 health API를 호출합니다.",
)
async def llm_health(
    client: HttpLlmClient = Depends(get_llm_client),
) -> dict[str, object]:
    try:
        detail = await client.get_json("/health")
    except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "llm_service": detail}


@app.get(
    "/health/services",
    tags=["시스템"],
    summary="팀 서비스 통합 상태 확인",
    description=(
        "Frontend 상태 화면에서 Backend, DB, LLM 연결 상태를 한 번에 확인합니다. "
        "내부 주소와 예외 원문은 반환하지 않습니다."
    ),
)
async def services_health(
    client: HttpLlmClient = Depends(get_llm_client),
) -> dict[str, object]:
    services: dict[str, dict[str, object]] = {
        "backend": {"status": "ok", "label": "Backend"}
    }

    repository_mode = get_repository_mode()
    if repository_mode == "memory":
        services["database"] = {
            "status": "development",
            "label": "DB",
            "mode": "memory",
            "message": "외부 PostgreSQL을 사용하지 않는 개발 모드입니다.",
        }
    else:
        try:
            await check_db()
        except Exception:
            services["database"] = {
                "status": "unavailable",
                "label": "DB",
                "mode": "postgres",
                "message": "PostgreSQL에 연결할 수 없습니다.",
            }
        else:
            try:
                contract = await inspect_db_contract(
                    require_vector=get_rag_mode() == "vector"
                )
            except Exception:
                contract = {"status": "unavailable"}
            services["database"] = {
                "status": "ok" if contract["status"] == "ok" else "unavailable",
                "label": "DB",
                "mode": "postgres",
                "message": (
                    "PostgreSQL 연결과 스키마 계약이 정상입니다."
                    if contract["status"] == "ok"
                    else "PostgreSQL migration 상태가 Backend 계약과 맞지 않습니다."
                ),
                "contract": contract,
            }

    try:
        detail = await client.get_json("/health")
    except (LlmServiceConnectionError, LlmServiceResponseError):
        services["llm"] = {
            "status": "unavailable",
            "label": "LLM",
            "message": "LLM 서비스에 연결할 수 없습니다.",
        }
    else:
        services["llm"] = {
            "status": "ok",
            "label": "LLM",
            "message": "LLM 서비스 연결이 정상입니다.",
            "service_status": detail.get("status", "unknown"),
        }

    degraded = any(
        service["status"] == "unavailable" for service in services.values()
    )
    return {
        "status": "degraded" if degraded else "ok",
        "services": services,
    }


@app.get(
    "/health/features",
    tags=["시스템"],
    summary="개발자 기능 상태 확인",
    description="활성 기능과 실제 연결 상태를 비밀 설정값 없이 반환합니다.",
)
async def feature_health(
    client: HttpLlmClient = Depends(get_llm_client),
) -> dict[str, object]:
    repository_mode = get_repository_mode()
    rag_mode = get_rag_mode()
    storage_mode = get_object_storage_mode()

    database_operational = True
    if repository_mode == "postgres":
        try:
            await check_db()
            contract = await inspect_db_contract(require_vector=rag_mode == "vector")
            database_operational = contract["status"] == "ok"
        except Exception:
            database_operational = False

    try:
        llm = await client.get_json("/diagnostics")
    except (LlmServiceConnectionError, LlmServiceResponseError):
        llm = {"status": "unavailable", "provider": "unknown", "features": {}}

    storage_operational: bool | None = True
    if storage_mode == "minio":
        try:
            storage = get_object_storage()
            await asyncio.to_thread(storage.client.bucket_exists, storage.bucket)
        except Exception:
            storage_operational = False

    llm_features = llm.get("features") if isinstance(llm.get("features"), dict) else {}
    features: dict[str, dict[str, object]] = {
        "vllm": {
            "label": "vLLM 생성 서버",
            **(llm_features.get("vllm") or {"enabled": None, "operational": None}),
        },
        "ollama_generation": {
            "label": "Ollama 답변 생성",
            **(llm_features.get("ollama_generation") or {"enabled": None, "operational": None}),
        },
        "embedding": {
            "label": "Ollama 임베딩",
            **(llm_features.get("ollama_embedding") or {"enabled": True, "operational": False}),
        },
        "gpu_acceleration": {
            "label": "모델 GPU 가속",
            **(llm_features.get("gpu_acceleration") or {
                "enabled": True, "operational": None, "mode": "unknown",
            }),
        },
        "streaming": {
            "label": "스트리밍 채팅",
            **(llm_features.get("streaming") or {"enabled": True, "operational": False}),
        },
        "database": {
            "label": "PostgreSQL DB",
            "enabled": repository_mode == "postgres",
            "operational": database_operational if repository_mode == "postgres" else None,
            "mode": repository_mode,
        },
        "vector_rag": {
            "label": "Vector RAG",
            "enabled": rag_mode == "vector",
            "operational": (
                database_operational
                and bool((llm_features.get("ollama_embedding") or {}).get("operational"))
                if rag_mode == "vector" else None
            ),
            "mode": rag_mode,
        },
        "object_storage": {
            "label": "문서 파일 저장소",
            "enabled": True,
            "operational": storage_operational,
            "mode": storage_mode,
        },
        "persona_parallelism": {
            "label": "페르소나 병렬 생성",
            "enabled": get_practice_max_concurrent_personas() > 1,
            "operational": True,
            "workers": get_practice_max_concurrent_personas(),
        },
    }
    degraded = any(
        item.get("enabled") is True and item.get("operational") is False
        for item in features.values()
    )
    return {
        "status": "degraded" if degraded else "ok",
        "active_llm_provider": llm.get("provider", "unknown"),
        "models": llm.get("models", []),
        "features": features,
    }
