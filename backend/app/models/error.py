from pydantic import BaseModel, Field


class ErrorField(BaseModel):
    loc: list[str | int]
    type: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    fields: list[ErrorField] = Field(default_factory=list)
    error_type: str | None = None
    contract: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
