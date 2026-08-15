from functools import lru_cache

from app.adapters.in_memory_agent_repository import InMemoryAgentRepository
from app.adapters.in_memory_document_repository import InMemoryDocumentRepository
from app.adapters.in_memory_review_repository import InMemoryReviewRepository
from app.adapters.http_llm_client import HttpLlmClient
from app.adapters.http_llm_generators import (
    HttpChatGenerator,
    HttpPersonaGenerator,
    HttpReviewGenerator,
)
from app.ports.agent_repository import AgentRepository
from app.ports.document_repository import DocumentRepository
from app.ports.review_repository import ReviewRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


@lru_cache
def get_llm_client() -> HttpLlmClient:
    return HttpLlmClient()


@lru_cache
def get_agent_repository() -> AgentRepository:
    return InMemoryAgentRepository()


@lru_cache
def get_document_repository() -> DocumentRepository:
    return InMemoryDocumentRepository()


@lru_cache
def get_review_repository() -> ReviewRepository:
    return InMemoryReviewRepository()


@lru_cache
def get_persona_service() -> PersonaService:
    return PersonaService(
        generator=HttpPersonaGenerator(get_llm_client()),
        repository=get_agent_repository(),
    )


@lru_cache
def get_review_service() -> ReviewService:
    return ReviewService(
        generator=HttpReviewGenerator(get_llm_client()),
        repository=get_review_repository(),
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
    )


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(
        generator=HttpChatGenerator(get_llm_client()),
        agent_repository=get_agent_repository(),
        document_repository=get_document_repository(),
    )
