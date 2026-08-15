from typing import Protocol
from uuid import UUID

from app.models.document import DocumentParseResponse


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
