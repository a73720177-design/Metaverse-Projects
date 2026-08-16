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

from fastapi import FastAPI

app = FastAPI(
    title="LLM Service",
    description="발표 자료/대본 기반 개념 추출 및 비판 질문 생성 API",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용. 배포/모니터링 담당자가 헬스체크에 사용."""
    return {"status": "ok"}
