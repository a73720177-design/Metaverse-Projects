from typing import Any

from app.config import get_chat_output_token_budgets
from app.integrations.llm.client import HttpLlmClient, LlmServiceConnectionError, LlmServiceResponseError
from app.integrations.llm.contracts import (
    ChatGeneratorError,
    EmbeddingGeneratorError,
    PersonaGeneratorError,
    ReviewGeneratorError,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.review import ReviewSource


class HttpPersonaGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        try:
            return await self.client.post_json(
                "/personas",
                request.model_dump(
                    mode="json", exclude={"document_ids", "gender", "age"}
                ),
            )
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise PersonaGeneratorError(str(exc)) from exc


class HttpReviewGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, persona: PersonaProfile, document: DocumentParseResponse,
                       instructions: str | None) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "document": document.model_dump(
                mode="json", exclude={"saved_path"}, exclude_none=True
            ),
            "instructions": instructions,
        }
        try:
            return await self.client.post_json("/reviews", payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ReviewGeneratorError(str(exc)) from exc


class HttpChatGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    @staticmethod
    def _max_output_tokens(request: ChatRequest) -> int:
        return get_chat_output_token_budgets()[request.response_detail.value]

    async def generate(self, persona: PersonaProfile, request: ChatRequest,
                       document: DocumentParseResponse | None) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            "max_output_tokens": self._max_output_tokens(request),
            # full_text already contains only selected RAG chunks. Omitting
            # sections prevents the same source text from being sent twice.
            "document": document.model_dump(
                mode="json", exclude={"saved_path", "sections"}
            ) if document else None,
        }
        try:
            generated = await self.client.post_json("/chat", payload)
            if document is not None:
                generated["sources"] = [
                    ReviewSource(
                        document_id=section.source_document_id or document.document_id,
                        filename=section.source_filename or document.filename,
                        page=(section.index if document.document_type in {"pdf", "pptx"} else None),
                        excerpt=section.text[:500],
                    ).model_dump(mode="json")
                    for section in document.sections
                ]
            else:
                generated["sources"] = []
            return generated
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ChatGeneratorError(str(exc)) from exc

    async def stream(self, persona: PersonaProfile, request: ChatRequest,
                     document: DocumentParseResponse | None):
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            "max_output_tokens": self._max_output_tokens(request),
            "document": document.model_dump(
                mode="json", exclude={"saved_path", "sections"}
            ) if document else None,
        }
        try:
            async for token in self.client.stream_sse("/chat/stream", payload):
                yield token
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ChatGeneratorError(str(exc)) from exc


class HttpEmbeddingGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.post_json("/embeddings", {"texts": texts})
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise EmbeddingGeneratorError(str(exc)) from exc
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list):
            raise EmbeddingGeneratorError("LLM 서비스가 잘못된 임베딩 응답을 반환했습니다.")
        return embeddings
