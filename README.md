# Metaverse Projects — Backend

문서 업로드·분석, AI 페르소나, 리뷰와 채팅 기능을 연결하는 FastAPI 백엔드입니다. Frontend에 단일 API를 제공하고 LLM과 DB는 정해진 계약을 통해 연결합니다.

이 문서는 `Backend-main` 브랜치의 대표 README입니다. Backend 코드는 `backend/`에 있으며, 팀별 공통 `main`에 합칠 때는 루트 README를 전체 프로젝트 안내로 다시 구성해야 합니다.

## 현재 개발 상태

| 항목 | 상태 | 설명 |
|---|---|---|
| FastAPI·Swagger | 완료 | `/docs`, `/health` 사용 가능 |
| Agent API | 기본 완료 | 현재 메모리에 저장 |
| PPTX·PDF·DOCX 파싱 | 완료 | 업로드 문서에서 텍스트 추출 |
| Document 저장 | 기본 완료 | `document_id` 발급, 메모리 저장 |
| LLM HTTP 연결 | Backend 완료 | 방식 B 클라이언트와 `/health/llm` 구현 |
| LLM 실제 응답 | 연동 대기 | LLM 팀의 `/api/v1` 구현 필요 |
| 실제 DB 연결 | 연동 대기 | 메모리 Repository 교체 필요 |
| Review·Chat 영구 저장 | 미구현 | 저장 계약 합의 후 구현 |

Backend 서버와 문서 파싱은 실행할 수 있습니다. LLM 팀 서비스가 새 계약을 구현하기 전에는 페르소나, 리뷰, 채팅 요청이 `503 Service Unavailable`로 끝날 수 있습니다. 메모리 데이터는 Backend 재시작 시 사라집니다.

## 서비스 구조

```text
Frontend ──HTTP──▶ Backend :8000
                      ├─HTTP──▶ LLM Service :8001 ──▶ Ollama :11434
                      └─Repository──▶ DB / Vector DB / Object Storage
```

상세 역할과 변경 규칙은 [팀 연동 계약](./backend/docs/INTEGRATION_CONTRACTS.md)을 확인하세요.

## 실행 환경과 설치

- Python 3.11 이상 (현재 Backend 확인 환경: Python 3.14.7)
- Backend 기본 주소: `http://localhost:8000`
- LLM 서비스 기본 주소: `http://localhost:8001`

```powershell
cd C:\meta_project\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

팀별 Python·패키지 버전은 같을 필요가 없습니다. 자세한 기준은 [버전 호환성 안내](./backend/docs/VERSION_COMPATIBILITY.md)에 있습니다.

## 환경 변수

`backend/.env.example`의 기본 예시는 다음과 같습니다.

```text
LLM_SERVICE_URL=http://localhost:8001
LLM_API_PREFIX=/api/v1
LLM_SERVICE_TIMEOUT=300
FRONTEND_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:5500
FRONTEND_ORIGIN_REGEX=^http://25(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}:(?:4173|5173)$
```

PowerShell 현재 터미널에 직접 지정할 수도 있습니다.

```powershell
$env:LLM_SERVICE_URL = "http://localhost:8001"
$env:LLM_API_PREFIX = "/api/v1"
$env:LLM_SERVICE_TIMEOUT = "300"
$env:FRONTEND_ORIGINS = "http://localhost:3000,http://localhost:5173,http://localhost:5500"
$env:FRONTEND_ORIGIN_REGEX = '^http://25(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}:(?:4173|5173)$'
```

처음 설정할 때 저장소 루트에서 다음 명령으로 예시 파일을 `backend/.env`로 복사하면 Backend가 시작할 때 자동으로 읽습니다. `.env`는 Git에 올라가지 않습니다.

```powershell
Copy-Item backend\.env.example backend\.env
```

`FRONTEND_ORIGINS`는 브라우저에서 Backend를 호출할 수 있는 프론트 개발 서버 주소입니다. 쉼표로 구분하고 주소 마지막의 `/`는 생략합니다. 기본 설정은 다음 환경을 지원합니다.

| 프론트 개발 방식 | 기본 주소 |
|---|---|
| React Create React App | `http://localhost:3000` |
| React + Vite | `http://localhost:5173` |
| Vite Preview | `http://localhost:4173` |
| HTML·CSS·Vanilla JS + Live Server | `http://localhost:5500` |

각 주소의 `127.0.0.1` 형태도 기본 허용됩니다. 프론트 팀이 다른 포트를 사용하면 그 주소를 `FRONTEND_ORIGINS`에 추가한 뒤 Backend를 다시 실행합니다. 운영 배포 주소는 확정된 도메인만 별도로 넣어야 하며 `*` 사용은 피합니다.

HTML 파일을 탐색기에서 직접 열어 `file://`로 실행하지 말고 개발 서버를 사용합니다. Python만 있다면 프론트 폴더에서 다음처럼 실행할 수 있습니다.

```powershell
python -m http.server 5500
```

### 프론트에서 Backend 호출 예시

React와 Vanilla JS 모두 표준 `fetch`를 사용할 수 있습니다.

```javascript
const API_BASE_URL = "http://127.0.0.1:8000";

const response = await fetch(`${API_BASE_URL}/health`);
if (!response.ok) {
  throw new Error(`Backend error: ${response.status}`);
}

const data = await response.json();
console.log(data);
```

