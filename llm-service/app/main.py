"""
LLM 서비스 API 서버.

실행:
    uvicorn app.main:app --reload --port 8001

사전 조건:
    - Ollama가 로컬에서 실행 중이어야 함 (ollama serve)
    - qwen3:14b 모델이 pull 되어 있어야 함
"""

import json

from fastapi import FastAPI, HTTPException

from app.llm_client import LLMError, call_llm
from app.prompts import CONCEPT_EXTRACTION_PROMPT, QUESTION_GENERATION_PROMPT
from app.schemas import (
    ConceptExtractionRequest,
    ConceptExtractionResponse,
    QuestionGenerationRequest,
    QuestionGenerationResponse,
)

app = FastAPI(
    title="LLM Service",
    description="발표 자료/대본 기반 개념 추출 및 비판 질문 생성 API",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}


@app.post("/extract-concepts", response_model=ConceptExtractionResponse)
def extract_concepts(req: ConceptExtractionRequest):
    """
    논문 본문에서 핵심 개념 8개를 추출한다. (기획서 1단계)
    """
    prompt = CONCEPT_EXTRACTION_PROMPT.format(paper_text=req.paper_text)

    try:
        result = call_llm(prompt)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    try:
        return ConceptExtractionResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"모델 응답이 예상한 형식과 다릅니다: {e}",
        ) from e


@app.post("/generate-questions", response_model=QuestionGenerationResponse)
def generate_questions(req: QuestionGenerationRequest):
    """
    concepts + critical_points + 발표 대본을 바탕으로 비판 질문 5개를 생성한다. (기획서 2단계, v2)
    """
    concepts_json = json.dumps(
        [c.model_dump() for c in req.concepts], ensure_ascii=False
    )
    prompt = QUESTION_GENERATION_PROMPT.format(
        critical_points=req.critical_points,
        concepts_json=concepts_json,
        script_text=req.script_text,
    )

    try:
        result = call_llm(prompt)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    try:
        return QuestionGenerationResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"모델 응답이 예상한 형식과 다릅니다: {e}",
        ) from e
