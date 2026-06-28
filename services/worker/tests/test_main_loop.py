"""배관(큐 루프 + 상태기계 + 영속화) 테스트 — 통과해야 한다.

가짜 ``agent_run`` 을 주입해 에이전트 두뇌 없이도 배관만 검증한다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.models import AgentJob, Recommendation
from contest_helper_core.schemas import JobStatus, RecommendationOut, RecommendJobPayload
from worker import main
from worker.main import QUEUE_KEY, handle_job, run_loop


def _make_job(session_factory: sessionmaker[Session], user_id: int, job_id: str) -> None:
    with session_factory() as session:
        session.add(AgentJob(job_id=job_id, user_id=user_id, status=JobStatus.queued.value))
        session.commit()


def _canned_agent(recos: list[RecommendationOut]):
    def _run(payload: RecommendJobPayload) -> list[RecommendationOut]:
        return recos

    return _run


def test_handle_job_transitions_queued_to_done_and_persists(session_factory, fake_redis, seed_user):
    _make_job(session_factory, seed_user, "job-1")
    recos = [
        RecommendationOut(competition_id=10, title="해커톤", reason="AI 관심사와 일치", score=0.9),
        RecommendationOut(competition_id=11, title="공모전 B", reason="python 스킬 활용"),
    ]
    payload = RecommendJobPayload(job_id="job-1", user_id=seed_user, limit=5)

    status = handle_job(
        payload,
        session_factory=session_factory,
        redis=fake_redis,
        agent_run=_canned_agent(recos),
    )

    assert status is JobStatus.done
    with session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "job-1")
        ).scalar_one()
        assert job.status == JobStatus.done.value
        assert job.error is None

        rows = session.execute(
            select(Recommendation).where(Recommendation.job_id == "job-1")
        ).scalars().all()
        assert len(rows) == 2
        assert {r.competition_id for r in rows} == {10, 11}
        assert all(r.user_id == seed_user for r in rows)
        first = next(r for r in rows if r.competition_id == 10)
        assert first.title == "해커톤"
        assert first.score == 0.9


def test_handle_job_marks_failed_on_agent_exception(session_factory, fake_redis, seed_user):
    _make_job(session_factory, seed_user, "job-2")

    def _boom(payload: RecommendJobPayload) -> list[RecommendationOut]:
        raise RuntimeError("LLM down")

    payload = RecommendJobPayload(job_id="job-2", user_id=seed_user, limit=5)

    status = handle_job(
        payload,
        session_factory=session_factory,
        redis=fake_redis,
        agent_run=_boom,
    )

    assert status is JobStatus.failed
    with session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "job-2")
        ).scalar_one()
        assert job.status == JobStatus.failed.value
        assert "LLM down" in (job.error or "")
        rows = session.execute(
            select(Recommendation).where(Recommendation.job_id == "job-2")
        ).scalars().all()
        assert rows == []


def test_handle_job_creates_missing_agent_job_defensively(session_factory, fake_redis, seed_user):
    # api 가 row 를 안 만든 비정상 케이스에서도 배관이 죽지 않아야 한다.
    payload = RecommendJobPayload(job_id="job-3", user_id=seed_user, limit=5)

    status = handle_job(
        payload,
        session_factory=session_factory,
        redis=fake_redis,
        agent_run=_canned_agent([]),
    )

    assert status is JobStatus.done
    with session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "job-3")
        ).scalar_one()
        assert job.status == JobStatus.done.value


def test_run_loop_consumes_one_payload_from_queue(session_factory, fake_redis, seed_user):
    _make_job(session_factory, seed_user, "job-4")
    payload = RecommendJobPayload(job_id="job-4", user_id=seed_user, limit=5)
    fake_redis.lpush(QUEUE_KEY, payload.model_dump_json())

    recos = [RecommendationOut(competition_id=42, title="C", reason="fit")]
    run_loop(
        redis=fake_redis,
        session_factory=session_factory,
        agent_run=_canned_agent(recos),
        max_iterations=1,
    )

    with session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "job-4")
        ).scalar_one()
        assert job.status == JobStatus.done.value
        rows = session.execute(
            select(Recommendation).where(Recommendation.job_id == "job-4")
        ).scalars().all()
        assert [r.competition_id for r in rows] == [42]


def test_run_loop_handles_empty_queue_without_error(session_factory, fake_redis):
    # brpop 타임아웃(None)일 때 조용히 다음 바퀴로 넘어가야 한다.
    run_loop(
        redis=fake_redis,
        session_factory=session_factory,
        agent_run=_canned_agent([]),
        max_iterations=3,
    )


def test_queue_key_matches_contract():
    # api 와 worker 가 같은 키를 써야 작업이 흐른다.
    assert main.QUEUE_KEY == "contest-helper:jobs:recommend"
