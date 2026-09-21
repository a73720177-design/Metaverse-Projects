-- Substring candidate search works before this migration too. This index helps
-- sufficiently selective patterns with >= 3 characters; two-character Korean
-- terms may still require scanning the owner/document-filtered pages.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm
    ON document_chunks USING gin (lower(content) gin_trgm_ops);
