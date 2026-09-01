import os
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from app.models.document import DocumentListItem, DocumentParseResponse
from app.db.database import get_session_factory
from app.db.tables import DocumentChunkTable, DocumentFileTable, DocumentTable, ReviewTable


class DocumentRepository(Protocol):
    """Backend가 DB 팀에 요구하는 문서 저장 계약입니다."""

    async def save(self, document: DocumentParseResponse, owner_id: UUID) -> None: ...
    async def get(self, document_id: UUID, owner_id: UUID) -> DocumentParseResponse | None: ...
    async def list(self, owner_id: UUID) -> list[DocumentListItem]: ...
    async def is_referenced(self, document_id: UUID, owner_id: UUID) -> bool: ...
    async def delete(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None: ...


class InMemoryDocumentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._documents: dict[
            UUID, tuple[UUID, DocumentParseResponse, datetime]
        ] = {}

    async def save(self, document: DocumentParseResponse, owner_id: UUID) -> None:
        self._documents[document.document_id] = (
            owner_id,
            document,
            datetime.now(timezone.utc),
        )

    async def get(self, document_id: UUID, owner_id: UUID) -> DocumentParseResponse | None:
        stored = self._documents.get(document_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None

    async def list(self, owner_id: UUID) -> list[DocumentListItem]:
        items = [
            DocumentListItem(
                document_id=document.document_id,
                filename=document.filename,
                document_type=document.document_type,
                created_at=created_at,
            )
            for stored_owner_id, document, created_at in self._documents.values()
            if stored_owner_id == owner_id
        ]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def is_referenced(self, document_id: UUID, owner_id: UUID) -> bool:
        return False

    async def delete(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None:
        document = await self.get(document_id, owner_id)
        if document is not None:
            self._documents.pop(document_id, None)
        return document


class PostgresDocumentRepository:
    def __init__(self) -> None:
        storage_mode = os.getenv("OBJECT_STORAGE_MODE", "local").strip().lower()
        self.bucket = "local" if storage_mode == "local" else os.getenv("MINIO_BUCKET", "documents")

    async def save(self, document: DocumentParseResponse, owner_id: UUID) -> None:
        data = document.model_dump(mode="json")
        content_types = {
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        row = DocumentTable(
            document_id=document.document_id,
            owner_id=owner_id,
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

    async def get(self, document_id: UUID, owner_id: UUID) -> DocumentParseResponse | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(DocumentTable).where(
                    DocumentTable.document_id == document_id,
                    DocumentTable.owner_id == owner_id,
                )
            )
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

    async def list(self, owner_id: UUID) -> list[DocumentListItem]:
        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(DocumentTable)
                    .where(DocumentTable.owner_id == owner_id)
                    .order_by(DocumentTable.created_at.desc())
                )
            ).all()
        return [
            DocumentListItem(
                document_id=row.document_id,
                filename=row.filename,
                document_type=row.document_type,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def is_referenced(self, document_id: UUID, owner_id: UUID) -> bool:
        async with get_session_factory()() as session:
            review_id = await session.scalar(
                select(ReviewTable.review_id).where(
                    ReviewTable.document_id == document_id,
                    ReviewTable.owner_id == owner_id,
                ).limit(1)
            )
        return review_id is not None

    async def delete(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None:
        document = await self.get(document_id, owner_id)
        if document is None:
            return None
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(DocumentTable).where(
                    DocumentTable.document_id == document_id,
                    DocumentTable.owner_id == owner_id,
                )
            )
            if result.rowcount == 0:
                await session.rollback()
                return None
            await session.commit()
        return document
