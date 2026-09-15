import pytest
from uuid import UUID

from app.config import (
    get_jwt_access_token_expire_minutes,
    get_jwt_secret_key,
    get_max_upload_size_bytes,
    get_object_storage_mode,
    get_rag_max_context_chars,
    get_rag_mode,
    get_repository_mode,
    validate_runtime_contract,
)
from app.controllers.document_controller import build_document_object_key
from app.dependencies import get_user_repository
from app.db.database import normalize_database_url
from app.db.tables import (
    AgentTable,
    DocumentChunkTable,
    DocumentFileTable,
    DocumentTable,
    ReviewTable,
    UserTable,
)
from app.repositories.user_repository import InMemoryUserRepository, PostgresUserRepository


def test_default_infrastructure_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPOSITORY_MODE", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_MODE", raising=False)
    monkeypatch.delenv("RAG_MODE", raising=False)
    assert get_repository_mode() == "postgres"
    assert get_rag_mode() == "vector"
    assert get_object_storage_mode() == "local"


def test_default_vector_runtime_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPOSITORY_MODE", raising=False)
    monkeypatch.delenv("RAG_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://qwen:pw@localhost/qwendb")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1024")
    monkeypatch.setenv("DB_AUTO_CREATE", "false")
    validate_runtime_contract()


def test_memory_lexical_mode_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOSITORY_MODE", "memory")
    monkeypatch.setenv("RAG_MODE", "lexical")
    assert get_repository_mode() == "memory"
    assert get_rag_mode() == "lexical"
    validate_runtime_contract()


def test_postgres_url_is_normalized_for_asyncpg() -> None:
    assert normalize_database_url("postgresql://user:pw@localhost/db") == (
        "postgresql+asyncpg://user:pw@localhost/db"
    )


def test_invalid_repository_mode_fails_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOSITORY_MODE", "unknown")
    with pytest.raises(RuntimeError, match="REPOSITORY_MODE"):
        get_repository_mode()


def test_vector_rag_requires_postgres_and_migration_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MODE", "vector")
    monkeypatch.setenv("REPOSITORY_MODE", "memory")
    with pytest.raises(RuntimeError, match="REPOSITORY_MODE=postgres"):
        validate_runtime_contract()

    monkeypatch.setenv("REPOSITORY_MODE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://qwen:pw@localhost/qwendb")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    with pytest.raises(RuntimeError, match="EMBEDDING_DIMENSION=1024"):
        validate_runtime_contract()


def test_postgres_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOSITORY_MODE", "postgres")
    monkeypatch.setenv("RAG_MODE", "lexical")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_runtime_contract()


def test_upload_limit_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "10")
    assert get_max_upload_size_bytes() == 10 * 1024 * 1024


def test_rag_context_limit_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_MAX_CONTEXT_CHARS", "2048")
    assert get_rag_max_context_chars() == 2048

    monkeypatch.setenv("RAG_MAX_CONTEXT_CHARS", "0")
    with pytest.raises(RuntimeError, match="RAG_MAX_CONTEXT_CHARS"):
        get_rag_max_context_chars()


def test_document_storage_schema_is_split() -> None:
    assert set(DocumentTable.__table__.columns.keys()) == {
        "document_id",
        "owner_id",
        "filename",
        "document_type",
        "full_text",
        "created_at",
    }
    assert {"bucket", "object_key", "content_type"}.issubset(
        DocumentFileTable.__table__.columns.keys()
    )
    assert {"chunk_index", "content", "metadata"}.issubset(
        DocumentChunkTable.__table__.columns.keys()
    )


def test_original_document_object_key_contract() -> None:
    document_id = UUID("12345678-1234-5678-1234-567812345678")
    assert build_document_object_key(document_id, ".PDF") == (
        "12345678-1234-5678-1234-567812345678/original.pdf"
    )


def test_user_schema_contains_auth_fields() -> None:
    assert set(UserTable.__table__.columns.keys()) == {
        "user_id",
        "username",
        "password_hash",
        "created_at",
    }


def test_resource_tables_contain_owner_id() -> None:
    assert "owner_id" in AgentTable.__table__.columns
    assert "owner_id" in DocumentTable.__table__.columns
    assert "owner_id" in ReviewTable.__table__.columns


def test_jwt_settings_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    assert get_jwt_secret_key() == "x" * 32
    assert get_jwt_access_token_expire_minutes() == 30

    monkeypatch.setenv("JWT_SECRET_KEY", "too-short")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        get_jwt_secret_key()


def test_user_repository_follows_repository_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        monkeypatch.setenv("REPOSITORY_MODE", "memory")
        get_user_repository.cache_clear()
        assert isinstance(get_user_repository(), InMemoryUserRepository)

        monkeypatch.setenv("REPOSITORY_MODE", "postgres")
        get_user_repository.cache_clear()
        assert isinstance(get_user_repository(), PostgresUserRepository)
    finally:
        get_user_repository.cache_clear()
