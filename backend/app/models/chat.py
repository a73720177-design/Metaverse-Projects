from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.review import ReviewSource


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


class ChatResponse(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    answer: str
    sources: list[ReviewSource] = Field(default_factory=list)
    needs_more_material: bool = Field(
        default=False,
        description="검색된 자료가 임계값에 못 미쳐 자료 추가를 요청한 답변인지",
    )


class ChatHistoryItem(ChatResponse):
    """저장된 질문/답변 한 쌍과 휴지통 상태입니다."""

    owner_id: UUID = Field(exclude=True)
    message: str
    document_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
