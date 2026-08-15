from pathlib import Path
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from app.dependencies import (
    get_chat_service,
    get_llm_client,
    get_persona_service,
    get_review_service,
)
from app.main import app
from app.models.chat import ChatRequest
from app.models.persona import PersonaCreateRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository
from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import HttpPersonaGenerator
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.review import ReviewCreateRequest
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


client = TestClient(app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Local AI Review Backend"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_preflight_allows_known_frontend_origin() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight_allows_vite_over_hamachi() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://25.20.30.40:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://25.20.30.40:5173"


def test_cors_does_not_allow_unknown_frontend_origin() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_rejects_unsupported_document() -> None:
    response = client.post("/documents/parse", files={"file": ("sample.txt", b"hello", "text/plain")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "http_415"


class FakePersonaGenerator:
    async def generate(self, request: PersonaCreateRequest) -> dict:
        return {
            "name": "must-be-overridden",
            "role": "Professor",
            "expertise": [
                {
                    "value": "Artificial Intelligence",
                    "status": "user_stated",
                    "confidence": 1.0,
                    "evidence": [],
                }
            ],
        }


def test_create_and_get_agent_through_contracts() -> None:
    service = PersonaService(FakePersonaGenerator(), InMemoryAgentRepository())
    app.dependency_overrides[get_persona_service] = lambda: service
    try:
        created = client.post("/agents", json={"name": "Test Professor", "description": "AI evaluator"})
        assert created.status_code == 201
        payload = created.json()
        assert payload["name"] == "Test Professor"

        fetched = client.get(f"/agents/{payload['agent_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == payload
    finally:
        app.dependency_overrides.clear()


class FakeReviewGenerator:
    async def generate(self, persona, document, instructions) -> dict:
        return {
            "feedback": {"positive": "Clear structure", "negative": "Add evidence"},
            "claims": [],
            "questions": ["What evidence supports this claim?"],
        }


class FakeChatGenerator:
    async def generate(self, persona, request: ChatRequest, document) -> dict:
        return {"answer": f"Evaluator response: {request.message}", "sources": []}


def test_review_contract() -> None:
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    service = ReviewService(
        FakeReviewGenerator(),
        InMemoryReviewRepository(),
        agent_repository,
        document_repository,
    )
    app.dependency_overrides[get_review_service] = lambda: service
    try:
        agent_id = UUID("11111111-1111-1111-1111-111111111111")
        document_id = UUID("22222222-2222-2222-2222-222222222222")
        import asyncio
        asyncio.run(
            agent_repository.save(
                PersonaProfile(agent_id=agent_id, name="Evaluator", description="Strict")
            )
        )
        asyncio.run(
            document_repository.save(
                DocumentParseResponse(
                    document_id=document_id,
                    filename="slides.pptx",
                    document_type="pptx",
                    saved_path=Path("uploads/slides.pptx"),
                    sections=[],
                    full_text="Presentation text",
                )
            )
        )
        created = client.post(
            f"/agents/{agent_id}/reviews", json={"document_id": str(document_id)}
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["agent_id"] == str(agent_id)
        assert payload["document_id"] == str(document_id)

        fetched = client.get(f"/reviews/{payload['review_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == payload
    finally:
        app.dependency_overrides.clear()


def test_chat_contract() -> None:
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    agent_id = UUID("11111111-1111-1111-1111-111111111111")
    import asyncio
    asyncio.run(
        agent_repository.save(
            PersonaProfile(agent_id=agent_id, name="Evaluator", description="Strict")
        )
    )
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        FakeChatGenerator(), agent_repository, document_repository
    )
    try:
        response = client.post(f"/agents/{agent_id}/chat", json={"message": "Hello"})
        assert response.status_code == 200
        assert response.json()["answer"] == "Evaluator response: Hello"
    finally:
        app.dependency_overrides.clear()


def test_http_llm_persona_adapter_uses_service_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/personas"
        payload = __import__("json").loads(request.content)
        assert payload["name"] == "Professor"
        return httpx.Response(
            200,
            json={"role": "Professor", "expertise": [], "evaluation_style": []},
        )

    import asyncio
    generator = HttpPersonaGenerator(HttpLlmClient(httpx.MockTransport(handler)))
    result = asyncio.run(
        generator.generate(
            PersonaCreateRequest(name="Professor", description="Evidence focused")
        )
    )
    assert result["role"] == "Professor"


def test_llm_health_uses_versioned_http_service() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/health"
        assert request.headers["X-Backend-Contract-Version"] == "1"
        return httpx.Response(200, json={"status": "ok"})

    app.dependency_overrides[get_llm_client] = lambda: HttpLlmClient(
        httpx.MockTransport(handler)
    )
    try:
        response = client.get("/health/llm")
        assert response.status_code == 200
        assert response.json()["llm_service"] == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()
