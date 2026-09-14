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
from app.models.review import ReviewSource
from app.models.summary import SummaryStyle


class LocalPersonaGenerator:
    """Backend가 받은 입력을 그대로 사용해, LLM 호출 없이 페르소나를 만든다.

    PERSONA_FALLBACK_LOCAL=true일 때 개발용 대체 경로로 쓴다(로컬 모델이
    잘못된 JSON을 반환해도 페르소나 생성 자체는 막히지 않도록).
    """

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        if not request.description.strip():
            raise PersonaGeneratorError("평가자 설명이 필요합니다.")
        return {
            "role": "Evaluator",
            "expertise": [],
            "evaluation_style": [],
        }


class HttpPersonaGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        try:
            return await self.client.post_json(
                "/personas",
                request.model_dump(
                    mode="json",
                    exclude={"document_ids", "gender", "age", "role", "focus", "question_strategy"},
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
            if document is not None:
                generated["sources"] = [
                    ReviewSource(
                        document_id=section.source_document_id or document.document_id,
                        filename=section.source_filename or document.filename,
                        page=(section.index if (section.source_document_type or document.document_type) in {"pdf", "pptx"} else None),
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
