from pathlib import Path

import pytest

from scripts.apply_migrations import build_target, build_parser, run
import asyncio


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


def test_default_mode_does_not_apply():
    assert build_parser().parse_args([]).apply is False


def test_apply_requires_exact_database_confirmation_before_connecting(tmp_path):
    with pytest.raises(ValueError, match="exact target"):
        asyncio.run(run('postgresql://localhost/project', tmp_path, apply=True, confirm_database='other'))
