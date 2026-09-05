from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.db.database import get_session_factory
from app.db.tables import AgentAllDcTable
from app.models.agent_all_dc import AgentDataRecord, AgentDataSourceType


class AgentAllDcRepository(Protocol):
    """에이전트별 통합 자료를 소유자 범위 안에서 저장하는 계약입니다."""

    async def upsert(
        self,
        *,
        agent_id: UUID,
        owner_id: UUID,
        source_type: AgentDataSourceType,
        source_id: UUID,
        data: dict,
        source_created_at: datetime | None = None,
    ) -> AgentDataRecord: ...

    async def get(
        self, record_id: UUID, owner_id: UUID
    ) -> AgentDataRecord | None: ...

    async def list(self, agent_id: UUID, owner_id: UUID) -> list[AgentDataRecord]: ...

    async def delete(self, record_id: UUID, owner_id: UUID) -> bool: ...


def _to_model(row: AgentAllDcTable) -> AgentDataRecord:
    return AgentDataRecord.model_validate(row, from_attributes=True)


class PostgresAgentAllDcRepository:
    async def upsert(
        self,
        *,
        agent_id: UUID,
        owner_id: UUID,
        source_type: AgentDataSourceType,
        source_id: UUID,
        data: dict,
        source_created_at: datetime | None = None,
    ) -> AgentDataRecord:
        statement = insert(AgentAllDcTable).values(
            record_id=uuid4(),
            agent_id=agent_id,
            owner_id=owner_id,
            source_type=source_type.value,
            source_id=source_id,
            data=data,
            source_created_at=source_created_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["agent_id", "source_type", "source_id"],
            set_={
                "owner_id": statement.excluded.owner_id,
                "data": statement.excluded.data,
                "source_created_at": statement.excluded.source_created_at,
            },
        ).returning(AgentAllDcTable)
        async with get_session_factory()() as session:
            row = (await session.execute(statement)).scalar_one()
            await session.commit()
            return _to_model(row)

    async def get(
        self, record_id: UUID, owner_id: UUID
    ) -> AgentDataRecord | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(AgentAllDcTable).where(
                    AgentAllDcTable.record_id == record_id,
                    AgentAllDcTable.owner_id == owner_id,
                )
            )
        return _to_model(row) if row is not None else None

    async def list(self, agent_id: UUID, owner_id: UUID) -> list[AgentDataRecord]:
        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(AgentAllDcTable)
                    .where(
                        AgentAllDcTable.agent_id == agent_id,
                        AgentAllDcTable.owner_id == owner_id,
                    )
                    .order_by(AgentAllDcTable.source_created_at, AgentAllDcTable.stored_at)
                )
            ).all()
        return [_to_model(row) for row in rows]

    async def delete(self, record_id: UUID, owner_id: UUID) -> bool:
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(AgentAllDcTable).where(
                    AgentAllDcTable.record_id == record_id,
                    AgentAllDcTable.owner_id == owner_id,
                )
            )
            await session.commit()
            return bool(result.rowcount)
