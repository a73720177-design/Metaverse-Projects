from uuid import UUID
from sqlalchemy import select
from app.db.database import get_session_factory
from app.db.tables import PracticeSessionTable
from app.models.practice import PracticeSession, PracticeSessionItem


def item(session):
    return PracticeSessionItem(session_id=session.session_id, created_at=session.created_at,
                               persona_names=[r.persona_name for r in session.response.results])


class InMemoryPracticeRepository:
    def __init__(self):
        self.sessions: dict[UUID, tuple[UUID, PracticeSession]] = {}

    async def save(self, session, owner_id):
        self.sessions[session.session_id] = (owner_id, session.model_copy(deep=True))

    async def get(self, session_id, owner_id):
        stored = self.sessions.get(session_id)
        return stored[1].model_copy(deep=True) if stored and stored[0] == owner_id else None

    async def list(self, owner_id, limit=50):
        sessions = sorted((s for o, s in self.sessions.values() if o == owner_id),
                          key=lambda s: s.created_at, reverse=True)
        return [item(s) for s in sessions[:limit]]


class PostgresPracticeRepository:
    async def save(self, session, owner_id):
        async with get_session_factory()() as db:
            db.add(PracticeSessionTable(session_id=session.session_id, owner_id=owner_id,
                                       payload=session.model_dump(mode="json"), created_at=session.created_at))
            await db.commit()

    async def get(self, session_id, owner_id):
        async with get_session_factory()() as db:
            row = await db.scalar(select(PracticeSessionTable).where(
                PracticeSessionTable.session_id == session_id, PracticeSessionTable.owner_id == owner_id))
            return PracticeSession.model_validate(row.payload) if row else None

    async def list(self, owner_id, limit=50):
        async with get_session_factory()() as db:
            rows = (await db.scalars(select(PracticeSessionTable).where(
                PracticeSessionTable.owner_id == owner_id).order_by(
                    PracticeSessionTable.created_at.desc()).limit(limit))).all()
            return [item(PracticeSession.model_validate(row.payload)) for row in rows]
