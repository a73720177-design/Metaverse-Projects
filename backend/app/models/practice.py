from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.models.review import ReviewSource
from app.models.coverage import Coverage
from app.models.content_assessment import ContentAssessment
from app.models.llm import DEFAULT_LLM_MODEL, LlmModel


class ExpectedQuestionRequest(BaseModel):
    model: LlmModel = DEFAULT_LLM_MODEL
    persona_ids: list[UUID] = Field(min_length=1, max_length=4)
    presentation_document_ids: list[UUID] = Field(min_length=1, max_length=20)
    question_count_per_persona: int = Field(default=5, ge=1, le=10)


class ExpectedQuestion(BaseModel):
    question_id: UUID = Field(default_factory=uuid4)
    question: str
    sources: list[ReviewSource] = Field(default_factory=list)
    conversation_id: UUID = Field(default_factory=uuid4)
    focus: str = ""
    origin: Literal["model", "template"] = "model"


class PersonaQuestionResult(BaseModel):
    assessment: ContentAssessment | None = None
    persona_id: UUID
    persona_name: str
    questions: list[ExpectedQuestion]
    requested_count: int = 5
    generated_count: int = 0
    status: Literal["complete", "partial", "fallback"] = "complete"
    warnings: list[str] = Field(default_factory=list)
    coverage: Coverage | None = None


class ExpectedQuestionResponse(BaseModel):
    results: list[PersonaQuestionResult]
    session_id: UUID | None = None


class PracticeSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request: ExpectedQuestionRequest
    response: ExpectedQuestionResponse
    warnings: list[str] = Field(default_factory=list)


class PracticeSessionItem(BaseModel):
    session_id: UUID
    created_at: datetime
    persona_names: list[str]