문서 업로드는 브라우저가 multipart 경계를 자동으로 만들도록 `Content-Type`을 직접 지정하지 않습니다.

```javascript
const formData = new FormData();
formData.append("file", selectedFile);

const response = await fetch(`${API_BASE_URL}/documents/parse`, {
  method: "POST",
  body: formData,
});
```

## 권장 실행 순서

1. LLM 담당자가 Ollama와 사용할 모델을 실행합니다.
2. LLM 서비스를 `localhost:8001`에서 실행합니다.
3. Backend를 실행합니다.

```powershell
cd C:\meta_project\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

`app` 모듈 오류를 피하려면 `.venv\Scripts`가 아니라 반드시 `C:\meta_project\backend`에서 실행해야 합니다.

- Swagger: <http://127.0.0.1:8000/docs>
- Backend 상태: <http://127.0.0.1:8000/health>
- LLM 연결 상태: <http://127.0.0.1:8000/health/llm>

`/health`만 정상이고 `/health/llm`이 `503`이면 Backend는 정상이나 LLM 서비스가 꺼져 있거나 `/api/v1/health` 계약이 맞지 않는 상태입니다.

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | Backend 상태 |
| GET | `/health/llm` | LLM 연결 상태 |
| POST | `/agents` | AI 페르소나 생성 |
| GET | `/agents/{agent_id}` | 페르소나 조회 |
| POST | `/documents/parse` | 문서 업로드와 텍스트 추출 |
| POST | `/agents/{agent_id}/reviews` | 문서·페르소나 기반 리뷰 |
| GET | `/reviews/{review_id}` | 리뷰 조회 |
| POST | `/agents/{agent_id}/chat` | 문서·페르소나 기반 채팅 |

필드와 응답 예시는 실행 중인 `/docs`를 기준으로 확인합니다.

## 팀별 다음 작업

### Backend

- DB Repository가 준비되면 `app/dependencies.py`에서 메모리 구현체 교체
- LLM `/api/v1` 완료 후 정상·오류·시간 초과 통합 테스트
- 업로드 크기 제한과 오류 처리 보강
- Review·Chat 저장 계약 확정 후 API 완성

### LLM

- `GET /api/v1/health` 구현
- `POST /api/v1/personas`, `/reviews`, `/chat` 구현
- 계약된 JSON 응답과 Ollama 오류의 HTTP 변환
- Backend가 보낸 ID와 필드 이름 유지

기준은 [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)입니다.

### DB

- `AgentRepository`, `DocumentRepository` 실제 구현체 제공
- Review·Chat 저장 요구사항을 Backend와 합의
- 스키마, 마이그레이션, 환경 변수 예시 제공
- Backend 도메인 모델로 결과 반환

### Frontend

- Backend `/docs`에 공개된 API만 호출
- LLM·Ollama·DB 주소를 Frontend에서 직접 사용하지 않기
- 공통 오류의 `error.code`, `error.message` 처리

## 테스트

```powershell
cd C:\meta_project\backend
.\.venv\Scripts\Activate.ps1
python -m pytest
```

현재 Backend 테스트 결과는 `11 passed`입니다. 팀 연동 후 LLM·DB 통합 테스트를 추가해야 합니다.

## 주요 폴더

```text
backend/
├─ app/
│  ├─ controllers/    # Frontend에 공개하는 HTTP API 계층
│  ├─ models/         # API·도메인 데이터 구조
│  ├─ services/       # Backend 업무 로직 계층
│  ├─ repositories/   # DB 저장 계약과 임시 메모리 구현체
│  ├─ integrations/   # LLM 등 외부 서비스 연동
│  ├─ parsers/        # 문서 텍스트 추출
│  └─ dependencies.py # 실제 구현체 연결 위치
├─ docs/              # 연동 계약과 버전 안내
└─ tests/             # Backend 테스트
```

## 알려진 제한 사항

- Agent와 Document 데이터는 서버 재시작 시 사라집니다.
- LLM API가 `/api/v1`과 맞기 전에는 LLM 기능을 끝까지 실행할 수 없습니다.
- Review와 Chat 영구 저장, 업로드 크기 제한이 아직 없습니다.
- 실제 DB·LLM 통합 테스트가 아직 없습니다.

## Git 작업 방식

```text
imjae-workingtree → Backend-main → 공통 main
```

- Backend 개발은 `imjae-workingtree`에서 작업하고 push합니다.
- 확인 후 PR로 `Backend-main`, 이후 공통 `main`에 합칩니다.
- `Frontend-main`, `LLM-main`, `DB-main`과 다른 팀원의 작업 브랜치에는 직접 push하지 않습니다.
- 팀 간 계약 변경은 코드보다 먼저 문서와 예시 JSON을 공유합니다.

## 관련 문서

- [팀별 코드 확인 안내](./backend/docs/TEAM_CODE_GUIDE.md)
- [React + Vite 연동 안내](./backend/docs/FRONTEND_INTEGRATION.md)
- [팀 연동 계약](./backend/docs/INTEGRATION_CONTRACTS.md)
- [LLM HTTP 요청·응답 계약](./backend/docs/LLM_HTTP_CONTRACT.md)
- [팀별 버전 호환성 안내](./backend/docs/VERSION_COMPATIBILITY.md)
