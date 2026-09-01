from pathlib import Path
from typing import Callable

from app.models.document import DocumentParseResponse, DocumentSection
from app.parsers.docx_parser import parse_docx
from app.parsers.pdf_parser import parse_pdf
from app.parsers.ppt_parser import parse_ppt


Parser = Callable[[Path], list[tuple[int, str]]]
PARSERS: dict[str, Parser] = {
    ".pptx": parse_ppt,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}
SUPPORTED_EXTENSIONS = frozenset(PARSERS)


def parse_document(path: Path, original_filename: str) -> DocumentParseResponse:
    parser = PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"지원하지 않는 문서 형식: {path.suffix}")

    try:
        parsed = parser(path)
    except Exception as exc:
        raise ValueError(
            "파일이 손상됐거나 올바른 PDF, PPTX, DOCX 문서가 아닙니다."
        ) from exc
    sections = [
        DocumentSection(index=index, text=text.strip())
        for index, text in parsed
        if text.strip()
    ]
    if not sections:
        raise ValueError(
            "문서에서 분석 가능한 텍스트를 찾지 못했습니다. 스캔 문서는 OCR이 필요합니다."
        )
    return DocumentParseResponse(
        filename=original_filename,
        document_type=path.suffix.lower().lstrip("."),
        saved_path=path,
        sections=sections,
        full_text="\n\n".join(section.text for section in sections),
    )
