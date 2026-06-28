"""추천 라우터.

POST /recommend  : job 생성 → Redis enqueue → 즉시 202 {job_id}
GET  /recommend/{job_id} : agent_jobs + recommendations 폴링 → JobResultOut

api 는 LLM 을 직접 호출하지 않는다(무거운 작업은 worker 로 위임).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from keenee_core.models import AgentJob, Recommendation, User
from keenee_core.schemas import JobResultOut, JobStatus, RecommendationOut

from app.deps import get_current_user, get_db, get_redis
from app.queue import enqueue_recommend

if TYPE_CHECKING:
    from redis import Redis

router = APIRouter(tags=["recommend"])

# 진행 중으로 간주해 재사용하는 상태들.
_ACTIVE = ("queued", "running")


class RecommendRequest(BaseModel):
    limit: int = Field(5, ge=1, le=50)


class RecommendAccepted(BaseModel):
    job_id: str


@router.post(
    "/recommend",
    response_model=RecommendAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_recommendation(
    payload: RecommendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    redis: "Redis" = Depends(get_redis),
) -> RecommendAccepted:
    """추천 작업 생성. 이미 진행 중인 작업이 있으면 재사용(중복 방지)."""
    existing = db.scalar(
        select(AgentJob)
        .where(AgentJob.user_id == current_user.id, AgentJob.status.in_(_ACTIVE))
        .order_by(AgentJob.created_at.desc())
    )
    if existing is not None:
        return RecommendAccepted(job_id=existing.job_id)

    job_id = enqueue_recommend(
        db, redis, user_id=current_user.id, limit=payload.limit
    )
    return RecommendAccepted(job_id=job_id)


@router.get("/recommend/{job_id}", response_model=JobResultOut)
def get_recommendation(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobResultOut:
    """작업 상태와 결과를 반환. 없는 job 404, 소유자만 조회 가능."""
    job = db.scalar(select(AgentJob).where(AgentJob.job_id == job_id))
    if job is None or job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="작업을 찾을 수 없습니다.",
        )

    rows = db.scalars(
        select(Recommendation)
        .where(Recommendation.job_id == job_id)
        .order_by(Recommendation.id.asc())
    ).all()
    results = [
        RecommendationOut(
            competition_id=r.competition_id,
            title=r.title,
            reason=r.reason,
            score=r.score,
        )
        for r in rows
    ]

    return JobResultOut(
        job_id=job.job_id,
        status=JobStatus(job.status),
        results=results,
        error=job.error,
    )
