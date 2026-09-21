"""Repository integration checks inside a rollback-only outer transaction."""
import asyncio
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.database import get_engine
from app.db.tables import UserTable, DocumentTable
from app.models.persona import PersonaProfile, active_trait
from app.repositories.agent_repository import PostgresAgentRepository


async def main():
    engine = get_engine()
    owner, other, d1, d2 = uuid4(), uuid4(), uuid4(), uuid4()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode='create_savepoint')
        try:
            async with factory() as db:
                db.add(UserTable(user_id=owner, username='traitqa_' + uuid4().hex[:16], password_hash='test-only-no-login'))
                await db.flush()
                db.add_all([DocumentTable(document_id=did, owner_id=owner, filename='test.txt', document_type='txt', full_text='예산 검토') for did in [d1, d2]])
                await db.commit()
            reference = dict(value='예산 검토', status='inferred', confidence=.7, evidence=[dict(source_id='reference_context', summary='예산 검토', confidence=1)])
            declared = dict(value='직접 지정 관점', status='user_stated', confidence=1, evidence=[dict(source_id='description', summary='직접 지정 관점', confidence=1)])
            p = PersonaProfile(name='rollback-only-test', document_ids=[d1], expertise=[reference], evaluation_style=[declared])
            with patch('app.repositories.agent_repository.get_session_factory', return_value=factory):
                repo = PostgresAgentRepository()
                await repo.save(p, owner)
                await repo.unlink_document(d1, other)
                assert active_trait((await repo.get(p.agent_id, owner)).expertise[0])
                await repo.unlink_document(d1, owner)
                removed = await repo.get(p.agent_id, owner)
                assert removed.document_ids == []
                assert not active_trait(removed.expertise[0])
                assert removed.expertise[0].exclusion_reason == 'reference_changed'
                assert active_trait(removed.evaluation_style[0])
                print('PASS PostgreSQL unlink, scope isolation, reason persistence, declared criterion retained', flush=True)
                await repo.save(p, owner)
                unchanged = await repo.set_documents(p.agent_id, owner, [d1])
                assert active_trait(unchanged.expertise[0])
                changed = await repo.set_documents(p.agent_id, owner, [d2])
                assert not active_trait(changed.expertise[0])
                print('PASS PostgreSQL reference replacement and unchanged references', flush=True)
        finally:
            await transaction.rollback()
    async with engine.connect() as connection:
        assert await connection.scalar(select(UserTable.user_id).where(UserTable.user_id == owner)) is None
    print('PASS outer rollback: no test account or document persisted', flush=True)
    await engine.dispose()

asyncio.run(main())
