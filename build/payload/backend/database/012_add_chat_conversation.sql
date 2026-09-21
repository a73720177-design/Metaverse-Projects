-- Preserve legacy NULL history; new question threads use their own UUID.
-- Always filter history by owner_id AND agent_id AND conversation_id.
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS conversation_id UUID;

CREATE INDEX IF NOT EXISTS ix_chat_messages_conversation_history
    ON chat_messages (owner_id, agent_id, conversation_id, created_at);
