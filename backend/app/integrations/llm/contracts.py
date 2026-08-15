from typing import Any, Protocol

from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile


class PersonaGeneratorError(RuntimeError):
    pass


class ReviewGeneratorError(RuntimeError):
    pass


class ChatGeneratorError(RuntimeError):
    pass


class PersonaGenerator(Protocol):
    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]: ...


class ReviewGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
    ) -> dict[str, Any]: ...


class ChatGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document: DocumentParseResponse | None,
    ) -> dict[str, Any]: ...
