from functools import lru_cache
import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import (
    get_jwt_access_token_expire_minutes,
    get_jwt_secret_key,
    get_object_storage_mode,
    get_repository_mode,
)
from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import (
    HttpChatGenerator,
    HttpDocumentIndexer,
    HttpPersonaGenerator,
    HttpReviewGenerator,
)
from app.integrations.llm.local_persona import LocalPersonaGenerator
from app.repositories.agent_repository import AgentRepository, InMemoryAgentRepository, PostgresAgentRepository
from app.repositories.document_repository import DocumentRepository, InMemoryDocumentRepository, PostgresDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository, PostgresReviewRepository, ReviewRepository
from app.repositories.chat_repository import ChatRepository, InMemoryChatRepository, PostgresChatRepository
from app.repositories.user_repository import (
    InMemoryUserRepository,
    PostgresUserRepository,
    UserRepository,
)
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService
from app.models.user import UserResponse
from app.services.auth_service import InvalidCredentialsError
from app.storage.minio_storage import MinioStorage
from app.storage.local_storage import LocalStorage
from app.storage.object_storage import ObjectStorage


bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_llm_client() -> HttpLlmClient:
    return HttpLlmClient()


@lru_cache
def get_document_indexer() -> HttpDocumentIndexer:
    return HttpDocumentIndexer(get_llm_client())


@lru_cache
def get_agent_repository() -> AgentRepository:
    return PostgresAgentRepository() if get_repository_mode() == "postgres" else InMemoryAgentRepository()


@lru_cache
def get_document_repository() -> DocumentRepository:
    return PostgresDocumentRepository() if get_repository_mode() == "postgres" else InMemoryDocumentRepository()


@lru_cache
def get_review_repository() -> ReviewRepository:
    return PostgresReviewRepository() if get_repository_mode() == "postgres" else InMemoryReviewRepository()


@lru_cache
def get_chat_repository() -> ChatRepository:
    return PostgresChatRepository() if get_repository_mode() == "postgres" else InMemoryChatRepository()


@lru_cache
def get_user_repository() -> UserRepository:
    return (
        PostgresUserRepository()
        if get_repository_mode() == "postgres"
        else InMemoryUserRepository()
    )


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(
        repository=get_user_repository(),
        secret_key=get_jwt_secret_key(),
        access_token_expire_minutes=get_jwt_access_token_expire_minutes(),
    )


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


async def get_current_user(
    token: str = Depends(require_bearer_token),
    service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    try:
        return await service.get_user_from_token(token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않거나 만료된 로그인입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@lru_cache
def get_object_storage() -> ObjectStorage:
    return MinioStorage() if get_object_storage_mode() == "minio" else LocalStorage()


@lru_cache
def get_persona_service() -> PersonaService:
    generator = (
        LocalPersonaGenerator()
        if os.getenv("PERSONA_FALLBACK_LOCAL", "false").strip().lower()
        in {"1", "true", "yes"}
        else HttpPersonaGenerator(get_llm_client())
    )
    return PersonaService(
        generator=generator,
        repository=get_agent_repository(),
        document_repository=get_document_repository(),
    )


@lru_cache
def get_review_service() -> ReviewService:
    return ReviewService(
        generator=HttpReviewGenerator(get_llm_client()),
        repository=get_review_repository(),
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
        indexer=get_document_indexer(),
    )


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(
        generator=HttpChatGenerator(get_llm_client()),
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
        chat_repository=get_chat_repository(),
        indexer=get_document_indexer(),
    )
