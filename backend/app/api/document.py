from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.document import DocumentParseResponse
from app.services.document_service import SUPPORTED_EXTENSIONS, parse_document


router = APIRouter(prefix="/documents", tags=["문서"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


@router.post(
    "/parse",
    response_model=DocumentParseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="문서 업로드 및 텍스트 추출",
    description=(
        "PPTX, PDF 또는 DOCX 파일을 업로드합니다. 파일은 uploads 폴더에 UUID 이름으로 "
        "저장되며, 슬라이드·페이지·문단 단위 텍스트와 전체 텍스트를 반환합니다."
    ),
)
async def upload_and_parse(file: UploadFile = File(...)) -> DocumentParseResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 형식입니다. 지원 형식: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
    try:
        saved_path.write_bytes(await file.read())
        return parse_document(saved_path, original_filename=file.filename or saved_path.name)
    except ValueError as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="문서를 처리하지 못했습니다.") from exc
    finally:
        await file.close()
