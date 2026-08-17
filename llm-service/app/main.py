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
from app.prompts import CONCEPT_EXTRACTION_PROMPT, QUESTION_GENERATION_PROMPT
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

# response_schema로 구조화 출력을 강제해도, Ollama 버전에 따라 강제가 안 통하는
# 경우를 대비한 방어적 처리로 코드펜스 제거는 남겨둔다.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


def _build_concept_prompt(paper_text: str) -> str:
    return CONCEPT_EXTRACTION_PROMPT.format(paper_text=paper_text)


def _build_question_prompt(request: QuestionGenerationRequest) -> str:
    concepts_json = json.dumps(
        [c.model_dump() for c in request.concepts], ensure_ascii=False
    )
    return QUESTION_GENERATION_PROMPT.format(
        critical_points=request.critical_points,
        concepts_json=concepts_json,
        script_text=request.script_text,
    )


def _call_llm_as_json(prompt: str, response_schema: dict) -> dict:
    try:
        raw = call_llm(prompt, response_schema=response_schema)
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
    schema = ConceptExtractionResponse.model_json_schema()
    data = _call_llm_as_json(_build_concept_prompt(request.paper_text), schema)
    try:
        return ConceptExtractionResponse.model_validate(data)
    except ValidationError:
        logger.error("개념 추출 응답 스키마 불일치")
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")


@app.post("/generate-questions", response_model=QuestionGenerationResponse)
def generate_questions(request: QuestionGenerationRequest) -> QuestionGenerationResponse:
    schema = QuestionGenerationResponse.model_json_schema()
    data = _call_llm_as_json(_build_question_prompt(request), schema)
    try:
        return QuestionGenerationResponse.model_validate(data)
    except ValidationError:
        logger.error("질문 생성 응답 스키마 불일치")
        raise HTTPException(status_code=502, detail="LLM 응답 형식이 올바르지 않습니다.")
