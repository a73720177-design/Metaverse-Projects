import json
import pytest

from app.llm_client import LLMError, call_llm, check_ollama_health, embed_texts, stream_llm


class FakeResponse:
    def __init__(self, payload=None, lines=None, ok=True):
        self._payload = payload
        self._lines = lines or []
        self.ok = ok

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_vllm_non_stream_payload_and_structured_output(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse({"choices": [{"message": {"content": '{"ok":true}'}}]})

    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "quantized-model")
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    monkeypatch.setattr("app.llm_client.requests.post", fake_post)
    schema = {"type": "object"}
    result = call_llm("prompt", response_schema=schema, max_tokens=1536)

    assert result == '{"ok":true}'
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["json"]["max_tokens"] == 1536
    assert captured["json"]["structured_outputs"] == {"json": schema}
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["json"]["messages"][0]["content"].endswith("\n/no_think")
    assert captured["headers"] == {"Authorization": "Bearer secret"}


def test_vllm_stream_parses_openai_sse(monkeypatch):
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "안녕"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "하세요"}}]}),
        "data: [DONE]",
    ]
    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "quantized-model")
    monkeypatch.setattr(
        "app.llm_client.requests.post", lambda *a, **k: FakeResponse(lines=lines)
    )
    assert list(stream_llm("prompt", max_tokens=512)) == ["안녕", "하세요"]


def test_vllm_health_uses_models_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse(ok=True)

    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setattr("app.llm_client.requests.get", fake_get)
    assert check_ollama_health() is True
    assert captured["url"].endswith("/v1/models")


def test_vllm_stream_skips_reasoning_and_usage_events(monkeypatch):
    captured = {}
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}',
        'data: {"choices":[{"delta":{"content":"답변"}}]}',
        'data: {"choices":[],"usage":{"completion_tokens":10}}',
        'data: [DONE]',
    ]

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse(lines=lines)

    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "quantized-model")
    monkeypatch.setattr("app.llm_client.requests.post", fake_post)
    assert list(stream_llm("prompt")) == ["답변"]
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("payload", [[], {"response": None}, {"error": "failed"}])
def test_ollama_malformed_generation_is_a_controlled_error(monkeypatch, payload):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr("app.llm_client.requests.post", lambda *a, **k: FakeResponse(payload))
    with pytest.raises(LLMError):
        call_llm("prompt")


def test_ollama_stream_error_event_is_not_success(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(
        "app.llm_client.requests.post",
        lambda *a, **k: FakeResponse(lines=['{"error":"model unloaded"}']),
    )
    with pytest.raises(LLMError):
        list(stream_llm("prompt"))


def test_ollama_disables_thinking_in_option_and_prompt(monkeypatch):
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse({"response": "최종 답변"})

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr("app.llm_client.requests.post", fake_post)

    assert call_llm("질문") == "최종 답변"
    assert captured["json"]["think"] is False
    assert captured["json"]["prompt"].endswith("\n/no_think")


@pytest.mark.parametrize("vector", [None, [], [True], [float("nan")], [float("inf")], ["1"]])
def test_embeddings_reject_invalid_vectors_before_database_insert(monkeypatch, vector):
    monkeypatch.setattr(
        "app.llm_client.requests.post",
        lambda *a, **k: FakeResponse({"embeddings": [vector]}),
    )
    with pytest.raises(LLMError):
        embed_texts(["문서"])
