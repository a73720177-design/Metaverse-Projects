import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_max_upload_size_bytes
from app.integrations.vision import VisionUnavailableError
from app.dependencies import (
    get_agent_repository, get_current_user, get_document_repository, get_object_storage,
    get_summary_service,
)
from app.models.document import (
    DocumentDetailResponse, DocumentListItem, DocumentParseResponse,
)
from app.models.summary import SummaryCreateRequest, SummaryResult
from app.models.user import UserResponse
from app.repositories.document_repository import DocumentRepository
from app.repositories.agent_repository import AgentRepository
from app.services.document_service import SUPPORTED_EXTENSIONS, parse_document
from app.services.summary_service import (
    SummaryResourceNotFoundError, SummaryService, SummaryServiceError,
    SummarySourceUnavailableError,
)
from app.storage.object_storage import ObjectStorage, ObjectStorageError

router = APIRouter(prefix="/documents", tags=["문서"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


def build_document_object_key(document_id: UUID, suffix: str) -> str:
    """Return the shared DB/MinIO key for an original uploaded document."""
    return f"{document_id}/original{suffix.lower()}"


@router.get("", response_model=list[DocumentListItem], summary="내 문서 목록 조회")
async def list_documents(
    repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserResponse = Depends(get_current_user),
) -> list[DocumentListItem]:
    return await repository.list(current_user.user_id)


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="내 문서 조회",
)
async def get_document(
    document_id: UUID,
    repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserResponse = Depends(get_current_user),
) -> DocumentDetailResponse:
    document = await repository.get(document_id, current_user.user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return DocumentDetailResponse.from_document(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 문서 삭제",
)
async def delete_document(
    document_id: UUID,
    repository: DocumentRepository = Depends(get_document_repository),
    agent_repository: AgentRepository = Depends(get_agent_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    document = await repository.get(document_id, current_user.user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if await repository.is_referenced(document_id, current_user.user_id):
        raise HTTPException(
            status_code=409,
            detail="리뷰에서 사용 중인 문서는 삭제할 수 없습니다.",
        )
    await storage.delete(str(document.saved_path))
    await agent_repository.unlink_document(document_id, current_user.user_id)
    deleted = await repository.delete(document_id, current_user.user_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")


@router.post("/parse", response_model=DocumentDetailResponse,
             status_code=status.HTTP_201_CREATED,
             summary="문서 업로드 및 내용 분석",
             description="PPTX, PDF, DOCX를 저장합니다. VLM 활성화 시 PPTX/PDF의 시각 정보도 분석합니다.")
async def upload_and_parse(
    file: UploadFile = File(...),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    current_user: UserResponse = Depends(get_current_user),
) -> DocumentDetailResponse:
    raw_filename = (file.filename or "").replace("\\", "/")
    filename = Path(raw_filename).name
    if not filename:
        raise HTTPException(status_code=400, detail="올바른 파일 이름이 필요합니다.")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 형식입니다. 지원 형식: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
    object_key: str | None = None
    uploaded = False
    try:
        max_size = get_max_upload_size_bytes()
        contents = await file.read(max_size + 1)
        if not contents and suffix not in {".pdf", ".pptx"}:
            raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
        if len(contents) > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기는 {max_size // (1024 * 1024)}MB 이하여야 합니다.",
            )
        await asyncio.to_thread(saved_path.write_bytes, contents)
        document = await asyncio.to_thread(
            parse_document,
            saved_path,
            filename,
        )
        object_key = build_document_object_key(document.document_id, suffix)
        await storage.upload(saved_path, object_key, file.content_type)
        uploaded = True
        document.saved_path = Path(object_key)
        await repository.save(document, current_user.user_id)
        return DocumentDetailResponse.from_document(document)
    except HTTPException:
        raise
    except VisionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        if uploaded and object_key is not None:
            try:
                await storage.delete(object_key)
            except Exception:
                pass
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (SQLAlchemyError, ObjectStorageError):
        if uploaded and object_key is not None:
            try:
                await storage.delete(object_key)
            except Exception:
                pass
        raise
    except Exception as exc:
        if uploaded and object_key is not None:
            try:
                await storage.delete(object_key)
            except Exception:
                pass
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="문서를 처리하지 못했습니다.") from exc
    finally:
        saved_path.unlink(missing_ok=True)
        await file.close()


@router.post(
    "/{document_id}/summary",
    response_model=SummaryResult,
    status_code=status.HTTP_201_CREATED,
    summary="문서 요약 생성",
    description=(
        "문서 전체 요약과 핵심 주제를 생성합니다. 같은 (문서, 페르소나, 스타일) "
        "조합의 요약이 이미 있으면 refresh=true를 주지 않는 한 캐시된 결과를 반환합니다."
    ),
)
async def create_summary(
    document_id: UUID,
    request: SummaryCreateRequest,
    refresh: bool = False,
    service: SummaryService = Depends(get_summary_service),
    current_user: UserResponse = Depends(get_current_user),
) -> SummaryResult:
    try:
        return await service.create(document_id, request, current_user.user_id, refresh=refresh)
    except SummaryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SummarySourceUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SummaryServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/{document_id}/summary",
    response_model=SummaryResult,
    summary="문서 요약 조회",
    description="기본 스타일(brief)로 생성된 요약을 조회합니다. 없으면 404입니다.",
)
async def get_summary(
    document_id: UUID,
    service: SummaryService = Depends(get_summary_service),
    current_user: UserResponse = Depends(get_current_user),
) -> SummaryResult:
    try:
        summary = await service.get(document_id, current_user.user_id)
    except SummaryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="요약을 찾을 수 없습니다.")
    return summary
