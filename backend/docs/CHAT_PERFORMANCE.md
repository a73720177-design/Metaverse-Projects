# 채팅 응답 성능 최적화

## 적용 내용

- 명백한 인사말은 연결 문서의 소유권만 확인하고 LLM 문맥에서는 제외합니다.
- 문서는 700자, 100자 overlap으로 분할하고 질문 용어와 겹치는 최대 3개 청크만 전달합니다.
- 같은 문서의 청크 분할 결과는 최근 32개 문서까지 Backend 메모리에 캐시합니다.
- LLM 요청에서 `sections`를 제외하고 선택된 `full_text`만 보내 중복 토큰을 제거합니다.
- LLM은 채팅 답변 텍스트만 생성하고, 출처는 Backend가 선택 청크로 직접 구성합니다.
- Ollama 모델을 기본 30분간 유지해 반복적인 모델 로딩을 줄입니다.
- 채팅 출력은 최대 160토큰, 기본 답변은 3문장 이내로 제한합니다.
- `OLLAMA_CHAT_MODEL`로 Persona·Review와 다른 소형 채팅 모델을 선택할 수 있습니다.
- 기존 JSON API와 별도로 `POST /agents/{agent_id}/chat/stream` SSE API를 제공합니다.

## 로컬 CPU 실측

환경: Intel Core i7-1260P, Ollama `qwen2.5:7b`, 100% CPU 실행.

| 요청 | 변경 전 | 변경 후 |
|---|---:|---:|
| 문서 문맥 질문 | 약 101.27초 | 약 7.5초 |
| 문서 없는 `안녕` | 약 11초 | 약 6.5초 |
| 스트리밍 `안녕` 첫 토큰 | 전체 응답 후 표시 | 약 2.39초 |
| 스트리밍 `안녕` 완료 | 해당 없음 | 약 4.11초 |

짧은 요청의 약 11초는 저장소나 HTTP가 아니라 CPU 기반 구조화 LLM 생성 시간입니다.
GPU 또는 `OLLAMA_CHAT_MODEL`에 3B급 모델을 적용하면 추가 개선이 가능합니다.

## 제한 사항

현재 검색은 외부 Vector DB가 없는 환경에서도 동작하도록 lexical overlap을 사용합니다.
문서가 많아지거나 의미 기반 검색이 필요하면 동일한 `DocumentContextSelector` 경계에서
Vector DB retriever로 교체합니다. 스트리밍 완료 이벤트에는 저장된 채팅 정보와 출처가
포함되며, 중간 token 이벤트는 화면에 즉시 이어 붙이는 용도로만 사용합니다.

## SSE 이벤트

```plain text
event: token
data: {"token":"안녕"}

event: done
data: {"message_id":"...","answer":"안녕하세요",...}
```

오류가 스트림 시작 후 발생하면 HTTP 상태를 바꿀 수 없으므로 `event: error`로 전달합니다.
