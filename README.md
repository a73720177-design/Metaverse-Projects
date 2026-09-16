# Metaverse Projects

PPTX·PDF·DOCX 발표 자료를 업로드하고 평가자 페르소나의 관점으로 리뷰와 질의응답을 제공하는 서비스입니다. React + Vite Frontend는 FastAPI Backend만 호출하며, Backend가 LLM Service·PostgreSQL·MinIO를 조합합니다.

## 아키텍처

모델 문맥 예산, 비전 모델 유지, 긴 문서 전체 분석, 선택적 검색 재정렬 설정은 [모델 파이프라인 개선 안내](docs/model-pipeline-improvements.md)를 참고하세요.

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
- Persona 기반 Review와 자료 첨부 Chat
- Chat 이력, 휴지통 이동·복원·완전 삭제
- Chat JSON 응답 및 SSE 스트리밍. 화면은 토큰을 즉시 표시하고 생성 중에는 근거 검증 전임을 표시합니다. 명시적 reasoning 태그를 조각 단위로 제거하며 중지·화면 이탈 시 상위 HTTP 스트림까지 닫습니다. 최종 근거 검증·저장에 실패하면 부분 답변을 완료 결과로 남기지 않습니다.
- 질문자별 예상 질문 1~10개 선택, 발표 근거 ID 검증, 질문자 간 중복 제거와 1회 보충 요청. 부족분은 근거를 인용한 보충 질문으로 표시하며, 다양성·근거 부족 시 실제 개수와 이유를 표시합니다. 이전 질문을 제외 목록으로 전달하기 위해 질문자는 순차 처리합니다.
- 리뷰 생성·목록·상세, 대화 이력, 질문자·대화 휴지통 복원·완전 삭제를 화면에서 제공합니다.
- 예상 질문과 질문별 conversation UUID를 연습 세션에 저장하고 새로고침·재로그인 시 복원합니다. 세션 목록은 최근 50개, 리뷰 목록은 최근 100개입니다. `memory` 기록은 프로세스 재시작 시 사라지고 영속 저장에는 `postgres`가 필요합니다.
- 리뷰·요약·예상 질문에 분석 범위(`coverage`)를 표시합니다. 범위 정보가 없는 기존 기록은 “분석 범위 정보 없음”으로 표시합니다. 예상 질문의 lexical 개요는 문서별 처음·중간·마지막 구간을 균등한 문자 예산으로 선택합니다.
- 긴 대화 원문은 보존하고 LLM 전송 이력만 항목당 2,000자·최대 20개·합계 12,000자로 제한합니다. LLM Service는 프롬프트 이력 예산에 맞춰 추가로 축약하며 LLM 프롬프트에 생략 사실을 표시합니다.
- 페르소나 생성·수정 시 사용자 설명(최대 5,000자)과 첨부 근거(`reference_context`, 파일명 포함 최대 3,000자)를 분리합니다. 첨부 근거는 사용자 설명에 저장하지 않습니다. 첨부 근거를 지원하는 LLM Service가 필요합니다. 아래 배포 순서를 따릅니다.
- `memory|postgres` Repository, `local|minio` Object Storage
- LLM `/api/v1` 단일 계약 (personas·reviews·practice·summaries·embeddings·chat)
- 문서 근거 질문과 일반 대화를 지연 없는 경량 규칙으로 분기하는 LLM Chat 프롬프트
- 질문 관련 문서 청크 선택, 캐시, 출력 제한과 Ollama keep-alive를 통한 Chat 지연 개선
- 기본값은 `RAG_MODE=vector`, `REPOSITORY_MODE=postgres`입니다. Backend가 Ollama 임베딩 모델을 직접 호출해 `document_chunks`를 pgvector로 시맨틱 검색합니다. 색인 미완료나 검색 실패 시 lexical 검색으로 전환합니다.
- 문서 요약·핵심 주제 API(`brief`/`detailed`/`outline` 스타일, 선택적 페르소나 관점). 동일 (문서, 페르소나, 스타일) 조합은 캐시된 결과를 재사용하고 `refresh=true`일 때만 재생성. LLM Service는 긴 문서를 map-reduce로 나눠 처리
- `GROUNDING_MODE`(`off`/`annotate`/`strict`)로 Chat 답변-근거 검증. LLM을 다시 부르지 않고 lexical 포함률 + 애매한 문장만 배치 임베딩 재확인으로 `grounding` 필드를 채움. 기본값 `off`

