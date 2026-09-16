import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app import llm_client, main
from app.context_budget import context_length, prompt_fits
from app.schemas_v1 import DocumentIn, PersonaProfileIn, ReviewGenerationRequest, SummaryGenerationRequest


def test_optional_tokenizer_is_loaded_offline_and_overrides_character_estimate(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.context_budget import _local_tokenizer, estimated_tokens
    calls = []
    def load(path, **kwargs):
        calls.append((path, kwargs))
        return SimpleNamespace(encode=lambda text, **kwargs: list(text.encode("utf-8")))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=load)))
    monkeypatch.setenv("LLM_TOKENIZER_PATH", "/local/test-tokenizer")
    _local_tokenizer.cache_clear()
    try:
        assert estimated_tokens("한글") == 6
        assert estimated_tokens("a") == 1
        assert calls == [("/local/test-tokenizer", {"local_files_only": True})]
    finally:
        _local_tokenizer.cache_clear()


def test_question_generation_without_presentation_evidence_never_calls_model(monkeypatch):
    from app.schemas_v1 import ExpectedQuestionGenerationRequest
    request = ExpectedQuestionGenerationRequest(
        persona={"agent_id": "11111111-1111-1111-1111-111111111111", "name": "평가자"},
        evidence=[{"id": "reference", "scope": "persona_reference", "text": "참고 관점"}],
    )
    monkeypatch.setattr(main, "_generate", lambda *a, **k: pytest.fail("no presentation"))
    assert main.generate_expected_questions(request).questions == []


@pytest.mark.parametrize("streaming", [False, True, "async"])
def test_all_ollama_paths_send_the_budgeted_context_length(monkeypatch, streaming):
    from tests.test_llm_client import FakeResponse
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    captured = []
    def post(*args, **kwargs):
        captured.append(kwargs["json"])
        return FakeResponse({"response": "ok"}, lines=['{"response":"ok","done":true}'])
    monkeypatch.setattr(llm_client.requests, "post", post)
    if streaming == "async":
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, text='{"response":"ok","done":true}\n')
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
        async def run():
            return [chunk async for chunk in llm_client.stream_llm_async("질문", max_tokens=512)]
        assert asyncio.run(run()) == ["ok"]
    elif streaming:
        assert list(llm_client.stream_llm("질문", max_tokens=512)) == ["ok"]
    else:
        assert llm_client.call_llm("질문", max_tokens=512) == "ok"
    assert captured[0]["options"]["num_ctx"] == 4096


def test_oversize_request_is_rejected_before_model_call(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: pytest.fail("called model"))
    with pytest.raises(HTTPException) as exc:
        llm_client.call_llm("가" * 10000, max_tokens=2048)
    assert exc.value.status_code == 422


def test_vllm_budget_cannot_exceed_server_context(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "16384")
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "4096")
    assert context_length() == 4096


@pytest.mark.parametrize("operation", ["review", "summary"])
def test_short_document_routes_to_map_reduce_when_rendered_prompt_exceeds_budget(monkeypatch, operation):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    document = DocumentIn(document_id="22222222-2222-2222-2222-222222222222",
                          filename="자료.pdf", document_type="pdf", full_text="근거" * 3000)
    sentinel = object()
    monkeypatch.setattr(main, "_generate", lambda *a, **k: pytest.fail("single pass"))
    if operation == "review":
        monkeypatch.setattr(main, "generate_review_map_reduce", lambda **k: sentinel)
        request = ReviewGenerationRequest(document=document, persona=PersonaProfileIn(
            agent_id="11111111-1111-1111-1111-111111111111", name="평가자"))
        assert main.generate_review(request) is sentinel
    else:
        monkeypatch.setattr(main, "generate_summary_map_reduce", lambda **k: sentinel)
        assert main.generate_summary(SummaryGenerationRequest(document=document)) is sentinel


def test_questions_keep_real_presentation_ids_under_small_context(monkeypatch):
    from app.schemas_v1 import ExpectedQuestionGenerationRequest, ExpectedQuestionGenerationResponse
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    request = ExpectedQuestionGenerationRequest(
        persona={"agent_id": "11111111-1111-1111-1111-111111111111", "name": "평가자"},
        evidence=[{"id": "original", "scope": "presentation", "text": "실험 근거 " * 900},
                  {"id": "reference", "scope": "persona_reference", "text": "평가 기준 " * 900}],
    )
    def generate(prompt, response_model, **kwargs):
        assert prompt_fits(prompt, kwargs["max_tokens"])
        assert '"id": "original"' in prompt
        assert "이하 생략" in prompt
        return ExpectedQuestionGenerationResponse(questions=[])
    monkeypatch.setattr(main, "_generate", generate)
    main.generate_expected_questions(request)
    assert len(request.evidence[0].text) > 5000
