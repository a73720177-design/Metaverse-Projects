from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_review_service
from app.models.error import ErrorResponse
from app.models.review import ReviewCreateRequest, ReviewResult
from app.services.review_service import (
    ReviewResourceNotFoundError,
    ReviewService,
    ReviewServiceError,
)


router = APIRouter(tags=["리뷰"])


@router.post(
    "/agents/{agent_id}/reviews",
    response_model=ReviewResult,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"model": ErrorResponse}},
    summary="발표자료 리뷰 생성",
    description=(
        "경로의 평가자 ID와 본문의 문서 ID를 이용해 리뷰를 요청합니다. LLM/RAG 담당자의 "
        "ReviewGenerator가 주장 검증, 근거, 장단점과 예상 질문을 생성합니다. 생성기가 아직 "
        "연결되지 않았다면 503 오류가 반환됩니다."
    ),
)
async def create_review(
    agent_id: UUID,
    request: ReviewCreateRequest,
    service: ReviewService = Depends(get_review_service),
) -> ReviewResult:
    try:
        return await service.create(agent_id, request)
    except ReviewResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewResult,
    summary="리뷰 결과 조회",
    description="리뷰 생성 시 받은 UUID로 저장된 리뷰 결과를 조회합니다.",
)
async def get_review(
    review_id: UUID,
    service: ReviewService = Depends(get_review_service),
) -> ReviewResult:
    review = await service.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review
