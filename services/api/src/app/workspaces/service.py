"""워크스페이스/멤버십 비즈니스 로직 + 권한 체크.

권한 위반은 HTTPException(403), 미존재는 404 로 통일한다.
"""

from __future__ import annotations

from contest_helper_core.models import (
    Recommendation,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import TaskIn
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_workspace_or_404(db: Session, workspace_id: int) -> Workspace:
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="워크스페이스를 찾을 수 없습니다.",
        )
    return ws


def is_member(db: Session, workspace_id: int, user_id: int) -> bool:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    return member is not None


def require_member(db: Session, workspace_id: int, user_id: int) -> None:
    if not is_member(db, workspace_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="워크스페이스 멤버만 접근할 수 있습니다.",
        )


def require_owner(db: Session, ws: Workspace, user_id: int) -> None:
    if ws.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="워크스페이스 소유자만 가능합니다.",
        )


def create_workspace(
    db: Session, *, name: str, owner: User, contest_id: int | None = None
) -> Workspace:
    """팀 생성. 생성자를 owner 로 두고 멤버로도 등록한다."""
    ws = Workspace(name=name, owner_id=owner.id, contest_id=contest_id)
    db.add(ws)
    db.flush()  # ws.id 확보

    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
    db.commit()
    db.refresh(ws)
    return ws


def add_member(
    db: Session,
    *,
    ws: Workspace,
    actor: User,
    email: str,
    role: str = "member",
) -> WorkspaceMember:
    """멤버 초대(owner 만). 대상 사용자 미존재 404, 중복 초대 409."""
    require_owner(db, ws, actor.id)

    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="초대할 사용자를 찾을 수 없습니다.",
        )

    if is_member(db, ws.id, target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 멤버입니다.",
        )

    member = WorkspaceMember(workspace_id=ws.id, user_id=target.id, role=role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def attach_recommendations(
    db: Session,
    *,
    ws: Workspace,
    actor: User,
    recommendation_ids: list[int],
) -> int:
    """추천을 팀에 저장(멤버만). 적용된 행 수를 반환."""
    require_member(db, ws.id, actor.id)

    rows = db.scalars(
        select(Recommendation).where(Recommendation.id.in_(recommendation_ids))
    ).all()
    for r in rows:
        r.workspace_id = ws.id
    db.commit()
    return len(rows)


def list_recommendations(db: Session, workspace_id: int) -> list[Recommendation]:
    return list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.workspace_id == workspace_id)
            .order_by(Recommendation.id.asc())
        ).all()
    )


def list_tasks(db: Session, workspace_id: int) -> list[Task]:
    """워크스페이스 할 일 목록. week_no, id 순으로 정렬한다."""
    return list(
        db.scalars(
            select(Task)
            .where(Task.workspace_id == workspace_id)
            .order_by(Task.week_no.asc(), Task.id.asc())
        ).all()
    )


def add_task(
    db: Session, *, ws: Workspace, actor: User, payload: TaskIn
) -> Task:
    """할 일 1건 추가(멤버만)."""
    require_member(db, ws.id, actor.id)

    task = Task(
        workspace_id=ws.id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        week_no=payload.week_no,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