`backend/database/005_add_trash_and_chat_history.sql`은 `chat_messages`, `agents.deleted_at`, Agent 외래키 cascade와 휴지통 인덱스를 반영합니다. `009_add_document_chunk_embeddings.sql`은 `pgvector` 확장과 `document_chunks.embedding`/`embedding_model`/`embedded_at`/`content_hash` 컬럼을 추가합니다(테이블의 기존 의미는 바꾸지 않습니다). `010_add_summaries.sql`은 문서 요약을 저장하는 `summaries` 테이블을 추가합니다. `docker-compose.yml`의 postgres 이미지는 `pgvector/pgvector:pg16`을 사용합니다. Migration을 공유 DB에 적용하기 전에 별도 테스트 DB에서 적용·재실행·rollback을 검증해야 합니다.

## 기능 정합성 개선 배포

1. 별도 테스트 DB에서 `001`~`014`를 순서대로 적용하고 재실행·Repository 테스트를 확인합니다. `013_add_result_metadata_and_practice_sessions.sql`은 Chat grounding, 리뷰·요약 coverage, 연습 세션을 저장하고, `014_add_lexical_search_index.sql`은 PostgreSQL의 `pg_trgm` 기반 lexical 검색 인덱스를 추가합니다. Persona 완전 삭제 시 해당 요약도 삭제하여 일반 요약 캐시로 잘못 전환되지 않게 합니다. memory 모드에도 리뷰 참조 삭제 제한과 Persona 삭제 cascade를 적용했습니다.
2. **예상 질문 내부 계약이 변경되었습니다.** 이전 `{persona, document, instructions}` / 문자열 질문 배열 대신 `{persona, question_count, evidence: [{id, scope, text}], excluded_questions}` / `{questions: [{question, presentation_evidence_ids, focus}]}`를 사용합니다. DB를 먼저 업그레이드하고 Backend와 LLM Service는 요청을 중단한 유지보수 구간에 함께 교체한 뒤 Frontend를 배포합니다. 서로 다른 버전을 섞지 않습니다.
3. 질문 결과는 `requested_count`, `generated_count`, `status=complete|fallback|partial`, `warnings`, 질문별 `origin=model|template`를 포함합니다. evidence ID는 실제 전달한 발표 구간만 허용하며, 질문자 참고자료는 평가 관점으로만 사용합니다. 단어·수치·중복 검사는 의미적 사실 검증을 보장하지 않으므로 모델 품질 검증은 별도로 진행합니다.
4. 롤백은 Backend·LLM·Frontend 버전을 함께 되돌리고 추가된 테이블·컬럼은 보존합니다. Persona 요약 cascade 정책까지 되돌리는 SQL은 `013` 하단에 안내되어 있습니다. 이미 완전 삭제된 행은 백업에서만 복구할 수 있습니다.

`GROUNDING_MODE=strict`는 최종 검증 결과에 따라 답변을 대체하며, 생성 중 토큰의 사실성을 보증하지 않습니다. grounding 결과는 DB에 저장해 재조회·휴지통 복원에도 유지합니다. 직접 인용 마커 없이 반환된 채팅 sources는 화면에서 참고자료로 구분합니다.

### 업로드 분석 제한

- 빈 파일, 확장자·MIME·PDF 시그니처 또는 Office 내부 구조 불일치를 거절합니다. Office ZIP은 항목 5,000개, 해제 합계 100MB, 개별 항목 25MB, 압축률 200배를 기본 상한으로 사용합니다. 합계와 개수는 `UPLOAD_MAX_EXPANDED_BYTES`, `UPLOAD_MAX_ZIP_ENTRIES`로 조정합니다. 크기 제한은 413, 형식 오류는 400입니다.
- 파서는 별도 프로세스에서 실행합니다. `PARSER_TIMEOUT_SECONDS` 기본 120초(VLM 활성화 시 650초), `PARSER_MEMORY_MB` 기본 1,024MB이며 시간 초과 시 하위 프로세스 그룹을 종료합니다. Linux는 주소 공간 상한, macOS는 0.1초 간격 RSS 감시를 사용합니다. Windows에는 시간 제한만 적용되므로 메모리 강제 제한이 필요한 배포는 Linux 컨테이너를 사용합니다.
- 문서 결과는 1,000개 구간·200만 자 이하여야 합니다. 기존 대형 문서의 리뷰·요약 요청에도 동일한 분석 한도를 적용합니다. VLM 연결 실패는 503입니다.
- 유효한 시그니처의 PDF/PPTX에서 텍스트 추출에 실패했을 때 원본을 보관하는 기존 정책은 유지합니다. `parse_status=no_text`와 경고를 표시하며 예상 질문 생성 대상에서 제외합니다. 텍스트 없는 리뷰·요약은 422를 반환합니다.
- 오류 로그에는 예외 원문·traceback을 넣지 않고 오류 종류와 요청 ID로 추적합니다. SQLAlchemy 파라미터 출력도 숨깁니다.

