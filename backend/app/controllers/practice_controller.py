from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from app.models.practice import PracticeSession, PracticeSessionItem

from app.dependencies import get_current_user, get_practice_service
from app.models.practice import ExpectedQuestionRequest, ExpectedQuestionResponse
from app.models.user import UserResponse
from app.services.practice_service import (
    PracticeResourceNotFoundError,
    PracticeService,
    PracticeServiceError,
)


router = APIRouter(prefix="/practice", tags=["예상 질문"])


@router.get("/sessions", response_model=list[PracticeSessionItem])
async def list_sessions(service: PracticeService = Depends(get_practice_service),
                        current_user: UserResponse = Depends(get_current_user)):
    return await service.list_sessions(current_user.user_id)


@router.get("/sessions/{session_id}", response_model=PracticeSession)
async def get_session(session_id: UUID, service: PracticeService = Depends(get_practice_service),
                      current_user: UserResponse = Depends(get_current_user)):
    try:
        return await service.get_session(session_id, current_user.user_id)
    except PracticeResourceNotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


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
