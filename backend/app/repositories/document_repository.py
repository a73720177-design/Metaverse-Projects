import os
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from app.models.document import DocumentParseResponse
from app.db.database import get_session_factory
from app.db.tables import DocumentChunkTable, DocumentFileTable, DocumentTable


class DocumentRepository(Protocol):
    """Backend가 DB 팀에 요구하는 문서 저장 계약입니다."""

    async def save(self, document: DocumentParseResponse) -> None: ...
    async def get(self, document_id: UUID) -> DocumentParseResponse | None: ...


class InMemoryDocumentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._documents: dict[UUID, DocumentParseResponse] = {}

    async def save(self, document: DocumentParseResponse) -> None:
        self._documents[document.document_id] = document

    async def get(self, document_id: UUID) -> DocumentParseResponse | None:
        return self._documents.get(document_id)


class PostgresDocumentRepository:
    def __init__(self) -> None:
        storage_mode = os.getenv("OBJECT_STORAGE_MODE", "local").strip().lower()
        self.bucket = "local" if storage_mode == "local" else os.getenv("MINIO_BUCKET", "documents")

    async def save(self, document: DocumentParseResponse) -> None:
        data = document.model_dump(mode="json")
        content_types = {
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        row = DocumentTable(
            document_id=document.document_id,
            filename=document.filename,
            document_type=document.document_type,
            full_text=document.full_text,
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.merge(
                DocumentFileTable(
                    document_id=document.document_id,
                    bucket=self.bucket,
                    object_key=str(document.saved_path),
                    content_type=content_types.get(document.document_type),
                )
            )
            await session.execute(
                delete(DocumentChunkTable).where(
                    DocumentChunkTable.document_id == document.document_id
                )
            )
            session.add_all(
                DocumentChunkTable(
                    chunk_id=uuid4(),
                    document_id=document.document_id,
                    chunk_index=section["index"],
                    content=section["text"],
                    metadata_json={},
                )
                for section in data["sections"]
            )
            await session.commit()

    async def get(self, document_id: UUID) -> DocumentParseResponse | None:
        async with get_session_factory()() as session:
            row = await session.get(DocumentTable, document_id)
            file_row = await session.get(DocumentFileTable, document_id)
            chunks = (
                await session.scalars(
                    select(DocumentChunkTable)
                    .where(DocumentChunkTable.document_id == document_id)
                    .order_by(DocumentChunkTable.chunk_index)
                )
            ).all()
        if row is None or file_row is None:
            return None
        return DocumentParseResponse.model_validate(
            {
                "document_id": row.document_id,
                "filename": row.filename,
                "document_type": row.document_type,
                "saved_path": file_row.object_key,
                "sections": [
                    {"index": chunk.chunk_index, "text": chunk.content}
                    for chunk in chunks
                ],
                "full_text": row.full_text,
            }
        )
