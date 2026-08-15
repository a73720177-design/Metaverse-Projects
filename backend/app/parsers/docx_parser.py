from pathlib import Path

from docx import Document


def parse_docx(path: Path) -> list[str]:
    document = Document(path)
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    table_texts = [
        "\n".join(cell.text.strip() for row in table.rows for cell in row.cells if cell.text.strip())
        for table in document.tables
    ]
    return paragraphs + [text for text in table_texts if text]
