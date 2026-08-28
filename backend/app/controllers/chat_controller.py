from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_chat_service, get_current_user
from app.models.chat import ChatRequest, ChatResponse
from app.models.error import ErrorResponse
from app.models.user import UserResponse
from app.services.chat_service import ChatResourceNotFoundError, ChatService, ChatServiceError

router = APIRouter(tags=["대화"])


@router.post("/agents/{agent_id}/chat", response_model=ChatResponse,
             responses={503: {"model": ErrorResponse}}, summary="평가자 관점으로 질문하기",
             description="선택한 페르소나와 선택적 문서 문맥을 사용해 LLM 답변을 반환합니다.")
async def chat(
    agent_id: UUID,
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ChatResponse:
    try:
        return await service.reply(agent_id, request, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
