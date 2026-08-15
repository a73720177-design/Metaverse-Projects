from typing import Any

from app.adapters.http_llm_client import (
    HttpLlmClient,
    LlmServiceConnectionError,
    LlmServiceResponseError,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.ports.chat_generator import ChatGeneratorError
from app.ports.persona_generator import PersonaGeneratorError
from app.ports.review_generator import ReviewGeneratorError


class HttpPersonaGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        try:
            return await self.client.post_json("/personas", request.model_dump(mode="json"))
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise PersonaGeneratorError(str(exc)) from exc


class HttpReviewGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
    ) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "document": document.model_dump(mode="json", exclude={"saved_path"}),
            "instructions": instructions,
        }
        try:
            return await self.client.post_json("/reviews", payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ReviewGeneratorError(str(exc)) from exc


class HttpChatGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document: DocumentParseResponse | None,
    ) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            "document": (
                document.model_dump(mode="json", exclude={"saved_path"})
                if document
                else None
            ),
        }
        try:
            return await self.client.post_json("/chat", payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ChatGeneratorError(str(exc)) from exc
