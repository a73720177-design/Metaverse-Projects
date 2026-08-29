from pathlib import Path

import fitz


def parse_pdf(path: Path) -> list[str]:
    with fitz.open(path) as document:
        return [page.get_text("text").strip() for page in document]
