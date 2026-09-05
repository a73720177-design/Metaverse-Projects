# Metaverse Projects

PPTX·PDF·DOCX 발표 자료를 업로드하고 평가자 페르소나의 관점으로 리뷰와 질의응답을 제공하는 서비스입니다. React + Vite Frontend는 FastAPI Backend만 호출하며, Backend가 LLM Service·PostgreSQL·MinIO를 조합합니다.

## 아키텍처

```text
React + Vite :5173
        |
        v
FastAPI Backend :8000
   |                    |
   v                    v
LLM Service :8001     PostgreSQL :5432 / MinIO :9000
   |
   v
Ollama :11434
```

| 파트 | 담당자 | 책임 |
|---|---|---|
| Backend / PM | 정재균 | 공개 API, 인증·소유권, 서비스 통합, 일정·릴리스 |
| Frontend | 김승태 | React UI, Backend API 연동, 사용자 흐름 |
| DB | 임준혁 | PostgreSQL·MinIO, migration, 백업·복구 |
| LLM | 최건희 | 프롬프트, Ollama, 구조화 응답과 모델 품질 |

## 구현 상태

- JWT 회원가입·로그인·현재 사용자 조회와 사용자별 리소스 격리
- Persona 생성·조회·목록, 휴지통 이동·복원·완전 삭제
- PPTX·PDF·DOCX 업로드, 25MB 제한, 텍스트 추출
- 업로드 시 1회 bge-m3 인덱싱, 문서 삭제 시 인덱스 정리
- Persona 기반 최초 Review와 이후 Chat 피드백
- Chat 이력, 휴지통 이동·복원·완전 삭제
- `memory|postgres` Repository, `local|minio` Object Storage
- 정식 `/api/v1` 계약 (legacy 호환 모드 제거)

### LLM 동작 방식

RAG(bge-m3 검색)가 모든 답변 경로의 공통 기반 레이어입니다. 답변을 생성하기 전에 항상 관련 자료 조각을 검색해서 프롬프트에 넣습니다. 경로마다 다른 것은 "검색 여부"가 아니라 "검색 후 추론(think) 여부"입니다.

| 단계 | RAG 검색 | 추론(think) | 모델 |
|---|---|---|---|
| 문서 인덱싱 | 임베딩 생성 | — | bge-m3 |
| 최초 평가 (`/reviews`) | ✅ | ✅ | qwen3:8b |
| Chat 피드백 (`/chat`) | ✅ | ✅ | qwen3:8b |
| 유사도 미달 시 자료 추가 요청 | ✅ (임계값 미달) | ❌ | 코드 템플릿 (생성 없음) |
| 인사말·잡담 | ❌ (검색 생략) | ❌ | qwen3:4b |
| Persona 생성 | ❌ | ❌ | qwen3:4b |

문서 전문은 업로드 시점에 Backend가 LLM Service로 한 번만 보냅니다. 이후 평가·채팅 요청에는 `document_id`만 오갑니다. LLM Service가 재시작되어 인덱스가 비면 409(`document_not_indexed`)를 반환하고, Backend가 문서를 다시 인덱싱한 뒤 한 번 재시도합니다.

임베딩 벡터는 LLM Service의 메모리(LRU)와 로컬 디스크 캐시(`llm-service/.rag_cache`)에 보관합니다. DB나 pgvector는 쓰지 않습니다.

`backend/database/007_add_chat_needs_more_material.sql`은 자료 부족으로 자료 추가를 요청한 답변을 구분하는 `chat_messages.needs_more_material` 컬럼을 추가합니다. Migration `001`부터 `007`까지 공유 DB에 적용하기 전에 별도 테스트 DB에서 적용·재실행·rollback을 검증해야 합니다.

## 빠른 실행

Windows PowerShell 기준입니다. Python 가상환경은 서비스별로 분리할 수 있습니다.

### 1. Ollama

```powershell
ollama serve
ollama pull qwen3:8b
ollama pull qwen3:4b
ollama pull bge-m3
```

세 모델을 16GB VRAM에 함께 올리려면 Ollama 서버에 아래 값을 설정합니다. `OLLAMA_NUM_PARALLEL`이 1보다 크면 KV 캐시가 그 배수만큼 할당되어 예산이 무너집니다.

```powershell
$env:OLLAMA_MAX_LOADED_MODELS = "3"
$env:OLLAMA_NUM_PARALLEL = "1"
```

가중치 기준 예산: bge-m3 약 1.2GB + qwen3:4b 약 3GB + qwen3:8b 약 5GB = 약 9.2GB. 나머지는 KV 캐시(`OLLAMA_NUM_CTX`)가 씁니다.

