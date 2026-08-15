from typing import Any, Protocol
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile


class ChatGeneratorError(RuntimeError):
    pass


class ChatGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document: DocumentParseResponse | None,
    ) -> dict[str, Any]: ...
