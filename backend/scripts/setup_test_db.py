from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_.+\.sql$")
TEST_DATABASE_PATTERN = re.compile(r"(?:^test(?:_|$)|(?:^|_)test$|_test_)")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database"


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    checksum: str
    sql: str


@dataclass(frozen=True)
class DatabaseTarget:
    database_name: str
    database_url: str
    admin_url: str


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def parse_database_target(
    database_url: str, admin_url: str | None = None
) -> DatabaseTarget:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("TEST_DATABASE_URL must use a PostgreSQL URL.")

    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name or "/" in database_name:
        raise ValueError("TEST_DATABASE_URL must include one database name.")
    if not TEST_DATABASE_PATTERN.search(database_name.lower()):
        raise ValueError(
            "Refusing to modify a database whose name is not clearly for tests "
            "(for example, qwendb_test)."
        )

    if admin_url:
        parsed_admin = urlsplit(admin_url)
        if parsed_admin.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError("TEST_DATABASE_ADMIN_URL must use a PostgreSQL URL.")
        resolved_admin_url = _asyncpg_url(admin_url)
    else:
        admin_scheme = (
            "postgresql" if parsed.scheme == "postgresql+asyncpg" else parsed.scheme
        )
        resolved_admin_url = urlunsplit(
            (
                admin_scheme,
                parsed.netloc,
                "/postgres",
                parsed.query,
                parsed.fragment,
            )
        )

    return DatabaseTarget(
        database_name=database_name,
        database_url=_asyncpg_url(database_url),
        admin_url=resolved_admin_url,
    )


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.is_dir():
        raise ValueError(f"Migration directory does not exist: {migrations_dir}")

    migrations: list[Migration] = []
    versions: set[str] = set()
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        version = match.group("version")
        if version in versions:
            raise ValueError(f"Duplicate migration version: {version}")
        versions.add(version)
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )

    if not migrations:
        raise ValueError(f"No numbered SQL migrations found in: {migrations_dir}")
    return migrations


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def create_database_if_missing(target: DatabaseTarget) -> bool:
    import asyncpg

    connection = await asyncpg.connect(target.admin_url)
    try:
        exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)",
            target.database_name,
        )
        if exists:
            return False
        await connection.execute(
            f"CREATE DATABASE {_quote_identifier(target.database_name)}"
        )
        return True
    finally:
        await connection.close()


async def apply_migrations(
    target: DatabaseTarget, migrations: list[Migration]
) -> list[str]:
    import asyncpg

    connection = await asyncpg.connect(target.database_url)
    applied: list[str] = []
    lock_name = "metaverse-projects-schema-migrations"
    try:
        await connection.execute("SELECT pg_advisory_lock(hashtext($1))", lock_name)
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(3) PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        for migration in migrations:
            existing = await connection.fetchrow(
                "SELECT filename, checksum FROM schema_migrations WHERE version = $1",
                migration.version,
            )
            if existing:
                if (
                    existing["filename"] != migration.filename
                    or existing["checksum"] != migration.checksum
                ):
                    raise RuntimeError(
                        f"Applied migration {migration.version} no longer matches "
                        f"{migration.filename}."
                    )
                continue

            async with connection.transaction():
                await connection.execute(migration.sql)
                await connection.execute(
                    """
                    INSERT INTO schema_migrations (version, filename, checksum)
                    VALUES ($1, $2, $3)
                    """,
                    migration.version,
                    migration.filename,
                    migration.checksum,
                )
            applied.append(migration.filename)
        return applied
    finally:
        try:
            await connection.execute("SELECT pg_advisory_unlock(hashtext($1))", lock_name)
        finally:
            await connection.close()


async def setup_test_database(
    database_url: str,
    admin_url: str | None,
    migrations_dir: Path,
) -> tuple[bool, list[str], str]:
    target = parse_database_target(database_url, admin_url)
    migrations = discover_migrations(migrations_dir)
    created = await create_database_if_missing(target)
    applied = await apply_migrations(target, migrations)
    return created, applied, target.database_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a dedicated PostgreSQL test database and apply SQL migrations."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("TEST_DATABASE_URL", ""),
        help="Test DB URL. Defaults to TEST_DATABASE_URL.",
    )
    parser.add_argument(
        "--admin-url",
        default=os.getenv("TEST_DATABASE_ADMIN_URL") or None,
        help=(
            "Existing DB URL used to create the test DB. Defaults to the postgres "
            "database on the test DB server."
        ),
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="Directory containing numbered SQL migrations.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.database_url:
        raise SystemExit(
            "TEST_DATABASE_URL is required. Use a dedicated DB name such as qwendb_test."
        )

    try:
        created, applied, database_name = asyncio.run(
            setup_test_database(
                args.database_url,
                args.admin_url,
                args.migrations_dir,
            )
        )
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Test database setup failed: install backend/requirements.txt first."
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Test database setup failed: {exc}") from exc

    print(f"Test database: {database_name} ({'created' if created else 'already exists'})")
    if applied:
        for filename in applied:
            print(f"Applied migration: {filename}")
    else:
        print("All migrations are already applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
