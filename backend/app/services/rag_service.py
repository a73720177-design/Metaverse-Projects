
import hashlib
import re
import math
from collections import Counter
from collections import OrderedDict
from uuid import UUID

from app.config import get_rag_max_context_chars
from app.models.document import DocumentParseResponse, DocumentSection


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?。！？])(?:\s+|(?=[0-9A-Za-z가-힣]))|\n+"
)
_LOW_SIGNAL_TERMS = {
    "질문", "답변", "발표", "자료", "문서", "내용", "평가", "관련",
    "해주세요", "설명", "예상", "사용자", "페르소나",
}
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
            units = [unit.strip() for unit in _SENTENCE_BOUNDARY_RE.split(text) if unit.strip()]
            current: list[str] = []
            current_length = 0

            def append_current() -> None:
                nonlocal current, current_length
                if not current:
                    return
                chunk_text = " ".join(current).strip()
                chunks.append(
                    DocumentSection(
                        index=section.index,
                        text=chunk_text,
                        source_document_id=section.source_document_id,
                        source_filename=section.source_filename,
                        source_document_type=section.source_document_type,
                    )
                )
                overlap_units: list[str] = []
                overlap_length = 0
                for unit in reversed(current):
                    added = len(unit) + (1 if overlap_units else 0)
                    if not overlap_units and added > self.overlap:
                        break
                    if overlap_units and overlap_length + added > self.overlap:
                        break
                    overlap_units.insert(0, unit)
                    overlap_length += added
                current = overlap_units
                current_length = overlap_length

            for unit in units:
                if len(unit) > self.chunk_size:
                    append_current()
                    for start in range(0, len(unit), self.chunk_size):
                        part = unit[start : start + self.chunk_size].strip()
                        if part:
                            chunks.append(
                                DocumentSection(
                                    index=section.index,
                                    text=part,
                                    source_document_id=section.source_document_id,
                                    source_filename=section.source_filename,
                                    source_document_type=section.source_document_type,
                                )
                            )
                    current = []
                    current_length = 0
                    continue
                added = len(unit) + (1 if current else 0)
                if current and current_length + added > self.chunk_size:
                    append_current()
                current.append(unit)
                current_length += len(unit) + (1 if len(current) > 1 else 0)
            append_current()
        return chunks

    @staticmethod
    def _features(text: str) -> list[str]:
        raw_words = [word.lower() for word in _TOKEN_RE.findall(text)]
        words = [word for word in raw_words if word not in _LOW_SIGNAL_TERMS]
        if not words:
            words = raw_words
        features = list(words)
        for word in words:
            if re.fullmatch(r"[가-힣]+", word) and len(word) >= 2:
                features.extend(f"ko:{word[index:index + 2]}" for index in range(len(word) - 1))
        return features

    def _ranked_chunks(
        self, document: DocumentParseResponse, query: str
    ) -> list[tuple[float, int, DocumentSection]]:
        chunks = self._chunks(document)
        query_terms = set(self._features(query))
        if not query_terms or not chunks:
            return []
        chunk_terms = [self._features(chunk.text) for chunk in chunks]
        document_frequency = Counter(
            term for terms in chunk_terms for term in set(terms) if term in query_terms
        )
        average_length = sum(len(terms) for terms in chunk_terms) / len(chunk_terms) or 1
        ranked: list[tuple[float, int, DocumentSection]] = []
        for position, (chunk, terms) in enumerate(zip(chunks, chunk_terms)):
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                idf = math.log(1 + (len(chunks) - document_frequency[term] + 0.5) /
                               (document_frequency[term] + 0.5))
                denominator = frequency + 1.2 * (
                    0.25 + 0.75 * len(terms) / average_length
                )
                score += idf * frequency * 2.2 / denominator
            if score > 0:
                ranked.append((score, position, chunk))
        return sorted(ranked, key=lambda item: (item[0], -item[1]), reverse=True)

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

    def select(
        self, document: DocumentParseResponse, query: str
    ) -> DocumentParseResponse | None:
        candidates = self._ranked_chunks(document, query)
        if not candidates:
            return None
        selected: list[DocumentSection] = []
        rendered: list[str] = []
        rendered_length = 0
        for _, _, chunk in candidates:
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
        if not selected:
            return None
        return document.model_copy(update={"sections": selected, "full_text": context})

    def relevance_score(self, document: DocumentParseResponse, query: str) -> float:
        """Return the best BM25-style score for cross-document ranking."""
        ranked = self._ranked_chunks(document, query)
        return ranked[0][0] if ranked else 0.0
