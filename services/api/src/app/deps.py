"""FastAPI 의존성 모음.

모든 외부 의존성(App DB 세션·Redis·공모전 repo)은 여기서 주입한다.
테스트는 ``app.dependency_overrides`` 로 이 함수들을 가짜로 갈아끼운다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import redis as redis_lib
from contest_helper_core.config import get_settings
from contest_helper_core.db import get_session
from contest_helper_core.models import User
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE, read_session_token
from app.competitions.repository import (
    CompetitionRepository,
    SqlCompetitionRepository,
)

if TYPE_CHECKING:
    from redis import Redis


def get_db() -> Iterator[Session]:
    """App DB 세션. contest_helper_core.db 의 세션 팩토리에 위임한다."""
    yield from get_session()


def get_redis() -> Redis:
    """동기 redis-py 클라이언트. 큐 계약과 동일하게 redis_url 사용."""
    return redis_lib.from_url(get_settings().redis_url)


def get_competition_repo() -> CompetitionRepository:
    """공모전 DB 읽기 repo. 테스트에서 FakeRepo 로 override."""
    return SqlCompetitionRepository()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """서명된 세션 쿠키에서 user_id 를 복원해 User 를 반환. 없으면 401."""
    if get_settings().dev_bypass_auth:
        from app.auth.service import upsert_user
        return upsert_user(db, email="dev@localhost", name="Dev User")

    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 유효하지 않습니다.",
        )
    return user
