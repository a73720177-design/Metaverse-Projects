import json
import os
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
    assert {section.source_document_id for section in selected.sections} == {
        first.document_id, second.document_id,
    }
    assert any(section.index == 2 and section.source_document_id == first.document_id
               for section in selected.sections)
    assert any(section.index == 4 and section.source_document_id == second.document_id
               for section in selected.sections)
    assert "presentation.pdf" in selected.full_text
    assert "investor.pdf" in selected.full_text
    assert all(section.source_document_type == "pdf" for section in selected.sections)


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
    assert "WHERE distance <= :max_distance" in str(statement)
    assert params["max_distance"] > 0
    assert params["owner"] == owner
    assert params["ids"] == [document.document_id for document in documents]


@pytest.mark.asyncio
async def test_vector_context_keeps_second_file_when_first_has_long_hits(monkeypatch) -> None:
    monkeypatch.setenv("RAG_MAX_CONTEXT_CHARS", "4000")
    first = _document("first.pdf", "a" * 6000)
    second = _document("second.pdf", "b" * 3000)
    service = VectorRag(AsyncMock())
    service.search_hits = AsyncMock(return_value=[
        VectorSearchHit(first.document_id, first.filename, 1, "a" * 3000, 0.1),
        VectorSearchHit(first.document_id, first.filename, 2, "a" * 3000, 0.11),
        VectorSearchHit(second.document_id, second.filename, 4, "b" * 3000, 0.2),
    ])

    selected = await service.select_context([first, second], "compare", uuid4())

    assert selected is not None
    assert len(selected.full_text) <= 4000
    assert {section.source_document_id for section in selected.sections} == {
        first.document_id, second.document_id,
    }
    assert next(section for section in selected.sections
                if section.source_document_id == second.document_id).text == "b" * 700


@pytest.mark.asyncio
async def test_vector_context_includes_unindexed_file_using_lexical_context() -> None:
    indexed = _document("indexed.pdf", "indexed evidence")
    unindexed = _document("unindexed.pdf", "unindexed evidence")
    service = VectorRag(AsyncMock())
    service.search_hits = AsyncMock(return_value=[
        VectorSearchHit(indexed.document_id, indexed.filename, 1, indexed.full_text, 0.1),
    ])

    selected = await service.select_context([indexed, unindexed], "evidence", uuid4())

    assert selected is not None
    assert "unindexed evidence" in selected.full_text
    assert {section.source_document_id for section in selected.sections} == {
        indexed.document_id, unindexed.document_id,
    }


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


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
async def test_postgres_vector_search_diversifies_hits_and_excludes_other_sources(monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.db.database import normalize_database_url
    import app.services.vector_rag as module

    engine = create_async_engine(normalize_database_url(os.environ["TEST_DATABASE_URL"]))
    monkeypatch.setenv("VECTOR_RAG_FINAL_K", "12")
    owner, other_owner = uuid4(), uuid4()
    first, second, private, unrequested = [
        _document(name, name) for name in ("first.pdf", "second.pdf", "private.pdf", "unrequested.pdf")
    ]
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                # Session-local tables shadow production names and are always rolled back.
                await connection.execute(text("""
                    CREATE TEMP TABLE documents (
                        document_id uuid PRIMARY KEY, owner_id uuid, filename text
                    ) ON COMMIT DROP
                """))
                await connection.execute(text("""
                    CREATE TEMP TABLE document_chunks (
                        chunk_id uuid PRIMARY KEY, document_id uuid, chunk_index integer,
                        content text, embedding vector(3), embedding_model text, content_hash text
                    ) ON COMMIT DROP
                """))
                for document, document_owner, count, vector in (
                    (first, owner, 15, "[1,0,0]"),
                    (second, owner, 1, "[0.8,0.2,0]"),
                    (private, other_owner, 1, "[1,0,0]"),
                    (unrequested, owner, 1, "[1,0,0]"),
                ):
                    await connection.execute(text(
                        "INSERT INTO documents VALUES (:id, :owner, :filename)"
                    ), {"id": document.document_id, "owner": document_owner, "filename": document.filename})
                    for index in range(1, count + 1):
                        await connection.execute(text("""
                            INSERT INTO document_chunks VALUES (
                                :chunk, :document, :index, 'evidence', CAST(:vector AS vector),
                                'test-model', encode(sha256(convert_to('evidence', 'UTF8')), 'hex')
                            )
                        """), {"chunk": uuid4(), "document": document.document_id,
                               "index": index, "vector": vector})
                monkeypatch.setattr(module, "get_session_factory", lambda: lambda: AsyncSession(bind=connection))
                client = AsyncMock()
                client.model = "test-model"
                client.embed.return_value = [[1.0, 0.0, 0.0]]
                hits = await VectorRag(client).search_hits([first, second, private], "compare", owner)
                assert len(hits) == 12
                assert {hit.document_id for hit in hits[:2]} == {first.document_id, second.document_id}
                assert {hit.document_id for hit in hits} == {first.document_id, second.document_id}
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_vector_search_filters_weak_hits_and_applies_final_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.vector_rag as module

    monkeypatch.setenv("VECTOR_RAG_MAX_DISTANCE", "0.4")
    monkeypatch.setenv("VECTOR_RAG_FINAL_K", "2")
    owner = uuid4()
    document = _document("slides.pdf", "근거")
    rows = [
        {
            "document_id": document.document_id,
            "filename": document.filename,
            "chunk_index": index,
            "content": f"근거 {index}",
            "distance": distance,
        }
        for index, distance in [(1, 0.1), (2, 0.2), (3, 0.3), (4, 0.8)]
    ]
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute.return_value = result
    session.__aenter__.return_value = session
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    client = AsyncMock()
    client.model = "bge-m3:latest"
    client.embed.return_value = [[1.0] * 1024]

    hits = await VectorRag(client).search_hits([document], "근거", owner)

    assert [hit.chunk_index for hit in hits] == [1, 2]


@pytest.mark.asyncio
async def test_vector_context_recovers_evidence_at_end_of_long_page(monkeypatch) -> None:
    monkeypatch.setenv("RAG_MAX_CONTEXT_CHARS", "1000")
    body = "일반적인 프로젝트 소개입니다.\n" * 500 + "해지수수료는 75000원입니다."
    document = _document("contract.pdf", body)
    service = VectorRag(AsyncMock())
    service.search_hits = AsyncMock(return_value=[
        VectorSearchHit(document.document_id, document.filename, 7, body, 0.1),
    ])
    selected = await service.select_context([document], "해지수수료는?", uuid4())
    assert "75000원" in selected.full_text
    assert len(selected.full_text) <= 1000
    assert selected.sections[0].index == 7


@pytest.mark.asyncio
async def test_vector_context_recovers_exact_term_in_already_matched_file() -> None:
    document = _document("contract.pdf", "계약 조건 안내.\n위약금코드 ZX729 금액은 75000원.")
    service = VectorRag(AsyncMock())
    service.search_hits = AsyncMock(return_value=[
        VectorSearchHit(document.document_id, document.filename, 2, "해약 비용에 관한 일반 안내. " * 500, 0.1),
    ])
    selected = await service.select_context([document], "ZX729", uuid4())
    assert "ZX729" in selected.full_text
    assert "해약 비용" in selected.full_text
