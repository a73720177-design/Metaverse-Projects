from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatHistoryItem, ChatRequest
from app.integrations.llm.contracts import ChatGenerator, ChatGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chat_repository import ChatRepository


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
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository
        self.chat_repository = chat_repository

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatHistoryItem:
        persona = await self.agent_repository.get(agent_id, owner_id)
        if persona is None:
            raise ChatResourceNotFoundError("Agent not found")
        document = None
        if request.document_id is not None:
            document = await self.document_repository.get(request.document_id, owner_id)
            if document is None:
                raise ChatResourceNotFoundError("Document not found")
        try:
            generated = await self.generator.generate(persona, request, document)
            chat = ChatHistoryItem.model_validate(
                {
                    **generated,
                    "message_id": uuid4(),
                    "owner_id": owner_id,
                    "agent_id": agent_id,
                    "document_id": request.document_id,
                    "message": request.message,
                }
            )
            await self.chat_repository.save(chat)
            return chat
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc

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
