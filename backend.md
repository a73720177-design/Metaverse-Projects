# Backend 작업 계획 및 팀 브랜치 분석

현재 반영 브랜치: `imjae-workingtree`

통합 작업 출처: `backend-cycl-2-integration-fix`

확인일: 2026-08-18

이 문서는 원격 브랜치를 읽기 전용으로 비교해 Backend에서 해야 할 연결 작업을 정리한 문서입니다.
다른 팀 브랜치의 코드를 Backend 브랜치로 임의 복사하지 않고 HTTP·Repository 계약으로 연결합니다.

## 확인한 브랜치

| 구분 | 팀 main | 작업 브랜치 | 확인 결과 |
|---|---|---|---|
| 공통 | `main` | - | Backend 기본 구조만 병합되어 있고 Frontend·LLM 실제 코드는 아직 없음 |
| Backend | `Backend-main` | `Backend-CYCL-2` | PostgreSQL Repository, SQL 스키마, MinIO 저장소 구현 추가 |
| Backend 통합 | `Backend-CYCL-2` | `backend-cycl-2-integration-fix` | memory/postgres 및 local/minio 모드, Python 3.14 호환 처리 완료 |
| LLM | `LLM-main` | `kunhee-workspace` | legacy 2개와 정식 `/api/v1` 4개 API 구현, PR #17 리뷰 중 |
| DB | `DB-main` | `DB-One-of-kind-1` | GOT-OCR 2.0과 Surya 실험 스크립트만 추가됨 |
| Frontend | `Frontend-main` | `kstttt` | React + Vite 코드가 있으나 임시 SSE API를 사용해 Backend 계약과 다름 |

## 발견한 연결 차이

### LLM

- 최신 LLM 작업 브랜치는 `/extract-concepts`, `/generate-questions`와 함께
  `/api/v1/health`, `/personas`, `/reviews`, `/chat`을 모두 제공합니다.
- Backend의 `legacy_questions` 모드는 PR 병합 전에도 기존 두 API에 연결할 수 있습니다.
- 정식 v1 요청·응답은 Backend 모델과 일치하며 Persona·Review·Chat mock 계약 테스트를 추가했습니다.
- PR #17이 `LLM-main`에 병합되고 자동화 테스트가 보완되기 전까지 기본 모드는 legacy로 유지합니다.
- LLM의 `/health`는 프로세스 상태만 반환하며 Ollama 모델 준비 여부까지 확인하지 않습니다.
- LLM이 요구하는 모델은 `qwen3:14b`이므로 모든 팀 PC에서 설치 가능하다고 가정하면 안 됩니다.

### DB

- `Backend-CYCL-2`에는 `agents`, `documents`, `reviews`용 SQLAlchemy Repository가 있습니다.
- 기존 DB의 `document_files`, `document_chunks` 구조와 새 `documents` 구조가 일치하지 않습니다.
- `DB-One-of-kind-1`의 OCR 코드는 Repository나 API가 아닌 독립 실행 실험 코드입니다.
- GOT-OCR 결과는 Markdown 문자열, Surya 결과는 좌표 목록이므로 현재
  `DocumentParseResponse`에 바로 저장할 공통 결과 계약이 없습니다.
- OCR 모델 실행은 DB 저장 책임과 다르므로 별도 OCR 서비스 또는 문서 파서 계층으로 분리해야 합니다.

### Frontend

- `kstttt`에는 React + Vite 코드가 있지만 `POST /api/chat/stream` SSE를 임시로 가정합니다.
- Backend의 실제 Chat API는 `POST /agents/{agent_id}/chat`이며 JSON 한 번으로 응답합니다.
- Frontend는 persona 이름이 아니라 Backend가 발급한 `agent_id`를 저장해야 합니다.
- Frontend의 `.ppt` 선택은 Backend가 지원하지 않으므로 `.pptx,.pdf,.docx`로 맞춰야 합니다.

## Backend 순차 작업

### P0 — 팀 통합 전에 완료

