from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_review_service
from app.models.error import ErrorResponse
from app.models.review import ReviewCreateRequest, ReviewResult
from app.models.user import UserResponse
from app.services.review_service import ReviewResourceNotFoundError, ReviewService, ReviewServiceError

router = APIRouter(tags=["리뷰"])


@router.post("/agents/{agent_id}/reviews", response_model=ReviewResult,
             status_code=status.HTTP_201_CREATED,
             responses={503: {"model": ErrorResponse}}, summary="발표 자료 리뷰 생성",
             description="평가자와 문서를 조회한 뒤 LLM 서비스에 근거 기반 리뷰를 요청합니다.")
async def create_review(
    agent_id: UUID,
    request: ReviewCreateRequest,
    service: ReviewService = Depends(get_review_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ReviewResult:
    try:
        return await service.create(agent_id, request, current_user.user_id)
    except ReviewResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/reviews/{review_id}", response_model=ReviewResult,
            summary="리뷰 결과 조회",
            description="리뷰 생성 시 발급된 UUID로 저장된 결과를 조회합니다.")
async def get_review(
    review_id: UUID,
    service: ReviewService = Depends(get_review_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ReviewResult:
    review = await service.get(review_id, current_user.user_id)
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    return review
