# Frontend API 계약

기준일: 2026-08-22

Base URL은 `VITE_API_BASE_URL`을 사용하며 기본값은 `http://127.0.0.1:8000`입니다.

## 공통 오류

Backend 오류의 기본 형식은 다음과 같습니다.

```json
{
  "error": {
    "code": "http_422",
    "message": "요청을 처리할 수 없습니다."
  }
}
```

Frontend는 `error.message`, `detail`, `message` 순서로 사용자용 오류 문구를 찾습니다.

## 통합 상태

```http
GET /health/services
```

Frontend는 이 응답과 현재 브라우저 실행 상태를 합쳐 Frontend, Backend, DB, LLM 상태를 한 화면에 표시합니다. 15초마다 자동 갱신하며 수동 새로고침도 지원합니다. 상태 응답에는 내부 URL, 비밀번호, 예외 원문을 포함하지 않습니다.

## 페르소나 생성

```http
POST /agents
Content-Type: application/json
```

```json
{
  "name": "근거 중심 평가자",
  "description": "발표의 주장과 실험 근거를 중요하게 평가한다."
}
```

성공 응답의 `agent_id`는 채팅에 필요하므로 저장합니다.

## 문서 업로드

```http
POST /documents/parse
Content-Type: multipart/form-data
```

`FormData`의 `file` 필드에 PPTX, PDF 또는 DOCX 파일 한 개를 전송합니다. 성공 응답의 `document_id`를 저장합니다.

## 채팅

```http
POST /agents/{agent_id}/chat
Content-Type: application/json
```

```json
{
  "message": "이 발표에서 근거가 부족한 부분은 무엇인가요?",
  "document_id": "선택 문서 UUID 또는 null"
}
```

```json
{
  "message_id": "UUID",
  "agent_id": "UUID",
  "answer": "답변 내용",
  "sources": []
}
```

현재 응답은 JSON 단일 응답이며 SSE 스트리밍이 아닙니다. `message`는 1자 이상 5,000자 이하입니다.

## 현재 지원하지 않는 계약

- `/api/auth/login`
- `/api/chat/stream`
- Bearer token 인증
- 전체 대화 배열을 전달하는 멀티턴 Backend 계약

해당 기능을 추가할 때는 Backend 계약과 보안 정책을 먼저 확정한 뒤 Frontend와 함께 변경합니다.
