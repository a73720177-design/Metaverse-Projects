
import re
from collections import OrderedDict
from typing import Protocol
from uuid import UUID

from app.config import get_rag_max_context_chars, get_retrieval_candidate_multiplier
from app.integrations.llm.contracts import EmbeddingGenerator, EmbeddingGeneratorError
from app.models.document import DocumentParseResponse, DocumentSection
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import DocumentChunk, split_document


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_SMALL_TALK_RE = re.compile(
    r"^(안녕(?:하세요)?|반가워(?:요)?|고마워(?:요)?|감사(?:합니다|해요)?|"
    r"잘가(?:요)?|좋은\s*(아침|오후|저녁)(?:이에요|입니다)?)[!?.\s]*$",
    re.IGNORECASE,
)


def should_use_document(message: str, document_id: UUID | None) -> bool:
    """명백한 인사말에는 연결 문서를 넣지 않아 불필요한 토큰화를 피합니다."""
    return document_id is not None and _SMALL_TALK_RE.fullmatch(message.strip()) is None


class DocumentContextSelector:
    """외부 검색엔진 없이 관련 문서 청크만 고르는 경량 lexical retriever."""

    def __init__(
        self,
        *,
        chunk_size: int = 700,
        overlap: int = 100,
        max_chunks: int = 3,
        cache_size: int = 32,
        max_context_chars: int | None = None,
    ) -> None:
        if max_context_chars is None:
            max_context_chars = get_rag_max_context_chars()
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size - 1.")
        if max_chunks < 1:
            raise ValueError("max_chunks must be at least 1.")
        if cache_size < 1:
            raise ValueError("cache_size must be at least 1.")
        if max_context_chars < 1:
            raise ValueError("max_context_chars must be at least 1.")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.max_chunks = max_chunks
        self.cache_size = cache_size
        self.max_context_chars = max_context_chars
        self._cache: OrderedDict[UUID, tuple[str, list[DocumentSection]]] = OrderedDict()

    @staticmethod
    def _fingerprint(document: DocumentParseResponse) -> str:
        return f"{len(document.full_text)}:{hash(document.full_text)}"

    def _split(self, document: DocumentParseResponse) -> list[DocumentSection]:
        return [
            DocumentSection(index=chunk.section_index, text=chunk.text)
            for chunk in split_document(
                document, chunk_size=self.chunk_size, overlap=self.overlap
            )
        ]

    def _chunks(self, document: DocumentParseResponse) -> list[DocumentSection]:
        fingerprint = self._fingerprint(document)
        cached = self._cache.get(document.document_id)
        if cached is not None and cached[0] == fingerprint:
            self._cache.move_to_end(document.document_id)
            return cached[1]
        chunks = self._split(document)
        self._cache[document.document_id] = (fingerprint, chunks)
        self._cache.move_to_end(document.document_id)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return chunks

    async def select(self, document: DocumentParseResponse, query: str) -> DocumentParseResponse:
        query_terms = set(_TOKEN_RE.findall(query.lower()))
        chunks = self._chunks(document)

        def score(item: tuple[int, DocumentSection]) -> tuple[int, int]:
            position, chunk = item
            terms = set(_TOKEN_RE.findall(chunk.text.lower()))
            return (len(query_terms & terms), -position)

        ranked = sorted(enumerate(chunks), key=score, reverse=True)
        relevant = [item for item in ranked if score(item)[0] > 0]
        candidates = relevant or list(enumerate(chunks))
        selected: list[DocumentSection] = []
        rendered: list[str] = []
        rendered_length = 0
        for _, chunk in candidates:
            block = f"[구간 {chunk.index}]\n{chunk.text}"
            added_length = len(block) + (2 if rendered else 0)
            if rendered_length + added_length > self.max_context_chars:
                remaining = self.max_context_chars - rendered_length - (2 if rendered else 0)
                header = f"[구간 {chunk.index}]\n"
                if remaining > len(header):
                    truncated = chunk.model_copy(
                        update={"text": chunk.text[: remaining - len(header)]}
                    )
                    selected.append(truncated)
                    rendered.append(f"{header}{truncated.text}")
                break
            selected.append(chunk)
            rendered.append(block)
            rendered_length += added_length
            if len(selected) == self.max_chunks:
                break
        selected.sort(key=lambda chunk: chunk.index)
        context = "\n\n".join(
            f"[구간 {chunk.index}]\n{chunk.text}" for chunk in selected
        )
        return document.model_copy(update={"sections": selected, "full_text": context})

    async def relevance_score(self, document: DocumentParseResponse, query: str) -> int:
        """Return a cheap cross-document score used for an agent's defaults."""
        query_terms = set(_TOKEN_RE.findall(query.lower()))
        return max(
            (
                len(query_terms & set(_TOKEN_RE.findall(chunk.text.lower())))
                for chunk in self._chunks(document)
            ),
            default=0,
        )


