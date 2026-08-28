from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_auth_service, get_current_user
from app.models.user import TokenResponse, UserCredentials, UserResponse
from app.repositories.user_repository import UsernameAlreadyExistsError
from app.services.auth_service import AuthService, InvalidCredentialsError


router = APIRouter(prefix="/auth", tags=["로그인"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    credentials: UserCredentials,
    service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    try:
        return await service.signup(credentials)
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.") from exc


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserCredentials,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        return await service.login(credentials)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    return current_user
