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
