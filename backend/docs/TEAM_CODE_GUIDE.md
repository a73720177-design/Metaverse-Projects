# 팀별 코드 확인 안내

이 문서는 각 팀이 Backend 저장소에서 확인해야 할 위치만 빠르게 찾기 위한 안내입니다. 다른 팀의 내부 구현을 수정하기보다 계약 문서를 기준으로 의견을 전달합니다.

## Frontend 팀

먼저 볼 위치:

- `app/controllers/`: 브라우저에 공개되는 API 경로와 상태 코드
- `app/models/`: 요청·응답 JSON 필드
- 실행 중인 `http://127.0.0.1:8000/docs`: 실제 Swagger 문서
- README의 `FRONTEND_ORIGINS`: React·Vite·Vanilla JS 개발 서버 연결 방법
- `docs/FRONTEND_INTEGRATION.md`: React + Vite 환경 변수와 API 클라이언트 예시

Frontend는 `services`, `repositories`, `integrations`를 직접 호출하지 않고 HTTP API만 사용합니다.

## Backend 팀

Backend의 기본 3계층은 다음과 같습니다.

```text
Controller → Service → Repository
```

- `app/controllers/`: HTTP 요청을 받고 서비스 호출, HTTP 오류로 변환
- `app/services/`: 페르소나·문서·리뷰·채팅 업무 규칙
- `app/repositories/`: 저장 계약과 현재의 메모리 구현체
- `app/dependencies.py`: 실제 구현체를 조립하는 단일 위치

외부 LLM 호출은 저장 기능이 아니므로 `app/integrations/llm/`에 별도로 둡니다.

## LLM 팀

먼저 볼 위치:

- `docs/LLM_HTTP_CONTRACT.md`: 필수 HTTP 경로와 JSON 예시
- `app/integrations/llm/contracts.py`: Backend 서비스가 요구하는 생성 기능
- `app/integrations/llm/generators.py`: LLM 서비스로 보내는 실제 payload
- `app/integrations/llm/client.py`: 주소, 버전 헤더, 오류 처리
- `app/integrations/llm/legacy_generators.py`: 현재 LLM 팀 API용 임시 호환 어댑터

LLM 팀은 Backend의 Controller나 Repository를 수정할 필요가 없습니다. `/api/v1` 계약을 구현하면 Backend가 HTTP로 호출합니다.

## DB 팀

먼저 볼 위치:

- `app/repositories/agent_repository.py`
- `app/repositories/document_repository.py`
- `app/repositories/review_repository.py`
- `app/models/`: 저장할 Backend 데이터 구조
- `app/dependencies.py`: 메모리 구현체를 실제 DB 구현체로 교체할 위치

각 Repository의 `Protocol`이 계약이고 `InMemory...Repository`는 개발용 예시입니다. DB 팀 구현은 같은 메서드 입력·출력을 유지해야 합니다.

## 공통 변경 규칙

1. Frontend 공개 API 변경은 Controller와 Swagger를 확인합니다.
2. LLM 요청·응답 변경은 `LLM_HTTP_CONTRACT.md`를 먼저 수정합니다.
3. DB 저장 형식 변경은 Repository와 모델 매핑을 먼저 합의합니다.
4. 한 팀의 라이브러리 버전을 다른 팀에 강제로 맞추지 않습니다.
5. 작업 브랜치에서 테스트한 뒤 각 팀 main, 마지막에 공통 main 순서로 합칩니다.
