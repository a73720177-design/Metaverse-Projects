# 팀 통합 현황 및 Backend 작업 목록

확인일: 2026-08-22

이 문서는 각 파트의 최신 원격 브랜치와 열린 Pull Request를 비교하여, 현재 통합 상태와 다음 작업을 공유하기 위한 문서입니다. 실제 API의 최종 기준은 실행 중인 Backend의 `/docs`와 `backend/docs/` 아래 계약 문서입니다.

## 현재 기준 브랜치

| 파트 | 파트 main | 최신 작업 브랜치 | 확인 결과 |
|---|---|---|---|
| 공통 | `main` | - | 최신 Backend 통합 변경이 아직 모두 반영되지 않음 |
| Backend | `Backend-main` | `imjae-workingtree` | Backend CI 통과, PR #18 병합 완료 |
| Frontend | `Frontend-main` | `kstttt` | React + Vite 구현이 작업 브랜치에 있으며 PR #19 리뷰 대기 |
| LLM | `LLM-main` | `kunhee-workspace` | legacy 및 정식 v1 API가 작업 브랜치에 있으며 PR #17 변경 요청 상태 |
| DB | `DB-main` | `Backend-CYCL-2`, `DB-One-of-kind-1` | 문서 저장 구조와 OCR 실험이 여러 브랜치에 나뉘어 있음 |

파트별 main보다 작업 브랜치가 최신인 경우가 있으므로, 연동 작업 전에는 대상 PR과 최신 커밋을 함께 확인해야 합니다.

## 열린 Pull Request

### PR #17: LLM

- 대상: `kunhee-workspace` → `LLM-main`
- 상태: 변경 요청으로 병합 차단
- 구현: legacy API, `/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat`, Ollama 상태 확인, 테스트 추가
- Backend의 v1 요청·응답 구조와 큰 차이는 없음
- PR에 자동 테스트 결과가 연결되어 있지 않음

확인이 필요한 내용:

1. Ollama가 JSON이 아닌 응답을 반환할 때 통제된 502 또는 503 오류를 반환합니다.
2. `llm_client`의 실제 JSON 파싱 실패 테스트를 추가합니다.
3. 변경 요청 반영 후 재리뷰를 요청합니다.
4. 실제 LLM 연동이 성공한 뒤 Backend의 `LLM_CONTRACT_MODE`를 `v1`로 전환합니다.

### PR #19: Frontend

- 대상: `kstttt` → `Frontend-main`
- 상태: 리뷰 필요로 병합 차단
- 구성: React 18 + Vite 5
- PR에 build, lint, test 자동 검사가 연결되어 있지 않음

현재 Frontend 요청과 Backend API에는 다음 차이가 있습니다.

| Frontend 구현 | 현재 Backend |
|---|---|
| `POST /api/auth/login` | 인증 API 없음 |
| `POST /api/chat/stream` | `POST /agents/{agent_id}/chat` |
| SSE 스트리밍 응답 | JSON 단일 응답 |
| persona 문자열 전달 | UUID 형식의 `agent_id` 사용 |
| `{message}` 오류 응답 처리 | `{error: {code, message}}` 형식 사용 |

첫 통합에서는 현재 Backend의 UUID 기반 JSON API에 Frontend 요청을 맞추는 편이 작업 범위와 장애 지점을 줄일 수 있습니다. 인증과 SSE가 반드시 필요하면 별도 API 계약, 접근 제어, 연결 종료 및 재접속 정책을 먼저 정의해야 합니다.

## DB 통합 시 주의사항

`Backend-CYCL-2`에는 다음과 같은 활용 가능한 변경이 있습니다.

- `documents`, `document_files`, `document_chunks` 분리 구조
- `002_split_document_storage.sql` 마이그레이션
- `{document_id}/original{suffix}` 형식의 객체 저장 경로

다만 이 브랜치는 최신 `Backend-main`의 모든 안전장치를 포함하지 않으므로 전체 코드를 그대로 적용하면 안 됩니다. 최신 Backend 구조를 유지하면서 모델, repository, migration 변경을 선별하여 연결해야 합니다.

유지해야 하는 Backend 동작:

- `REPOSITORY_MODE=memory|postgres`
- `OBJECT_STORAGE_MODE=local|minio`
- 환경변수 시작 시 검증
- 파일명, 빈 파일, 파일 크기 검증
- 업로드 실패 시 DB 및 저장 객체 정리
- `{error: {code, message}}` 공통 오류 구조
- Python 3.14 호환 의존성

마이그레이션 확인 항목:

1. `002_split_document_storage.sql`을 반복 실행해도 실패하지 않도록 보완합니다.
2. `DROP COLUMN` 실행 전에 백업하고 테스트 DB에서 먼저 검증합니다.
3. 사용하는 PostgreSQL에서 `gen_random_uuid()` 지원 여부를 확인합니다.
4. 테이블과 제약조건 이름의 충돌 가능성을 확인합니다.
5. MinIO object key 규칙을 Backend 업로드·삭제 로직과 동일하게 맞춥니다.

