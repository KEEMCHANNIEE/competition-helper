"""진행 상황 저장 도구 — save_progress.

워크스페이스 에이전트(`worker.progress_agent`)가 계산한 진행률(%)·코멘트를
App DB의 ``workspace_progress`` 에 실제로 저장한다. (``tasks.create_tasks`` 와
같은 패턴: "계산"은 다른 곳에서, "쓰기"는 이 도구가 전담.)
"""

from __future__ import annotations

from collections.abc import Callable

from contest_helper_core.db import get_engine
from contest_helper_core.models import WorkspaceProgress
from contest_helper_core.schemas import ProgressOut
from sqlalchemy.orm import Session, sessionmaker


def _default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def save_progress(
    workspace_id: int,
    user_id: int,
    *,
    percent: int,
    comment: str,
    task_done: int,
    task_total: int,
    session_factory: Callable[[], Session] | None = None,
) -> ProgressOut:
    """진행 상황 1건을 ``workspace_progress`` 행으로 저장한다.

    Args:
        workspace_id: 진행 상황이 속한 워크스페이스 id.
        user_id: 진행 상황을 평가받는 사용자 id.
        percent: 0~100 진행률.
        comment: LLM(또는 폴백)이 생성한 코멘트.
        task_done: 완료된 할 일 수.
        task_total: 전체 할 일 수.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.

    Returns:
        저장된 값을 담은 ``ProgressOut``.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    with session_factory() as session:
        row = WorkspaceProgress(
            workspace_id=workspace_id,
            user_id=user_id,
            percent=percent,
            comment=comment,
            task_done=task_done,
            task_total=task_total,
        )
        session.add(row)
        session.commit()
        return ProgressOut(
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            percent=row.percent,
            comment=row.comment,
            task_done=row.task_done,
            task_total=row.task_total,
        )
