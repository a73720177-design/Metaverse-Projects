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
    section_count: int = Field(ge=0)
    text_length: int = Field(ge=0)


class DocumentDetailResponse(BaseModel):
    document_id: UUID
    filename: str
    document_type: str
    sections: list[DocumentSection]
    full_text: str
    section_count: int = Field(ge=0)
    text_length: int = Field(ge=0)

    @classmethod
    def from_document(cls, document: DocumentParseResponse) -> "DocumentDetailResponse":
        return cls(
            document_id=document.document_id,
            filename=document.filename,
            document_type=document.document_type,
            sections=document.sections,
            full_text=document.full_text,
            section_count=len(document.sections),
            text_length=len(document.full_text),
        )
