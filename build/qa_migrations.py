import asyncio
import hashlib
import os
from pathlib import Path
import asyncpg
from scripts.setup_test_db import DatabaseTarget, Migration, apply_migrations, discover_migrations

async def main():
    url = os.environ['TEST_DATABASE_URL']
    target = DatabaseTarget('installer_test', url, '')
    migrations = discover_migrations(Path('/app/database'))
    first = await apply_migrations(target, migrations)
    assert len(first) == 14, first
    assert await apply_migrations(target, migrations) == []
    sql1 = 'CREATE TABLE installer_rollback_probe (id integer);'
    sql2 = 'SELECT * FROM deliberately_missing_installer_table;'
    extras = [Migration('015', '015_qa_probe.sql', hashlib.sha256(sql1.encode()).hexdigest(), sql1),
              Migration('016', '016_qa_failure.sql', hashlib.sha256(sql2.encode()).hexdigest(), sql2)]
    try:
        await apply_migrations(target, migrations + extras)
    except asyncpg.UndefinedTableError:
        pass
    else:
        raise AssertionError('Failed batch did not fail')
    connection = await asyncpg.connect(url)
    try:
        assert await connection.fetchval("SELECT to_regclass('installer_rollback_probe')") is None
        assert await connection.fetchval('SELECT count(*) FROM schema_migrations') == 14
        assert await connection.fetchval("SELECT extversion FROM pg_extension WHERE extname='vector'")
    finally:
        await connection.close()
    print('PASS: fresh 14 migrations, repeat no-op, failed-batch rollback, pgvector')

asyncio.run(main())
