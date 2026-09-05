from typing import Any, Protocol
from uuid import UUID

from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile


class PersonaGeneratorError(RuntimeError):
    pass


class ReviewGeneratorError(RuntimeError):
    pass


class ChatGeneratorError(RuntimeError):
    pass


class DocumentIndexError(RuntimeError):
    pass


class DocumentNotIndexedError(RuntimeError):
    """LLM 서비스에 해당 문서의 임베딩 인덱스가 없습니다.

    LLM 서비스가 재시작되거나 캐시가 지워지면 발생합니다. 서비스 계층이 문서를
    다시 인덱싱한 뒤 한 번 재시도합니다.
    """

    def __init__(self, document_id: UUID) -> None:
        super().__init__(f"document not indexed: {document_id}")
        self.document_id = document_id


class PersonaGenerator(Protocol):
    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]: ...


class DocumentIndexer(Protocol):
    async def index(self, document: DocumentParseResponse) -> dict[str, Any]: ...

    async def forget(self, document_id: UUID) -> None: ...


class ReviewGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        document_id: UUID,
        instructions: str | None,
    ) -> dict[str, Any]: ...


class ChatGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document_ids: list[UUID],
    ) -> dict[str, Any]: ...
