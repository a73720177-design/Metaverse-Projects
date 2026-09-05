"""
Ollama HTTP 계약 테스트.

실제 서버는 부르지 않고 requests를 mock한다. think 모드에서 사고 과정이
응답 본문에 섞여 나오는 경우와, 임베딩 배치 호출을 검증한다.
"""

import pytest

from app import llm_client
from app.llm_client import LLMError, call_llm, embed_texts


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_call_llm_strips_inline_think_block(monkeypatch):
    """Ollama 버전에 따라 <think>가 response에 섞여 나와도 답변만 남아야 한다."""
    monkeypatch.setattr(
        llm_client.requests,
        "post",
        lambda *a, **k: FakeResponse(
            {"response": "<think>근거를 확인하자</think>실제 답변입니다."}
        ),
    )
    assert call_llm("프롬프트", think=True) == "실제 답변입니다."


def test_call_llm_sends_num_ctx_and_think(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse({"response": "답변"})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    call_llm("프롬프트", model="qwen3:8b", think=True, max_tokens=1536)

    assert captured["url"].endswith("/api/generate")
    assert captured["payload"]["model"] == "qwen3:8b"
    assert captured["payload"]["think"] is True
    assert captured["payload"]["options"]["num_predict"] == 1536
    assert captured["payload"]["options"]["num_ctx"] == llm_client.OLLAMA_NUM_CTX


def test_embed_texts_batches_requests(monkeypatch):
    batches: list[int] = []

    def fake_post(url, json, timeout):
        assert url.endswith("/api/embed")
        assert json["model"] == llm_client.OLLAMA_EMBED_MODEL
        batches.append(len(json["input"]))
        return FakeResponse({"embeddings": [[0.1, 0.2] for _ in json["input"]]})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client, "EMBED_BATCH_SIZE", 2)

    vectors = embed_texts(["a", "b", "c"])

    assert batches == [2, 1]
    assert len(vectors) == 3


def test_embed_texts_rejects_mismatched_response(monkeypatch):
    monkeypatch.setattr(
        llm_client.requests,
        "post",
        lambda *a, **k: FakeResponse({"embeddings": [[0.1]]}),
    )
    with pytest.raises(LLMError):
        embed_texts(["a", "b"])


def test_embed_texts_returns_empty_without_calling_ollama(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("빈 입력에는 호출하지 않습니다.")

    monkeypatch.setattr(llm_client.requests, "post", fail_if_called)
    assert embed_texts([]) == []
