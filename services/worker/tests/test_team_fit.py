"""team_fit.evaluate_team_fit 계약 테스트."""

from __future__ import annotations

import pytest
from contest_helper_core.models import User, Workspace, WorkspaceMember
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from worker import team_fit


class _CannedLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


class _BoomLLM:
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


@pytest.fixture()
def team_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (User, Workspace, WorkspaceMember):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def team_workspace(team_session_factory: sessionmaker[Session]) -> int:
    """팀원 2명(관심사·스킬 있음)이 있는 워크스페이스를 만든다."""
    with team_session_factory() as session:
        owner = User(
            email="owner@contest-helper.io", name="오너",
            interests=["마케팅"], skills=["기획"],
        )
        mate = User(
            email="mate@contest-helper.io", name="메이트",
            interests=["데이터분석"], skills=["python"],
        )
        session.add_all([owner, mate])
        session.flush()

        ws = Workspace(name="AI 해커톤", owner_id=owner.id, contest_id=1)
        session.add(ws)
        session.flush()

        session.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=mate.id, role="member"),
            ]
        )
        session.commit()
        return ws.id


def _fake_detail(**overrides):
    from datetime import date

    from worker.mcp_tools.competitions import CompetitionDetailOut

    base = dict(
        id=1, title="AI 해커톤", category=["데이터"], requirements=["대학생"],
        evaluation_criteria=["데이터 활용도"], deadline=date(2026, 5, 31),
    )
    base.update(overrides)
    return CompetitionDetailOut(**base)


def test_evaluate_team_fit_uses_llm_comment(team_session_factory, team_workspace):
    tools = {"get_competition_detail": lambda cid: _fake_detail(id=cid)}

    result = team_fit.evaluate_team_fit(
        team_workspace,
        session_factory=team_session_factory,
        tools=tools,
        llm=_CannedLLM("팀 적합도가 좋아요."),
    )

    assert result == "팀 적합도가 좋아요."


def test_evaluate_team_fit_falls_back_when_llm_fails(team_session_factory, team_workspace):
    tools = {"get_competition_detail": lambda cid: _fake_detail(id=cid)}

    result = team_fit.evaluate_team_fit(
        team_workspace,
        session_factory=team_session_factory,
        tools=tools,
        llm=_BoomLLM(),
    )

    assert isinstance(result, str)
    assert result
    assert "오너" in result and "메이트" in result


def test_evaluate_team_fit_handles_workspace_without_contest(team_session_factory):
    with team_session_factory() as session:
        owner = User(email="solo@contest-helper.io", name="솔로", interests=[], skills=[])
        session.add(owner)
        session.flush()
        ws = Workspace(name="아직 공모전 미정", owner_id=owner.id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
        session.commit()
        workspace_id = ws.id

    result = team_fit.evaluate_team_fit(
        workspace_id,
        session_factory=team_session_factory,
        tools={"get_competition_detail": lambda cid: None},
        llm=_BoomLLM(),
    )

    assert "연결된 공모전" in result or "공모전" in result


def test_evaluate_team_fit_returns_guidance_when_no_members(team_session_factory):
    with team_session_factory() as session:
        owner = User(email="ghost@contest-helper.io", name="고스트")
        session.add(owner)
        session.flush()
        ws = Workspace(name="멤버 없음", owner_id=owner.id)
        session.add(ws)
        session.commit()
        workspace_id = ws.id

    result = team_fit.evaluate_team_fit(
        workspace_id,
        session_factory=team_session_factory,
        tools={},
        llm=_CannedLLM("무시됨"),
    )

    assert "팀원" in result
