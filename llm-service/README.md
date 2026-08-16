# LLM Service

발표 자료(논문)와 대본을 받아, 핵심 개념을 추출하고 비판 질문을 생성하는 API 서버입니다.
Ollama(qwen3:14b)를 로컬에서 호출합니다.

## 현재 상태

지금은 `GET /health`만 제공하는 최소 골격입니다. `docs/LLM_HTTP_CONTRACT.md`가 정의한
정식 `/api/v1/health`, `/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat`을
프롬프트·파싱 로직과 함께 구현하는 작업이 남아 있습니다.

## 사전 준비

1. [Ollama](https://ollama.com/download) 설치
2. 모델 다운로드: `ollama pull qwen3:14b`
3. Ollama 서버 실행 확인 (기본적으로 설치 시 자동 실행됨, 안 되어 있으면 `ollama serve`)

## 실행 방법

```bash
# 1. 가상환경 생성 (최초 1회)
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 서버 실행
uvicorn app.main:app --reload --port 8001
```

서버가 뜨면 `http://localhost:8001/docs` 에서 Swagger UI로 API를 바로 테스트해볼 수 있습니다.

## API

### `GET /health`
서버 상태 확인용.

## 참고

- `app/llm_client.py`: Ollama `/api/generate` 호출용 최소 HTTP 클라이언트. 응답을 구조화된
  JSON으로 파싱·검증하는 부분은 정식 `/api/v1` 엔드포인트를 설계하면서 함께 정리합니다.
- `app/schemas.py`: 이전 `/extract-concepts`, `/generate-questions` 실험에서 쓰던 스키마.
  정식 계약(`PersonaProfile`, `ReviewResult` 등)에 맞춰 다시 정의할 예정입니다.
- 프롬프트(`app/prompts.py`)와 `.env.example`은 아직 git에 커밋하지 않습니다
  (`.gitignore` 참고). 로컬에서만 사용하세요.
