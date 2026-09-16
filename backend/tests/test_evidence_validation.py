"""Regression cases for fabricated citations and missing reference material."""
import asyncio
from pathlib import Path
from uuid import uuid4

from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.review import ReviewResult, ReviewCreateRequest
from app.repositories.agent_repository import InMemoryAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository
from app.services.persona_service import PersonaService
from app.services.review_service import ReviewService
from app.services.source_evidence import select_excerpts, verified_sources


def document(text="실험 참가자 20명의 정확도는 80%로 측정했습니다."):
    return DocumentParseResponse(filename="발표.pdf", document_type="pdf", saved_path=Path("unused"),
                                 sections=[DocumentSection(index=1, text=text)], full_text=text)


def source(doc, **updates):
    return {"filename": doc.filename, "page": 1, "excerpt": doc.full_text, **updates}


def test_review_rejects_fabricated_sources_and_persists_verified_feedback():
    doc = document()
    valid = source(doc)
    class Generator:
        async def generate(self, *args):
            return {
                "claims": [
                    {"claim": "정확도는 80%입니다.", "verdict": "supported", "confidence": .9,
                     "sources": [valid]},
                    {"claim": "정확도는 99%입니다.", "verdict": "supported", "confidence": .9,
                     "sources": [valid]},
                    {"claim": "매출이 증가했습니다.", "verdict": "supported", "confidence": .9,
                     "sources": [source(doc, excerpt="매출이 증가했습니다.")]},
                ],
                "feedback": {"positive": "참가자 20명의 측정 결과를 제시했습니다.",
                             "positive_sources": [valid],
                             "negative": "실험 참가자 100명이 부족합니다.", "negative_sources": [valid]},
                "questions": ["실험 참가자 20명의 선정 기준은 무엇입니까?", "정확도 99%의 근거는 무엇입니까?"],
            }
    async def run():
        owner = uuid4()
        agents, docs, reviews = InMemoryAgentRepository(), InMemoryDocumentRepository(), InMemoryReviewRepository()
        persona = PersonaProfile(name="평가자")
        await agents.save(persona, owner)
        await docs.save(doc, owner)
        service = ReviewService(Generator(), reviews, agents, docs)
        result = await service.create(persona.agent_id, ReviewCreateRequest(document_id=doc.document_id), owner)
        assert (await service.get(result.review_id, owner)) == result
        return result
    result = asyncio.run(run())
    assert result.claims[0].verdict == "supported"
    assert result.claims[0].sources[0].document_id == doc.document_id
    assert all(c.verdict == "insufficient_evidence" for c in result.claims[1:])
    assert result.claims[2].sources == []
    assert "20명" in result.feedback.positive
    assert "보류" in result.feedback.negative
    assert result.feedback.source_check_performed
    assert result.feedback.verification_warnings
    assert len(result.questions) == 1


def test_source_checks_reject_wrong_file_page_owner_and_empty_quote():
    from app.models.review import ReviewSource
    doc = document()
    candidates = [source(doc, filename="다른.pdf"), source(doc, page=2),
                  source(doc, document_id=uuid4()), source(doc, excerpt=""),
                  source(doc, excerpt="실험\n 참가자 20명의 정확도는 80%로 측정했습니다.")]
    result = verified_sources([ReviewSource(**s) for s in candidates], doc)
    assert len(result) == 1
    assert result[0].document_id == doc.document_id


def test_missing_feedback_citations_are_not_presented_as_verified_opinions():
    doc = document()
    result = ReviewResult(agent_id=uuid4(), document_id=doc.document_id,
                          feedback={"positive": "우수", "negative": "부족"})
    ReviewService._verify_review(result, doc)
    assert "보류" in result.feedback.positive and "보류" in result.feedback.negative


def test_persona_rejects_invented_quotes_and_preserves_reference_inference_on_update():
    description = "보안 검증을 중시합니다."
    ref = document("실험 설계와 재현성을 확인합니다.")
    class Generator:
        async def generate(self, request):
            return {"role": "평가자", "expertise": [
                {"value": "보안", "status": "user_stated", "confidence": .9,
                 "evidence": [{"source_id": "description", "summary": description, "confidence": .9}]},
                {"value": "금융", "status": "supported", "confidence": .9,
                 "evidence": [{"source_id": "description", "summary": "금융 전문가", "confidence": .9}]},
                {"value": "재현성", "status": "user_stated", "confidence": .9,
                 "evidence": [{"source_id": "reference_context", "summary": ref.full_text, "confidence": .9}]},
            ]}
    async def run():
        owner = uuid4()
        agents, docs = InMemoryAgentRepository(), InMemoryDocumentRepository()
        await docs.save(ref, owner)
        service = PersonaService(Generator(), agents, docs)
        request = PersonaCreateRequest(name="교수", description=description, document_ids=[ref.document_id])
        created = await service.create(request, owner)
        updated = await service.update(created.agent_id, request, owner)
        for result in [created, updated, await service.get(created.agent_id, owner)]:
            assert [t.status for t in result.expertise] == ["user_stated", "unknown", "inferred"]
            assert result.expertise[1].confidence == 0
            assert result.warnings
    asyncio.run(run())


def test_reference_budget_reaches_later_documents():
    first = document("첫 자료의 긴 내용입니다. " * 1000)
    second = document("두번째 논문의 보안 검증 기준입니다.").model_copy(update={"filename": "논문.pdf"})
    request = PersonaService._generation_request(PersonaCreateRequest(name="교수", description="보안 검증"), [first, second])
    assert "두번째 논문의 보안 검증 기준" in request.reference_context
    assert len(request.reference_context) <= 3000


def test_selector_keeps_all_short_sections_and_finds_relevant_non_anchor_page():
    doc = document().model_copy(update={"sections": [DocumentSection(index=i, text=f"페이지 {i} 일반 개요입니다.") for i in range(1, 8)]})
    assert len(select_excerpts(doc, 3000)) == 7
    sections = [DocumentSection(index=i, text=("보안 공격 검증 결과 " if i == 7 else "일반 개요 설명 ") * 100) for i in range(1, 20)]
    selected = select_excerpts(doc.model_copy(update={"sections": sections}), 3000, "보안 공격")
    assert any(s.index == 7 for s in selected)
    assert sum(len(s.text) for s in selected) <= 3000
    tail = document("일반 설명 " * 1000 + "보안 공격 검증 결과 " * 30)
    assert any("보안" in s.text for s in select_excerpts(tail, 3000, "보안 공격"))
