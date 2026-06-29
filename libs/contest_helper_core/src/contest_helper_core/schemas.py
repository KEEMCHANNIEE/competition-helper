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
    """공모전 DB(contests 테이블) 읽기 결과 1건.

    deadline = contests.end_date, url = contests.homepage 로 매핑한다.
    (호환 위해 deadline/organizer/url 필드명 유지)
    """

    id: int
    title: str
    organizer: str | None = None
    host: str | None = None
    category: list[str] = []
    target: list[str] = []
    keywords: list[str] = []
    start_date: date | None = None
    deadline: date | None = None  # = contests.end_date
    url: str | None = None  # = contests.homepage
    poster_url: str | None = None
    total_prize_amount: int | None = None
    participation_type: str | None = None
    status: str | None = None  # 진행중 / 마감


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
