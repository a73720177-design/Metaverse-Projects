-- vector_rag.py(app/services/vector_rag.py)가 사용하는 임베딩 컬럼을
-- document_chunks에 추가한다. document_chunks의 기존 컬럼·의미는 바꾸지 않는다.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS embedding vector(1024),
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- Rollback:
-- DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;
-- ALTER TABLE document_chunks
--     DROP COLUMN IF EXISTS content_hash,
--     DROP COLUMN IF EXISTS embedded_at,
--     DROP COLUMN IF EXISTS embedding_model,
--     DROP COLUMN IF EXISTS embedding;
-- DROP EXTENSION IF EXISTS vector;
