CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS document_files (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 과거 document_chunks 구조를 새 계약에 맞추되 기존 데이터는 보존합니다.
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'document_chunks'
          AND column_name = 'chunk_text'
    ) THEN
        EXECUTE 'UPDATE document_chunks SET content = COALESCE(content, chunk_text, '''')';
        EXECUTE 'ALTER TABLE document_chunks ALTER COLUMN chunk_text DROP NOT NULL';
    ELSE
        UPDATE document_chunks SET content = '' WHERE content IS NULL;
    END IF;
END $$;

ALTER TABLE document_chunks ALTER COLUMN content SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_document_chunks_index'
          AND conrelid = 'document_chunks'::regclass
    ) THEN
        ALTER TABLE document_chunks
        ADD CONSTRAINT uq_document_chunks_index UNIQUE (document_id, chunk_index);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id
ON document_chunks(document_id);

-- 기존 documents에 파일 메타데이터 컬럼이 있을 때만 데이터를 이전합니다.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'documents'
          AND column_name = 'bucket'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'documents'
          AND column_name = 'object_key'
    ) THEN
        EXECUTE $migration$
            INSERT INTO document_files (document_id, bucket, object_key, content_type)
            SELECT
                document_id,
                bucket,
                object_key,
                CASE document_type
                    WHEN 'pdf' THEN 'application/pdf'
                    WHEN 'pptx' THEN 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    WHEN 'docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    ELSE 'application/octet-stream'
                END
            FROM documents
            WHERE bucket IS NOT NULL AND object_key IS NOT NULL
            ON CONFLICT (document_id) DO NOTHING
        $migration$;
    END IF;
END $$;

-- 기존 sections JSONB가 있을 때만 청크를 이전합니다.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'documents'
          AND column_name = 'sections'
    ) THEN
        EXECUTE $migration$
            INSERT INTO document_chunks (document_id, chunk_index, content)
            SELECT
                document.document_id,
                (section.value->>'index')::INTEGER,
                section.value->>'text'
            FROM documents AS document
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(document.sections, '[]'::jsonb)
            ) AS section(value)
            WHERE section.value ? 'index'
              AND section.value ? 'text'
            ON CONFLICT (document_id, chunk_index) DO NOTHING
        $migration$;
    END IF;
END $$;

ALTER TABLE documents DROP CONSTRAINT IF EXISTS uq_documents_object;
ALTER TABLE documents DROP COLUMN IF EXISTS bucket;
ALTER TABLE documents DROP COLUMN IF EXISTS object_key;
ALTER TABLE documents DROP COLUMN IF EXISTS sections;
