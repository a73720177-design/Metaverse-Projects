from pydantic import BaseModel


class ContentAssessment(BaseModel):
    policy_version: int = 1
    unique_units: int = 0
    effective_chars: int = 0
    output_limit: int = 0
    saturated: bool = False
    basis: str = "중복을 제외한 내용량 기준의 추정치이며 정확도 평가는 아닙니다."