## 빠른 실행

Windows PowerShell 기준입니다. Python 가상환경은 서비스별로 분리할 수 있습니다.

### 1. Ollama

```powershell
ollama serve
ollama pull qwen3:4b
# 기본 벡터 RAG에 필요한 임베딩 모델입니다.
ollama pull bge-m3
```

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
# 아래 PostgreSQL 준비 및 .env 설정을 완료한 뒤 서버를 실행합니다.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

기본 실행에는 PostgreSQL(pgvector)과 Ollama의 `bge-m3` 모델이 필요합니다. 프로젝트 루트에서 `docker compose up -d postgres`로 로컬 DB를 실행할 수 있습니다. `backend/.env`에 해당 DB의 `DATABASE_URL`과 32바이트 이상의 `JWT_SECRET_KEY`를 설정합니다. Backend 폴더에서 번호 migration(009 포함)을 적용한 후 서버를 시작합니다.

```powershell
python scripts/apply_migrations.py --dry-run
python scripts/apply_migrations.py --apply --confirm-database qwendb
```

기존 문서에 임베딩이 없으면 `python scripts/reindex_embeddings.py --owner-id <사용자 UUID>`로 색인합니다. 신규 문서는 저장 시 자동으로 색인됩니다. 이미 `.env`에 `RAG_MODE=lexical` 또는 `REPOSITORY_MODE=memory`가 있으면 각각 `vector`, `postgres`로 변경해야 합니다.

PostgreSQL과 MinIO 없이 실행하는 개발·단위 테스트 모드는 명시적으로 설정합니다:

```env
REPOSITORY_MODE=memory
RAG_MODE=lexical
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
| Review | `POST /agents/{agent_id}/reviews`, `GET /reviews`, `GET /reviews/{review_id}` |
| 문서 요약 | `POST /documents/{document_id}/summary`, `GET /documents/{document_id}/summary` |
| 예상 질문·연습 복원 | `POST /practice/questions`, `GET /practice/sessions`, `GET /practice/sessions/{session_id}` |
| Chat | `POST /agents/{agent_id}/chat`, `POST /agents/{agent_id}/chat/stream`, `GET /chats` |
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
npm test
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

버전에 종속되어 코드와 함께 검증해야 하는 API 계약·DB migration·실행 및 장애 대응 문서는 저장소에 유지합니다. 일정, 담당자, 회의 결정, 진행 상태와 PR 설명 초안은 [프로젝트 Notion](https://app.notion.com/p/ICT-1e29aa63ac5a826b9f1981fca9529d8f)에서 관리합니다.

- 기술 계약·운영·성능: [기술 문서 허브](https://app.notion.com/p/3cb9aa63ac5a81759133f1e0fe055579)
- 일정·담당·완료 조건: Notion Tasks
- 엔드포인트 상세: Notion API 설계
- 장애·의사결정·검증 증적: Notion 개발 스토리 기록소
- 새 저장소 문서는 실행 코드와 함께 변경·검증되어야 하는 기술 계약에 한정합니다. PR의 배경, 일정, 담당, 테스트 증적과 후속 작업은 Notion에 기록합니다.

## 보안

- `.env`, DB URL, 비밀번호, token, JWT secret, MinIO key를 커밋하지 않습니다.
- 다른 사용자의 리소스 UUID는 존재 여부를 노출하지 않도록 404로 처리합니다.
- 로그와 오류 응답에 stack trace, 내부 주소, 문서 원문을 남기지 않습니다.
- 배포 전 로그인 rate limit, JWT 폐기·교체, 업로드 검증과 프롬프트 인젝션 방어를 점검합니다.

## PPTX/PDF 이미지 분석

로컬 Qwen3-VL로 슬라이드의 그림·차트·도식을 읽어 기존 예상 질문과 피드백에 반영할 수 있습니다. LibreOffice와 VLM 설치 후 `backend/.env`에서 `DOCUMENT_VISION_MODE=ollama`로 활성화하세요. 기본값은 텍스트 파싱(`off`)입니다. [설치·모델 선정·제한 사항](docs/LOCAL_VISION.md)을 참고하세요.
