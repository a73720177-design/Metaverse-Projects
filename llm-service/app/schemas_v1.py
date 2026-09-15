"""
정식 /api/v1 계약 스키마.

Backend의 backend/app/models/{persona,document,review,chat}.py와 필드가
1:1로 맞아야 한다. Backend는 이 서비스의 응답 dict를 자기 Pydantic 모델에
그대로 병합(model_validate)하므로, 필드 이름과 타입이 어긋나면 Backend
쪽에서 검증 오류가 난다.
"""

from enum import StrEnum
from typing import Annotated, Literal
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
    reference_context: str = Field(default="", max_length=3000)


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
    # Long PDFs are sampled by the review/summary map-reduce pipelines before
    # generation. Keep an HTTP safety cap while accepting the project's actual
    # parsed corpus (currently up to about 1.7M characters).
    full_text: str = Field(max_length=2_000_000)


class QuestionStrategy(BaseModel):
    criticalness: int = Field(default=3, ge=1, le=5)
    difficulty: int = Field(default=3, ge=1, le=5)
    evidence_required: bool = True
    follow_up_depth: int = Field(default=1, ge=1, le=3)


class PersonaProfileIn(BaseModel):
    agent_id: UUID
    name: str
    description: str = ""
    role: str = "Evaluator"
    expertise: list[PersonaTrait] = Field(default_factory=list, max_length=10)
    evaluation_style: list[PersonaTrait] = Field(default_factory=list, max_length=10)
    question_strategy: QuestionStrategy = Field(default_factory=QuestionStrategy)


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


class ReviewGenerationRequest(BaseModel):
    persona: PersonaProfileIn
    document: DocumentIn
    instructions: str | None = Field(default=None, max_length=2000)


class ReviewCoverage(BaseModel):
    total_chunks: int = Field(ge=0)
    analyzed_chunks: int = Field(ge=0)
    truncated: bool = False
    selection_method: str = "full"


class ReviewGenerationResponse(BaseModel):
    claims: list[ClaimAssessment] = Field(default_factory=list, max_length=20)
    feedback: ReviewFeedback
    questions: list[str] = Field(default_factory=list, max_length=10)
    # map-reduce 경로에서만 채워진다. 기본값 None이라 Backend의
    # ReviewResult.model_validate()나 단일 패스 응답은 영향받지 않는다.
    coverage: ReviewCoverage | None = None


class QuestionEvidence(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    scope: Literal["presentation", "persona_reference"]
    text: str = Field(min_length=1, max_length=8000)


class ExpectedQuestionGenerationRequest(BaseModel):
    persona: PersonaProfileIn
    question_count: int = Field(default=5, ge=1, le=10)
    evidence: list[QuestionEvidence] = Field(min_length=1, max_length=80)
    excluded_questions: list[str] = Field(default_factory=list, max_length=40)


class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=12, max_length=500)
    presentation_evidence_ids: list[str] = Field(min_length=1, max_length=3)
    focus: str = Field(min_length=1, max_length=150)


class ExpectedQuestionGenerationResponse(BaseModel):
    questions: list[GeneratedQuestion] = Field(max_length=10)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatGenerationRequest(BaseModel):
    persona: PersonaProfileIn
    message: str = Field(min_length=1, max_length=5000)
    document: DocumentIn | None = None
    max_output_tokens: int = Field(default=1024, ge=128, le=2048)
    # default_factory=list이므로 history를 안 보내는 기존 클라이언트와도 호환된다.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    history_truncated: bool = False


class ChatGenerationResponse(BaseModel):
    answer: str = Field(min_length=1)
    sources: list[ReviewSource] = Field(default_factory=list, max_length=10)


class EmbeddingRequest(BaseModel):
    texts: list[Annotated[str, Field(min_length=1, max_length=8000)]] = Field(
        min_length=1, max_length=128
    )


class EmbeddingResponse(BaseModel):
    model: str
    dimension: int = Field(ge=1)
    embeddings: list[list[float]]


class SummaryStyle(StrEnum):
    BRIEF = "brief"
    DETAILED = "detailed"
    OUTLINE = "outline"


class KeyTopic(BaseModel):
    topic: str
    description: str
    sources: list[ReviewSource] = Field(default_factory=list, max_length=5)


class SummaryGenerationRequest(BaseModel):
    topic_limit: int = Field(default=8, ge=0, le=8)
    document: DocumentIn
    style: SummaryStyle = SummaryStyle.BRIEF
    persona: PersonaProfileIn | None = None


class SummaryGenerationResponse(BaseModel):
    coverage: ReviewCoverage | None = None
    summary: str = Field(min_length=1)
    key_topics: list[KeyTopic] = Field(default_factory=list, max_length=8)
    outline: list[str] = Field(default_factory=list, max_length=20)
