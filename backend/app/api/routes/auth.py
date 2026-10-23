from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth_service, get_current_principal
from app.core.permissions import Principal
from app.schemas.models import LoginRequest, LoginResponse, UserProfile
from app.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> LoginResponse:
    try:
        return auth.login(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


@router.get("/me", response_model=UserProfile)
def me(principal: Principal = Depends(get_current_principal)) -> UserProfile:
    return AuthService.profile(principal)
