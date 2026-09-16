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
    _get_positive_int,
    get_embedding_dimension,
    get_embedding_model,
    get_embedding_timeout_seconds,
    get_embedding_url,
    get_rag_max_context_chars,
    get_rag_mode,
    get_vector_rag_candidate_k,
    get_vector_rag_final_k,
    get_vector_rag_max_distance,
)
from app.db.database import get_session_factory
from app.integrations.reranker import RerankerClient, reranking_enabled
from app.models.document import DocumentParseResponse, DocumentSection
from app.services.rag_service import (
    DocumentContextSelector, combine_document_contexts, fuse_chunk_rankings,
)


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
    def __init__(
        self, client: EmbeddingClient | None = None,
        selector: DocumentContextSelector | None = None,
        reranker: RerankerClient | None = None,
    ) -> None:
        self.client = client or EmbeddingClient()
        self.selector = selector or DocumentContextSelector()
        self.reranker = reranker

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
        limit: int | None = None,
    ) -> list[VectorSearchHit]:
        if not documents or not query.strip():
            return []
        vector = (await self.client.embed([query]))[0]
        candidate_limit = limit or get_vector_rag_candidate_k()
        max_distance = get_vector_rag_max_distance()
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        WITH ranked AS (
                        SELECT c.document_id, d.filename, c.chunk_index, c.content,
                               c.embedding <=> CAST(:vector AS vector) AS distance,
                               row_number() OVER (
                                   PARTITION BY c.document_id
                                   ORDER BY c.embedding <=> CAST(:vector AS vector), c.chunk_id
                               ) AS document_rank
                        FROM documents d
                        CROSS JOIN LATERAL (
                          SELECT c.* FROM document_chunks c
                          WHERE c.document_id = d.document_id
                            AND c.document_id = ANY(CAST(:ids AS uuid[]))
                            AND c.embedding IS NOT NULL
                            AND c.embedding_model = :model
                            AND c.content_hash =
                              encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
                          ORDER BY c.embedding <=> CAST(:vector AS vector)
                          LIMIT :per_document_limit
                        ) c
                        WHERE d.owner_id = :owner
                          AND d.document_id = ANY(CAST(:ids AS uuid[]))
                        )
                        SELECT document_id, filename, chunk_index, content, distance
                        FROM ranked
                        WHERE distance <= :max_distance
                        ORDER BY document_rank, distance, document_id, chunk_index
                        LIMIT :limit
                        """
                    ),
                    {
                        "owner": owner_id,
                        "ids": [document.document_id for document in documents],
                        "model": self.client.model,
                        "vector": json.dumps(vector),
                        "max_distance": max_distance,
                        "limit": max(candidate_limit, len({item.document_id for item in documents})),
                        "per_document_limit": candidate_limit,
                    },
                )
            ).mappings().all()
        hits = [
            VectorSearchHit(
                document_id=row["document_id"],
                filename=row["filename"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                distance=float(row["distance"]),
            )
            for row in rows
            if float(row["distance"]) <= max_distance
        ]
        # Keep the broader pool until lexical fusion and optional reranking.
        return hits if reranking_enabled() else hits[: get_vector_rag_final_k()]

    async def has_complete_index(
        self, documents: list[DocumentParseResponse], owner_id: UUID
    ) -> bool:
        """Return true only when every non-empty chunk has a current embedding."""
        if not documents:
            return False
        async with get_session_factory()() as session:
            rows = (await session.execute(text("""
                SELECT c.document_id, count(*) AS total,
                       count(*) FILTER (
                         WHERE c.embedding IS NOT NULL
                           AND c.embedding_model = :model
                           AND c.content_hash = encode(sha256(convert_to(c.content, 'UTF8')), 'hex')
                       ) AS indexed
                FROM document_chunks c
                JOIN documents d ON d.document_id = c.document_id
                WHERE d.owner_id = :owner
                  AND c.document_id = ANY(CAST(:ids AS uuid[]))
                  AND btrim(c.content) <> ''
                GROUP BY c.document_id
            """), {
                "owner": owner_id,
                "ids": [document.document_id for document in documents],
                "model": self.client.model,
            })).mappings().all()
        counts = {
            row["document_id"]: (int(row["indexed"]), int(row["total"]))
            for row in rows
        }
        expected = {document.document_id for document in documents if document.full_text.strip()}
        return bool(expected) and all(
            document_id in counts
            and counts[document_id][1] > 0
            and counts[document_id][0] == counts[document_id][1]
            for document_id in expected
        )

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
        grouped: dict[UUID, list[DocumentSection]] = {}
        for hit in hits:
            if hit.document_id not in by_id or not hit.content.strip():
                continue
            grouped.setdefault(hit.document_id, []).append(
                DocumentSection(index=hit.chunk_index, text=hit.content)
            )
        # Refine page-sized vector hits with lexical chunks. This also recovers
        # exact names/numbers missed by embeddings within an otherwise matched file.
        # Fuse rankings without comparing incompatible lexical/distance scores.
        selector = self.selector
        refinement_selector = DocumentContextSelector()
        for document_id, document in by_id.items():
            lexical = selector.select(document, query)
            semantic = grouped.get(document_id, [])
            refined = []
            for section in semantic:
                hit_document = document.model_copy(update={
                    "sections": [section], "full_text": section.text,
                })
                hit_context = refinement_selector.select(hit_document, query)
                refined.extend(
                    hit_context.sections if hit_context else refinement_selector._chunks(hit_document)[:1]
                )
            lexical_sections = lexical.sections if lexical is not None else []
            merged = fuse_chunk_rankings(refined, lexical_sections)
            if merged:
                grouped[document_id] = merged
        selected = [
            by_id[document_id].model_copy(update={"sections": sections})
            for document_id, sections in grouped.items() if sections
        ]
        if reranking_enabled():
            selected = await self._rerank_contexts(selected, query)
        return combine_document_contexts(
            selected, get_rag_max_context_chars()
        )

    async def _rerank_contexts(self, documents, query):
        """Rerank fused chunks, retaining source metadata and document diversity."""
        cap = min(64, _get_positive_int("RAG_RERANK_CANDIDATE_K", 24))
        candidates = []
        seen = set()
        # Round robin prevents the first file from exhausting the candidate pool.
        for position in range(max((len(doc.sections) for doc in documents), default=0)):
            for document in documents:
                if position >= len(document.sections):
                    continue
                section = document.sections[position]
                key = (document.document_id, section.index, section.text.strip())
                if key not in seen and section.text.strip():
                    candidates.append((document, section))
                    seen.add(key)
                if len(candidates) >= cap:
                    break
            if len(candidates) >= cap:
                break
        if len(candidates) < 2:
            return documents
        try:
            ranking = await (self.reranker or RerankerClient()).rank(
                query[:4000], [section.text[:8000] for _, section in candidates],
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            logger.warning("Reranking unavailable; using fused retrieval results")
            return documents
        final_k = get_vector_rag_final_k()
        chosen, document_ids = [], set()
        for index in ranking:
            document_id = candidates[index][0].document_id
            if document_id not in document_ids:
                chosen.append(index)
                document_ids.add(document_id)
            if len(chosen) == final_k:
                break
        for index in ranking:
            if len(chosen) >= final_k:
                break
            if index not in chosen:
                chosen.append(index)
        chosen_set = set(chosen)
        grouped = {}
        for index in ranking:
            if index in chosen_set:
                document, section = candidates[index]
                grouped.setdefault(document.document_id, (document, []))[1].append(section)
        return [document.model_copy(update={"sections": sections})
                for document, sections in grouped.values()]


async def index_after_save(document_id: UUID, owner_id: UUID) -> None:
    if not vector_enabled():
        return
    try:
        await VectorRag().index_document(document_id, owner_id)
    except Exception:
        logger.warning(
            "Embedding indexing failed for document %s; lexical RAG remains available",
            document_id,
        )
