from pathlib import Path

import pytest

from scripts.setup_test_db import discover_migrations, parse_database_target


def test_parse_database_target_builds_default_admin_url() -> None:
    target = parse_database_target(
        "postgresql+asyncpg://dbuser:secret@localhost:5432/qwendb_test"
    )

    assert target.database_name == "qwendb_test"
    assert target.database_url == "postgresql://dbuser:secret@localhost:5432/qwendb_test"
    assert target.admin_url == "postgresql://dbuser:secret@localhost:5432/postgres"


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://localhost/qwendb",
        "postgresql://localhost/production",
        "sqlite:///qwendb_test.db",
    ],
)
def test_parse_database_target_rejects_unsafe_database(database_url: str) -> None:
    with pytest.raises(ValueError):
        parse_database_target(database_url)


def test_discover_migrations_orders_files_and_calculates_checksum(
    tmp_path: Path,
) -> None:
    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "notes.sql").write_text("ignored", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == ["001", "002"]
    assert [migration.filename for migration in migrations] == [
        "001_first.sql",
        "002_second.sql",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_discover_migrations_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_again.sql").write_text("SELECT 2;", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate migration version"):
        discover_migrations(tmp_path)

