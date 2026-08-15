from typing import Protocol
from uuid import UUID

from app.models.document import DocumentParseResponse


class DocumentRepository(Protocol):
    async def save(self, document: DocumentParseResponse) -> None: ...

    async def get(self, document_id: UUID) -> DocumentParseResponse | None: ...
