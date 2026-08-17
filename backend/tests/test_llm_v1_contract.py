import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.integrations.llm.client import HttpLlmClient, LlmServiceResponseError
from app.integrations.llm.generators import (
    HttpChatGenerator,
    HttpPersonaGenerator,
    HttpReviewGenerator,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.review import ReviewCreateRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


def _persona() -> PersonaProfile:
    return PersonaProfile(
        agent_id=uuid4(),
        name="근거 중심 평가자",
        description="비교 실험과 출처를 중요하게 평가한다.",
        role="Professor",
        expertise=[
            {
                "value": "Artificial Intelligence",
                "status": "user_stated",
                "confidence": 1.0,
                "evidence": [],
            }
        ],
        evaluation_style=[],
    )


def _document() -> DocumentParseResponse:
    return DocumentParseResponse(
        document_id=uuid4(),
        filename="slides.pdf",
        document_type="pdf",
        saved_path=Path("private/storage/object.pdf"),
        sections=[DocumentSection(index=1, text="발표 내용")],
        full_text="발표 전체 내용",
    )


def test_v1_persona_contract_builds_backend_profile() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/personas"
        assert request.headers["X-Backend-Contract-Version"] == "1"
        assert json.loads(request.content) == {
            "name": "Professor",
            "description": "Evidence focused",
        }
        return httpx.Response(
            200,
            json={
                "role": "Professor",
                "expertise": [
                    {
                        "value": "AI",
                        "status": "supported",
                        "confidence": 0.9,
                        "evidence": [],
                    }
                ],
                "evaluation_style": [],
            },
        )

    service = PersonaService(
        HttpPersonaGenerator(HttpLlmClient(httpx.MockTransport(handler))),
        InMemoryAgentRepository(),
    )
    result = asyncio.run(
        service.create(
            PersonaCreateRequest(name="Professor", description="Evidence focused")
        )
    )
    assert result.name == "Professor"
    assert result.description == "Evidence focused"
    assert result.role == "Professor"
    assert result.expertise[0].value == "AI"


def test_v1_review_contract_excludes_private_storage_path() -> None:
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/reviews"
        payload = json.loads(request.content)
        assert payload["persona"]["agent_id"] == str(persona.agent_id)
        assert payload["document"]["document_id"] == str(document.document_id)
        assert payload["document"]["sections"] == [
            {"index": 1, "text": "발표 내용"}
        ]
        assert "saved_path" not in payload["document"]
        assert payload["instructions"] == "출처를 확인해 주세요."
        return httpx.Response(
            200,
            json={
                "claims": [
                    {
                        "claim": "주장",
                        "verdict": "supported",
                        "confidence": 0.8,
                        "sources": [
                            {
                                "document_id": str(document.document_id),
                                "filename": document.filename,
                                "page": 1,
                                "excerpt": "근거",
                            }
                        ],
                    }
                ],
                "feedback": {"positive": "좋음", "negative": "보완 필요"},
                "questions": ["근거는 무엇인가요?"],
            },
        )

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    review_repository = InMemoryReviewRepository()

    async def run_contract():
        await agent_repository.save(persona)
        await document_repository.save(document)
        service = ReviewService(
            HttpReviewGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            review_repository,
            agent_repository,
            document_repository,
        )
        return await service.create(
            persona.agent_id,
            ReviewCreateRequest(
                document_id=document.document_id,
                instructions="출처를 확인해 주세요.",
            ),
        )

    result = asyncio.run(run_contract())
    assert result.agent_id == persona.agent_id
    assert result.document_id == document.document_id
    assert result.claims[0].sources[0].document_id == document.document_id


@pytest.mark.parametrize("with_document", [False, True])
def test_v1_chat_contract_supports_optional_document(with_document: bool) -> None:
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat"
        payload = json.loads(request.content)
        assert payload["message"] == "핵심 문제는 무엇인가요?"
        if with_document:
            assert payload["document"]["document_id"] == str(document.document_id)
            assert "saved_path" not in payload["document"]
        else:
            assert payload["document"] is None
        return httpx.Response(200, json={"answer": "답변", "sources": []})

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()

    async def run_contract():
        await agent_repository.save(persona)
        if with_document:
            await document_repository.save(document)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            document_repository,
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(
                message="핵심 문제는 무엇인가요?",
                document_id=document.document_id if with_document else None,
            ),
        )

    result = asyncio.run(run_contract())
    assert result.agent_id == persona.agent_id
    assert result.answer == "답변"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(502, json={"detail": "invalid model output"}), "HTTP 502"),
        (httpx.Response(503, json={"detail": "ollama unavailable"}), "HTTP 503"),
        (httpx.Response(200, text="not-json"), "잘못된 JSON"),
    ],
)
def test_v1_client_rejects_upstream_errors_without_leaking_body(
    response: httpx.Response,
    message: str,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    client = HttpLlmClient(httpx.MockTransport(handler))
    with pytest.raises(LlmServiceResponseError) as captured:
        asyncio.run(client.post_json("/personas", {"name": "A", "description": "B"}))
    assert message in str(captured.value)
    assert "invalid model output" not in str(captured.value)
    assert "ollama unavailable" not in str(captured.value)
