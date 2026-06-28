"""워크스페이스 라우터: 생성·멤버 초대·추천 공유·조회."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from contest_helper_core.models import User

from app.deps import get_current_user, get_db
from app.workspaces import service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str


class MemberCreate(BaseModel):
    email: str
    role: str = "member"


class RecommendationAttach(BaseModel):
    recommendation_ids: list[int]


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_id: int
    created_at: datetime | None = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    user_id: int
    role: str


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
    ws = service.create_workspace(db, name=payload.name, owner=current_user)
    return WorkspaceOut.model_validate(ws)


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
        created_at=ws.created_at,
        recommendations=[RecommendationItem.model_validate(r) for r in recos],
    )
