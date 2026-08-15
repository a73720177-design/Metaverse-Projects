from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.ports.agent_repository import AgentRepository
from app.ports.persona_generator import PersonaGenerator, PersonaGeneratorError


class UpstreamServiceError(RuntimeError):
    pass


class PersonaService:
    """Backend orchestration only; generation and persistence are delegated."""

    def __init__(self, generator: PersonaGenerator, repository: AgentRepository) -> None:
        self.generator = generator
        self.repository = repository

    async def create(self, request: PersonaCreateRequest) -> PersonaProfile:
        try:
            generated = await self.generator.generate(request)
            persona = PersonaProfile.model_validate(
                {**generated, "agent_id": uuid4(), "name": request.name}
            )
        except (PersonaGeneratorError, ValidationError) as exc:
            raise UpstreamServiceError("Persona generator returned an invalid response") from exc

        await self.repository.save(persona)
        return persona

    async def get(self, agent_id: UUID) -> PersonaProfile | None:
        return await self.repository.get(agent_id)
