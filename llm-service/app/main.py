"""
LLM 서비스 API 서버.

실행:
    uvicorn app.main:app --reload --port 8001

사전 조건:
    - Ollama가 로컬에서 실행 중이어야 함 (ollama serve)
    - qwen3:14b 모델이 pull 되어 있어야 함

/extract-concepts, /generate-questions는 정식 /api/v1/personas,
/api/v1/reviews, /api/v1/chat 계약을 구현하면서 프롬프트·파싱과 함께
다시 정리한다 (docs/LLM_HTTP_CONTRACT.md 참고).
"""

import json
import logging
import re

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.llm_client import LLMError, call_llm
from app.schemas import (
    ConceptExtractionRequest,
    ConceptExtractionResponse,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="LLM Service",
    description="발표 자료/대본 기반 개념 추출 및 비판 질문 생성 API",
    version="0.1.0",
)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


def _build_concept_prompt(paper_text: str) -> str:
    return (
        "다음 본문에서 핵심 개념을 추출해라. 다른 설명 없이 JSON으로만 응답해라.\n"
        '형식: {"concepts": [{"name": "...", "definition": "..."}]}\n\n'
        f"본문:\n{paper_text}"
    )


def _build_question_prompt(request: QuestionGenerationRequest) -> str:
    concepts_text = "\n".join(f"- {c.name}: {c.definition}" for c in request.concepts)
    return (
        "아래 개념과 발표 대본을 참고해서, 주어진 평가 관점으로 비판 질문을 만들어라. "
        "다른 설명 없이 JSON으로만 응답해라.\n"
        '형식: {"questions": [{"question": "..."}]}\n\n'
        f"개념:\n{concepts_text}\n\n"
        f"평가자 관점: {request.critical_points}\n\n"
        f"발표 대본:\n{request.script_text}"
    )


def _call_llm_as_json(prompt: str) -> dict:
    try:
        raw = call_llm(prompt)
    except LLMError:
        # 내부 호스트 주소 등 민감할 수 있는 세부 정보는 서버 로그에만 남기고,
        # 클라이언트에는 일반화된 메시지만 반환한다.
        logger.exception("Ollama 호출 실패")
        raise HTTPException(status_code=503, detail="LLM 서버에 연결할 수 없습니다.")

    cleaned = _CODE_FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 모델 원본 출력 전체를 로그에 남기지 않는다 (문서 내용이 섞여 있을 수 있음).
        logger.error("LLM 응답이 JSON 형식이 아님 (길이=%d)", len(raw))
        raise HTTPException(status_code=502, detail="LLM 응답을 해석할 수 없습니다.")


@app.post("/extract-concepts", response_model=ConceptExtractionResponse)
def extract_concepts(request: ConceptExtractionRequest) -> ConceptExtractionResponse:
    data = _call_llm_as_json(_build_concept_prompt(request.paper_text))
    try:
        return ConceptExtractionResponse.model_validate(data)
    except ValidationError:
        logger.error("개념 추출 응답 스키마 불일치")
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")


@app.post("/generate-questions", response_model=QuestionGenerationResponse)
def generate_questions(request: QuestionGenerationRequest) -> QuestionGenerationResponse:
    data = _call_llm_as_json(_build_question_prompt(request))
    try:
        return QuestionGenerationResponse.model_validate(data)
    except ValidationError:
        logger.error("질문 생성 응답 스키마 불일치")
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")
