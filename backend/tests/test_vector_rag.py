import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.document import DocumentParseResponse, DocumentSection
from app.models.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.vector_rag import EmbeddingClient, VectorRag, index_after_save


@pytest.mark.asyncio
async def test_search_query_enforces_owner_and_allowed_ids(monkeypatch):
    from unittest.mock import MagicMock
    import app.services.vector_rag as module
    owner = uuid4()
    document = DocumentParseResponse(document_id=uuid4(), filename="test.pdf", document_type="pdf",
        saved_path=Path("test.pdf"), sections=[], full_text="자료")
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    session.__aenter__.return_value = session
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    client = AsyncMock()
    client.model = "bge-m3:latest"
    client.embed.return_value = [[1.0] * 1024]
    assert await VectorRag(client).search([document], "질문", owner) is None
    statement, params = session.execute.call_args.args
    assert "d.owner_id=:owner" in str(statement)
    assert "c.document_id=ANY" in str(statement)
    assert params["owner"] == owner
    assert params["ids"] == [document.document_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[[1.0] * 1024], [[1.0] * 768], [], [[0.0] * 1024]])
async def test_embedding_validation(vectors):
    def handle(request):
        payload = json.loads(request.content)
        assert payload["truncate"] is False
        assert payload["input"] == ["한국어 자료"]
        return httpx.Response(200, json={"embeddings": vectors})
    client = EmbeddingClient(httpx.MockTransport(handle))
    if vectors and len(vectors[0]) == 1024 and any(vectors[0]):
        assert await client.embed(["한국어 자료"]) == vectors
    else:
        with pytest.raises(ValueError):
            await client.embed(["한국어 자료"])


@pytest.mark.asyncio
async def test_upload_index_failure_is_recoverable(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "vector")
    monkeypatch.setattr(VectorRag, "index_document", AsyncMock(side_effect=RuntimeError("offline")))
    await index_after_save(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_vector_failure_falls_back_and_receives_only_owned_documents(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "vector")
    owner, agent, doc_id, inaccessible = uuid4(), uuid4(), uuid4(), uuid4()
    document = DocumentParseResponse(document_id=doc_id, filename="test.pdf", document_type="pdf",
        saved_path=Path("test.pdf"), sections=[DocumentSection(index=1, text="한국어 검색 자료")],
        full_text="한국어 검색 자료")
    from app.models.persona import PersonaProfile
    persona = PersonaProfile(agent_id=agent, name="Test", description="Test", document_ids=[doc_id, inaccessible])
    agents = AsyncMock()
    agents.get.return_value = persona
    documents = AsyncMock()
    documents.get.side_effect = [document, None]
    search = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(VectorRag, "search", search)
    service = ChatService(AsyncMock(), agents, documents, AsyncMock())
    _, _, result = await service._resolve_context(agent, ChatRequest(message="한국어 검색"), owner)
    assert result.document_id == doc_id
    assert "한국어" in result.full_text
    search.assert_awaited_once_with([document], "한국어 검색", owner)


@pytest.mark.asyncio
async def test_vector_result_sets_actual_source_document(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "vector")
    owner, agent = uuid4(), uuid4()
    docs = [DocumentParseResponse(document_id=uuid4(), filename="test.pdf", document_type="pdf",
        saved_path=Path("test.pdf"), sections=[DocumentSection(index=1, text=value)], full_text=value)
        for value in ["질문 키워드", "의미로 찾은 자료"]]
    from app.models.persona import PersonaProfile
    agents, documents = AsyncMock(), AsyncMock()
    agents.get.return_value = PersonaProfile(agent_id=agent, name="Test", description="Test",
        document_ids=[d.document_id for d in docs])
    documents.get.side_effect = docs
    monkeypatch.setattr(VectorRag, "search", AsyncMock(return_value=docs[1]))
    service = ChatService(AsyncMock(), agents, documents, AsyncMock())
    _, request, result = await service._resolve_context(agent, ChatRequest(message="질문 키워드"), owner)
    assert request.document_id == result.document_id == docs[1].document_id
