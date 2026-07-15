"""competition_agent._handle_study 계약 테스트.

실제 Gemini 없이, generate_with_tools 를 흉내내는 가짜 LLM으로 "모델이 도구를
호출하기로 했다"는 상황을 재현한다. 어떤 도구를 어떤 인자로 부를지는 테스트가
정하고(가짜 LLM의 역할), 그 다음 우리 코드(도구 wrapper)가 올바르게 동작하는지
검증한다.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contest_helper_core.models import (
    Conversation,
    Message,
    Recommendation,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import MessageOut
from worker import competition_agent
from worker.mcp_tools.competitions import CompetitionDetailOut


class _FakeToolLLM:
    """generate_with_tools 흉내: 지정된 이름의 도구를 실제로 호출해 그 결과를 돌려준다."""

    def __init__(self, *, call: str | None = None, kwargs: dict | None = None, plain: str = "일반 답변"):
        self.call = call
        self.kwargs = kwargs or {}
        self.plain = plain
        self.seen_tool_names: list[str] = []

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self.plain

    def generate_with_tools(self, prompt: str, tools: list) -> str:  # noqa: ARG002
        self.seen_tool_names = [fn.__name__ for fn in tools]
        if self.call is None:
            return self.plain
        for fn in tools:
            if fn.__name__ == self.call:
                return fn(**self.kwargs)
        raise AssertionError(f"tool {self.call!r} not offered; got {self.seen_tool_names}")


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for table in (User, Workspace, WorkspaceMember, Conversation, Message, Recommendation):
        table.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def conversation_with_workspace(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="A", interests=["마케팅"], skills=["기획"])
        session.add(user)
        session.flush()
        ws = Workspace(name="AI 해커톤", owner_id=user.id, contest_id=1)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        conv = Conversation(user_id=user.id, workspace_id=ws.id)
        session.add(conv)
        session.commit()
        return conv.id


@pytest.fixture()
def two_members_conversations(session_factory: sessionmaker[Session]) -> tuple[int, int, int]:
    """같은 워크스페이스, 서로 다른 두 멤버(각자 다른 Conversation)를 만든다.

    반환: (member_a의 conversation_id, member_b의 conversation_id, workspace_id).
    """
    with session_factory() as session:
        owner = User(email="owner@contest-helper.io", name="팀장")
        member = User(email="member@contest-helper.io", name="팀원")
        session.add_all([owner, member])
        session.flush()
        ws = Workspace(name="AI 해커톤", owner_id=owner.id, contest_id=1)
        session.add(ws)
        session.flush()
        session.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
            ]
        )
        conv_a = Conversation(user_id=owner.id, workspace_id=ws.id)
        conv_b = Conversation(user_id=member.id, workspace_id=ws.id)
        session.add_all([conv_a, conv_b])
        session.commit()
        return conv_a.id, conv_b.id, ws.id


@pytest.fixture()
def conversation_without_workspace(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        user = User(email="b@contest-helper.io", name="B")
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id, workspace_id=None)
        session.add(conv)
        session.commit()
        return conv.id


def _detail(id: int, title: str) -> CompetitionDetailOut:
    return CompetitionDetailOut(
        id=id, title=title, deadline=date(2026, 5, 31),
        total_prize_amount=5_000_000, category=["마케팅"], evaluation_criteria=["창의성"],
    )


def test_answer_returns_plain_text_when_no_tool_needed(session_factory, conversation_without_workspace):
    llm = _FakeToolLLM(plain="포트폴리오는 이렇게 준비하면 돼요.")

    result = competition_agent._handle_study(
        "포트폴리오 어떻게 준비해?", [], conversation_without_workspace, {},
        llm=llm, session_factory=session_factory,
    )

    assert result == "포트폴리오는 이렇게 준비하면 돼요."


def test_answer_returns_guidance_for_empty_message(session_factory, conversation_without_workspace):
    result = competition_agent._handle_study(
        "", [], conversation_without_workspace, {}, llm=_FakeToolLLM(), session_factory=session_factory,
    )
    assert "추천" in result or "계획" in result


def test_answer_offers_compare_tool_and_executes_it(session_factory, conversation_without_workspace):
    tools = {"compare_competitions": lambda ids: [_detail(i, f"공모전{i}") for i in ids]}
    llm = _FakeToolLLM(call="compare_competitions", kwargs={"competition_ids": [1, 2]})

    history = [MessageOut(role="assistant", content="- [1] 공모전1\n- [2] 공모전2")]
    result = competition_agent._handle_study(
        "이 두 개 비교해줘", history, conversation_without_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    assert "공모전1" in result and "공모전2" in result


def test_answer_does_not_offer_team_fit_tool_without_workspace(session_factory, conversation_without_workspace):
    llm = _FakeToolLLM(plain="무시됨")

    competition_agent._handle_study(
        "우리 팀이 잘할 수 있을까?", [], conversation_without_workspace, {},
        llm=llm, session_factory=session_factory,
    )

    assert "check_team_fit" not in llm.seen_tool_names
    assert "list_saved_competitions" not in llm.seen_tool_names
    assert "compare_competitions" in llm.seen_tool_names


def test_answer_offers_team_fit_tool_with_workspace(session_factory, conversation_with_workspace):
    tools = {"get_competition_detail": lambda cid: _detail(cid, "AI 해커톤")}
    llm = _FakeToolLLM(call="check_team_fit")

    result = competition_agent._handle_study(
        "우리 팀이 잘할 수 있을까?", [], conversation_with_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    assert isinstance(result, str) and result


def test_list_saved_competitions_visible_to_every_member(
    session_factory, two_members_conversations
):
    """한 멤버가 저장한 공모전이 다른 멤버의 대화에서도 조회돼야 한다(워크스페이스 단위 공유)."""
    conv_a, conv_b, workspace_id = two_members_conversations
    with session_factory() as session:
        session.add(
            Recommendation(
                job_id="job-1",
                user_id=1,
                workspace_id=workspace_id,
                competition_id=1,
                title="AI 해커톤",
                reason="관심 분야와 일치",
            )
        )
        session.commit()

    llm = _FakeToolLLM(call="list_saved_competitions")

    result = competition_agent._handle_study(
        "워크스페이스에 등록된 공모전이 뭐야?", [], conv_b, {},
        llm=llm, session_factory=session_factory,
    )

    assert "AI 해커톤" in result


def test_list_saved_competitions_empty_when_nothing_saved(
    session_factory, two_members_conversations
):
    _, conv_b, _ = two_members_conversations
    llm = _FakeToolLLM(call="list_saved_competitions")

    result = competition_agent._handle_study(
        "워크스페이스에 등록된 공모전이 뭐야?", [], conv_b, {},
        llm=llm, session_factory=session_factory,
    )

    assert "없" in result


def test_answer_offers_detail_tool_and_executes_it(session_factory, conversation_without_workspace):
    tools = {"get_competition_detail": lambda cid: _detail(cid, "AI 해커톤")}
    llm = _FakeToolLLM(call="get_competition_detail", kwargs={"competition_id": 12})

    result = competition_agent._handle_study(
        "이거 혼자도 나갈 수 있어?", [], conversation_without_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    assert "AI 해커톤" in result


def test_answer_offers_search_tool_and_persists_recommend_list(
    session_factory, conversation_without_workspace
):
    tools = {
        "search_competitions": lambda keyword=None, limit=5: [
            _detail(1, "공모전A"), _detail(2, "공모전B"),
        ]
    }
    llm = _FakeToolLLM(call="search_competitions", kwargs={"keyword": "마케팅"})

    result = competition_agent._handle_study(
        "마감 촉박한데 다른 거 없어?", [], conversation_without_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    # 사용자에게는 순번만 보이고, DB id(1, 2)는 텍스트에 노출되지 않아야 한다.
    assert "1. 공모전A" in result and "2. 공모전B" in result
    assert "[1]" not in result and "[2]" not in result

    with session_factory() as session:
        rows = session.query(Message).filter_by(
            conversation_id=conversation_without_workspace, role="recommend"
        ).all()
        assert len(rows) == 1
        saved = json.loads(rows[0].content)
        # 마감·카테고리 등 카드용 필드도 함께 저장된다(프론트 추천 카드가 읽는다).
        assert saved == [
            {"ordinal": 1, "id": 1, "title": "공모전A", "deadline": "2026-05-31", "category": ["마케팅"]},
            {"ordinal": 2, "id": 2, "title": "공모전B", "deadline": "2026-05-31", "category": ["마케팅"]},
        ]


def test_answer_offers_web_search_tool(session_factory, conversation_without_workspace):
    class _Result:
        def __init__(self, title, snippet, url):
            self.title, self.snippet, self.url = title, snippet, url

    tools = {"web_search": lambda query, max_results=3: [_Result("작년 수상작", "요약", "http://example.com")]}
    llm = _FakeToolLLM(call="web_search", kwargs={"query": "작년 수상작"})

    result = competition_agent._handle_study(
        "작년 수상작 뭐였어?", [], conversation_without_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    assert "작년 수상작" in result and "example.com" in result


def test_answer_web_search_tool_admits_when_nothing_found(
    session_factory, conversation_without_workspace
):
    tools = {"web_search": lambda query, max_results=3: []}
    llm = _FakeToolLLM(call="web_search", kwargs={"query": "심사위원"})

    result = competition_agent._handle_study(
        "심사위원 누구야?", [], conversation_without_workspace, tools,
        llm=llm, session_factory=session_factory,
    )

    assert "찾지 못했" in result
