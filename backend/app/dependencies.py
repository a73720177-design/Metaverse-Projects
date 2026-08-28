from functools import lru_cache
import os

from app.config import get_object_storage_mode, get_repository_mode
from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import (
    HttpChatGenerator,
    HttpPersonaGenerator,
    HttpReviewGenerator,
)
from app.integrations.llm.legacy_generators import (
    LegacyQuestionReviewGenerator,
    LocalPersonaGenerator,
    UnsupportedLegacyChatGenerator,
)
from app.repositories.agent_repository import AgentRepository, InMemoryAgentRepository, PostgresAgentRepository
from app.repositories.document_repository import DocumentRepository, InMemoryDocumentRepository, PostgresDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository, PostgresReviewRepository, ReviewRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService
from app.storage.minio_storage import MinioStorage
from app.storage.local_storage import LocalStorage
from app.storage.object_storage import ObjectStorage


@lru_cache
def get_llm_client() -> HttpLlmClient:
    if get_llm_contract_mode() == "legacy_questions":
        return HttpLlmClient(api_prefix="")
    return HttpLlmClient()


def get_llm_contract_mode() -> str:
    mode = os.getenv("LLM_CONTRACT_MODE", "legacy_questions").strip().lower()
    if mode not in {"legacy_questions", "v1"}:
        raise RuntimeError("LLM_CONTRACT_MODE는 legacy_questions 또는 v1이어야 합니다.")
    return mode


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
def get_object_storage() -> ObjectStorage:
    return MinioStorage() if get_object_storage_mode() == "minio" else LocalStorage()


@lru_cache
def get_persona_service() -> PersonaService:
    generator = (
        LocalPersonaGenerator()
        if get_llm_contract_mode() == "legacy_questions"
        else HttpPersonaGenerator(get_llm_client())
    )
    return PersonaService(
        generator=generator,
        repository=get_agent_repository(),
    )


@lru_cache
def get_review_service() -> ReviewService:
    generator = (
        LegacyQuestionReviewGenerator(get_llm_client())
        if get_llm_contract_mode() == "legacy_questions"
        else HttpReviewGenerator(get_llm_client())
    )
    return ReviewService(
        generator=generator,
        repository=get_review_repository(),
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
    )


@lru_cache
def get_chat_service() -> ChatService:
    generator = (
        UnsupportedLegacyChatGenerator()
        if get_llm_contract_mode() == "legacy_questions"
        else HttpChatGenerator(get_llm_client())
    )
    return ChatService(
        generator=generator,
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
    )
