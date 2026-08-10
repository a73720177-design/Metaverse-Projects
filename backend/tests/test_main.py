from fastapi.testclient import TestClient

from app.dependencies import get_chat_service, get_persona_service, get_review_service
from app.main import app
from app.models.chat import ChatRequest
from app.models.persona import PersonaCreateRequest
from app.adapters.in_memory_agent_repository import InMemoryAgentRepository
from app.adapters.in_memory_review_repository import InMemoryReviewRepository
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
    async def generate(self, agent_id, request: ReviewCreateRequest) -> dict:
        return {
            "feedback": {"positive": "Clear structure", "negative": "Add evidence"},
            "claims": [],
            "questions": ["What evidence supports this claim?"],
        }


class FakeChatGenerator:
    async def generate(self, agent_id, request: ChatRequest) -> dict:
        return {"answer": f"Evaluator response: {request.message}", "sources": []}


def test_review_contract() -> None:
    service = ReviewService(FakeReviewGenerator(), InMemoryReviewRepository())
    app.dependency_overrides[get_review_service] = lambda: service
    try:
        agent_id = "11111111-1111-1111-1111-111111111111"
        document_id = "22222222-2222-2222-2222-222222222222"
        created = client.post(
            f"/agents/{agent_id}/reviews", json={"document_id": document_id}
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["agent_id"] == agent_id
        assert payload["document_id"] == document_id

        fetched = client.get(f"/reviews/{payload['review_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == payload
    finally:
        app.dependency_overrides.clear()


def test_chat_contract() -> None:
    app.dependency_overrides[get_chat_service] = lambda: ChatService(FakeChatGenerator())
    try:
        agent_id = "11111111-1111-1111-1111-111111111111"
        response = client.post(f"/agents/{agent_id}/chat", json={"message": "Hello"})
        assert response.status_code == 200
        assert response.json()["answer"] == "Evaluator response: Hello"
    finally:
        app.dependency_overrides.clear()
