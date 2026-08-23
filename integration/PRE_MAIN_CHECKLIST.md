# 공통 main 병합 전 팀별 우선 작업

이 문서의 우선순위는 팀의 중요도나 작업량 순서가 아닙니다. **Backend가 Frontend 요청을 받아 LLM과 DB를 호출하는 전체 흐름을 검증하기 위해 필요한 의존 순서**입니다.

## 우선순위 기준

| 우선순위 | 의미 | 공통 main 병합 기준 |
|---|---|---|
| P0 | 병합 전 필수 | 완료되지 않으면 공통 main 통합 검증이 불가능하거나 비밀 정보가 노출됨 |
| P1 | MVP 완성 | 병합은 가능하지만 핵심 기능 일부가 임시 구현 또는 미완성 상태 |
| P2 | 안정화 | 기능 연결 후 품질·성능·운영 편의성을 높이는 작업 |

## 1. 공통 계약 — P0

모든 팀이 먼저 확인합니다.

- [ ] Frontend가 호출할 Backend 경로를 실행 중인 `/docs`와 비교
- [ ] LLM 요청·응답을 `backend/docs/LLM_HTTP_CONTRACT.md`와 비교
- [ ] DB 모델을 `backend/app/repositories/` 인터페이스와 비교
- [ ] UUID와 JSON 필드 이름의 철자·필수 여부 확정
- [ ] `.env`, 비밀번호, 실제 인증 URL이 Git에 포함되지 않았는지 확인
- [ ] 각 팀 서비스 포트 확정: Frontend 5173, Backend 8000, LLM 8001, Ollama 11434, PostgreSQL 5432

완료 조건: 팀별 코드 수정 전에 공통 요청·응답 예시를 모두가 확인합니다.

## 2. Backend 팀

### P0 — 공통 진입점 유지

- [x] Controller → Service → Repository 구조 정리
- [x] React + Vite localhost·Hamachi CORS 구성
- [x] 현재 LLM API용 `legacy_questions` 호환 모드 구현
- [x] 공통 오류 응답 `error.code`, `error.message` 적용
- [x] Backend 테스트 13개 통과
- [ ] PR #14 리뷰 후 `Backend-main`에 Squash merge
- [ ] Squash 후 `Backend-main`에서 테스트 재실행

완료 조건:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

결과가 `13 passed`이고 `/health`, `/docs`, `/health/llm`이 의도한 상태를 반환해야 합니다.

### P1 — 실제 저장 연결

- [ ] DB 팀의 Repository 구현을 `app/dependencies.py`에 연결
- [ ] 서버 재시작 후 Agent·Document·Review 조회 확인
- [ ] DB 연결 실패를 Frontend 공통 오류로 변환
- [ ] Review·Chat 저장 정책 확정

### P2 — 안정화

- [ ] 업로드 크기 제한과 파일명 검증
- [ ] LLM·DB timeout과 재시도 정책 정리
- [ ] 실제 서비스 통합 테스트와 CI 추가
- [ ] 로그에서 문서 내용과 인증 정보 제거

## 3. LLM 팀

### P0 — Backend가 호출할 서비스 제공

- [ ] `kunhee-workspace`의 `llm-service/`를 검토 후 `LLM-main`에 PR
- [ ] `GET /health`가 8001번 포트에서 응답
- [ ] `POST /extract-concepts` 요청·응답 검증
- [ ] `POST /generate-questions` 요청·응답 검증
- [ ] Ollama 모델 `qwen3:14b` 설치와 `/api/tags` 확인
- [ ] 오류 시 HTML이나 일반 문자열 대신 FastAPI JSON 오류 반환

완료 조건: Backend의 `LLM_CONTRACT_MODE=legacy_questions` 상태에서 Persona 생성과 Review 생성이 끝까지 성공해야 합니다.

### P1 — 정식 v1 계약

- [ ] `/api/v1/health` 구현
- [ ] `/api/v1/personas` 구현
- [ ] `/api/v1/reviews` 구현
- [ ] `/api/v1/chat` 구현
- [ ] 구조화 JSON 출력과 Pydantic 검증 적용
- [ ] v1 완료 후 Backend 설정을 `LLM_CONTRACT_MODE=v1`로 전환

### P2 — 안정화

