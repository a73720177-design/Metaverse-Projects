from pathlib import Path

from pydantic import BaseModel, Field


class DocumentSection(BaseModel):
    index: int = Field(ge=1)
    text: str


class DocumentParseResponse(BaseModel):
    filename: str
    document_type: str
    saved_path: Path
    sections: list[DocumentSection]
    full_text: str
