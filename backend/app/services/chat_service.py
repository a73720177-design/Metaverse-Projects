import asyncio
import logging
from time import perf_counter
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.config import get_grounding_mode, get_grounding_min_score
from app.models.chat import ChatHistoryItem, ChatRequest, ChatTiming, ChatTurn, Grounding
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.review import ReviewSource
from app.integrations.llm.contracts import ChatGenerator, ChatGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chat_repository import ChatRepository
from app.services.grounding_service import GroundingChecker
from app.services.rag_service import DocumentContextSelector, should_use_document
from app.services.vector_rag import VectorRag, vector_enabled


logger = logging.getLogger(__name__)
_NO_GROUNDED_CONTEXT_TYPE = "no_grounded_context"
_NO_GROUNDED_CONTEXT_ANSWER = (
    "첨부된 자료에서 이 질문을 뒷받침할 근거를 찾지 못했습니다. "
    "관련 내용이 있는 자료나 구체적인 페이지를 추가해 주세요."
)


class ChatServiceError(RuntimeError):
    pass


class ChatResourceNotFoundError(RuntimeError):
    pass


class ChatService:
    def __init__(
        self,
        generator: ChatGenerator,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
        chat_repository: ChatRepository,
        context_selector: DocumentContextSelector | None = None,
        history_turns: int = 6,
        grounding_checker: GroundingChecker | None = None,
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.chat_repository = chat_repository
        self.context_selector = context_selector or DocumentContextSelector()
        self.history_turns = history_turns
        self.grounding_checker = grounding_checker or GroundingChecker()

    async def _resolve_context(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> tuple[PersonaProfile, ChatRequest, DocumentParseResponse | None, list[ChatTurn]]:
        persona, previous_chats = await asyncio.gather(
            self.agent_repository.get(agent_id, owner_id),
            self.chat_repository.list_recent(owner_id, agent_id, self.history_turns),
        )
        if persona is None:
            raise ChatResourceNotFoundError("Agent not found")
        history: list[ChatTurn] = []
        for item in previous_chats:
            history.append(ChatTurn(role="user", content=item.message))
            history.append(ChatTurn(role="assistant", content=item.answer))
        # A bare follow-up ("그건 무슨 뜻이야?") carries no retrievable terms on
        # its own, so fold in the last user turn before scoring/searching chunks.
        # The LLM still only sees the untouched current message.
        retrieval_query = (
            f"{previous_chats[-1].message} {request.message}"
            if previous_chats
            else request.message
        )
        previous_used_document = bool(previous_chats) and previous_chats[-1].document_id is not None
        requested_ids = list(dict.fromkeys(
            [*request.document_ids, *persona.document_ids]
            if request.document_ids
            else ([request.document_id] if request.document_id else persona.document_ids)
        ))
        candidates = []
        if requested_ids:
            fetched = await asyncio.gather(*(
                self.document_repository.get(document_id, owner_id)
                for document_id in requested_ids
            ))
            if any(item is None for item in fetched):
                raise ChatResourceNotFoundError("Document not found")
            candidates = [item for item in fetched if item is not None]
        effective_request = request.model_copy(update={
            "document_id": candidates[0].document_id if candidates else None,
            "document_ids": [item.document_id for item in candidates],
        })

        document = None
        if candidates and should_use_document(
            effective_request.message,
            effective_request.document_id,
            previous_used_document=previous_used_document,
        ):
            if vector_enabled():
                try:
                    document = await VectorRag().select_context(
                        candidates, retrieval_query, owner_id
                    )
                except Exception:
                    logger.warning(
                        "Vector search failed; falling back to lexical RAG",
                        exc_info=True,
                    )
                if document is not None:
                    return persona, effective_request, document, history
            ranked = sorted(
                candidates,
                key=lambda item: self.context_selector.relevance_score(item, retrieval_query),
                reverse=True,
            )[:4]
            selected_documents = [
                selected
                for item in ranked
                if (selected := self.context_selector.select(item, retrieval_query))
                is not None
            ]
            if not selected_documents:
                return persona, effective_request, ranked[0].model_copy(update={
                    "filename": "검색 결과 없음",
                    "document_type": _NO_GROUNDED_CONTEXT_TYPE,
                    "sections": [],
                    "full_text": "",
                }), history
            sections = []
            blocks = []
            used = 0
            limit = self.context_selector.max_context_chars
            for item in selected_documents:
                for section in item.sections:
                    block = f"[파일: {item.filename} / 구간 {section.index}]\n{section.text}"
                    remaining = limit - used - (2 if blocks else 0)
                    if remaining <= 0:
                        break
                    block = block[:remaining]
                    blocks.append(block)
                    sections.append(section.model_copy(update={
                        "text": block,
                        "source_document_id": item.document_id,
                        "source_filename": item.filename,
                        "source_document_type": item.document_type,
                    }))
                    used += len(block) + (2 if len(blocks) > 1 else 0)
                if used >= limit:
                    break
            document = ranked[0].model_copy(update={
                "filename": "발표 프로젝트 통합 자료",
                "sections": sections,
                "full_text": "\n\n".join(blocks),
            })
        return persona, effective_request, document, history

    async def _apply_grounding(
        self, answer: str, document: DocumentParseResponse | None
    ) -> tuple[str, Grounding | None]:
        mode = get_grounding_mode()
        if mode == "off" or document is None:
            return answer, None
        grounding = await self.grounding_checker.check(answer, document)
        if mode == "strict" and grounding.score < get_grounding_min_score():
            answer = f"{answer}\n\n※ 이 답변의 일부는 첨부 문서에서 확인되지 않았습니다."
        return answer, grounding

    @staticmethod
    def _sources(document: DocumentParseResponse | None) -> list[ReviewSource]:
        if document is None:
            return []
        return [
            ReviewSource(
                document_id=section.source_document_id or document.document_id,
                filename=section.source_filename or document.filename,
                page=(
                    section.index
                    if (section.source_document_type or document.document_type)
                    in {"pdf", "pptx"}
                    else None
                ),
                excerpt=section.text[:500],
            )
            for section in document.sections
        ]

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatHistoryItem:
        started = perf_counter()
        persona, effective_request, document, history = await self._resolve_context(
            agent_id, request, owner_id
        )
        context_finished = perf_counter()
        if document is not None and document.document_type == _NO_GROUNDED_CONTEXT_TYPE:
            chat = ChatHistoryItem(
                message_id=uuid4(), owner_id=owner_id, agent_id=agent_id,
                document_id=effective_request.document_id, message=request.message,
                answer=_NO_GROUNDED_CONTEXT_ANSWER, sources=[],
                timing=ChatTiming(
                    context_ms=round((context_finished - started) * 1000),
                    total_ms=round((context_finished - started) * 1000),
                    output_characters=len(_NO_GROUNDED_CONTEXT_ANSWER), output_lines=1,
                ),
            )
            await self.chat_repository.save(chat)
            return chat
        try:
            generated = await self.generator.generate(persona, effective_request, document, history)
            generation_finished = perf_counter()
            answer, grounding = await self._apply_grounding(
                generated.get("answer", ""), document
            )
            generated = {**generated, "answer": answer, "grounding": grounding}
            chat = ChatHistoryItem.model_validate(
                {
                    **generated,
                    "message_id": uuid4(),
                    "owner_id": owner_id,
                    "agent_id": agent_id,
                    "document_id": effective_request.document_id,
                    "message": request.message,
                    "timing": ChatTiming(
                        context_ms=round((context_finished - started) * 1000),
                        first_content_latency_ms=round(
                            (generation_finished - context_finished) * 1000
                        ),
                        generation_ms=round((generation_finished - context_finished) * 1000),
                        output_characters=len(answer),
                        output_lines=len(answer.splitlines()) or 1,
                    ),
                }
            )
            save_started = perf_counter()
            await self.chat_repository.save(chat)
            completed = perf_counter()
            chat = chat.model_copy(update={"timing": chat.timing.model_copy(update={
                "save_ms": round((completed - save_started) * 1000),
                "total_ms": round((completed - started) * 1000),
            })})
            await self.chat_repository.save(chat)
            return chat
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc

    async def open_stream(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> AsyncIterator[dict[str, Any]]:
        started = perf_counter()
        persona, effective_request, document, history = await self._resolve_context(
            agent_id, request, owner_id
        )
        context_finished = perf_counter()
        stream_method = getattr(self.generator, "stream", None)
        if stream_method is None:
            raise ChatServiceError("Streaming chat is unavailable")

        async def events() -> AsyncIterator[dict[str, Any]]:
            if document is not None and document.document_type == _NO_GROUNDED_CONTEXT_TYPE:
                chat = ChatHistoryItem(
                    message_id=uuid4(), owner_id=owner_id, agent_id=agent_id,
                    document_id=effective_request.document_id, message=request.message,
                    answer=_NO_GROUNDED_CONTEXT_ANSWER, sources=[],
                    timing=ChatTiming(
                        context_ms=round((context_finished - started) * 1000),
                        total_ms=round((perf_counter() - started) * 1000),
                        output_characters=len(_NO_GROUNDED_CONTEXT_ANSWER), output_lines=1,
                    ),
                )
                await self.chat_repository.save(chat)
                yield {"event": "token", "data": {"token": _NO_GROUNDED_CONTEXT_ANSWER}}
                yield {"event": "done", "data": chat.model_dump(mode="json", exclude={"owner_id"})}
                return
            parts: list[str] = []
            llm_started = perf_counter()
            first_content_at: float | None = None
            try:
                async for token in stream_method(persona, effective_request, document, history):
                    if token and first_content_at is None:
                        first_content_at = perf_counter()
                    parts.append(token)
                    yield {"event": "token", "data": {"token": token}}
                generation_finished = perf_counter()
                answer = "".join(parts).strip()
                if not answer:
                    raise ChatServiceError("Chat generator returned an empty response")
                # Grounding is checked once all tokens are in, right before the
                # `done` event is built, so the live token stream itself is
                # never delayed by the check.
                answer, grounding = await self._apply_grounding(answer, document)
                chat = ChatHistoryItem(
                    message_id=uuid4(),
                    owner_id=owner_id,
                    agent_id=agent_id,
                    document_id=effective_request.document_id,
                    message=request.message,
                    answer=answer,
                    sources=self._sources(document),
                    grounding=grounding,
                    timing=ChatTiming(
                        context_ms=round((context_finished - started) * 1000),
                        first_content_latency_ms=round(
                            ((first_content_at or generation_finished) - llm_started) * 1000
                        ),
                        generation_ms=round(
                            (generation_finished - (first_content_at or llm_started)) * 1000
                        ),
                        output_characters=len(answer),
                        output_lines=len(answer.splitlines()) or 1,
                    ),
                )
                save_started = perf_counter()
                await self.chat_repository.save(chat)
                completed = perf_counter()
                chat = chat.model_copy(update={"timing": chat.timing.model_copy(update={
                    "save_ms": round((completed - save_started) * 1000),
                    "total_ms": round((completed - started) * 1000),
                })})
                await self.chat_repository.save(chat)
                yield {
                    "event": "done",
                    "data": chat.model_dump(mode="json", exclude={"owner_id"}),
                }
            except ChatGeneratorError as exc:
                raise ChatServiceError("Chat stream failed") from exc

        return events()

    async def list_active(self, owner_id: UUID) -> list[ChatHistoryItem]:
        return await self.chat_repository.list(owner_id, deleted=False)

    async def list_trash(self, owner_id: UUID) -> list[ChatHistoryItem]:
        return await self.chat_repository.list(owner_id, deleted=True)

    async def move_to_trash(self, message_id: UUID, owner_id: UUID) -> ChatHistoryItem:
        chat = await self.chat_repository.get(message_id, owner_id)
        if chat is None or chat.deleted_at is not None:
            raise ChatResourceNotFoundError("Active chat not found")
        updated = await self.chat_repository.set_deleted(message_id, owner_id, deleted=True)
        assert updated is not None
        return updated

    async def restore(self, message_id: UUID, owner_id: UUID) -> ChatHistoryItem:
        chat = await self.chat_repository.get(message_id, owner_id)
        if chat is None or chat.deleted_at is None:
            raise ChatResourceNotFoundError("Trashed chat not found")
        updated = await self.chat_repository.set_deleted(message_id, owner_id, deleted=False)
        assert updated is not None
        return updated

    async def permanently_delete(self, message_id: UUID, owner_id: UUID) -> None:
        if not await self.chat_repository.permanently_delete(message_id, owner_id):
            raise ChatResourceNotFoundError("Trashed chat not found")