- [ ] 모델 다운로드·버전·최소 사양 문서화
- [ ] Ollama timeout과 모델 오류 테스트
- [ ] 프롬프트 회귀 테스트용 고정 입력·예상 구조 추가
- [ ] 응답 시간과 메모리 사용량 기록

## 4. DB 팀

### P0 — 보안과 접속 기준 정리

- [ ] 대화나 테스트 중 공유된 DB 비밀번호 변경
- [ ] PostgreSQL·MinIO 주소와 인증 정보를 코드에서 제거하고 `.env`로 이동
- [ ] `qwendb`의 스키마 생성 SQL 또는 마이그레이션 파일 제공
- [ ] 현재 `document_files`, `document_chunks` 컬럼·관계·제약조건 문서화
- [ ] Hamachi에서 필요한 IP만 PostgreSQL 접속 허용
- [ ] 실제 비밀번호와 `DATABASE_URL`이 Git에 없는지 확인

완료 조건: 새 비밀번호로 읽기 전용 접속 검증이 성공하고, 저장소에는 예시 환경 변수만 존재해야 합니다.

### P1 — Backend Repository 제공

- [ ] `AgentRepository` 구현
- [ ] `DocumentRepository` 구현 및 기존 문서 테이블 매핑
- [ ] `ReviewRepository` 구현
- [ ] 트랜잭션 commit·rollback 처리
- [ ] 조회 결과가 없을 때 `None` 반환
- [ ] DB 모델을 Backend Pydantic 모델로 변환

### P2 — 확장 저장소

- [ ] MinIO 업로드·다운로드 인터페이스 분리
- [ ] Vector DB 저장·검색 계약 합의
- [ ] 백업·복구 절차와 개발용 seed 데이터 제공
- [ ] OCR 실험 코드를 독립 서비스 또는 문서 파서로 정리

## 5. Frontend 팀

### P0 — Backend API 기준으로 React + Vite 구성

- [ ] 실제 React + Vite 프로젝트를 `Frontend-main`에 PR
- [ ] `.env.example`에 `VITE_API_BASE_URL`만 공개
- [ ] `.env.local`, `.env.development.local` Git 제외
- [ ] LLM·Ollama·DB 주소를 Frontend 코드에서 제거
- [ ] `GET /health`로 Backend 연결 상태 표시
- [ ] 공통 API 클라이언트에서 `error.code`, `error.message` 처리

완료 조건: Frontend 담당자 PC와 Hamachi 접속 PC에서 화면이 열리고 Backend `/health` 호출이 성공해야 합니다.

### P1 — 핵심 사용자 흐름

- [ ] 페르소나 생성 후 `agent_id` 보관
- [ ] PPTX·PDF·DOCX 업로드 후 `document_id` 보관
- [ ] `agent_id`와 `document_id`로 Review 생성
- [ ] 로딩·실패·재시도 화면 제공
- [ ] Chat 미지원 상태에서는 버튼 비활성화 또는 안내 표시

### P2 — 안정화

- [ ] 새로고침 시 필요한 ID 상태 복구
- [ ] 파일 형식·크기 사전 검증
- [ ] 접근성, 반응형 UI, 오류 화면 개선
- [ ] Backend mock 없이 실제 통합 E2E 테스트 추가

## 6. 최종 통합 확인 — P0

각 팀 main이 준비된 후 공통 main PR 전에 실행합니다.

```powershell
Copy-Item integration\.env.example integration\.env
python integration\check_services.py
```

- [ ] Frontend 상태 `ok`
- [ ] Backend 상태 `ok`
- [ ] LLM 상태 `ok`
- [ ] Ollama 상태 `ok`
- [ ] PostgreSQL 상태 `ok`
- [ ] Swagger에서 Persona → Document → Review 순서로 수동 테스트
- [ ] 비밀 정보 검사
- [ ] 각 팀 담당자 최소 1명 리뷰

Chat과 실제 DB Repository가 P1로 남아 있다면 공통 main README에 제한 사항을 명확히 기록하고 병합합니다.

## 권장 진행 순서

```text
공통 계약 확인
  → DB 보안 조치 + LLM 서비스 실행 준비
  → Backend-main 검증
  → Frontend 실제 API 연결
  → Persona·Document·Review 통합 테스트
  → 각 팀 main PR
  → 공통 main PR
```

작업은 병렬로 진행할 수 있지만, 완료 확인은 위 순서로 수행합니다.
