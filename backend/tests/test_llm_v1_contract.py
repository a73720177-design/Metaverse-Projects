import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.integrations.llm.client import HttpLlmClient, LlmServiceResponseError
from app.integrations.llm.generators import (
    HttpChatGenerator,
    HttpDocumentIndexer,
    HttpPersonaGenerator,
    HttpReviewGenerator,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.review import ReviewCreateRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.repositories.chat_repository import InMemoryChatRepository
from app.repositories.review_repository import InMemoryReviewRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService


OWNER_ID = uuid4()


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
            PersonaCreateRequest(name="Professor", description="Evidence focused"),
            OWNER_ID,
        )
    )
    assert result.name == "Professor"
    assert result.description == "Evidence focused"
    assert result.role == "Professor"
    assert result.expertise[0].value == "AI"


def test_v1_review_contract_sends_document_id_only() -> None:
    """평가 요청에는 문서 전문이 실리지 않는다. 자료는 인덱싱 때 이미 넘어갔다."""
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/reviews"
        payload = json.loads(request.content)
        assert payload["persona"]["agent_id"] == str(persona.agent_id)
        assert payload["document_id"] == str(document.document_id)
        assert "document" not in payload
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
        await agent_repository.save(persona, OWNER_ID)
        await document_repository.save(document, OWNER_ID)
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
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert result.agent_id == persona.agent_id
    assert result.document_id == document.document_id
    assert result.claims[0].sources[0].document_id == document.document_id


def test_v1_index_contract_sends_full_text_without_storage_path() -> None:
    """문서 전문이 LLM 서비스로 넘어가는 유일한 지점이다."""
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/documents/index"
        payload = json.loads(request.content)
        assert payload["document_id"] == str(document.document_id)
        assert payload["full_text"] == "발표 전체 내용"
        assert payload["sections"] == [{"index": 1, "text": "발표 내용"}]
        assert "saved_path" not in payload
        return httpx.Response(
            200,
            json={
                "document_id": str(document.document_id),
                "chunk_count": 1,
                "reused": False,
            },
        )

    indexer = HttpDocumentIndexer(HttpLlmClient(httpx.MockTransport(handler)))
    result = asyncio.run(indexer.index(document))
    assert result["chunk_count"] == 1


def test_v1_index_is_removed_when_document_is_deleted() -> None:
    """문서를 지우면 LLM 서비스의 임베딩 캐시에 남은 본문도 지운다."""
    document = _document()
    requested: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.method, request.url.path))
        return httpx.Response(204)

    indexer = HttpDocumentIndexer(HttpLlmClient(httpx.MockTransport(handler)))
    asyncio.run(indexer.forget(document.document_id))
    assert requested == [
        ("DELETE", f"/api/v1/documents/{document.document_id}/index")
    ]


@pytest.mark.parametrize("with_document", [False, True])
def test_v1_chat_contract_sends_document_ids(with_document: bool) -> None:
    """채팅 요청에는 후보 document_id만 실린다. 문서 선택과 검색은 LLM이 한다."""
    persona = _persona()
    document = _document()
    source = {
        "document_id": str(document.document_id),
        "filename": document.filename,
        "page": 1,
        "excerpt": "근거",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat"
        payload = json.loads(request.content)
        assert payload["message"] == "핵심 문제는 무엇인가요?"
        assert "document" not in payload
        if with_document:
            assert payload["document_ids"] == [str(document.document_id)]
        else:
            assert payload["document_ids"] == []
        return httpx.Response(
            200,
            json={
                "answer": "답변",
                "sources": [source] if with_document else [],
                "needs_more_material": False,
            },
        )

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()

    async def run_contract():
        await agent_repository.save(persona, OWNER_ID)
        if with_document:
            await document_repository.save(document, OWNER_ID)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(
                message="핵심 문제는 무엇인가요?",
                document_id=document.document_id if with_document else None,
            ),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert result.agent_id == persona.agent_id
    assert result.answer == "답변"
    assert result.needs_more_material is False
    if with_document:
        assert result.sources[0].document_id == document.document_id
        assert result.sources[0].filename == document.filename
    else:
        assert result.sources == []


def test_v1_chat_marks_answer_that_asks_for_more_material() -> None:
    persona = _persona()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "관련 내용을 찾지 못했습니다. 자료를 추가해 주세요.",
                "sources": [],
                "needs_more_material": True,
            },
        )

    agent_repository = InMemoryAgentRepository()
    chat_repository = InMemoryChatRepository()

    async def run_contract():
        await agent_repository.save(persona, OWNER_ID)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            InMemoryDocumentRepository(),
            chat_repository,
        )
        result = await service.reply(
            persona.agent_id, ChatRequest(message="조직도를 알려주세요"), OWNER_ID
        )
        stored = await chat_repository.list(OWNER_ID, deleted=False)
        return result, stored

    result, stored = asyncio.run(run_contract())
    assert result.needs_more_material is True
    assert stored[0].needs_more_material is True


def test_v1_chat_reindexes_and_retries_when_index_is_missing() -> None:
    """LLM 서비스가 재시작돼 인덱스가 비면 문서를 다시 밀어넣고 한 번 재시도한다."""
    persona = _persona()
    document = _document()
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/api/v1/documents/index":
            return httpx.Response(
                200,
                json={
                    "document_id": str(document.document_id),
                    "chunk_count": 1,
                    "reused": False,
                },
            )
        if requested.count("/api/v1/chat") == 1:
            return httpx.Response(
                409,
                json={
                    "detail": {
                        "code": "document_not_indexed",
                        "document_id": str(document.document_id),
                    }
                },
            )
        return httpx.Response(
            200, json={"answer": "답변", "sources": [], "needs_more_material": False}
        )

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()

    async def run_contract():
        await agent_repository.save(persona, OWNER_ID)
        await document_repository.save(document, OWNER_ID)
        llm_client = HttpLlmClient(httpx.MockTransport(handler))
        service = ChatService(
            HttpChatGenerator(llm_client),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            indexer=HttpDocumentIndexer(llm_client),
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(message="근거는?", document_id=document.document_id),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert result.answer == "답변"
    assert requested == [
        "/api/v1/chat",
        "/api/v1/documents/index",
        "/api/v1/chat",
    ]


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
