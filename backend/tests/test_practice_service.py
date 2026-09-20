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
    async def generate(self, persona, document, instructions, **kwargs):
        assert "[발표 자료:" in document.full_text
        if persona.document_ids:
            assert "[질문자 참고자료:" in document.full_text
        assert "최대 5개" in instructions
        return {
            "questions": [{"question": "발표 자료에서 전환율 개선을 검증한 방법은 무엇입니까?", "presentation_evidence_ids": ["e1"], "focus": "검증"}]
        }


def _document(name: str) -> DocumentParseResponse:
    return DocumentParseResponse(
        filename=name,
        document_type="pdf",
        saved_path=Path(name),
        sections=[DocumentSection(index=1, text=f"{name} 본문은 전환율 개선을 검증하기 위해 사용자 실험을 수행했습니다.")],
        full_text=f"{name} 본문은 전환율 개선을 검증하기 위해 사용자 실험을 수행했습니다.",
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
    assert len(response.results[0].questions) == 1
    assert len(response.results[1].questions) == 1
    assert response.session_id is not None
    assert all("avatar_data_url" not in result.model_dump() for result in response.results)
    assert len(response.results[0].questions[0].sources) == 1
    assert all(s.document_id != reference.document_id for r in response.results for q in r.questions for s in q.sources)


@pytest.mark.parametrize("limit, expected_peak", [(1, 1), (2, 2)])
def test_expected_question_http_calls_respect_persona_concurrency_limit(
    limit: int, expected_peak: int, monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.practice_service.vector_enabled", lambda: False)
    class ConcurrencyGenerator:
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def generate(self, persona, document, instructions, **kwargs):
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
            generator, agents, documents, max_concurrent_personas=limit
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id for persona in personas],
                presentation_document_ids=[presentation.document_id],
            ),
            owner_id,
        )

    asyncio.run(run())
    assert generator.peak == expected_peak


def test_expected_questions_reject_more_than_four_personas() -> None:
    with pytest.raises(ValidationError):
        ExpectedQuestionRequest(
            persona_ids=[uuid4() for _ in range(5)],
            presentation_document_ids=[uuid4()],
        )


def test_expected_questions_do_not_replace_placeholder_model_output() -> None:
    class PlaceholderGenerator:
        async def generate(self, persona, document, instructions, **kwargs):
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
    assert questions == []
    assert all(len(item.question) >= 12 for item in questions)
    assert all("Question " not in item.question for item in questions)


def test_expected_questions_limit_large_context_with_lexical_rag(monkeypatch) -> None:
    captured = {}

    class CapturingGenerator:
        async def generate(self, persona, document, instructions, **kwargs):
            captured["document"] = document
            captured["model"] = kwargs["model"]
            return {"questions": []}

    monkeypatch.setattr("app.services.practice_service.vector_enabled", lambda: False)
    owner_id = uuid4()
    agent_repository = InMemoryAgentRepository()
    document_repository = InMemoryDocumentRepository()
    document = DocumentParseResponse(
        filename="긴발표.pdf",
        document_type="pdf",
        saved_path=Path("긴발표.pdf"),
        sections=[DocumentSection(index=1, text="핵심 검증 근거를 사용자 실험으로 구체적으로 확인했습니다. " * 2000)],
        full_text="핵심 검증 근거를 사용자 실험으로 구체적으로 확인했습니다. " * 2000,
    )
    persona = PersonaProfile(name="검증자", description="핵심 근거를 검증한다")

    async def run():
        await document_repository.save(document, owner_id)
        await agent_repository.save(persona, owner_id)
        await PracticeService(
            CapturingGenerator(), agent_repository, document_repository
        ).generate_expected_questions(
            ExpectedQuestionRequest(
                model="qwen3.5:9b",
                persona_ids=[persona.agent_id],
                presentation_document_ids=[document.document_id],
            ),
            owner_id,
        )

    asyncio.run(run())
    assert len(captured["document"].full_text) <= 4000
    assert captured["model"] == "qwen3.5:9b"
    assert len(captured["document"].sections) <= 8


def test_large_presentation_does_not_push_out_persona_reference(monkeypatch) -> None:
    captured = {}

    class CapturingGenerator:
        async def generate(self, persona, document, instructions, **kwargs):
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
        sections=[DocumentSection(index=1, text="발표 본문에서는 사용자 실험으로 효과를 확인했습니다. " * 5000)],
        full_text="발표 본문에서는 사용자 실험으로 효과를 확인했습니다. " * 5000,
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
        async def generate(self, persona, document, instructions, **kwargs):
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


def test_invalid_reference_ids_are_rejected_but_personas_keep_independent_questions(monkeypatch):
    monkeypatch.setattr('app.services.practice_service.vector_enabled', lambda: False)
    calls = []
    class Generator:
        async def generate(self, persona, document, instructions, **kwargs):
            calls.append(kwargs)
            return {'questions': [
                {'question': '교수논문.pdf 본문에 대한 잘못된 질문입니다?', 'presentation_evidence_ids': ['e2'], 'focus': '참고자료'},
                {'question': '사업계획.pdf 본문에서 근거를 검증한 방법은 무엇입니까?', 'presentation_evidence_ids': ['invalid'], 'focus': '없는 근거'},
                {'question': '전환율 개선 효과를 사용자 실험으로 검증한 절차는 무엇입니까?', 'presentation_evidence_ids': ['e1'], 'focus': '근거 검증'},
            ]}
    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        presentation, reference = _document('사업계획.pdf'), _document('교수논문.pdf')
        await docs.save(presentation, owner)
        await docs.save(reference, owner)
        personas = [PersonaProfile(name=name, document_ids=[reference.document_id]) for name in ['교수', '투자자']]
        for persona in personas:
            await agents.save(persona, owner)
        response = await PracticeService(Generator(), agents, docs).generate_expected_questions(
            ExpectedQuestionRequest(persona_ids=[p.agent_id for p in personas], presentation_document_ids=[presentation.document_id], question_count_per_persona=1), owner)
        questions = [q for r in response.results for q in r.questions]
        assert len(questions) == 2
        assert all(s.document_id == presentation.document_id for q in questions for s in q.sources)
        assert all(q.origin == 'model' for q in questions)
        assert all(result.status == 'complete' for result in response.results)
    asyncio.run(run())


