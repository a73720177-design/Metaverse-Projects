from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from app.models.summary import SummaryResult, SummaryStyle
from app.db.database import get_session_factory
from app.db.tables import SummaryTable


class SummaryRepository(Protocol):
    """Backend가 DB 팀에 요구하는 요약 저장 계약입니다."""

    async def save(self, summary: SummaryResult, owner_id: UUID) -> None: ...
    async def get(self, summary_id: UUID, owner_id: UUID) -> SummaryResult | None: ...
    async def find_cached(
        self, document_id: UUID, style: SummaryStyle, agent_id: UUID | None, owner_id: UUID
    ) -> SummaryResult | None: ...


class InMemorySummaryRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._summaries: dict[UUID, tuple[UUID, SummaryResult]] = {}

    async def save(self, summary: SummaryResult, owner_id: UUID) -> None:
        self._summaries[summary.summary_id] = (owner_id, summary)

    async def get(self, summary_id: UUID, owner_id: UUID) -> SummaryResult | None:
        stored = self._summaries.get(summary_id)
        return stored[1] if stored is not None and stored[0] == owner_id else None

    async def find_cached(
        self, document_id: UUID, style: SummaryStyle, agent_id: UUID | None, owner_id: UUID
    ) -> SummaryResult | None:
        for stored_owner_id, summary in self._summaries.values():
            if (
                stored_owner_id == owner_id
                and summary.document_id == document_id
                and summary.style == style
                and summary.agent_id == agent_id
            ):
                return summary
        return None


class PostgresSummaryRepository:
    async def save(self, summary: SummaryResult, owner_id: UUID) -> None:
        data = summary.model_dump(mode="json")
        row = SummaryTable(
            summary_id=summary.summary_id,
            owner_id=owner_id,
            document_id=summary.document_id,
            agent_id=summary.agent_id,
            style=summary.style.value,
            summary=summary.summary,
            key_topics=data["key_topics"],
            outline=data["outline"],
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, summary_id: UUID, owner_id: UUID) -> SummaryResult | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(SummaryTable).where(
                    SummaryTable.summary_id == summary_id,
                    SummaryTable.owner_id == owner_id,
                )
            )
        return self._to_result(row)

    async def find_cached(
        self, document_id: UUID, style: SummaryStyle, agent_id: UUID | None, owner_id: UUID
    ) -> SummaryResult | None:
        async with get_session_factory()() as session:
            conditions = [
                SummaryTable.document_id == document_id,
                SummaryTable.owner_id == owner_id,
                SummaryTable.style == style.value,
            ]
            conditions.append(
                SummaryTable.agent_id == agent_id if agent_id is not None
                else SummaryTable.agent_id.is_(None)
            )
            row = await session.scalar(select(SummaryTable).where(*conditions))
        return self._to_result(row)

    @staticmethod
    def _to_result(row: SummaryTable | None) -> SummaryResult | None:
        if row is None:
            return None
        return SummaryResult.model_validate(
            {
                "summary_id": row.summary_id,
                "document_id": row.document_id,
                "agent_id": row.agent_id,
                "style": row.style,
                "summary": row.summary,
                "key_topics": row.key_topics,
                "outline": row.outline,
                "created_at": row.created_at,
            }
        )
