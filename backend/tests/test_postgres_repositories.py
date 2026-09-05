import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL이 설정된 별도 테스트 DB에서만 실행합니다.",
)
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import config  # noqa: F401 - .env를 먼저 불러옵니다.
from app.db.database import init_db
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.agent_all_dc import AgentDataSourceType
from app.models.persona import PersonaProfile
from app.models.review import ReviewFeedback, ReviewResult
from app.repositories.agent_repository import PostgresAgentRepository
from app.repositories.agent_all_dc_repository import PostgresAgentAllDcRepository
from app.repositories.document_repository import PostgresDocumentRepository
from app.repositories.review_repository import PostgresReviewRepository
from app.repositories.user_repository import PostgresUserRepository


@pytest.mark.asyncio
async def test_postgres_repositories_save_and_get() -> None:
    await init_db()
    user = await PostgresUserRepository().create(
        f"repocheck_{uuid4().hex[:8]}",
        "test-password-hash",
    )

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
    agent_data_repository = PostgresAgentAllDcRepository()

    await agent_repository.save(agent, user.user_id)
    await document_repository.save(document, user.user_id)
    await review_repository.save(review, user.user_id)
    agent_data = await agent_data_repository.upsert(
        agent_id=agent.agent_id,
        owner_id=user.user_id,
        source_type=AgentDataSourceType.AGENT,
        source_id=agent.agent_id,
        data={"name": agent.name},
    )

    assert await agent_repository.get(agent.agent_id, user.user_id) == agent
    assert await document_repository.get(document.document_id, user.user_id) == document
    assert await review_repository.get(review.review_id, user.user_id) == review
    assert await agent_data_repository.get(agent_data.record_id, user.user_id) == agent_data
    assert await agent_data_repository.list(agent.agent_id, user.user_id) == [agent_data]

    updated_agent_data = await agent_data_repository.upsert(
        agent_id=agent.agent_id,
        owner_id=user.user_id,
        source_type=AgentDataSourceType.AGENT,
        source_id=agent.agent_id,
        data={"name": agent.name, "updated": True},
    )
    assert updated_agent_data.record_id == agent_data.record_id
    assert updated_agent_data.data["updated"] is True
    assert updated_agent_data.updated_at >= agent_data.updated_at

    with pytest.raises(DBAPIError, match="source does not exist"):
        await agent_data_repository.upsert(
            agent_id=agent.agent_id,
            owner_id=user.user_id,
            source_type=AgentDataSourceType.AGENT,
            source_id=uuid4(),
            data={},
        )

    other_user = await PostgresUserRepository().create(
        f"repocheck_{uuid4().hex[:8]}",
        "test-password-hash",
    )
    with pytest.raises(DBAPIError, match="agent and owner do not match"):
        await agent_data_repository.upsert(
            agent_id=agent.agent_id,
            owner_id=other_user.user_id,
            source_type=AgentDataSourceType.AGENT,
            source_id=agent.agent_id,
            data={},
        )

    assert await agent_repository.set_deleted(
        agent.agent_id, user.user_id, deleted=True
    ) is not None
    assert await agent_repository.permanently_delete(agent.agent_id, user.user_id) is True
    assert await agent_repository.get(agent.agent_id, user.user_id) is None
    assert await review_repository.get(review.review_id, user.user_id) is None
    assert await agent_data_repository.get(agent_data.record_id, user.user_id) is None
