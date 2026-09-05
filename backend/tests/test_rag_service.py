from pathlib import Path
from uuid import UUID

from app.models.document import DocumentParseResponse, DocumentSection
from app.services.rag_service import DocumentContextSelector, should_use_document


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


def test_selector_applies_character_limit_even_with_large_chunks() -> None:
    selector = DocumentContextSelector(
        chunk_size=2000,
        overlap=0,
        max_chunks=3,
        max_context_chars=500,
    )
    selected = selector.select(_document(), "매출 성장률")

    assert len(selected.full_text) <= 500


def test_selector_falls_back_to_opening_chunks_when_nothing_matches() -> None:
    selector = DocumentContextSelector(chunk_size=300, overlap=0, max_chunks=2)
    selected = selector.select(_document(), "존재하지 않는 키워드")

    assert len(selected.sections) == 2
    assert all(section.index == 1 for section in selected.sections)


def test_selector_reuses_cached_chunks() -> None:
    selector = DocumentContextSelector()
    document = _document()
    selector.select(document, "프로젝트 배경")
    cached = selector._cache[DOCUMENT_ID][1]
    selector.select(document, "개발 일정")
    assert selector._cache[DOCUMENT_ID][1] is cached
