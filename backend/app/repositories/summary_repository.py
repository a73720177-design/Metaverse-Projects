from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text

from app.models.summary import SummaryResult, SummaryStyle
from app.db.database import get_session_factory
from app.db.tables import SummaryTable


class SummaryRepository(Protocol):
    """Backend가 DB 팀에 요구하는 요약 저장 계약입니다."""

    async def save(self, summary: SummaryResult, owner_id: UUID) -> SummaryResult: ...
    async def get(self, summary_id: UUID, owner_id: UUID) -> SummaryResult | None: ...
    async def find_cached(
        self, document_id: UUID, style: SummaryStyle, agent_id: UUID | None, owner_id: UUID
    ) -> SummaryResult | None: ...


class InMemorySummaryRepository:
    """실제 DB 연결 전까지 사용하는 개발용 임시 저장소입니다."""

    def __init__(self) -> None:
        self._summaries: dict[UUID, tuple[UUID, SummaryResult]] = {}

    async def save(self, summary: SummaryResult, owner_id: UUID) -> SummaryResult:
        existing = await self.find_cached(
            summary.document_id, summary.style, summary.agent_id, owner_id
        )
        if existing is not None:
            summary = summary.model_copy(update={"summary_id": existing.summary_id})
        self._summaries[summary.summary_id] = (owner_id, summary)
        return summary

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

    async def remove_agent(self, agent_id, owner_id):
        self._summaries = {key: (o, s) for key, (o, s) in self._summaries.items()
                           if not (o == owner_id and s.agent_id == agent_id)}

    async def remove_document(self, document_id, owner_id):
        self._summaries = {key: (o, s) for key, (o, s) in self._summaries.items()
                           if not (o == owner_id and s.document_id == document_id)}


class PostgresSummaryRepository:
    async def save(self, summary: SummaryResult, owner_id: UUID) -> SummaryResult:
        data = summary.model_dump(mode="json")
        values = dict(
            summary_id=summary.summary_id,
            owner_id=owner_id,
            document_id=summary.document_id,
            agent_id=summary.agent_id,
            style=summary.style.value,
            summary=summary.summary,
            key_topics=data["key_topics"],
            outline=data["outline"],
            # Keep generation metadata in the existing JSON coverage column;
            # legacy rows remain readable without a schema migration.
            coverage={**(data["coverage"] or {}),
                      "generation_assessment": data["assessment"],
                      "generation_warnings": data["warnings"]},
            created_at=summary.created_at,
        )
        async with get_session_factory()() as session:
            async with session.begin():
                # NULL agent_id is not unique under migration 010. Serialize the
                # logical cache key across workers, including no-persona summaries.
                cache_key = f"summary:{owner_id}:{summary.document_id}:{summary.agent_id}:{summary.style.value}"
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": cache_key},
                )
                row = await session.scalar(
                    self._cached_query(summary.document_id, summary.style, summary.agent_id, owner_id)
                )
                if row is None:
                    row = SummaryTable(**values)
                    session.add(row)
                else:
                    values.pop("summary_id")
                    for field, value in values.items():
                        setattr(row, field, value)
                await session.flush()
                saved = self._to_result(row)
        assert saved is not None
        return saved

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
            row = await session.scalar(self._cached_query(document_id, style, agent_id, owner_id))
        return self._to_result(row)

    @staticmethod
    def _cached_query(document_id: UUID, style: SummaryStyle, agent_id: UUID | None, owner_id: UUID):
        return (
            select(SummaryTable)
            .where(
                SummaryTable.document_id == document_id,
                SummaryTable.owner_id == owner_id,
                SummaryTable.style == style.value,
                SummaryTable.agent_id == agent_id,
            )
            .order_by(SummaryTable.created_at.desc(), SummaryTable.summary_id.desc())
            .limit(1)
        )

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
                "coverage": row.coverage if row.coverage and "total_chunks" in row.coverage else None,
                "assessment": (row.coverage or {}).get("generation_assessment"),
                "warnings": (row.coverage or {}).get("generation_warnings", []),
                "created_at": row.created_at,
            }
        )
