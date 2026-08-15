from uuid import UUID

from app.models.document import DocumentParseResponse


class InMemoryDocumentRepository:
    """DB 팀 구현이 연결되기 전까지 사용하는 개발용 저장소입니다."""

    def __init__(self) -> None:
        self._documents: dict[UUID, DocumentParseResponse] = {}

    async def save(self, document: DocumentParseResponse) -> None:
        self._documents[document.document_id] = document

    async def get(self, document_id: UUID) -> DocumentParseResponse | None:
        return self._documents.get(document_id)
