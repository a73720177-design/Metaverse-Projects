
import hashlib
import json
from bisect import bisect_right
import logging
import re
import math
from collections import Counter
from collections import OrderedDict
from uuid import UUID

from app.config import get_rag_max_context_chars
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.review import ReviewSource


logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?。！？])\s+|(?<=[!?。！？])(?=[0-9A-Za-z가-힣])|\n+"
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


_FOLLOW_UP_RE = re.compile(
    r"^(?:그(?:건|것|거|게|걸|러면|렇다면|래서)|이(?:것|건|거)|저것|"
    r"그\s|이\s|좀\s*더|더\s*(?:자세|설명)|왜(?:요|죠)?[?？.!\s]*$|"
    r"예시|예를\s*들|다시\s*설명|계속|이어서|what about|why[?!.\s]*$|"
    r"tell me more|explain (?:that|it))", re.IGNORECASE,
)


def build_retrieval_query(message: str, previous_message: str | None = None) -> str:
    """Carry the previous topic only for an explicit referential follow-up."""
    if previous_message and _FOLLOW_UP_RE.search(message.strip()):
        return f"{previous_message} {message}"
    return message


# llm-service/app/prompts.py의 CHUNK_LABEL_TEMPLATE과 반드시 같은 형식이어야
# 한다. 두 서비스는 분리되어 있어 import로 공유할 수 없으므로 문자열을 양쪽에
# 두고, 계약 테스트(backend/tests/test_llm_v1_contract.py,
# llm-service/tests/test_prompts.py)로 drift를 막는다. ordinal(1..N)은
# "구간 N"이 문서마다 중복돼 다중 문서 컨텍스트에서 인용 키로 못 쓰기 때문에
# 붙이는 전역 일련번호다.
_CHUNK_LABEL_TEMPLATE = "[근거 {ordinal}] 파일: {filename} / 구간 {index}"


def _chunk_header(ordinal: int, filename: str, index: int) -> str:
    return _CHUNK_LABEL_TEMPLATE.format(ordinal=ordinal, filename=filename, index=index) + "\n"


