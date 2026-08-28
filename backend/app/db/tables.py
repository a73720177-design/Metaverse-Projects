from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserTable(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    username: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentTable(Base):
    __tablename__ = "agents"

    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(Text, nullable=False, default="Evaluator")
    expertise: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evaluation_style: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentTable(Base):
    __tablename__ = "documents"

    document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentFileTable(Base):
    __tablename__ = "document_files"

    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentChunkTable(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_index"),
        Index("ix_document_chunks_document_id", "document_id"),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewTable(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_agent_id", "agent_id"),
        Index("ix_reviews_document_id", "document_id"),
    )

    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.agent_id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="RESTRICT"),
        nullable=False,
    )
    claims: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    feedback: Mapped[dict] = mapped_column(JSONB, nullable=False)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
