from pathlib import Path

import pytest

from scripts.apply_migrations import build_target


def test_build_target_accepts_existing_application_database() -> None:
    target = build_target(
        "postgresql+asyncpg://qwen:password@localhost:5432/qwendb"
    )
    assert target.database_name == "qwendb"
    assert target.database_url.startswith("postgresql://")


@pytest.mark.parametrize("name", ["postgres", "template0", "template1"])
def test_build_target_rejects_admin_databases(name: str) -> None:
    with pytest.raises(ValueError, match="admin database"):
        build_target(f"postgresql://qwen:password@localhost:5432/{name}")


def test_build_target_rejects_non_postgres_url() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        build_target("sqlite:///local.db")
