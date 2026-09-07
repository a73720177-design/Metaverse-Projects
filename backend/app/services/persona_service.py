from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.persona import (
    PersonaCreateRequest, PersonaHistoryItem, PersonaProfile, PersonaUpdateRequest,
)
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
                    "gender": request.gender,
                    "age": request.age,
                    "document_ids": request.document_ids,
                }
            )
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc

        await self.repository.save(persona, owner_id)
        return persona

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        return await self.repository.get(agent_id, owner_id)

    async def update(
        self, agent_id: UUID, request: PersonaUpdateRequest, owner_id: UUID
    ) -> PersonaProfile:
        current = await self.repository.get(agent_id, owner_id)
        if current is None:
            raise PersonaNotFoundError("질문자를 찾을 수 없습니다.")
        if len(set(request.document_ids)) != len(request.document_ids):
            raise PersonaDocumentNotFoundError("중복된 자료는 연결할 수 없습니다.")
        if self.document_repository is None:
            raise PersonaDocumentNotFoundError("문서 저장소가 설정되지 않았습니다.")
        for document_id in request.document_ids:
            if await self.document_repository.get(document_id, owner_id) is None:
                raise PersonaDocumentNotFoundError("연결할 자료를 찾을 수 없습니다.")
        updated = current.model_copy(update={
            "name": request.name,
            "description": request.description,
            "gender": request.gender,
            "age": request.age,
            "document_ids": request.document_ids,
        })
        await self.repository.save(updated, owner_id)
        return updated

    async def update_documents(
        self, agent_id: UUID, document_ids: list[UUID], owner_id: UUID
    ) -> PersonaProfile:
        if len(set(document_ids)) != len(document_ids):
            raise PersonaDocumentNotFoundError("중복된 자료는 연결할 수 없습니다.")
        if await self.repository.get(agent_id, owner_id) is None:
            raise PersonaNotFoundError("질문자를 찾을 수 없습니다.")
        if self.document_repository is None:
            raise PersonaDocumentNotFoundError("문서 저장소가 설정되지 않았습니다.")
        for document_id in document_ids:
            if await self.document_repository.get(document_id, owner_id) is None:
                raise PersonaDocumentNotFoundError("연결할 자료를 찾을 수 없습니다.")
        updated = await self.repository.set_documents(agent_id, owner_id, document_ids)
        if updated is None:
            raise PersonaNotFoundError("질문자를 찾을 수 없습니다.")
        return updated

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
