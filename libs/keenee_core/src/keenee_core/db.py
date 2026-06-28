"""App DB(읽기/쓰기) 엔진·세션. 공모전 DB 와 절대 공유하지 않는다."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from keenee_core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # lru_cache 로 프로세스당 한 번만 생성. import 시점엔 연결하지 않음(lazy).
    return create_engine(get_settings().app_db_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성 / worker 공용 세션 컨텍스트."""
    with _session_factory()() as session:
        yield session
