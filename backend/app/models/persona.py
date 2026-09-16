from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


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
    gender: Literal["male", "female", "other", "unspecified"] = Field(
        default="unspecified", description="아바타 생성에 사용할 질문자의 성별"
    )
    age: int | None = Field(
        default=None, ge=1, le=120, description="아바타 생성에 사용할 질문자의 나이"
    )
    document_ids: list[UUID] = Field(
        default_factory=list,
        description="페르소나의 기본 대화 자료로 연결할 문서 UUID 목록",
    )


class PersonaUpdateRequest(PersonaCreateRequest):
    """질문자 기본 정보와 연결 자료를 한 번에 수정하는 요청."""


class PersonaProfile(BaseModel):
    agent_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = Field(
        default="",
        description="LLM 리뷰와 대화에 전달할 평가자 원본 설명",
    )
    role: str = "Evaluator"
    gender: Literal["male", "female", "other", "unspecified"] = "unspecified"
    age: int | None = Field(default=None, ge=1, le=120)
    expertise: list[PersonaTrait] = Field(default_factory=list)
    evaluation_style: list[PersonaTrait] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)

    @computed_field
    @property
    def warnings(self) -> list[str]:
        warnings = []
        if self.role == "기본 평가자 (로컬 모드)":
            warnings.append("로컬 모드: 입력한 설명을 평가 관점으로 사용하며, 모델의 전문성·참고자료 분석은 수행하지 않았습니다.")
        traits = [*self.expertise, *self.evaluation_style]
        if not any(t.status in {"user_stated", "supported", "inferred"} for t in traits):
            warnings.append("근거가 확인된 전문 분야·평가 스타일이 없습니다. 설명이나 참고자료를 보강해 수정해주세요.")
        if any(t.status == "unknown" for t in traits):
            warnings.append("원문 근거가 확인되지 않은 특성은 평가 관점에서 제외했습니다.")
        return warnings


class PersonaDocumentsUpdate(BaseModel):
    document_ids: list[UUID] = Field(
        default_factory=list,
        description="질문자에 연결할 전체 문서 UUID 목록. 빈 배열은 모두 연결 해제합니다.",
    )


class PersonaHistoryItem(PersonaProfile):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
