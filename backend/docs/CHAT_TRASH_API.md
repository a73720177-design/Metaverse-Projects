# 채팅 이력 및 휴지통 API

모든 API는 `Authorization: Bearer <token>` 인증이 필요하며, 로그인 사용자가 소유한
채팅만 조회하거나 변경할 수 있습니다. 현재 채팅 단위는 질문 1개와 LLM 답변 1개입니다.

## API

| Method | Path | 설명 | 성공 상태 |
|---|---|---|---|
| `POST` | `/agents/{agent_id}/chat` | 답변 생성 및 채팅 이력 저장 | `200` |
| `GET` | `/chats` | 삭제되지 않은 채팅 목록 | `200` |
| `DELETE` | `/chats/{message_id}` | 휴지통으로 이동(소프트 삭제) | `200` |
| `GET` | `/trash/chats` | 휴지통 목록 | `200` |
| `POST` | `/trash/chats/{message_id}/restore` | 원래 채팅 목록으로 복원 | `200` |
| `DELETE` | `/trash/chats/{message_id}` | 완전 삭제 | `204` |

채팅 응답에는 기존 `message_id`, `agent_id`, `answer`, `sources`와 함께 다음 필드가
포함됩니다.

- `message`: 사용자의 원래 질문
- `document_id`: 채팅에 사용한 문서 ID 또는 `null`
- `created_at`: 생성 시각
- `deleted_at`: 휴지통 이동 시각. 활성 채팅은 `null`

완전 삭제는 먼저 휴지통으로 이동한 채팅에만 적용됩니다. 다른 사용자의 채팅이거나
요청한 상태에 존재하지 않는 채팅은 리소스 존재 여부를 노출하지 않고 `404`를 반환합니다.

## PostgreSQL 반영

`DB_AUTO_CREATE=true` 환경에서는 Backend 시작 시 `chat_messages` 테이블이 자동 생성됩니다.
운영 환경에서 자동 생성을 끈 경우 `app.db.tables.ChatMessageTable` 정의와 동일한 스키마를
DB 배포 과정에서 먼저 반영해야 합니다.
