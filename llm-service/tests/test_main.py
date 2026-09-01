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
        '{"answer": "a", "sources": []}',
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
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "이건 JSON이 아님")
    response = client.post(path, json=payload)
    assert response.status_code == 502


@pytest.mark.parametrize("path,payload,_llm_response", ENDPOINTS, ids=ENDPOINT_IDS)
def test_schema_mismatch_returns_502(monkeypatch, path, payload, _llm_response):
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


# --- /api/v1/chat: 주제 분류(1차 호출) → on/off-topic 분기(2차 호출) ---
#
# call_llm이 호출 순서대로 responses의 값을 반환하도록 하는 mock. 각 호출의
# kwargs(response_schema, think)도 함께 기록해 분기별 호출 방식을 검증한다.


def _sequenced_call_llm(responses):
    calls = []

    def _mock(prompt, *args, **kwargs):
        calls.append(
            {
                "prompt": prompt,
                "response_schema": kwargs.get("response_schema"),
                "think": kwargs.get("think", False),
            }
        )
        return responses[len(calls) - 1]

    return _mock, calls


def test_chat_on_topic_calls_llm_twice_and_keeps_sources(monkeypatch):
    responses = [
        '{"on_topic": true}',
        '{"answer": "문서에 따르면...", "sources": [{"filename": "slides.pptx", "excerpt": "근거 문장"}]}',
    ]
    mock, calls = _sequenced_call_llm(responses)
    monkeypatch.setattr("app.main.call_llm", mock)

    payload = {
        "persona": _persona_payload(),
        "message": "이 발표의 핵심 주장 근거가 뭐야?",
        "document": _document_payload(),
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["sources"] != []
    assert len(calls) == 2
    # 분류 호출: think=False, JSON 스키마 강제
    assert calls[0]["think"] is False
    assert calls[0]["response_schema"] is not None
    # 생성 호출(on-topic): think=False, JSON 스키마 강제 (기존 동작 유지)
    assert calls[1]["think"] is False
    assert calls[1]["response_schema"] is not None


def test_chat_off_topic_uses_free_generation_without_schema(monkeypatch):
    responses = [
        '{"on_topic": false}',
        "저는 발표 평가를 돕는 역할이라 특정 모델명을 밝히긴 어렵지만, 편하게 물어보세요.",
    ]
    mock, calls = _sequenced_call_llm(responses)
    monkeypatch.setattr("app.main.call_llm", mock)

    payload = {
        "persona": _persona_payload(),
        "message": "너는 무슨 모델이야?",
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["answer"] != ""
    assert len(calls) == 2
    # 생성 호출(off-topic): think=True, JSON 스키마 강제하지 않음
    assert calls[1]["think"] is True
    assert calls[1]["response_schema"] is None


def test_chat_off_topic_strips_think_tags_from_answer(monkeypatch):
    responses = [
        '{"on_topic": false}',
        "<think>사용자가 잡담을 원하는군</think>네, 편하게 말씀하세요!",
    ]
    mock, _calls = _sequenced_call_llm(responses)
    monkeypatch.setattr("app.main.call_llm", mock)

    payload = {"persona": _persona_payload(), "message": "안녕!"}
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["answer"] == "네, 편하게 말씀하세요!"


def test_chat_classification_failure_falls_back_to_on_topic(monkeypatch):
    call_count = {"n": 0}

    def mock(prompt, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise LLMError("분류 호출 실패")
        return '{"answer": "a", "sources": [{"filename": "slides.pptx", "excerpt": "근거"}]}'

    monkeypatch.setattr("app.main.call_llm", mock)

    payload = {
        "persona": _persona_payload(),
        "message": "질문",
        "document": _document_payload(),
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert call_count["n"] == 2
    assert response.json()["sources"] != []
