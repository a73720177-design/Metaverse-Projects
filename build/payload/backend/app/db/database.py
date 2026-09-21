import os
from collections.abc import AsyncIterator
from pathlib import Path

from app import config as app_config  # noqa: F401 - backend/.env를 먼저 불러옵니다.
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError(
                "REPOSITORY_MODE=postgres requires the DATABASE_URL environment variable."
            )
        _engine = create_async_engine(
            normalize_database_url(database_url), pool_pre_ping=True, hide_parameters=True
        )
        _session_factory = async_sessionmaker(
            bind=_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from app.db import tables  # noqa: F401

    async with get_engine().begin() as connection:
        # ORM metadata includes vector(1024) even when retrieval is lexical.
        # create_all only creates missing tables; numbered migrations upgrade them.
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)


async def check_db() -> None:
    """Verify connectivity without reading or changing application data."""
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def inspect_db_contract(*, require_vector: bool = False) -> dict[str, object]:
    """Read-only validation of tables/columns required by Backend repositories."""

    from app.db import tables  # noqa: F401

    # ORM SELECTs include every mapped column, including embeddings in lexical
    # mode. A small hand-maintained subset can incorrectly report a broken DB OK.
    required_columns = {
        table.name: set(table.columns.keys())
        for table in Base.metadata.sorted_tables
    }

    async with get_engine().connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = ANY(CAST(:tables AS text[]))
                    """
                ),
                {"tables": list(required_columns)},
            )
        ).mappings().all()
        actual: dict[str, set[str]] = {}
        for row in rows:
            actual.setdefault(row["table_name"], set()).add(row["column_name"])

        vector_installed = bool(
            await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
        )
        migration_table_exists = bool(
            await connection.scalar(
                text("SELECT to_regclass(current_schema() || '.schema_migrations') IS NOT NULL")
            )
        )
        latest_migration = None
        applied_versions: set[str] = set()
        if migration_table_exists:
            applied_versions = set((await connection.execute(
                text("SELECT version FROM schema_migrations")
            )).scalars().all())
            latest_migration = max(applied_versions, default=None)
        embedding_type = await connection.scalar(text("""
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = 'document_chunks'
              AND a.attname = 'embedding' AND NOT a.attisdropped
        """))

    missing = {
        table: sorted(columns - actual.get(table, set()))
        for table, columns in required_columns.items()
        if columns - actual.get(table, set())
    }
    if not vector_installed:
        missing["extensions"] = ["vector"]
    if migration_table_exists:
        migration_dir = Path(__file__).resolve().parents[2] / "database"
        expected_versions = {
            path.name[:3] for path in migration_dir.glob("[0-9][0-9][0-9]_*.sql")
        }
        if unapplied := expected_versions - applied_versions:
            missing["migrations"] = sorted(unapplied)
    mismatched_types = {}
    if embedding_type is not None and embedding_type != "vector(1024)":
        mismatched_types["document_chunks.embedding"] = {
            "expected": "vector(1024)", "actual": embedding_type,
        }
    return {
        "status": "ok" if not missing and not mismatched_types else "mismatch",
        "latest_migration": latest_migration,
        "vector_extension": "installed" if vector_installed else "not_installed",
        "missing": missing,
        "mismatched_types": mismatched_types,
    }


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
