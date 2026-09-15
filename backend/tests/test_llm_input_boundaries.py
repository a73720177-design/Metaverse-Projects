"""Validate outgoing HTTP bodies against the actual receiving service schemas.

Only model generation is stubbed; schema limits are loaded from llm-service,
so a hand-written mock cannot silently accept an invalid Backend payload.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import HttpChatGenerator, HttpPersonaGenerator
from app.models.chat import ChatRequest, ChatTurn
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaCreateRequest, PersonaProfile, PersonaUpdateRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.chat_repository import InMemoryChatRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.services.chat_service import ChatService
from app.services.persona_service import PersonaService


@pytest.fixture(scope="module")
def receiving_schema():
    path = Path(__file__).resolve().parents[2] / "llm-service/app/schemas_v1.py"
    name = "receiving_llm_input_schemas"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("message_length", [2001, 5000])
def test_long_saved_turn_can_be_followed_up(receiving_schema, monkeypatch, streaming, message_length):
    monkeypatch.setenv("GROUNDING_MODE", "off")
    owner = uuid4()
    persona = PersonaProfile(name="평가자")
    bodies = []
    long_answer = " ".join(f"검증항목{i}" for i in range(400))

    async def handler(request):
        body = json.loads(request.content)
        receiving_schema.ChatGenerationRequest.model_validate(body)
        bodies.append(body)
        answer = long_answer if len(bodies) == 1 else "추가 검증 기준입니다."
        if streaming:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=(
                "event: token\ndata: " + json.dumps({"token": answer})
                + "\n\nevent: done\ndata: {}\n\n"
            ))
        return httpx.Response(200, json={"answer": answer, "sources": []})

    async def run():
        agents = InMemoryAgentRepository()
        chats = InMemoryChatRepository()
        await agents.save(persona, owner)
        service = ChatService(
            HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler))),
            agents, InMemoryDocumentRepository(), chats,
        )
        for message in ["가" * message_length, "그 검증 기준을 설명해 주세요."]:
            request = ChatRequest(message=message)
            if streaming:
                events = [event async for event in await service.open_stream(persona.agent_id, request, owner)]
                assert events[-1]["event"] == "done"
            else:
                await service.reply(persona.agent_id, request, owner)
        saved = await chats.list_recent(owner, persona.agent_id, 2)
        assert saved[0].message == "가" * message_length
        assert saved[0].answer == long_answer

    asyncio.run(run())
    assert bodies[0]["history"] == []
    assert bodies[0]["message"] == "가" * message_length
    assert bodies[1]["history_truncated"] is True
    assert [turn["role"] for turn in bodies[1]["history"]] == ["user", "assistant"]
    assert bodies[1]["history"][-1]["content"].endswith("검증항목399")


def test_history_total_budget_and_empty_legacy_turns(receiving_schema):
    history = [ChatTurn(role="user", content=f"{i}:" + "가" * 2100) for i in range(25)]
    history.append(ChatTurn(role="assistant", content=" "))
    payload = HttpChatGenerator._history_payload(history)
    receiving_schema.ChatGenerationRequest.model_validate({
        "persona": PersonaProfile(name="평가자").model_dump(mode="json"),
        "message": "현재 질문", **payload,
    })
    assert payload["history_truncated"] is True
    assert sum(len(turn["content"]) for turn in payload["history"]) <= 12000
    assert len(payload["history"]) <= 20
    assert history[0].content.startswith("0:")  # never modify saved input


def test_max_description_with_references_create_and_update(receiving_schema):
    owner = uuid4()
    captured = []
    description = "설" * 5000
    document = DocumentParseResponse(
        filename="평가기준.pdf", document_type="pdf", saved_path=Path("unused"),
        sections=[DocumentSection(index=1, text="근거 자료")], full_text="근거 자료" * 1000,
    )

    async def handler(request):
        body = json.loads(request.content)
        receiving_schema.PersonaGenerationRequest.model_validate(body)
        captured.append(body)
        return httpx.Response(200, json={"role": "평가자", "expertise": [], "evaluation_style": []})

    async def run():
        agents, documents = InMemoryAgentRepository(), InMemoryDocumentRepository()
        await documents.save(document, owner)
        service = PersonaService(
            HttpPersonaGenerator(HttpLlmClient(httpx.MockTransport(handler))), agents, documents,
        )
        persona = await service.create(PersonaCreateRequest(
            name="평가자", description=description, document_ids=[document.document_id],
        ), owner)
        updated = await service.update(persona.agent_id, PersonaUpdateRequest(
            name="수정 평가자", description=description, document_ids=[document.document_id],
        ), owner)
        saved = await agents.get(updated.agent_id, owner)
        assert saved.description == description
        assert "reference_context" not in saved.model_dump()

    asyncio.run(run())
    assert len(captured) == 2
    for body in captured:
        assert body["description"] == description
        assert body["reference_context"].startswith("[평가기준.pdf]\n근거 자료")
        assert len(body["reference_context"]) <= 3000
        assert "document_ids" not in body


@pytest.mark.parametrize("count", [1, 5, 10])
def test_question_count_evidence_and_saved_session_round_trip(receiving_schema, monkeypatch, count):
    from app.integrations.llm.generators import HttpQuestionGenerator
    from app.models.practice import ExpectedQuestionRequest
    from app.services.practice_service import PracticeService, PracticeResourceNotFoundError
    monkeypatch.setenv("RAG_MODE", "lexical")
    owner = uuid4()
    document = DocumentParseResponse(filename="발표.pdf", document_type="pdf", saved_path=Path("unused"),
        sections=[DocumentSection(index=1, text="측정 " + " ".join(f"검증항목{i}" for i in range(10)))],
        full_text="측정 " + " ".join(f"검증항목{i}" for i in range(10)))
    persona = PersonaProfile(name="연구자", description="재현성과 측정 신뢰성을 검증한다")
    bodies = []
    async def handler(request):
        body = json.loads(request.content)
        receiving_schema.ExpectedQuestionGenerationRequest.model_validate(body)
        bodies.append(body)
        questions = [{"question": f"검증항목{i}의 조건{i}와 절차{i}가 결과{i}에 미친 영향을 설명해 주세요?",
                      "presentation_evidence_ids": ["e1"], "focus": f"검증항목{i}"} for i in range(count)]
        response = {"questions": questions}
        receiving_schema.ExpectedQuestionGenerationResponse.model_validate(response)
        return httpx.Response(200, json=response)
    async def run():
        agents, documents = InMemoryAgentRepository(), InMemoryDocumentRepository()
        await agents.save(persona, owner)
        await documents.save(document, owner)
        service = PracticeService(HttpQuestionGenerator(HttpLlmClient(httpx.MockTransport(handler))), agents, documents)
        response = await service.generate_expected_questions(ExpectedQuestionRequest(persona_ids=[persona.agent_id],
            presentation_document_ids=[document.document_id], question_count_per_persona=count), owner)
        result = response.results[0]
        assert result.requested_count == count
        assert result.generated_count == 1
        assert result.status == ("complete" if count == 1 else "partial")
        assert all(q.origin == "model" and q.sources[0].document_id == document.document_id for q in result.questions)
        saved = await service.get_session(response.session_id, owner)
        assert saved.response == response
        assert [q.conversation_id for q in saved.response.results[0].questions] == [q.conversation_id for q in result.questions]
        assert await service.list_sessions(uuid4()) == []
        with pytest.raises(PracticeResourceNotFoundError):
            await service.get_session(response.session_id, uuid4())
        await agents.set_deleted(persona.agent_id, owner, deleted=True)
        assert (await service.get_session(response.session_id, owner)).response.results == []
        await agents.set_deleted(persona.agent_id, owner, deleted=False)
        assert (await service.get_session(response.session_id, owner)).response == response
    asyncio.run(run())
    assert len(bodies) == 1
    assert bodies[0]["question_count"] == 1
