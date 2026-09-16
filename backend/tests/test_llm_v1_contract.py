import asyncio
import json
import re
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
from app.repositories.chat_repository import InMemoryChatRepository
from app.repositories.review_repository import InMemoryReviewRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService
from app.services.rag_service import combine_document_contexts


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
                                "excerpt": "발표 내용",
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


def test_expected_question_generator_uses_focused_endpoint() -> None:
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/practice/questions"
        payload = json.loads(request.content)
        assert payload["persona"]["agent_id"] == str(persona.agent_id)
        assert "saved_path" not in payload["document"]
        return httpx.Response(200, json={"questions": ["발표 근거를 어떻게 검증했습니까?"]})

    result = asyncio.run(HttpReviewGenerator(
        HttpLlmClient(httpx.MockTransport(handler)), endpoint="/practice/questions"
    ).generate(persona, document, "5개"))
    assert result["questions"] == ["발표 근거를 어떻게 검증했습니까?"]


@pytest.mark.parametrize("with_document", [False, True])
def test_v1_chat_contract_supports_optional_document(with_document: bool) -> None:
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat"
        payload = json.loads(request.content)
        assert payload["message"] == "발표 내용은 무엇인가요?"
        assert payload["max_output_tokens"] == 1024
        if with_document:
            assert payload["document"]["document_id"] == str(document.document_id)
            assert "saved_path" not in payload["document"]
            assert "sections" not in payload["document"]
            assert payload["document"]["full_text"]
        else:
            assert payload["document"] is None
        return httpx.Response(200, json={"answer": "답변", "sources": []})

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
                message="발표 내용은 무엇인가요?",
                document_id=document.document_id if with_document else None,
                response_detail="standard",
            ),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert result.agent_id == persona.agent_id
    assert result.answer == "답변"
    if with_document:
        assert result.sources
        assert result.sources[0].document_id == document.document_id
        assert result.sources[0].filename == document.filename
    else:
        assert result.sources == []


def test_v1_chat_contract_filters_sources_to_cited_chunks_only() -> None:
    # Phase 8: llm-service의 답변이 [근거 N] 마커로 인용한 청크만 sources에
    # 남아야 한다 — 검색은 됐지만 인용되지 않은 청크는 제외한다.
    persona = _persona()
    document = _document().model_copy(update={
        "sections": [
            DocumentSection(index=1, text="첫 구간 내용"),
            DocumentSection(index=2, text="둘째 구간 내용"),
        ],
    })

    async def handler(request: httpx.Request) -> httpx.Response:
        context = json.loads(request.content)["document"]["full_text"]
        assert context.startswith("[근거 1]")
        assert context.index("둘째 구간 내용") < context.index("첫 구간 내용")
        return httpx.Response(
            200, json={"answer": "둘째 구간을 인용합니다 [근거 1].", "sources": []}
        )

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()

    async def run_contract():
        await agent_repository.save(persona, OWNER_ID)
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
                message="둘째 구간이 뭔가요?",
                document_id=document.document_id,
                response_detail="standard",
            ),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert len(result.sources) == 1
    assert result.sources[0].excerpt == "둘째 구간 내용"
    assert "[근거 1]" in result.answer


def test_chat_returns_safe_answer_without_calling_llm_when_source_has_no_evidence() -> None:
    persona = _persona()
    document = _document()

    async def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("LLM must not be called without grounded context")

    async def run_contract():
        agent_repository = InMemoryAgentRepository()
        document_repository = InMemoryDocumentRepository()
        await agent_repository.save(persona, OWNER_ID)
        await document_repository.save(document, OWNER_ID)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(message="화성 토양의 염분 농도는?", document_id=document.document_id),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert "근거를 찾지 못했습니다" in result.answer
    assert result.sources == []


