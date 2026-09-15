from pathlib import Path

import pytest

from scripts.setup_test_db import (
    DEFAULT_MIGRATIONS_DIR, discover_migrations, parse_database_target, pending_migrations,
)
from scripts.migrate_db import application_target, validate_selected_versions


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


def test_legacy_007_checksum_is_preserved_and_chat_timing_has_a_new_version() -> None:
    migrations = {migration.version: migration for migration in discover_migrations(DEFAULT_MIGRATIONS_DIR)}
    legacy = migrations["007"]
    assert legacy.filename == "007_add_agent_all_dc.sql"
    assert legacy.checksum == "addf8e07d52c94f726115dc39ec2ff91cb4a3195ef6535167f2b072c8f6240d9"
    assert migrations["011"].filename == "011_add_chat_timing.sql"
    assert migrations["012"].filename == "012_add_chat_conversation.sql"


def test_pending_migrations_rejects_conflicting_history_before_returning_work() -> None:
    migrations = discover_migrations(DEFAULT_MIGRATIONS_DIR)
    with pytest.raises(RuntimeError, match="No migrations were applied"):
        pending_migrations(migrations, [{
            "version": "007", "filename": "007_add_chat_timing.sql", "checksum": "0" * 64,
        }])


def test_pending_migrations_retains_matching_history() -> None:
    migrations = discover_migrations(DEFAULT_MIGRATIONS_DIR)
    legacy = next(migration for migration in migrations if migration.version == "007")
    pending = pending_migrations(migrations, [{
        "version": legacy.version, "filename": legacy.filename, "checksum": legacy.checksum,
    }])
    assert legacy not in pending
    assert len(pending) == len(migrations) - 1


def test_application_migrations_require_matching_database_name() -> None:
    with pytest.raises(ValueError, match="does not match"):
        application_target("postgresql://localhost/qwendb", "wrong_database")
    target = application_target("postgresql+asyncpg://localhost/qwendb", "qwendb")
    assert target.database_url == "postgresql://localhost/qwendb"


def test_selected_application_migration_requires_known_three_digit_version() -> None:
    migrations = discover_migrations(DEFAULT_MIGRATIONS_DIR)

    assert validate_selected_versions(migrations, ["008"]) == {"008"}
    with pytest.raises(ValueError, match="three digits"):
        validate_selected_versions(migrations, ["8"])
    with pytest.raises(ValueError, match="Unknown migration version"):
        validate_selected_versions(migrations, ["999"])

