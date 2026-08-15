from pathlib import Path

from pptx import Presentation


def parse_ppt(path: Path) -> list[str]:
    presentation = Presentation(path)
    slides: list[str] = []
    for slide in presentation.slides:
        parts = [shape.text.strip() for shape in slide.shapes if hasattr(shape, "text") and shape.text.strip()]
        slides.append("\n".join(parts))
    return slides