def test_v1_chat_omits_linked_document_for_greeting() -> None:
    persona = _persona()
    document = _document()

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["message"] == "안녕"
        assert payload["document"] is None
        return httpx.Response(200, json={"answer": "안녕하세요!", "sources": []})

    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()

    async def run_contract():
        await agent_repository.save(persona, OWNER_ID)
        await document_repository.save(document, OWNER_ID)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(message="안녕", document_id=document.document_id),
            OWNER_ID,
        )

    result = asyncio.run(run_contract())
    assert result.answer == "안녕하세요!"
    assert result.document_id == document.document_id


@pytest.mark.parametrize(
    ("detail", "expected_tokens"),
    [("concise", 512), ("standard", 1024), ("detailed", 1024)],
)
def test_v1_chat_maps_response_detail_to_safe_token_budget(
    detail: str, expected_tokens: int
) -> None:
    persona = _persona()

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["max_output_tokens"] == expected_tokens
        return httpx.Response(200, json={"answer": "답변", "sources": []})

    async def run_contract():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(persona, OWNER_ID)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agent_repository,
            InMemoryDocumentRepository(),
            InMemoryChatRepository(),
        )
        return await service.reply(
            persona.agent_id,
            ChatRequest(message="설명해 주세요.", response_detail=detail),
            OWNER_ID,
        )

    assert asyncio.run(run_contract()).answer == "답변"


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


def test_v1_client_extracts_json_without_exposing_reasoning_prefix() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "사용자의 의도를 먼저 분석합니다.\n"
                '<think>내부 사고 과정</think>\n'
                '{"answer":"최종 답변","sources":[]}'
            ),
            headers={"content-type": "text/plain"},
        )

    result = asyncio.run(
        HttpLlmClient(httpx.MockTransport(handler)).post_json("/chat", {})
    )

    assert result == {"answer": "최종 답변", "sources": []}


def test_v1_client_removes_reasoning_block_from_answer_field() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "<think>프론트에 보이면 안 되는 내용</think>\n공개 답변",
                "sources": [],
            },
        )

    result = asyncio.run(
        HttpLlmClient(httpx.MockTransport(handler)).post_json("/chat", {})
    )

    assert result["answer"] == "공개 답변"


def test_v1_client_buffers_stream_and_only_emits_public_answer() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        body = (
            'event: token\ndata: {"token":"<thi"}\n\n'
            'event: token\ndata: {"token":"nk>내부 사고</think>"}\n\n'
            'event: token\ndata: {"token":"최종 답변"}\n\n'
            "event: done\ndata: {}\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def collect() -> list[str]:
        client = HttpLlmClient(httpx.MockTransport(handler))
        return [token async for token in client.stream_sse("/chat/stream", {})]

    assert asyncio.run(collect()) == ["최종 답변"]


# llm-service/app/prompts.py의 CHUNK_LABEL_RE와 반드시 같은 형식이어야 한다.
# 두 서비스는 분리되어 있어 import로 공유할 수 없으므로 이 정규식을 여기에
# 하드코딩해 drift를 잡는다(llm-service/tests/test_prompts.py가 반대편을
# 고정한다).
_CHUNK_LABEL_RE = re.compile(r"^\[근거 (\d+)\] 파일: (.+?) / 구간 (\d+)\]?$", re.MULTILINE)


def test_combine_document_contexts_full_text_matches_llm_service_chunk_label_contract() -> None:
    documents = [
        DocumentParseResponse(
            document_id=uuid4(),
            filename="slides.pdf",
            document_type="pdf",
            saved_path=Path("private/storage/a.pdf"),
            sections=[
                DocumentSection(index=1, text="첫 구간 내용"),
                DocumentSection(index=2, text="둘째 구간 내용"),
            ],
            full_text="",
        ),
        DocumentParseResponse(
            document_id=uuid4(),
            filename="notes.pdf",
            document_type="pdf",
            saved_path=Path("private/storage/b.pdf"),
            sections=[DocumentSection(index=1, text="다른 파일 구간")],
            full_text="",
        ),
    ]

    context = combine_document_contexts(documents, 4000)

    assert context is not None
    matches = list(_CHUNK_LABEL_RE.finditer(context.full_text))
    assert len(matches) == 3
    ordinals = [int(match.group(1)) for match in matches]
    assert ordinals == [1, 2, 3]
