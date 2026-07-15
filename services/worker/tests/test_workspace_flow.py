"""워크스페이스 생성 트리거·관리 계약 테스트.

핵심 회귀 지점: "1번으로 할게" 같은 선택 발화가 study 로 새지 않고
워크스페이스 생성 제안 → 수락 → 실제 생성(공모전 연결)으로 이어지는지,
그리고 "어떤 워크스페이스야?" 현황 조회가 동작하는지.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from worker import agent


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for model in (User, Conversation, Message, Workspace, WorkspaceMember, Task):
        model.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def conv_with_recommend(session_factory: sessionmaker[Session]) -> tuple[int, int]:
    """추천 목록(role="recommend")이 저장된 대화를 만든다. (user_id, conversation_id)"""
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="A", interests=[], skills=[])
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.flush()
        session.add(
            Message(
                conversation_id=conv.id,
                role="recommend",
                content=json.dumps(
                    [
                        {"ordinal": 1, "id": 11, "title": "브랜드 인사이트 공모전"},
                        {"ordinal": 2, "id": 22, "title": "빅데이터 아이디어톤"},
                    ],
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()
        return user.id, conv.id


def test_keyword_fallback_classifies_select_and_wsinfo():
    assert agent._classify_intent_by_keyword("1번으로 할게")["intent"] == "select"
    assert agent._classify_intent_by_keyword("첫 번째 걸로 하자")["intent"] == "select"
    assert (
        agent._classify_intent_by_keyword("지금 어떤 워크스페이스야?")["intent"]
        == "wsinfo"
    )
    # 워크스페이스 생성 요청은 여전히 workspace 가 먼저 잡는다.
    assert (
        agent._classify_intent_by_keyword("1번으로 워크스페이스 만들어줘")["intent"]
        == "workspace"
    )


def test_select_offers_workspace_creation(session_factory, conv_with_recommend):
    _, conv_id = conv_with_recommend
    reply = agent._handle_select(conv_id, "1번으로 할게", session_factory=session_factory)
    assert "브랜드 인사이트 공모전" in reply
    assert "워크스페이스를 만들까요" in reply  # _OFFER_MARKERS 와 짝


def test_select_out_of_range_asks_again(session_factory, conv_with_recommend):
    _, conv_id = conv_with_recommend
    reply = agent._handle_select(conv_id, "5번으로 할게", session_factory=session_factory)
    assert "다시" in reply


def test_select_without_list_falls_back(session_factory):
    with session_factory() as session:
        user = User(email="b@contest-helper.io", name="B", interests=[], skills=[])
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.commit()
        conv_id = conv.id
    assert agent._handle_select(conv_id, "이걸로 진행하자", session_factory=session_factory) is None


def test_accepting_offer_creates_workspace_linked_to_selection(
    session_factory, conv_with_recommend
):
    """"1번으로 할게" → 제안 → "응" 수락이 실제 워크스페이스 생성(공모전 연결)으로 이어진다."""
    user_id, conv_id = conv_with_recommend
    with session_factory() as session:
        session.add_all(
            [
                Message(conversation_id=conv_id, role="user", content="1번으로 할게"),
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content="'브랜드 인사이트 공모전'로 정하셨네요, 좋은 선택이에요. "
                    "팀원들과 준비를 시작하도록 이 공모전으로 워크스페이스를 만들까요?",
                ),
                Message(conversation_id=conv_id, role="user", content="응"),
            ]
        )
        session.commit()

    reply = agent.chat(conv_id, user_id, session_factory=session_factory)

    with session_factory() as session:
        ws = session.execute(select(Workspace)).scalars().first()
        conv = session.get(Conversation, conv_id)
    assert ws is not None
    assert ws.contest_id == 11  # 수락 메시지("응")가 아니라 직전 선택 발화에서 특정
    assert ws.name == "브랜드 인사이트 공모전"
    assert conv.workspace_id == ws.id
    assert "워크스페이스" in reply


def test_select_by_name_with_particle_matches(session_factory, conv_with_recommend):
    """조사가 붙은 이름 선택("~활용대회로 하자")도 부분문자열 매칭으로 특정된다."""
    _, conv_id = conv_with_recommend
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conv_id,
                role="recommend",
                content=json.dumps(
                    [
                        {"ordinal": 1, "id": 31, "title": "국가데이터 활용대회"},
                        {"ordinal": 2, "id": 32, "title": "브랜드 인사이트 공모전"},
                    ],
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()
    assert (
        agent._classify_intent_by_keyword("그럼 국가데이터 활용대회로 하자")["intent"]
        == "select"
    )
    reply = agent._handle_select(
        conv_id, "그럼 국가데이터 활용대회로 하자", session_factory=session_factory
    )
    assert "국가데이터 활용대회" in reply and "워크스페이스를 만들까요" in reply


def test_create_workspace_uses_recent_selection_message(
    session_factory, conv_with_recommend
):
    """선택("~로 하자")과 생성("워크스페이스 만들어 줘")이 다른 턴이어도 공모전이 연결된다.

    스크린샷 회귀 케이스: 예전엔 생성 메시지만 봐서 '새 워크스페이스'가 됐다.
    """
    user_id, conv_id = conv_with_recommend
    with session_factory() as session:
        session.add_all(
            [
                Message(conversation_id=conv_id, role="user", content="그럼 브랜드 인사이트 공모전으로 하자"),
                Message(conversation_id=conv_id, role="assistant", content="..."),
                Message(conversation_id=conv_id, role="user", content="워크스페이스 만들어 줘"),
            ]
        )
        session.commit()

    reply = agent._handle_create_workspace(
        conv_id, user_id, "워크스페이스 만들어 줘", session_factory=session_factory
    )

    with session_factory() as session:
        ws = session.execute(select(Workspace)).scalars().first()
    assert ws is not None
    assert ws.contest_id == 11
    assert ws.name == "브랜드 인사이트 공모전"
    assert "브랜드 인사이트 공모전" in reply


def test_context_scan_ignores_recommend_requests(session_factory, conv_with_recommend):
    """"공모전 추천해줘" 같은 과거 검색 요청의 단어 겹침에는 낚이지 않는다."""
    user_id, conv_id = conv_with_recommend
    with session_factory() as session:
        session.add_all(
            [
                Message(conversation_id=conv_id, role="user", content="공모전 추천해줘"),
                Message(conversation_id=conv_id, role="assistant", content="..."),
                Message(conversation_id=conv_id, role="user", content="워크스페이스 만들어 줘"),
            ]
        )
        session.commit()

    agent._handle_create_workspace(
        conv_id, user_id, "워크스페이스 만들어 줘", session_factory=session_factory
    )

    with session_factory() as session:
        ws = session.execute(select(Workspace)).scalars().first()
    assert ws is not None
    assert ws.contest_id is None  # 무리하게 추측해 연결하지 않는다
    assert ws.name == "새 워크스페이스"


def test_select_confirms_topic_when_topic_is_latest(session_factory, conv_with_recommend):
    """주제 후보가 추천 목록보다 최신이면 "1번으로 할게"는 주제 확정으로 해석한다."""
    _, conv_id = conv_with_recommend
    with session_factory() as session:
        session.add(
            Message(conversation_id=conv_id, role="topic", content="주제 후보 ①: A\n주제 후보 ②: B")
        )
        session.commit()
    reply = agent._handle_select(conv_id, "1번으로 할게", session_factory=session_factory)
    assert "계획을 짜 볼까요" in reply  # _OFFER_MARKERS 와 짝


def test_workspace_info_summarizes_state(session_factory, conv_with_recommend):
    user_id, conv_id = conv_with_recommend
    with session_factory() as session:
        ws = Workspace(name="브랜드 준비팀", owner_id=user_id)
        session.add(ws)
        session.flush()
        session.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role="owner"))
        session.add_all(
            [
                Task(workspace_id=ws.id, title="요강 정리", status="done", week_no=1),
                Task(workspace_id=ws.id, title="데이터 수집", status="todo", week_no=1),
            ]
        )
        conv = session.get(Conversation, conv_id)
        conv.workspace_id = ws.id
        session.commit()

    reply = agent._handle_workspace_info(conv_id, {}, session_factory=session_factory)
    assert "브랜드 준비팀" in reply
    assert "1/2개 완료" in reply


def test_workspace_info_without_workspace_asks(session_factory, conv_with_recommend):
    _, conv_id = conv_with_recommend
    reply = agent._handle_workspace_info(conv_id, {}, session_factory=session_factory)
    assert "없어요" in reply and "?" in reply