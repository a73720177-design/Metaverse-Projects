import pytest

from app.review_pipeline import _split_text as split_review
from app.summary_pipeline import _split_text as split_summary


@pytest.mark.parametrize("split", [split_review, split_summary])
@pytest.mark.parametrize("chunk_size", [1, 100, 200])
def test_small_chunk_configuration_advances_and_covers_full_document(split, chunk_size):
    text = "발표 자료의 근거를 검토합니다." * 100
    pieces = split(text, chunk_size, overlap=200)
    assert pieces
    assert len(pieces) <= len(text) // max(1, chunk_size // 2) + 1
    assert all(0 < len(piece) <= chunk_size for piece in pieces)
    assert text.endswith(pieces[-1])
