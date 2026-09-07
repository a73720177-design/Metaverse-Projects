from pathlib import Path

import fitz


def parse_pdf(path: Path) -> list[tuple[int, str]]:
    with fitz.open(path) as document:
        return [
            (page_number, page.get_text("text").strip())
            for page_number, page in enumerate(document, start=1)
        ]
