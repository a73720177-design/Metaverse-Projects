from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.review import ReviewSource
from app.models.coverage import Coverage


class SummaryStyle(StrEnum):
    BRIEF = "brief"
    DETAILED = "detailed"
    OUTLINE = "outline"


class KeyTopic(BaseModel):
    topic: str
    description: str
    sources: list[ReviewSource] = Field(default_factory=list)


class SummaryCreateRequest(BaseModel):
    style: SummaryStyle = Field(
        default=SummaryStyle.BRIEF,
        description="brief(3~5문장), detailed(문단 요약), outline(개요만) 중 선택",
    )
    agent_id: UUID | None = Field(
        default=None,
        description="지정하면 해당 평가자 페르소나의 관점으로 요약합니다(선택)",
    )


class SummaryResult(BaseModel):
    coverage: Coverage | None = None
    summary_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    agent_id: UUID | None = None
    style: SummaryStyle
    summary: str
    key_topics: list[KeyTopic] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
