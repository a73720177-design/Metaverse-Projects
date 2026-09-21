CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE agents
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_agents_deleted_at ON agents(deleted_at);
CREATE INDEX IF NOT EXISTS ix_agents_owner_deleted
ON agents(owner_id, deleted_at);

-- 페르소나 완전 삭제 시 연결된 리뷰도 함께 제거합니다.
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_agent_id_fkey;
ALTER TABLE reviews
ADD CONSTRAINT reviews_agent_id_fkey
FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(document_id) ON DELETE SET NULL,
    message TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_chat_messages_owner_id
ON chat_messages(owner_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_agent_id
ON chat_messages(agent_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_document_id
ON chat_messages(document_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_deleted_at
ON chat_messages(deleted_at);
CREATE INDEX IF NOT EXISTS ix_chat_messages_owner_deleted
ON chat_messages(owner_id, deleted_at);
