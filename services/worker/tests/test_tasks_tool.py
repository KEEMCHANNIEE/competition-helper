"""create_tasks 도구 계약 테스트.

계획 능력의 "쓰기" 도구: 계획을 워크스페이스 할 일(Task)로 저장한다.
"""

from __future__ import annotations

import pytest
from contest_helper_core.schemas import TaskIn, TaskOut
from worker.mcp_tools import registry, tasks

_SKIP_REASON = "create_tasks 가 실제 DB 호출 — mock 없인 CI 에서 멈춤. session_factory 주입 후 skip 제거"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_create_tasks_returns_saved_task_out():
    # 구현 후: 입력 TaskIn 들을 워크스페이스에 저장하고 id 가 채워진 TaskOut 으로 돌려준다.
    plan = [
        TaskIn(title="기획서 초안", description="문제정의", assignee_id=1, week_no=1),
        TaskIn(title="모델 베이스라인", week_no=2),
    ]
    saved = tasks.create_tasks(workspace_id=1, tasks=plan)
    assert isinstance(saved, list)
    assert all(isinstance(t, TaskOut) for t in saved)
    assert [t.title for t in saved] == ["기획서 초안", "모델 베이스라인"]
    assert all(t.id is not None for t in saved)


def test_create_tasks_registered_in_registry():
    # 레지스트리에 도구로 등록되어 있어야 한다(이름 계약).
    assert tasks.create_tasks is registry.TOOLS["create_tasks"]
