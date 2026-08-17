from pydantic import BaseModel, Field


class Concept(BaseModel):
    name: str
    definition: str


class ConceptExtractionRequest(BaseModel):
    paper_text: str = Field(
        ...,
        min_length=1,
        max_length=200_000,
        description="개념을 추출할 논문 본문 전체 텍스트",
    )


class ConceptExtractionResponse(BaseModel):
    concepts: list[Concept]


class QuestionGenerationRequest(BaseModel):
    concepts: list[Concept] = Field(
        ..., min_length=1, max_length=100, description="1단계에서 추출된 개념 목록"
    )
    critical_points: str = Field(
        ...,
        min_length=1,
        max_length=5_000,
        description="사용자가 평소 중요하게 여기는 관점 (캐릭터 설정)",
    )
    script_text: str = Field(
        ..., min_length=1, max_length=200_000, description="비판 대상이 되는 발표 대본"
    )


class Question(BaseModel):
    question: str


class QuestionGenerationResponse(BaseModel):
    questions: list[Question]
