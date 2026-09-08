import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaProfile
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.chat_repository import InMemoryChatRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.services.chat_service import ChatService
from app.services.grounding_service import GroundingChecker


AGENT_ID = uuid4()
OWNER_ID = uuid4()


def _document() -> DocumentParseResponse:
    return DocumentParseResponse(
        document_id=uuid4(),
        filename="slides.pptx",
        document_type="pptx",
        saved_path=Path("slides.pptx"),
        sections=[
            DocumentSection(
                index=1,
                text="매출 성장률은 25퍼센트이며 고객 수가 증가했다.",
            )
        ],
        full_text="매출 성장률은 25퍼센트이며 고객 수가 증가했다.",
    )


@pytest.mark.asyncio
async def test_verbatim_quote_is_fully_grounded_without_calling_embeddings() -> None:
    client = AsyncMock()
    checker = GroundingChecker(client)

    grounding = await checker.check("매출 성장률은 25퍼센트이며 고객 수가 증가했다.", _document())

    assert grounding.score == 1.0
    assert grounding.unsupported == []
    assert grounding.checked is True
    client.embed.assert_not_called()


@pytest.mark.asyncio
async def test_fabricated_claim_is_marked_unsupported() -> None:
    client = AsyncMock()
    # The fabricated sentence embeds far from the source chunk; the source
    # chunk embeds close to itself.
    client.embed.return_value = [[1.0, 0.0], [0.0, 1.0]]
    checker = GroundingChecker(client)

    answer = "매출은 실제로는 90퍼센트나 폭증했으며 해외 지사도 열 곳으로 늘었다."
    grounding = await checker.check(answer, _document())

    assert grounding.checked is True
    assert grounding.unsupported == [answer]
    assert grounding.score == 0.0
    client.embed.assert_called_once()


@pytest.mark.asyncio
async def test_embedding_failure_falls_back_to_lexical_only_and_does_not_raise() -> None:
    client = AsyncMock()
    client.embed.side_effect = RuntimeError("embedding service offline")
    checker = GroundingChecker(client)

    answer = "매출은 실제로는 90퍼센트나 폭증했으며 해외 지사도 열 곳으로 늘었다."
    grounding = await checker.check(answer, _document())

    assert grounding.checked is False


@pytest.mark.asyncio
async def test_ambiguous_sentences_are_embedded_in_a_single_batch_call() -> None:
    client = AsyncMock()
    client.embed.return_value = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
    checker = GroundingChecker(client)

    answer = (
        "매출은 실제로는 90퍼센트나 폭증했다. "
        "해외 지사도 열 곳으로 늘어난 것으로 보인다."
    )
    await checker.check(answer, _document())

    assert client.embed.call_count == 1


def _persona() -> PersonaProfile:
    return PersonaProfile(
        agent_id=AGENT_ID,
        name="근거 중심 평가자",
        description="출처를 중요하게 평가한다.",
    )


class _StubGenerator:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def generate(self, persona, request, document, history) -> dict:
        return {"answer": self.answer, "sources": []}

    async def stream(self, persona, request, document, history):
        for token in self.answer.split(" "):
            yield token + " "


def test_grounding_mode_off_never_calls_embedding_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROUNDING_MODE", raising=False)

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _document()
        await document_repository.save(document, OWNER_ID)
        checker = GroundingChecker(AsyncMock())
        service = ChatService(
            _StubGenerator("매출 성장률은 25퍼센트이며 고객 수가 증가했다."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            grounding_checker=checker,
        )
        chat = await service.reply(
            AGENT_ID,
            ChatRequest(message="매출 성장률을 알려줘", document_id=document.document_id),
            OWNER_ID,
        )
        return chat, checker

    chat, checker = asyncio.run(run())
    assert chat.grounding is None
    checker.client.embed.assert_not_called()


def test_reply_attaches_grounding_result_in_annotate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDING_MODE", "annotate")

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _document()
        await document_repository.save(document, OWNER_ID)
        checker = GroundingChecker(AsyncMock())
        service = ChatService(
            _StubGenerator("매출 성장률은 25퍼센트이며 고객 수가 증가했다."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            grounding_checker=checker,
        )
        return await service.reply(
            AGENT_ID,
            ChatRequest(message="매출 성장률을 알려줘", document_id=document.document_id),
            OWNER_ID,
        )

    chat = asyncio.run(run())
    assert chat.grounding is not None
    assert chat.grounding.score == 1.0
    # annotate must not touch the visible answer text.
    assert chat.answer == "매출 성장률은 25퍼센트이며 고객 수가 증가했다."


def test_strict_mode_appends_notice_when_score_is_low(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDING_MODE", "strict")

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _document()
        await document_repository.save(document, OWNER_ID)
        client = AsyncMock()
        client.embed.return_value = [[1.0, 0.0], [0.0, 1.0]]
        checker = GroundingChecker(client)
        service = ChatService(
            _StubGenerator("매출은 실제로는 90퍼센트나 폭증했으며 해외 지사도 열 곳으로 늘었다."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            grounding_checker=checker,
        )
        return await service.reply(
            AGENT_ID,
            ChatRequest(message="매출 성장률을 알려줘", document_id=document.document_id),
            OWNER_ID,
        )

    chat = asyncio.run(run())
    assert chat.grounding.score == 0.0
    assert "확인되지 않았습니다" in chat.answer


def test_stream_done_event_includes_grounding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDING_MODE", "annotate")

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _document()
        await document_repository.save(document, OWNER_ID)
        checker = GroundingChecker(AsyncMock())
        service = ChatService(
            _StubGenerator("매출 성장률은 25퍼센트이며 고객 수가 증가했다."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            grounding_checker=checker,
        )
        events = [
            event
            async for event in await service.open_stream(
                AGENT_ID,
                ChatRequest(message="매출 성장률을 알려줘", document_id=document.document_id),
                OWNER_ID,
            )
        ]
        return events

    events = asyncio.run(run())
    done = next(event for event in events if event["event"] == "done")
    assert done["data"]["grounding"] is not None
    assert done["data"]["grounding"]["score"] == 1.0
