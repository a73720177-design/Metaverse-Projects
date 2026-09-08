
import hashlib
import re
from collections import OrderedDict
from uuid import UUID

from app.config import get_rag_max_context_chars
from app.models.document import DocumentParseResponse, DocumentSection


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_SMALL_TALK_RE = re.compile(
    r"^(안녕(?:하세요)?|반가워(?:요)?|고마워(?:요)?|감사(?:합니다|해요)?|"
    r"잘가(?:요)?|좋은\s*(아침|오후|저녁)(?:이에요|입니다)?)[!?.\s]*$",
    re.IGNORECASE,
)


def should_use_document(
    message: str, document_id: UUID | None, *, previous_used_document: bool = False
) -> bool:
    """명백한 인사말에는 연결 문서를 넣지 않아 불필요한 토큰화를 피합니다.

    직전 답변이 문서를 사용했다면(previous_used_document), 짧은 후속 질문도
    인사말이 아닌 한 계속 같은 문서 문맥을 사용한다.
    """
    if document_id is None:
        return False
    return _SMALL_TALK_RE.fullmatch(message.strip()) is None


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
        # sha256 (not the builtin hash()) so the fingerprint is stable across
        # processes/restarts, matching vector_rag's content_hash convention.
        return hashlib.sha256(document.full_text.encode("utf-8")).hexdigest()

    def _split(self, document: DocumentParseResponse) -> list[DocumentSection]:
        chunks: list[DocumentSection] = []
        source = document.sections or [DocumentSection(index=1, text=document.full_text)]
        for section in source:
            text = section.text.strip()
            if not text:
                continue
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunks.append(DocumentSection(index=section.index, text=text[start:end]))
                if end == len(text):
                    break
                start = end - self.overlap
        return chunks

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

    def select(self, document: DocumentParseResponse, query: str) -> DocumentParseResponse:
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

    def relevance_score(self, document: DocumentParseResponse, query: str) -> int:
        """Return a cheap cross-document score used for an agent's defaults."""
        query_terms = set(_TOKEN_RE.findall(query.lower()))
        return max(
            (
                len(query_terms & set(_TOKEN_RE.findall(chunk.text.lower())))
                for chunk in self._chunks(document)
            ),
            default=0,
        )
