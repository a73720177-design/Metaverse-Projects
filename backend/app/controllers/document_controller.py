import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_max_upload_size_bytes
from app.dependencies import (
    get_agent_repository, get_current_user, get_document_indexer,
    get_document_repository, get_object_storage,
)
from app.integrations.llm.contracts import DocumentIndexError, DocumentIndexer
from app.models.document import (
    DocumentDetailResponse, DocumentListItem, DocumentParseResponse,
)
from app.models.user import UserResponse
from app.repositories.document_repository import DocumentRepository
from app.repositories.agent_repository import AgentRepository
from app.services.document_service import SUPPORTED_EXTENSIONS, parse_document
from app.storage.object_storage import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["문서"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


async def _index_best_effort(
    indexer: DocumentIndexer, document: DocumentParseResponse
) -> None:
    """LLM 서비스에 임베딩 인덱스를 만들어 둡니다.

    문서 전문이 LLM 서비스로 넘어가는 유일한 지점입니다. 이후 평가·채팅
    요청에는 document_id만 오갑니다. 인덱싱이 실패해도 업로드는 성공으로
    두고, 첫 평가/채팅에서 409를 받으면 그때 다시 인덱싱합니다.
    """
    try:
        await indexer.index(document)
    except DocumentIndexError:
        logger.warning(
            "LLM 인덱싱에 실패해 업로드만 완료했습니다 (document_id=%s)",
            document.document_id,
        )


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
    indexer: DocumentIndexer = Depends(get_document_indexer),
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
    # 삭제한 문서의 본문이 LLM 서비스의 임베딩 캐시에 남지 않도록 함께 지웁니다.
    try:
        await indexer.forget(document_id)
    except DocumentIndexError:
        logger.warning("LLM 인덱스 삭제에 실패했습니다 (document_id=%s)", document_id)


@router.post("/parse", response_model=DocumentDetailResponse,
             status_code=status.HTTP_201_CREATED,
             summary="문서 업로드 및 텍스트 추출",
             description="PPTX, PDF, DOCX 파일을 저장하고 구간별·전체 텍스트를 반환합니다.")
async def upload_and_parse(
    file: UploadFile = File(...),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
    indexer: DocumentIndexer = Depends(get_document_indexer),
    current_user: UserResponse = Depends(get_current_user),
) -> DocumentDetailResponse:
    filename = file.filename or ""
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=422, detail="올바른 파일 이름이 필요합니다.")
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
        if not contents:
            raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")
        if len(contents) > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기는 {max_size // (1024 * 1024)}MB 이하여야 합니다.",
            )
        await asyncio.to_thread(saved_path.write_bytes, contents)
        document = await asyncio.to_thread(
            parse_document,
            saved_path,
            file.filename or saved_path.name,
        )
        object_key = build_document_object_key(document.document_id, suffix)
        await storage.upload(saved_path, object_key, file.content_type)
        uploaded = True
        document.saved_path = Path(object_key)
        await repository.save(document, current_user.user_id)
        await _index_best_effort(indexer, document)
        return DocumentDetailResponse.from_document(document)
    except HTTPException:
        raise
    except ValueError as exc:
        if uploaded and object_key is not None:
            try:
                await storage.delete(object_key)
            except Exception:
                pass
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
