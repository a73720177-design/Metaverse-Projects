# Metaverse Projects

발표 자료를 업로드하고 평가자 페르소나 관점에서 리뷰와 질문, 대화를 생성하는 팀 프로젝트입니다.
이 문서는 `imjae-workingtree`에서 검증한 Backend 통합 현황과 다른 팀의 연결 방법을 설명합니다.

## 현재 Backend 작업 결과

- FastAPI Controller → Service → Repository 구조
- PPTX·PDF·DOCX 업로드 및 텍스트 추출
- Persona·Document·Review·Chat 공개 API
- 독립 LLM FastAPI 서비스와 HTTP 방식으로 연결
- LLM legacy 계약과 정식 `/api/v1` 계약을 환경 변수로 선택
- 메모리 또는 PostgreSQL Repository 선택
- 로컬 디렉터리 또는 MinIO 파일 저장소 선택
- React + Vite localhost·Hamachi CORS 지원
- PostgreSQL·MinIO 오류의 공통 503 응답 처리
- 파일명·빈 파일·최대 업로드 크기 검증
- PostgreSQL 연결 지연 초기화 및 종료 시 연결 정리
- Python 3.14 호환 의존성 적용
- GitHub Actions Backend CI 적용

현재 자동 테스트 결과는 다음과 같습니다.

```text
29 passed, 1 skipped
```

skip된 테스트는 실제 PostgreSQL에 데이터를 생성하는 통합 테스트입니다. 별도
`TEST_DATABASE_URL`을 설정했을 때만 실행됩니다.

## 전체 연결 구조

```text
React + Vite :5173
        │ HTTP
        ▼
Backend :8000
   ├─ HTTP ──▶ LLM Service :8001 ──▶ Ollama :11434
   └─ Repository ──▶ PostgreSQL / MinIO
```

- Frontend는 Backend만 호출합니다.
- Backend는 Ollama를 직접 호출하지 않고 LLM 팀의 FastAPI 서비스를 호출합니다.
- Controller와 Service는 SQLAlchemy나 MinIO 클라이언트를 직접 사용하지 않습니다.
- DB와 파일 저장 구현은 Repository·ObjectStorage 인터페이스 뒤에서 교체합니다.

## 팀 브랜치 기준 진행 상황

| 팀 | 확인한 작업 브랜치 | 현재 상태 | 다음 연결 조건 |
|---|---|---|---|
| Backend | `imjae-workingtree` | 통합 코드와 CI 검증 완료 | `Backend-main` PR 리뷰 및 병합 |
| LLM | `kunhee-workspace` | legacy API와 정식 `/api/v1` Persona·Review·Chat 구현 | PR #17 수정·병합 후 실제 Ollama 통합 테스트 |
| Frontend | `kstttt` | React + Vite 화면 구현 | 임시 `/api/chat/stream`을 Backend UUID API로 변경 |
| DB | `Backend-CYCL-2`, `DB-One-of-kind-1` | PostgreSQL Repository·MinIO 구현과 OCR 실험 존재 | 최종 문서 스키마와 migration 확정 |

## Backend 실행

Windows PowerShell 기준입니다.

```powershell
cd C:\meta_project\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

확인 주소:

- Swagger: <http://localhost:8000/docs>
- Backend 상태: <http://localhost:8000/health>
- DB 상태: <http://localhost:8000/health/db>
- Backend → LLM 상태: <http://localhost:8000/health/llm>

## 개발 모드

외부 DB와 MinIO가 준비되지 않았을 때 사용하는 기본 설정입니다.

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
DB_AUTO_CREATE=false
MAX_UPLOAD_SIZE_MB=25
```

- 데이터는 Backend 재시작 시 초기화됩니다.
- 업로드 원본은 기본적으로 `backend/uploads/objects`에 저장됩니다.
- DB·MinIO가 꺼져 있어도 Backend 개발과 단위 테스트가 가능합니다.

## PostgreSQL·MinIO 통합 모드

DB 팀과 통합할 때 로컬 `backend/.env`에만 실제 값을 입력합니다.

```env
REPOSITORY_MODE=postgres
OBJECT_STORAGE_MODE=minio
DB_AUTO_CREATE=false
DATABASE_URL=postgresql://사용자:비밀번호@호스트:5432/qwendb
MINIO_ENDPOINT=호스트:9000
MINIO_ACCESS_KEY=접근키
MINIO_SECRET_KEY=비밀키
MINIO_BUCKET=documents
MINIO_SECURE=false
```

- `.env`는 Git에 커밋하지 않습니다.
- `postgresql://` 주소는 Backend가 `postgresql+asyncpg://`로 자동 변환합니다.
- 공통 환경에서는 `DB_AUTO_CREATE=true` 대신 버전 관리되는 migration을 사용합니다.
- MinIO 기본 관리자 계정은 코드에 포함하지 않습니다.

### DB 팀 확인 사항

1. `documents`와 기존 `document_files + document_chunks` 중 최종 문서 스키마를 확정합니다.
2. `AgentTable`, `DocumentTable`, `ReviewTable` 필드를 실제 테이블과 맞춥니다.
3. JSONB 필드와 외래 키 삭제 정책, 인덱스를 확정합니다.
4. migration SQL과 적용 순서를 제공합니다.
5. MinIO bucket과 `{document_id}.{확장자}` object key 규칙을 확인합니다.
6. 공유 개발 DB와 분리된 `TEST_DATABASE_URL`을 제공합니다.
7. GOT-OCR·Surya는 Repository에 직접 넣지 않고 OCR 입출력 계약을 먼저 정합니다.

자세한 내용은 [DB 통합 안내](./backend/docs/DB_INTEGRATION.md)를 확인합니다.

