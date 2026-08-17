# LLM Service

발표 자료(논문)와 대본을 받아, 핵심 개념을 추출하고 비판 질문을 생성하는 API 서버입니다.
Ollama(qwen3:14b)를 로컬에서 호출합니다.

## 현재 상태

`GET /health`와 함께 `POST /extract-concepts`, `POST /generate-questions`를 제공합니다.
Backend의 `LLM_CONTRACT_MODE=legacy_questions`가 이 두 API를 Persona·Review 흐름에
연결합니다. `docs/LLM_HTTP_CONTRACT.md`가 정의한 정식 `/api/v1/health`,
`/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat`은 아직 구현 전입니다.

## 사전 준비

1. [Ollama](https://ollama.com/download) 설치
2. 모델 다운로드: `ollama pull qwen3:14b`
3. Ollama 서버 실행 확인 (기본적으로 설치 시 자동 실행됨, 안 되어 있으면 `ollama serve`)

### 테스트한 버전

- Ollama: 0.32.11
- 모델: `qwen3:14b`

qwen3는 reasoning 모델이라 이 서비스는 `think: false`로 호출해 추론 과정이
응답에 섞이지 않게 합니다 (`app/llm_client.py`).

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

### `POST /extract-concepts`

요청:

```json
{"paper_text": "..."}
```

응답:

```json
{"concepts": [{"name": "...", "definition": "..."}]}
```

### `POST /generate-questions`

요청:

```json
{
  "concepts": [{"name": "...", "definition": "..."}],
  "critical_points": "사용자가 평소 중요하게 여기는 관점",
  "script_text": "비판 대상이 되는 발표 대본"
}
```

응답:

```json
{"questions": [{"question": "..."}]}
```

두 API 모두 Ollama structured output(JSON Schema)으로 응답 형식을 강제하고,
연결 실패 시 503, 응답이 JSON이 아니거나 스키마와 다르면 502를 반환합니다.

## 참고

- `app/llm_client.py`: Ollama `/api/generate` 호출용 HTTP 클라이언트.
  `response_schema`로 구조화 출력을 강제하고 `think=False`로 추론 과정을 끕니다.
- `app/prompts.py`: 맥북/Windows 양쪽에서 검증된 프롬프트 템플릿.
- `app/schemas.py`: 현재 `/extract-concepts`, `/generate-questions`가 쓰는 요청·응답 스키마.
  정식 계약(`PersonaProfile`, `ReviewResult` 등)에 맞춰 다시 정의할 예정입니다.
- `.env.example`은 아직 git에 커밋하지 않습니다 (`.gitignore` 참고). 로컬에서만 사용하세요.
