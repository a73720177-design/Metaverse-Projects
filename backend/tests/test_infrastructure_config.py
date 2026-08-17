import pytest

from app.config import get_max_upload_size_bytes, get_object_storage_mode, get_repository_mode
from app.db.database import normalize_database_url


def test_default_infrastructure_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPOSITORY_MODE", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_MODE", raising=False)
    assert get_repository_mode() == "memory"
    assert get_object_storage_mode() == "local"


def test_postgres_url_is_normalized_for_asyncpg() -> None:
    assert normalize_database_url("postgresql://user:pw@localhost/db") == (
        "postgresql+asyncpg://user:pw@localhost/db"
    )


def test_invalid_repository_mode_fails_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOSITORY_MODE", "unknown")
    with pytest.raises(RuntimeError, match="REPOSITORY_MODE"):
        get_repository_mode()


def test_upload_limit_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "10")
    assert get_max_upload_size_bytes() == 10 * 1024 * 1024
