from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.summary import SummaryStyle


class PersonaGeneratorError(RuntimeError):
    pass


class ReviewGeneratorError(RuntimeError):
    pass


class ChatGeneratorError(RuntimeError):
    pass


class SummaryGeneratorError(RuntimeError):
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
        history: list[ChatTurn],
    ) -> dict[str, Any]: ...

    def stream(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document: DocumentParseResponse | None,
        history: list[ChatTurn],
    ) -> AsyncIterator[str]: ...


class SummaryGenerator(Protocol):
    async def generate(
        self,
        document: DocumentParseResponse,
        style: SummaryStyle,
        persona: PersonaProfile | None,
    ) -> dict[str, Any]: ...
