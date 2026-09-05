CREATE TABLE IF NOT EXISTS agent_all_dc (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CONSTRAINT ck_agent_all_dc_source_type CHECK (
        source_type IN (
            'agent',
            'chat_message',
            'document',
            'document_file',
            'document_chunk',
            'review'
        )
    ),
    source_id UUID NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_created_at TIMESTAMPTZ,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_all_dc_source UNIQUE (agent_id, source_type, source_id)
);

-- 수동 생성 후 migration 이력만 누락된 DB도 소유권 계약을 복구합니다.
ALTER TABLE agent_all_dc
ALTER COLUMN owner_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_agent_all_dc_agent_id
ON agent_all_dc(agent_id);

CREATE INDEX IF NOT EXISTS ix_agent_all_dc_owner_id
ON agent_all_dc(owner_id);

CREATE INDEX IF NOT EXISTS ix_agent_all_dc_source_type
ON agent_all_dc(source_type);

CREATE INDEX IF NOT EXISTS ix_agent_all_dc_data_gin
ON agent_all_dc USING GIN(data);

CREATE OR REPLACE FUNCTION validate_agent_all_dc_source()
RETURNS TRIGGER AS $$
DECLARE
    source_exists BOOLEAN;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM agents
        WHERE agent_id = NEW.agent_id AND owner_id = NEW.owner_id
    ) THEN
        RAISE EXCEPTION 'agent_all_dc agent and owner do not match';
    END IF;

    CASE NEW.source_type
        WHEN 'agent' THEN
            source_exists := NEW.source_id = NEW.agent_id;
        WHEN 'chat_message' THEN
            SELECT EXISTS (
                SELECT 1 FROM chat_messages
                WHERE message_id = NEW.source_id
                  AND agent_id = NEW.agent_id
                  AND owner_id = NEW.owner_id
            ) INTO source_exists;
        WHEN 'review' THEN
            SELECT EXISTS (
                SELECT 1 FROM reviews
                WHERE review_id = NEW.source_id
                  AND agent_id = NEW.agent_id
                  AND owner_id = NEW.owner_id
            ) INTO source_exists;
        WHEN 'document' THEN
            SELECT EXISTS (
                SELECT 1 FROM documents
                WHERE document_id = NEW.source_id AND owner_id = NEW.owner_id
            ) INTO source_exists;
        WHEN 'document_file' THEN
            SELECT EXISTS (
                SELECT 1
                FROM document_files df
                JOIN documents d USING (document_id)
                WHERE df.document_id = NEW.source_id AND d.owner_id = NEW.owner_id
            ) INTO source_exists;
        WHEN 'document_chunk' THEN
            SELECT EXISTS (
                SELECT 1
                FROM document_chunks dc
                JOIN documents d USING (document_id)
                WHERE dc.chunk_id = NEW.source_id AND d.owner_id = NEW.owner_id
            ) INTO source_exists;
        ELSE
            source_exists := FALSE;
    END CASE;

    IF NOT source_exists THEN
        RAISE EXCEPTION 'agent_all_dc source does not exist or is outside owner scope';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_all_dc_validate_source ON agent_all_dc;
CREATE TRIGGER trg_agent_all_dc_validate_source
BEFORE INSERT OR UPDATE OF agent_id, owner_id, source_type, source_id
ON agent_all_dc
FOR EACH ROW EXECUTE FUNCTION validate_agent_all_dc_source();

DROP TRIGGER IF EXISTS trg_agent_all_dc_updated_at ON agent_all_dc;
CREATE TRIGGER trg_agent_all_dc_updated_at
BEFORE UPDATE ON agent_all_dc
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
