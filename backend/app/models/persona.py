from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EvidenceStatus(StrEnum):
    USER_STATED = "user_stated"
    SUPPORTED = "supported"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class Evidence(BaseModel):
    source_id: str
    summary: str
    confidence: float = Field(ge=0, le=1)


class PersonaTrait(BaseModel):
    value: str
    status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)


class PersonaCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="평가자 이름 또는 구분용 이름",
        examples=["홍길동 교수"],
    )
    description: str = Field(
        min_length=1,
        max_length=5000,
        description="전문 분야, 평가 기준 등 사용자가 알고 있는 평가자 정보",
        examples=["인공지능을 연구하며 발표의 근거와 비교 실험을 중요하게 평가한다."],
    )


class PersonaProfile(BaseModel):
    agent_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = Field(
        default="",
        description="LLM 리뷰와 대화에 전달할 평가자 원본 설명",
    )
    role: str = "Evaluator"
    expertise: list[PersonaTrait] = Field(default_factory=list)
    evaluation_style: list[PersonaTrait] = Field(default_factory=list)
