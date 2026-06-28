"""인증 비즈니스 로직: 사용자 upsert + 서명 세션 토큰.

세션은 서버 상태 없이 itsdangerous 로 서명한 쿠키에 user_id 만 담는다.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from contest_helper_core.config import get_settings
from contest_helper_core.models import User

# 세션 쿠키 이름 및 만료(초). deps.get_current_user 와 공유.
SESSION_COOKIE = "contest_helper_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14일
_SALT = "contest-helper-session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SALT)


def create_session_token(user_id: int) -> str:
    """user_id 를 서명해 쿠키 값으로 쓸 토큰 생성."""
    return _serializer().dumps({"user_id": user_id})


def read_session_token(token: str) -> int | None:
    """서명 검증 후 user_id 반환. 변조/만료 시 None."""
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user_id = data.get("user_id")
    return int(user_id) if user_id is not None else None


def upsert_user(db: Session, *, email: str, name: str = "") -> User:
    """이메일 기준으로 사용자를 찾고 없으면 생성. 이름은 비어있을 때만 채운다."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name or "", interests=[], skills=[])
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    if name and not user.name:
        user.name = name
        db.commit()
        db.refresh(user)
    return user
