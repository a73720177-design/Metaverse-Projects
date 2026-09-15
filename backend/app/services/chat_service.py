from contextlib import aclosing
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
from app.services.rag_service import (
    DocumentContextSelector, build_retrieval_query, clean_answer_citations, combine_document_contexts,
    should_use_document, sources_from_citations, strip_citation_markers,
)
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
            self.chat_repository.list_recent(
                owner_id, agent_id, self.history_turns, request.conversation_id
            ),
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
        retrieval_query = build_retrieval_query(
            request.message, previous_chats[-1].message if previous_chats else None
        )
        previous_used_document = bool(previous_chats) and previous_chats[-1].document_id is not None
        requested_ids = list(dict.fromkeys(
            [*request.document_ids,
             *([request.document_id] if request.document_id else []),
             *persona.document_ids]
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
                    vector_rag = VectorRag()
                    if await vector_rag.has_complete_index(candidates, owner_id):
                        document = await vector_rag.select_context(
                            candidates, retrieval_query, owner_id
                        )
                    else:
                        logger.info(
                            "Chat vector index is incomplete; using lexical retrieval"
                        )
                except Exception:
                    logger.warning(
                        "Vector search failed; falling back to lexical RAG",
                    )
                if document is not None:
                    return persona, effective_request, document, history
            ranked = sorted(
                candidates,
                key=lambda item: self.context_selector.relevance_score(item, retrieval_query),
                reverse=True,
            )
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
            document = combine_document_contexts(
                selected_documents, self.context_selector.max_context_chars
            )
        return persona, effective_request, document, history

    async def _apply_grounding(
        self, answer: str, document: DocumentParseResponse | None
    ) -> tuple[str, Grounding | None]:
        mode = get_grounding_mode()
        if mode == "off" or document is None:
            return answer, None
        # 인라인 [근거 N] 마커는 청크 본문에 없는 토큰이라 lexical containment
        # 점수를 부당하게 낮춘다. 채점용 사본에서만 지우고, 저장/표시용
        # answer에는 마커를 그대로 남긴다.
        grounding = await self.grounding_checker.check(strip_citation_markers(answer), document)
        if mode == "strict" and grounding.score < get_grounding_min_score():
            answer = f"{answer}\n\n※ 이 답변의 일부는 첨부 문서에서 확인되지 않았습니다."
        return answer, grounding

    @staticmethod
    def _sources(answer: str, document: DocumentParseResponse | None) -> list[ReviewSource]:
        return sources_from_citations(answer, document)

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
                conversation_id=request.conversation_id,
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
            # 모델이 지어낸, 범위 밖 [근거 N] 마커는 sources에 없는 죽은
            # 참조이므로 저장/표시용 답변에서 지운다. generators.py가 이미
            # 같은 원문으로 sources를 필터링했으므로 순서는 상관없다.
            section_count = len(document.sections) if document is not None else 0
            raw_answer = clean_answer_citations(generated.get("answer", ""), section_count)
            answer, grounding = await self._apply_grounding(raw_answer, document)
            generated = {**generated, "answer": answer, "grounding": grounding}
            chat = ChatHistoryItem.model_validate(
                {
                    **generated,
                    "conversation_id": request.conversation_id,
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
                    conversation_id=request.conversation_id,
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
                async with aclosing(stream_method(persona, effective_request, document, history)) as upstream:
                    async for token in upstream:
                        if token and first_content_at is None:
                            first_content_at = perf_counter()
                        parts.append(token)
                        yield {"event": "token", "data": {"token": token}}
                generation_finished = perf_counter()
                answer = "".join(parts).strip()
                if not answer:
                    raise ChatServiceError("Chat generator returned an empty response")
                # 모델이 지어낸, 범위 밖 [근거 N] 마커는 sources에 없는 죽은
                # 참조이므로 저장/표시용 답변에서 지운다(이미 스트리밍된
                # 토큰 자체는 되돌릴 수 없다).
                section_count = len(document.sections) if document is not None else 0
                answer = clean_answer_citations(answer, section_count)
                # Grounding is checked once all tokens are in, right before the
                # `done` event is built, so the live token stream itself is
                # never delayed by the check.
                answer, grounding = await self._apply_grounding(answer, document)
                chat = ChatHistoryItem(
                    conversation_id=request.conversation_id,
                    message_id=uuid4(),
                    owner_id=owner_id,
                    agent_id=agent_id,
                    document_id=effective_request.document_id,
                    message=request.message,
                    answer=answer,
                    sources=self._sources(answer, document),
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
