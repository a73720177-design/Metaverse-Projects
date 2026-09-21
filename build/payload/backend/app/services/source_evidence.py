"""Bounded excerpts and literal source checks; these do not prove factual truth."""
import re

from app.models.document import DocumentSection


def normalized(text: str) -> str:
    return " ".join(text.split())


def select_excerpts(document, budget: int, query: str = ""):
    """Scan every section; mix overview anchors with query-relevant windows.

    Short documents remain intact. Long sections are windowed so relevant text
    near the end of a page can be selected, with original section IDs preserved.
    """
    sections = [s for s in document.sections if s.text.strip()]
    if not sections and document.full_text.strip():
        sections = [DocumentSection(index=1, text=document.full_text)]
    if not sections or budget <= 0:
        return []
    if sum(len(s.text) for s in sections) <= budget:
        return sections
    width = min(600, max(120, budget // 3))
    windows = [(s, s.text[start:start + width]) for s in sections
               for start in range(0, len(s.text), width) if s.text[start:start + width].strip()]
    count = min(len(windows), 8, max(1, budget // 250))
    terms = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", query.lower()))
    ranked = sorted(range(len(windows)), key=lambda i: (
        -sum(term in windows[i][1].lower() for term in terms), i))
    # Reserve overview anchors, then use the remaining slots for relevance.
    if len(sections) > 1:
        anchor_sections = {sections[0].index, sections[len(sections) // 2].index, sections[-1].index}
        anchors = []
        for i, (section, _) in enumerate(windows):
            if section.index in anchor_sections:
                anchors.append(i)
                anchor_sections.remove(section.index)
    else:
        anchors = [0, len(windows) // 2, len(windows) - 1]
    chosen = list(dict.fromkeys(anchors))[:count]
    for i in ranked:
        if len(chosen) >= count:
            break
        if i not in chosen:
            chosen.append(i)
    per_window = budget // len(chosen)
    return [windows[i][0].model_copy(update={"text": windows[i][1][:per_window]})
            for i in sorted(chosen)]


def verified_sources(sources, document):
    """Reject invented files/pages/quotes; only fill IDs from owned documents."""
    result = []
    sections = {s.index: normalized(s.text) for s in document.sections}
    for source in sources:
        if source.filename != document.filename or source.document_id not in (None, document.document_id):
            continue
        quote = normalized(source.excerpt or "")
        candidates = ([sections.get(source.page, "")] if source.page is not None else
                      list(sections.values()) or [normalized(document.full_text)])
        if not quote or not any(quote in text for text in candidates):
            continue
        result.append(source.model_copy(update={"document_id": document.document_id}))
    return result
