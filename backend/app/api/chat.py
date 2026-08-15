from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_chat_service
from app.models.chat import ChatRequest, ChatResponse
from app.models.error import ErrorResponse
from app.services.chat_service import (
    ChatResourceNotFoundError,
    ChatService,
    ChatServiceError,
)


router = APIRouter(tags=["대화"])


@router.post(
    "/agents/{agent_id}/chat",
    response_model=ChatResponse,
    responses={503: {"model": ErrorResponse}},
    summary="평가자 관점으로 질문하기",
    description=(
        "선택한 평가자에게 질문을 보내고 페르소나 관점의 답변과 근거 출처를 받습니다. "
        "document_id를 전달하면 특정 발표자료를 대화 문맥으로 지정할 수 있습니다."
    ),
)
async def chat(
    agent_id: UUID,
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    try:
        return await service.reply(agent_id, request)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
