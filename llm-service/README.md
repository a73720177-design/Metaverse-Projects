# LLM Service

발표 자료(논문)와 대본을 받아, 핵심 개념을 추출하고 비판 질문을 생성하는 API 서버입니다.
Ollama(qwen3:14b)를 로컬에서 호출합니다.

## 현재 상태

두 가지 API 세트를 함께 제공합니다.

- **정식 계약** (`docs/LLM_HTTP_CONTRACT.md`): `GET /api/v1/health`,
  `POST /api/v1/personas`, `POST /api/v1/reviews`, `POST /api/v1/chat`.
  Backend의 `PersonaProfile`, `ReviewResult`, `ChatResponse` 모델과 필드가
  1:1로 맞도록 구현했습니다. Backend가 `LLM_CONTRACT_MODE=v1`로 전환하면
  이쪽을 씁니다.
- **legacy 호환** (`GET /health`, `POST /extract-concepts`,
  `POST /generate-questions`): Backend의 `LLM_CONTRACT_MODE=legacy_questions`가
  Persona·Review 흐름에 임시로 연결하는 API. v1 전환 후 제거 예정입니다.

## 사전 준비

1. [Ollama](https://ollama.com/download) 설치
2. 모델 다운로드: `ollama pull qwen3:14b`
3. Ollama 서버 실행 확인 (기본적으로 설치 시 자동 실행됨, 안 되어 있으면 `ollama serve`)

### 테스트한 버전

- Ollama: 0.32.11
- 모델: `qwen3:14b`

qwen3는 reasoning 모델이라 이 서비스는 `think: false`로 호출해 추론 과정이
응답에 섞이지 않게 합니다 (`app/llm_client.py`).

### 검증 기록

위 버전 조합으로 5개 엔드포인트 전부 실제 Ollama 호출까지 수동으로 확인했습니다
(응답이 스키마와 정확히 일치, 잘못된 입력은 LLM 호출 없이 422로 즉시 차단됨).

| 엔드포인트 | 결과 | 응답 시간 |
|---|---|---|
| `GET /health`, `GET /api/v1/health` | 200 | 즉시 |
| `POST /extract-concepts` | 200 | 약 44초 |
| `POST /generate-questions` | 200 | 약 37초 |
| `POST /api/v1/personas` | 200 | 약 68초 |
| `POST /api/v1/reviews` | 200 | 약 57초 |
| `POST /api/v1/chat` | 200 | 약 22초 |

자동화된 회귀 테스트(pytest)는 아직 없습니다. 위는 수동 확인 기록입니다.

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

### 정식 계약 (`/api/v1`)

#### `GET /api/v1/health`
서버 상태 확인용. Backend의 `/health/llm`이 호출합니다.

#### `POST /api/v1/personas`

요청:

```json
{"name": "홍길동 교수", "description": "근거와 비교 실험을 중요하게 평가한다."}
```

응답 (`role`/`expertise`/`evaluation_style`만 생성하며, `agent_id`/`name`/
`description`은 Backend가 확정):

```json
{
  "role": "AI 연구자",
  "expertise": [
    {
      "value": "비교 실험 설계",
      "status": "user_stated",
      "confidence": 0.9,
      "evidence": [{"source_id": "description", "summary": "비교 실험을 중요하게 평가한다", "confidence": 0.9}]
    }
  ],
  "evaluation_style": []
}
```

#### `POST /api/v1/reviews`

요청은 Backend가 보낸 `persona`(전체 `PersonaProfile`), `document`
(`DocumentParseResponse`에서 `saved_path` 제외), `instructions`(선택)를
그대로 받습니다. 응답은 `claims`, `feedback`, `questions`이며 `review_id`/
`agent_id`/`document_id`는 Backend가 확정합니다.

#### `POST /api/v1/chat`

요청은 `persona`, `message`, `document`(선택)를 받고, 응답은 `answer`,
`sources`입니다. `message_id`/`agent_id`는 Backend가 확정합니다.

정확한 필드 정의는 `app/schemas_v1.py`와 `backend/docs/LLM_HTTP_CONTRACT.md`를
참고하세요.

### legacy 호환

#### `GET /health`
서버 상태 확인용.

#### `POST /extract-concepts`

요청:

```json
{"paper_text": "..."}
```

응답:

```json
{"concepts": [{"name": "...", "definition": "..."}]}
```

#### `POST /generate-questions`

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

`/api/v1/*`, legacy 5개 엔드포인트 모두 Ollama structured output(JSON Schema)으로
응답 형식을 강제하고, 연결 실패 시 503, 응답이 JSON이 아니거나 스키마와 다르면
502를 반환합니다.

## 참고

- `app/llm_client.py`: Ollama `/api/generate` 호출용 HTTP 클라이언트.
  `response_schema`로 구조화 출력을 강제하고 `think=False`로 추론 과정을 끕니다.
- `app/prompts.py`: 프롬프트 템플릿. 개념 추출·질문 생성 프롬프트는 맥북/Windows
  양쪽에서 검증됨. persona/review/chat 프롬프트는 이번에 새로 작성해 위
  "검증 기록"의 1회 수동 테스트만 거쳤습니다 (반복 실행 시 품질 편차는
  아직 확인 전).
- `app/schemas.py`: legacy `/extract-concepts`, `/generate-questions`가 쓰는 스키마.
- `app/schemas_v1.py`: 정식 `/api/v1` 계약 스키마. Backend의
  `backend/app/models/{persona,document,review,chat}.py`와 필드가 1:1로
  맞아야 하므로, Backend 모델이 바뀌면 이 파일도 같이 맞춥니다.
- `.env.example`은 아직 git에 커밋하지 않습니다 (`.gitignore` 참고). 로컬에서만 사용하세요.
