import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.integrations.reranker import RerankerClient
from app.models.document import DocumentParseResponse, DocumentSection
from app.services.vector_rag import VectorRag, VectorSearchHit


@pytest.mark.asyncio
async def test_reranker_sorts_scores_and_sends_only_candidate_text():
    def handler(request):
        assert request.url.path == "/rerank"
        assert json.loads(request.content) == {"query": "질문", "documents": ["첫 근거", "다른 근거"]}
        return httpx.Response(200, json={"results": [
            {"index": 0, "relevance_score": .1}, {"index": 1, "relevance_score": .9}]})
    client = RerankerClient(httpx.MockTransport(handler))
    assert await client.rank("질문", ["첫 근거", "다른 근거"]) == [1, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [
    [], [{"index": 0, "relevance_score": .1}] * 2,
    [{"index": 0, "relevance_score": .1}, {"index": 2, "relevance_score": .2}],
    [{"index": True, "relevance_score": .1}, {"index": 0, "relevance_score": .2}],
    [{"index": 0, "relevance_score": 2}, {"index": 1, "relevance_score": .2}],
])
async def test_malformed_rankings_are_rejected(results):
    client = RerankerClient(httpx.MockTransport(lambda _: httpx.Response(200, json={"results": results})))
    with pytest.raises(ValueError):
        await client.rank("질문", ["a", "b"])


def test_remote_reranker_cannot_receive_private_documents(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_URL", "http://example.com")
    with pytest.raises(ValueError, match="loopback"):
        RerankerClient()


def document(name, texts):
    return DocumentParseResponse(document_id=uuid4(), filename=name, document_type="pdf", saved_path=name,
        full_text="\n".join(texts), sections=[DocumentSection(index=i, text=t) for i, t in enumerate(texts, 1)])


@pytest.mark.asyncio
async def test_reranking_recovers_low_ranked_candidate_and_preserves_provenance(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_MODE", "local")
    monkeypatch.setenv("VECTOR_RAG_FINAL_K", "2")
    first = document("a.pdf", ["일반 설명", "중요한 실험 근거"])
    second = document("b.pdf", ["비교 실험 근거"])
    ranker = AsyncMock()
    # Round robin: a1, b1, a2. a2 must survive the final cutoff.
    ranker.rank.return_value = [2, 1, 0]
    rag = VectorRag(AsyncMock(), reranker=ranker)
    selected = await rag._rerank_contexts([first, second], "실험")
    assert [doc.document_id for doc in selected] == [first.document_id, second.document_id]
    assert selected[0].sections[0].index == 2
    assert selected[0].sections[0].text == "중요한 실험 근거"
    assert len(first.sections) == 2  # no source mutation


@pytest.mark.asyncio
async def test_rerank_failure_retains_original_fused_contexts():
    docs = [document("a.pdf", ["a", "b"])]
    ranker = AsyncMock()
    ranker.rank.side_effect = httpx.ReadTimeout("slow CPU")
    assert await VectorRag(AsyncMock(), reranker=ranker)._rerank_contexts(docs, "query") is docs


@pytest.mark.asyncio
async def test_disabled_reranking_never_calls_optional_server(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_MODE", "off")
    doc = document("a.pdf", ["실험 근거"])
    ranker = AsyncMock()
    rag = VectorRag(AsyncMock(), reranker=ranker)
    rag.search_hits = AsyncMock(return_value=[VectorSearchHit(doc.document_id, doc.filename, 1, doc.full_text, .1)])
    result = await rag.select_context([doc], "실험", uuid4())
    assert result is not None
    ranker.rank.assert_not_awaited()


@pytest.mark.asyncio
async def test_fused_reranking_keeps_original_page_and_document_in_final_context(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_MODE", "local")
    monkeypatch.setenv("VECTOR_RAG_FINAL_K", "1")
    doc = document("실험.pdf", ["프로젝트 소개"])
    def handler(request):
        texts = json.loads(request.content)["documents"]
        assert any("93%" in text for text in texts)
        return httpx.Response(200, json={"results": [
            {"index": i, "relevance_score": .99 if "93%" in text else .1}
            for i, text in enumerate(texts)]})
    rag = VectorRag(AsyncMock(), reranker=RerankerClient(httpx.MockTransport(handler)))
    rag.search_hits = AsyncMock(return_value=[
        VectorSearchHit(doc.document_id, doc.filename, 1, "프로젝트 소개", .1),
        VectorSearchHit(doc.document_id, doc.filename, 7, "실험 성공률은 93%입니다.", .3),
    ])
    selected = await rag.select_context([doc], "실험 성공률", uuid4())
    assert len(selected.sections) == 1
    assert selected.sections[0].source_document_id == doc.document_id
    assert selected.sections[0].index == 7
    assert "93%" in selected.full_text
    assert "실험.pdf / 구간 7" in selected.full_text
