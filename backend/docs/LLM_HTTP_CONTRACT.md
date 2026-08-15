# LLM HTTP contract v1

## 현재 팀 코드 호환 모드

LLM 팀의 현재 `kunhee-workspace` 코드는 아래 정식 `/api/v1` 계약이 아니라 `/health`, `/extract-concepts`, `/generate-questions`를 제공합니다. 공통 main에서 먼저 연결할 수 있도록 Backend는 다음 임시 모드를 지원합니다.

```env
LLM_CONTRACT_MODE=legacy_questions
```

이 모드에서는 페르소나 입력을 Backend가 저장하고, 리뷰 요청 시 `/extract-concepts`와 `/generate-questions`를 순서대로 호출한 뒤 `ReviewResult`로 변환합니다. 현재 LLM에 chat API가 없으므로 Chat은 `503`을 반환합니다.

LLM 팀이 아래 정식 API를 구현한 후에는 `LLM_CONTRACT_MODE=v1`로 전환합니다. 임시 모드는 기존 팀 코드를 연결하기 위한 어댑터이며 정식 계약을 대체하지 않습니다.

백엔드는 Ollama를 직접 호출하지 않고 LLM 팀의 독립 FastAPI 서비스만 호출합니다.

```text
Backend :8000 -> LLM Service :8001 -> Ollama :11434
```

기본 주소는 `http://localhost:8001/api/v1`이며 모든 요청에
`X-Backend-Contract-Version: 1` 헤더를 보냅니다.

## GET /api/v1/health

응답:

```json
{"status": "ok"}
```

## POST /api/v1/personas

요청:

```json
{
  "name": "홍길동 교수",
  "description": "근거와 비교 실험을 중요하게 평가한다."
}
```

응답은 `PersonaProfile` 중 LLM 생성 필드인 `role`, `expertise`,
`evaluation_style`을 반환합니다. 최종 `agent_id`, `name`, `description`은 백엔드가 확정합니다.

## POST /api/v1/reviews

요청:

```json
{
  "persona": {"agent_id": "uuid", "name": "평가자", "description": "..."},
  "document": {
    "document_id": "uuid",
    "filename": "slides.pptx",
    "document_type": "pptx",
    "sections": [{"index": 1, "text": "..."}],
    "full_text": "..."
  },
  "instructions": "기술 근거를 중점 평가"
}
```

응답:

```json
{
  "claims": [],
  "feedback": {"positive": "...", "negative": "..."},
  "questions": ["..."]
}
```

최종 `review_id`, `agent_id`, `document_id`는 백엔드가 확정합니다.

## POST /api/v1/chat

요청:

```json
{
  "persona": {"agent_id": "uuid", "name": "평가자", "description": "..."},
  "message": "이 주장의 근거가 충분한가요?",
  "document": null
}
```

응답:

```json
{
  "answer": "...",
  "sources": []
}
```

## 오류 규칙

- LLM 서비스 연결 실패: 백엔드가 `503` 반환
- LLM 서비스의 4xx/5xx 또는 JSON 형식 오류: 백엔드가 `503` 반환
- LLM 서비스는 내부 Ollama 오류를 일관된 JSON 오류로 반환해야 합니다.
- 응답 스키마가 바뀌면 기존 v1을 유지하고 `/api/v2`를 새로 추가합니다.
