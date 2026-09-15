from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from scripts import audit_db
from app.repositories import document_repository as repository


def test_audit_without_configuration_is_explicit(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["audit_db.py"])
    assert audit_db.main() == 2
    assert '"status": "unconfigured"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_audit_does_not_query_data_when_schema_is_incomplete(monkeypatch):
    monkeypatch.setattr(audit_db, "inspect_db_contract", AsyncMock(return_value={
        "status": "mismatch", "missing": {"document_chunks": ["embedding"]},
    }))
    close = AsyncMock()
    monkeypatch.setattr(audit_db, "close_db", close)
    engine = MagicMock(side_effect=AssertionError("must not query invalid schema"))
    monkeypatch.setattr(audit_db, "get_engine", engine)
    assert (await audit_db.audit())["status"] == "mismatch"
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_read_stops_before_loading_other_owners_chunks(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = None
    monkeypatch.setattr(repository, "get_session_factory", lambda: lambda: session)
    assert await repository.PostgresDocumentRepository().get(uuid4(), uuid4()) is None
    session.get.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_read_only_fetches_section_fields(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    document_id = uuid4()
    session.scalar.return_value = MagicMock(
        document_id=document_id, filename="test.pdf", document_type="pdf", full_text="본문",
    )
    session.get.return_value = MagicMock(object_key="test.pdf")
    rows = MagicMock()
    rows.all.return_value = [MagicMock(chunk_index=1, content="본문")]
    session.execute.return_value = rows
    monkeypatch.setattr(repository, "get_session_factory", lambda: lambda: session)
    document = await repository.PostgresDocumentRepository().get(document_id, uuid4())
    assert document.sections[0].text == "본문"
    statement = session.execute.call_args.args[0]
    assert set(statement.selected_columns.keys()) == {"chunk_index", "content"}
