from typing import Any

from app.integrations.llm.client import (
    HttpLlmClient,
    LlmServiceConnectionError,
    LlmServiceResponseError,
)
from app.integrations.llm.contracts import (
    ChatGeneratorError,
    PersonaGeneratorError,
    ReviewGeneratorError,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile


def _validate_concepts(body: dict[str, Any]) -> list[dict[str, str]]:
    raw_concepts = body.get("concepts")
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise ReviewGeneratorError("LLM 응답에 concepts 배열이 없습니다.")
    concepts: list[dict[str, str]] = []
    for item in raw_concepts:
        if not isinstance(item, dict):
            raise ReviewGeneratorError("LLM concept 항목은 JSON 객체여야 합니다.")
        name = item.get("name")
        definition = item.get("definition")
        if not isinstance(name, str) or not name.strip():
            raise ReviewGeneratorError("LLM concept의 name이 올바르지 않습니다.")
        if not isinstance(definition, str) or not definition.strip():
            raise ReviewGeneratorError("LLM concept의 definition이 올바르지 않습니다.")
        concepts.append({"name": name.strip(), "definition": definition.strip()})
    return concepts


class LocalPersonaGenerator:
    """현재 LLM 서비스에 persona API가 없을 때 입력 정보를 그대로 사용합니다."""

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        if not request.description.strip():
            raise PersonaGeneratorError("평가자 설명이 필요합니다.")
        return {
            "role": "Evaluator",
            "expertise": [],
            "evaluation_style": [],
        }


class LegacyQuestionReviewGenerator:
    """현재 LLM 팀의 2단계 질문 생성 API를 Backend 리뷰로 변환합니다."""

    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(
        self,
        persona: PersonaProfile,
        document: DocumentParseResponse,
        instructions: str | None,
    ) -> dict[str, Any]:
        critical_points = persona.description
        if instructions:
            critical_points = f"{critical_points}\n추가 요청: {instructions}"

        try:
            concept_result = await self.client.post_json(
                "/extract-concepts",
                {"paper_text": document.full_text},
            )
            question_result = await self.client.post_json(
                "/generate-questions",
                {
                    "concepts": _validate_concepts(concept_result),
                    "critical_points": critical_points,
                    "script_text": document.full_text,
                },
            )
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise ReviewGeneratorError(str(exc)) from exc

        raw_questions = question_result.get("questions")
        if not isinstance(raw_questions, list):
            raise ReviewGeneratorError("LLM 응답에 questions 배열이 없습니다.")

        questions = [
            item["question"].strip()
            for item in raw_questions
            if isinstance(item, dict)
            and isinstance(item.get("question"), str)
            and item["question"].strip()
        ]
        if len(questions) != len(raw_questions):
            raise ReviewGeneratorError("LLM question 항목의 형식이 올바르지 않습니다.")
        if not questions:
            raise ReviewGeneratorError("LLM이 유효한 질문을 반환하지 않았습니다.")

        return {
            "claims": [],
            "feedback": {
                "positive": "핵심 개념을 기준으로 발표 내용을 분석했습니다.",
                "negative": "아래 비판 질문을 중심으로 근거와 설명을 보완해 주세요.",
            },
            "questions": questions,
        }


class UnsupportedLegacyChatGenerator:
    """현재 LLM 팀 API에 chat 기능이 없음을 명시적으로 알립니다."""

    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document: DocumentParseResponse | None,
    ) -> dict[str, Any]:
        raise ChatGeneratorError(
            "현재 LLM 서비스는 채팅 API를 제공하지 않습니다. LLM /api/v1/chat 구현이 필요합니다."
        )
