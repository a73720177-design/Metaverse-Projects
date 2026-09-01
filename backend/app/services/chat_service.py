from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatHistoryItem, ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.review import ReviewSource
from app.integrations.llm.contracts import ChatGenerator, ChatGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chat_repository import ChatRepository
from app.services.rag_service import DocumentContextSelector, should_use_document


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
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.chat_repository = chat_repository
        self.context_selector = context_selector or DocumentContextSelector()

    async def _resolve_context(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> tuple[PersonaProfile, ChatRequest, DocumentParseResponse | None]:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ChatResourceNotFoundError("Agent not found")
        effective_request = request
        source_document = None
        if request.document_id is None and persona.document_ids:
            candidates = [
                candidate
                for document_id in persona.document_ids
                if (candidate := await self.document_repository.get(document_id, owner_id))
                is not None
            ]
            if candidates:
                source_document = max(
                    candidates,
                    key=lambda item: self.context_selector.relevance_score(
                        item, request.message
                    ),
                )
                effective_request = request.model_copy(
                    update={"document_id": source_document.document_id}
                )
        elif effective_request.document_id is not None:
            source_document = await self.document_repository.get(
                effective_request.document_id, owner_id
            )
            if source_document is None:
                raise ChatResourceNotFoundError("Document not found")

        document = None
        if source_document is not None:
            if should_use_document(effective_request.message, effective_request.document_id):
                document = self.context_selector.select(
                    source_document, effective_request.message
                )
        return persona, effective_request, document

    @staticmethod
    def _sources(document: DocumentParseResponse | None) -> list[ReviewSource]:
        if document is None:
            return []
        return [
            ReviewSource(
                document_id=document.document_id,
                filename=document.filename,
                page=(section.index if document.document_type in {"pdf", "pptx"} else None),
                excerpt=section.text[:500],
            )
            for section in document.sections
        ]

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatHistoryItem:
        persona, effective_request, document = await self._resolve_context(
            agent_id, request, owner_id
        )
        try:
            generated = await self.generator.generate(persona, effective_request, document)
            chat = ChatHistoryItem.model_validate(
                {
                    **generated,
                    "message_id": uuid4(),
                    "owner_id": owner_id,
                    "agent_id": agent_id,
                    "document_id": effective_request.document_id,
                    "message": request.message,
                }
            )
            await self.chat_repository.save(chat)
            return chat
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc

    async def open_stream(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> AsyncIterator[dict[str, Any]]:
        persona, effective_request, document = await self._resolve_context(
            agent_id, request, owner_id
        )
        stream_method = getattr(self.generator, "stream", None)
        if stream_method is None:
            raise ChatServiceError("Streaming chat is unavailable")

        async def events() -> AsyncIterator[dict[str, Any]]:
            parts: list[str] = []
            try:
                async for token in stream_method(persona, effective_request, document):
                    parts.append(token)
                    yield {"event": "token", "data": {"token": token}}
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
                )
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