def combine_document_contexts(
    documents: list[DocumentParseResponse], max_context_chars: int
) -> DocumentParseResponse | None:
    """파일별로 분량을 나누고 짧은 파일의 남는 분량은 다른 파일에 배분합니다."""
    groups = []
    for document in documents:
        chunks = [
            (section, document.filename, section.text.strip())
            for section in document.sections if section.text.strip()
        ]
        if chunks:
            groups.append((document, chunks))
    # ordinal은 최종 조립 순서에서만 정해지지만, 헤더 길이는 budgeting에 먼저
    # 필요하다. ordinal=1을 자리표시자로 써서 근사한다 — 실제 헤더는 아래
    # 조립 루프에서 진짜 ordinal로 다시 계산되므로 여기서는 근사치면 충분하다.
    def _header_len(filename: str, index: int) -> int:
        return len(_chunk_header(1, filename, index))

    # Even a tiny budget must contain a complete source label and some text.
    while groups and (
        sum(_header_len(chunks[0][1], chunks[0][0].index) + 1 for _, chunks in groups)
        + 2 * (len(groups) - 1) > max_context_chars
    ):
        groups.pop()
    if not groups:
        return None

    sizes = [
        sum(_header_len(filename, section.index) + len(text) for section, filename, text in chunks)
        + 2 * (len(chunks) - 1)
        for _, chunks in groups
    ]
    budgets = [_header_len(chunks[0][1], chunks[0][0].index) + 1 for _, chunks in groups]
    remaining = max_context_chars - sum(budgets) - 2 * (len(groups) - 1)
    while remaining > 0:
        active = [i for i, size in enumerate(sizes) if budgets[i] < size]
        if not active:
            break
        share = max(1, remaining // len(active))
        for i in active:
            added = min(share, sizes[i] - budgets[i], remaining)
            budgets[i] += added
            remaining -= added

    sections = []
    blocks = []
    ordinal = 0
    for (document, chunks), budget in zip(groups, budgets):
        used = 0
        for section, filename, text in chunks:
            separator = 2 if used else 0
            header = _chunk_header(ordinal + 1, filename, section.index)
            available = budget - used - separator - len(header)
            if available <= 0:
                break
            content = text[:available]
            blocks.append(header + content)
            sections.append(section.model_copy(update={
                "text": content,
                "source_document_id": document.document_id,
                "source_filename": document.filename,
                "source_document_type": document.document_type,
            }))
            used += separator + len(header) + len(content)
            ordinal += 1
    first = groups[0][0]
    return first.model_copy(update={
        "filename": "통합 참고 자료" if len(groups) > 1 else first.filename,
        "document_type": "collection" if len(groups) > 1 else first.document_type,
        "sections": sections,
        "full_text": "\n\n".join(blocks),
    })


# --- 인용 마커 기반 sources 필터 (Phase 8) ----------------------------------
# CITATION_RULE(llm-service/app/prompts.py)이 모델에게 답변 문장 끝에
# "[근거 N]"을 붙이도록 지시한다. combine_document_contexts()가 부여한
# ordinal은 document.sections를 순회하며 매긴 것과 같은 순서이므로,
# ordinal N은 항상 document.sections[N-1]을 가리킨다 — 이 정렬이 깨지면
# 마커가 엉뚱한 sources를 가리키게 된다.
_CITATION_MARKER_RE = re.compile(r"\[근거\s*(\d+)\]")


def strip_citation_markers(answer: str) -> str:
    """grounding 채점용 사본에서만 인라인 [근거 N] 마커를 제거한다.

    마커의 "근거"/숫자 토큰은 청크 본문에 존재하지 않아 lexical containment
    점수를 부당하게 낮춘다. 사용자에게 보여주고 저장하는 answer 자체는
    건드리지 않는다.
    """
    return _CITATION_MARKER_RE.sub("", answer).strip()


def _cited_indices(answer: str, section_count: int) -> list[int]:
    """답변에 등장한 순서대로, 유효 범위 안의 0-based section 인덱스만 뽑는다."""
    seen: list[int] = []
    for match in _CITATION_MARKER_RE.finditer(answer):
        index = int(match.group(1)) - 1
        if 0 <= index < section_count and index not in seen:
            seen.append(index)
    return seen


def clean_answer_citations(answer: str, section_count: int) -> str:
    """모델이 지어낸, 범위를 벗어난 [근거 N] 마커만 답변 본문에서 지운다.

    존재하지 않는 sources[N-1]을 가리키는 죽은 참조를 사용자에게 보여주지
    않기 위함이다. 유효한 마커는 그대로 둔다.
    """
    def _replace(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return match.group(0) if 0 <= index < section_count else ""

    return _CITATION_MARKER_RE.sub(_replace, answer)


def sources_from_citations(
    answer: str, document: DocumentParseResponse | None
) -> list[ReviewSource]:
    """답변이 실제로 인용한 [근거 N] 청크만 sources로 좁힌다.

    마커가 하나도 없거나(모델이 안 붙인 경우) 전부 범위 밖이면, sources가
    통째로 비어버리는 것보다는 과다 노출이 낫다고 보고 검색된 섹션 전부로
    폴백한다.
    """
    if document is None:
        return []
    sections = document.sections
    cited = _cited_indices(answer, len(sections))
    if not cited and sections:
        logger.info(
            "No valid [근거 N] citation markers in chat answer; "
            "falling back to all %d retrieved sources",
            len(sections),
        )
    indices = cited if cited else range(len(sections))
    return [
        ReviewSource(
            document_id=sections[i].source_document_id or document.document_id,
            filename=sections[i].source_filename or document.filename,
            page=(
                sections[i].index
                if (sections[i].source_document_type or document.document_type)
                in {"pdf", "pptx"}
                else None
            ),
            excerpt=sections[i].text[:500],
        )
        for i in indices
    ]


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
        payload = {"full_text": document.full_text,
                   "sections": [section.model_dump(mode="json") for section in document.sections]}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _split(self, document: DocumentParseResponse) -> list[DocumentSection]:
        chunks: list[DocumentSection] = []
        source = document.sections or [DocumentSection(index=1, text=document.full_text)]
        for section in source:
            text = section.text.strip()
            if not text:
                continue
            # Slice the original text: table rows, paragraphs and decimal values
            # must survive retrieval. Prefer sentence/line endings within the cap.
            boundaries = [match.end() for match in _SENTENCE_BOUNDARY_RE.finditer(text)]
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                if end < len(text):
                    boundary_index = bisect_right(boundaries, end) - 1
                    if boundary_index >= 0 and boundaries[boundary_index] > start + self.overlap:
                        end = boundaries[boundary_index]
                content = text[start:end].strip()
                if content:
                    chunks.append(section.model_copy(update={"text": content}))
                if end == len(text):
                    break
                # Keep overlap even for a single long sentence, while ensuring
                # forward progress when overlap is close to the chunk size.
                next_start = max(start + 1, end - self.overlap)
                boundary_index = bisect_right(boundaries, next_start - 1)
                if boundary_index < len(boundaries) and boundaries[boundary_index] < end:
                    next_start = boundaries[boundary_index]
                start = next_start
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
