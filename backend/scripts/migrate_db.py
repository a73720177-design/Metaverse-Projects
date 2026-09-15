"""Inspect or migrate the configured application DB without rewriting its history.

Run from backend: python -m scripts.migrate_db --database-name qwendb [--apply]
To apply one known migration without replaying older unrecorded history, add
``--only VERSION``. The complete recorded history is still checksum-validated.
The default only displays pending migrations. The test-DB CLI keeps its test-name guard.
"""

import argparse
import asyncio
import os
from urllib.parse import unquote, urlsplit

from app.config import BACKEND_ROOT
from scripts.setup_test_db import (
    DatabaseTarget, apply_migrations, discover_migrations, plan_migrations,
)


def application_target(database_url: str, expected_name: str) -> DatabaseTarget:
    parsed = urlsplit(database_url)
    database_name = unquote(parsed.path.lstrip("/"))
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use PostgreSQL.")
    if not database_name or "/" in database_name or database_name != expected_name:
        raise ValueError("DATABASE_URL does not match --database-name.")
    return DatabaseTarget(
        database_name=database_name,
        database_url=database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        admin_url="",
    )


def validate_selected_versions(
    migrations, requested_versions: list[str] | None
) -> set[str] | None:
    if requested_versions is None:
        return None
    selected = set(requested_versions)
    invalid = sorted(version for version in selected if not version.isdigit() or len(version) != 3)
    if invalid:
        raise ValueError(f"Migration versions must contain exactly three digits: {', '.join(invalid)}")
    known = {migration.version for migration in migrations}
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(f"Unknown migration version: {', '.join(unknown)}")
    return selected


async def migrate(
    target: DatabaseTarget,
    *,
    apply: bool,
    only_versions: list[str] | None = None,
) -> list[str]:
    migrations = discover_migrations(BACKEND_ROOT / "database")
    selected_versions = validate_selected_versions(migrations, only_versions)
    if apply:
        return await apply_migrations(
            target,
            migrations,
            only_versions=selected_versions,
        )
    plan = await plan_migrations(target, migrations)
    pending = plan["pending"]
    if selected_versions is not None:
        pending = [migration for migration in pending if migration.version in selected_versions]
    return [migration.filename for migration in pending]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--only",
        action="append",
        dest="only_versions",
        metavar="VERSION",
        help="Inspect or apply only this three-digit migration version. Repeatable.",
    )
    args = parser.parse_args()
    target = application_target(os.getenv("DATABASE_URL", ""), args.database_name)
    filenames = asyncio.run(
        migrate(target, apply=args.apply, only_versions=args.only_versions)
    )
    print(f"Database: {target.database_name}")
    for filename in filenames:
        print(f"{'Applied' if args.apply else 'Pending'}: {filename}")
    if not filenames:
        print("All migration records match; no pending migrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
