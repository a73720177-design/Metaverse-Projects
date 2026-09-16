import os
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
    vision_mode = os.getenv("DOCUMENT_VISION_MODE", "off").strip().lower()
    if vision_mode not in {"off", "ollama"}:
        raise ValueError("DOCUMENT_VISION_MODE는 off 또는 ollama여야 합니다.")
    parser = PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"지원하지 않는 문서 형식: {path.suffix}")

    try:
        parsed = parser(path)
    except Exception as exc:
        # PDF/PPTX 원본은 향후 DB/vector 파싱 파이프라인이 다시 처리할 수
        # 있도록 현재 파서가 읽지 못해도 먼저 보관한다. DOCX는 기존처럼
        # 손상된 문서를 거절한다.
        if path.suffix.lower() in {".pdf", ".pptx"} and vision_mode == "off":
            parsed = []
        else:
            raise ValueError(
                "파일이 손상됐거나 올바른 PDF, PPTX, DOCX 문서가 아닙니다."
            ) from exc
    if vision_mode == "ollama" and path.suffix.lower() in {".pdf", ".pptx"}:
        from app.parsers.visual_parser import enrich_visual_pages

        parsed = enrich_visual_pages(path, parsed)
    sections = [
        DocumentSection(index=index, text=text.strip())
        for index, text in parsed
        if text.strip()
    ]
    return DocumentParseResponse(
        filename=original_filename,
        document_type=path.suffix.lower().lstrip("."),
        saved_path=path,
        sections=sections,
        full_text="\n\n".join(section.text for section in sections),
    )
