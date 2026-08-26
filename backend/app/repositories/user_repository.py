from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.user_table import UserTable


@dataclass(frozen=True)
class StoredUser:
    user_id: UUID
    username: str
    password_hash: str
    created_at: datetime


class UsernameAlreadyExistsError(RuntimeError):
    pass


class UserRepository(Protocol):
    async def create(self, username: str, password_hash: str) -> StoredUser: ...
    async def get_by_username(self, username: str) -> StoredUser | None: ...
    async def get_by_id(self, user_id: UUID) -> StoredUser | None: ...


def _to_stored_user(row: UserTable) -> StoredUser:
    return StoredUser(
        user_id=row.user_id,
        username=row.username,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )


class PostgresUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, username: str, password_hash: str) -> StoredUser:
        row = UserTable(user_id=uuid4(), username=username, password_hash=password_hash)
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise UsernameAlreadyExistsError from exc
        await self.session.refresh(row)
        return _to_stored_user(row)

    async def get_by_username(self, username: str) -> StoredUser | None:
        result = await self.session.execute(
            select(UserTable).where(UserTable.username == username)
        )
        row = result.scalar_one_or_none()
        return _to_stored_user(row) if row else None

    async def get_by_id(self, user_id: UUID) -> StoredUser | None:
        row = await self.session.get(UserTable, user_id)
        return _to_stored_user(row) if row else None


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[UUID, StoredUser] = {}

    async def create(self, username: str, password_hash: str) -> StoredUser:
        if await self.get_by_username(username):
            raise UsernameAlreadyExistsError
        user = StoredUser(
            user_id=uuid4(),
            username=username,
            password_hash=password_hash,
            created_at=datetime.now().astimezone(),
        )
        self._users[user.user_id] = user
        return user

    async def get_by_username(self, username: str) -> StoredUser | None:
        return next((user for user in self._users.values() if user.username == username), None)

    async def get_by_id(self, user_id: UUID) -> StoredUser | None:
        return self._users.get(user_id)
