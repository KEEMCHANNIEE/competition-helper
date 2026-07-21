"""_handle_workspace_edit 계약 테스트."""

from __future__ import annotations

import json

import pytest
from contest_helper_core.models import Conversation, Message, User, Workspace, WorkspaceMember
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from worker import agent


class _CannedLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


class _BoomLLM:
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for table in (User, Workspace, WorkspaceMember, Conversation, Message):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def workspace_conversation(session_factory: sessionmaker[Session]):
    """워크스페이스 1개 + 멤버 2명 + 그 워크스페이스에 연결된 대화 1개를 만든다."""
    with session_factory() as session:
        owner = User(email="owner@contest-helper.io", name="오너")
        mate = User(email="mate@contest-helper.io", name="메이트")
        session.add_all([owner, mate])
        session.flush()

        ws = Workspace(name="기존 이름", owner_id=owner.id, contest_id=None)
        session.add(ws)
        session.flush()
        session.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=mate.id, role="member"),
            ]
        )

        conv = Conversation(user_id=owner.id, workspace_id=ws.id)
        session.add(conv)
        session.commit()
        return ws.id, conv.id


def test_rename_only(session_factory, workspace_conversation):
    workspace_id, conversation_id = workspace_conversation

    reply = agent._handle_workspace_edit(
        conversation_id, "이름을 KOSAC 준비팀으로 바꿔줘",
        session_factory=session_factory, llm=_CannedLLM("KOSAC 준비팀"),
    )

    assert "KOSAC 준비팀" in reply
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        assert ws.name == "KOSAC 준비팀"
        assert ws.contest_id is None


def test_contest_change_only(session_factory, workspace_conversation):
    workspace_id, conversation_id = workspace_conversation
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps([{"ordinal": 1, "id": 42, "title": "새 공모전"}]),
            )
        )
        session.commit()

    reply = agent._handle_workspace_edit(
        conversation_id, "1번으로 바꿔줘",
        session_factory=session_factory, llm=_BoomLLM(),
    )

    assert "새 공모전" in reply
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        assert ws.contest_id == 42
        assert ws.name == "기존 이름"  # 이름은 안 바뀜


def test_rename_and_contest_change_together(session_factory, workspace_conversation):
    workspace_id, conversation_id = workspace_conversation
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps([{"ordinal": 1, "id": 7, "title": "합동 공모전"}]),
            )
        )
        session.commit()

    reply = agent._handle_workspace_edit(
        conversation_id, "이름은 새이름으로 바꾸고 1번 공모전으로 연결해줘",
        session_factory=session_factory, llm=_CannedLLM("새이름"),
    )

    assert "새이름" in reply and "합동 공모전" in reply
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        assert ws.name == "새이름"
        assert ws.contest_id == 7


def test_notifies_other_members(session_factory, workspace_conversation):
    workspace_id, conversation_id = workspace_conversation

    agent._handle_workspace_edit(
        conversation_id, "이름을 새이름으로 바꿔줘",
        session_factory=session_factory, llm=_CannedLLM("새이름"),
    )

    with session_factory() as session:
        notify_rows = session.query(Message).filter_by(role="notify").all()
        assert len(notify_rows) >= 1
        payload = json.loads(notify_rows[0].content)
        assert "새이름" in payload["text"]


def test_asks_for_clarification_when_nothing_detected(session_factory, workspace_conversation):
    _, conversation_id = workspace_conversation

    reply = agent._handle_workspace_edit(
        conversation_id, "음 그냥 그런 얘기였어",
        session_factory=session_factory, llm=_BoomLLM(),
    )

    assert "무엇을 바꾸고" in reply
    with session_factory() as session:
        assert session.query(Message).filter_by(role="notify").count() == 0


def test_ambiguous_contest_reference_does_not_apply_changes(session_factory, workspace_conversation):
    workspace_id, conversation_id = workspace_conversation
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps([{"ordinal": 1, "id": 42, "title": "공모전A"}]),
            )
        )
        session.commit()

    reply = agent._handle_workspace_edit(
        conversation_id, "5번으로 바꿔줘",
        session_factory=session_factory, llm=_BoomLLM(),
    )

    assert "특정하지 못했어요" in reply
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        assert ws.contest_id is None


def test_requires_existing_workspace(session_factory):
    with session_factory() as session:
        user = User(email="solo@contest-helper.io", name="솔로")
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id, workspace_id=None)
        session.add(conv)
        session.commit()
        conversation_id = conv.id

    reply = agent._handle_workspace_edit(
        conversation_id, "이름을 바꿔줘",
        session_factory=session_factory, llm=_CannedLLM("아무이름"),
    )

    # 워크스페이스가 없으면 수정 대신 생성 쪽으로 안내한다(참여 유도형 가드).
    assert "아직 연결된 워크스페이스가 없어요" in reply