## Backend 우선 작업

### P0: 파트 간 계약 확정

- [ ] Frontend 인증과 SSE를 현재 MVP 범위에 포함할지 결정
- [ ] Frontend 요청 경로, UUID, 오류 응답을 Backend 계약과 일치시킴
- [ ] LLM PR #17 재리뷰 및 자동 테스트 결과 확인
- [ ] DB 문서 테이블 구조와 MinIO object key 규칙 확정

### P1: DB 안전 통합

- [ ] 최신 Backend 구조에 DB 모델과 repository 연결
- [ ] 재실행 가능한 migration으로 보완
- [ ] PostgreSQL·MinIO 실패 시 정리 동작 검증
- [ ] Persona → Document → Review 전체 흐름을 테스트 DB에서 검증

### P1: 실제 LLM 통합

- [ ] LLM PR 병합 후 persona, review, chat HTTP 연동 테스트
- [ ] Ollama 중단, timeout, 잘못된 JSON 응답 테스트
- [ ] v1 검증 완료 후 계약 모드 전환

### P2: Frontend 연동 지원

- [ ] Vite 환경변수에는 Backend 주소만 설정
- [ ] `/agents`, `/documents/parse`, review, chat 호출 흐름 연결
- [ ] 채팅 메시지 개수와 요청 본문 크기 제한
- [ ] 업로드 크기와 지원 확장자를 UI에 표시

## 보안 점검 결과

2026-08-21 원격 저장소 기준 점검 결과입니다.

확인된 정상 항목:

- 실제 `.env` 파일과 확인 가능한 비밀정보가 Git 추적 파일에서 발견되지 않음
- Git 이력에서 공유 DB 비밀번호 패턴이 발견되지 않음
- GitHub Secret Scanning 및 Push Protection 활성화
- 열린 Secret Scanning 경고와 CodeQL 경고 없음
- 최신 `main` CodeQL 성공
- 최신 `Backend-main` Backend CI 성공
- GitHub Actions 기본 권한이 읽기 전용이며 PR 자동 승인이 비활성화됨

개선할 항목:

- [ ] Dependabot alerts 및 security updates 활성화
- [ ] Frontend에 `npm build`, lint, test CI 추가
- [ ] LLM에 pytest CI 추가
- [ ] 필요한 GitHub Actions만 허용하거나 action 버전을 commit SHA로 고정
- [ ] Frontend 토큰의 `localStorage` 저장 위험 검토
- [ ] 채팅 요청 크기, 메시지 수, 업로드 크기 제한 적용
- [ ] 로그에 토큰, DB URL, 문서 본문이 기록되지 않는지 확인

저장소는 Public이므로 실제 DB URL, 비밀번호, MinIO secret, 토큰은 코드·문서·Issue·PR 본문에 작성하지 않습니다. 노출이 의심되면 값을 즉시 교체한 뒤 GitHub 보안 경고를 확인합니다.

## Ruleset 확인 결과

파트별 main(`Backend-main`, `Frontend-main`, `LLM-main`, `DB-main`)에는 다음 보호가 적용되어 있습니다.

- 브랜치 삭제 및 force push 금지
- Pull Request 필수
- 승인 1명과 리뷰 대화 해결 필요
- squash merge만 허용

승인 후 새 커밋이 추가되어도 기존 승인이 유지될 수 있으므로 `Dismiss stale approvals when new commits are pushed` 활성화를 권장합니다.

공통 `main`에는 승인 2명, CODEOWNERS 승인, 마지막 push 승인, CodeQL 검사와 squash merge 제한이 적용되어 있습니다. 우회 권한은 긴급 복구처럼 사전에 합의한 상황에서만 사용해야 합니다.

## 통합 전 공통 확인

- [ ] 각 파트의 실제 실행 방법과 `.env.example`이 최신 상태임
- [ ] Frontend는 Backend만 호출하고 DB, Ollama, LLM에 직접 접근하지 않음
- [ ] API 요청·응답 예시가 계약 문서 및 `/docs`와 일치함
- [ ] 실제 비밀정보가 Git 추적 파일과 PR 본문에 없음
- [ ] 각 파트의 자동 검사와 수동 연동 테스트 결과를 PR에서 확인 가능함
- [ ] 실패 응답에 내부 주소, stack trace, 문서 본문이 포함되지 않음

관련 문서:

- [통합 계약](./backend/docs/INTEGRATION_CONTRACTS.md)
- [LLM HTTP 계약](./backend/docs/LLM_HTTP_CONTRACT.md)
- [DB 통합 안내](./backend/docs/DB_INTEGRATION.md)
- [Frontend 연동 안내](./backend/docs/FRONTEND_INTEGRATION.md)
- [버전 호환성](./backend/docs/VERSION_COMPATIBILITY.md)
- [팀 코드 확인 안내](./backend/docs/TEAM_CODE_GUIDE.md)
