"""역할 간 통신 계약(DTO). api·worker·web 이 모두 이 모양으로 대화한다."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class JobStatus(StrEnum):
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


# ---- 대화(채팅) ----

class ChatJobPayload(BaseModel):
    """api → 큐 → worker 로 전달되는 채팅 작업 입력."""

    job_id: str
    user_id: int
    conversation_id: int


class MessageOut(BaseModel):
    """대화 속 한 줄."""

    role: str  # user / assistant
    content: str


class ChatStateOut(BaseModel):
    """api → web 채팅 폴링 응답. pending=True 면 에이전트가 아직 답하는 중."""

    conversation_id: int
    pending: bool
    messages: list[MessageOut] = []
    error: str | None = None


# ---- 계획(할 일) ----

class TaskOut(BaseModel):
    """워크스페이스 할 일 1건."""

    id: int
    title: str
    description: str | None = None
    status: str = "todo"
    assignee_id: int | None = None
    week_no: int | None = None


class TaskIn(BaseModel):
    """create_tasks 도구가 받는 할 일 입력(저장 전)."""

    title: str
    description: str | None = None
    assignee_id: int | None = None
    week_no: int | None = None


# ---- 진행 상황(워크스페이스 에이전트) ----


class ProgressOut(BaseModel):
    """워크스페이스 에이전트가 계산·저장한 사용자별 진행 상황 1건."""

    workspace_id: int
    user_id: int
    percent: int  # 0~100
    comment: str  # LLM 코멘트(실패 시 규칙 기반 폴백)
    task_done: int
    task_total: int
