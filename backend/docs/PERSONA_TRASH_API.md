# 페르소나 휴지통 API

모든 API는 로그인 사용자가 소유한 페르소나에만 적용됩니다.

| Method | Path | 설명 | 성공 상태 |
|---|---|---|---|
| `GET` | `/agents` | 활성 페르소나 목록 | `200` |
| `DELETE` | `/agents/{agent_id}` | 페르소나를 휴지통으로 이동 | `200` |
| `GET` | `/agents/trash` | 휴지통 페르소나 목록 | `200` |
| `POST` | `/agents/trash/{agent_id}/restore` | 페르소나 복원 | `200` |
| `DELETE` | `/agents/trash/{agent_id}` | 페르소나 완전 삭제 | `204` |

목록 및 상태 변경 응답에는 `created_at`, `updated_at`, `deleted_at`이 포함됩니다.
휴지통에 있는 페르소나는 단건 조회, 새 리뷰 생성, 새 채팅 생성에 사용할 수 없습니다.
복원하면 기존 UUID와 연결 이력을 유지한 채 다시 사용할 수 있습니다.

완전 삭제는 휴지통에 있는 페르소나에만 허용됩니다. PostgreSQL에서는 해당 페르소나에
연결된 채팅과 리뷰도 외래키 cascade 정책에 따라 함께 삭제됩니다.

기존 PostgreSQL을 사용하는 환경에서는 `agents.deleted_at` 컬럼 추가와 `reviews`,
`chat_messages`의 agent 외래키 cascade 변경을 DB 마이그레이션으로 반영해야 합니다.
새 DB에서 `DB_AUTO_CREATE=true`를 사용하면 현재 SQLAlchemy 모델대로 자동 생성됩니다.
