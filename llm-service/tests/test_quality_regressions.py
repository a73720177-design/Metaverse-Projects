"""Regression cases for evidence preservation and actual generation paths."""
import math

import pytest

from app import main, prompts
from app.schemas_v1 import (
    ChatGenerationRequest, DocumentIn, PersonaProfileIn,
    ReviewGenerationRequest, SummaryGenerationRequest, SummaryGenerationResponse, SummaryStyle,
)


def persona():
    return PersonaProfileIn(agent_id="11111111-1111-1111-1111-111111111111", name="평가자")


def document(**updates):
    values = dict(document_id="22222222-2222-2222-2222-222222222222",
                  filename="발표.pdf", document_type="pdf", full_text="다른 본문",
                  sections=[{"index": 7, "text": "실험 참가자는 20명이다."}])
    values.update(updates)
    return DocumentIn(**values)


@pytest.mark.parametrize("has_sections", [True, False])
def test_context_budget_counts_rendered_labels_and_wrappers(monkeypatch, has_sections):
    doc = document(sections=[{"index": i, "text": "검증 자료 " * 70} for i in range(1, 7)])
    if not has_sections:
        doc = doc.model_copy(update={"full_text": prompts.retrieved_context_text(doc), "sections": []})
    request = ChatGenerationRequest(persona=persona(), document=doc, message="자료를 요약해줘", max_output_tokens=128)
    empty = request.model_copy(update={"document": doc.model_copy(update={"full_text": "", "sections": []})})
    budget = len(prompts.build_effective_chat_prompt(empty)) + 650
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", str(budget + 128 + 1))
    monkeypatch.setenv("LLM_CONTEXT_SAFETY_TOKENS", "1")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    fitted = main._fit_chat_context(request)
    actual = prompts.build_effective_chat_prompt(fitted)
    assert math.ceil(len(actual)) <= budget
    assert "[근거 1]" in actual
    assert "[근거 6]" not in actual
    assert fitted.document.sections == []
    assert request.document is doc  # Fitting does not mutate the input.


def test_summary_uses_section_text_and_original_index():
    prompt = main._build_summary_prompt(SummaryGenerationRequest(document=document()))
    assert "[구간 7]" in prompt
    assert "실험 참가자는 20명" in prompt
    assert "다른 본문" not in prompt
    assert prompts.OUTPUT_LANGUAGE_RULE in prompt


@pytest.mark.parametrize("operation", ["review", "summary"])
def test_long_sections_use_map_reduce_even_if_full_text_is_short(monkeypatch, operation):
    doc = document(full_text="", sections=[{"index": 1, "text": "가" * 13000}])
    captured = {}
    sentinel = object()
    def pipeline(**kwargs):
        captured.update(kwargs)
        return sentinel
    def unexpected(*args, **kwargs):
        pytest.fail("long section bypassed map-reduce")
    monkeypatch.setattr(main, "_generate", unexpected)
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "12000")
    monkeypatch.setenv("SUMMARY_SINGLE_PASS_CHARS", "12000")
    if operation == "review":
        monkeypatch.setattr(main, "generate_review_map_reduce", pipeline)
        result = main.generate_review(ReviewGenerationRequest(persona=persona(), document=doc))
    else:
        monkeypatch.setattr(main, "generate_summary_map_reduce", pipeline)
        result = main.generate_summary(SummaryGenerationRequest(document=doc))
    assert result is sentinel
    assert captured["document"] == doc


def test_no_chunks_fit_is_explicitly_missing_evidence():
    assert prompts.render_retrieved_context(document(sections=[{"index": 1, "text": "가" * 5000}])) == "(검색된 근거 없음)"


def test_summary_sampling_discloses_limited_coverage_to_model(monkeypatch):
    from app.summary_pipeline import generate_summary_map_reduce
    monkeypatch.setenv("SUMMARY_CHUNK_CHARS", "100")
    monkeypatch.setenv("SUMMARY_MAP_CHARS", "100")
    monkeypatch.setenv("SUMMARY_MAX_MAP_CALLS", "1")
    captured = []
    def generate(prompt, response_model, **kwargs):
        captured.append(prompt)
        if response_model is SummaryGenerationResponse:
            return response_model(summary="표본 요약")
        return response_model(points=[])
    result = generate_summary_map_reduce(document=document(sections=[], full_text="가" * 500),
        style=SummaryStyle.BRIEF,
        persona=None, generate=generate, model=None)
    assert result.coverage.truncated
    assert "일부 구간만 표본 분석" in captured[-1]
    assert prompts.UNTRUSTED_INPUT_RULE in captured[0]


def test_review_threshold_cannot_bypass_renderer_limit(monkeypatch):
    from app.review_pipeline import should_use_map_reduce
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "100000")
    assert should_use_map_reduce("가" * (prompts.FULL_TEXT_MAX_CHARS + 1))
