"""progress_agent.evaluate_progress 계약 테스트.

워크스페이스 에이전트(다이어그램 ②)의 핵심: Task 완료 비율(수치 %) +
LLM 코멘트를 합쳐 workspace_progress 에 실제로 저장하는지 검증한다.
"""

from __future__ import annotations

import pytest
from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceProgress,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from worker import progress_agent
from worker.mcp_tools import registry


class _CannedLLM:
    """LLM 성공 경로를 흉내내는 가짜 클라이언트."""

    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


class _BoomLLM:
    """LLM 실패(폴백 경로 검증용) 가짜 클라이언트."""

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


@pytest.fixture()
def progress_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (User, Workspace, Task, Conversation, Message, WorkspaceProgress):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def seed(progress_session_factory: sessionmaker[Session]) -> tuple[int, int]:
    """워크스페이스 1개 + 사용자 1명 + 할일 2개(완료 1, 미완료 1)를 만든다."""
    with progress_session_factory() as session:
        user = User(email="progress@contest-helper.io", name="Progress Tester")
        session.add(user)
        session.flush()

        ws = Workspace(name="AI 해커톤 준비", owner_id=user.id)
        session.add(ws)
        session.flush()

        session.add_all(
            [
                Task(workspace_id=ws.id, title="기획서 초안", status="done", assignee_id=user.id),
                Task(
                    workspace_id=ws.id, title="모델 베이스라인", status="todo", assignee_id=user.id
                ),
            ]
        )

        conv = Conversation(user_id=user.id, workspace_id=ws.id)
        session.add(conv)
        session.flush()
        session.add(
            Message(conversation_id=conv.id, role="user", content="기획서 초안 다 썼어요")
        )
        session.commit()
        return ws.id, user.id


def test_evaluate_progress_computes_percent_from_tasks(progress_session_factory, seed):
    workspace_id, user_id = seed

    result = progress_agent.evaluate_progress(
        workspace_id,
        user_id,
        session_factory=progress_session_factory,
        llm=_CannedLLM("순조롭게 진행 중이에요."),
        tools=registry.build_registry(),
    )

    assert result.task_done == 1
    assert result.task_total == 2
    assert result.percent == 50
    assert result.comment == "순조롭게 진행 중이에요."


def test_evaluate_progress_saves_row_in_db(progress_session_factory, seed):
    workspace_id, user_id = seed

    progress_agent.evaluate_progress(
        workspace_id,
        user_id,
        session_factory=progress_session_factory,
        llm=_CannedLLM("좋아요"),
        tools=registry.build_registry(),
    )

    with progress_session_factory() as session:
        rows = session.query(WorkspaceProgress).filter_by(workspace_id=workspace_id).all()
        assert len(rows) == 1
        assert rows[0].user_id == user_id
        assert rows[0].percent == 50


def test_evaluate_progress_falls_back_when_llm_fails(progress_session_factory, seed):
    workspace_id, user_id = seed

    result = progress_agent.evaluate_progress(
        workspace_id,
        user_id,
        session_factory=progress_session_factory,
        llm=_BoomLLM(),
        tools=registry.build_registry(),
    )

    # LLM 이 죽어도 전체 평가가 실패하면 안 되고, 규칙 기반 코멘트로 대체돼야 한다.
    assert isinstance(result.comment, str)
    assert result.comment
    assert result.percent == 50


def test_evaluate_progress_returns_zero_percent_when_no_tasks(progress_session_factory):
    with progress_session_factory() as session:
        user = User(email="empty@contest-helper.io", name="Empty")
        session.add(user)
        session.flush()
        ws = Workspace(name="아직 할일 없음", owner_id=user.id)
        session.add(ws)
        session.commit()
        workspace_id, user_id = ws.id, user.id

    result = progress_agent.evaluate_progress(
        workspace_id,
        user_id,
        session_factory=progress_session_factory,
        llm=_CannedLLM("아직 시작 전이에요."),
        tools=registry.build_registry(),
    )

    assert result.task_total == 0
    assert result.percent == 0
