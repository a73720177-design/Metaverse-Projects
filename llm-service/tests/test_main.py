"""
main.py의 HTTP 계약 테스트.

실제 Ollama는 부르지 않는다. app.main.call_llm을 mock해서, 각 생성
엔드포인트가 성공/입력 오류/LLM 오류를 계약대로(200/422/502/503) 처리하는지
검증한다. 이후 프롬프트나 스키마를 바꾸다가 계약이 깨지면 여기서 잡힌다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.llm_client import LLMError
from app.main import app

client = TestClient(app)


async def async_tokens(items):
    for item in items:
        yield item


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
        "/api/v1/practice/questions",
        {"persona": _persona_payload(), "question_count": 1, "evidence": [{"id": "e1", "scope": "presentation", "text": "발표 근거"}]},
        '{"questions": [{"question": "발표 근거를 어떻게 검증했습니까?", "presentation_evidence_ids": ["e1"], "focus": "검증"}]}',
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


def test_empty_description_rejected_without_calling_llm(monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr("app.main.call_llm", fail_if_called)
    response = client.post(
        "/api/v1/personas", json={"name": "홍길동 교수", "description": ""}
    )

    assert response.status_code == 422
    assert called is False


def test_summary_contract_accepts_large_parsed_pdf_for_map_reduce(monkeypatch):
    monkeypatch.setenv("SUMMARY_SINGLE_PASS_CHARS", "10")
    monkeypatch.setattr("app.main.generate_summary_map_reduce", lambda **kwargs: {
        "summary": "요약", "key_topics": [], "outline": []
    })
    payload = {
        "document": {
            "document_id": "22222222-2222-2222-2222-222222222222",
            "filename": "large.pdf",
            "document_type": "pdf",
            "sections": [],
            "full_text": "가" * 1_700_000,
        },
        "style": "brief",
    }
    response = client.post("/api/v1/summaries", json=payload)
    assert response.status_code == 200


def test_plain_health_ok():
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


def test_chat_uses_requested_output_limit_and_deduplicated_document_prompt(monkeypatch):
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
        "max_output_tokens": 1536,
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert response.json() == {"answer": "짧은 답변", "sources": []}
    assert captured["max_tokens"] == 1536
    assert "response_schema" not in captured
    assert captured["prompt"].count("본문") == 1
    assert '"sections"' not in captured["prompt"]


def test_chat_rejects_empty_text_response(monkeypatch):
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "   ")
    response = client.post(
        "/api/v1/chat", json={"persona": _persona_payload(), "message": "질문"}
    )
    assert response.status_code == 502


def test_chat_retries_and_blocks_chinese_output(monkeypatch):
    answers = iter(["这是中文回答", "한국어로 다시 작성한 답변입니다."])
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: next(answers))
    response = client.post(
        "/api/v1/chat", json={"persona": _persona_payload(), "message": "질문"}
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "한국어로 다시 작성한 답변입니다."


def test_chat_hides_reasoning_and_limits_duplicate_long_answer(monkeypatch):
    answer = "<think>private</think>" + "\n".join(f"줄 {i}" for i in range(69))
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: answer)
    response = client.post(
        "/api/v1/chat", json={"persona": _persona_payload(), "message": "질문"}
    )
    assert response.status_code == 200
    assert "private" not in response.text
    assert len(response.json()["answer"].splitlines()) == 30


def test_chat_stream_hides_split_reasoning_and_signals_empty_answer(monkeypatch):
    monkeypatch.setattr(
        "app.main.stream_llm", lambda *a, **k: async_tokens(["<thi", "nk>private", "</think>"])
    )
    response = client.post(
        "/api/v1/chat/stream", json={"persona": _persona_payload(), "message": "안녕"}
    )
    assert "private" not in response.text
    assert "event: error" in response.text
    assert "event: done" not in response.text


def test_no_document_chat_still_checks_context_capacity(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "1024")
    monkeypatch.setenv("LLM_CONTEXT_SAFETY_TOKENS", "512")
    response = client.post(
        "/api/v1/chat", json={
            "persona": _persona_payload(), "message": "안녕", "max_output_tokens": 1024
        }
    )
    assert response.status_code == 422


def test_chat_stream_returns_token_and_done_events(monkeypatch):
    monkeypatch.setattr("app.main.stream_llm", lambda *a, **k: async_tokens(["안녕", "하세요"]))
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
    assert "[검색된 근거]" not in captured["prompt"]


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
    assert "[검색된 근거]" in captured["prompt"]
    assert "본문" in captured["prompt"]


def test_chat_stream_uses_same_free_chat_routing(monkeypatch):
    captured = {}

    async def fake_stream(prompt, **kwargs):
        captured["prompt"] = prompt
        for token in ["반갑", "습니다"]:
            yield token

    monkeypatch.setattr("app.main.stream_llm", fake_stream)
    response = client.post(
        "/api/v1/chat/stream",
        json={"persona": _persona_payload(), "message": "안녕하세요"},
    )

    assert response.status_code == 200
    assert "일반적인 대화" in captured["prompt"]
    assert 'data: {"token": "반갑"}' in response.text


def test_chat_trims_document_to_reserved_context_budget(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "문서 기반 답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    # 페르소나 블록에 질문 전략 지침이 추가되며 페르소나만으로도 프롬프트가
    # 커졌으므로, 여유 있는 모델 길이를 줘서 트리밍 자체(문서만 잘리는지)를
    # 검증한다. 너무 타이트하면 페르소나 지침만으로 예산을 넘겨 422가 난다.
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "2048")
    monkeypatch.setenv("LLM_CONTEXT_SAFETY_TOKENS", "128")
    monkeypatch.setenv("LLM_APPROX_CHARS_PER_TOKEN", "1")
    document = _document_payload()
    document["full_text"] = "가" * 2000
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "자료를 분석해 주세요.",
            "document": document,
            "max_output_tokens": 128,
        },
    )

    assert response.status_code == 200
    assert 0 < captured["prompt"].count("가") < 2000


def test_chat_rejects_output_budget_that_leaves_no_context(monkeypatch):
    monkeypatch.setenv("LLM_MAX_MODEL_LEN", "1024")
    monkeypatch.setenv("LLM_CONTEXT_SAFETY_TOKENS", "512")
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "자료를 분석해 주세요.",
            "document": _document_payload(),
            "max_output_tokens": 1024,
        },
    )
    assert response.status_code == 422


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


def test_embeddings_returns_model_and_dimension(monkeypatch):
    monkeypatch.setattr(
        "app.main.embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    )
    response = client.post("/api/v1/embeddings", json={"texts": ["문장 1", "문장 2"]})
    assert response.status_code == 200
    body = response.json()
    assert body["dimension"] == 3
    assert len(body["embeddings"]) == 2


def test_embeddings_unavailable_returns_503(monkeypatch):
    def raise_llm_error(texts):
        raise LLMError("연결 실패")

    monkeypatch.setattr("app.main.embed_texts", raise_llm_error)
    response = client.post("/api/v1/embeddings", json={"texts": ["문장"]})
    assert response.status_code == 503


def test_chat_without_history_field_still_succeeds(monkeypatch):
    """Older Backend builds that never send history must keep working."""
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "답변")
    response = client.post(
        "/api/v1/chat", json={"persona": _persona_payload(), "message": "질문"}
    )
    assert response.status_code == 200


def test_chat_includes_history_block_in_prompt(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    payload = {
        "persona": _persona_payload(),
        "message": "그건 전문 용어야?",
        "document": _document_payload(),
        "history": [
            {"role": "user", "content": "이 발표의 매출 근거는?"},
            {"role": "assistant", "content": "3페이지 표를 근거로 듭니다."},
        ],
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert "[이전 대화]" in captured["prompt"]
    assert "이 발표의 매출 근거는?" in captured["prompt"]
    assert "3페이지 표를 근거로 듭니다." in captured["prompt"]
    # Ambiguous follow-up with an attached document must stay grounded.
    assert "[검색된 근거]" in captured["prompt"]


def test_chat_follow_up_with_thanks_marker_stays_grounded_when_history_present(monkeypatch):
    """A free-chat marker in a follow-up should not bounce a live conversation
    out of the grounded document prompt."""
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    payload = {
        "persona": _persona_payload(),
        "message": "고마워요, 근데 그거 무슨 뜻이에요?",
        "document": _document_payload(),
        "history": [
            {"role": "user", "content": "이 발표의 핵심 주장은?"},
            {"role": "assistant", "content": "매출 성장률이 핵심입니다."},
        ],
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert "[검색된 근거]" in captured["prompt"]
    assert "일반적인 대화" not in captured["prompt"]


def test_chat_history_is_truncated_from_oldest_when_over_budget(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return "답변"

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("CHAT_HISTORY_MAX_CHARS", "30")
    payload = {
        "persona": _persona_payload(),
        "message": "질문",
        "history": [
            {"role": "user", "content": "오래된 첫 질문"},
            {"role": "assistant", "content": "오래된 첫 답변"},
            {"role": "user", "content": "최근 질문"},
            {"role": "assistant", "content": "최근 답변"},
        ],
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    assert "오래된 첫 질문" not in captured["prompt"]
    assert "최근 질문" in captured["prompt"]
    assert "최근 답변" in captured["prompt"]


def test_chat_stream_includes_history_block(monkeypatch):
    captured = {}

    async def fake_stream(prompt, **kwargs):
        captured["prompt"] = prompt
        for token in ["답", "변"]:
            yield token

    monkeypatch.setattr("app.main.stream_llm", fake_stream)
    payload = {
        "persona": _persona_payload(),
        "message": "그건 왜 그런가요?",
        "document": _document_payload(),
        "history": [
            {"role": "user", "content": "핵심 주장은?"},
            {"role": "assistant", "content": "매출 근거입니다."},
        ],
    }
    response = client.post("/api/v1/chat/stream", json=payload)

    assert response.status_code == 200
    assert "핵심 주장은?" in captured["prompt"]


def test_embeddings_inconsistent_dimension_returns_502(monkeypatch):
    monkeypatch.setattr(
        "app.main.embed_texts", lambda texts: [[0.1, 0.2], [0.1, 0.2, 0.3]]
    )
    response = client.post("/api/v1/embeddings", json={"texts": ["문장 1", "문장 2"]})
    assert response.status_code == 502


def test_embeddings_rejects_oversized_item():
    response = client.post("/api/v1/embeddings", json={"texts": ["a" * 8001]})
    assert response.status_code == 422


def test_ollama_health_fails_when_embedding_model_not_pulled(monkeypatch):
    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {"models": [{"name": "qwen3:4b"}]}

    monkeypatch.setattr("app.llm_client.requests.get", lambda *a, **k: FakeResponse())
    from app.llm_client import check_ollama_health

    assert check_ollama_health() is False


def test_ollama_health_ok_when_embedding_model_pulled(monkeypatch):
    class FakeResponse:
        ok = True

        @staticmethod
        def json():
                    return {"models": [
                        {"name": "bge-m3:latest"},
                        {"name": "qwen3:4b"},
                        {"name": "qwen2.5:7b"},
                    ]}

    monkeypatch.setattr("app.llm_client.requests.get", lambda *a, **k: FakeResponse())
    from app.llm_client import check_ollama_health

    assert check_ollama_health() is True


def _long_document_payload(total_chars: int) -> dict:
    return {
        "document_id": "22222222-2222-2222-2222-222222222222",
        "filename": "long.pdf",
        "document_type": "pdf",
        "sections": [],
        "full_text": "가" * total_chars,
    }


def _reduce_response_json(**overrides) -> str:
    body = {
        "claims": [],
        "feedback": {"positive": "p", "negative": "n"},
        "questions": ["질문 1", "질문 2", "질문 3"],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def test_review_short_document_uses_single_pass_call(monkeypatch):
    calls = []

    def fake_call(prompt, **kwargs):
        calls.append(prompt)
        return _reduce_response_json()

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document": _document_payload()},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["coverage"] == {"total_chunks": 1, "analyzed_chunks": 1, "truncated": False, "selection_method": "full"}


def test_review_long_document_uses_map_reduce(monkeypatch):
    calls = []

    def fake_call(prompt, **kwargs):
        calls.append(prompt)
        if "[구간별로 추출된 주장 목록]" in prompt:
            return _reduce_response_json()
        return '{"claims": []}'

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document": _long_document_payload(50000)},
    )

    assert response.status_code == 200
    map_calls = [p for p in calls if "[발표 자료 구간]" in p]
    reduce_calls = [p for p in calls if "[구간별로 추출된 주장 목록]" in p]
    assert len(reduce_calls) == 1
    assert 1 <= len(map_calls) <= 6
    assert len(calls) == len(map_calls) + len(reduce_calls)
    body = response.json()
    assert body["coverage"] is not None
    assert body["feedback"] == {"positive": "p", "negative": "n"}


def test_review_map_reduce_still_returns_valid_feedback_when_all_maps_empty(monkeypatch):
    def fake_call(prompt, **kwargs):
        if "[구간별로 추출된 주장 목록]" in prompt:
            return _reduce_response_json()
        return '{"claims": []}'

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document": _long_document_payload(50000)},
    )

    assert response.status_code == 200
    assert len(response.json()["questions"]) == 3


def test_review_map_reduce_propagates_llm_error_as_503(monkeypatch):
    def raise_llm_error(*args, **kwargs):
        raise LLMError("연결 실패")

    monkeypatch.setattr("app.main.call_llm", raise_llm_error)
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document": _long_document_payload(50000)},
    )

    assert response.status_code == 503


def test_review_map_reduce_bad_schema_returns_502(monkeypatch):
    def fake_call(prompt, **kwargs):
        if "[구간별로 추출된 주장 목록]" in prompt:
            return "이건 JSON이 아님"
        return '{"claims": []}'

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("REVIEW_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document": _long_document_payload(50000)},
    )

    assert response.status_code == 502


def _summary_response_json(**overrides) -> str:
    body = {
        "summary": "요약문",
        "key_topics": [],
        "outline": ["항목 1"],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


@pytest.mark.parametrize("style", ["brief", "detailed", "outline"])
def test_summary_short_document_uses_single_pass_call(monkeypatch, style):
    calls = []

    def fake_call(prompt, **kwargs):
        calls.append(prompt)
        return _summary_response_json()

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/summaries",
        json={"document": _document_payload(), "style": style},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    body = response.json()
    assert body["summary"] == "요약문"
    assert body["outline"] == ["항목 1"]


def test_summary_without_persona_uses_general_reader_perspective(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return _summary_response_json()

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/summaries",
        json={"document": _document_payload()},
    )

    assert response.status_code == 200
    assert "일반적인 독자 관점" in captured["prompt"]


def test_summary_with_persona_passes_persona_json(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        return _summary_response_json()

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/summaries",
        json={"document": _document_payload(), "persona": _persona_payload()},
    )

    assert response.status_code == 200
    assert "홍길동 교수" in captured["prompt"]


def test_summary_long_document_uses_map_reduce(monkeypatch):
    calls = []

    def fake_call(prompt, **kwargs):
        calls.append(prompt)
        if "[구간별로 추출된 핵심 요점 목록]" in prompt:
            return _summary_response_json()
        return '{"points": []}'

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("SUMMARY_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/summaries",
        json={"document": _long_document_payload(50000)},
    )

    assert response.status_code == 200
    map_calls = [p for p in calls if "[문서 구간]" in p]
    reduce_calls = [p for p in calls if "[구간별로 추출된 핵심 요점 목록]" in p]
    assert len(reduce_calls) == 1
    assert 1 <= len(map_calls) <= 6
    assert len(calls) == len(map_calls) + len(reduce_calls)
    assert response.json()["summary"] == "요약문"


def test_summary_map_reduce_propagates_llm_error_as_503(monkeypatch):
    def raise_llm_error(*args, **kwargs):
        raise LLMError("연결 실패")

    monkeypatch.setattr("app.main.call_llm", raise_llm_error)
    monkeypatch.setenv("SUMMARY_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/summaries",
        json={"document": _long_document_payload(50000)},
    )

    assert response.status_code == 503


def test_summary_map_reduce_bad_schema_returns_502(monkeypatch):
    def fake_call(prompt, **kwargs):
        if "[구간별로 추출된 핵심 요점 목록]" in prompt:
            return "이건 JSON이 아님"
        return '{"points": []}'

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setenv("SUMMARY_SINGLE_PASS_CHARS", "1000")

    response = client.post(
        "/api/v1/summaries",
        json={"document": _long_document_payload(50000)},
    )

    assert response.status_code == 502


def test_llm_failures_do_not_log_private_exceptions(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise LLMError('PRIVATE_DOCUMENT http://internal-service:11434')
    monkeypatch.setattr('app.main.call_llm', fail)
    response = client.post('/api/v1/personas', json={'name': '평가자', 'description': '근거 검증'})
    assert response.status_code == 503
    assert 'PRIVATE_DOCUMENT' not in response.text + caplog.text
    assert 'internal-service' not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_short_summary_coverage_is_derived_not_trusted_from_model(monkeypatch):
    monkeypatch.setattr('app.main.call_llm', lambda *a, **k: json.dumps({
        'summary': '요약', 'key_topics': [], 'outline': [],
        'coverage': {'total_chunks': 99, 'analyzed_chunks': 1, 'truncated': True}}))
    response = client.post('/api/v1/summaries', json={'document': _document_payload(), 'style': 'brief'})
    assert response.status_code == 200
    assert response.json()['coverage'] == {'total_chunks': 1, 'analyzed_chunks': 1, 'truncated': False, 'selection_method': 'full'}
