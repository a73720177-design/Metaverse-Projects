from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.dependencies import (
    get_chat_service,
    get_current_user,
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
from app.repositories.chat_repository import InMemoryChatRepository
from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import HttpPersonaGenerator
from app.integrations.llm.contracts import ReviewGeneratorError
from app.integrations.llm.legacy_generators import (
    LegacyQuestionReviewGenerator,
    LocalPersonaGenerator,
)
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.review import ReviewCreateRequest
from app.models.user import UserResponse
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


client = TestClient(app)
TEST_USER = UserResponse(
    user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    username="testuser",
    created_at=datetime.now(timezone.utc),
)


@pytest.fixture(autouse=True)
def authenticated_user_override():
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Local AI Review Backend"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_db_health_reports_memory_mode_without_external_db() -> None:
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "repository_mode": "memory",
        "database": "not_configured",
    }


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


def test_cors_preflight_allows_vite_over_private_lan() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://192.168.0.40:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.0.40:5173"


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


def test_rejects_empty_supported_document() -> None:
    response = client.post(
        "/documents/parse",
        files={"file": ("sample.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "빈 파일은 업로드할 수 없습니다."


def test_rejects_document_over_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    response = client.post(
        "/documents/parse",
        files={"file": ("large.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
    )
    assert response.status_code == 413


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

        active = client.get("/agents")
        assert active.status_code == 200
        assert active.json()[0]["agent_id"] == payload["agent_id"]

        moved = client.delete(f"/agents/{payload['agent_id']}")
        assert moved.status_code == 200
        assert moved.json()["deleted_at"] is not None
        assert client.get(f"/agents/{payload['agent_id']}").status_code == 404
        assert client.get("/agents").json() == []
        assert client.get("/agents/trash").json()[0]["agent_id"] == payload["agent_id"]

        restored = client.post(f"/agents/trash/{payload['agent_id']}/restore")
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None
        assert client.get(f"/agents/{payload['agent_id']}").status_code == 200

        assert client.delete(f"/agents/{payload['agent_id']}").status_code == 200
        assert client.delete(f"/agents/trash/{payload['agent_id']}").status_code == 204
        assert client.get("/agents/trash").json() == []
        assert client.post(f"/agents/trash/{payload['agent_id']}/restore").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_agent_is_hidden_from_another_user() -> None:
    service = PersonaService(FakePersonaGenerator(), InMemoryAgentRepository())
    app.dependency_overrides[get_persona_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    try:
        created = client.post(
            "/agents",
            json={"name": "Private", "description": "Owner only"},
        )
        assert created.status_code == 201

        other_user = TEST_USER.model_copy(
            update={"user_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")}
        )
        app.dependency_overrides[get_current_user] = lambda: other_user
        response = client.get(f"/agents/{created.json()['agent_id']}")
        assert response.status_code == 404
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


class FakeStreamingChatGenerator(FakeChatGenerator):
    async def stream(self, persona, request: ChatRequest, document):
        yield "Evaluator "
        yield f"response: {request.message}"


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
                PersonaProfile(agent_id=agent_id, name="Evaluator", description="Strict"),
                TEST_USER.user_id,
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
                ),
                TEST_USER.user_id,
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
            PersonaProfile(agent_id=agent_id, name="Evaluator", description="Strict"),
            TEST_USER.user_id,
        )
    )
    chat_repository = InMemoryChatRepository()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        FakeChatGenerator(), agent_repository, document_repository, chat_repository
    )
    try:
        response = client.post(f"/agents/{agent_id}/chat", json={"message": "Hello"})
        assert response.status_code == 200
        assert response.json()["answer"] == "Evaluator response: Hello"
        assert response.json()["message"] == "Hello"

        message_id = response.json()["message_id"]
        assert client.get("/chats").json()[0]["message_id"] == message_id

        moved = client.delete(f"/chats/{message_id}")
        assert moved.status_code == 200
        assert moved.json()["deleted_at"] is not None
        assert client.get("/chats").json() == []
        assert client.get("/trash/chats").json()[0]["message_id"] == message_id

        restored = client.post(f"/trash/chats/{message_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None
        assert client.get("/trash/chats").json() == []

        assert client.delete(f"/chats/{message_id}").status_code == 200
        assert client.delete(f"/trash/chats/{message_id}").status_code == 204
        assert client.get("/trash/chats").json() == []
        assert client.post(f"/trash/chats/{message_id}/restore").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_agent_persists_owned_document_contract() -> None:
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    service = PersonaService(
        FakePersonaGenerator(), agent_repository, document_repository
    )
    document = DocumentParseResponse(
        filename="source.pdf",
        document_type="pdf",
        saved_path=Path("source.pdf"),
        sections=[{"index": 1, "text": "grounded content"}],
        full_text="grounded content",
    )
    import asyncio
    asyncio.run(document_repository.save(document, TEST_USER.user_id))
    app.dependency_overrides[get_persona_service] = lambda: service
    try:
        created = client.post(
            "/agents",
            json={
                "name": "Grounded evaluator",
                "description": "Uses linked material",
                "document_ids": [str(document.document_id)],
            },
        )
        assert created.status_code == 201
        assert created.json()["document_ids"] == [str(document.document_id)]
        assert client.get("/agents").json()[0]["document_ids"] == [
            str(document.document_id)
        ]
    finally:
        app.dependency_overrides.clear()


def test_agent_rejects_document_owned_by_another_user() -> None:
    document_repository = InMemoryDocumentRepository()
    service = PersonaService(
        FakePersonaGenerator(), InMemoryAgentRepository(), document_repository
    )
    document = DocumentParseResponse(
        filename="private.pdf",
        document_type="pdf",
        saved_path=Path("private.pdf"),
        sections=[],
        full_text="private",
    )
    import asyncio
    asyncio.run(
        document_repository.save(
            document, UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        )
    )
    app.dependency_overrides[get_persona_service] = lambda: service
    try:
        response = client.post(
            "/agents",
            json={
                "name": "Invalid",
                "description": "Cross-owner material",
                "document_ids": [str(document.document_id)],
            },
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_contract_persists_completed_answer() -> None:
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    chat_repository = InMemoryChatRepository()
    agent_id = UUID("11111111-1111-1111-1111-111111111111")
    import asyncio
    asyncio.run(
        agent_repository.save(
            PersonaProfile(agent_id=agent_id, name="Evaluator", description="Strict"),
            TEST_USER.user_id,
        )
    )
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        FakeStreamingChatGenerator(),
        agent_repository,
        document_repository,
        chat_repository,
    )
    try:
        response = client.post(
            f"/agents/{agent_id}/chat/stream", json={"message": "Hello"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: token" in response.text
        assert "event: done" in response.text
        stored = asyncio.run(chat_repository.list(TEST_USER.user_id, deleted=False))
        assert len(stored) == 1
        assert stored[0].answer == "Evaluator response: Hello"
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


def test_services_health_reports_all_backend_dependencies() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(200, json={"status": "ok"})

    app.dependency_overrides[get_llm_client] = lambda: HttpLlmClient(
        httpx.MockTransport(handler)
    )
    try:
        response = client.get("/health/services")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["services"]["backend"]["status"] == "ok"
        assert payload["services"]["database"]["status"] == "development"
        assert payload["services"]["database"]["mode"] == "memory"
        assert payload["services"]["llm"]["status"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_services_health_returns_degraded_without_exposing_llm_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-host:8001 secret detail")

    app.dependency_overrides[get_llm_client] = lambda: HttpLlmClient(
        httpx.MockTransport(handler)
    )
    try:
        response = client.get("/health/services")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "degraded"
        assert payload["services"]["llm"]["status"] == "unavailable"
        assert "private-host" not in response.text
        assert "secret" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_legacy_persona_uses_backend_input_without_llm_call() -> None:
    import asyncio

    result = asyncio.run(
        LocalPersonaGenerator().generate(
            PersonaCreateRequest(name="Professor", description="근거를 중요하게 평가")
        )
    )
    assert result["role"] == "Evaluator"


def test_database_failure_uses_safe_common_error_response() -> None:
    class FailingAgentRepository:
        async def save(self, persona: PersonaProfile, owner_id: UUID) -> None:
            raise SQLAlchemyError("sensitive database detail")

        async def get(self, agent_id: UUID, owner_id: UUID) -> PersonaProfile | None:
            return None

    service = PersonaService(LocalPersonaGenerator(), FailingAgentRepository())
    app.dependency_overrides[get_persona_service] = lambda: service
    try:
        response = client.post(
            "/agents",
            json={"name": "Professor", "description": "Evidence focused"},
        )
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "database_unavailable",
                "message": "데이터베이스를 일시적으로 사용할 수 없습니다.",
            }
        }
        assert "sensitive" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_legacy_review_adapts_current_llm_team_contract() -> None:
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/extract-concepts":
            return httpx.Response(
                200,
                json={"concepts": [{"name": "AI", "definition": "인공지능"}]},
            )
        if request.url.path == "/generate-questions":
            return httpx.Response(
                200,
                json={"questions": [{"question": "근거는 무엇인가요?"}]},
            )
        return httpx.Response(404)

    import asyncio

    generator = LegacyQuestionReviewGenerator(
        HttpLlmClient(httpx.MockTransport(handler), api_prefix="")
    )
    result = asyncio.run(
        generator.generate(
            PersonaProfile(name="Evaluator", description="근거 중심"),
            DocumentParseResponse(
                filename="slides.pptx",
                document_type="pptx",
                saved_path=Path("uploads/slides.pptx"),
                sections=[],
                full_text="발표 내용",
            ),
            None,
        )
    )

    assert requested_paths == ["/extract-concepts", "/generate-questions"]
    assert result["questions"] == ["근거는 무엇인가요?"]


def test_legacy_review_rejects_invalid_concept_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/extract-concepts":
            return httpx.Response(200, json={"concepts": [{"name": "AI"}]})
        raise AssertionError("질문 API는 호출되면 안 됩니다.")

    import asyncio

    generator = LegacyQuestionReviewGenerator(
        HttpLlmClient(httpx.MockTransport(handler), api_prefix="")
    )
    with pytest.raises(ReviewGeneratorError, match="definition"):
        asyncio.run(
            generator.generate(
                PersonaProfile(name="Evaluator", description="Evidence"),
                DocumentParseResponse(
                    filename="slides.pdf",
                    document_type="pdf",
                    saved_path=Path("uploads/slides.pdf"),
                    sections=[],
                    full_text="Presentation",
                ),
                None,
            )
        )
