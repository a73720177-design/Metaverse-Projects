from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.models.user import TokenResponse, UserCredentials, UserResponse
from app.repositories.user_repository import (
    StoredUser,
    UserRepository,
    UsernameAlreadyExistsError,
)


class InvalidCredentialsError(RuntimeError):
    pass


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        secret_key: str,
        access_token_expire_minutes: int = 60,
    ) -> None:
        self.repository = repository
        self.secret_key = secret_key
        self.access_token_expire_minutes = access_token_expire_minutes
        self.password_hash = PasswordHash.recommended()
        self._dummy_hash = self.password_hash.hash("not-a-real-password")

    async def signup(self, credentials: UserCredentials) -> UserResponse:
        if await self.repository.get_by_username(credentials.username):
            raise UsernameAlreadyExistsError
        user = await self.repository.create(
            credentials.username,
            self.password_hash.hash(credentials.password),
        )
        return self._to_response(user)

    async def login(self, credentials: UserCredentials) -> TokenResponse:
        user = await self.repository.get_by_username(credentials.username)
        stored_hash = user.password_hash if user else self._dummy_hash
        if not self.password_hash.verify(credentials.password, stored_hash) or user is None:
            raise InvalidCredentialsError

        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.access_token_expire_minutes
        )
        token = jwt.encode(
            {"sub": str(user.user_id), "exp": expires_at},
            self.secret_key,
            algorithm="HS256",
        )
        return TokenResponse(access_token=token)

    async def get_user_from_token(self, token: str) -> UserResponse:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            user_id = UUID(payload["sub"])
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise InvalidCredentialsError from exc

        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise InvalidCredentialsError
        return self._to_response(user)

    @staticmethod
    def _to_response(user: StoredUser) -> UserResponse:
        return UserResponse(
            user_id=user.user_id,
            username=user.username,
            created_at=user.created_at,
        )
