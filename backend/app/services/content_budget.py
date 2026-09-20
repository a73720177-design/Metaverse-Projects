"""Conservative output budgets, not a factual accuracy or semantic-topic score."""
import re
from collections.abc import Iterable

from app.models.content_assessment import ContentAssessment


def assess_content(texts: Iterable[str], *, max_output: int = 8) -> ContentAssessment:
    if max_output < 1:
        raise ValueError("max_output must be at least 1")
    # Sentence/line boundaries are independent of file count. Token signatures
    # also collapse repeated paragraphs whose whitespace or punctuation differs.
    accepted: list[set[str]] = []
    seen: set[frozenset[str]] = set()
    effective_chars = 0
    for text in texts:
        for unit in re.split(r"[\n.!?。！？]+", text):
            tokens = re.findall(r"[가-힣A-Za-z0-9]+", unit.lower())
            signature = frozenset(tokens)
            if len(signature) < 3 or sum(map(len, signature)) < 15:
                continue
            if signature in seen:
                continue
            seen.add(signature)
            terms = set(signature)
            # Bound comparison cost on very large documents. Once the budget
            # saturates, extra text cannot change this conservative estimate.
            if any(len(terms & other) / len(terms | other) >= .8 for other in accepted):
                continue
            accepted.append(terms)
            effective_chars += sum(map(len, signature))
            saturation_chars = 2400 if max_output <= 8 else 0
            if len(accepted) >= max_output and effective_chars >= saturation_chars:
                return ContentAssessment(
                    unique_units=len(accepted),
                    effective_chars=effective_chars,
                    output_limit=max_output,
                    saturated=True,
                )
    units = len(accepted)
    if max_output <= 8:
        length_limit = 1 if effective_chars < 100 else 3 if effective_chars < 800 else 5 if effective_chars < 2400 else 8
    else:
        # Each distinct, non-trivial sentence can ground a question. Character
        # volume is useful for summaries but must not collapse ten concise
        # slide claims into only three expected questions.
        length_limit = max_output
    return ContentAssessment(unique_units=units, effective_chars=effective_chars,
                             output_limit=min(units, length_limit, max_output))


def document_assessment(document) -> ContentAssessment:
    texts = [s.text for s in document.sections if s.text.strip()]
    return assess_content(texts or [document.full_text])
