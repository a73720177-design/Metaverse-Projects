"""채팅 답변이 실제로 첨부 문서 근거에 기반하는지 검증하는 경량 후처리.

LLM을 다시 부르지 않는다(CPU 추론에서는 지연이 두 배가 된다). 대신:
  1) 답변을 문장 단위로 쪼갠 뒤 각 문장과 근거 청크의 lexical 포함률을 계산한다.
  2) 포함률이 애매한 문장만 모아 임베딩 코사인 유사도로 한 번(배치)만 재확인한다.
"""

import logging
import math
import re

from app.config import get_grounding_threshold
from app.models.chat import Grounding
from app.models.document import DocumentParseResponse
from app.services.rag_service import _SMALL_TALK_RE, _TOKEN_RE
from app.services.vector_rag import EmbeddingClient


logger = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MIN_SENTENCE_CHARS = 10
# At/above this lexical containment ratio, a sentence is confidently grounded
# and does not need an embedding call.
_LEXICAL_CONFIDENT_SCORE = 0.6
_MAX_UNSUPPORTED = 10


def _split_sentences(answer: str) -> list[str]:
    candidates = [piece.strip() for piece in _SENTENCE_SPLIT_RE.split(answer) if piece.strip()]
    return [
        sentence
        for sentence in candidates
        if len(sentence) >= _MIN_SENTENCE_CHARS and _SMALL_TALK_RE.fullmatch(sentence) is None
    ]


def _containment(sentence_tokens: set[str], chunk_tokens: set[str]) -> float:
    """What fraction of the sentence's tokens also appear in the chunk."""
    if not sentence_tokens:
        return 0.0
    return len(sentence_tokens & chunk_tokens) / len(sentence_tokens)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class GroundingChecker:
    def __init__(self, client: EmbeddingClient | None = None) -> None:
        self.client = client or EmbeddingClient()

    async def check(self, answer: str, document: DocumentParseResponse) -> Grounding:
        sentences = _split_sentences(answer)
        if not sentences:
            return Grounding(score=1.0, unsupported=[], checked=True)

        chunk_texts = [section.text for section in document.sections if section.text.strip()]
        chunk_token_sets = [set(_TOKEN_RE.findall(text.lower())) for text in chunk_texts]

        lexical_scores = [
            max(
                (
                    _containment(set(_TOKEN_RE.findall(sentence.lower())), chunk_tokens)
                    for chunk_tokens in chunk_token_sets
                ),
                default=0.0,
            )
            for sentence in sentences
        ]

        final_scores = list(lexical_scores)
        ambiguous = [
            index for index, score in enumerate(lexical_scores) if score < _LEXICAL_CONFIDENT_SCORE
        ]
        checked = True
        if ambiguous and chunk_texts:
            try:
                vectors = await self.client.embed(
                    [sentences[index] for index in ambiguous] + chunk_texts
                )
                sentence_vectors = vectors[: len(ambiguous)]
                chunk_vectors = vectors[len(ambiguous):]
                for position, index in enumerate(ambiguous):
                    best_cosine = max(
                        (_cosine(sentence_vectors[position], chunk_vector) for chunk_vector in chunk_vectors),
                        default=0.0,
                    )
                    final_scores[index] = max(final_scores[index], best_cosine)
            except Exception:
                logger.warning(
                    "Grounding embedding check failed; falling back to lexical-only scores",
                    exc_info=True,
                )
                checked = False

        threshold = get_grounding_threshold()
        unsupported = [
            sentences[index] for index, score in enumerate(final_scores) if score < threshold
        ][:_MAX_UNSUPPORTED]
        supported = sum(1 for score in final_scores if score >= threshold)
        overall_score = supported / len(final_scores) if final_scores else 1.0
        return Grounding(score=overall_score, unsupported=unsupported, checked=checked)
