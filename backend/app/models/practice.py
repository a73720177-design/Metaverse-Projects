from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.review import ReviewSource


class ExpectedQuestionRequest(BaseModel):
    persona_ids: list[UUID] = Field(min_length=1, max_length=4)
    presentation_document_ids: list[UUID] = Field(min_length=1)
    question_count_per_persona: int = Field(default=5, ge=1, le=10)


class ExpectedQuestion(BaseModel):
    question_id: UUID = Field(default_factory=uuid4)
    question: str
    sources: list[ReviewSource] = Field(default_factory=list)


class PersonaQuestionResult(BaseModel):
    persona_id: UUID
    persona_name: str
    persona_role: str
    avatar_data_url: str
    questions: list[ExpectedQuestion]


class ExpectedQuestionResponse(BaseModel):
    results: list[PersonaQuestionResult]
