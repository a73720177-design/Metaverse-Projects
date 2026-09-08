import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from app.models.document import DocumentParseResponse, DocumentSection
from app.services.vector_rag import (
    EmbeddingClient,
    VectorRag,
    VectorSearchHit,
    index_after_save,
)


def _document(filename: str, text: str) -> DocumentParseResponse:
    return DocumentParseResponse(
        document_id=uuid4(),
        filename=filename,
        document_type="pdf",
        saved_path=Path(filename),
        sections=[DocumentSection(index=1, text=text)],
        full_text=text,
    )


@pytest.mark.asyncio
async def test_embedding_client_validates_bge_m3_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1024")

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "bge-m3:latest"
        assert payload["truncate"] is True
        return httpx.Response(200, json={"embeddings": [[1.0] * 1024]})

    result = await EmbeddingClient(httpx.MockTransport(handle)).embed(["한국어 발표 자료"])

    assert len(result[0]) == 1024


@pytest.mark.asyncio
async def test_vector_context_keeps_hits_from_multiple_documents() -> None:
    first = _document("presentation.pdf", "시장 규모")
    second = _document("investor.pdf", "투자 기준")
    service = VectorRag(AsyncMock())
    service.search_hits = AsyncMock(
        return_value=[
            VectorSearchHit(first.document_id, first.filename, 2, "시장 규모는 성장 중", 0.1),
            VectorSearchHit(second.document_id, second.filename, 4, "회수 기간을 검증", 0.2),
        ]
    )

    selected = await service.select_context([first, second], "시장성과 투자성", uuid4())

    assert selected is not None
    assert [section.source_document_id for section in selected.sections] == [
        first.document_id,
        second.document_id,
    ]
    assert "presentation.pdf" in selected.full_text
    assert "investor.pdf" in selected.full_text


@pytest.mark.asyncio
async def test_vector_search_limits_query_to_owner_and_requested_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.vector_rag as module

    owner = uuid4()
    documents = [_document("one.pdf", "하나"), _document("two.pdf", "둘")]
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    session.__aenter__.return_value = session
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    client = AsyncMock()
    client.model = "bge-m3:latest"
    client.embed.return_value = [[1.0] * 1024]

    assert await VectorRag(client).search_hits(documents, "질문", owner) == []

    statement, params = session.execute.call_args.args
    assert "d.owner_id = :owner" in str(statement)
    assert "c.document_id = ANY" in str(statement)
    assert params["owner"] == owner
    assert params["ids"] == [document.document_id for document in documents]


@pytest.mark.asyncio
async def test_index_failure_does_not_fail_document_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MODE", "vector")
    monkeypatch.setattr(
        VectorRag,
        "index_document",
        AsyncMock(side_effect=RuntimeError("embedding service offline")),
    )

    await index_after_save(uuid4(), uuid4())
