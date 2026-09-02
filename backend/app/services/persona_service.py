from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.persona import PersonaCreateRequest, PersonaHistoryItem, PersonaProfile
from app.integrations.llm.contracts import PersonaGenerator, PersonaGeneratorError
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository


class UpstreamServiceError(RuntimeError):
    pass


class PersonaNotFoundError(RuntimeError):
    pass


class PersonaDocumentNotFoundError(RuntimeError):
    pass


class PersonaService:
    """Backend orchestration only; generation and persistence are delegated."""

    def __init__(self, generator: PersonaGenerator, repository: AgentRepository,
                 document_repository: DocumentRepository | None = None) -> None:
        self.generator = generator
        self.repository = repository
        self.document_repository = document_repository

    async def create(self, request: PersonaCreateRequest, owner_id: UUID) -> PersonaProfile:
        if len(set(request.document_ids)) != len(request.document_ids):
            raise PersonaDocumentNotFoundError("Duplicate document IDs are not allowed")
        if request.document_ids:
            if self.document_repository is None:
                raise PersonaDocumentNotFoundError("Document repository is not configured")
            for document_id in request.document_ids:
                if await self.document_repository.get(document_id, owner_id) is None:
                    raise PersonaDocumentNotFoundError("Document not found")
        try:
            generated = await self.generator.generate(request)
            persona = PersonaProfile.model_validate(
                {
                    **generated,
                    "agent_id": uuid4(),
                    "name": request.name,
                    "description": request.description,
                    "document_ids": request.document_ids,
                }
            )
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc

        await self.repository.save(persona, owner_id)
        return persona

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        return await self.repository.get(agent_id, owner_id)

    async def list_active(self, owner_id: UUID) -> list[PersonaHistoryItem]:
        return await self.repository.list(owner_id, deleted=False)

    async def list_trash(self, owner_id: UUID) -> list[PersonaHistoryItem]:
        return await self.repository.list(owner_id, deleted=True)

    async def move_to_trash(self, agent_id: UUID, owner_id: UUID) -> PersonaHistoryItem:
        if await self.repository.get(agent_id, owner_id) is None:
            raise PersonaNotFoundError("Active persona not found")
        persona = await self.repository.set_deleted(agent_id, owner_id, deleted=True)
        assert persona is not None
        return persona

    async def restore(self, agent_id: UUID, owner_id: UUID) -> PersonaHistoryItem:
        trashed_ids = {
            persona.agent_id for persona in await self.repository.list(owner_id, deleted=True)
        }
        if agent_id not in trashed_ids:
            raise PersonaNotFoundError("Trashed persona not found")
        persona = await self.repository.set_deleted(agent_id, owner_id, deleted=False)
        assert persona is not None
        return persona

    async def permanently_delete(self, agent_id: UUID, owner_id: UUID) -> None:
        if not await self.repository.permanently_delete(agent_id, owner_id):
            raise PersonaNotFoundError("Trashed persona not found")
