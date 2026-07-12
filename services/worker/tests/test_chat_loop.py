"""채팅 배관(handle_chat_job + run_loop 디스패치) 테스트 — 통과해야 한다.

가짜 ``agent_chat`` 을 주입해 대화형 두뇌 없이도 배관만 검증한다.
hermetic: SQLite 로 필요한 테이블(User/AgentJob/Conversation/Message)만 만든다.
"""

from __future__ import annotations

import pytest
from contest_helper_core.models import AgentJob, Conversation, Message, User
from contest_helper_core.schemas import ChatJobPayload, JobStatus
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from worker import main
from worker.main import CHAT_QUEUE_KEY, handle_chat_job, run_loop


@pytest.fixture()
def chat_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # pgvector 컬럼이 있는 embeddings 는 제외, 채팅에 필요한 테이블만.
    for table in (User, AgentJob, Conversation, Message):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def chat_seed(chat_session_factory: sessionmaker[Session]) -> tuple[int, int]:
    """사용자 1명 + 대화 1개를 만들고 (user_id, conversation_id) 반환."""
    with chat_session_factory() as session:
        user = User(email="chatter@contest-helper.io", name="Chatter")
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.commit()
        return user.id, conv.id


def _make_job(session_factory: sessionmaker[Session], user_id: int, job_id: str) -> None:
    with session_factory() as session:
        session.add(
            AgentJob(job_id=job_id, user_id=user_id, status=JobStatus.queued.value)
        )
        session.commit()


def _canned_chat(reply: str):
    def _chat(conversation_id: int, user_id: int) -> str:  # noqa: ARG001
        return reply

    return _chat


def test_handle_chat_job_writes_assistant_message_and_marks_done(
    chat_session_factory, chat_seed
):
    user_id, conv_id = chat_seed
    _make_job(chat_session_factory, user_id, "chat-1")
    payload = ChatJobPayload(job_id="chat-1", user_id=user_id, conversation_id=conv_id)

    status = handle_chat_job(
        payload,
        session_factory=chat_session_factory,
        agent_chat=_canned_chat("안녕하세요"),
    )

    assert status is JobStatus.done
    with chat_session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "chat-1")
        ).scalar_one()
        assert job.status == JobStatus.done.value
        assert job.error is None

        msgs = (
            session.execute(
                select(Message).where(Message.conversation_id == conv_id)
            )
            .scalars()
            .all()
        )
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert msgs[0].content == "안녕하세요"


def test_handle_chat_job_marks_failed_on_agent_exception(
    chat_session_factory, chat_seed
):
    user_id, conv_id = chat_seed
    _make_job(chat_session_factory, user_id, "chat-2")

    def _boom(conversation_id: int, user_id: int) -> str:  # noqa: ARG001
        raise RuntimeError("LLM down")

    payload = ChatJobPayload(job_id="chat-2", user_id=user_id, conversation_id=conv_id)

    status = handle_chat_job(
        payload, session_factory=chat_session_factory, agent_chat=_boom
    )

    assert status is JobStatus.failed
    with chat_session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "chat-2")
        ).scalar_one()
        assert job.status == JobStatus.failed.value
        assert "LLM down" in (job.error or "")
        msgs = (
            session.execute(
                select(Message).where(Message.conversation_id == conv_id)
            )
            .scalars()
            .all()
        )
        assert msgs == []


def test_run_loop_dispatches_chat_payload(chat_session_factory, chat_seed, fake_redis):
    user_id, conv_id = chat_seed
    _make_job(chat_session_factory, user_id, "chat-3")
    payload = ChatJobPayload(job_id="chat-3", user_id=user_id, conversation_id=conv_id)
    fake_redis.lpush(CHAT_QUEUE_KEY, payload.model_dump_json())

    run_loop(
        redis=fake_redis,
        session_factory=chat_session_factory,
        agent_run=lambda p: [],
        agent_chat=_canned_chat("도와드릴게요"),
        max_iterations=1,
    )

    with chat_session_factory() as session:
        job = session.execute(
            select(AgentJob).where(AgentJob.job_id == "chat-3")
        ).scalar_one()
        assert job.status == JobStatus.done.value
        msgs = (
            session.execute(
                select(Message).where(Message.conversation_id == conv_id)
            )
            .scalars()
            .all()
        )
        assert [m.content for m in msgs] == ["도와드릴게요"]


def test_load_history_returns_messages_in_order(chat_session_factory, chat_seed):
    from worker import agent

    user_id, conv_id = chat_seed
    with chat_session_factory() as session:
        session.add_all(
            [
                Message(conversation_id=conv_id, role="user", content="안녕"),
                Message(conversation_id=conv_id, role="assistant", content="반가워요"),
            ]
        )
        session.commit()

    history = agent.load_history(conv_id, session_factory=chat_session_factory)
    assert [(m.role, m.content) for m in history] == [
        ("user", "안녕"),
        ("assistant", "반가워요"),
    ]


def test_chat_queue_key_matches_contract():
    assert main.CHAT_QUEUE_KEY == "contest-helper:jobs:chat"
