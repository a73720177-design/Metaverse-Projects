import asyncio
from time import perf_counter
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatHistoryItem, ChatRequest, ChatTiming
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.review import ReviewSource
from app.integrations.llm.contracts import ChatGenerator, ChatGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chat_repository import ChatRepository
from app.services.rag_service import ContextSelector, DocumentContextSelector, should_use_document


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
        context_selector: ContextSelector | None = None,
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.chat_repository = chat_repository
        self.context_selector: ContextSelector = context_selector or DocumentContextSelector()

    async def _resolve_context(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> tuple[PersonaProfile, ChatRequest, DocumentParseResponse | None]:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ChatResourceNotFoundError("Agent not found")
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
        if candidates and should_use_document(effective_request.message, effective_request.document_id):
            scores = await asyncio.gather(*(
                self.context_selector.relevance_score(item, request.message)
                for item in candidates
            ))
            ranked = [
                item
                for _, item in sorted(
                    zip(scores, candidates), key=lambda pair: pair[0], reverse=True
                )
            ][:4]
            selected_documents = await asyncio.gather(*(
                self.context_selector.select(item, request.message) for item in ranked
            ))
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
                    }))
                    used += len(block) + (2 if len(blocks) > 1 else 0)
                if used >= limit:
                    break
            document = ranked[0].model_copy(update={
                "filename": "발표 프로젝트 통합 자료",
                "sections": sections,
                "full_text": "\n\n".join(blocks),
            })
        return persona, effective_request, document

    @staticmethod
    def _sources(document: DocumentParseResponse | None) -> list[ReviewSource]:
        if document is None:
            return []
        return [
            ReviewSource(
                document_id=section.source_document_id or document.document_id,
                filename=section.source_filename or document.filename,
                page=(section.index if document.document_type in {"pdf", "pptx"} else None),
                excerpt=section.text[:500],
            )
            for section in document.sections
        ]

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatHistoryItem:
        started = perf_counter()
        persona, effective_request, document = await self._resolve_context(
            agent_id, request, owner_id
        )
        context_finished = perf_counter()
        try:
            generated = await self.generator.generate(persona, effective_request, document)
            generation_finished = perf_counter()
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
                        output_characters=len(generated.get("answer", "")),
                        output_lines=len(generated.get("answer", "").splitlines()) or 1,
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
        persona, effective_request, document = await self._resolve_context(
            agent_id, request, owner_id
        )
        context_finished = perf_counter()
        stream_method = getattr(self.generator, "stream", None)
        if stream_method is None:
            raise ChatServiceError("Streaming chat is unavailable")

        async def events() -> AsyncIterator[dict[str, Any]]:
            parts: list[str] = []
            llm_started = perf_counter()
            first_content_at: float | None = None
            try:
                async for token in stream_method(persona, effective_request, document):
                    if token and first_content_at is None:
                        first_content_at = perf_counter()
                    parts.append(token)
                    yield {"event": "token", "data": {"token": token}}
                generation_finished = perf_counter()
                answer = "".join(parts).strip()
                if not answer:
                    raise ChatServiceError("Chat generator returned an empty response")
                chat = ChatHistoryItem(
                    message_id=uuid4(),
                    owner_id=owner_id,
                    agent_id=agent_id,
                    document_id=effective_request.document_id,
                    message=request.message,
                    answer=answer,
                    sources=self._sources(document),
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
