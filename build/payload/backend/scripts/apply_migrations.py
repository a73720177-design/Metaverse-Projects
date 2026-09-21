"""기존 운영·개발 PostgreSQL DB에 번호 migration을 안전하게 적용한다."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.setup_test_db import (
    DEFAULT_MIGRATIONS_DIR,
    DatabaseTarget,
    _asyncpg_url,
    apply_migrations,
    discover_migrations,
    plan_migrations,
)


def build_target(database_url: str) -> DatabaseTarget:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use a PostgreSQL URL.")
    if not parsed.hostname or (parsed.port is not None and parsed.port < 1):
        raise ValueError("DATABASE_URL must include a valid host and port.")
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
        description="Inspect numbered migrations read-only; use --apply to modify an existing database."
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply pending migrations after confirmation.")
    mode.add_argument("--dry-run", action="store_true", help="Read-only migration plan (the default).")
    parser.add_argument("--confirm-database", help="Exact database name required with --apply.")
    parser.add_argument("--allow-untracked-schema", action="store_true", help="Allow replay against a reviewed/backed-up schema without migration history.")
    return parser


async def run(
    database_url: str, migrations_dir: Path, *, apply: bool = False,
    confirm_database: str | None = None, allow_untracked_schema: bool = False,
) -> tuple[str, list[str], bool]:
    target = build_target(database_url)
    if apply and confirm_database != target.database_name:
        raise ValueError("--apply requires --confirm-database with the exact target database name.")
    migrations = discover_migrations(migrations_dir)
    if apply:
        applied = await apply_migrations(target, migrations, allow_untracked_schema=allow_untracked_schema)
        return target.database_name, applied, False
    plan = await plan_migrations(target, migrations)
    return target.database_name, [m.filename for m in plan["pending"]], plan["untracked_schema"]


def main() -> int:
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    args = build_parser().parse_args()
    if not args.database_url:
        raise SystemExit("Migration failed: DATABASE_URL is required.")
    try:
        database_name, applied, untracked_schema = asyncio.run(
            run(
                args.database_url, args.migrations_dir, apply=args.apply,
                confirm_database=args.confirm_database,
                allow_untracked_schema=args.allow_untracked_schema,
            )
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Migration failed: {exc}") from exc
    except Exception as exc:
        # Driver exceptions can contain credentials, URLs or source data.
        raise SystemExit(
            f"Migration failed ({type(exc).__name__}). Check connectivity, permissions and DB logs."
        ) from None

    print(f"Database: {database_name}")
    if not args.apply:
        print("Read-only plan. No schema or data was changed.")
    if untracked_schema:
        print("Warning: existing application tables have no migration history; review and back up before replay.")
    if not applied:
        print("All migrations are already applied and checksums match.")
    for filename in applied:
        print(f"{'Applied' if args.apply else 'Pending'} migration: {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
