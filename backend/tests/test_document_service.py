from pathlib import Path

import pytest

from app.services import document_service


def test_parse_document_preserves_source_page_numbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "slides.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setitem(
        document_service.PARSERS,
        ".pdf",
        lambda _: [(1, "first page"), (2, ""), (3, "third page")],
    )

    document = document_service.parse_document(source, "slides.pdf")

    assert [section.index for section in document.sections] == [1, 3]
    assert document.full_text == "first page\n\nthird page"


def test_parse_document_rejects_files_without_extractable_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setitem(document_service.PARSERS, ".pdf", lambda _: [(1, "")])

    with pytest.raises(ValueError, match="OCR"):
        document_service.parse_document(source, "scan.pdf")


def test_parse_document_normalizes_corrupt_file_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"placeholder")

    def broken_parser(_: Path) -> list[tuple[int, str]]:
        raise RuntimeError("parser internals")

    monkeypatch.setitem(document_service.PARSERS, ".pdf", broken_parser)

    with pytest.raises(ValueError, match="손상"):
        document_service.parse_document(source, "broken.pdf")
