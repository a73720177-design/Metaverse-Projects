from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_persona_service
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.models.user import UserResponse
from app.services.persona_service import PersonaService, UpstreamServiceError

router = APIRouter(prefix="/agents", tags=["평가자"])


@router.get("", response_model=list[PersonaProfile], summary="내 평가자 페르소나 목록")
async def list_agents(
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> list[PersonaProfile]:
    return await service.list(current_user.user_id)


@router.post("", response_model=PersonaProfile, status_code=status.HTTP_201_CREATED,
             summary="평가자 페르소나 생성",
             description="이름과 설명을 받아 LLM으로 페르소나를 만들고 Backend가 ID를 발급합니다.")
async def create_agent(
    request: PersonaCreateRequest,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> PersonaProfile:
    try:
        return await service.create(request, current_user.user_id)
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="평가자 페르소나 삭제")
async def delete_agent(
    agent_id: UUID,
    service: PersonaService = Depends(get_persona_service),
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    deleted = await service.delete(agent_id, current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="평가자를 찾을 수 없습니다.")
