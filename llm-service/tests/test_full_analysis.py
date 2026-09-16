import json
import re

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.context_budget import prompt_fits
from app.pipeline_budget import budgeted_groups, reduce_to_fit
from app.review_pipeline import ReviewChunk, generate_review_map_reduce
from app.summary_pipeline import generate_summary_map_reduce
from app.schemas_v1 import DocumentIn, PersonaProfileIn, ReviewGenerationResponse, SummaryGenerationResponse, SummaryStyle


@pytest.mark.parametrize("operation", ["review", "summary"])
@pytest.mark.parametrize("mode", ["fast", "full"])
def test_full_mode_visits_every_source_even_past_fast_limit(monkeypatch, operation, mode):
    prefix = operation.upper()
    monkeypatch.setenv(f"{prefix}_ANALYSIS_MODE", mode)
    monkeypatch.setenv(f"{prefix}_MAX_MAP_CALLS", "2")
    monkeypatch.setenv(f"{prefix}_MAP_CHARS", "1")
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    seen = []
    document = DocumentIn(document_id="22222222-2222-2222-2222-222222222222",
                          filename="자료.pdf", document_type="pdf", full_text="자료",
                          sections=[{"index": index, "text": f"실험 {index}의 근거"} for index in range(1, 10)])
    def generate(prompt, response_model, **kwargs):
        assert prompt_fits(prompt, kwargs["max_tokens"])
        if response_model is ReviewGenerationResponse:
            return response_model(feedback={"positive": "검토", "negative": "한계"})
        if response_model is SummaryGenerationResponse:
            return response_model(summary="요약")
        seen.extend(int(i) for i in re.findall(r"\[구간 (\d+)\]", prompt))
        return response_model(**({"claims": []} if operation == "review" else {"points": []}))
    if operation == "review":
        result = generate_review_map_reduce(document=document, persona=PersonaProfileIn(
            agent_id="11111111-1111-1111-1111-111111111111", name="평가자"),
            instructions=None, generate=generate, model=None)
    else:
        result = generate_summary_map_reduce(document=document, persona=None, style=SummaryStyle.BRIEF,
                                             generate=generate, model=None)
    assert seen == (list(range(1, 10)) if mode == "full" else [1, 9])
    assert result.coverage.truncated == (mode == "fast")
    assert result.coverage.analyzed_chunks == len(seen)
    assert result.coverage.total_chunks == 9


def test_packing_counts_prompt_overhead_and_preserves_every_character(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    source = "앞부분 " * 900 + "중요한 마지막 근거"
    def render(group):
        return "작업 지침" * 300 + "\n".join(c.text for c in group)
    groups = budgeted_groups([ReviewChunk(7, source)], render, 1024, 12000)
    assert len(groups) > 1
    assert all(prompt_fits(render(group), 1024) for group in groups)
    assert "".join(c.text for g in groups for c in g) == source
    assert all(c.section_index == 7 for g in groups for c in g)


class Point(BaseModel):
    text: str
    pages: list[int]


class Points(BaseModel):
    points: list[Point]


def test_hierarchical_reduction_passes_all_pages_to_final_prompt(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    items = [{"text": "근거 " * 150, "pages": [i]} for i in range(30)]
    def render(items):
        return json.dumps(items, ensure_ascii=False)
    calls = []
    def generate(prompt, response_model, **kwargs):
        assert prompt_fits(prompt, kwargs["max_tokens"])
        rows = json.loads(prompt)
        pages = [p for row in rows for p in row["pages"]]
        calls.append(pages)
        return Points(points=[Point(text="압축 근거", pages=pages)])
    reduced = reduce_to_fit(items, final_prompt=render, final_tokens=2048,
                            compact_prompt=render, response_model=Points, field="points",
                            generate=generate, model=None)
    assert len(calls) > 1
    assert sorted(p for row in reduced for p in row["pages"]) == list(range(30))
    assert prompt_fits(render(reduced), 2048)


def test_non_compressing_model_fails_instead_of_dropping_evidence(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    items = [{"text": "근거" * 900, "pages": [1]}]
    def render(items):
        return json.dumps(items, ensure_ascii=False)
    with pytest.raises(HTTPException) as exc:
        reduce_to_fit(items, final_prompt=render, final_tokens=2048,
                      compact_prompt=render, response_model=Points, field="points",
                      generate=lambda prompt, *a, **k: Points(points=json.loads(prompt)), model=None)
    assert exc.value.status_code == 502


def test_full_work_limit_rejects_before_any_generation(monkeypatch):
    monkeypatch.setenv("SUMMARY_ANALYSIS_MODE", "full")
    monkeypatch.setenv("SUMMARY_FULL_MAX_MAP_CALLS", "1")
    monkeypatch.setenv("SUMMARY_MAP_CHARS", "1")
    document = DocumentIn(document_id="22222222-2222-2222-2222-222222222222",
                          filename="자료.pdf", document_type="pdf", full_text="자료",
                          sections=[{"index": i, "text": "근거"} for i in range(1, 4)])
    with pytest.raises(HTTPException) as exc:
        generate_summary_map_reduce(document=document, persona=None, style=SummaryStyle.BRIEF,
            generate=lambda *a, **k: pytest.fail("called model"), model=None)
    assert exc.value.status_code == 422
