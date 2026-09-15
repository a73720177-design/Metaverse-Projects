import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.document import DocumentParseResponse, DocumentSection
from app.repositories.document_repository import PostgresDocumentRepository
from app.services.rag_service import DocumentContextSelector, fuse_chunk_rankings


def document(body="매출 성장률은 25퍼센트입니다."):
    return DocumentParseResponse(
        filename="slides.pdf", document_type="pdf", saved_path=Path("slides.pdf"),
        sections=[DocumentSection(index=3, text=body)], full_text=body,
    )


def test_bm25_reuses_features_and_invalidates_on_edit_and_eviction(monkeypatch):
    selector = DocumentContextSelector(cache_size=1)
    original = document()
    features = MagicMock(wraps=selector._features)
    monkeypatch.setattr(selector, "_features", features)
    first = selector.select(original, "성장률")
    features.reset_mock()
    assert selector.select(original, "성장률") == first
    assert features.call_args_list == [(("성장률",),)]

    changed = original.model_copy(update={
        "sections": [DocumentSection(index=4, text="기술특허 등록 완료")],
    })
    assert selector.select(changed, "성장률") is None
    assert selector.select(changed, "기술특허").sections[0].index == 4
    other = document("시장규모 증가")
    selector.select(other, "시장규모")
    assert set(selector._term_cache) == {other.document_id}


def test_rrf_promotes_shared_evidence_without_duplicate_votes():
    semantic = DocumentSection(index=1, text="의미 검색 근거")
    lexical = DocumentSection(index=2, text="키워드 검색 근거")
    shared = DocumentSection(index=3, text="공통 근거")
    assert fuse_chunk_rankings(
        [semantic, shared, shared], [lexical, shared]
    ) == [shared, semantic, lexical]


@pytest.mark.asyncio
async def test_postgres_retrieval_loads_metadata_and_candidates_in_one_query(monkeypatch):
    import app.repositories.document_repository as module

    owner, first, second = uuid4(), uuid4(), uuid4()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {"document_id": first, "filename": "one.pdf", "document_type": "pdf",
         "object_key": "one.pdf", "chunk_index": 8, "content": "ZX729 해지수수료 75000원"},
        {"document_id": second, "filename": "two.pdf", "document_type": "pdf",
         "object_key": "two.pdf", "chunk_index": None, "content": None},
    ]
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = result
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    records = await PostgresDocumentRepository().get_for_retrieval(
        [second, first], owner, "ZX729 해지수수료는?"
    )
    assert [item.document_id for item in records] == [second, first]
    assert all(item.full_text == "" for item in records)
    assert records[0].sections == []  # still available for semantic search
    assert records[1].sections[0].index == 8
    statement, params = session.execute.call_args.args
    assert "full_text" not in str(statement)
    assert "d.owner_id = :owner" in str(statement)
    assert params["owner"] == owner
    assert "%zx729%" in params["patterns"]
    assert "%해지%" in params["patterns"]
    assert params["limit"] > 0
    assert session.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("greeting", [False, True])
async def test_chat_uses_retrieval_contract_and_rejects_missing_permissions(monkeypatch, greeting):
    from app.models.chat import ChatRequest
    from app.models.persona import PersonaProfile
    from app.repositories.agent_repository import InMemoryAgentRepository
    from app.repositories.chat_repository import InMemoryChatRepository
    from app.services.chat_service import ChatResourceNotFoundError, ChatService

    monkeypatch.setenv("RAG_MODE", "lexical")
    owner = uuid4()
    persona = PersonaProfile(agent_id=uuid4(), name="평가자")
    agents = InMemoryAgentRepository()
    await agents.save(persona, owner)
    record = document()
    repository = AsyncMock()
    repository.get.side_effect = AssertionError("Full-document fetch is forbidden")
    repository.get_for_retrieval.return_value = [record]
    service = ChatService(AsyncMock(), agents, repository, InMemoryChatRepository())
    query = "안녕하세요" if greeting else "성장률은?"
    await service._resolve_context(persona.agent_id, ChatRequest(
        message=query, document_ids=[record.document_id],
    ), owner)
    repository.get_for_retrieval.assert_awaited_once_with(
        [record.document_id], owner, "" if greeting else query
    )
    with pytest.raises(ChatResourceNotFoundError):
        await service._resolve_context(persona.agent_id, ChatRequest(
            message=query, document_ids=[record.document_id, uuid4()],
        ), owner)


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
async def test_postgres_candidate_query_owner_isolation_korean_and_limits(monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.db.database import normalize_database_url
    import app.repositories.document_repository as module

    engine = create_async_engine(normalize_database_url(os.environ["TEST_DATABASE_URL"]))
    owner, stranger = uuid4(), uuid4()
    requested, private, unrequested, semantic_only = [uuid4() for _ in range(4)]
    monkeypatch.setenv("VECTOR_RAG_CANDIDATE_K", "2")
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("""
                    CREATE TEMP TABLE documents (
                        document_id uuid PRIMARY KEY, owner_id uuid, filename text,
                        document_type text, full_text text
                    ) ON COMMIT DROP
                """))
                await connection.execute(text("""
                    CREATE TEMP TABLE document_files (
                        document_id uuid PRIMARY KEY, object_key text
                    ) ON COMMIT DROP
                """))
                await connection.execute(text("""
                    CREATE TEMP TABLE document_chunks (
                        document_id uuid, chunk_index integer, content text
                    ) ON COMMIT DROP
                """))
                for identifier, document_owner in (
                    (requested, owner), (private, stranger),
                    (unrequested, owner), (semantic_only, owner),
                ):
                    await connection.execute(text("""
                        INSERT INTO documents VALUES (:id, :owner, 'test.pdf', 'pdf', 'FULL BODY')
                    """), {"id": identifier, "owner": document_owner})
                    await connection.execute(text("""
                        INSERT INTO document_files VALUES (:id, 'test.pdf')
                    """), {"id": identifier})
                    for index in range(1, 5):
                        await connection.execute(text("""
                            INSERT INTO document_chunks VALUES (:id, :index, :content)
                        """), {"id": identifier, "index": index, "content": (
                            "unrelated" if identifier == semantic_only else
                            "해지수수료 ZX729는 75000원" if index == 4 else "해지 안내"
                        )})
                monkeypatch.setattr(module, "get_session_factory",
                                    lambda: lambda: AsyncSession(bind=connection))
                repository = PostgresDocumentRepository()
                records = await repository.get_for_retrieval(
                    [requested, private, semantic_only], owner, "해지수수료 ZX729"
                )
                assert [item.document_id for item in records] == [requested, semantic_only]
                assert len(records[0].sections) == 2
                assert any(section.index == 4 for section in records[0].sections)
                assert all(item.full_text == "" for item in records)
                assert records[1].sections == []
                greeting = await repository.get_for_retrieval([requested], owner, "")
                assert greeting[0].sections == []
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
