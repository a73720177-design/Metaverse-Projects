-- 임베딩 기반 시맨틱 검색을 위한 pgvector 확장과 청크 임베딩 테이블.
-- document_chunks(섹션 단위, /documents/{id} 응답이 사용)와는 별개 테이블이다.
-- document_chunks의 스키마·의미는 이 migration에서 건드리지 않는다.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_document_embeddings_document_id
    ON document_embeddings (document_id);

CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding_hnsw
    ON document_embeddings USING hnsw (embedding vector_cosine_ops);

-- Rollback:
-- DROP INDEX IF EXISTS ix_document_embeddings_embedding_hnsw;
-- DROP INDEX IF EXISTS ix_document_embeddings_document_id;
-- DROP TABLE IF EXISTS document_embeddings;
-- DROP EXTENSION IF EXISTS vector;
