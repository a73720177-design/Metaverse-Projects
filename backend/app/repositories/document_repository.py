from typing import Protocol
from uuid import UUID

from app.models.document import DocumentParseResponse
from app.db.database import AsyncSessionLocal
from app.db.tables import DocumentTable


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
    async def save(self, document: DocumentParseResponse) -> None:
        data = document.model_dump(mode="json")
        row = DocumentTable(
            document_id=document.document_id,
            filename=document.filename,
            document_type=document.document_type,
            bucket="documents",
            object_key=str(document.saved_path),
            sections=data["sections"],
            full_text=document.full_text,
        )
        async with AsyncSessionLocal() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, document_id: UUID) -> DocumentParseResponse | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(DocumentTable, document_id)
        if row is None:
            return None
        return DocumentParseResponse.model_validate(
            {
                "document_id": row.document_id,
                "filename": row.filename,
                "document_type": row.document_type,
                "saved_path": row.object_key,
                "sections": row.sections,
                "full_text": row.full_text,
            }
        )