def test_similar_but_distinct_questions_do_not_starve_later_persona(monkeypatch):
    monkeypatch.setattr('app.services.practice_service.vector_enabled', lambda: False)

    class Generator:
        async def generate(self, persona, document, instructions, **kwargs):
            suffix = "측정 지표" if persona.name == "교수" else "측정 기준"
            return {'questions': [{
                'question': f'전환율 개선 사용자 실험 검증 절차와 {suffix}는 무엇입니까?',
                'presentation_evidence_ids': ['e1'],
                'focus': suffix,
            }]}

    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        presentation = _document('사업계획.pdf')
        personas = [PersonaProfile(name='교수'), PersonaProfile(name='투자자')]
        await docs.save(presentation, owner)
        for persona in personas:
            await agents.save(persona, owner)
        return await PracticeService(
            Generator(), agents, docs, max_concurrent_personas=2
        ).generate_expected_questions(ExpectedQuestionRequest(
            persona_ids=[persona.agent_id for persona in personas],
            presentation_document_ids=[presentation.document_id],
            question_count_per_persona=1,
        ), owner)

    response = asyncio.run(run())
    assert [result.generated_count for result in response.results] == [1, 1]
    assert all(result.status == 'complete' for result in response.results)


def test_generic_questions_are_rejected_and_specific_retry_is_accepted(monkeypatch):
    monkeypatch.setattr('app.services.practice_service.vector_enabled', lambda: False)
    calls = []

    class Generator:
        async def generate(self, persona, document, instructions, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {'questions': [{
                    'question': '발표 자료의 근거와 검증 방법을 구체적으로 설명해 주시겠습니까?',
                    'presentation_evidence_ids': ['e1'],
                    'focus': '근거 검증',
                }]}
            return {'questions': [{
                'question': '전환율 개선 효과를 사용자 실험에서 어떤 지표로 측정했습니까?',
                'presentation_evidence_ids': ['e1'],
                'focus': '전환율 측정 지표',
            }]}

    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        presentation = _document('사업계획.pdf')
        persona = PersonaProfile(name='투자자')
        await docs.save(presentation, owner)
        await agents.save(persona, owner)
        return await PracticeService(Generator(), agents, docs).generate_expected_questions(
            ExpectedQuestionRequest(
                persona_ids=[persona.agent_id],
                presentation_document_ids=[presentation.document_id],
                question_count_per_persona=1,
            ), owner)

    result = asyncio.run(run()).results[0]
    assert [question.question for question in result.questions] == [
        '전환율 개선 효과를 사용자 실험에서 어떤 지표로 측정했습니까?'
    ]
    assert calls[1]['excluded_questions'] == [
        '발표 자료의 근거와 검증 방법을 구체적으로 설명해 주시겠습니까?'
    ]


def test_overview_includes_first_middle_last_pages_and_reports_coverage(monkeypatch):
    monkeypatch.setattr('app.services.practice_service.vector_enabled', lambda: False)
    seen = []
    class Generator:
        async def generate(self, persona, document, instructions, **kwargs):
            seen.append(document.full_text)
            return {'questions': []}
    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        sections = [
            DocumentSection(
                index=i + 1,
                text=f'페이지{i} 프로젝트 성과 검증을 위한 구체적인 핵심 근거와 측정 결과 ' * 100,
            )
            for i in range(101)
        ]
        document = _document('긴발표.pdf').model_copy(update={'sections': sections, 'full_text': '\n'.join(s.text for s in sections)})
        persona = PersonaProfile(name='평가자')
        await agents.save(persona, owner)
        await docs.save(document, owner)
        response = await PracticeService(Generator(), agents, docs).generate_expected_questions(
            ExpectedQuestionRequest(persona_ids=[persona.agent_id], presentation_document_ids=[document.document_id]), owner)
        coverage = response.results[0].coverage
        assert coverage.truncated and coverage.total_chunks == 101 and coverage.analyzed_chunks == 3
    asyncio.run(run())
    assert all(marker in seen[0] for marker in ['페이지0 ', '페이지50 ', '페이지100 '])


def test_heading_only_material_returns_zero_without_model_call(monkeypatch):
    monkeypatch.setattr('app.services.practice_service.vector_enabled', lambda: False)
    class Generator:
        async def generate(self, *args, **kwargs):
            raise AssertionError('No useful evidence: do not call model')
    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        doc = _document('표지.pdf').model_copy(update={
            'sections': [DocumentSection(index=1, text='목차\n소개\n감사합니다')],
            'full_text': '목차\n소개\n감사합니다'})
        persona = PersonaProfile(name='평가자')
        await agents.save(persona, owner)
        await docs.save(doc, owner)
        service = PracticeService(Generator(), agents, docs)
        response = await service.generate_expected_questions(ExpectedQuestionRequest(
            persona_ids=[persona.agent_id], presentation_document_ids=[doc.document_id]), owner)
        result = response.results[0]
        assert result.questions == []
        assert result.requested_count == 5 and result.generated_count == 0
        assert result.assessment.output_limit == 0
        assert result.status == 'partial' and result.warnings
        restored = await service.get_session(response.session_id, owner)
        assert restored.response.results[0].assessment == result.assessment
    asyncio.run(run())
