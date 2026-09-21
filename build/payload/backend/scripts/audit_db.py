"""Read-only schema and RAG data audit; never prints document content or credentials."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.config import get_embedding_model
from app.db.database import close_db, get_engine, inspect_db_contract


AUDIT_SQL = """
WITH scoped AS (
    SELECT document_id, owner_id, full_text FROM documents
    WHERE (CAST(:owner AS uuid) IS NULL OR owner_id = CAST(:owner AS uuid))
), chunks AS (
    SELECT c.* FROM document_chunks c JOIN scoped d USING (document_id)
), nonempty AS (
    SELECT * FROM chunks WHERE btrim(content) <> ''
)
SELECT
    (SELECT count(*) FROM scoped) AS documents,
    (SELECT count(*) FROM scoped WHERE owner_id IS NULL) AS unowned_documents,
    (SELECT count(*) FROM scoped WHERE btrim(full_text) = '') AS empty_documents,
    (SELECT count(*) FROM scoped d WHERE NOT EXISTS (
        SELECT 1 FROM document_files f WHERE f.document_id = d.document_id
    )) AS documents_without_file_record,
    (SELECT count(*) FROM scoped d WHERE btrim(full_text) <> '' AND NOT EXISTS (
        SELECT 1 FROM nonempty c WHERE c.document_id = d.document_id
    )) AS text_documents_without_chunks,
    (SELECT count(*) FROM chunks) AS chunks,
    (SELECT count(*) FROM chunks WHERE btrim(content) = '') AS empty_chunks,
    (SELECT count(*) FROM nonempty WHERE embedding IS NULL) AS missing_embeddings,
    (SELECT count(*) FROM nonempty WHERE embedding IS NOT NULL AND (
        embedding_model IS DISTINCT FROM :model OR content_hash IS DISTINCT FROM
        encode(sha256(convert_to(content, 'UTF8')), 'hex')
    )) AS stale_embeddings,
    (SELECT count(*) FROM nonempty WHERE embedding IS NOT NULL
        AND embedding_model = :model
        AND content_hash = encode(sha256(convert_to(content, 'UTF8')), 'hex')
    ) AS current_embeddings,
    (SELECT coalesce(max(length(content)), 0) FROM chunks) AS largest_chunk_chars,
    (SELECT count(*) FROM chunks WHERE length(content) > 4000) AS chunks_over_4000_chars
"""


async def audit(owner_id: UUID | None = None) -> dict:
    try:
        contract = await inspect_db_contract()
        report = {"schema": contract, "scope": str(owner_id) if owner_id else "all"}
        if contract["status"] != "ok":
            return {**report, "status": "mismatch"}
        async with get_engine().begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            counts = dict((await connection.execute(
                text(AUDIT_SQL), {"owner": owner_id, "model": get_embedding_model()}
            )).mappings().one())
        issues = [name for name in (
            "unowned_documents", "empty_documents", "documents_without_file_record",
            "text_documents_without_chunks", "missing_embeddings", "stale_embeddings",
        ) if counts[name]]
        return {**report, "status": "attention" if issues else "ok",
                "counts": counts, "issues": issues,
                "notes": ["4000 characters is a review heuristic, not a token limit.",
                          "File record existence does not verify object storage contents.",
                          "Embedding service availability and answer quality are not tested."]}
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", type=UUID)
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL", "").strip():
        print(json.dumps({"status": "unconfigured", "reason": "DATABASE_URL is not set"}))
        return 2
    try:
        report = asyncio.run(audit(args.owner_id))
    except Exception as exc:
        # Driver exceptions may include connection details or SQL parameters.
        report = {"status": "error", "error_type": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
