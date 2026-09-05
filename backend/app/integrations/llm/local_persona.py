from typing import Any

from app.integrations.llm.contracts import PersonaGeneratorError
from app.models.persona import PersonaCreateRequest


class LocalPersonaGenerator:
    """개발용 대체 구현입니다.

    로컬 모델이 잘못된 JSON을 뱉어도 Persona 생성 흐름을 계속 확인할 수 있도록,
    LLM을 호출하지 않고 입력 정보를 그대로 사용합니다. PERSONA_FALLBACK_LOCAL로
    켭니다.
    """

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        if not request.description.strip():
            raise PersonaGeneratorError("평가자 설명이 필요합니다.")
        return {
            "role": "Evaluator",
            "expertise": [],
            "evaluation_style": [],
        }
