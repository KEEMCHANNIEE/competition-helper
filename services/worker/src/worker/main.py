"""큐 소비 루프 + 작업 상태기계 + DB 영속화 (배관: 완전 구현).

이 모듈은 과제(stub)가 아니다. 큐에서 작업을 꺼내고, ``AgentJob`` 상태를
queued→running→done/failed 로 전이시키며, 에이전트가 만든 추천을
``Recommendation`` 행으로 저장하는 "수도 배관" 전부를 책임진다.

상태를 메모리에 두지 않는다(전부 App DB). 그래야 worker 를 복제할 수 있다.

큐 계약 (api 와 정확히 일치해야 함):
- 추천 리스트 키: ``contest-helper:jobs:recommend`` (payload: ``RecommendJobPayload``)
- 채팅 리스트 키: ``contest-helper:jobs:chat`` (payload: ``ChatJobPayload``)
- 클라이언트: ``redis.from_url(get_settings().redis_url)`` (동기 redis-py)

루프는 두 키를 한 번에 ``brpop`` 으로 대기하고, 어느 키에서 나왔는지로 디스패치한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.config import get_settings
from contest_helper_core.db import get_engine
from contest_helper_core.models import AgentJob, Message, Recommendation
from contest_helper_core.schemas import (
    ChatJobPayload,
    JobStatus,
    RecommendationOut,
    RecommendJobPayload,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 체크 전용
    from redis import Redis

# api 와 공유하는 큐 키. 절대 바꾸지 말 것(계약).
QUEUE_KEY = "contest-helper:jobs:recommend"
CHAT_QUEUE_KEY = "contest-helper:jobs:chat"

# brpop 블로킹 타임아웃(초). 타임아웃이면 루프를 한 바퀴 더 돌며 종료신호 확인 여지를 둔다.
BRPOP_TIMEOUT = 5

# agent.run 시그니처: payload -> 추천 결과 리스트.
AgentRun = Callable[[RecommendJobPayload], list[RecommendationOut]]
# agent.chat 시그니처: (conversation_id, user_id) -> 어시스턴트 답변 텍스트.
AgentChat = Callable[[int, int], str]


def default_session_factory() -> sessionmaker[Session]:
    """App DB 엔진에 바인딩된 세션 팩토리(프로세스 공용)."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def default_redis() -> Redis:
    """설정의 redis_url 로 동기 redis 클라이언트 생성."""
    import redis  # 지연 import: 테스트는 FakeRedis 주입으로 의존 회피.

    return redis.from_url(get_settings().redis_url, socket_timeout=BRPOP_TIMEOUT + 2)


def default_agent_run() -> AgentRun:
    """실제 에이전트 진입점(과제 구현부). 지연 import 로 stub 미구현과 분리."""
    from worker import agent

    return agent.run


def default_agent_chat() -> AgentChat:
    """대화형 에이전트 진입점(과제 구현부). 지연 import 로 stub 미구현과 분리."""
    from worker import agent

    return agent.chat


def _get_or_create_job(
    session: Session, payload: RecommendJobPayload | ChatJobPayload
) -> AgentJob:
    """job_id 로 AgentJob 을 찾고, 없으면(방어적으로) 생성한다.

    정상 흐름에선 api 가 enqueue 전에 queued 상태로 만들어 두므로 보통 조회된다.
    """
    job = session.execute(
        select(AgentJob).where(AgentJob.job_id == payload.job_id)
    ).scalar_one_or_none()
    if job is None:
        job = AgentJob(
            job_id=payload.job_id,
            user_id=payload.user_id,
            status=JobStatus.queued.value,
        )
        session.add(job)
        session.flush()
    return job


def handle_job(
    payload: RecommendJobPayload,
    *,
    session_factory: Callable[[], Session],
    redis: Any,
    agent_run: AgentRun,
) -> JobStatus:
    """단일 작업 처리: 상태기계 + 영속화. (테스트 주입 가능하도록 분리)

    흐름:
        1. AgentJob.status = running
        2. recos = agent_run(payload)          # <- 과제(에이전트 두뇌)
        3. recos 를 Recommendation 행으로 저장
        4. status = done  / 예외 시 status = failed, error 기록

    Returns:
        최종 JobStatus (done 또는 failed).
    """
    # --- 1. running 으로 전이 (별도 트랜잭션으로 즉시 가시화) ---
    with session_factory() as session:
        job = _get_or_create_job(session, payload)
        job.status = JobStatus.running.value
        job.error = None
        session.commit()

    # --- 2~4. 에이전트 실행 + 결과 저장 ---
    try:
        recos = agent_run(payload)
        with session_factory() as session:
            job = _get_or_create_job(session, payload)
            for reco in recos:
                session.add(
                    Recommendation(
                        job_id=payload.job_id,
                        user_id=payload.user_id,
                        competition_id=reco.competition_id,
                        title=reco.title,
                        reason=reco.reason,
                        score=reco.score,
                    )
                )
            job.status = JobStatus.done.value
            job.error = None
            session.commit()
        return JobStatus.done
    except Exception as exc:  # noqa: BLE001 - 모든 실패를 작업 실패로 노출
        # 실패는 메모리가 아니라 DB 에 기록해야 api 폴링이 볼 수 있다.
        with session_factory() as session:
            job = _get_or_create_job(session, payload)
            job.status = JobStatus.failed.value
            job.error = str(exc)[:1000]
            session.commit()
        # 재시도/백오프 훅 지점:
        #   여기서 redis.lpush(QUEUE_KEY, payload.model_dump_json()) 로 재투입하되
        #   payload 에 attempt 카운트를 두고 지수 백오프(예: 2**attempt 초)로 제한할 것.
        #   (현재는 단순 실패 기록까지만 구현. 무한 재시도 방지를 위해 기본은 재투입 안 함.)
        return JobStatus.failed


