CREATE TABLE IF NOT EXISTS agent_documents (
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, document_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_documents_document_id
ON agent_documents(document_id);
