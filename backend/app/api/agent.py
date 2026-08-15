from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_persona_service
from app.models.persona import PersonaCreateRequest, PersonaProfile
from app.services.persona_service import PersonaService, UpstreamServiceError


router = APIRouter(prefix="/agents", tags=["평가자"])


@router.post(
    "",
    response_model=PersonaProfile,
    status_code=status.HTTP_201_CREATED,
    summary="평가자 페르소나 생성",
    description=(
        "이름과 자연어 설명을 전달하면 LLM 담당자의 생성기를 호출하고, 백엔드가 결과를 "
        "검증하여 평가자 ID를 발급합니다. 현재 저장소는 개발용 메모리 구현입니다."
    ),
)
async def create_agent(
    request: PersonaCreateRequest,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaProfile:
    try:
        return await service.create(request)
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/{agent_id}",
    response_model=PersonaProfile,
    summary="평가자 페르소나 조회",
    description="평가자 생성 시 받은 UUID로 저장된 페르소나를 조회합니다.",
)
async def get_agent(
    agent_id: UUID,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaProfile:
    persona = await service.get(agent_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return persona
