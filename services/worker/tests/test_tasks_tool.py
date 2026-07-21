"""create_tasks 도구 계약 테스트.

계획 능력의 "쓰기" 도구: 계획을 워크스페이스 할 일(Task)로 저장한다.
실제 App DB(Docker)에 쓰므로, 필요한 유저·워크스페이스를 직접 시드하고 정리한다
(하드코딩 id=1 은 DB 를 비우면 FK 위반으로 깨진다).
"""

from __future__ import annotations

import pytest
from contest_helper_core.db import get_engine
from contest_helper_core.models import Task, User, Workspace
from contest_helper_core.schemas import TaskIn, TaskOut
from sqlalchemy.orm import sessionmaker
from worker.mcp_tools import registry, tasks

_SKIP_REASON = "create_tasks 가 실제 DB 호출 — mock 없인 CI 에서 멈춤. session_factory 주입 후 skip 제거"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_create_tasks_returns_saved_task_out():
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        user = User(
            email="tasks-tool-test@conmate.local", name="테스트", interests=[], skills=[]
        )
        session.add(user)
        session.flush()
        ws = Workspace(name="tasks-tool-test", owner_id=user.id)
        session.add(ws)
        session.commit()
        uid, wid = user.id, ws.id

    try:
        plan = [
            TaskIn(title="기획서 초안", description="문제정의", assignee_id=uid, week_no=1),
            TaskIn(title="모델 베이스라인", week_no=2),
        ]
        saved = tasks.create_tasks(workspace_id=wid, tasks=plan)
        assert isinstance(saved, list)
        assert all(isinstance(t, TaskOut) for t in saved)
        assert [t.title for t in saved] == ["기획서 초안", "모델 베이스라인"]
        assert all(t.id is not None for t in saved)
    finally:
        with factory() as session:
            session.query(Task).filter_by(workspace_id=wid).delete()
            session.query(Workspace).filter_by(id=wid).delete()
            session.query(User).filter_by(id=uid).delete()
            session.commit()


def test_create_tasks_registered_in_registry():
    # 레지스트리에 도구로 등록되어 있어야 한다(이름 계약).
    assert tasks.create_tasks is registry.TOOLS["create_tasks"]
