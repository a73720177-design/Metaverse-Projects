from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_persona_service
from app.models.persona import (
    PersonaCreateRequest, PersonaDocumentsUpdate, PersonaHistoryItem, PersonaProfile,
    PersonaUpdateRequest,
)
from app.models.user import UserResponse
from app.services.persona_service import (
    PersonaDocumentNotFoundError, PersonaNotFoundError, PersonaService, UpstreamServiceError,
)

router = APIRouter(prefix="/agents", tags=["평가자"])


@router.post("", response_model=PersonaProfile, status_code=status.HTTP_201_CREATED,
             summary="평가자 페르소나 생성",
             description="전문 분야를 받아 LLM으로 질문자를 만들고 Backend가 ID를 발급합니다.")
async def create_agent(
    request: PersonaCreateRequest,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> PersonaProfile:
    try:
        return await service.create(request, current_user.user_id)
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonaDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[PersonaHistoryItem], summary="페르소나 목록 조회")
async def list_agents(
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> list[PersonaHistoryItem]:
    return await service.list_active(current_user.user_id)


@router.put("/{agent_id}/documents", response_model=PersonaProfile,
            summary="질문자 참고자료 연결 변경")
async def update_agent_documents(
    agent_id: UUID,
    request: PersonaDocumentsUpdate,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> PersonaProfile:
    try:
        return await service.update_documents(
            agent_id, request.document_ids, current_user.user_id
        )
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (PersonaNotFoundError, PersonaDocumentNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=PersonaProfile, summary="질문자 정보 수정")
async def update_agent(
    agent_id: UUID,
    request: PersonaUpdateRequest,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> PersonaProfile:
    try:
        return await service.update(agent_id, request, current_user.user_id)
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (PersonaNotFoundError, PersonaDocumentNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="페르소나 영구 삭제")
async def delete_agent(
    agent_id: UUID,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    try:
        await service.permanently_delete(agent_id, current_user.user_id)
    except PersonaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{agent_id}", response_model=PersonaProfile,
            summary="평가자 페르소나 조회",
            description="생성 시 발급된 UUID로 저장된 페르소나를 조회합니다.")
async def get_agent(
    agent_id: UUID,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> PersonaProfile:
    persona = await service.get(agent_id, current_user.user_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="평가자를 찾을 수 없습니다.")
    return persona
