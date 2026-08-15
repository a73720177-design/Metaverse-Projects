from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ClaimVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    OVERGENERALIZED = "overgeneralized"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_VERIFIABLE = "not_verifiable"


class ReviewSource(BaseModel):
    document_id: UUID | None = None
    filename: str
    page: int | None = Field(default=None, ge=1)
    excerpt: str | None = None


class ClaimAssessment(BaseModel):
    claim: str
    verdict: ClaimVerdict
    confidence: float = Field(ge=0, le=1)
    sources: list[ReviewSource] = Field(default_factory=list)


class ReviewFeedback(BaseModel):
    positive: str
    negative: str


class ReviewCreateRequest(BaseModel):
    document_id: UUID = Field(description="리뷰할 업로드 문서의 UUID")
    instructions: str | None = Field(
        default=None,
        max_length=2000,
        description="이번 리뷰에서 특별히 확인할 사항(선택)",
        examples=["기술적 근거와 비교 실험의 타당성을 중점적으로 평가해 주세요."],
    )


class ReviewResult(BaseModel):
    review_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    document_id: UUID
    claims: list[ClaimAssessment] = Field(default_factory=list)
    feedback: ReviewFeedback
    questions: list[str] = Field(default_factory=list)
