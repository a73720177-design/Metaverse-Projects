from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class AgentDataSourceType(StrEnum):
    AGENT = "agent"
    CHAT_MESSAGE = "chat_message"
    DOCUMENT = "document"
    DOCUMENT_FILE = "document_file"
    DOCUMENT_CHUNK = "document_chunk"
    REVIEW = "review"


class AgentDataRecord(BaseModel):
    record_id: UUID
    agent_id: UUID
    owner_id: UUID
    source_type: AgentDataSourceType
    source_id: UUID
    data: dict = Field(default_factory=dict)
    source_created_at: datetime | None = None
    stored_at: datetime
    updated_at: datetime
