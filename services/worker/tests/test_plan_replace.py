"""_handle_plan 계약 테스트 — 계획 "교체" 동작.

핵심 회귀 지점: 계획을 다시 짜면 이전 계획에 계속 "추가"되는 게 아니라,
미완료(todo) 할 일은 새 계획으로 교체되고 완료(done)된 할 일은 보존돼야 한다.
LLM 실패 시엔 기존 계획을 지우지 않아야 한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from worker import agent
from worker.mcp_tools import tasks as tasks_tool


class _CannedLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


class _FailingLLM:
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for model in (User, Conversation, Message, Workspace, WorkspaceMember, Task):
        model.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def workspace_conv(session_factory: sessionmaker[Session]) -> tuple[int, int]:
    """워크스페이스에 연결된 대화와 기존 계획(완료 1 + 미완료 2)을 만든다."""
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="A", interests=[], skills=[])
        session.add(user)
        session.flush()
        ws = Workspace(name="테스트 워크스페이스", owner_id=user.id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        conv = Conversation(user_id=user.id, workspace_id=ws.id)
        session.add(conv)
        session.flush()
        session.add_all(
            [
                Task(workspace_id=ws.id, title="완료된 조사", status="done", week_no=1),
                Task(workspace_id=ws.id, title="옛 할 일 1", status="todo", week_no=1),
                Task(workspace_id=ws.id, title="옛 할 일 2", status="todo", week_no=2),
            ]
        )
        session.commit()
        return conv.id, ws.id


def _tools(session_factory: sessionmaker[Session]) -> dict:
    return {
        "create_tasks": lambda workspace_id, tasks: tasks_tool.create_tasks(
            workspace_id=workspace_id, tasks=tasks, session_factory=session_factory
        )
    }


def test_plan_rerun_replaces_todo_and_keeps_done(session_factory, workspace_conv):
    conversation_id, workspace_id = workspace_conv

    reply = agent._handle_plan(
        conversation_id,
        "1주차 줄여줘",
        _tools(session_factory),
        session_factory=session_factory,
        llm=_CannedLLM("1주차 | 새 할 일 A\n2주차 | 새 할 일 B"),
    )

    with session_factory() as session:
        titles = {
            t.title
            for t in session.execute(
                select(Task).where(Task.workspace_id == workspace_id)
            ).scalars()
        }
    # 미완료였던 옛 계획은 사라지고 새 계획으로 교체, 완료된 할 일은 보존된다.
    assert titles == {"완료된 조사", "새 할 일 A", "새 할 일 B"}
    assert "교체" in reply


def test_plan_rerun_llm_failure_keeps_existing_plan(session_factory, workspace_conv):
    conversation_id, workspace_id = workspace_conv

    reply = agent._handle_plan(
        conversation_id,
        "계획 다시 짜줘",
        _tools(session_factory),
        session_factory=session_factory,
        llm=_FailingLLM(),
    )

    with session_factory() as session:
        titles = {
            t.title
            for t in session.execute(
                select(Task).where(Task.workspace_id == workspace_id)
            ).scalars()
        }
    # 수정 생성 실패 시 기존 계획을 지우지 않는다.
    assert titles == {"완료된 조사", "옛 할 일 1", "옛 할 일 2"}
    assert "수정하지 못했어요" in reply


def test_plan_without_any_material_asks_first(session_factory):
    """주제·배경·마감·기존 계획이 전혀 없으면 일반론을 만들지 않고 먼저 묻는다."""
    with session_factory() as session:
        user = User(email="b@contest-helper.io", name="B", interests=[], skills=[])
        session.add(user)
        session.flush()
        ws = Workspace(name="빈 워크스페이스", owner_id=user.id)
        session.add(ws)
        session.flush()
        conv = Conversation(user_id=user.id, workspace_id=ws.id)
        session.add(conv)
        session.commit()
        conv_id, ws_id = conv.id, ws.id

    reply = agent._handle_plan(
        conv_id,
        "계획 짜줘",
        _tools(session_factory),
        session_factory=session_factory,
        llm=_CannedLLM("1주차 | 아무거나"),
    )

    with session_factory() as session:
        count = len(
            session.execute(select(Task).where(Task.workspace_id == ws_id))
            .scalars()
            .all()
        )
    assert count == 0  # 할 일을 만들지 않고
    assert "?" in reply  # 되묻는다