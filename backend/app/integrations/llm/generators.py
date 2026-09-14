from typing import Any

from app.config import get_chat_output_token_budgets
from app.integrations.llm.client import HttpLlmClient, LlmServiceConnectionError, LlmServiceResponseError
from app.integrations.llm.contracts import (
    ChatGeneratorError,
    PersonaGeneratorError,
    ReviewGeneratorError,
    SummaryGeneratorError,
)
from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.summary import SummaryStyle
from app.services.rag_service import sources_from_citations


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
    def __init__(self, client: HttpLlmClient, endpoint: str = "/reviews") -> None:
        self.client = client
        self.endpoint = endpoint

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
            return await self.client.post_json(self.endpoint, payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ReviewGeneratorError(str(exc)) from exc


class HttpChatGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    @staticmethod
    def _max_output_tokens(request: ChatRequest) -> int:
        return get_chat_output_token_budgets()[request.response_detail.value]

    async def generate(self, persona: PersonaProfile, request: ChatRequest,
                       document: DocumentParseResponse | None,
                       history: list[ChatTurn]) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            "max_output_tokens": self._max_output_tokens(request),
            # full_text already contains only selected RAG chunks. Omitting
            # sections prevents the same source text from being sent twice.
            "document": document.model_dump(
                mode="json", exclude={"saved_path", "sections"}
            ) if document else None,
            "history": [turn.model_dump(mode="json") for turn in history],
        }
        try:
            generated = await self.client.post_json("/chat", payload)
            # 답변이 실제로 인용한 [근거 N] 청크만 sources로 좁힌다(Phase 8).
            # 마커가 없으면 sources_from_citations가 검색된 전부로 폴백한다.
            generated["sources"] = [
                source.model_dump(mode="json")
                for source in sources_from_citations(generated.get("answer", ""), document)
            ]
            return generated
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ChatGeneratorError(str(exc)) from exc

    async def stream(self, persona: PersonaProfile, request: ChatRequest,
                     document: DocumentParseResponse | None,
                     history: list[ChatTurn]):
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            "max_output_tokens": self._max_output_tokens(request),
            "document": document.model_dump(
                mode="json", exclude={"saved_path", "sections"}
            ) if document else None,
            "history": [turn.model_dump(mode="json") for turn in history],
        }
        try:
            async for token in self.client.stream_sse("/chat/stream", payload):
                yield token
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ChatGeneratorError(str(exc)) from exc


class HttpSummaryGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, document: DocumentParseResponse, style: SummaryStyle,
                       persona: PersonaProfile | None) -> dict[str, Any]:
        payload = {
            "document": document.model_dump(
                mode="json", exclude={"saved_path"}, exclude_none=True
            ),
            "style": style.value,
            "persona": persona.model_dump(mode="json") if persona else None,
        }
        try:
            return await self.client.post_json("/summaries", payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise SummaryGeneratorError(str(exc)) from exc