## LLM 연결

LLM 서비스 기본 주소는 `http://localhost:8001`입니다.

PR #17이 `LLM-main`에 병합되기 전까지는 legacy 모드를 유지합니다.

```env
LLM_SERVICE_URL=http://localhost:8001
LLM_CONTRACT_MODE=legacy_questions
LLM_SERVICE_TIMEOUT=300
```

PR 병합과 실제 통합 테스트가 끝난 뒤 정식 v1로 전환합니다.

```env
LLM_SERVICE_URL=http://localhost:8001
LLM_CONTRACT_MODE=v1
LLM_API_PREFIX=/api/v1
LLM_SERVICE_TIMEOUT=300
```

Backend 계약 테스트는 PR #17의 전체 커밋과 최종 `schemas_v1.py`를 기준으로 다음을 검증합니다.

- `/api/v1/personas` 요청·응답과 Backend ID 생성
- `/api/v1/reviews` Persona·Document·Instructions payload
- LLM 요청에서 내부 `saved_path` 제외
- `/api/v1/chat`의 선택적 Document 처리
- `X-Backend-Contract-Version: 1` 헤더
- LLM 502·503 및 잘못된 JSON 처리
- LLM 오류 본문의 내부 정보 비노출

### LLM 팀 확인 사항

1. PR #17 제목과 본문을 최종 구현 상태에 맞춥니다.
2. mock 기반 자동화 테스트를 추가합니다.
3. `.env` 로딩 방법과 안전한 `.env.example`을 제공합니다.
4. `/api/v1/health`가 FastAPI만 확인하는지 Ollama·모델까지 확인하는지 명시합니다.
5. v1 필드나 타입을 변경할 때 Backend 계약 문서를 먼저 함께 수정합니다.

자세한 요청·응답은 [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)을 확인합니다.

## Frontend 연결

Frontend 환경 변수에는 Backend 주소만 입력합니다.

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Hamachi에서는 Backend PC의 Hamachi IP를 사용합니다.

```env
VITE_API_BASE_URL=http://<Backend-Hamachi-IP>:8000
```

현재 `kstttt`의 `POST /api/chat/stream`은 Backend에 없는 임시 SSE 계약입니다.
Backend의 현재 Chat API는 다음과 같습니다.

```http
POST /agents/{agent_id}/chat
Content-Type: application/json
```

```json
{
  "message": "핵심 문제가 무엇인가요?",
  "document_id": null
}
```

### Frontend 팀 확인 사항

1. `POST /agents` 응답의 `agent_id`를 저장합니다.
2. 문서는 `POST /documents/parse`에 `FormData`로 전송하고 `document_id`를 저장합니다.
3. Chat과 Review 요청에는 이름 대신 UUID를 사용합니다.
4. 파일 선택 형식은 Backend와 동일하게 `.pptx,.pdf,.docx`로 설정합니다.
5. Backend 오류의 `error.code`, `error.message`를 화면에 표시합니다.
6. 스트리밍이 반드시 필요하면 Frontend만 임의로 가정하지 않고 새 계약으로 협의합니다.

자세한 내용은 [React + Vite 연동 안내](./backend/docs/FRONTEND_INTEGRATION.md)를 확인합니다.

## 주요 Backend API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/health` | Backend 프로세스 상태 |
| GET | `/health/db` | Repository 모드와 PostgreSQL 상태 |
| GET | `/health/llm` | LLM 서비스 상태 |
| POST | `/agents` | 평가자 페르소나 생성 |
| GET | `/agents/{agent_id}` | 평가자 조회 |
| POST | `/documents/parse` | 문서 업로드 및 텍스트 추출 |
| POST | `/agents/{agent_id}/reviews` | 문서 리뷰 생성 |
| GET | `/reviews/{review_id}` | 리뷰 조회 |
| POST | `/agents/{agent_id}/chat` | 평가자 관점 대화 |

정확한 필드와 오류 응답은 실행 중인 `/docs`를 기준으로 합니다.

## 테스트와 CI

로컬 테스트:

```powershell
cd C:\meta_project\backend
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions의 `Backend CI`는 다음 상황에서 실행됩니다.

- `imjae-workingtree`, `Backend-main`에 Backend 변경 push
- `Backend-main`, `main` 대상 Backend PR
- Actions 화면에서 수동 실행

CI는 Python 3.14, `memory + local` 모드를 사용하며 외부 DB·MinIO·Ollama에 의존하지 않습니다.

## Git 협업 원칙

```text
개인 작업 브랜치 → 팀 main → 공통 main
```

- 다른 팀 작업 브랜치에 직접 push하지 않습니다.
- 팀 main에서 테스트 후 공통 main PR을 만듭니다.
- rebase는 담당자 확인 없이 실행하지 않습니다.
- force push를 사용하지 않습니다.
- API나 DB 계약이 달라지면 계약 문서와 예시 JSON을 먼저 수정합니다.
- 비밀번호, 실제 DB URL, MinIO secret을 코드·README·PR에 작성하지 않습니다.

## 문서

- [Backend 작업 계획과 팀 브랜치 분석](./backend.md)
- [팀 연동 계약](./backend/docs/INTEGRATION_CONTRACTS.md)
- [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)
- [DB 통합 안내](./backend/docs/DB_INTEGRATION.md)
- [React + Vite 연동](./backend/docs/FRONTEND_INTEGRATION.md)
- [버전 호환성](./backend/docs/VERSION_COMPATIBILITY.md)
- [팀별 코드 확인 안내](./backend/docs/TEAM_CODE_GUIDE.md)
- [공통 main 병합 체크리스트](./integration/PRE_MAIN_CHECKLIST.md)
