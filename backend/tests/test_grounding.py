import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.chat import ChatRequest, ChatTurn, Grounding
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


# --- Phase 8: 인용 마커 기반 sources 필터 + grounding 보정 -------------------


_MULTI_SECTION_QUERY = "발표 자료 요약을 알려줘"


def _multi_section_document() -> DocumentParseResponse:
    # 두 구간 모두 검색 쿼리(_MULTI_SECTION_QUERY)와 겹치는 토큰("발표",
    # "자료", "요약")을 갖고 있어야 DocumentContextSelector가 둘 다
    # 골라온다 — 그래야 "실제로 인용된 것만 sources에 남는지"가 검증된다.
    # 토큰이 안 겹치면 BM25 점수가 0이라 애초에 후보에서 빠진다.
    return _document().model_copy(update={
        "sections": [
            DocumentSection(
                index=1,
                text="발표 자료 요약: 매출 성장률은 25퍼센트이며 고객 수가 증가했다.",
            ),
            DocumentSection(
                index=2,
                text="발표 자료 요약: 해외 지사는 세 곳으로 늘었다.",
            ),
        ],
    })


class _RecordingGroundingChecker:
    """근거 채점기에 실제로 전달된 answer 텍스트를 기록하는 테스트 더블."""

    def __init__(self) -> None:
        self.received_answer: str | None = None

    async def check(self, answer: str, document: DocumentParseResponse) -> Grounding:
        self.received_answer = answer
        return Grounding(score=1.0, unsupported=[], checked=True)


def test_reply_filters_sources_to_cited_chunk_only() -> None:
    class CitingGenerator(_StubGenerator):
        async def stream(self, persona, request, document, history):
            ordinal = next(i for i, section in enumerate(document.sections, 1)
                           if "매출 성장률" in section.text)
            yield f"매출 성장률은 25퍼센트입니다 [근거 {ordinal}]."

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _multi_section_document()
        await document_repository.save(document, OWNER_ID)
        service = ChatService(
            CitingGenerator(""),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        return await service.open_stream(
            AGENT_ID,
            ChatRequest(message=_MULTI_SECTION_QUERY, document_id=document.document_id),
            OWNER_ID,
        )

    async def collect():
        return [event async for event in await run()]

    events = asyncio.run(collect())
    done = next(event for event in events if event["event"] == "done")
    sources = done["data"]["sources"]
    assert len(sources) == 1
    assert sources[0]["excerpt"] == "발표 자료 요약: 매출 성장률은 25퍼센트이며 고객 수가 증가했다."


def test_reply_drops_out_of_range_marker_from_visible_answer() -> None:
    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _multi_section_document()
        await document_repository.save(document, OWNER_ID)
        service = ChatService(
            # 청크는 2개인데 존재하지 않는 [근거 9]를 지어낸 경우.
            _StubGenerator("근거는 [근거 9]에 있습니다."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        return await service.open_stream(
            AGENT_ID,
            ChatRequest(message=_MULTI_SECTION_QUERY, document_id=document.document_id),
            OWNER_ID,
        )

    async def collect():
        return [event async for event in await run()]

    events = asyncio.run(collect())
    done = next(event for event in events if event["event"] == "done")
    assert "[근거 9]" not in done["data"]["answer"]
    # 유효한 마커가 하나도 없으니 검색된 청크 전부로 폴백한다.
    assert len(done["data"]["sources"]) == 2


def test_grounding_check_receives_answer_without_citation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROUNDING_MODE", "annotate")

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        document = _multi_section_document()
        await document_repository.save(document, OWNER_ID)
        checker = _RecordingGroundingChecker()
        service = ChatService(
            _StubGenerator("매출 성장률은 25퍼센트입니다 [근거 1]."),
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
            grounding_checker=checker,
        )
        chat = await service.reply(
            AGENT_ID,
            ChatRequest(message=_MULTI_SECTION_QUERY, document_id=document.document_id),
            OWNER_ID,
        )
        return chat, checker

    chat, checker = asyncio.run(run())
    # 채점용 사본에는 마커가 없어야 하지만, 사용자에게 보이는/저장되는
    # answer에는 마커가 그대로 남아 있어야 한다.
    assert checker.received_answer is not None
    assert "[근거" not in checker.received_answer
    assert "[근거 1]" in chat.answer
