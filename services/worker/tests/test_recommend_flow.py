"""_handle_recommend / _extract_contest 계약 테스트.

핵심 회귀 지점: 추천 응답에 DB 고유번호(PK)가 절대 노출되지 않고 순번만 보이는지,
그리고 그 순번이 이후 "1번으로 워크스페이스 만들어줘"/"OO공모전으로 만들어줘" 요청에서
올바른 id로 다시 풀리는지(``_extract_contest``). 시맨틱 검색·Gemini 는 무겁고 외부
의존적이라 ``agent`` 모듈에 바인딩된 이름을 monkeypatch 로 가짜 구현으로 바꿔 치환한다.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contest_helper_core.models import Conversation, Message, User
from contest_helper_core.schemas import MessageOut
from worker import agent
from worker.mcp_tools.competitions import CompetitionDetailOut, CompetitionSearchFilters


class _CannedLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for table in (User, Conversation, Message):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def conversation_id(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="A")
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.commit()
        return conv.id


def _detail(id: int, title: str) -> CompetitionDetailOut:
    return CompetitionDetailOut(id=id, title=title, deadline=date(2026, 5, 31))


def test_handle_recommend_never_leaks_pk_and_saves_recommend_list(
    monkeypatch, session_factory, conversation_id
):
    monkeypatch.setattr(agent, "GeminiClient", lambda: _CannedLLM("추천 답변입니다."))
    monkeypatch.setattr(agent, "_extract_search_keyword", lambda history: "마케팅")
    monkeypatch.setattr(
        agent, "_extract_search_filters", lambda history, **kw: CompetitionSearchFilters()
    )
    monkeypatch.setattr(
        agent, "semantic_search", lambda keyword, k: [_detail(101, "공모전A"), _detail(202, "공모전B")]
    )
    monkeypatch.setattr(agent, "get_competition_detail", lambda cid: _detail(cid, f"공모전{cid}"))

    history = [MessageOut(role="user", content="마케팅 관련 팀 공모전 찾아줘")]
    reply = agent._handle_recommend(
        history, "마케팅 관련 팀 공모전 찾아줘", conversation_id, session_factory=session_factory
    )

    assert reply == "추천 답변입니다."

    with session_factory() as session:
        rows = session.query(Message).filter_by(
            conversation_id=conversation_id, role="recommend"
        ).all()
        assert len(rows) == 1
        saved = json.loads(rows[0].content)
        # 상세 조회(get_competition_detail) 결과가 우선 저장되고, 카드용 필드(마감)도 실린다.
        assert saved == [
            {"ordinal": 1, "id": 101, "title": "공모전101", "deadline": "2026-05-31"},
            {"ordinal": 2, "id": 202, "title": "공모전202", "deadline": "2026-05-31"},
        ]


def test_extract_contest_resolves_ordinal(session_factory, conversation_id):
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps(
                    [
                        {"ordinal": 1, "id": 11, "title": "공모전A"},
                        {"ordinal": 2, "id": 22, "title": "공모전B"},
                    ]
                ),
            )
        )
        session.commit()

    contest_id, title, ambiguous = agent._extract_contest(
        "2번으로 워크스페이스 만들어줘", conversation_id, session_factory=session_factory
    )

    assert (contest_id, title, ambiguous) == (22, "공모전B", False)


def test_extract_contest_resolves_by_name(session_factory, conversation_id):
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps(
                    [
                        {"ordinal": 1, "id": 11, "title": "AI 해커톤"},
                        {"ordinal": 2, "id": 22, "title": "디자인 공모전"},
                    ]
                ),
            )
        )
        session.commit()

    contest_id, title, ambiguous = agent._extract_contest(
        "디자인 공모전으로 만들어줘", conversation_id, session_factory=session_factory
    )

    assert (contest_id, title, ambiguous) == (22, "디자인 공모전", False)


def test_extract_contest_flags_out_of_range_ordinal_as_ambiguous(session_factory, conversation_id):
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps([{"ordinal": 1, "id": 11, "title": "공모전A"}]),
            )
        )
        session.commit()

    contest_id, title, ambiguous = agent._extract_contest(
        "5번으로 워크스페이스 만들어줘", conversation_id, session_factory=session_factory
    )

    assert (contest_id, title, ambiguous) == (None, None, True)


def test_extract_contest_no_recommend_list_returns_unlinked(session_factory, conversation_id):
    contest_id, title, ambiguous = agent._extract_contest(
        "그냥 워크스페이스 만들어줘", conversation_id, session_factory=session_factory
    )

    assert (contest_id, title, ambiguous) == (None, None, False)


def test_extract_contest_no_match_returns_unlinked_not_ambiguous(session_factory, conversation_id):
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="recommend",
                content=json.dumps([{"ordinal": 1, "id": 11, "title": "AI 해커톤"}]),
            )
        )
        session.commit()

    contest_id, title, ambiguous = agent._extract_contest(
        "그냥 워크스페이스 만들어줘", conversation_id, session_factory=session_factory
    )

    assert (contest_id, title, ambiguous) == (None, None, False)
