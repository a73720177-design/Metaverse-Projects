# Metaverse Projects

발표자료를 업로드하고 평가자 페르소나의 관점에서 리뷰와 질문·답변을 제공하는 팀 프로젝트입니다. 현재 공통 `main`에는 Backend 통합 코드만 유지하며 Frontend 애플리케이션 코드는 아직 포함하지 않습니다. 향후 Frontend는 Backend API만 호출하고 Backend가 LLM 서비스, PostgreSQL, MinIO를 연결합니다.

## 전체 구성

```text
React + Vite :5173
        |
        | HTTP
        v
FastAPI Backend :8000
   |                    |
   | HTTP               | Repository / Object Storage
   v                    v
LLM Service :8001     PostgreSQL :5432 / MinIO :9000
   |
   v
Ollama :11434
```

- Frontend는 DB, LLM, Ollama에 직접 접근하지 않습니다.
- Backend Controller는 Service를 호출하고, Service는 Repository 계약을 사용합니다.
- DB와 파일 저장소 구현은 환경변수로 교체합니다.
- 실제 비밀번호, DB URL, MinIO secret은 로컬 `.env`에만 저장합니다.

## 현재 구현 상태

### Backend

- FastAPI Controller → Service → Repository 구조
- 평가자 생성·조회 API
- PPTX·PDF·DOCX 업로드와 텍스트 추출
- 문서 리뷰와 페르소나 채팅 API
- 독립 LLM FastAPI 서비스 HTTP 연동
- legacy 및 정식 `/api/v1` LLM 계약 모드
- `memory|postgres` Repository 모드
- `local|minio` Object Storage 모드
- React/Vite localhost 및 Hamachi CORS
- 공통 오류 응답 `{error: {code, message}}`
- 업로드 파일명·형식·빈 파일·25MB 크기 검증
- DB 또는 저장소 실패 시 업로드 객체 정리
- Python 3.14 호환 의존성
- Backend CI

### DB 연동

CYCL DB 작업을 기준으로 문서 저장 구조를 다음과 같이 분리했습니다.

| 테이블 | 역할 |
|---|---|
| `documents` | 문서 기본 정보와 전체 텍스트 |
| `document_files` | bucket, object key, content type |
| `document_chunks` | 순서가 있는 추출 구간과 metadata |

- 신규 DB 스키마: `backend/database/001_initial_schema.sql`
- 기존 DB 전환: `backend/database/002_split_document_storage.sql`
- 원본 파일 object key: `{document_id}/original{suffix}`
- 문서·파일·청크를 한 트랜잭션으로 저장·조회
- 기존 `memory/postgres`, `local/minio` 실행 모드와 시작 시 환경변수 검증 유지
- 별도 테스트 DB 설정 예시: `backend/.env.test.example`

`002_split_document_storage.sql`은 기존 파일 정보와 sections를 새 테이블로 이전한 뒤 예전 컬럼을 제거합니다. 공유 DB에 적용하기 전에 반드시 백업하고 별도 테스트 DB에서 데이터 이전과 재실행을 검증해야 합니다.

### Frontend 연동

Frontend 애플리케이션과 Frontend CI는 아직 공통 브랜치에 포함하지 않습니다. Backend는 향후 연동을 위한 HTTP API와 CORS 설정만 제공합니다. Frontend를 통합할 때는 `/agents`, `/documents/parse`, `/agents/{agent_id}/chat` 계약과 Backend 공통 오류 응답을 기준으로 별도 PR에서 검증합니다.

현재 Backend는 JSON 단일 채팅 응답을 사용합니다. 로그인, SSE, Backend 멀티턴은 별도 계약과 보안 정책이 확정된 뒤 추가합니다.

### LLM 연동

LLM 작업은 `kunhee-workspace`의 PR #17을 기준으로 확인합니다.

- legacy API와 `/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat` 구현
- Ollama 상태 확인과 LLM 단위 테스트 추가
- Backend v1 mock 계약 테스트 구현

PR #17이 승인·병합되고 실제 Ollama 연동 테스트가 끝나기 전까지 기본값은 다음과 같습니다.

```env
LLM_CONTRACT_MODE=legacy_questions
```

실제 v1 연동이 성공하면 다음 설정으로 전환합니다.

