"""hermetic 테스트 픽스처.

실제 DB/Redis/네트워크 없이 동작:
- App DB: SQLite in-memory (StaticPool 로 연결 간 동일 DB 유지)
- Redis: FakeRedis (lpush 만 기록)
- 공모전 repo: FakeCompetitionRepository
- 인증: get_current_user override 로 테스트 유저 주입

embeddings 테이블은 pgvector Vector 라 SQLite 가 만들 수 없으므로
필요한 테이블만 골라서 생성한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contest_helper_core.models import (
    AgentJob,
    Base,
    Conversation,
    Message,
    Recommendation,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import CompetitionOut

from app.deps import (
    get_competition_repo,
    get_current_user,
    get_db,
    get_redis,
)
from app.main import app as fastapi_app

# SQLite 가 만들 수 있는 테이블만(pgvector Vector 쓰는 embeddings 만 제외).
TEST_TABLES = [
    User.__table__,
    Workspace.__table__,
    WorkspaceMember.__table__,
    AgentJob.__table__,
    Recommendation.__table__,
    Task.__table__,
    Conversation.__table__,
    Message.__table__,
]


class FakeRedis:
    """lpush 한 페이로드를 메모리 리스트에 쌓아두는 가짜 Redis."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def lpush(self, key: str, *values: str) -> int:
        bucket = self.lists.setdefault(key, [])
        for v in values:
            bucket.insert(0, v)
        return len(bucket)


class FakeCompetitionRepository:
    """고정 공모전 목록을 반환하는 가짜 repo."""

    def __init__(self, items: list[CompetitionOut] | None = None) -> None:
        self._items = items if items is not None else [
            CompetitionOut(id=1, title="AI 공모전", organizer="org", url="http://x"),
            CompetitionOut(id=2, title="데이터 해커톤", organizer="org2"),
        ]

    def list_open(self, limit: int = 20) -> list[CompetitionOut]:
        return self._items[:limit]


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng, tables=TEST_TABLES)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def test_user(db_session) -> User:
    user = User(email="me@contest-helper.dev", name="테스터", interests=[], skills=[])
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_repo() -> FakeCompetitionRepository:
    return FakeCompetitionRepository()


@pytest.fixture
def client(engine, test_user, fake_redis, fake_repo):
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: test_user
    fastapi_app.dependency_overrides[get_redis] = lambda: fake_redis
    fastapi_app.dependency_overrides[get_competition_repo] = lambda: fake_repo

    with TestClient(fastapi_app) as c:
        yield c

    fastapi_app.dependency_overrides.clear()
