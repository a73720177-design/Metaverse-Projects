from fastapi.testclient import TestClient

from app.reranker_server import create_app


def test_local_reranker_contract_without_optional_model_dependencies():
    class Ranker:
        def score(self, query, documents):
            assert query == "실험 근거"
            assert documents == ["배경", "실험"]
            return [.1, .9]
    client = TestClient(create_app(Ranker()))
    response = client.post("/rerank", json={"query": "실험 근거", "documents": ["배경", "실험"]})
    assert response.status_code == 200
    assert response.json()["results"][1] == {"index": 1, "relevance_score": .9}
    assert client.post("/rerank", json={"query": "실험", "documents": []}).status_code == 422


def test_reranker_releases_slot_after_model_failure():
    class Ranker:
        calls = 0
        def score(self, query, documents):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("model failed")
            return [.5]
    client = TestClient(create_app(Ranker()), raise_server_exceptions=False)
    payload = {"query": "질문", "documents": ["문서"]}
    assert client.post("/rerank", json=payload).status_code == 500
    assert client.post("/rerank", json=payload).status_code == 200
