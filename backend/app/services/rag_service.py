import re
from collections import Counter

from app.models.document import DocumentParseResponse, DocumentSection


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
MAX_CONTEXT_CHARS = 4000
MAX_SECTIONS = 5


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def _score_section(query_terms: Counter[str], section: DocumentSection) -> tuple[int, int]:
    section_terms = Counter(_tokens(section.text))
    overlap = sum(min(count, section_terms[term]) for term, count in query_terms.items())
    return overlap, -section.index


class RagService:
    """Select a small document context for chat instead of sending the whole file."""

    def build_context(
        self,
        document: DocumentParseResponse,
        query: str,
        max_sections: int = MAX_SECTIONS,
        max_chars: int = MAX_CONTEXT_CHARS,
    ) -> DocumentParseResponse:
        if not document.sections:
            return document.model_copy(update={"full_text": document.full_text[:max_chars]})

        query_terms = Counter(_tokens(query))
        if query_terms:
            ranked_sections = sorted(
                document.sections,
                key=lambda section: _score_section(query_terms, section),
                reverse=True,
            )
            selected = [
                section
                for section in ranked_sections
                if _score_section(query_terms, section)[0] > 0
            ][:max_sections]
        else:
            selected = []

        if not selected:
            selected = document.sections[:max_sections]

        selected = sorted(selected, key=lambda section: section.index)
        trimmed_sections: list[DocumentSection] = []
        used_chars = 0
        for section in selected:
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            text = section.text[:remaining]
            trimmed_sections.append(section.model_copy(update={"text": text}))
            used_chars += len(text)

        context_text = "\n\n".join(
            f"[section {section.index}]\n{section.text}" for section in trimmed_sections
        )
        return document.model_copy(
            update={"sections": trimmed_sections, "full_text": context_text}
        )
