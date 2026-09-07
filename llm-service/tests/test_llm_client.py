import json

from app.llm_client import call_llm, check_ollama_health, stream_llm


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
