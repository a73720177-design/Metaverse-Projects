"""
main.py의 HTTP 계약 테스트.

실제 Ollama는 부르지 않는다. 생성은 app.main.call_llm을, 임베딩은
app.rag.embed_texts를 mock한다. 임베딩 mock은 텍스트에 들어 있는 키워드로
직교하는 단위 벡터를 돌려주므로, 질의와 자료가 같은 키워드를 공유하면
유사도 1.0, 아니면 0.0이 되어 임계값 분기를 그대로 검증할 수 있다.
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import rag
from app.llm_client import LLMError
from app.main import app

client = TestClient(app)

AGENT_ID = "11111111-1111-1111-1111-111111111111"
DOCUMENT_ID = "22222222-2222-2222-2222-222222222222"

REVIEW_JSON = '{"claims": [], "feedback": {"positive": "p", "negative": "n"}, "questions": []}'
PERSONA_JSON = '{"role": "평가자", "expertise": [], "evaluation_style": []}'

# 키워드별 직교 벡터. 같은 키워드를 공유하면 코사인 유사도가 1.0이 된다.
_KEYWORDS = ("매출", "예산")


def _fake_embed(texts, model=None):
    vectors = []
    for text in texts:
        vector = [0.0] * (len(_KEYWORDS) + 1)
        for position, keyword in enumerate(_KEYWORDS):
            if keyword in text:
                vector[position] = 1.0
        if not any(vector):
            vector[-1] = 1.0
        vectors.append(vector)
    return vectors


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """테스트마다 빈 인덱스 저장소를 쓴다. 디스크 캐시도 tmp_path로 격리."""
    monkeypatch.setattr(rag, "embed_texts", _fake_embed)
    store = rag.DocumentIndexStore(cache_dir=tmp_path / "rag_cache")
    monkeypatch.setattr(rag, "store", store)
    return store


def _persona_payload() -> dict:
    return {
        "agent_id": AGENT_ID,
        "name": "홍길동 교수",
        "description": "근거를 중요하게 평가한다.",
        "role": "평가자",
        "expertise": [],
        "evaluation_style": [],
    }


def _document_payload() -> dict:
    return {
        "document_id": DOCUMENT_ID,
        "filename": "slides.pptx",
        "document_type": "pptx",
        "sections": [
            {"index": 1, "text": "작년 매출은 120억 원이다."},
            {"index": 2, "text": "내년 예산 계획을 설명한다."},
        ],
        "full_text": "작년 매출은 120억 원이다.\n내년 예산 계획을 설명한다.",
    }


def _index_document() -> dict:
    response = client.post("/api/v1/documents/index", json=_document_payload())
    assert response.status_code == 200
    return response.json()


# --- 인덱싱 -----------------------------------------------------------


def test_index_document_returns_chunk_count():
    body = _index_document()
    assert body["document_id"] == DOCUMENT_ID
    assert body["chunk_count"] == 2
    assert body["reused"] is False


def test_reindexing_same_content_skips_embedding(monkeypatch):
    _index_document()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("같은 내용을 다시 임베딩하면 안 됩니다.")

    monkeypatch.setattr(rag, "embed_texts", fail_if_called)
    body = _index_document()
    assert body["reused"] is True


def test_index_survives_new_store_via_disk_cache(monkeypatch):
    _index_document()
    # 프로세스를 재시작한 상황: 메모리는 비었지만 디스크 캐시는 남아 있다.
    reloaded = rag.DocumentIndexStore(cache_dir=rag.store.cache_dir)
    monkeypatch.setattr(rag, "store", reloaded)

    assert reloaded.is_indexed(UUID(DOCUMENT_ID)) is True
    assert reloaded.describe(UUID(DOCUMENT_ID)) == ("slides.pptx", "pptx")


def test_deleting_index_removes_document_and_disk_cache():
    _index_document()
    cache_file = rag.store.cache_dir / f"{DOCUMENT_ID}.npz"
    assert cache_file.exists()

    response = client.delete(f"/api/v1/documents/{DOCUMENT_ID}/index")

    assert response.status_code == 204
    assert cache_file.exists() is False
    assert rag.store.is_indexed(UUID(DOCUMENT_ID)) is False


# --- 평가 -------------------------------------------------------------


def test_review_returns_409_when_document_not_indexed():
    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document_id": DOCUMENT_ID},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_not_indexed"


def test_review_uses_thinking_model_with_retrieved_context(monkeypatch):
    _index_document()
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return REVIEW_JSON

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/reviews",
        json={
            "persona": _persona_payload(),
            "document_id": DOCUMENT_ID,
            "instructions": "매출 근거를 확인해 주세요.",
        },
    )

    assert response.status_code == 200
    assert captured["think"] is True
    assert captured["model"] == "qwen3:8b"
    assert "[출처: slides.pptx 구간 1]" in captured["prompt"]
    assert "작년 매출은 120억 원이다." in captured["prompt"]


def test_review_returns_502_on_non_json_response(monkeypatch):
    _index_document()
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "이건 JSON이 아님")
    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document_id": DOCUMENT_ID},
    )
    assert response.status_code == 502


def test_review_returns_503_when_ollama_unreachable(monkeypatch):
    _index_document()

    def raise_llm_error(*args, **kwargs):
        raise LLMError("연결 실패")

    monkeypatch.setattr("app.main.call_llm", raise_llm_error)
    response = client.post(
        "/api/v1/reviews",
        json={"persona": _persona_payload(), "document_id": DOCUMENT_ID},
    )
    assert response.status_code == 503


# --- 채팅 -------------------------------------------------------------


def test_chat_answers_with_retrieved_sources(monkeypatch):
    _index_document()
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "매출 근거가 부족합니다."

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "매출 수치의 근거는 무엇인가요?",
            "document_ids": [DOCUMENT_ID],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["needs_more_material"] is False
    assert body["sources"][0]["filename"] == "slides.pptx"
    assert body["sources"][0]["page"] == 1
    assert captured["think"] is True
    assert captured["model"] == "qwen3:8b"
    assert "작년 매출은 120억 원이다." in captured["prompt"]


def test_chat_requests_more_material_without_calling_llm(monkeypatch):
    _index_document()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("근거가 없으면 생성 모델을 부르지 않습니다.")

    monkeypatch.setattr("app.main.call_llm", fail_if_called)
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "우리 회사 조직도는 어떻게 되나요?",
            "document_ids": [DOCUMENT_ID],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["needs_more_material"] is True
    assert body["sources"] == []
    assert "홍길동 교수" in body["answer"]


def test_chat_without_documents_requests_material(monkeypatch):
    monkeypatch.setattr(
        "app.main.call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출되면 안 됩니다.")),
    )
    response = client.post(
        "/api/v1/chat",
        json={"persona": _persona_payload(), "message": "매출 근거가 궁금합니다."},
    )
    assert response.status_code == 200
    assert response.json()["needs_more_material"] is True


def test_small_talk_skips_retrieval_and_uses_fast_model(monkeypatch):
    _index_document()
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "반갑습니다."

    def fail_if_called(*args, **kwargs):
        raise AssertionError("인사말에는 검색하지 않습니다.")

    monkeypatch.setattr("app.main.call_llm", fake_call)
    monkeypatch.setattr(rag, "embed_texts", fail_if_called)
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "안녕하세요",
            "document_ids": [DOCUMENT_ID],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["needs_more_material"] is False
    assert captured["model"] == "qwen3:4b"
    assert captured["max_tokens"] == 160
    assert captured.get("think", False) is False


def test_chat_returns_409_when_document_not_indexed():
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "매출 근거는 무엇인가요?",
            "document_ids": [DOCUMENT_ID],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_not_indexed"


def test_chat_rejects_empty_text_response(monkeypatch):
    _index_document()
    monkeypatch.setattr("app.main.call_llm", lambda *a, **k: "   ")
    response = client.post(
        "/api/v1/chat",
        json={
            "persona": _persona_payload(),
            "message": "매출 근거는 무엇인가요?",
            "document_ids": [DOCUMENT_ID],
        },
    )
    assert response.status_code == 502


# --- 페르소나 / 헬스체크 ---------------------------------------------


def test_persona_uses_fast_model(monkeypatch):
    captured = {}

    def fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return PERSONA_JSON

    monkeypatch.setattr("app.main.call_llm", fake_call)
    response = client.post(
        "/api/v1/personas",
        json={"name": "홍길동 교수", "description": "근거를 중요하게 평가한다."},
    )

    assert response.status_code == 200
    assert captured["model"] == "qwen3:4b"
    assert captured.get("think", False) is False


def test_structured_response_accepts_trailing_model_text(monkeypatch):
    monkeypatch.setattr(
        "app.main.call_llm", lambda *a, **k: f"{PERSONA_JSON}\n추가 설명"
    )
    response = client.post(
        "/api/v1/personas",
        json={"name": "평가자", "description": "근거를 확인한다."},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "평가자"


def test_legacy_endpoints_are_removed():
    assert client.post("/extract-concepts", json={"paper_text": "x"}).status_code == 404
    assert client.post("/api/v1/chat/stream", json={}).status_code == 404


def test_legacy_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_health_ok_when_ollama_reachable(monkeypatch):
    monkeypatch.setattr("app.main.check_ollama_health", lambda: True)
    assert client.get("/api/v1/health").status_code == 200


def test_v1_health_503_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr("app.main.check_ollama_health", lambda: False)
    assert client.get("/api/v1/health").status_code == 503
