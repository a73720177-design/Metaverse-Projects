from pathlib import Path
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DocumentSection(BaseModel):
    index: int = Field(ge=1)
    text: str


class DocumentParseResponse(BaseModel):
    document_id: UUID = Field(default_factory=uuid4, description="문서 식별 UUID")
    filename: str
    document_type: str
    saved_path: Path
    sections: list[DocumentSection]
    full_text: str


class DocumentListItem(BaseModel):
    document_id: UUID
    filename: str
    document_type: str
    created_at: datetime
