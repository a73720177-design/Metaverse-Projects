import os
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text

from app.models.document import DocumentListItem, DocumentParseResponse
from app.db.database import get_session_factory
from app.db.tables import DocumentChunkTable, DocumentFileTable, DocumentTable, ReviewTable


class DocumentRepository(Protocol):
    """Backend가 DB 팀에 요구하는 문서 저장 계약입니다."""

    async def save(self, document: DocumentParseResponse, owner_id: UUID) -> None: ...
    async def get(self, document_id: UUID, owner_id: UUID) -> DocumentParseResponse | None: ...
    async def get_for_retrieval(
        self, document_ids: list[UUID], owner_id: UUID, query: str
    ) -> list[DocumentParseResponse]: ...
    async def list(self, owner_id: UUID) -> list[DocumentListItem]: ...
    async def is_referenced(self, document_id: UUID, owner_id: UUID) -> bool: ...
    async def delete(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None: ...


class InMemoryDocumentRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self, review_repository=None, related_repositories=()) -> None:
        self.review_repository = review_repository
        self.related_repositories = related_repositories
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

    async def get_for_retrieval(
        self, document_ids: list[UUID], owner_id: UUID, query: str
    ) -> list[DocumentParseResponse]:
        documents = []
        for document_id in dict.fromkeys(document_ids):
            document = await self.get(document_id, owner_id)
            if document is not None:
                documents.append(document if query else document.model_copy(
                    update={"sections": [], "full_text": ""}
                ))
        return documents

    async def list(self, owner_id: UUID) -> list[DocumentListItem]:
        items = [
            DocumentListItem(
                document_id=document.document_id,
                filename=document.filename,
                document_type=document.document_type,
                created_at=created_at,
                section_count=len(document.sections),
                text_length=len(document.full_text),
            )
            for stored_owner_id, document, created_at in self._documents.values()
            if stored_owner_id == owner_id
        ]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def is_referenced(self, document_id: UUID, owner_id: UUID) -> bool:
        return bool(self.review_repository and await self.review_repository.references_document(document_id, owner_id))

    async def delete(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None:
        document = await self.get(document_id, owner_id)
        if await self.is_referenced(document_id, owner_id):
            raise ValueError("리뷰에서 사용 중인 문서는 삭제할 수 없습니다.")
        if document is not None:
            for repository in self.related_repositories:
                await repository.remove_document(document_id, owner_id)
            self._documents.pop(document_id, None)
        return document


class PostgresDocumentRepository:
    def __init__(self) -> None:
        storage_mode = os.getenv("OBJECT_STORAGE_MODE", "local").strip().lower()
        self.bucket = "local" if storage_mode == "local" else os.getenv("MINIO_BUCKET", "documents")

    async def get_for_retrieval(
        self, document_ids: list[UUID], owner_id: UUID, query: str
    ) -> list[DocumentParseResponse]:
        """Load authorized metadata and bounded lexical candidates, never full_text.

        Substring candidates preserve Korean bigram matching; Python BM25 then
        refines these pages into evidence chunks. Vector retrieval independently
        searches all requested documents, including those without lexical hits.
        """
        from app.config import get_vector_rag_candidate_k
        from app.services.rag_service import DocumentContextSelector

        if not document_ids:
            return []
        terms = sorted({term.removeprefix("ko:")
                        for term in DocumentContextSelector._features(query)})
        # Features contain only letters/digits, so SQL wildcard escaping is unnecessary.
        patterns = [f"%{term}%" for term in terms]
        async with get_session_factory()() as session:
            rows = (await session.execute(text("""
                SELECT d.document_id, d.filename, d.document_type, f.object_key,
                       c.chunk_index, c.content
                FROM documents d
                JOIN document_files f ON f.document_id = d.document_id
                LEFT JOIN LATERAL (
                    SELECT chunk_index, content
                    FROM document_chunks
                    WHERE document_id = d.document_id
                      AND lower(content) LIKE ANY(CAST(:patterns AS text[]))
                    ORDER BY (
                        SELECT count(*) FROM unnest(CAST(:patterns AS text[])) p
                        WHERE lower(content) LIKE p
                    ) DESC, chunk_index
                    LIMIT :limit
                ) c ON true
                WHERE d.owner_id = :owner
                  AND d.document_id = ANY(CAST(:ids AS uuid[]))
                ORDER BY d.document_id, c.chunk_index
            """), {"owner": owner_id, "ids": document_ids,
                     "patterns": patterns, "limit": get_vector_rag_candidate_k()})).mappings().all()
        grouped = {}
        for row in rows:
            document = grouped.setdefault(row["document_id"], {
                "document_id": row["document_id"], "filename": row["filename"],
                "document_type": row["document_type"], "saved_path": row["object_key"],
                "sections": [], "full_text": "",
            })
            if row["chunk_index"] is not None:
                document["sections"].append({"index": row["chunk_index"], "text": row["content"]})
        return [DocumentParseResponse.model_validate(grouped[document_id])
                for document_id in dict.fromkeys(document_ids) if document_id in grouped]

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

        # Index for the default vector RAG mode; indexing failures do not fail uploads.
        from app.services.vector_rag import index_after_save

        await index_after_save(document.document_id, owner_id)

    async def get(self, document_id: UUID, owner_id: UUID) -> DocumentParseResponse | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(DocumentTable).where(
                    DocumentTable.document_id == document_id,
                    DocumentTable.owner_id == owner_id,
                )
            )
            if row is None:
                return None
            file_row = await session.get(DocumentFileTable, document_id)
            chunks = (
                await session.execute(
                    select(DocumentChunkTable.chunk_index, DocumentChunkTable.content)
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
                await session.execute(
                    select(
                        DocumentTable.document_id, DocumentTable.filename,
                        DocumentTable.document_type, DocumentTable.created_at,
                        func.length(DocumentTable.full_text).label("text_length"),
                        func.count(DocumentChunkTable.chunk_id).label("section_count"),
                    )
                    .outerjoin(
                        DocumentChunkTable,
                        DocumentChunkTable.document_id == DocumentTable.document_id,
                    )
                    .where(DocumentTable.owner_id == owner_id)
                    .group_by(DocumentTable.document_id)
                    .order_by(DocumentTable.created_at.desc())
                )
            ).all()
        return [
            DocumentListItem(
                document_id=row.document_id,
                filename=row.filename,
                document_type=row.document_type,
                created_at=row.created_at,
                section_count=row.section_count,
                text_length=row.text_length,
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
