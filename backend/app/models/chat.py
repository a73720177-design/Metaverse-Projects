from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.review import ReviewSource


class ResponseDetail(StrEnum):
    CONCISE = "concise"
    STANDARD = "standard"
    DETAILED = "detailed"


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=5000,
        description="평가자에게 전달할 질문",
        examples=["이 발표에서 근거가 가장 부족한 주장은 무엇인가요?"],
    )
    document_id: UUID | None = Field(
        default=None,
        description="대화 문맥으로 사용할 발표자료 UUID(선택)",
    )
    response_detail: ResponseDetail = Field(
        default=ResponseDetail.STANDARD,
        description="답변 상세도. Backend가 안전한 출력 토큰 상한으로 변환합니다.",
    )


class ChatResponse(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    answer: str
    sources: list[ReviewSource] = Field(default_factory=list)


class ChatHistoryItem(ChatResponse):
    """저장된 질문/답변 한 쌍과 휴지통 상태입니다."""

    owner_id: UUID = Field(exclude=True)
    message: str
    document_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
