ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS grounding JSONB;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS coverage JSONB;
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS coverage JSONB;

CREATE TABLE IF NOT EXISTS practice_sessions (
    session_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_practice_sessions_owner_created
    ON practice_sessions (owner_id, created_at DESC);

-- A persona summary must never become a generic summary when its persona is deleted.
ALTER TABLE summaries DROP CONSTRAINT IF EXISTS summaries_agent_id_fkey;
ALTER TABLE summaries ADD CONSTRAINT summaries_agent_id_fkey
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE;

-- Rollback: restore the FK to ON DELETE SET NULL only if reverting that policy.
-- ALTER TABLE summaries DROP CONSTRAINT summaries_agent_id_fkey;
-- ALTER TABLE summaries ADD CONSTRAINT summaries_agent_id_fkey
--     FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE SET NULL;
-- Previously cascaded rows require backup restoration.
-- Rollback: deploy the previous application first and retain these additive
-- columns/tables. After exporting new data, an explicit destructive rollback is:
-- DROP TABLE practice_sessions;
-- ALTER TABLE chat_messages DROP COLUMN grounding;
-- ALTER TABLE reviews DROP COLUMN coverage;
-- ALTER TABLE summaries DROP COLUMN coverage;
