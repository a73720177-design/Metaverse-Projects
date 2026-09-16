import asyncio
import os
from pathlib import Path
from uuid import uuid4
import pytest
from app.models.persona import PersonaProfile
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.review import ReviewResult, ReviewFeedback
from app.models.summary import SummaryResult, SummaryStyle
from app.models.chat import ChatHistoryItem, Grounding
from app.models.coverage import Coverage
from app.models.practice import PracticeSession, ExpectedQuestionRequest, ExpectedQuestionResponse
from app.repositories.agent_repository import InMemoryAgentRepository, PostgresAgentRepository
from app.repositories.document_repository import InMemoryDocumentRepository, PostgresDocumentRepository
from app.repositories.review_repository import InMemoryReviewRepository, PostgresReviewRepository
from app.repositories.chat_repository import InMemoryChatRepository, PostgresChatRepository
from app.repositories.summary_repository import InMemorySummaryRepository, PostgresSummaryRepository
from app.repositories.practice_repository import InMemoryPracticeRepository, PostgresPracticeRepository


@pytest.mark.parametrize('mode', ['memory', 'postgres'])
def test_metadata_owner_isolation_and_permanent_delete_policy(mode, monkeypatch):
    if mode == 'postgres' and not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('별도 TEST_DATABASE_URL이 필요합니다.')
    async def run():
        if mode == 'postgres':
            from app.db.database import init_db, close_db
            from app.repositories.user_repository import PostgresUserRepository
            monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
            await close_db()
            await init_db()
            owner = (await PostgresUserRepository().create(f'policy_{uuid4().hex[:10]}', 'test-hash')).user_id
            agents, documents, reviews, chats, summaries, practices = (PostgresAgentRepository(), PostgresDocumentRepository(), PostgresReviewRepository(), PostgresChatRepository(), PostgresSummaryRepository(), PostgresPracticeRepository())
        else:
            owner = uuid4()
            reviews, chats, summaries, practices = InMemoryReviewRepository(), InMemoryChatRepository(), InMemorySummaryRepository(), InMemoryPracticeRepository()
            agents = InMemoryAgentRepository((reviews, chats, summaries))
            documents = InMemoryDocumentRepository(reviews, (chats, summaries))
        persona = PersonaProfile(name='평가자')
        document = DocumentParseResponse(filename='자료.pdf', document_type='pdf', saved_path=Path('unused'), sections=[DocumentSection(index=1, text='근거')], full_text='근거')
        coverage = Coverage(total_chunks=10, analyzed_chunks=3, truncated=True, selection_method='even_sample')
        await agents.save(persona, owner)
        await documents.save(document, owner)
        review = ReviewResult(agent_id=persona.agent_id, document_id=document.document_id, feedback=ReviewFeedback(positive='좋음', negative='보완'), coverage=coverage)
        summary = SummaryResult(agent_id=persona.agent_id, document_id=document.document_id, style=SummaryStyle.BRIEF, summary='요약', coverage=coverage)
        chat = ChatHistoryItem(agent_id=persona.agent_id, owner_id=owner, document_id=document.document_id, message='질문', answer='답변', grounding=Grounding(score=.4, unsupported=['미확인'], checked=True))
        practice = PracticeSession(request=ExpectedQuestionRequest(persona_ids=[persona.agent_id], presentation_document_ids=[document.document_id]), response=ExpectedQuestionResponse(results=[]))
        await reviews.save(review, owner)
        await summaries.save(summary, owner)
        await chats.save(chat)
        await practices.save(practice, owner)
        assert (await reviews.get(review.review_id, owner)).coverage == coverage
        assert (await summaries.get(summary.summary_id, owner)).coverage == coverage
        assert (await chats.list(owner, deleted=False))[0].grounding == chat.grounding
        assert (await practices.get(practice.session_id, owner)) == practice
        assert await practices.get(practice.session_id, uuid4()) is None
        assert await reviews.list(uuid4()) == []
        assert await documents.is_referenced(document.document_id, owner)
        await agents.set_deleted(persona.agent_id, owner, deleted=True)
        assert await reviews.get(review.review_id, owner) is not None
        assert await agents.permanently_delete(persona.agent_id, owner)
        assert await reviews.get(review.review_id, owner) is None
        assert await summaries.get(summary.summary_id, owner) is None
        assert await summaries.find_cached(document.document_id, SummaryStyle.BRIEF, None, owner) is None
        assert await chats.list(owner, deleted=False) == []
        assert not await documents.is_referenced(document.document_id, owner)
        assert await documents.delete(document.document_id, owner) is not None
        if mode == 'postgres':
            await close_db()
    asyncio.run(run())
