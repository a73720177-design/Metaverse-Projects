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


def test_map_reduce_does_not_expand_repeated_points(monkeypatch):
    from app.summary_pipeline import generate_summary_map_reduce, _MapResult
    from app.schemas_v1 import DocumentIn, SummaryStyle, SummaryGenerationResponse
    monkeypatch.setenv('SUMMARY_CHUNK_CHARS', '100')
    prompts = []
    def generate(prompt, response_model, **kwargs):
        prompts.append(prompt)
        if response_model is _MapResult:
            return _MapResult(points=[{'point': '사용자 실험 결과를 검증했습니다.', 'source_index': 1}])
        return SummaryGenerationResponse(summary='요약', key_topics=[
            {'topic': str(i), 'description': '설명'} for i in range(8)])
    result = generate_summary_map_reduce(document=DocumentIn(
        document_id='22222222-2222-2222-2222-222222222222', document_type='pdf', filename='자료.pdf', full_text='사용자 실험 결과를 검증했습니다.' * 100),
        style=SummaryStyle.BRIEF, persona=None, generate=generate, model=None, topic_limit=5)
    assert len(result.key_topics) == 1
    assert '최대 1개' in prompts[-1]
