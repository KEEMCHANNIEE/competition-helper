"""인증 라우터: 구글 로그인/콜백 + /me 조회·수정."""

from __future__ import annotations

from datetime import datetime
from secrets import token_urlsafe

from contest_helper_core.config import get_settings
from contest_helper_core.models import User
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import oauth, service
from app.deps import get_current_user, get_db

router = APIRouter(tags=["auth"])

# 로그인 시작 시 발급한 CSRF state 를 잠깐 담아두는 쿠키.
_STATE_COOKIE = "contest-helper_oauth_state"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    interests: list[str]
    skills: list[str]
    created_at: datetime | None = None


class MeUpdate(BaseModel):
    interests: list[str] | None = None
    skills: list[str] | None = None


@router.get("/auth/google/login")
def google_login() -> RedirectResponse:
    """구글 동의 화면으로 리다이렉트. state 를 쿠키에 저장해 콜백에서 검증."""
    state = token_urlsafe(24)
    url = oauth.build_authorization_url(state)
    resp = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    resp.set_cookie(
        _STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax"
    )
    return resp


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """code↔token 교환 → 프로필 조회 → 사용자 upsert → 세션 쿠키 설정."""
    expected = request.cookies.get(_STATE_COOKIE)
    if not expected or state != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 OAuth state 입니다.",
        )

    token = oauth.exchange_code(code)
    info = oauth.fetch_userinfo(token)

    email = info.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="구글 계정에서 이메일을 가져오지 못했습니다.",
        )

    user = service.upsert_user(db, email=email, name=info.get("name", ""))

    session_token = service.create_session_token(user.id)
    resp = RedirectResponse(
        url=get_settings().frontend_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    resp.set_cookie(
        service.SESSION_COOKIE,
        session_token,
        max_age=service.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    resp.delete_cookie(_STATE_COOKIE)
    return resp


class SwitchRequest(BaseModel):
    user_id: int


@router.post("/auth/dev/switch")
def dev_switch_user(
    payload: SwitchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """[데모용] 같은 워크스페이스의 다른 멤버로 세션을 전환한다(팀원 전환 스위치).

    실제 인증을 우회하는 데모 전용 백도어다. 프로덕션에선 제거/비활성화할 것.
    """
    from app.workspaces import service as ws_service

    target = db.get(User, payload.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다."
        )
    if not ws_service.shares_workspace(db, current_user.id, target.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="같은 워크스페이스 멤버로만 전환할 수 있습니다.",
        )
    resp = JSONResponse(
        {"ok": True, "user_id": target.id, "name": target.name or target.email}
    )
    resp.set_cookie(
        service.SESSION_COOKIE,
        service.create_session_token(target.id),
        max_age=service.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: MeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """관심사·스킬 갱신. 빈 배열도 허용(명시적으로 비우기 가능)."""
    if payload.interests is not None:
        current_user.interests = payload.interests
    if payload.skills is not None:
        current_user.skills = payload.skills
    db.commit()
    db.refresh(current_user)
    return current_user
