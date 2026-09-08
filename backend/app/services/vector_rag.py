"""DB 팀의 pgvector 스키마를 선택적으로 사용하는 Backend 검색 어댑터."""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import text

from app.config import (
    get_embedding_dimension,
    get_embedding_model,
    get_embedding_timeout_seconds,
    get_embedding_url,
    get_rag_max_context_chars,
    get_rag_mode,
)
from app.db.database import get_session_factory
from app.models.document import DocumentParseResponse, DocumentSection


logger = logging.getLogger(__name__)


def vector_enabled() -> bool:
    return get_rag_mode() == "vector"


@dataclass(frozen=True)
class VectorSearchHit:
    document_id: UUID
    filename: str
    chunk_index: int
    content: str
    distance: float


class EmbeddingClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.model = get_embedding_model()
        self.url = get_embedding_url()
        self.dimension = get_embedding_dimension()
        self.timeout_seconds = get_embedding_timeout_seconds()
        self.transport = transport

    async def embed(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(2, self.timeout_seconds))
        async with httpx.AsyncClient(transport=self.transport, timeout=timeout) as client:
            response = await client.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": inputs, "truncate": True},
            )
            response.raise_for_status()
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(inputs):
            raise ValueError("Embedding count mismatch")
        for vector in vectors:
            if (
                not isinstance(vector, list)
                or len(vector) != self.dimension
                or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in vector
                )
                or not any(vector)
            ):
                raise ValueError(
                    f"Expected a finite, nonzero {self.dimension}-dimensional vector"
                )
        return vectors


class VectorRag:
    def __init__(self, client: EmbeddingClient | None = None) -> None:
        self.client = client or EmbeddingClient()

    async def index_document(self, document_id: UUID, owner_id: UUID) -> int:
        """현재 내용과 모델에 맞지 않는 청크만 다시 임베딩합니다."""
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.chunk_id, c.content
                        FROM document_chunks c
                        JOIN documents d ON d.document_id = c.document_id
                        WHERE d.owner_id = :owner
                          AND d.document_id = :document
                          AND btrim(c.content) <> ''
                          AND (
                            c.embedding IS NULL
                            OR c.embedding_model IS DISTINCT FROM :model
                            OR c.content_hash IS DISTINCT FROM
                              encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
                          )
                        ORDER BY c.chunk_index
                        """
                    ),
                    {"owner": owner_id, "document": document_id, "model": self.client.model},
                )
            ).mappings().all()

        updated = 0
        for start in range(0, len(rows), 8):
            batch = rows[start : start + 8]
            vectors = await self.client.embed([row["content"] for row in batch])
            async with get_session_factory()() as session:
                for row, vector in zip(batch, vectors):
                    result = await session.execute(
                        text(
                            """
                            UPDATE document_chunks c
                            SET embedding = CAST(:vector AS vector),
                                embedding_model = :model,
                                embedded_at = now(),
                                content_hash = :hash
                            FROM documents d
                            WHERE c.chunk_id = :chunk
                              AND c.content = :content
                              AND c.document_id = d.document_id
                              AND d.owner_id = :owner
                            """
                        ),
                        {
                            "vector": json.dumps(vector),
                            "model": self.client.model,
                            "hash": hashlib.sha256(row["content"].encode()).hexdigest(),
                            "chunk": row["chunk_id"],
                            "content": row["content"],
                            "owner": owner_id,
                        },
                    )
                    updated += result.rowcount
                await session.commit()
        return updated

    async def search_hits(
        self,
        documents: list[DocumentParseResponse],
        query: str,
        owner_id: UUID,
        *,
        limit: int = 12,
    ) -> list[VectorSearchHit]:
        if not documents or not query.strip():
            return []
        vector = (await self.client.embed([query]))[0]
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.document_id, d.filename, c.chunk_index, c.content,
                               c.embedding <=> CAST(:vector AS vector) AS distance
                        FROM document_chunks c
                        JOIN documents d ON d.document_id = c.document_id
                        WHERE d.owner_id = :owner
                          AND c.document_id = ANY(CAST(:ids AS uuid[]))
                          AND c.embedding IS NOT NULL
                          AND c.embedding_model = :model
                          AND c.content_hash =
                            encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
                        ORDER BY distance, c.chunk_id
                        LIMIT :limit
                        """
                    ),
                    {
                        "owner": owner_id,
                        "ids": [document.document_id for document in documents],
                        "model": self.client.model,
                        "vector": json.dumps(vector),
                        "limit": limit,
                    },
                )
            ).mappings().all()
        return [
            VectorSearchHit(
                document_id=row["document_id"],
                filename=row["filename"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                distance=float(row["distance"]),
            )
            for row in rows
        ]

    async def select_context(
        self,
        documents: list[DocumentParseResponse],
        query: str,
        owner_id: UUID,
    ) -> DocumentParseResponse | None:
        """여러 문서의 상위 청크를 출처 정보와 함께 하나의 LLM 문맥으로 구성합니다."""
        hits = await self.search_hits(documents, query, owner_id)
        if not hits:
            return None
        by_id = {document.document_id: document for document in documents}
        sections: list[DocumentSection] = []
        rendered: list[str] = []
        remaining = get_rag_max_context_chars()
        for hit in hits:
            document = by_id.get(hit.document_id)
            if document is None:
                continue
            header = f"[파일: {hit.filename} / 구간 {hit.chunk_index}]\n"
            separator = 2 if rendered else 0
            available = remaining - len(header) - separator
            if available <= 0:
                break
            content = hit.content[:available]
            if not content:
                continue
            rendered.append(header + content)
            sections.append(
                DocumentSection(
                    index=hit.chunk_index,
                    text=content,
                    source_document_id=hit.document_id,
                    source_filename=hit.filename,
                )
            )
            remaining -= len(header) + len(content) + separator
            if remaining <= 0:
                break
        if not sections:
            return None
        first = by_id[sections[0].source_document_id]
        return first.model_copy(
            update={
                "filename": "벡터 검색 통합 자료",
                "document_type": "collection",
                "sections": sections,
                "full_text": "\n\n".join(rendered),
            }
        )


async def index_after_save(document_id: UUID, owner_id: UUID) -> None:
    if not vector_enabled():
        return
    try:
        await VectorRag().index_document(document_id, owner_id)
    except Exception:
        logger.warning(
            "Embedding indexing failed for document %s; lexical RAG remains available",
            document_id,
            exc_info=True,
        )
