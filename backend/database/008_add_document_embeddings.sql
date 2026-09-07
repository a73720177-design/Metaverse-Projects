-- Apply explicitly to a PostgreSQL installation that includes pgvector.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024);
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS content_hash TEXT;
CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
ON document_chunks USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;
