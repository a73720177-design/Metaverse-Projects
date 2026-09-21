from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field

from app.models.llm import DEFAULT_LLM_MODEL, LlmModel


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
    exclusion_reason: Literal["missing_quote", "model_unknown", "conflicting", "zero_confidence", "reference_changed"] | None = None


def active_trait(trait: PersonaTrait) -> bool:
    return (trait.status in {EvidenceStatus.USER_STATED, EvidenceStatus.SUPPORTED, EvidenceStatus.INFERRED}
            and trait.confidence > 0 and bool(trait.value.strip())
            and any(e.source_id in {"description", "reference_context"}
                    and e.confidence > 0 and e.summary.strip() for e in trait.evidence))


def invalidate_reference_traits(persona):
    """Legacy evidence identifies the aggregate reference, not a document ID.

    Invalidate conservatively on any reference change; never reuse stale traits.
    """
    updated = persona.model_copy(deep=True)
    for trait in [*updated.expertise, *updated.evaluation_style]:
        if any(e.source_id == "reference_context" for e in trait.evidence):
            trait.evidence = [e for e in trait.evidence if e.source_id != "reference_context"]
            trait.status = EvidenceStatus.UNKNOWN
            trait.confidence = 0
            trait.exclusion_reason = "reference_changed"
    return updated


class PersonaCreateRequest(BaseModel):
    model: LlmModel = DEFAULT_LLM_MODEL
    name: str = Field(
        min_length=1,
        max_length=100,
        description="평가자 이름 또는 구분용 이름",
        examples=["홍길동 교수"],
    )
    description: str = Field(
        min_length=1,
        max_length=5000,
        description="질문자가 검토할 전문 분야",
        examples=["인공지능"],
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
        if not any(active_trait(t) for t in traits):
            warnings.append("근거가 확인된 전문 분야·평가 스타일이 없습니다. 설명이나 참고자료를 보강해 수정해주세요.")
        excluded = [t for t in traits if not active_trait(t)]
        if excluded:
            warnings.append(f"원문 인용·상태·신뢰도 검증을 통과하지 못한 특성 {len(excluded)}개는 평가 관점에서 제외했습니다.")
        if any(t.status == "conflicting" for t in traits):
            warnings.append("서로 충돌하는 특성은 사용하지 않습니다. 설명과 참고자료를 확인해주세요.")
        if any(t.exclusion_reason == "reference_changed" for t in traits):
            warnings.append("참고자료 연결이 변경되어 관련 특성을 제외했습니다. 질문자를 수정해 다시 분석해주세요.")
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
