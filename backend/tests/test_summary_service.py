import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_summary_service
from app.main import app
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaProfile
from app.models.user import UserResponse
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.repositories.summary_repository import InMemorySummaryRepository
from app.services.summary_service import SummaryService


client = TestClient(app)
TEST_USER = UserResponse(
    user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    username="testuser",
    created_at=datetime.now(timezone.utc),
)
DOCUMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
AGENT_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def authenticated_user_override():
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


class FakeSummaryGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, document, style, persona) -> dict:
        self.calls += 1
        return {
            "summary": f"요약 #{self.calls} ({style.value})",
            "key_topics": [],
            "outline": ["항목 1"],
        }


def _build_service(generator=None):
    document_repository = InMemoryDocumentRepository()
    agent_repository = InMemoryAgentRepository()
    asyncio.run(
        document_repository.save(
            DocumentParseResponse(
                document_id=DOCUMENT_ID,
                filename="slides.pptx",
                document_type="pptx",
                saved_path=Path("uploads/slides.pptx"),
                sections=[],
                full_text="Presentation text",
            ),
            TEST_USER.user_id,
        )
    )
    asyncio.run(
        agent_repository.save(
            PersonaProfile(agent_id=AGENT_ID, name="Evaluator", description="Strict"),
            TEST_USER.user_id,
        )
    )
    generator = generator or FakeSummaryGenerator()
    service = SummaryService(
        generator=generator,
        repository=InMemorySummaryRepository(),
        agent_repository=agent_repository,
        document_repository=document_repository,
    )
    return service, generator, document_repository, agent_repository


def test_create_and_get_summary_contract() -> None:
    service, generator, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        created = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        assert created.status_code == 201
        payload = created.json()
        assert payload["document_id"] == str(DOCUMENT_ID)
        assert payload["style"] == "brief"
        assert payload["agent_id"] is None
        assert generator.calls == 1

        fetched = client.get(f"/documents/{DOCUMENT_ID}/summary")
        assert fetched.status_code == 200
        assert fetched.json() == payload
    finally:
        app.dependency_overrides.clear()


def test_get_summary_without_prior_create_returns_404() -> None:
    service, _, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        response = client.get(f"/documents/{DOCUMENT_ID}/summary")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_create_summary_for_missing_document_returns_404() -> None:
    service, _, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        missing_id = UUID("33333333-3333-3333-3333-333333333333")
        response = client.post(f"/documents/{missing_id}/summary", json={})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_create_summary_for_document_without_text_returns_actionable_422() -> None:
    service, _, document_repository, _ = _build_service()
    empty = DocumentParseResponse(
        document_id=UUID("33333333-3333-3333-3333-333333333333"),
        filename="scan.pdf",
        document_type="pdf",
        saved_path=Path("scan.pdf"),
        sections=[],
        full_text="",
    )
    asyncio.run(document_repository.save(empty, TEST_USER.user_id))
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        response = client.post(f"/documents/{empty.document_id}/summary", json={})
        assert response.status_code == 422
        assert "텍스트를 추출하지 못했습니다" in response.json()["error"]["message"]
    finally:
        app.dependency_overrides.clear()


def test_create_summary_for_missing_agent_returns_404() -> None:
    service, _, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        missing_agent = UUID("44444444-4444-4444-4444-444444444444")
        response = client.post(
            f"/documents/{DOCUMENT_ID}/summary", json={"agent_id": str(missing_agent)}
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_repeated_create_reuses_cached_summary_without_regenerating() -> None:
    service, generator, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        first = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        second = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        assert first.json() == second.json()
        assert generator.calls == 1
    finally:
        app.dependency_overrides.clear()


def test_refresh_true_regenerates_and_replaces_cached_summary() -> None:
    service, generator, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        first = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        refreshed = client.post(f"/documents/{DOCUMENT_ID}/summary?refresh=true", json={})
        assert generator.calls == 2
        assert first.json()["summary_id"] == refreshed.json()["summary_id"]
        assert first.json()["summary"] != refreshed.json()["summary"]
    finally:
        app.dependency_overrides.clear()


def test_different_styles_are_cached_independently() -> None:
    service, generator, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        brief = client.post(f"/documents/{DOCUMENT_ID}/summary", json={"style": "brief"})
        outline = client.post(f"/documents/{DOCUMENT_ID}/summary", json={"style": "outline"})
        assert brief.json()["summary_id"] != outline.json()["summary_id"]
        assert generator.calls == 2
    finally:
        app.dependency_overrides.clear()


def test_summary_hidden_from_another_owners_document() -> None:
    service, _, _, _ = _build_service()
    app.dependency_overrides[get_summary_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    try:
        created = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        assert created.status_code == 201

        other_user = TEST_USER.model_copy(
            update={"user_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")}
        )
        app.dependency_overrides[get_current_user] = lambda: other_user
        response = client.get(f"/documents/{DOCUMENT_ID}/summary")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


class RaisingSummaryGenerator:
    async def generate(self, document, style, persona) -> dict:
        from app.integrations.llm.contracts import SummaryGeneratorError

        raise SummaryGeneratorError("LLM 서비스를 사용할 수 없습니다.")


def test_legacy_contract_mode_returns_503_for_unsupported_summary_generator() -> None:
    from app.integrations.llm.legacy_generators import UnsupportedLegacySummaryGenerator

    service, _, _, _ = _build_service(generator=UnsupportedLegacySummaryGenerator())
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        response = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_generator_error_surfaces_as_503() -> None:
    service, _, _, _ = _build_service(generator=RaisingSummaryGenerator())
    app.dependency_overrides[get_summary_service] = lambda: service
    try:
        response = client.post(f"/documents/{DOCUMENT_ID}/summary", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
