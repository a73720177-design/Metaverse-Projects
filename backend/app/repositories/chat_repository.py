from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select

from app.db.database import get_session_factory
from app.db.tables import ChatMessageTable
from app.models.chat import ChatHistoryItem


class ChatRepository(Protocol):
    async def save(self, chat: ChatHistoryItem) -> None: ...
    async def get(self, message_id: UUID, owner_id: UUID) -> ChatHistoryItem | None: ...
    async def list(self, owner_id: UUID, *, deleted: bool) -> list[ChatHistoryItem]: ...
    async def set_deleted(
        self, message_id: UUID, owner_id: UUID, *, deleted: bool
    ) -> ChatHistoryItem | None: ...
    async def permanently_delete(self, message_id: UUID, owner_id: UUID) -> bool: ...


class InMemoryChatRepository:
    def __init__(self) -> None:
        self._chats: dict[UUID, ChatHistoryItem] = {}

    async def save(self, chat: ChatHistoryItem) -> None:
        self._chats[chat.message_id] = chat

    async def get(self, message_id: UUID, owner_id: UUID) -> ChatHistoryItem | None:
        chat = self._chats.get(message_id)
        return chat if chat is not None and chat.owner_id == owner_id else None

    async def list(self, owner_id: UUID, *, deleted: bool) -> list[ChatHistoryItem]:
        chats = [
            chat
            for chat in self._chats.values()
            if chat.owner_id == owner_id and (chat.deleted_at is not None) == deleted
        ]
        return sorted(chats, key=lambda chat: chat.created_at, reverse=True)

    async def set_deleted(
        self, message_id: UUID, owner_id: UUID, *, deleted: bool
    ) -> ChatHistoryItem | None:
        chat = await self.get(message_id, owner_id)
        if chat is None:
            return None
        from datetime import datetime, timezone

        updated = chat.model_copy(
            update={"deleted_at": datetime.now(timezone.utc) if deleted else None}
        )
        self._chats[message_id] = updated
        return updated

    async def permanently_delete(self, message_id: UUID, owner_id: UUID) -> bool:
        chat = await self.get(message_id, owner_id)
        if chat is None or chat.deleted_at is None:
            return False
        del self._chats[message_id]
        return True


def _to_model(row: ChatMessageTable) -> ChatHistoryItem:
    return ChatHistoryItem.model_validate(
        {
            "message_id": row.message_id,
            "owner_id": row.owner_id,
            "agent_id": row.agent_id,
            "document_id": row.document_id,
            "message": row.message,
            "answer": row.answer,
            "sources": row.sources,
            "needs_more_material": row.needs_more_material,
            "created_at": row.created_at,
            "deleted_at": row.deleted_at,
        }
    )


class PostgresChatRepository:
    async def save(self, chat: ChatHistoryItem) -> None:
        row = ChatMessageTable(
            message_id=chat.message_id,
            owner_id=chat.owner_id,
            agent_id=chat.agent_id,
            document_id=chat.document_id,
            message=chat.message,
            answer=chat.answer,
            sources=[source.model_dump(mode="json") for source in chat.sources],
            needs_more_material=chat.needs_more_material,
            created_at=chat.created_at,
            deleted_at=chat.deleted_at,
        )
        async with get_session_factory()() as session:
            await session.merge(row)
            await session.commit()

    async def get(self, message_id: UUID, owner_id: UUID) -> ChatHistoryItem | None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(ChatMessageTable).where(
                    ChatMessageTable.message_id == message_id,
                    ChatMessageTable.owner_id == owner_id,
                )
            )
        return _to_model(row) if row is not None else None

    async def list(self, owner_id: UUID, *, deleted: bool) -> list[ChatHistoryItem]:
        condition = (
            ChatMessageTable.deleted_at.is_not(None)
            if deleted
            else ChatMessageTable.deleted_at.is_(None)
        )
        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(ChatMessageTable)
                    .where(ChatMessageTable.owner_id == owner_id, condition)
                    .order_by(ChatMessageTable.created_at.desc())
                )
            ).all()
        return [_to_model(row) for row in rows]

    async def set_deleted(
        self, message_id: UUID, owner_id: UUID, *, deleted: bool
    ) -> ChatHistoryItem | None:
        from datetime import datetime, timezone

        async with get_session_factory()() as session:
            row = await session.scalar(
                select(ChatMessageTable).where(
                    ChatMessageTable.message_id == message_id,
                    ChatMessageTable.owner_id == owner_id,
                )
            )
            if row is None:
                return None
            row.deleted_at = datetime.now(timezone.utc) if deleted else None
            await session.commit()
            await session.refresh(row)
            return _to_model(row)

    async def permanently_delete(self, message_id: UUID, owner_id: UUID) -> bool:
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(ChatMessageTable).where(
                    ChatMessageTable.message_id == message_id,
                    ChatMessageTable.owner_id == owner_id,
                    ChatMessageTable.deleted_at.is_not(None),
                )
            )
            await session.commit()
            return bool(result.rowcount)