### 2. LLM Service

```powershell
cd C:\meta_projects\llm-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 3. Backend

```powershell
cd C:\meta_projects\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PostgreSQL과 MinIO 없이 실행할 개발 기본값:

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
DB_AUTO_CREATE=false
LLM_SERVICE_URL=http://localhost:8001
LLM_API_PREFIX=/api/v1
```

실제 DB URL, JWT secret, MinIO key는 Git에 포함하지 않는 `backend/.env`에만 입력합니다.

### 4. Frontend

```powershell
cd C:\meta_projects
npm install
Copy-Item .env.example .env.local
npm run dev
```

`VITE_API_BASE_URL`에는 Backend 주소만 지정합니다. LLM·Ollama·DB 주소나 비밀 값은 Frontend에 넣지 않습니다.

## 상태 확인

- Frontend: <http://localhost:5173>
- Backend Swagger: <http://localhost:8000/docs>
- Backend: <http://localhost:8000/health>
- DB: <http://localhost:8000/health/db>
- LLM 연동: <http://localhost:8000/health/llm>
- 전체 서비스: <http://localhost:8000/health/services>
- LLM Swagger: <http://localhost:8001/docs>

전체 상태 점검:

```powershell
Copy-Item integration\.env.example integration\.env
python integration\check_services.py
```

## 주요 Backend API

| 기능 | API |
|---|---|
| 인증 | `POST /auth/signup`, `POST /auth/login`, `GET /auth/me` |
| Persona | `POST/GET /agents`, `GET/DELETE /agents/{agent_id}` |
| Persona 휴지통 | `GET /agents/trash`, `POST /agents/trash/{agent_id}/restore`, `DELETE /agents/trash/{agent_id}` |
| 문서 | `POST /documents/parse`, `GET /documents`, `GET/DELETE /documents/{document_id}` |
| Review | `POST /agents/{agent_id}/reviews`, `GET /reviews/{review_id}` |
| Chat | `POST /agents/{agent_id}/chat`, `GET /chats` |
| Chat 휴지통 | `DELETE /chats/{message_id}`, `GET /trash/chats`, 복원·완전 삭제 |

`/auth/signup`과 `/auth/login`을 제외한 업무 API는 `Authorization: Bearer <token>`을 요구합니다. 정확한 필드와 상태 코드는 실행 중인 Backend `/docs`가 기준입니다.

## 테스트

```powershell
cd C:\meta_projects\backend
python -m compileall -q app tests
python -m pytest -q

cd C:\meta_projects\llm-service
python -m compileall -q app tests
python -m pytest -q

cd C:\meta_projects
npm run build
```

실제 PostgreSQL Repository 테스트는 데이터가 생성되므로 공유 DB 대신 별도 `TEST_DATABASE_URL`에서만 실행합니다.

개발용 PostgreSQL과 테스트 DB migration 준비:

```powershell
docker compose up -d postgres
$env:TEST_DATABASE_URL="postgresql+asyncpg://qwen:dev_postgres_password@localhost:5432/qwendb_test"
$env:TEST_DATABASE_ADMIN_URL="postgresql+asyncpg://qwen:dev_postgres_password@localhost:5432/postgres"
python -m backend.scripts.setup_test_db
```

## 문서 운영

저장소에는 이 루트 `README.md`만 유지합니다. 상세 API 계약, DB 변경, 실행·장애 대응, 성능 기록, PR 설명 초안과 팀별 작업은 [프로젝트 Notion](https://app.notion.com/p/ICT-1e29aa63ac5a826b9f1981fca9529d8f)에서 관리합니다.

- 기술 계약·운영·성능: [기술 문서 허브](https://app.notion.com/p/3cb9aa63ac5a81759133f1e0fe055579)
- 일정·담당·완료 조건: Notion Tasks
- 엔드포인트 상세: Notion API 설계
- 장애·의사결정·검증 증적: Notion 개발 스토리 기록소
- PR 작성 시 별도 `docs/*.md`를 만들지 않고 Notion에 배경, 변경 범위, API·DB 영향, 테스트 결과, 배포·rollback, 후속 작업을 기록합니다.

## 보안

- `.env`, DB URL, 비밀번호, token, JWT secret, MinIO key를 커밋하지 않습니다.
- 다른 사용자의 리소스 UUID는 존재 여부를 노출하지 않도록 404로 처리합니다.
- 로그와 오류 응답에 stack trace, 내부 주소, 문서 원문을 남기지 않습니다.
- 배포 전 로그인 rate limit, JWT 폐기·교체, 업로드 검증과 프롬프트 인젝션 방어를 점검합니다.
