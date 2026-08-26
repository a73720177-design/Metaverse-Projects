import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from app.db.database import close_db, get_session_factory
from app.db.user_table import UserTable
from app.main import app


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="RUN_POSTGRES_TESTS=1일 때만 로컬 PostgreSQL 인증을 검사합니다.",
)
def test_postgres_signup_login_and_me() -> None:
    async def run() -> None:
        username = f"codexcheck_{uuid4().hex[:8]}"
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                signup = await client.post(
                    "/auth/signup",
                    json={"username": username, "password": "password123"},
                )
                assert signup.status_code == 201

                login = await client.post(
                    "/auth/login",
                    json={"username": username, "password": "password123"},
                )
                assert login.status_code == 200

                me = await client.get(
                    "/auth/me",
                    headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                )
                assert me.status_code == 200
                assert me.json()["username"] == username
        finally:
            async with get_session_factory()() as session:
                await session.execute(delete(UserTable).where(UserTable.username == username))
                await session.commit()
            await close_db()

    asyncio.run(run())
