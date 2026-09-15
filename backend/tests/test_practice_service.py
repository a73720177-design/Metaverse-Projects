import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaProfile
from app.models.practice import ExpectedQuestionRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.services.practice_service import PracticeService


class FakeQuestionGenerator:
    async def generate(self, persona, document, instructions):
        assert "[발표 자료:" in document.full_text
        if persona.document_ids:
            assert "[질문자 참고자료:" in document.full_text
        assert "5개" in instructions
        return {
            "questions": [f"{persona.name} 질문 {index}" for index in range(1, 7)]
        }


def _document(name: str) -> DocumentParseResponse:
    return DocumentParseResponse(
        filename=name,
        document_type="pdf",
        saved_path=Path(name),
        sections=[DocumentSection(index=1, text=f"{name} 본문")],
        full_text=f"{name} 본문",
    )


def test_expected_questions_use_multiple_documents_and_personas() -> None:
    owner_id = uuid4()
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    presentation_a = _document("발표.pdf")
    presentation_b = _document("대본.pdf")
    reference = _document("교수논문.pdf")
    professor = PersonaProfile(name="교수", document_ids=[reference.document_id])
    investor = PersonaProfile(name="투자자")

    async def run():
        for document in (presentation_a, presentation_b, reference):
            await document_repository.save(document, owner_id)
        for persona in (professor, investor):
            await agent_repository.save(persona, owner_id)
        return await PracticeService(
            FakeQuestionGenerator(), agent_repository, document_repository
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[professor.agent_id, investor.agent_id],
                presentation_document_ids=[
                    presentation_a.document_id,
                    presentation_b.document_id,
                ],
            ),
            owner_id,
        )

    response = asyncio.run(run())
    assert len(response.results) == 2
    assert all(len(result.questions) == 5 for result in response.results)
    assert all(result.avatar_data_url.startswith("data:image/svg+xml;base64,") for result in response.results)
    assert len(response.results[0].questions[0].sources) == 3


def test_expected_question_http_calls_respect_persona_concurrency_limit() -> None:
    class ConcurrencyGenerator:
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def generate(self, persona, document, instructions):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return {"questions": []}

    owner_id = uuid4()
    agents = InMemoryAgentRepository()
    documents = InMemoryDocumentRepository()
    presentation = _document("발표.pdf")
    personas = [PersonaProfile(name=f"질문자 {index}") for index in range(3)]
    generator = ConcurrencyGenerator()

    async def run():
        await documents.save(presentation, owner_id)
        for persona in personas:
            await agents.save(persona, owner_id)
        await PracticeService(
            generator, agents, documents, max_concurrent_personas=1
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id for persona in personas],
                presentation_document_ids=[presentation.document_id],
            ),
            owner_id,
        )

    asyncio.run(run())
    assert generator.peak == 1


def test_expected_questions_reject_more_than_four_personas() -> None:
    with pytest.raises(ValidationError):
        ExpectedQuestionRequest(
            persona_ids=[uuid4() for _ in range(5)],
            presentation_document_ids=[uuid4()],
        )


def test_expected_questions_replace_placeholder_model_output() -> None:
    class PlaceholderGenerator:
        async def generate(self, persona, document, instructions):
            return {"questions": ["Question 1", "질문 2", "Q3: ...", "질문 4", "질문 5"]}

    owner_id = uuid4()
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    document = _document("사업계획.pdf")
    persona = PersonaProfile(name="투자자", description="시장성과 수익성을 검증한다")

    async def run():
        await document_repository.save(document, owner_id)
        await agent_repository.save(persona, owner_id)
        return await PracticeService(
            PlaceholderGenerator(), agent_repository, document_repository
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id],
                presentation_document_ids=[document.document_id],
            ),
            owner_id,
        )

    questions = asyncio.run(run()).results[0].questions
    assert len(questions) == 5
    assert all(len(item.question) >= 12 for item in questions)
    assert all("Question " not in item.question for item in questions)


