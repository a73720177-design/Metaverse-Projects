"""
정식 /api/v1 계약 스키마.

Backend의 backend/app/models/{persona,document,review,chat}.py와 필드가
1:1로 맞아야 한다. Backend는 이 서비스의 응답 dict를 자기 Pydantic 모델에
그대로 병합(model_validate)하므로, 필드 이름과 타입이 어긋나면 Backend
쪽에서 검증 오류가 난다.

문서 전문(DocumentIn)은 /documents/index 요청에만 실린다. 평가와 채팅은
이미 인덱싱된 문서를 document_id로 가리키기만 한다.
"""

from enum import StrEnum
from uuid import UUID

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
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)


class PersonaGenerationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)


class PersonaGenerationResponse(BaseModel):
    role: str = Field(min_length=1, max_length=100)
    expertise: list[PersonaTrait] = Field(default_factory=list, max_length=10)
    evaluation_style: list[PersonaTrait] = Field(default_factory=list, max_length=10)


class DocumentSection(BaseModel):
    index: int = Field(ge=1)
    text: str


class DocumentIn(BaseModel):
    document_id: UUID
    filename: str
    document_type: str
    sections: list[DocumentSection] = Field(default_factory=list, max_length=1000)
    full_text: str = Field(max_length=300_000)


class PersonaProfileIn(BaseModel):
    agent_id: UUID
    name: str
    description: str = ""
    role: str = "Evaluator"
    expertise: list[PersonaTrait] = Field(default_factory=list, max_length=10)
    evaluation_style: list[PersonaTrait] = Field(default_factory=list, max_length=10)


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
    sources: list[ReviewSource] = Field(default_factory=list, max_length=10)


class ReviewFeedback(BaseModel):
    positive: str
    negative: str


class DocumentIndexResponse(BaseModel):
    document_id: UUID
    chunk_count: int = Field(ge=0)
    reused: bool = False


class ReviewGenerationRequest(BaseModel):
    persona: PersonaProfileIn
    document_id: UUID
    instructions: str | None = Field(default=None, max_length=2000)


class ReviewGenerationResponse(BaseModel):
    claims: list[ClaimAssessment] = Field(default_factory=list, max_length=20)
    feedback: ReviewFeedback
    questions: list[str] = Field(default_factory=list, max_length=10)


class ChatGenerationRequest(BaseModel):
    persona: PersonaProfileIn
    message: str = Field(min_length=1, max_length=5000)
    # 검색 대상 후보. 여러 개를 넘기면 검색 점수가 가장 높은 문서가 쓰인다.
    document_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ChatGenerationResponse(BaseModel):
    answer: str = Field(min_length=1)
    sources: list[ReviewSource] = Field(default_factory=list, max_length=10)
    # 검색 결과가 임계값에 못 미쳐 자료 추가를 요청한 응답인지.
    needs_more_material: bool = False
