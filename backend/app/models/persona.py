from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
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


class QuestionStrategy(BaseModel):
    criticalness: int = Field(
        default=3, ge=1, le=5, description="질문의 비판 강도 (1=온건, 5=매우 날카로움)"
    )
    difficulty: int = Field(
        default=3, ge=1, le=5, description="질문 난이도 (1=기초, 5=심화)"
    )
    evidence_required: bool = Field(
        default=True, description="답변에 근거·수치 제시를 요구할지 여부"
    )
    follow_up_depth: int = Field(
        default=1, ge=1, le=3, description="후속 질문으로 얼마나 깊이 파고들지"
    )


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
    role: str | None = Field(
        default=None,
        max_length=100,
        description="직접 지정한 평가자 역할. focus와 함께 지정하면 AI 추론을 건너뜁니다.",
        examples=["컴퓨터공학 전공 교수"],
    )
    focus: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="평가자가 중점적으로 보는 관점 목록. role과 함께 지정하면 AI 추론을 건너뜁니다.",
        examples=[["기술 선택 근거", "시스템 구조", "구현 가능성"]],
    )
    question_strategy: QuestionStrategy = Field(default_factory=QuestionStrategy)
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
    question_strategy: QuestionStrategy = Field(default_factory=QuestionStrategy)
    document_ids: list[UUID] = Field(default_factory=list)


class PersonaDocumentsUpdate(BaseModel):
    document_ids: list[UUID] = Field(
        default_factory=list,
        description="질문자에 연결할 전체 문서 UUID 목록. 빈 배열은 모두 연결 해제합니다.",
    )


class PersonaHistoryItem(PersonaProfile):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
