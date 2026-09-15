from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_practice_service
from app.models.practice import ExpectedQuestionRequest, ExpectedQuestionResponse
from app.models.user import UserResponse
from app.services.practice_service import (
    PracticeResourceNotFoundError,
    PracticeService,
    PracticeServiceError,
)


router = APIRouter(prefix="/practice", tags=["예상 질문"])


@router.post(
    "/questions",
    response_model=ExpectedQuestionResponse,
    summary="여러 질문자 페르소나의 예상 질문 생성",
)
async def generate_expected_questions(
    request: ExpectedQuestionRequest,
    service: PracticeService = Depends(get_practice_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ExpectedQuestionResponse:
    try:
        return await service.generate_expected_questions(request, current_user.user_id)
    except PracticeResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PracticeServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
