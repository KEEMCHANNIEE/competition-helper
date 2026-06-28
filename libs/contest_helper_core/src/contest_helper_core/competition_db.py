"""공모전 DB(읽기 전용 소스) 엔진·세션. App DB 와 분리된 별도 엔진."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def get_competition_engine() -> Engine:
    from contest_helper_core.config import get_settings

    return create_engine(get_settings().competition_db_url, pool_pre_ping=True)


@lru_cache
def competition_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_competition_engine(), expire_on_commit=False)
