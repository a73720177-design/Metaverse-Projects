# Metaverse Projects

발표 자료를 업로드하면 평가자 페르소나 관점에서 핵심 개념과 비판 질문을 생성하고 대화할 수 있도록 만드는 팀 프로젝트입니다.

이 문서는 공통 `main` 기준의 통합 안내서입니다. 각 팀은 자기 폴더와 팀 main을 소유하고, HTTP·Repository 계약을 통해 연결합니다.

## 전체 구조

```text
React + Vite :5173
        │ HTTP
        ▼
Backend :8000
   ├─ HTTP ──▶ LLM Service :8001 ──▶ Ollama :11434
   └─ Repository ──▶ PostgreSQL / MinIO / Vector DB
```

| 팀 | 공통 main 경로 | 담당 범위 |
|---|---|---|
| Frontend | `frontend/` | React + Vite 화면, Backend API 호출 |
| Backend | `backend/` | 공개 API, 요청 검증, 문서 파싱, 서비스 조합 |
| LLM | `llm-service/` | 프롬프트, Ollama 호출, 구조화 응답 |
| DB | `database/` 또는 합의된 독립 경로 | PostgreSQL·MinIO·Vector DB와 Repository |

Frontend는 LLM·Ollama·DB를 직접 호출하지 않습니다. Backend도 Ollama나 DB 라이브러리를 Controller에서 직접 호출하지 않습니다.

## 현재 통합 상태

| 영역 | 상태 | 설명 |
|---|---|---|
| Backend | 실행 가능 | API, 문서 파싱, CORS, LLM HTTP 연동 구현 |
| React + Vite | 계약 준비 완료 | Backend CORS와 환경 변수 문서 완료, 실제 Frontend 코드는 아직 원격에 없음 |
| LLM | 호환 모드 연결 가능 | 현재 `/extract-concepts`, `/generate-questions` API에 맞춘 Backend 어댑터 제공 |
| Chat | 연동 대기 | LLM 팀의 `/api/v1/chat` 구현 필요 |
| PostgreSQL | 접속 확인 | `qwendb` 로그인과 CONNECT·CREATE 권한 확인 |
| DB 저장 연동 | 연동 대기 | 문서 테이블은 존재하지만 Backend Repository 구현 필요 |

## 이번 통합 작업 요약

- Backend와 현재 LLM 팀 API 사이에 `legacy_questions` 호환 어댑터 추가
- React + Vite의 localhost·Hamachi 개발 Origin 허용
- 공통 서비스 상태 점검 도구 `integration/check_services.py` 추가
- PostgreSQL `qwendb` 접속과 권한을 읽기 전용 쿼리로 검증
- DB에 `document_files`, `document_chunks` 테이블이 존재함을 확인
- 팀별 실행 환경과 공통 main 병합 기준 문서화
- Backend 자동 테스트 `13 passed`

PostgreSQL 접속 확인은 저장 기능 구현 완료를 뜻하지 않습니다. 현재 Backend는 여전히 메모리 Repository를 사용하므로 서버를 재시작하면 Agent·Document·Review 데이터가 사라집니다.

## 서비스 실행 순서

### 1. Ollama

LLM 담당자 PC에서 실행하고 사용할 모델을 준비합니다.

```powershell
ollama serve
ollama pull qwen3:14b
```

### 2. LLM 서비스

공통 main에 `llm-service/`가 병합된 뒤 해당 폴더에서 실행합니다.

```powershell
cd llm-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8001
```

### 3. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

현재 LLM 팀 코드와 연결할 Backend 설정:

```env
LLM_SERVICE_URL=http://localhost:8001
LLM_CONTRACT_MODE=legacy_questions
```

LLM 팀이 정식 `/api/v1/personas`, `/reviews`, `/chat`을 구현한 뒤에는 다음처럼 전환합니다.

```env
LLM_CONTRACT_MODE=v1
LLM_API_PREFIX=/api/v1
```

### 4. React + Vite

프론트 프로젝트의 `.env.development.local`에 Backend 주소를 넣습니다.

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Hamachi를 사용할 때는 Backend 담당자 주소로 바꿉니다.

```env
VITE_API_BASE_URL=http://<Backend-Hamachi-IP>:8000
```

Vite 환경 변수에는 비밀번호나 API 키를 넣지 않습니다.

## 상태 확인

개별 주소:

- Frontend: <http://localhost:5173>
- Backend Swagger: <http://localhost:8000/docs>
- Backend 상태: <http://localhost:8000/health>
- Backend → LLM 상태: <http://localhost:8000/health/llm>
- LLM 상태: <http://localhost:8001/health>
- Ollama 모델 목록: <http://localhost:11434/api/tags>

전체 상태 점검:

```powershell
Copy-Item integration\.env.example integration\.env
python integration\check_services.py
```

## 팀별 필수 작업

공통 main 병합 전 작업의 우선순위, 담당 팀, 완료 조건은 [공통 main 병합 전 체크리스트](./integration/PRE_MAIN_CHECKLIST.md)를 기준으로 합니다. 우선순위는 Backend 통합 흐름의 의존 순서이며 팀의 중요도 순서가 아닙니다.

### Frontend

- React + Vite 프로젝트를 `frontend/`에 배치
- `VITE_API_BASE_URL`을 통해 Backend만 호출
- Backend의 `error.code`, `error.message` 표시
- 파일 업로드 시 `FormData`의 `Content-Type`을 직접 지정하지 않기

### Backend

- 공개 API와 팀 간 오류 형식 유지
- LLM 호환 모드는 임시 연결에만 사용
- DB 팀 구현이 준비되면 `dependencies.py`에서 Repository 교체

### LLM

- 현재 코드를 먼저 `LLM-main`에 PR로 병합
- 장기적으로 `/api/v1/personas`, `/reviews`, `/chat` 계약 구현
- Ollama 오류를 HTTP 502 또는 503으로 명확히 반환
- 모델 출력은 계약된 JSON으로 검증

### DB

- 코드에 MinIO·PostgreSQL 주소와 인증 정보 하드코딩 금지
- 실험 스크립트를 Backend Repository 또는 독립 DB 서비스로 정리
- 스키마와 마이그레이션 제공
- Agent, Document, Review 저장 계약부터 구현
- 현재 `document_files`, `document_chunks` 스키마를 Backend `DocumentRepository`와 매핑

## 테스트

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest
```

현재 기준 결과:

```text
13 passed
```

공통 통합 상태:

```powershell
python integration\check_services.py
```

## Git 통합 원칙

```text
개인 작업 브랜치 → 팀 main → 공통 main
```

- 다른 팀 작업 브랜치에 직접 push하지 않습니다.
- 각 팀 main에서 단독 실행을 확인한 뒤 공통 main PR을 만듭니다.
- 계약이 달라지면 코드를 억지로 합치지 말고 계약 문서와 예시 JSON을 먼저 수정합니다.
- rebase, force push, 다른 브랜치 병합은 담당자 확인 후 실행합니다.
- 공통 main 루트 README는 전체 프로젝트 안내로 유지합니다.

## 문서

- [공통 서비스 통합 안내](./integration/README.md)
- [공통 main 병합 전 팀별 체크리스트](./integration/PRE_MAIN_CHECKLIST.md)
- [팀별 코드 확인 안내](./backend/docs/TEAM_CODE_GUIDE.md)
- [팀 연동 계약](./backend/docs/INTEGRATION_CONTRACTS.md)
- [React + Vite 연동](./backend/docs/FRONTEND_INTEGRATION.md)
- [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)
- [버전 호환성](./backend/docs/VERSION_COMPATIBILITY.md)
