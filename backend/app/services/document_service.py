from pathlib import Path
from typing import Callable

from app.models.document import DocumentParseResponse, DocumentSection
from app.parsers.docx_parser import parse_docx
from app.parsers.pdf_parser import parse_pdf
from app.parsers.ppt_parser import parse_ppt


Parser = Callable[[Path], list[str]]
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

    texts = [text.strip() for text in parser(path) if text.strip()]
    sections = [DocumentSection(index=index, text=text) for index, text in enumerate(texts, start=1)]
    return DocumentParseResponse(
        filename=original_filename,
        document_type=path.suffix.lower().lstrip("."),
        saved_path=path,
        sections=sections,
        full_text="\n\n".join(texts),
    )