- [x] Repository를 `memory|postgres` 모드로 분리
- [x] 파일 저장소를 `local|minio` 모드로 분리
- [x] DB 연결 지연 초기화 및 종료 시 연결 정리
- [x] Python 3.14용 asyncpg/greenlet 버전 수정
- [x] DB 저장 실패 시 업로드 객체 삭제
- [x] `GET /health/db`로 현재 Repository 모드와 PostgreSQL 연결 상태 제공
- [x] legacy LLM 응답의 `concepts`, `questions` 구조를 Backend에서 엄격하게 검증
- [x] PostgreSQL/MinIO 오류를 내부 정보가 없는 공통 503 응답으로 변환
- [x] 업로드 파일 이름, 빈 파일, 최대 크기 검증
- [x] 위 항목의 단위 테스트 추가
- [x] PR #17 전체 커밋 기준 v1 Persona·Review·Chat·오류 계약 테스트 추가

### P1 — 팀 코드가 각 main에 올라온 뒤 완료

- [ ] DB 팀이 확정한 문서 테이블에 `DocumentRepository` 필드 매핑
- [ ] 버전 관리되는 DB migration 적용 방식 확정
- [ ] LLM `kunhee-workspace`가 `LLM-main`에 병합된 뒤 실제 HTTP 통합 테스트
- [ ] Persona → Document → Review 전체 흐름을 PostgreSQL 테스트 DB에서 검증
- [ ] Frontend React + Vite 코드가 올라오면 실제 요청과 `/docs` 비교
- [ ] Frontend에서 Backend 공통 오류 `error.code`, `error.message` 표시 확인

### P2 — MVP 연결 후 안정화

- [ ] LLM timeout 및 제한적 재시도 정책 적용
- [ ] 대용량 문서를 LLM에 보낼 때 길이 제한 또는 chunk 정책 적용
- [ ] OCR 결과 계약 정의 후 문서 파서 또는 독립 OCR 서비스와 연결
- [ ] `/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat` 전환 시 legacy 모드 제거 계획
- [ ] 실제 서비스 통합 테스트와 CI 분리

## 다른 팀에 필요한 결정

### DB 팀

1. `documents` 또는 `document_files + document_chunks` 중 최종 구조를 선택합니다.
2. SQL migration 파일과 적용 순서를 제공합니다.
3. JSONB 필드 구조와 외래 키 삭제 정책을 Backend 모델과 맞춥니다.
4. MinIO bucket 및 object key 규칙을 확정합니다.
5. 실제 공유 DB와 분리된 `TEST_DATABASE_URL`을 제공합니다.
6. OCR은 DB Repository에 넣지 말고 입력·출력 계약을 먼저 제안합니다.

### LLM 팀

1. `kunhee-workspace` 구현을 검증한 뒤 `LLM-main`에 PR로 병합합니다.
2. `/health`에서 Ollama 연결 및 모델 존재 상태를 구분할지 결정합니다.
3. `concepts`와 `questions` 응답 구조를 유지합니다.
4. chat/persona API 구현 전까지 변경 예정 경로와 JSON 계약을 먼저 공유합니다.

### Frontend 팀

1. React + Vite 코드를 작업 브랜치에 커밋·푸시합니다.
2. 모든 요청은 `VITE_API_BASE_URL`을 통해 Backend만 호출합니다.
3. 파일 업로드는 `FormData`를 사용하고 `Content-Type`을 직접 지정하지 않습니다.
4. Backend의 UUID와 공통 오류 응답을 저장·표시하는 방식을 공유합니다.

## 완료 기준

```powershell
cd C:\meta_project\backend
.\.venv\Scripts\python.exe -m pytest -q
```

- 기본 모드에서 DB·MinIO 없이 모든 단위 테스트 통과
- 별도 테스트 DB에서 Repository 통합 테스트 통과
- LLM 8001과 Ollama 11434 실행 상태에서 Review 생성 통과
- Frontend 5173에서 Backend 8000 API 호출 통과
- 코드와 문서에 실제 비밀번호, DB URL, MinIO secret이 없음
