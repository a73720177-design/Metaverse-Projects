"""Opt-in live PostgreSQL checks, only on a newly created test database."""
import asyncio
import hashlib
import os
from uuid import uuid4

import asyncpg
import pytest

from scripts.setup_test_db import (
    DEFAULT_MIGRATIONS_DIR, Migration, apply_migrations, create_database_if_missing,
    discover_migrations, parse_database_target, read_migration_history,
)


@pytest.mark.skipif(not os.getenv('MIGRATION_REPAIR_TEST_DATABASE_URL'), reason='Dedicated migration test URL required')
def test_fresh_replay_selective_apply_and_batch_rollback():
    async def check():
        target = parse_database_target(os.environ['MIGRATION_REPAIR_TEST_DATABASE_URL'])
        created = await create_database_if_missing(target)
        assert created, 'Refusing to reuse or delete an existing test database'
        connection = None
        try:
            migrations = discover_migrations(DEFAULT_MIGRATIONS_DIR)
            assert len(await apply_migrations(target, migrations)) == 12
            assert await apply_migrations(target, migrations) == []
            connection = await asyncpg.connect(target.database_url)
            user, agent, document = uuid4(), uuid4(), uuid4()
            await connection.execute("INSERT INTO users(user_id,username,password_hash) VALUES ($1,'repair_test','fake-hash')", user)
            await connection.execute("INSERT INTO agents(agent_id,owner_id,name) VALUES ($1,$2,'test agent')", agent, user)
            await connection.execute("INSERT INTO documents(document_id,owner_id,filename,document_type,full_text) VALUES ($1,$2,'test.pdf','pdf','preserved evidence')", document, user)
            await connection.execute("INSERT INTO chat_messages(owner_id,agent_id,document_id,message,answer) VALUES ($1,$2,$3,'test question','preserved answer')", user, agent, document)

            # Reproduce the live legacy state only inside this new test DB.
            await connection.execute('ALTER TABLE chat_messages DROP COLUMN conversation_id')
            await connection.execute("DELETE FROM schema_migrations WHERE version IN ('001','002','003','004','005','006','012')")
            tables = ['users', 'agents', 'documents', 'chat_messages']

            async def fingerprint():
                return {table: await connection.fetchval(
                    f"SELECT md5(string_agg((to_jsonb(t)-'conversation_id')::text, '' ORDER BY (to_jsonb(t)-'conversation_id')::text)) FROM {table} t"
                ) for table in tables}

            before = await fingerprint()
            old_history = await read_migration_history(connection)
            selected = await apply_migrations(target, migrations, only_versions={'012'})
            assert selected == ['012_add_chat_conversation.sql']
            assert len(await apply_migrations(target, migrations)) == 6
            assert await fingerprint() == before
            history = await read_migration_history(connection)
            assert all(history[key] == row for key, row in old_history.items())
            assert await apply_migrations(target, migrations) == []

            def migration(version, sql):
                return Migration(version, f'{version}_test.sql', hashlib.sha256(sql.encode()).hexdigest(), sql)

            additions = [migration('013', 'CREATE TABLE migration_rollback_probe(id integer)'),
                         migration('014', 'INSERT INTO definitely_missing_repair_table VALUES (1)')]
            with pytest.raises(asyncpg.UndefinedTableError):
                await apply_migrations(target, [*migrations, *additions])
            assert await connection.fetchval("SELECT to_regclass('migration_rollback_probe')") is None
            assert await read_migration_history(connection) == history
            assert await fingerprint() == before

            # Even --only must verify every historical checksum before writing.
            altered = [migration('001', 'SELECT 1'), *migrations[1:], additions[0]]
            with pytest.raises(RuntimeError, match='No migrations were applied'):
                await apply_migrations(target, altered, only_versions={'013'})
            assert await connection.fetchval("SELECT to_regclass('migration_rollback_probe')") is None
        finally:
            if connection is not None:
                await connection.close()
            admin = await asyncpg.connect(target.admin_url)
            try:
                # This exact test-only database was created by this test above.
                quoted = '"' + target.database_name.replace('"', '""') + '"'
                await admin.execute(f'DROP DATABASE {quoted}')
            finally:
                await admin.close()

    asyncio.run(check())
