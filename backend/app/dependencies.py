from functools import lru_cache

from app.adapters.in_memory_agent_repository import InMemoryAgentRepository
from app.adapters.in_memory_review_repository import InMemoryReviewRepository
from app.adapters.not_configured_generators import (
    NotConfiguredChatGenerator,
    NotConfiguredReviewGenerator,
)
from app.adapters.ollama_persona_generator import OllamaPersonaGenerator
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


@lru_cache
def get_persona_service() -> PersonaService:
    # Integration seam: DB and LLM teams replace only these two adapters.
    return PersonaService(
        generator=OllamaPersonaGenerator(),
        repository=InMemoryAgentRepository(),
    )


@lru_cache
def get_review_service() -> ReviewService:
    return ReviewService(
        generator=NotConfiguredReviewGenerator(),
        repository=InMemoryReviewRepository(),
    )


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(generator=NotConfiguredChatGenerator())
