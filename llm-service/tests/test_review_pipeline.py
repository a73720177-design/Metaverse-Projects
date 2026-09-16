"""review_pipeline.py의 청킹/패킹/map-reduce 오케스트레이션 단위 테스트.

Ollama는 부르지 않는다. generate_review_map_reduce에는 가짜 generate
콜백을 주입해서, map/reduce 호출 횟수와 sources[].page가 원본 section
index를 그대로 따르는지 검증한다.
"""

import re

from app.review_pipeline import (
    ReviewChunk,
    _build_chunks,
    _evenly_sample,
    _greedy_pack,
    _pack_chunks,
    _split_text,
    generate_review_map_reduce,
    should_use_map_reduce,
)
from app.schemas_v1 import (
    ClaimAssessment,
    DocumentIn,
    PersonaProfileIn,
    ReviewFeedback,
    ReviewGenerationResponse,
    ReviewSource,
)


def _persona() -> PersonaProfileIn:
    return PersonaProfileIn(agent_id="11111111-1111-1111-1111-111111111111", name="홍길동 교수")


def test_should_use_map_reduce_respects_threshold(monkeypatch):
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "100")
    assert should_use_map_reduce("가" * 101) is True
    assert should_use_map_reduce("가" * 100) is False


def test_split_text_returns_single_piece_when_short():
    assert _split_text("본문", chunk_size=100, overlap=10) == ["본문"]
    assert _split_text("", chunk_size=100, overlap=10) == []


def test_split_text_produces_overlapping_windows_covering_the_end():
    text = "가" * 100
    pieces = _split_text(text, chunk_size=40, overlap=10)
    assert pieces == [text[0:40], text[30:70], text[60:100]]


def test_build_chunks_tags_pieces_with_source_section_index():
    document = DocumentIn(
        document_id="22222222-2222-2222-2222-222222222222",
        filename="doc.pdf",
        document_type="pdf",
        sections=[
            {"index": 1, "text": "가" * 50},
            {"index": 2, "text": "나" * 120},
        ],
        full_text="가" * 50 + "나" * 120,
    )
    chunks = _build_chunks(document)
    assert all(c.section_index == 1 for c in chunks if c.text.startswith("가"))
    assert all(c.section_index == 2 for c in chunks if c.text.startswith("나"))
    # 두 번째 섹션(120자)은 기본 chunk_size(3000)보다 짧으니 한 조각으로 남는다.
    assert sum(1 for c in chunks if c.section_index == 2) == 1


def test_build_chunks_without_sections_uses_full_text_with_no_section_index():
    document = DocumentIn(
        document_id="22222222-2222-2222-2222-222222222222",
        filename="doc.pdf",
        document_type="pdf",
        sections=[],
        full_text="가" * 50,
    )
    chunks = _build_chunks(document)
    assert len(chunks) == 1
    assert chunks[0].section_index is None
    assert chunks[0].text == "가" * 50


def test_greedy_pack_splits_when_group_exceeds_map_chars():
    chunks = [ReviewChunk(section_index=i, text="가" * 10) for i in range(1, 4)]
    groups = _greedy_pack(chunks, map_chars=15)
    assert [len(g) for g in groups] == [1, 1, 1]


def test_evenly_sample_always_keeps_first_and_last():
    items = list(range(10))
    sampled = _evenly_sample(items, 3)
    assert sampled[0] == 0
    assert sampled[-1] == 9
    assert len(sampled) == 3


def test_pack_chunks_truncates_and_reports_it(monkeypatch):
    monkeypatch.setenv("REVIEW_MAP_CHARS", "10")
    monkeypatch.setenv("REVIEW_MAX_MAP_CALLS", "3")
    chunks = [ReviewChunk(section_index=i, text="가" * 10) for i in range(1, 11)]

    groups, truncated = _pack_chunks(chunks)

    assert truncated is True
    assert len(groups) == 3
    assert groups[0][0].section_index == 1
    assert groups[-1][0].section_index == 10


def test_pack_chunks_not_truncated_when_within_limit(monkeypatch):
    monkeypatch.setenv("REVIEW_MAP_CHARS", "100")
    monkeypatch.setenv("REVIEW_MAX_MAP_CALLS", "6")
    chunks = [ReviewChunk(section_index=1, text="가" * 10) for _ in range(3)]

    groups, truncated = _pack_chunks(chunks)

    assert truncated is False
    assert len(groups) == 1


