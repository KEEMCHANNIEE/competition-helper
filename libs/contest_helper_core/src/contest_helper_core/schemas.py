"""역할 간 통신 계약(DTO). api·worker·web 이 모두 이 모양으로 대화한다."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class RecommendJobPayload(BaseModel):
    """api → 큐 → worker 로 전달되는 추천 작업 입력."""

    job_id: str
    user_id: int
    limit: int = 5


class CompetitionOut(BaseModel):
    """공모전 DB 읽기 결과 1건."""

    id: int
    title: str
    deadline: date | None = None
    organizer: str | None = None
    url: str | None = None


class RecommendationOut(BaseModel):
    """worker 가 생성하는 추천 결과 1건."""

    competition_id: int
    title: str
    reason: str
    score: float | None = None


class JobResultOut(BaseModel):
    """api → web 폴링 응답."""

    job_id: str
    status: JobStatus
    results: list[RecommendationOut] = []
    error: str | None = None
