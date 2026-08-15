from typing import Any, Protocol
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile


class ReviewGeneratorError(RuntimeError):
    pass


class ReviewGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
    ) -> dict[str, Any]: ...
