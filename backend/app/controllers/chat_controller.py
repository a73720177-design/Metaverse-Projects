from uuid import UUID
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_chat_service, get_current_user
from app.models.chat import ChatHistoryItem, ChatRequest
from app.models.error import ErrorResponse
from app.models.user import UserResponse
from app.services.chat_service import ChatResourceNotFoundError, ChatService, ChatServiceError

router = APIRouter(tags=["대화"])


@router.post("/agents/{agent_id}/chat", response_model=ChatHistoryItem,
             responses={503: {"model": ErrorResponse}}, summary="평가자 관점으로 질문하기",
             description="선택한 페르소나와 선택적 문서 문맥을 사용해 LLM 답변을 반환합니다.")
async def chat(
    agent_id: UUID,
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ChatHistoryItem:
    try:
        return await service.reply(agent_id, request, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post(
    "/agents/{agent_id}/chat/stream",
    summary="평가자 채팅 스트리밍",
    description="기존 JSON 채팅 API와 별도로 SSE 토큰과 최종 저장 결과를 반환합니다.",
)
async def stream_chat(
    agent_id: UUID,
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> StreamingResponse:
    try:
        stream = await service.open_stream(agent_id, request, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def sse():
        try:
            async for item in stream:
                data = json.dumps(item["data"], ensure_ascii=False)
                yield f"event: {item['event']}\ndata: {data}\n\n"
        except ChatServiceError:
            data = json.dumps(
                {"message": "채팅 스트리밍 중 오류가 발생했습니다."},
                ensure_ascii=False,
            )
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chats", response_model=list[ChatHistoryItem], summary="채팅 목록 조회")
async def list_chats(
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> list[ChatHistoryItem]:
    return await service.list_active(current_user.user_id)


@router.delete("/chats/{message_id}", response_model=ChatHistoryItem, summary="채팅을 휴지통으로 이동")
async def move_chat_to_trash(
    message_id: UUID,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ChatHistoryItem:
    try:
        return await service.move_to_trash(message_id, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/trash/chats", response_model=list[ChatHistoryItem], summary="휴지통 채팅 목록 조회")
async def list_trashed_chats(
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> list[ChatHistoryItem]:
    return await service.list_trash(current_user.user_id)


@router.post("/trash/chats/{message_id}/restore", response_model=ChatHistoryItem, summary="채팅 복원")
async def restore_chat(
    message_id: UUID,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> ChatHistoryItem:
    try:
        return await service.restore(message_id, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/trash/chats/{message_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="휴지통 채팅 완전 삭제")
async def permanently_delete_chat(
    message_id: UUID,
    service: ChatService = Depends(get_chat_service),
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    try:
        await service.permanently_delete(message_id, current_user.user_id)
    except ChatResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
