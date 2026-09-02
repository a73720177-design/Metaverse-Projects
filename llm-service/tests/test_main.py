"""
main.py의 HTTP 계약 테스트.

실제 Ollama는 부르지 않는다. app.main.call_llm을 mock해서, 각 생성
엔드포인트가 성공/입력 오류/LLM 오류를 계약대로(200/422/502/503) 처리하는지
검증한다. 이후 프롬프트나 스키마를 바꾸다가 계약이 깨지면 여기서 잡힌다.
"""

import pytest
from fastapi.testclient import TestClient

from app.llm_client import LLMError
from app.main import app

client = TestClient(app)


def _persona_payload() -> dict:
    return {
        "agent_id": "11111111-1111-1111-1111-111111111111",
        "name": "홍길동 교수",
        "description": "근거를 중요하게 평가한다.",
        "role": "평가자",
        "expertise": [],
        "evaluation_style": [],
    }


def _document_payload() -> dict:
    return {
        "document_id": "22222222-2222-2222-2222-222222222222",
        "filename": "slides.pptx",
        "document_type": "pptx",
        "sections": [{"index": 1, "text": "본문"}],
        "full_text": "본문",
    }


# (경로, 요청 payload, 스키마를 만족하는 LLM 응답 문자열)
ENDPOINTS = [
    (
        "/extract-concepts",
        {"paper_text": "논문 본문"},
        '{"concepts": [{"name": "a", "definition": "b"}]}',
    ),
    (
        "/generate-questions",
        {
            "concepts": [{"name": "a", "definition": "b"}],
            "critical_points": "관점",
            "script_text": "대본",
        },
        '{"questions": [{"question": "q"}]}',
    ),
    (
        "/api/v1/personas",
        {"name": "홍길동 교수", "description": "근거를 중요하게 평가한다."},
        '{"role": "평가자", "expertise": [], "evaluation_style": []}',
    ),
    (
        "/api/v1/reviews",
        {"persona": _persona_payload(), "document": _document_payload()},
        '{"claims": [], "feedback": {"positive": "p", "negative": "n"}, "questions": []}',
    ),
    (
        "/api/v1/chat",
        {"persona": _persona_payload(), "message": "질문"},
        "짧은 답변",
    ),
]

ENDPOINT_IDS = [path for path, _, _ in ENDPOINTS]


@pytest.mark.parametrize("path,payload,llm_response", ENDPOINTS, ids=ENDPOINT_IDS)
def test_success_returns_200(monkeypatch, path, payload, llm_response):
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: llm_response)
    response = client.post(path, json=payload)
    assert response.status_code == 200


@pytest.mark.parametrize("path,payload,_llm_response", ENDPOINTS, ids=ENDPOINT_IDS)
def test_ollama_connection_failure_returns_503(monkeypatch, path, payload, _llm_response):
    def raise_llm_error(*args, **kwargs):
        raise LLMError("연결 실패")

    monkeypatch.setattr("app.main.call_llm", raise_llm_error)
    response = client.post(path, json=payload)
    assert response.status_code == 503


@pytest.mark.parametrize("path,payload,_llm_response", ENDPOINTS, ids=ENDPOINT_IDS)
def test_non_json_llm_response_returns_502(monkeypatch, path, payload, _llm_response):
    if path == "/api/v1/chat":
        pytest.skip("채팅은 자유 텍스트 응답을 사용합니다.")
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "이건 JSON이 아님")
    response = client.post(path, json=payload)
    assert response.status_code == 502


@pytest.mark.parametrize("path,payload,_llm_response", ENDPOINTS, ids=ENDPOINT_IDS)
def test_schema_mismatch_returns_502(monkeypatch, path, payload, _llm_response):
    if path == "/api/v1/chat":
        pytest.skip("채팅은 자유 텍스트 응답을 사용합니다.")
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "{}")
    response = client.post(path, json=payload)
    assert response.status_code == 502


def test_empty_paper_text_rejected_without_calling_llm(monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr("app.main.call_llm", fail_if_called)
    response = client.post("/extract-concepts", json={"paper_text": ""})

    assert response.status_code == 422
    assert called is False


def test_legacy_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_health_ok_when_ollama_reachable(monkeypatch):
    monkeypatch.setattr("app.main.check_ollama_health", lambda: True)
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_v1_health_503_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr("app.main.check_ollama_health", lambda: False)
    response = client.get("/api/v1/health")
    assert response.status_code == 503


def test_chat_uses_short_output_limit_and_deduplicated_document_prompt(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "짧은 답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    payload = {
        "persona": _persona_payload(),
        "message": "매출은 얼마인가요?",
        "document": _document_payload(),
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"answer": "짧은 답변", "sources": []}
    assert captured["max_tokens"] == 160
    assert "response_schema" not in captured
    assert captured["prompt"].count("본문") == 1
    assert '"sections"' not in captured["prompt"]


def test_chat_rejects_empty_text_response(monkeypatch):
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "   ")
    response = client.post(
        "/api/v1/chat", json={"persona": _persona_payload(), "message": "질문"}
    )
    assert response.status_code == 502


def test_chat_stream_returns_token_and_done_events(monkeypatch):
    monkeypatch.setattr("app.main.stream_llm", lambda *a, **k: iter(["안녕", "하세요"]))
    response = client.post(
        "/api/v1/chat/stream",
        json={"persona": _persona_payload(), "message": "안녕"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"token": "안녕"}' in response.text
    assert 'data: {"token": "하세요"}' in response.text
    assert "event: done" in response.text


def test_chat_routes_general_conversation_without_document_context(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "안녕하세요."

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/chat",
        json={"persona": _persona_payload(), "message": "안녕, 넌 누구야?"},
    )

    assert response.status_code == 200
    assert "일반적인 대화" in captured["prompt"]
    assert "[참고 문서]" not in captured["prompt"]


def test_chat_keeps_ambiguous_question_grounded_when_document_is_attached(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "문서 기반 답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    payload = {
        "persona": _persona_payload(),
        "message": "이 부분은 왜 그런가요?",
        "document": _document_payload(),
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert "[참고 문서]" in captured["prompt"]
    assert "본문" in captured["prompt"]


def test_chat_stream_uses_same_free_chat_routing(monkeypatch):
    captured = {}

    def fake_stream(prompt, **kwargs):
        captured["prompt"] = prompt
        return iter(["반갑", "습니다"])

    monkeypatch.setattr("app.main.stream_llm", fake_stream)
    response = client.post(
        "/api/v1/chat/stream",
        json={"persona": _persona_payload(), "message": "안녕하세요"},
    )

    assert response.status_code == 200
    assert "일반적인 대화" in captured["prompt"]
    assert 'data: {"token": "반갑"}' in response.text


def test_structured_response_accepts_trailing_model_text(monkeypatch):
    monkeypatch.setattr(
        "app.main.call_llm",
        lambda *a, **k: '{"role":"평가자","expertise":[],"evaluation_style":[]}\n추가 설명',
    )
    response = client.post(
        "/api/v1/personas",
        json={"name": "평가자", "description": "근거를 확인한다."},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "평가자"