class ContextSelector(Protocol):
    """Duck-typed interface ChatService relies on, shared by both selectors."""

    max_context_chars: int

    async def select(self, document: DocumentParseResponse, query: str) -> DocumentParseResponse: ...

    async def relevance_score(self, document: DocumentParseResponse, query: str) -> int: ...


class HybridContextSelector:
    """Combines lexical keyword matching with pgvector cosine search via RRF.

    Falls back to plain lexical selection whenever the document has not been
    indexed yet or the embedding call fails, so a broken/slow embedding path
    never breaks chat.
    """

    def __init__(
        self,
        *,
        embedding_generator: EmbeddingGenerator,
        document_repository: DocumentRepository,
        chunk_size: int = 700,
        overlap: int = 100,
        max_chunks: int = 3,
        max_context_chars: int | None = None,
        candidate_multiplier: int | None = None,
        rrf_k: int = 60,
        lexical_selector: DocumentContextSelector | None = None,
    ) -> None:
        if max_context_chars is None:
            max_context_chars = get_rag_max_context_chars()
        if candidate_multiplier is None:
            candidate_multiplier = get_retrieval_candidate_multiplier()
        self.embedding_generator = embedding_generator
        self.document_repository = document_repository
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.max_chunks = max_chunks
        self.max_context_chars = max_context_chars
        self.candidate_multiplier = candidate_multiplier
        self.rrf_k = rrf_k
        self.lexical_selector = lexical_selector or DocumentContextSelector(
            chunk_size=chunk_size,
            overlap=overlap,
            max_chunks=max_chunks,
            max_context_chars=max_context_chars,
        )

    async def _fuse_ranked_chunks(
        self, document: DocumentParseResponse, query: str
    ) -> list[DocumentChunk] | None:
        if not await self.document_repository.has_embeddings(document.document_id):
            return None
        try:
            query_vector = (await self.embedding_generator.embed([query]))[0]
        except EmbeddingGeneratorError:
            return None

        lexical_chunks = split_document(
            document, chunk_size=self.chunk_size, overlap=self.overlap
        )
        limit = self.max_chunks * self.candidate_multiplier
        semantic = await self.document_repository.search_chunks(
            document.document_id, query_vector, limit
        )
        if not semantic:
            return None

        query_terms = set(_TOKEN_RE.findall(query.lower()))
        lexical_ranked = sorted(
            lexical_chunks,
            key=lambda chunk: (
                len(query_terms & set(_TOKEN_RE.findall(chunk.text.lower()))),
                -chunk.chunk_index,
            ),
            reverse=True,
        )
        lexical_rank = {chunk.chunk_index: rank for rank, chunk in enumerate(lexical_ranked, start=1)}
        semantic_rank = {row.chunk_index: rank for rank, row in enumerate(semantic, start=1)}

        by_index: dict[int, DocumentChunk] = {chunk.chunk_index: chunk for chunk in lexical_chunks}
        for row in semantic:
            by_index.setdefault(
                row.chunk_index,
                DocumentChunk(
                    chunk_index=row.chunk_index,
                    section_index=row.section_index,
                    text=row.content,
                ),
            )

        worst_lexical_rank = len(lexical_chunks) + 1

        def fused_score(chunk_index: int) -> float:
            lexical_component = 1 / (self.rrf_k + lexical_rank.get(chunk_index, worst_lexical_rank))
            semantic_component = (
                1 / (self.rrf_k + semantic_rank[chunk_index]) if chunk_index in semantic_rank else 0
            )
            return lexical_component + semantic_component

        top = sorted(
            by_index.values(), key=lambda chunk: fused_score(chunk.chunk_index), reverse=True
        )[: self.max_chunks]
        top.sort(key=lambda chunk: chunk.section_index)
        return top

    def _render(
        self, document: DocumentParseResponse, chunks: list[DocumentChunk]
    ) -> DocumentParseResponse:
        selected: list[DocumentSection] = []
        rendered: list[str] = []
        used = 0
        for chunk in chunks:
            block = f"[구간 {chunk.section_index}]\n{chunk.text}"
            added = len(block) + (2 if rendered else 0)
            if used + added > self.max_context_chars:
                break
            selected.append(DocumentSection(index=chunk.section_index, text=chunk.text))
            rendered.append(block)
            used += added
        return document.model_copy(
            update={"sections": selected, "full_text": "\n\n".join(rendered)}
        )

    async def select(self, document: DocumentParseResponse, query: str) -> DocumentParseResponse:
        fused = await self._fuse_ranked_chunks(document, query)
        if fused is None:
            return await self.lexical_selector.select(document, query)
        return self._render(document, fused)

    async def relevance_score(self, document: DocumentParseResponse, query: str) -> int:
        # Cheap cross-document pre-ranking only picks which documents to embed
        # a query against; keep it lexical so it never triggers embedding calls.
        return await self.lexical_selector.relevance_score(document, query)
