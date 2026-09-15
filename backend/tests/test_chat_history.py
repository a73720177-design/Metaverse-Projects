import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaProfile
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.chat_repository import InMemoryChatRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.services.chat_service import ChatService


OWNER_ID = uuid4()
AGENT_ID = uuid4()
OTHER_AGENT_ID = uuid4()
DOCUMENT_ID = UUID("22222222-2222-2222-2222-222222222222")


def _persona() -> PersonaProfile:
    return PersonaProfile(
        agent_id=AGENT_ID,
        name="근거 중심 평가자",
        description="비교 실험과 출처를 중요하게 평가한다.",
    )


def _document() -> DocumentParseResponse:
    sections = [
        DocumentSection(index=1, text="소개와 프로젝트 배경 " * 50),
        DocumentSection(index=2, text="매출 성장률은 25퍼센트이며 고객 수가 증가했다. " * 50),
        DocumentSection(index=3, text="향후 개발 일정과 결론 " * 50),
    ]
    return DocumentParseResponse(
        document_id=DOCUMENT_ID,
        filename="slides.pptx",
        document_type="pptx",
        saved_path=Path("slides.pptx"),
        sections=sections,
        full_text="\n".join(section.text for section in sections),
    )


class RecordingChatGenerator:
    """History가 실제로 LLM 호출부까지 전달되는지 기록하는 테스트 더블."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[ChatTurn], DocumentParseResponse | None]] = []

    async def generate(self, persona, request: ChatRequest, document, history) -> dict:
        self.calls.append((request.message, history, document))
        return {"answer": f"답변: {request.message}", "sources": []}


def test_list_recent_returns_oldest_first_and_excludes_deleted_and_other_agents() -> None:
    async def run() -> list:
        repo = InMemoryChatRepository()
        from app.models.chat import ChatHistoryItem

        for i in range(3):
            await repo.save(
                ChatHistoryItem(
                    message_id=uuid4(),
                    owner_id=OWNER_ID,
                    agent_id=AGENT_ID,
                    answer=f"answer-{i}",
                    message=f"message-{i}",
                )
            )
        # Trashed turn must never leak into history.
        trashed = ChatHistoryItem(
            message_id=uuid4(),
            owner_id=OWNER_ID,
            agent_id=AGENT_ID,
            answer="trashed-answer",
            message="trashed-message",
        )
        await repo.save(trashed)
        await repo.set_deleted(trashed.message_id, OWNER_ID, deleted=True)
        # A different agent's chat must never leak in either.
        await repo.save(
            ChatHistoryItem(
                message_id=uuid4(),
                owner_id=OWNER_ID,
                agent_id=OTHER_AGENT_ID,
                answer="other-agent-answer",
                message="other-agent-message",
            )
        )
        return await repo.list_recent(OWNER_ID, AGENT_ID, limit=2)

    recent = asyncio.run(run())
    assert [item.message for item in recent] == ["message-1", "message-2"]


def test_reply_sends_prior_turns_as_history_in_chronological_order() -> None:
    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        generator = RecordingChatGenerator()
        service = ChatService(
            generator,
            agent_repository,
            InMemoryDocumentRepository(),
            InMemoryChatRepository(),
        )
        await service.reply(AGENT_ID, ChatRequest(message="첫 질문"), OWNER_ID)
        await service.reply(AGENT_ID, ChatRequest(message="두 번째 질문"), OWNER_ID)
        return generator.calls

    calls = asyncio.run(run())
    assert calls[0][0] == "첫 질문"
    assert calls[0][1] == []  # no prior turns yet

    second_message, second_history, _ = calls[1]
    assert second_message == "두 번째 질문"
    assert second_history == [
        ChatTurn(role="user", content="첫 질문"),
        ChatTurn(role="assistant", content="답변: 첫 질문"),
    ]


def test_reply_rewrites_retrieval_query_so_bare_follow_up_finds_prior_topic_chunk() -> None:
    """"매출 성장률은?" 다음의 "그 수치는 왜 늘었나요?" 같은 후속 질문은 그
    자체로는 검색어가 없지만, 직전 사용자 발화를 검색어에 섞으면 올바른
    구간(매출 관련 구간)을 계속 찾아야 한다."""

    async def run():
        agent_repository = InMemoryAgentRepository()
        await agent_repository.save(_persona(), OWNER_ID)
        document_repository = InMemoryDocumentRepository()
        await document_repository.save(_document(), OWNER_ID)
        generator = RecordingChatGenerator()
        service = ChatService(
            generator,
            agent_repository,
            document_repository,
            InMemoryChatRepository(),
        )
        await service.reply(
            AGENT_ID,
            ChatRequest(message="매출 성장률을 알려줘", document_id=DOCUMENT_ID),
            OWNER_ID,
        )
        await service.reply(
            AGENT_ID,
            ChatRequest(message="그 수치는 왜 늘었나요?", document_id=DOCUMENT_ID),
            OWNER_ID,
        )
        return generator.calls

    calls = asyncio.run(run())
    _, _, second_document = calls[1]
    assert second_document is not None
    assert any(section.index == 2 for section in second_document.sections)


@pytest.mark.parametrize("vector_failure", [False, True])
def test_chat_combines_explicit_and_agent_files_without_starvation(monkeypatch, vector_failure):
    from unittest.mock import AsyncMock
    from app.services.vector_rag import VectorRag

    monkeypatch.setenv("RAG_MODE", "vector" if vector_failure else "lexical")
    monkeypatch.setenv("RAG_MAX_CONTEXT_CHARS", "4000")
    monkeypatch.setattr(VectorRag, "select_context", AsyncMock(side_effect=RuntimeError("offline")))
    documents = [_document().model_copy(update={
        "document_id": uuid4(), "filename": f"reference-{i}.pdf", "document_type": "pdf",
    }) for i in range(5)]
    persona = _persona().model_copy(update={
        "document_ids": [document.document_id for document in documents[2:]],
    })
    generator = RecordingChatGenerator()

    async def run():
        agents = InMemoryAgentRepository()
        repository = InMemoryDocumentRepository()
        await agents.save(persona, OWNER_ID)
        for document in documents:
            await repository.save(document, OWNER_ID)
        service = ChatService(generator, agents, repository, InMemoryChatRepository())
        await service.reply(persona.agent_id, ChatRequest(
            message="모든 자료의 매출 성장률을 비교해줘",
            document_id=documents[0].document_id,
            document_ids=[documents[1].document_id, documents[2].document_id],
        ), OWNER_ID)

    asyncio.run(run())
    context = generator.calls[0][2]
    assert context is not None
    assert len(context.full_text) <= 4000
    assert {section.source_document_id for section in context.sections} == {
        document.document_id for document in documents
    }
    # No citation markers in this synthetic answer, so it falls back to all
    # retrieved sections (Phase 8's "no markers" fallback).
    sources = ChatService._sources("", context)
    assert all(source.page == 2 for source in sources)
    assert {source.filename for source in sources} == {document.filename for document in documents}
