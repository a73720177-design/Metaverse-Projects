CREATE TABLE agent_all_dc (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    owner_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (
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
    UNIQUE (agent_id, source_type, source_id)
);

CREATE INDEX ix_agent_all_dc_agent_id
ON agent_all_dc(agent_id);

CREATE INDEX ix_agent_all_dc_owner_id
ON agent_all_dc(owner_id);

CREATE INDEX ix_agent_all_dc_source_type
ON agent_all_dc(source_type);

CREATE INDEX ix_agent_all_dc_data_gin
ON agent_all_dc USING GIN(data);

