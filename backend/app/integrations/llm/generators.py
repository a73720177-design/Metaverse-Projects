from contextlib import aclosing
from typing import Any

from app.config import get_chat_output_token_budgets
from app.integrations.llm.client import HttpLlmClient, LlmServiceConnectionError, LlmServiceResponseError
from app.integrations.llm.contracts import (
    ChatGeneratorError,
    PersonaGeneratorError,
    PersonaGenerationRequest,
    ReviewGeneratorError,
    SummaryGeneratorError,
)
from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.summary import SummaryStyle
from app.services.content_budget import document_assessment
from app.services.rag_service import sources_from_citations


class HttpPersonaGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, request: PersonaGenerationRequest) -> dict[str, Any]:
        try:
            return await self.client.post_json(
                "/personas",
                request.model_dump(mode="json", exclude_defaults=True),
            )
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise PersonaGeneratorError(str(exc)) from exc


class LocalPersonaGenerator:
    """LLM 호출 없이 Backend 입력만으로 페르소나를 만든다.

    PERSONA_FALLBACK_LOCAL=true일 때만 쓰인다 — LLM 서비스가 없거나 느린
    환경에서 페르소나 생성이 전체 흐름을 막지 않게 하는 탈출구다.
    """

    async def generate(self, request: PersonaGenerationRequest) -> dict[str, Any]:
        if not request.description.strip():
            raise PersonaGeneratorError("평가자 설명이 필요합니다.")
        return {
            "role": "Evaluator",
            "expertise": [],
            "evaluation_style": [],
        }


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


class HttpQuestionGenerator:
    def __init__(self, client: HttpLlmClient):
        self.client = client

    async def generate(self, persona, document, instructions, *, question_count=5, excluded_questions=None):
        evidence = [{"id": f"e{i}",
                     "scope": "presentation" if section.text.startswith("[발표 자료:") else "persona_reference",
                     "text": section.text}
                    for i, section in enumerate(document.sections, 1)]
        try:
            return await self.client.post_json("/practice/questions", {
                "persona": persona.model_dump(mode="json"),
                "question_count": question_count, "evidence": evidence,
                "excluded_questions": (excluded_questions or [])[-40:],
            })
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ReviewGeneratorError("예상 질문 생성 응답을 확인할 수 없습니다.") from exc


class HttpChatGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    @staticmethod
    def _max_output_tokens(request: ChatRequest) -> int:
        return get_chat_output_token_budgets()[request.response_detail.value]

    @staticmethod
    def _history_payload(history: list[ChatTurn]) -> dict[str, Any]:
        # The persisted conversation stays intact. Only this wire copy is bounded
        # to schemas_v1.ChatTurn (2,000 chars, 20 turns) and a total text budget.
        remaining = 12_000
        selected = []
        truncated = len(history) > 20
        marker = "[앞부분 생략]\n"
        for turn in reversed(history[-20:]):
            if remaining <= len(marker):
                truncated = True
                break
            content = turn.content
            if not content.strip():
                truncated = True
                continue
            limit = min(2000, remaining)
            if len(content) > limit:
                content = marker + content[-(limit - len(marker)):]
                truncated = True
            selected.append({"role": turn.role, "content": content})
            remaining -= len(content)
        return {"history": list(reversed(selected)), "history_truncated": truncated}

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
            **self._history_payload(history),
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
            **self._history_payload(history),
        }
        try:
            async with aclosing(self.client.stream_sse("/chat/stream", payload)) as upstream:
                async for token in upstream:
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
            "topic_limit": document_assessment(document).output_limit,
            "persona": persona.model_dump(mode="json") if persona else None,
        }
        try:
            return await self.client.post_json("/summaries", payload)
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise SummaryGeneratorError(str(exc)) from exc
