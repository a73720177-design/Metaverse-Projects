from pydantic import BaseModel, Field


class Coverage(BaseModel):
    total_chunks: int = Field(ge=0)
    analyzed_chunks: int = Field(ge=0)
    truncated: bool = False
    selection_method: str = "full"