def test_expected_questions_limit_large_context_with_lexical_rag(monkeypatch) -> None:
    captured = {}

    class CapturingGenerator:
        async def generate(self, persona, document, instructions):
            captured["document"] = document
            return {"questions": []}

    monkeypatch.setattr("app.services.practice_service.vector_enabled", lambda: False)
    owner_id = uuid4()
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    document = DocumentParseResponse(
        filename="긴발표.pdf",
        document_type="pdf",
        saved_path=Path("긴발표.pdf"),
        sections=[DocumentSection(index=1, text="핵심 검증 근거 " * 2000)],
        full_text="핵심 검증 근거 " * 2000,
    )
    persona = PersonaProfile(name="검증자", description="핵심 근거를 검증한다")

    async def run():
        await document_repository.save(document, owner_id)
        await agent_repository.save(persona, owner_id)
        await PracticeService(
            CapturingGenerator(), agent_repository, document_repository
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id],
                presentation_document_ids=[document.document_id],
            ),
            owner_id,
        )

    asyncio.run(run())
    assert len(captured["document"].full_text) <= 4000
    assert len(captured["document"].sections) <= 3


def test_large_presentation_does_not_push_out_persona_reference(monkeypatch) -> None:
    captured = {}

    class CapturingGenerator:
        async def generate(self, persona, document, instructions):
            captured["text"] = document.full_text
            return {"questions": []}

    monkeypatch.setattr("app.services.practice_service.vector_enabled", lambda: False)
    owner_id = uuid4()
    agents = InMemoryAgentRepository()
    documents = InMemoryDocumentRepository()
    presentation = DocumentParseResponse(
        filename="긴발표.pdf",
        document_type="pdf",
        saved_path=Path("긴발표.pdf"),
        sections=[DocumentSection(index=1, text="발표 본문 " * 5000)],
        full_text="발표 본문 " * 5000,
    )
    reference = _document("교수의 보안평가기준.pdf")
    persona = PersonaProfile(name="교수", document_ids=[reference.document_id])

    async def run():
        await documents.save(presentation, owner_id)
        await documents.save(reference, owner_id)
        await agents.save(persona, owner_id)
        await PracticeService(CapturingGenerator(), agents, documents).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id],
                presentation_document_ids=[presentation.document_id],
            ),
            owner_id,
        )

    asyncio.run(run())
    assert "[발표 자료: 긴발표.pdf]" in captured["text"]
    assert "[질문자 참고자료: 교수의 보안평가기준.pdf]" in captured["text"]
    assert "교수의 보안평가기준.pdf 본문" in captured["text"]


def test_expected_questions_keep_bounded_overview_when_persona_terms_do_not_match(monkeypatch) -> None:
    captured = {}

    class CapturingGenerator:
        async def generate(self, persona, document, instructions):
            captured["document"] = document
            return {"questions": [{"question": "잘못된 객체"}, "какие 질문", "실제 발표 내용의 검증 방법을 구체적으로 설명해 주시겠습니까?"]}

    monkeypatch.setattr("app.services.practice_service.vector_enabled", lambda: False)
    owner_id = uuid4()
    agents = InMemoryAgentRepository()
    documents = InMemoryDocumentRepository()
    document = _document("양자역학.pdf")
    persona = PersonaProfile(name="디자인 심사위원", description="색상과 조형을 검토한다")

    async def run():
        await documents.save(document, owner_id)
        await agents.save(persona, owner_id)
        return await PracticeService(CapturingGenerator(), agents, documents).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id],
                presentation_document_ids=[document.document_id],
            ),
            owner_id,
        )

    result = asyncio.run(run())
    assert captured["document"] is not None
    assert "양자역학.pdf 본문" in captured["document"].full_text
    assert len(captured["document"].full_text) <= 4000
    assert not any(item.question.startswith("{'question'") for item in result.results[0].questions)
    assert not any("какие" in item.question for item in result.results[0].questions)
