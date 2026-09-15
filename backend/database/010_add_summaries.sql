-- 문서 요약(/documents/{id}/summary)을 저장하는 테이블을 추가한다.
-- 같은 (document_id, agent_id, style) 조합은 하나만 저장되어, 재생성 없이
-- 캐시된 요약을 재사용할 수 있다(backend/app/services/summary_service.py).

CREATE TABLE IF NOT EXISTS summaries (
    summary_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(agent_id) ON DELETE SET NULL,
    style TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    outline JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_summaries_document_agent_style UNIQUE (document_id, agent_id, style)
);

CREATE INDEX IF NOT EXISTS ix_summaries_owner_id ON summaries (owner_id);

-- Rollback:
-- DROP TABLE IF EXISTS summaries;
