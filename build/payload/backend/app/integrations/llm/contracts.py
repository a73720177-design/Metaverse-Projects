from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.summary import SummaryStyle
from app.models.llm import DEFAULT_LLM_MODEL, LlmModel


class PersonaGeneratorError(RuntimeError):
    pass


class ReviewGeneratorError(RuntimeError):
    pass


class ChatGeneratorError(RuntimeError):
    pass


class SummaryGeneratorError(RuntimeError):
    pass


class PersonaGenerationRequest(BaseModel):
    """Internal wire contract; reference text is never part of the saved description."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    reference_context: str = Field(default="", max_length=3000)
    model: LlmModel = DEFAULT_LLM_MODEL


class PersonaGenerator(Protocol):
    async def generate(self, request: PersonaGenerationRequest) -> dict[str, Any]: ...


class ReviewGenerator(Protocol):
    async def generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
        model: LlmModel = DEFAULT_LLM_MODEL,
    ) -> dict[str, Any]: ...


class QuestionGenerator(Protocol):
    async def generate(
        self, persona: PersonaProfile, document: DocumentParseResponse,
        instructions: str | None, *, question_count: int = 5,
        excluded_questions: list[str] | None = None,
        model: LlmModel = DEFAULT_LLM_MODEL,
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
