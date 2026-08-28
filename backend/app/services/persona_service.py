from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.integrations.llm.contracts import PersonaGenerator, PersonaGeneratorError
from app.repositories.agent_repository import AgentRepository


class UpstreamServiceError(RuntimeError):
    pass


class PersonaService:
    """Backend orchestration only; generation and persistence are delegated."""

    def __init__(self, generator: PersonaGenerator, repository: AgentRepository) -> None:
        self.generator = generator
        self.repository = repository

    async def create(self, request: PersonaCreateRequest, owner_id: UUID) -> PersonaProfile:
        try:
            generated = await self.generator.generate(request)
            persona = PersonaProfile.model_validate(
                {
                    **generated,
                    "agent_id": uuid4(),
                    "name": request.name,
                    "description": request.description,
                }
            )
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc

        await self.repository.save(persona, owner_id)
        return persona

    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
        return await self.repository.get(agent_id, owner_id)
