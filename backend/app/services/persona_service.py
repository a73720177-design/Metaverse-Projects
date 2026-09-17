from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.persona import (
    PersonaCreateRequest, PersonaHistoryItem, PersonaProfile, PersonaUpdateRequest, EvidenceStatus,
)
from app.models.document import DocumentParseResponse
from app.services.source_evidence import normalized, select_excerpts
from app.integrations.llm.contracts import (
    PersonaGenerationRequest, PersonaGenerator, PersonaGeneratorError,
)
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

    async def _owned_documents(
        self, document_ids: list[UUID], owner_id: UUID
    ) -> list[DocumentParseResponse]:
        if len(set(document_ids)) != len(document_ids):
            raise PersonaDocumentNotFoundError("중복된 자료는 연결할 수 없습니다.")
        if not document_ids:
            return []
        if self.document_repository is None:
            raise PersonaDocumentNotFoundError("문서 저장소가 설정되지 않았습니다.")

        documents = []
        for document_id in document_ids:
            document = await self.document_repository.get(document_id, owner_id)
            if document is None:
                raise PersonaDocumentNotFoundError("연결할 자료를 찾을 수 없습니다.")
            documents.append(document)
        return documents

    @staticmethod
    def _generation_request(
        request: PersonaCreateRequest, documents: list[DocumentParseResponse]
    ) -> PersonaGenerationRequest:
        """Give the generator bounded source evidence without persisting it as description."""
        excerpts: list[str] = []
        usable = [d for d in documents if d.full_text.strip() or any(s.text.strip() for s in d.sections)]
        per_document = 3000 // max(1, len(usable))
        for document in usable:
            header = f"[{document.filename}]\n"
            available = per_document - len(header) - 2
            selected = select_excerpts(document, max(0, available - 32), request.description)
            if selected:
                excerpts.append(header + "\n…\n".join(s.text for s in selected))
        return PersonaGenerationRequest(
            name=request.name,
            description=request.description,
            reference_context="\n\n".join(excerpts)[:3000],
            model=request.model,
        )

    @staticmethod
    def _verify_traits(persona: PersonaProfile, request: PersonaGenerationRequest) -> None:
        sources = {"description": normalized(request.description),
                   "reference_context": normalized(request.reference_context)}
        for trait in [*persona.expertise, *persona.evaluation_style]:
            trait.evidence = [e for e in trait.evidence
                              if normalized(e.summary) and
                              normalized(e.summary) in sources.get(e.source_id, "")]
            if not trait.evidence:
                trait.status = EvidenceStatus.UNKNOWN
                trait.confidence = 0
            elif trait.status == "user_stated" and not any(
                e.source_id == "description" for e in trait.evidence
            ):
                trait.status = EvidenceStatus.INFERRED

    async def create(self, request: PersonaCreateRequest, owner_id: UUID) -> PersonaProfile:
        documents = await self._owned_documents(request.document_ids, owner_id)
        try:
            generation_request = self._generation_request(request, documents)
            generated = await self.generator.generate(generation_request)
            persona = PersonaProfile.model_validate(
                {
                    **generated,
                    "agent_id": uuid4(),
                    "name": request.name,
                    "description": request.description,
                    "gender": "unspecified",
                    "age": None,
                    "document_ids": request.document_ids,
                }
            )
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc

        self._verify_traits(persona, generation_request)
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
        documents = await self._owned_documents(request.document_ids, owner_id)
        try:
            generation_request = self._generation_request(request, documents)
            generated = await self.generator.generate(generation_request)
            updated = PersonaProfile.model_validate({
                **generated,
                "agent_id": current.agent_id,
                "name": request.name,
                "description": request.description,
                "gender": "unspecified",
                "age": None,
                "document_ids": request.document_ids,
            })
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc
        self._verify_traits(updated, generation_request)
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