```env
LLM_CONTRACT_MODE=v1
LLM_API_PREFIX=/api/v1
```

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

- API 문서: <http://localhost:8000/docs>
- Backend 상태: <http://localhost:8000/health>
- DB 상태: <http://localhost:8000/health/db>
- LLM 상태: <http://localhost:8000/health/llm>
- 통합 상태: <http://localhost:8000/health/services>

## 개발 모드

PostgreSQL과 MinIO가 없어도 Backend를 실행할 수 있습니다.

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
DB_AUTO_CREATE=false
MAX_UPLOAD_SIZE_MB=25
```

로컬 데이터는 Backend를 재시작하면 초기화되며 업로드 원본은 기본적으로 `backend/uploads/objects`에 저장됩니다.

## PostgreSQL·MinIO 모드

실제 값은 Git에 포함되지 않는 `backend/.env`에만 입력합니다.

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

- `postgresql://` 주소는 Backend에서 `postgresql+asyncpg://`로 변환합니다.
- 공유 DB에서는 `DB_AUTO_CREATE=true` 대신 버전 관리 SQL을 사용합니다.
- MinIO 기본 관리자 계정을 코드나 문서에 입력하지 않습니다.

## 주요 Backend API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/health` | Backend 프로세스 상태 |
| GET | `/health/db` | Repository 모드와 PostgreSQL 상태 |
| GET | `/health/llm` | LLM 서비스 상태 |
| GET | `/health/services` | Backend·DB·LLM 통합 연결 상태 |
| POST | `/agents` | 평가자 페르소나 생성 |
| GET | `/agents/{agent_id}` | 평가자 조회 |
| POST | `/documents/parse` | 문서 업로드와 텍스트 추출 |
| POST | `/agents/{agent_id}/reviews` | 문서 리뷰 생성 |
| GET | `/reviews/{review_id}` | 리뷰 조회 |
| POST | `/agents/{agent_id}/chat` | 평가자 관점 채팅 |

정확한 필드와 오류 응답은 실행 중인 `/docs`를 기준으로 합니다.

## 테스트

```powershell
cd C:\meta_project\backend
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -q
```

현재 기본 테스트 결과:

```text
31 passed, 1 skipped
```

skip된 테스트는 실제 PostgreSQL에 데이터를 생성하는 Repository 통합 테스트입니다. 공유 DB가 아닌 별도 테스트 DB에 `TEST_DATABASE_URL`을 설정했을 때만 실행합니다.

## 통합 전 남은 작업

### P0

- [ ] LLM PR #17 변경 요청 해결과 재리뷰
- [ ] 실제 LLM/Ollama persona·review·chat 연동 테스트
- [ ] DB migration을 별도 테스트 DB에서 검증
- [ ] Frontend 통합 전 Persona → Document → Chat API 흐름 검증

### P1

- [ ] PostgreSQL·MinIO 실패 및 rollback 통합 테스트
- [ ] Backend 삭제 API와 Frontend 페르소나·문서 삭제 연결
- [ ] 채팅 timeout, 메시지 개수와 요청 크기 정책 확정

### P2

- [ ] Backend 멀티턴 계약 확정
- [ ] 필요할 경우 인증과 SSE를 별도 보안 검토 후 구현
- [ ] Frontend 통합 범위와 일정 확정

## 보안 기준

- `.env`, 실제 DB URL, 비밀번호, token, MinIO secret을 커밋하지 않습니다.
- Frontend에는 Backend 주소만 공개합니다.
- 실패 응답과 로그에 stack trace, 내부 주소, 문서 본문을 남기지 않습니다.
- 의존성 audit와 CodeQL 경고를 PR 병합 전에 확인합니다.
- 업로드 확장자와 크기는 Frontend와 Backend 양쪽에서 검사합니다.

## 문서

- [팀 통합 현황과 Backend 작업](./backend.md)
- [팀 통합 계약](./backend/docs/INTEGRATION_CONTRACTS.md)
- [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)
- [DB 연동 안내](./backend/docs/DB_INTEGRATION.md)
- [Frontend 연동 안내](./backend/docs/FRONTEND_INTEGRATION.md)
- [버전 호환성](./backend/docs/VERSION_COMPATIBILITY.md)
- [팀 코드 확인 안내](./backend/docs/TEAM_CODE_GUIDE.md)
