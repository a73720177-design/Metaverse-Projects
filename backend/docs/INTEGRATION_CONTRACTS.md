# 팀 연동 계약

이 문서는 Frontend, Backend, LLM, DB 팀이 서로의 코드를 직접 침범하지 않고 연동하기 위한 기준입니다. 내부 구현이 달라도 여기에 정의된 HTTP 요청·응답과 Repository 인터페이스를 지키면 각 팀은 독립적으로 개발할 수 있습니다.

## 1. 전체 구조

```text
Frontend ──HTTP──▶ Backend (:8000)
                      ├─HTTP──▶ LLM Service (:8001) ──▶ Ollama (:11434)
                      └─Repository──▶ DB / Vector DB / Object Storage
```

- Frontend는 Backend API만 호출합니다.
- Backend는 요청 검증, ID 관리, 파일 처리와 업무 흐름 조정을 담당합니다.
- LLM은 Backend와 분리된 HTTP 서버로 실행합니다. 이것이 팀에서 정한 **방식 B**입니다.
- Ollama는 LLM 서비스가 호출하며 Backend가 직접 호출하지 않습니다.
- DB 연결과 저장 방식은 Repository 구현체 뒤에 숨깁니다.

## 2. 팀별 담당 범위

| 팀 | 담당하는 것 | 담당하지 않는 것 |
|---|---|---|
| Backend | 공개 API, Pydantic 검증, ID, 파일 업로드·파싱, 서비스 흐름, 오류 변환 | 모델·프롬프트, DB 스키마·마이그레이션 |
| LLM | `/api/v1` LLM API, 프롬프트, 모델, Ollama 호출, 출력 형식 | Frontend 공개 API, 데이터 저장 |
| DB | 스키마, 마이그레이션, CRUD Repository, Vector DB·파일 저장소 | Backend 라우팅, LLM 프롬프트 |
| Frontend | Backend API 호출과 화면 처리 | LLM·Ollama·DB 직접 호출 |

팀별 패키지 버전은 달라도 됩니다. 단, API 경로와 JSON 형식은 반드시 일치해야 합니다.

## 3. Backend와 LLM 계약

Backend와 LLM은 Python 클래스를 공유하지 않고 HTTP로만 연결합니다. 기본 주소는 `http://localhost:8001/api/v1`입니다.

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/v1/health` | LLM 서비스와 Ollama 상태 확인 |
| POST | `/api/v1/personas` | 페르소나 생성 |
| POST | `/api/v1/reviews` | 문서 리뷰 생성 |
| POST | `/api/v1/chat` | 문서·페르소나 기반 대화 |

정확한 요청·응답 예시는 [LLM HTTP 계약](./LLM_HTTP_CONTRACT.md)을 따릅니다.

### Backend가 보장할 사항

- 페르소나와 문서를 조회해 LLM 요청에 포함합니다.
- 연결 실패, 시간 초과, 잘못된 JSON을 Backend 공통 오류로 변환합니다.
- `agent_id`, `document_id`, `review_id` 등 서비스 ID를 관리합니다.
- LLM 주소와 시간 제한을 환경 변수로 관리합니다.

### LLM 팀이 보장할 사항

- `/api/v1` 경로와 계약된 JSON 필드 이름을 유지합니다.
- 모델의 자유 형식 문자열이 아닌 계약된 JSON 구조를 반환합니다.
- Ollama 연결 실패와 모델 오류를 적절한 HTTP 상태 코드로 반환합니다.
- Backend가 보낸 ID를 변경하거나 새 ID로 대체하지 않습니다.
- 호환되지 않는 변경은 기존 `/api/v1`을 유지하고 `/api/v2`로 분리합니다.

## 4. Backend와 DB 계약

Backend 서비스는 특정 DB 라이브러리를 직접 사용하지 않고 Repository 인터페이스를 사용합니다.

```python
class AgentRepository(Protocol):
    async def save(self, persona: PersonaProfile, owner_id: UUID) -> None: ...
    async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None: ...

class DocumentRepository(Protocol):
    async def save(self, document: DocumentParseResponse, owner_id: UUID) -> None: ...
    async def get(
        self, document_id: UUID, owner_id: UUID
    ) -> DocumentParseResponse | None: ...

class ReviewRepository(Protocol):
    async def save(self, review: ReviewResult, owner_id: UUID) -> None: ...
    async def get(self, review_id: UUID, owner_id: UUID) -> ReviewResult | None: ...