def test_generate_review_map_reduce_runs_map_then_reduce(monkeypatch):
    document = DocumentIn(
        document_id="22222222-2222-2222-2222-222222222222",
        filename="doc.pdf",
        document_type="pdf",
        sections=[
            {"index": 1, "text": "가" * 60},
            {"index": 2, "text": "나" * 60},
        ],
        full_text="가" * 60 + "나" * 60,
    )

    calls = []

    def fake_generate(prompt, response_model, max_tokens=None, model=None):
        calls.append((response_model, max_tokens, model))
        if response_model is ReviewGenerationResponse:
            return ReviewGenerationResponse(
                claims=[],
                feedback=ReviewFeedback(positive="p", negative="n"),
                questions=["q1", "q2", "q3"],
            )
        return response_model(claims=[])

    result = generate_review_map_reduce(
        persona=_persona(),
        document=document,
        instructions=None,
        generate=fake_generate,
        model="qwen3:8b",
    )

    assert isinstance(result, ReviewGenerationResponse)
    assert result.coverage is not None
    assert result.coverage.truncated is False
    assert result.coverage.analyzed_chunks == result.coverage.total_chunks
    # 마지막 호출이 reduce여야 한다.
    assert calls[-1][0] is ReviewGenerationResponse
    assert len(calls) >= 2


def test_generate_review_map_reduce_keeps_section_index_as_page(monkeypatch):
    monkeypatch.setenv("REVIEW_CHUNK_CHARS", "1000")
    # 각 섹션이 하나의 청크로 남을 만큼 작으므로(<1000자), map_chars를 극단적으로
    # 작게 둬서 두 섹션이 같은 그룹으로 묶이지 않고 그룹당 1청크씩 나뉘게 한다.
    monkeypatch.setenv("REVIEW_MAP_CHARS", "1")
    monkeypatch.setenv("REVIEW_MAX_MAP_CALLS", "6")

    document = DocumentIn(
        document_id="22222222-2222-2222-2222-222222222222",
        filename="doc.pdf",
        document_type="pdf",
        sections=[
            {"index": 1, "text": "첫 번째 섹션 내용입니다."},
            {"index": 2, "text": "두 번째 섹션 내용입니다."},
        ],
        full_text="첫 번째 섹션 내용입니다.두 번째 섹션 내용입니다.",
    )

    reduce_prompt_holder: dict = {}

    def fake_generate(prompt, response_model, max_tokens=None, model=None):
        if response_model is ReviewGenerationResponse:
            reduce_prompt_holder["prompt"] = prompt
            return ReviewGenerationResponse(
                claims=[],
                feedback=ReviewFeedback(positive="p", negative="n"),
                questions=["q1", "q2", "q3"],
            )
        assert "[구간 " in prompt
        section_index = int(re.search(r"\[구간 (\d+)\]", prompt).group(1))
        return response_model(
            claims=[
                ClaimAssessment(
                    claim="주장",
                    verdict="supported",
                    confidence=0.9,
                    sources=[
                        ReviewSource(filename="doc.pdf", page=section_index, excerpt=document.sections[section_index - 1].text)
                    ],
                )
            ]
        )

    generate_review_map_reduce(
        persona=_persona(),
        document=document,
        instructions=None,
        generate=fake_generate,
        model="qwen3:8b",
    )

    claims_json = reduce_prompt_holder["prompt"]
    assert '"page": 1' in claims_json
    assert '"page": 2' in claims_json


def test_map_citations_are_checked_before_reduce():
    from app.review_pipeline import _verify_map_claims, ReviewChunk
    from app.schemas_v1 import ClaimAssessment
    def claim(page, excerpt):
        return ClaimAssessment(claim="실험 결과", verdict="supported", confidence=.9,
                               sources=[{"filename": "발표.pdf", "page": page, "excerpt": excerpt}])
    claims = [claim(1, "성능이 개선되었습니다."), claim(2, "성능이 개선되었습니다."), claim(1, "매출 증가")]
    result = list(_verify_map_claims(claims, [ReviewChunk(1, "성능이 개선되었습니다.")], "발표.pdf"))
    assert len(result) == 1
    assert result[0].sources[0].page == 1
