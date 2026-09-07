"""Optional pgvector retrieval. No schema changes occur at application startup."""
import hashlib
import json
import logging
import math
import os
from uuid import UUID

import httpx
from sqlalchemy import text

from app.db.database import get_session_factory
from app.models.document import DocumentParseResponse, DocumentSection

logger = logging.getLogger(__name__)
DIMENSION = 1024


def enabled() -> bool:
    return os.getenv("RAG_MODE", "lexical").lower() == "vector"


class EmbeddingClient:
    def __init__(self, transport=None):
        self.model = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest")
        self.url = os.getenv("OLLAMA_EMBEDDING_URL", "http://127.0.0.1:11434").rstrip("/")
        self.transport = transport

    async def embed(self, inputs: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            response = await client.post(
                self.url + "/api/embed",
                json={"model": self.model, "input": inputs, "truncate": False},
            )
            response.raise_for_status()
        vectors = response.json()["embeddings"]
        if len(vectors) != len(inputs):
            raise ValueError("Embedding count mismatch")
        for vector in vectors:
            if (len(vector) != DIMENSION or
                    not all(isinstance(v, (float, int)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in vector) or
                    not any(vector)):
                raise ValueError("Expected a finite, nonzero 1024-dimensional vector")
        return vectors


class VectorRag:
    def __init__(self, client=None):
        self.client = client or EmbeddingClient()

    async def index_document(self, document_id: UUID, owner_id: UUID) -> int:
        # Read then close the transaction before the potentially slow model request.
        async with get_session_factory()() as session:
            rows = (await session.execute(text("""
                SELECT c.chunk_id, c.content FROM document_chunks c
                JOIN documents d ON d.document_id=c.document_id
                WHERE d.owner_id=:owner AND d.document_id=:document
                  AND btrim(c.content) <> ''
                  AND (c.embedding IS NULL OR c.embedding_model IS DISTINCT FROM :model
                    OR c.content_hash IS DISTINCT FROM encode(sha256(convert_to(c.content, 'UTF8')), 'hex'))
                ORDER BY c.chunk_index
            """), {"owner": owner_id, "document": document_id,
                   "model": self.client.model})).mappings().all()
        updated = 0
        for start in range(0, len(rows), 8):
            batch = rows[start:start + 8]
            vectors = await self.client.embed([row["content"] for row in batch])
            async with get_session_factory()() as session:
                for row, vector in zip(batch, vectors):
                    result = await session.execute(text("""
                        UPDATE document_chunks c SET embedding=CAST(:vector AS vector),
                            embedding_model=:model, embedded_at=now(), content_hash=:hash
                        FROM documents d
                        WHERE c.chunk_id=:chunk AND c.content=:content
                          AND c.document_id=d.document_id AND d.owner_id=:owner
                    """), {"vector": json.dumps(vector), "model": self.client.model,
                           "hash": hashlib.sha256(row["content"].encode()).hexdigest(),
                           "chunk": row["chunk_id"], "content": row["content"], "owner": owner_id})
                    updated += result.rowcount
                await session.commit()
        return updated

    async def search(self, documents: list[DocumentParseResponse], query: str,
                     owner_id: UUID) -> DocumentParseResponse | None:
        if not documents:
            return None
        vector = (await self.client.embed([query]))[0]
        async with get_session_factory()() as session:
            rows = (await session.execute(text("""
                SELECT c.document_id, c.chunk_index, c.content
                FROM document_chunks c JOIN documents d ON d.document_id=c.document_id
                WHERE d.owner_id=:owner AND c.document_id=ANY(CAST(:ids AS uuid[]))
                  AND c.embedding IS NOT NULL AND c.embedding_model=:model
                  AND c.content_hash=encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
                ORDER BY c.embedding <=> CAST(:vector AS vector), c.chunk_id
                LIMIT 12
            """), {"owner": owner_id, "ids": [d.document_id for d in documents],
                   "model": self.client.model, "vector": json.dumps(vector)})).mappings().all()
        if not rows:
            return None
        # The existing chat API stores one source document per answer.
        selected = next(d for d in documents if d.document_id == rows[0]["document_id"])
        sections, rendered = [], []
        remaining = 4000
        for row in rows:
            if row["document_id"] != selected.document_id:
                continue
            header = f"[구간 {row['chunk_index']}]\n"
            budget = remaining - len(header) - (2 if rendered else 0)
            if budget <= 0:
                break
            content = row["content"][:budget]
            sections.append(DocumentSection(index=row["chunk_index"], text=content))
            rendered.append(header + content)
            remaining = 4000 - len("\n\n".join(rendered))
            if len(sections) == 3:
                break
        return selected.model_copy(update={"sections": sections, "full_text": "\n\n".join(rendered)})


async def index_after_save(document_id: UUID, owner_id: UUID) -> None:
    if not enabled():
        return
    try:
        await VectorRag().index_document(document_id, owner_id)
    except Exception:
        # Upload has committed; retain the document and allow backfill to retry.
        logger.warning("Embedding indexing failed for document %s; using lexical RAG", document_id, exc_info=True)
