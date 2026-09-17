from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.review import ReviewSource
from app.models.llm import DEFAULT_LLM_MODEL, LlmModel


class ResponseDetail(StrEnum):
    CONCISE = "concise"
    STANDARD = "standard"
    DETAILED = "detailed"


class ChatTurn(BaseModel):
    """LLM Service에 전달하는 과거 대화 한 마디."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: LlmModel = DEFAULT_LLM_MODEL
    conversation_id: UUID | None = Field(
        default=None,
        description="질문별 대화 UUID. 생략하면 기존 일반 대화 이력만 사용합니다.",
    )
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
    document_ids: list[UUID] = Field(
        default_factory=list,
        description="발표 프로젝트와 페르소나에서 채팅 근거로 사용할 문서 UUID 목록",
    )
    response_detail: ResponseDetail = Field(
        default=ResponseDetail.STANDARD,
        description="답변 상세도. Backend가 안전한 출력 토큰 상한으로 변환합니다.",
    )


class Grounding(BaseModel):
    """답변 문장이 실제로 첨부 문서 근거에 기반하는지 검증한 결과."""

    score: float = Field(ge=0, le=1)
    unsupported: list[str] = Field(default_factory=list, max_length=10)
    checked: bool = True


class ChatResponse(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID | None = None
    agent_id: UUID
    answer: str
    sources: list[ReviewSource] = Field(default_factory=list)
    grounding: Grounding | None = None


class ChatTiming(BaseModel):
    context_ms: int = Field(default=0, ge=0)
    first_content_latency_ms: int = Field(default=0, ge=0)
    generation_ms: int = Field(default=0, ge=0)
    save_ms: int = Field(default=0, ge=0)
    total_ms: int = Field(default=0, ge=0)
    output_characters: int = Field(default=0, ge=0)
    output_lines: int = Field(default=0, ge=0)


class ChatHistoryItem(ChatResponse):
    """저장된 질문/답변 한 쌍과 휴지통 상태입니다."""

    owner_id: UUID = Field(exclude=True)
    message: str
    document_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
    timing: ChatTiming = Field(default_factory=ChatTiming)
