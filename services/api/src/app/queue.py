"""Redis 큐 enqueue 래퍼.

worker 와의 큐 계약(키·페이로드 모양·job_id 규칙)을 한 곳에 고정한다.
이 모양이 worker 의 BRPOP 소비부와 정확히 일치해야 한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.orm import Session

from contest_helper_core.models import AgentJob
from contest_helper_core.schemas import RecommendJobPayload

if TYPE_CHECKING:
    from redis import Redis

# worker 가 소비하는 추천 작업 리스트 키. 절대 변경 금지(계약).
RECOMMEND_QUEUE_KEY = "contest-helper:jobs:recommend"


def enqueue_recommend(
    db: Session,
    redis: "Redis",
    *,
    user_id: int,
    limit: int = 5,
) -> str:
    """AgentJob(queued) 생성 후 Redis 리스트에 페이로드를 push, job_id 반환.

    DB 커밋을 먼저 끝내 작업 기록을 영속화한 뒤 enqueue 한다.
    """
    job_id = uuid4().hex

    job = AgentJob(job_id=job_id, user_id=user_id, status="queued")
    db.add(job)
    db.commit()

    payload = RecommendJobPayload(job_id=job_id, user_id=user_id, limit=limit)
    redis.lpush(RECOMMEND_QUEUE_KEY, payload.model_dump_json())

    return job_id
