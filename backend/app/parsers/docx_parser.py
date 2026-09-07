from pathlib import Path

from docx import Document
from docx.table import Table


def parse_docx(path: Path) -> list[tuple[int, str]]:
    document = Document(path)
    sections: list[tuple[int, str]] = []
    for block_index, block in enumerate(document.iter_inner_content(), start=1):
        if isinstance(block, Table):
            text = "\n".join(
                cell.text.strip()
                for row in block.rows
                for cell in row.cells
                if cell.text.strip()
            )
        else:
            text = block.text.strip()
        sections.append((block_index, text))
    return sections