```

`owner_id`는 API 응답에 노출하지 않는 내부 소유권 경계입니다. 다른 사용자의 UUID를 조회하면 Repository는 `None`을 반환합니다. Chat은 별도 저장하지 않고 소유권이 확인된 Agent와 선택적 Document만 사용합니다.

### Repository 구현 규칙

- 조회 결과가 없으면 예외 대신 `None`을 반환합니다.
- 라우터에서 SQLAlchemy, ChromaDB 같은 DB 라이브러리를 직접 호출하지 않습니다.
- 연결 문자열과 비밀번호는 환경 변수로 관리합니다.
- DB 전용 객체를 API에 직접 반환하지 않고 Backend 도메인 모델로 변환합니다.
- 스키마 변경 전 Backend 팀과 필드 변환 방법을 합의합니다.
- Agent·Document·Review 생성과 조회에는 인증된 `owner_id`를 반드시 전달합니다.

## 5. 공통 오류 응답

Frontend에 공개되는 오류는 다음 형식을 사용합니다.

```json
{
  "error": {
    "code": "http_404",
    "message": "리뷰를 찾을 수 없습니다."
  }
}
```

- `code`: 프로그램이 분기 처리할 고정 값
- `message`: 사용자가 이해할 수 있는 설명
- 내부 주소, 비밀번호, 전체 예외 추적은 응답에 포함하지 않습니다.
- LLM·DB 오류도 Backend가 이 형식으로 변환하여 Frontend에 전달합니다.

## 6. 구현체 연결 위치

실제 구현체를 선택하고 서비스에 주입하는 작업은 `app/dependencies.py`에서만 수행합니다. 저장 계약은 `app/repositories/`, LLM 연동 계약은 `app/integrations/llm/`에서 확인합니다. 개발 중 메모리 Repository를 사용하다가 실제 DB 구현체로 바꾸더라도 Controller와 Service는 수정되지 않아야 합니다.

## 7. 계약 변경 절차

1. 요청·응답 예시와 변경 이유를 먼저 공유합니다.
2. 영향을 받는 팀이 필드 이름, 필수 여부, 오류 방식을 확인합니다.
3. 호환되는 필드 추가는 `/api/v1`에서 가능합니다.
4. 필드 삭제나 의미 변경은 `/api/v2`로 분리합니다.
5. 계약 문서와 테스트를 같은 PR에서 수정합니다.
6. 작업 브랜치에서 검증한 뒤 팀 main을 거쳐 공통 main에 합칩니다.

## 8. 현재 연동 상태

- Backend의 LLM HTTP 클라이언트와 `/health/llm`은 구현되어 있습니다.
- LLM 작업 브랜치는 legacy API와 정식 `/api/v1` Persona·Review·Chat을 모두 구현했습니다.
- Backend v1 mock 계약 테스트는 통과했으며 PR #17의 `LLM-main` 병합 후 실제 Ollama 통합 테스트가 필요합니다.
- Agent·Document·Review는 `REPOSITORY_MODE=memory|postgres`에 따라 저장소를 선택합니다.
- 인증된 사용자는 본인이 생성한 Agent·Document·Review만 조회할 수 있습니다.
- PostgreSQL은 `003_add_users.sql`과 `004_add_resource_ownership.sql` 적용이 필요합니다.
- 버전 차이와 팀별 수정 항목은 [버전 호환성 안내](./VERSION_COMPATIBILITY.md)를 확인합니다.

## 9. 연동 전 확인 목록

### LLM 팀

- [x] `/api/v1/health`, `/personas`, `/reviews`, `/chat` 구현
- [ ] 계약서와 요청·응답 JSON 일치 확인
- [ ] Ollama와 사용할 모델 연결 확인
- [ ] 잘못된 요청과 Ollama 오류 상태 코드 확인

### DB 팀

- [ ] Repository 인터페이스와 필드 매핑 합의
- [ ] 스키마와 마이그레이션 제공
- [ ] 조회 실패 시 `None` 반환
- [ ] 비밀 정보 환경 변수 처리

### Backend 팀

- [ ] `dependencies.py`에서 실제 구현체 연결
- [ ] `/health`, `/health/llm`, `/docs` 확인
- [ ] 정상·오류·시간 초과 통합 테스트

### Frontend 팀

- [ ] Backend `/docs` 기준으로 호출
- [ ] `error.code`, `error.message` 처리
- [ ] LLM·DB 주소를 직접 사용하지 않는지 확인
