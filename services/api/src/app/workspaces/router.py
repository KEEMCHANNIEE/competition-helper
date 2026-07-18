"""워크스페이스 라우터: 생성·멤버 초대·추천 공유·조회."""

from __future__ import annotations

from datetime import datetime

from contest_helper_core.models import User, Workspace
from contest_helper_core.schemas import TaskIn, TaskOut
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.workspaces import service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str
    contest_id: int | None = None


class MemberCreate(BaseModel):
    email: str
    role: str = "member"


class RecommendationAttach(BaseModel):
    recommendation_ids: list[int]


class TaskStatusUpdate(BaseModel):
    status: str  # "todo" | "done"


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_id: int
    contest_id: int | None = None
    created_at: datetime | None = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    user_id: int
    role: str


class MemberInfoOut(BaseModel):
    """팀원 전환 스위치용 멤버 정보(이름·역할 포함)."""

    user_id: int
    name: str
    role: str
    is_owner: bool


class LogOut(BaseModel):
    """워크스페이스 실행 로그 1건(작성자·시각·내용). content 는 '제목:/요약:/키워드:' 텍스트."""

    id: int
    author: str
    created_at: datetime | None = None
    content: str


class ReportOut(BaseModel):
    """주간 리포트 1건. content 는 'N주차 주간 리포트\\n전체 진행률: ...' 형식 텍스트."""

    id: int
    author: str
    created_at: datetime | None = None
    content: str


class RecommendationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    competition_id: int
    title: str
    reason: str
    score: float | None = None


class WorkspaceDetailOut(WorkspaceOut):
    recommendations: list[RecommendationItem] = []


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    ws = service.create_workspace(
        db, name=payload.name, owner=current_user, contest_id=payload.contest_id
    )
    return WorkspaceOut.model_validate(ws)


@router.get("", response_model=list[WorkspaceOut])
def list_my_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkspaceOut]:
    """내가 멤버인 워크스페이스 목록(최신순). 프론트가 표시할 워크스페이스를 고를 때 사용."""
    return [
        WorkspaceOut.model_validate(w)
        for w in service.list_my_workspaces(db, current_user.id)
    ]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: int,
    payload: MemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemberOut:
    ws = service.get_workspace_or_404(db, workspace_id)
    member = service.add_member(
        db, ws=ws, actor=current_user, email=payload.email, role=payload.role
    )
    return MemberOut.model_validate(member)


def _member_infos(db: Session, ws: Workspace, workspace_id: int) -> list[MemberInfoOut]:
    return [
        MemberInfoOut(
            user_id=u.id,
            name=u.name or u.email,
            role=m.role,
            is_owner=(u.id == ws.owner_id),
        )
        for m, u in service.list_members(db, workspace_id)
    ]


@router.get("/{workspace_id}/members", response_model=list[MemberInfoOut])
def list_workspace_members(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MemberInfoOut]:
    """워크스페이스 멤버 목록(이름·역할). 팀원 전환 스위치가 사용한다."""
    ws = service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    return _member_infos(db, ws, workspace_id)


@router.post("/{workspace_id}/demo-team", response_model=list[MemberInfoOut])
def setup_demo_team(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MemberInfoOut]:
    """[데모용] 팀원(유진·채원·채은)을 추가하고 할 일을 4명에게 배정한다.

    발표에서 '팀원 전환'으로 멤버별 진행률·주간 리포트를 보여주기 위한 시드 데이터.
    """
    ws = service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    service.ensure_demo_team(db, ws=ws)
    return _member_infos(db, ws, workspace_id)


