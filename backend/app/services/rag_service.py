
import re
from collections import OrderedDict
from uuid import UUID

from app.models.document import DocumentParseResponse, DocumentSection


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

    def __init__(self, *, chunk_size: int = 700, overlap: int = 100,
                 max_chunks: int = 3, cache_size: int = 32) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.max_chunks = max_chunks
        self.cache_size = cache_size
        self._cache: OrderedDict[UUID, tuple[str, list[DocumentSection]]] = OrderedDict()

    @staticmethod
    def _fingerprint(document: DocumentParseResponse) -> str:
        return f"{len(document.full_text)}:{hash(document.full_text)}"

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
        selected = [chunk for _, chunk in ranked[: self.max_chunks]]
        selected.sort(key=lambda chunk: chunk.index)
        context = "\n\n".join(f"[구간 {chunk.index}]\n{chunk.text}" for chunk in selected)
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
