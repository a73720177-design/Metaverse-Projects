from pathlib import Path
from uuid import UUID

import pytest

from app.models.document import DocumentParseResponse, DocumentSection
from app.services.rag_service import (
    DocumentContextSelector, clean_answer_citations, combine_document_contexts,
    should_use_document, sources_from_citations, strip_citation_markers,
)


DOCUMENT_ID = UUID("22222222-2222-2222-2222-222222222222")


def _document() -> DocumentParseResponse:
    sections = [
        DocumentSection(index=1, text="소개와 프로젝트 배경 " * 100),
        DocumentSection(index=2, text="매출 성장률은 25퍼센트이며 고객 수가 증가했다. " * 100),
        DocumentSection(index=3, text="향후 개발 일정과 결론 " * 100),
    ]
    return DocumentParseResponse(
        document_id=DOCUMENT_ID,
        filename="slides.pptx",
        document_type="pptx",
        saved_path=Path("slides.pptx"),
        sections=sections,
        full_text="\n".join(section.text for section in sections),
    )


def test_greeting_does_not_require_document_context() -> None:
    assert should_use_document("안녕", DOCUMENT_ID) is False
    assert should_use_document("안녕하세요!", DOCUMENT_ID) is False
    assert should_use_document("자료의 매출 성장률을 알려줘", DOCUMENT_ID) is True
    assert should_use_document("안녕", None) is False


def test_selector_limits_and_prioritizes_relevant_chunks() -> None:
    selector = DocumentContextSelector(chunk_size=300, overlap=20, max_chunks=2)
    selected = selector.select(_document(), "매출 성장률과 고객 수는?")

    assert len(selected.sections) == 2
    assert all(section.index == 2 for section in selected.sections)
    assert "매출 성장률" in selected.full_text
    assert len(selected.full_text) < len(_document().full_text)


def test_selector_reuses_cached_chunks() -> None:
    selector = DocumentContextSelector()
    document = _document()
    selector.select(document, "프로젝트 배경")
    cached = selector._cache[DOCUMENT_ID][1]
    selector.select(document, "개발 일정")
    assert selector._cache[DOCUMENT_ID][1] is cached


def test_fingerprint_is_stable_across_selector_instances() -> None:
    """A restarted worker (=a brand new selector/cache) must still recognize
    unchanged content as unchanged, so hashing cannot depend on the
    randomized builtin hash() (PYTHONHASHSEED varies per process)."""
    document = _document()
    assert (
        DocumentContextSelector._fingerprint(document)
        == DocumentContextSelector._fingerprint(document)
        == DocumentContextSelector(cache_size=1)._fingerprint(document)
    )

    changed = document.model_copy(update={"full_text": document.full_text + " "})
    assert DocumentContextSelector._fingerprint(changed) != DocumentContextSelector._fingerprint(
        document
    )


def test_selector_returns_no_context_when_query_has_no_match() -> None:
    selector = DocumentContextSelector(chunk_size=300, overlap=20, max_chunks=1)
    selected = selector.select(_document(), "전혀없는검색어")

    assert selected is None


def test_selector_prefers_sentence_boundaries() -> None:
    document = DocumentParseResponse(
        document_id=DOCUMENT_ID,
        filename="script.docx",
        document_type="docx",
        saved_path=Path("script.docx"),
        sections=[DocumentSection(index=1, text="첫 문장입니다. 두 번째 핵심 문장입니다. 세 번째 결론입니다.")],
        full_text="첫 문장입니다. 두 번째 핵심 문장입니다. 세 번째 결론입니다.",
    )
    selector = DocumentContextSelector(chunk_size=24, overlap=5, max_chunks=3)

    chunks = selector._chunks(document)

    assert len(chunks) >= 2
    assert chunks[0].text.endswith(".")
    assert chunks[1].text.endswith(".")


