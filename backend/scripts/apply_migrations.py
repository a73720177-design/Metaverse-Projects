"""기존 운영·개발 PostgreSQL DB에 번호 migration을 안전하게 적용한다."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.setup_test_db import (
    DEFAULT_MIGRATIONS_DIR,
    DatabaseTarget,
    _asyncpg_url,
    apply_migrations,
    discover_migrations,
)


def build_target(database_url: str) -> DatabaseTarget:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use a PostgreSQL URL.")
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name or "/" in database_name:
        raise ValueError("DATABASE_URL must include one database name.")
    if database_name.lower() in {"postgres", "template0", "template1"}:
        raise ValueError("Refusing to apply application migrations to an admin database.")
    return DatabaseTarget(
        database_name=database_name,
        database_url=_asyncpg_url(database_url),
        admin_url="",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply backend/database numbered migrations to an existing database."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Existing PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
    )
    return parser


async def run(database_url: str, migrations_dir: Path) -> tuple[str, list[str]]:
    target = build_target(database_url)
    migrations = discover_migrations(migrations_dir)
    applied = await apply_migrations(target, migrations)
    return target.database_name, applied


def main() -> int:
    args = build_parser().parse_args()
    if not args.database_url:
        raise SystemExit("Migration failed: DATABASE_URL is required.")
    try:
        database_name, applied = asyncio.run(
            run(args.database_url, args.migrations_dir)
        )
    except Exception as exc:
        raise SystemExit(f"Migration failed: {exc}") from exc

    print(f"Database: {database_name}")
    if not applied:
        print("All migrations are already applied and checksums match.")
    for filename in applied:
        print(f"Applied migration: {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
