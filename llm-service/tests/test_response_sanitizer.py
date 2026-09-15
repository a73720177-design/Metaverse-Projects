import json

import pytest

from app.response_sanitizer import (
    clean_chat_text,
    extract_json_object,
    safe_stream,
    sanitize_payload,
)


def test_structured_output_ignores_reasoning_json_and_preserves_quoted_evidence():
    payload = {
        "feedback": {
            "positive": "<analysis>private</analysis>근거가 명확합니다.",
            "negative": "검증 조건을 추가하세요.",
        },
        "sources": [{"excerpt": "<think> is a model token", "filename": "source.txt"}],
    }
    raw = '<think>{"feedback":{"positive":"private"}}</think>\n```json\n'
    raw += json.dumps(payload, ensure_ascii=False) + '\n```\n설명'

    result = sanitize_payload(extract_json_object(raw, ["feedback"]))

    assert result["feedback"]["positive"] == "근거가 명확합니다."
    assert result["sources"] == payload["sources"]


def test_structured_output_skips_unrelated_object_before_final_result():
    result = extract_json_object(
        '{"debug":true}\n최종 결과: {"role":"평가자", "expertise": []}',
        ["role"],
    )
    assert result["role"] == "평가자"


def test_reasoning_only_json_is_not_used_as_a_final_answer():
    with pytest.raises(json.JSONDecodeError):
        extract_json_object('<think>{"role":"private"}')


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_stream_hides_tags_at_any_chunk_boundary(size):
    raw = '<think>private <analysis>nested</analysis> hidden</think>공개 답변\n끝'
    chunks = [raw[i:i + size] for i in range(0, len(raw), size)]
    assert "".join(safe_stream(chunks)) == "공개 답변\n끝"


def test_stream_unclosed_mid_answer_reasoning_is_dropped():
    chunks = ["공개 답변", "<thi", "nk>private", " still private"]
    assert "".join(safe_stream(chunks)) == "공개 답변"


def test_stream_stops_provider_and_closes_iterator_at_line_cap():
    closed = []

    def provider():
        try:
            yield "\n".join(f"줄 {i}" for i in range(1, 70))
            pytest.fail("provider must not be consumed after the line cap")
        finally:
            closed.append(True)

    output = "".join(safe_stream(provider()))
    assert len(output.splitlines()) == 30
    assert output.endswith("줄 30")
    assert closed == [True]


def test_stream_line_cap_is_independent_of_transport_chunk_size():
    chunks = (f"줄 {i}\n" for i in range(1, 70))
    output = "".join(safe_stream(chunks))
    assert len(output.splitlines()) == 30
    assert output.endswith("줄 30")


def test_final_chat_filters_reasoning_and_repeated_lines():
    raw = "<think>private</think>좋은 점\n수정 제안\n수정 제안\n답변<analysis>unfinished"
    assert clean_chat_text(raw) == "좋은 점\n수정 제안\n답변"