def test_selector_respects_configured_context_character_limit() -> None:
    selector = DocumentContextSelector(
        chunk_size=300,
        overlap=20,
        max_chunks=3,
        max_context_chars=120,
    )
    selected = selector.select(_document(), "매출 성장률")

    assert 0 < len(selected.full_text) <= 120
    assert selected.full_text == "\n\n".join(
        f"[구간 {section.index}]\n{section.text}" for section in selected.sections
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunk_size": 0},
        {"chunk_size": 100, "overlap": 100},
        {"overlap": -1},
        {"max_chunks": 0},
        {"cache_size": 0},
        {"max_context_chars": 0},
    ],
)
def test_selector_rejects_invalid_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        DocumentContextSelector(**kwargs)


def test_combined_context_shares_budget_and_preserves_source_metadata() -> None:
    from uuid import uuid4

    documents = [
        _document().model_copy(update={
            "document_id": uuid4(), "filename": f"file-{i}.pdf", "document_type": "pdf",
            "sections": [DocumentSection(index=7, text=str(i) * 4000)],
        }) for i in range(5)
    ]
    context = combine_document_contexts(documents, 4000)

    assert context is not None
    assert len(context.full_text) <= 4000
    assert {section.source_document_id for section in context.sections} == {
        document.document_id for document in documents
    }
    assert all(len(section.text) > 500 for section in context.sections)
    assert all(section.source_document_type == "pdf" for section in context.sections)
    assert all(section.index == 7 for section in context.sections)


def test_combined_context_reuses_short_document_budget() -> None:
    from uuid import uuid4

    short = _document().model_copy(update={
        "sections": [DocumentSection(index=1, text="short evidence")],
    })
    long = short.model_copy(update={
        "document_id": uuid4(), "filename": "long.pdf",
        "sections": [DocumentSection(index=1, text="long evidence " * 500)],
    })
    context = combine_document_contexts([short, long], 1000)

    assert context is not None
    assert len(context.full_text) == 1000
    assert context.sections[0].text == "short evidence"
    assert len(context.sections[1].text) > 800


def test_combined_context_does_not_emit_header_without_evidence() -> None:
    assert combine_document_contexts([_document()], 10) is None


# --- 인용 마커 기반 sources 필터 (Phase 8) ----------------------------------


def test_sources_from_citations_keeps_only_cited_sections() -> None:
    document = _document()
    answer = "매출은 25퍼센트 증가했습니다 [근거 2]."

    sources = sources_from_citations(answer, document)

    assert len(sources) == 1
    assert sources[0].excerpt.startswith("매출 성장률은")


def test_sources_from_citations_falls_back_to_all_when_no_markers() -> None:
    document = _document()

    sources = sources_from_citations("마커가 없는 답변입니다.", document)

    assert len(sources) == len(document.sections)


def test_sources_from_citations_ignores_out_of_range_ordinal() -> None:
    document = _document()
    # 청크가 3개인데 모델이 [근거 7]을 지어낸 경우: sources에 반영하지 않는다.
    answer = "이 내용은 [근거 7]에 근거합니다."

    sources = sources_from_citations(answer, document)

    assert len(sources) == len(document.sections)  # 유효 마커가 없으니 폴백


def test_sources_from_citations_keeps_valid_and_drops_invalid_ordinal() -> None:
    document = _document()
    answer = "첫 근거는 [근거 1]이고 지어낸 근거는 [근거 99]입니다."

    sources = sources_from_citations(answer, document)

    assert len(sources) == 1
    assert sources[0].excerpt.startswith("소개와")


def test_sources_from_citations_none_document_returns_empty() -> None:
    assert sources_from_citations("[근거 1]", None) == []


def test_strip_citation_markers_removes_all_markers() -> None:
    cleaned = strip_citation_markers("매출이 늘었습니다 [근거 1]. 고객도 늘었습니다 [근거 2].")
    assert "[근거" not in cleaned
    assert "매출이 늘었습니다" in cleaned
    assert "고객도 늘었습니다" in cleaned


def test_clean_answer_citations_drops_only_out_of_range_markers() -> None:
    answer = "유효한 근거는 [근거 1]이고 지어낸 근거는 [근거 99]입니다."

    cleaned = clean_answer_citations(answer, section_count=3)

    assert "[근거 1]" in cleaned
    assert "[근거 99]" not in cleaned
