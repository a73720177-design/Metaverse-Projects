from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_max_upload_size_bytes
from app.dependencies import get_document_repository, get_object_storage
from app.models.document import DocumentParseResponse
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import SUPPORTED_EXTENSIONS, parse_document
from app.storage.object_storage import ObjectStorage, ObjectStorageError

router = APIRouter(prefix="/documents", tags=["문서"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


@router.post("/parse", response_model=DocumentParseResponse,
             status_code=status.HTTP_201_CREATED,
             summary="문서 업로드 및 텍스트 추출",
             description="PPTX, PDF, DOCX 파일을 저장하고 구간별·전체 텍스트를 반환합니다.")
async def upload_and_parse(
    file: UploadFile = File(...),
    repository: DocumentRepository = Depends(get_document_repository),
    storage: ObjectStorage = Depends(get_object_storage),
) -> DocumentParseResponse:
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
        saved_path.write_bytes(contents)
        document = parse_document(
            saved_path, original_filename=file.filename or saved_path.name
        )
        object_key = f"{document.document_id}{suffix}"
        await storage.upload(saved_path, object_key, file.content_type)
        uploaded = True
        document.saved_path = Path(object_key)
        await repository.save(document)
        return document
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