@router.get("/{workspace_id}/reports", response_model=list[ReportOut])
def list_workspace_reports(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    """워크스페이스 주간 리포트 목록(멤버만, 최신순). S-03 STEP01."""
    service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    return [
        ReportOut(
            id=m.id,
            author=(u.name or u.email),
            created_at=m.created_at,
            content=m.content,
        )
        for m, u in service.list_reports(db, workspace_id)
    ]


@router.post("/{workspace_id}/weekly-report", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_weekly_report(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportOut:
    """주간 리포트를 지금 집계·생성한다(멤버만). '주간 리포트 생성' 버튼 / cron 진입점."""
    ws = service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    m = service.generate_weekly_report(db, ws=ws)
    author = current_user.name or current_user.email
    return ReportOut(id=m.id, author=author, created_at=m.created_at, content=m.content)


@router.post("/{workspace_id}/proposals/approve")
def approve_proposal(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """AI 제안(계획 변경)을 승인·반영한다. **팀장(owner)만 가능.** (S-03 STEP02)"""
    ws = service.get_workspace_or_404(db, workspace_id)
    service.require_owner(db, ws, current_user.id)  # 팀장만 승인 가능
    result = service.apply_latest_proposal(db, ws=ws)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="반영할 제안이 없습니다.",
        )
    # 조정 대상 팀원에게 알림 발송(S-03 STEP03): 그 팀원이 입장하면 보인다.
    member_id = result.get("member_id")
    if member_id and not result.get("already_applied"):
        actor = current_user.name or current_user.email
        service.create_notification(
            db,
            workspace_id=workspace_id,
            recipient_id=member_id,
            text=f"{actor}님이 일정을 조정했어요 — {result.get('label', '')}",
        )
    return result


@router.get("/{workspace_id}/logs", response_model=list[LogOut])
def list_workspace_logs(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LogOut]:
    """워크스페이스 실행 로그 목록(멤버만, 최신순). S-02 STEP02 로 기록된 작업 요약."""
    service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    return [
        LogOut(
            id=m.id,
            author=(u.name or u.email),
            created_at=m.created_at,
            content=m.content,
        )
        for m, u in service.list_logs(db, workspace_id)
    ]


@router.post("/{workspace_id}/recommendations")
def attach_recommendations(
    workspace_id: int,
    payload: RecommendationAttach,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ws = service.get_workspace_or_404(db, workspace_id)
    count = service.attach_recommendations(
        db,
        ws=ws,
        actor=current_user,
        recommendation_ids=payload.recommendation_ids,
    )
    return {"attached": count}


@router.get("/{workspace_id}", response_model=WorkspaceDetailOut)
def get_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceDetailOut:
    ws = service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    recos = service.list_recommendations(db, workspace_id)
    return WorkspaceDetailOut(
        id=ws.id,
        name=ws.name,
        owner_id=ws.owner_id,
        contest_id=ws.contest_id,
        created_at=ws.created_at,
        recommendations=[RecommendationItem.model_validate(r) for r in recos],
    )


@router.get("/{workspace_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    """워크스페이스 할 일 목록(멤버만). week_no, id 순."""
    service.get_workspace_or_404(db, workspace_id)
    service.require_member(db, workspace_id, current_user.id)
    tasks = service.list_tasks(db, workspace_id)
    return [TaskOut.model_validate(t, from_attributes=True) for t in tasks]


@router.post(
    "/{workspace_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
def add_task(
    workspace_id: int,
    payload: TaskIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    """할 일 1건 수동 추가(멤버만)."""
    ws = service.get_workspace_or_404(db, workspace_id)
    task = service.add_task(db, ws=ws, actor=current_user, payload=payload)
    return TaskOut.model_validate(task, from_attributes=True)


@router.patch("/{workspace_id}/tasks/{task_id}", response_model=TaskOut)
def update_task_status(
    workspace_id: int,
    task_id: int,
    payload: TaskStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    """할 일 1건의 완료 상태 변경(멤버만). 체크박스 토글용."""
    ws = service.get_workspace_or_404(db, workspace_id)
    task = service.update_task_status(
        db, ws=ws, actor=current_user, task_id=task_id, new_status=payload.status
    )
    return TaskOut.model_validate(task, from_attributes=True)
