from pathlib import Path
from uuid import uuid4

import pytest

from app import config  # noqa: F401 - .env를 먼저 불러옵니다.
from app.db.database import init_db
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.persona import PersonaProfile
from app.models.review import ReviewFeedback, ReviewResult
from app.repositories.agent_repository import PostgresAgentRepository
from app.repositories.document_repository import PostgresDocumentRepository
from app.repositories.review_repository import PostgresReviewRepository


@pytest.mark.asyncio
async def test_postgres_repositories_save_and_get() -> None:
    await init_db()

    agent = PersonaProfile(agent_id=uuid4(), name="DB 테스트 평가자")
    document = DocumentParseResponse(
        document_id=uuid4(),
        filename="test.pdf",
        document_type="pdf",
        saved_path=Path("documents/test.pdf"),
        sections=[DocumentSection(index=1, text="테스트 문서")],
        full_text="테스트 문서",
    )
    review = ReviewResult(
        review_id=uuid4(),
        agent_id=agent.agent_id,
        document_id=document.document_id,
        feedback=ReviewFeedback(positive="좋음", negative="보완 필요"),
    )

    agent_repository = PostgresAgentRepository()
    document_repository = PostgresDocumentRepository()
    review_repository = PostgresReviewRepository()

    await agent_repository.save(agent)
    await document_repository.save(document)
    await review_repository.save(review)

    assert await agent_repository.get(agent.agent_id) == agent
    assert await document_repository.get(document.document_id) == document
    assert await review_repository.get(review.review_id) == review
