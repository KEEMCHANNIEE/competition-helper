"""worker 테스트 공용 픽스처.

hermetic: 실제 Postgres/Redis 없이 SQLite + FakeRedis 로 배관을 검증한다.
embeddings 는 pgvector ``Vector`` 컬럼을 써서 SQLite 가 만들 수 없으므로
필요한 테이블(User/AgentJob/Recommendation)만 생성한다.
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.models import AgentJob, Base, Recommendation, User


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    """SQLite 인메모리 엔진에 바인딩된 세션 팩토리.

    pgvector 컬럼이 있는 embeddings 는 제외하고 필요한 테이블만 만든다.
    StaticPool 로 같은 인메모리 DB 를 여러 세션이 공유하게 한다.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AgentJob.__table__, Recommendation.__table__],
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


class FakeRedis:
    """리스트 연산만 흉내내는 최소 가짜 Redis (lpush/brpop FIFO)."""

    def __init__(self) -> None:
        self._lists: dict[str, list[bytes]] = defaultdict(list)

    def lpush(self, key: str, *values: str | bytes) -> int:
        # api 는 lpush 로 넣고 worker 는 brpop 으로 꺼낸다(FIFO).
        for v in values:
            self._lists[key].insert(0, _as_bytes(v))
        return len(self._lists[key])

    def brpop(self, key: str, timeout: int = 0):  # noqa: ARG002 - 가짜는 블로킹 안 함
        keys = [key] if isinstance(key, str) else list(key)
        for k in keys:
            if self._lists[k]:
                return (_as_bytes(k), self._lists[k].pop())
        return None


def _as_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode()


@pytest.fixture()
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture()
def seed_user(session_factory: sessionmaker[Session]) -> int:
    """추천이 매달릴 사용자 1명을 만든다."""
    with session_factory() as session:
        user = User(email="tester@contest-helper.io", name="Tester", interests=["AI"], skills=["python"])
        session.add(user)
        session.commit()
        return user.id