def handle_chat_job(
    payload: ChatJobPayload,
    *,
    session_factory: Callable[[], Session],
    agent_chat: AgentChat,
) -> JobStatus:
    """단일 채팅 작업 처리: 상태기계 + 답변 영속화. (handle_job 의 대화판)

    흐름:
        1. AgentJob.status = running
        2. reply = agent_chat(conversation_id, user_id)   # <- 과제(대화형 두뇌)
        3. reply 를 assistant Message 행으로 저장
        4. status = done  / 예외 시 status = failed, error 기록

    계획(plan) 의도일 때 에이전트가 호출하는 ``create_tasks`` 의 Task 저장은
    도구 내부에서 일어난다. 여기(배관)는 대화 답변 메시지 저장만 책임진다.

    Returns:
        최종 JobStatus (done 또는 failed).
    """
    # --- 1. running 으로 전이 (별도 트랜잭션으로 즉시 가시화) ---
    with session_factory() as session:
        job = _get_or_create_job(session, payload)
        job.status = JobStatus.running.value
        job.error = None
        session.commit()

    # --- 2~4. 대화 에이전트 실행 + 답변 저장 ---
    try:
        reply_text = agent_chat(payload.conversation_id, payload.user_id)
        with session_factory() as session:
            job = _get_or_create_job(session, payload)
            session.add(
                Message(
                    conversation_id=payload.conversation_id,
                    role="assistant",
                    content=reply_text,
                )
            )
            job.status = JobStatus.done.value
            job.error = None
            session.commit()
        return JobStatus.done
    except Exception as exc:  # noqa: BLE001 - 모든 실패를 작업 실패로 노출
        with session_factory() as session:
            job = _get_or_create_job(session, payload)
            job.status = JobStatus.failed.value
            job.error = str(exc)[:1000]
            session.commit()
        return JobStatus.failed


def run_loop(
    *,
    redis: Any | None = None,
    session_factory: Callable[[], Session] | None = None,
    agent_run: AgentRun | None = None,
    agent_chat: AgentChat | None = None,
    queue_keys: list[str] | None = None,
    max_iterations: int | None = None,
) -> None:
    """큐 소비 메인 루프(stateless). 추천·채팅 두 큐를 동시에 대기한다.

    Args:
        redis: redis 클라이언트(미지정 시 설정에서 생성). 테스트는 FakeRedis 주입.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.
        agent_run: 추천 진입점(미지정 시 worker.agent.run). 테스트는 가짜 주입.
        agent_chat: 채팅 진입점(미지정 시 worker.agent.chat). 테스트는 가짜 주입.
        queue_keys: 대기할 Redis 리스트 키들(미지정 시 [추천, 채팅]).
        max_iterations: None 이면 무한 루프. 테스트는 정수로 회수를 제한.
    """
    if redis is None:
        redis = default_redis()
    if session_factory is None:
        session_factory = default_session_factory()
    if agent_run is None:
        agent_run = default_agent_run()
    if agent_chat is None:
        agent_chat = default_agent_chat()
    if queue_keys is None:
        queue_keys = [QUEUE_KEY, CHAT_QUEUE_KEY]

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        # redis-py brpop 은 여러 키를 받고 (꺼낸키, 값) 튜플을 돌려준다.
        item = redis.brpop(queue_keys, timeout=BRPOP_TIMEOUT)
        if not item:
            continue  # 타임아웃 — 다음 바퀴.
        key, raw = item
        key_str = key.decode() if isinstance(key, bytes) else key
        # 어느 큐에서 나왔는지로 디스패치.
        if key_str == CHAT_QUEUE_KEY:
            handle_chat_job(
                ChatJobPayload.model_validate_json(raw),
                session_factory=session_factory,
                agent_chat=agent_chat,
            )
        else:
            handle_job(
                RecommendJobPayload.model_validate_json(raw),
                session_factory=session_factory,
                redis=redis,
                agent_run=agent_run,
            )


def main() -> None:  # pragma: no cover - 컨테이너 엔트리포인트
    """컨테이너 CMD 진입점: 기본 의존성으로 무한 루프 기동."""
    run_loop()


if __name__ == "__main__":  # pragma: no cover
    main()
