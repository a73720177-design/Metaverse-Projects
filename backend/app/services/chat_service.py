from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatHistoryItem, ChatRequest
from app.models.persona import PersonaProfile
from app.integrations.llm.contracts import (
    ChatGenerator,
    ChatGeneratorError,
    DocumentIndexError,
    DocumentIndexer,
    DocumentNotIndexedError,
)
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chat_repository import ChatRepository


class ChatServiceError(RuntimeError):
    pass


class ChatResourceNotFoundError(RuntimeError):
    pass


class ChatService:
    """대화 요청의 소유권을 확인하고 LLM 서비스에 위임합니다.

    자료 검색(어떤 문서의 어떤 조각을 쓸지)은 LLM 서비스가 bge-m3 임베딩으로
    수행합니다. Backend는 사용자가 접근할 수 있는 문서 후보만 추려서 넘깁니다.
    """

    def __init__(
        self,
        generator: ChatGenerator,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
        chat_repository: ChatRepository,
        indexer: DocumentIndexer | None = None,
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.chat_repository = chat_repository
        self.indexer = indexer

    async def _resolve_context(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> tuple[PersonaProfile, list[UUID]]:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ChatResourceNotFoundError("Agent not found")

        if request.document_id is not None:
            document = await self.document_repository.get(request.document_id, owner_id)
            if document is None:
                raise ChatResourceNotFoundError("Document not found")
            return persona, [request.document_id]

        # 문서를 고르지 않았으면 페르소나에 연결된 자료 전체를 후보로 넘긴다.
        return persona, list(persona.document_ids)

    async def _generate(
        self, persona: PersonaProfile, request: ChatRequest,
        document_ids: list[UUID], owner_id: UUID
    ) -> dict:
        try:
            return await self.generator.generate(persona, request, document_ids)
        except DocumentNotIndexedError as exc:
            # LLM 서비스가 재시작되어 인덱스가 비었을 때만 발생한다. 문서를 다시
            # 밀어넣고 한 번 재시도한다.
            await self._reindex(exc.document_id, owner_id)
            return await self.generator.generate(persona, request, document_ids)

    async def _reindex(self, document_id: UUID, owner_id: UUID) -> None:
        if self.indexer is None:
            raise ChatServiceError("Document index is unavailable")
        document = await self.document_repository.get(document_id, owner_id)
        if document is None:
            raise ChatResourceNotFoundError("Document not found")
        try:
            await self.indexer.index(document)
        except DocumentIndexError as exc:
            raise ChatServiceError("Document indexing failed") from exc

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatHistoryItem:
        persona, document_ids = await self._resolve_context(agent_id, request, owner_id)
        try:
            generated = await self._generate(persona, request, document_ids, owner_id)
            sources = generated.get("sources") or []
            chat = ChatHistoryItem.model_validate(
                {
                    **generated,
                    "message_id": uuid4(),
                    "owner_id": owner_id,
                    "agent_id": agent_id,
                    # 어떤 문서가 쓰였는지는 LLM 서비스의 검색 결과가 알려준다.
                    "document_id": request.document_id or _first_document_id(sources),
                    "message": request.message,
                }
            )
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc
        await self.chat_repository.save(chat)
        return chat

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


def _first_document_id(sources: list) -> UUID | None:
    for source in sources:
        raw = source.get("document_id") if isinstance(source, dict) else None
        if raw:
            try:
                return UUID(str(raw))
            except ValueError:
                return None
    return None
