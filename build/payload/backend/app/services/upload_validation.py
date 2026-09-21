import os
import zipfile
from pathlib import Path


class UploadLimitError(ValueError):
    pass


def validate_container(path: Path, mime: str | None) -> None:
    suffix = path.suffix.lower()
    expected = {".pdf": "application/pdf",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[suffix]
    allowed = {expected, "application/octet-stream"}
    if suffix != ".pdf":
        allowed.add("application/zip")
    if mime and mime.split(";")[0].lower() not in allowed:
        raise ValueError("파일 확장자와 MIME 형식이 일치하지 않습니다.")
    with path.open("rb") as source:
        signature = source.read(1024)
    if suffix == ".pdf":
        if not signature.startswith(b"%PDF-"):
            raise ValueError("올바른 PDF 파일 형식이 아닙니다.")
        return
    if not zipfile.is_zipfile(path):
        raise ValueError("올바른 Office 문서 형식이 아닙니다.")
    max_total = int(os.getenv("UPLOAD_MAX_EXPANDED_BYTES", str(100 * 1024 * 1024)))
    max_entries = int(os.getenv("UPLOAD_MAX_ZIP_ENTRIES", "5000"))
    with zipfile.ZipFile(path) as archive:
        items = archive.infolist()
        if len(items) > max_entries or sum(i.file_size for i in items) > max_total:
            raise UploadLimitError("압축 해제 용량 또는 파일 항목 수 제한을 초과했습니다.")
        for item in items:
            if item.flag_bits & 1:
                raise ValueError("암호화된 문서는 지원하지 않습니다.")
            if item.file_size > 25 * 1024 * 1024 or item.file_size / max(1, item.compress_size) > 200:
                raise UploadLimitError("압축 항목 크기 또는 압축률 제한을 초과했습니다.")
        names = set(archive.namelist())
        required = "ppt/presentation.xml" if suffix == ".pptx" else "word/document.xml"
        if required not in names or "[Content_Types].xml" not in names:
            raise ValueError("문서 확장자와 내부 Office 구조가 일치하지 않습니다.")
