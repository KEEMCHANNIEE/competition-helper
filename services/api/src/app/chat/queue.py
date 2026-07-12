"""채팅 큐 enqueue 래퍼.

queue.py(enqueue_recommend)와 동일한 스타일로 채팅 작업을 큐에 넣는다.
worker 의 BRPOP 소비부와 키·페이로드 모양이 정확히 일치해야 한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from contest_helper_core.models import AgentJob
from contest_helper_core.schemas import ChatJobPayload
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from redis import Redis

# worker 가 소비하는 채팅 작업 리스트 키. 절대 변경 금지(계약).
CHAT_QUEUE_KEY = "contest-helper:jobs:chat"


def enqueue_chat(
    db: Session,
    redis: Redis,
    *,
    user_id: int,
    conversation_id: int,
) -> str:
    """AgentJob(queued) 생성 후 Redis 리스트에 페이로드를 push, job_id 반환.

    DB 커밋을 먼저 끝내 작업 기록을 영속화한 뒤 enqueue 한다.
    (enqueue_recommend 와 동일한 순서)
    """
    job_id = uuid4().hex

    job = AgentJob(job_id=job_id, user_id=user_id, status="queued")
    db.add(job)
    db.commit()

    payload = ChatJobPayload(
        job_id=job_id, user_id=user_id, conversation_id=conversation_id
    )
    redis.lpush(CHAT_QUEUE_KEY, payload.model_dump_json())

    return job_id
