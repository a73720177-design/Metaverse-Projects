from typing import Any, Protocol

from app.models.persona import PersonaCreateRequest


class PersonaGeneratorError(RuntimeError):
    """Normalized error exposed by an LLM implementation to the backend."""


class PersonaGenerator(Protocol):
    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]: ...
