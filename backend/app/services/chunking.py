from pydantic import BaseModel, Field

from app.models.document import DocumentParseResponse, DocumentSection


class DocumentChunk(BaseModel):
    chunk_index: int = Field(ge=0, description="문서 전체에서의 청크 순번(0부터)")
    section_index: int = Field(ge=1, description="이 청크가 나온 원본 섹션 번호")
    text: str


def split_document(
    document: DocumentParseResponse, *, chunk_size: int = 700, overlap: int = 100
) -> list[DocumentChunk]:
    """Split a document into overlapping chunks, numbered across the whole document.

    Mirrors DocumentContextSelector's original splitting exactly (same slicing
    per section) so lexical and embedding retrieval operate on identical
    chunk boundaries when given the same chunk_size/overlap.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1.")

    chunks: list[DocumentChunk] = []
    source = document.sections or [DocumentSection(index=1, text=document.full_text)]
    for section in source:
        text = section.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(
                DocumentChunk(
                    chunk_index=len(chunks),
                    section_index=section.index,
                    text=text[start:end],
                )
            )
            if end == len(text):
                break
            start = end - overlap
    return chunks
