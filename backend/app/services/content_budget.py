"""Conservative output budgets, not a factual accuracy or semantic-topic score."""
import re
from collections.abc import Iterable

from app.models.content_assessment import ContentAssessment


def assess_content(texts: Iterable[str]) -> ContentAssessment:
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
            if len(accepted) >= 8 and effective_chars >= 2400:
                return ContentAssessment(unique_units=len(accepted), effective_chars=effective_chars, output_limit=8, saturated=True)
    units = len(accepted)
    length_limit = 1 if effective_chars < 100 else 3 if effective_chars < 800 else 5 if effective_chars < 2400 else 8
    return ContentAssessment(unique_units=units, effective_chars=effective_chars,
                             output_limit=min(units, length_limit))


def document_assessment(document) -> ContentAssessment:
    texts = [s.text for s in document.sections if s.text.strip()]
    return assess_content(texts or [document.full_text])
