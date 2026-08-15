import json
from pathlib import Path
from typing import Any

from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.ports.persona_generator import PersonaGeneratorError
from app.services.ollama_service import OllamaConnectionError, OllamaResponseError, OllamaService


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "persona.txt"


class OllamaPersonaGenerator:
    """Reference adapter owned/replaced by the LLM team."""

    def __init__(self, client: OllamaService | None = None) -> None:
        self.client = client or OllamaService()

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").format(
            name=request.name,
            description=request.description,
            schema=json.dumps(PersonaProfile.model_json_schema(), ensure_ascii=False),
        )
        try:
            return await self.client.generate_json(prompt)
        except (OllamaConnectionError, OllamaResponseError) as exc:
            raise PersonaGeneratorError(str(exc)) from exc
