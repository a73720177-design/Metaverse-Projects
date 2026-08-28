from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.chat import ChatRequest, ChatResponse
from app.integrations.llm.contracts import ChatGenerator, ChatGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository


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
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository

    async def reply(
        self, agent_id: UUID, request: ChatRequest, owner_id: UUID
    ) -> ChatResponse:
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
            return ChatResponse.model_validate(
                {**generated, "message_id": uuid4(), "agent_id": agent_id}
            )
        except (ChatGeneratorError, ValidationError) as exc:
            raise ChatServiceError("Chat generator returned an invalid response") from exc
