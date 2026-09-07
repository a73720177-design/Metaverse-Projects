import os
from uuid import uuid4

import pytest
from sqlalchemy import delete


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL이 설정된 별도 테스트 DB에서만 실행합니다.",
)
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.db.database import get_session_factory, init_db
from app.db.tables import UserTable
from app.repositories.user_repository import PostgresUserRepository
from app.services.auth_service import AuthService
from app.models.user import UserCredentials


@pytest.mark.asyncio
async def test_postgres_signup_login_and_token_lookup() -> None:
    await init_db()
    username = f"authcheck_{uuid4().hex[:8]}"
    service = AuthService(
        PostgresUserRepository(),
        secret_key="test-secret-key-which-is-longer-than-32-bytes",
    )
    try:
        created = await service.signup(
            UserCredentials(username=username, password="password123")
        )
        token = await service.login(
            UserCredentials(username=username, password="password123")
        )
        current = await service.get_user_from_token(token.access_token)
        assert current.user_id == created.user_id
        assert current.username == username
    finally:
        async with get_session_factory()() as session:
            await session.execute(delete(UserTable).where(UserTable.username == username))
            await session.commit()
