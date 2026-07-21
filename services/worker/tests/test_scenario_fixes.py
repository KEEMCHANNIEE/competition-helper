"""S-01(검색)·S-02(적재) 시나리오 케이스 계약 테스트.

conmate_scenarios.md 표의 발화들이 실제로 끊기지 않는지 검증한다:
- "두 번째 걸로 할게" (공백 서수 선택)
- "마감 촉박한데 다른 거 없어?" (준비 기간 되묻기 + 후속 턴 연결)
- "비슷한 다른 것도 보여줘" (직전 추천 제외)
- "이 부분만 저장해줘" (범위 되묻기)
- "지난번에 저장한 거랑 합쳐줘" (병합 미리보기 → 수락 → 교체)
- "저장 말고 OO한테만 공유해줘" (로그 미저장 + 팀원 다이렉트 공유)
- "오늘은 여기까지만 할게" (저장 제안 → "응" → 저장)
- 할 일 완료 오매칭 완화 (겹침 1개는 확인 질문 → "응" → 완료)
"""

from __future__ import annotations

import json

import pytest
from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import MessageOut
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from worker import agent
from worker.mcp_tools import tasks as tasks_tool
from worker.mcp_tools.competitions import CompetitionDetailOut, CompetitionSearchFilters


class _CannedLLM:
    """고정 응답 LLM. 마지막 prompt 를 기록해 프롬프트 계약도 검증할 수 있게 한다."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._text


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for model in (User, Conversation, Message, Workspace, WorkspaceMember, Task):
        model.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def workspace_conv(session_factory: sessionmaker[Session]) -> dict:
    """워크스페이스에 연결된 대화 + 팀원 2명(작성자/유진)을 만든다."""
    with session_factory() as session:
        owner = User(email="a@contest-helper.io", name="동영 (팀장)", interests=[], skills=[])
        mate = User(email="b@contest-helper.io", name="유진", interests=[], skills=[])
        session.add_all([owner, mate])
        session.flush()
        ws = Workspace(name="테스트 워크스페이스", owner_id=owner.id)
        session.add(ws)
        session.flush()
        session.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=mate.id, role="데이터 분석"),
            ]
        )
        conv = Conversation(user_id=owner.id, workspace_id=ws.id)
        session.add(conv)
        session.commit()
        return {
            "owner_id": owner.id,
            "mate_id": mate.id,
            "workspace_id": ws.id,
            "conversation_id": conv.id,
        }


def _add_messages(session_factory, conversation_id: int, *pairs: tuple[str, str]) -> None:
    with session_factory() as session:
        for role, content in pairs:
            session.add(
                Message(conversation_id=conversation_id, role=role, content=content)
            )
        session.commit()


# --------------------------------------------------------------------------- #
# S-01 검색
# --------------------------------------------------------------------------- #


def test_extract_contest_resolves_spaced_ordinal(session_factory):
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="A")
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
                        {"ordinal": 1, "id": 11, "title": "AI 해커톤"},
                        {"ordinal": 2, "id": 22, "title": "디자인 공모전"},
                        {"ordinal": 3, "id": 33, "title": "마케팅 공모전"},
                    ]
                ),
            )
        )
        session.commit()
        conv_id = conv.id

    result_second = agent._extract_contest("두 번째 걸로 할게", conv_id, session_factory=session_factory)
    assert result_second[:2] == (22, "디자인 공모전")

    result_third = agent._extract_contest("세 번째 거로 하자", conv_id, session_factory=session_factory)
    assert result_third[:2] == (33, "마케팅 공모전")


def test_recommend_asks_prep_period_before_researching(session_factory, workspace_conv):
    """"마감 촉박한데 다른 거 없어?"는 검색 대신 준비 기간을 되묻는다."""
    history = [MessageOut(role="user", content="마감이 너무 촉박한데 다른 거 없어?")]
    reply = agent._handle_recommend(
        history, "마감이 너무 촉박한데 다른 거 없어?", workspace_conv["conversation_id"],
        session_factory=session_factory,
    )
    assert "준비 기간이 얼마나 필요" in reply


def test_prep_period_answer_continues_recommend_flow():
    history = [
        MessageOut(role="assistant", content="준비 기간이 얼마나 필요해요? '3주는 필요해'처럼 알려주세요."),
        MessageOut(role="user", content="3주 정도는 필요해"),
    ]
    assert agent._continuation_intent(history, "3주 정도는 필요해") == "recommend"


def test_range_answer_continues_log_flow():
    history = [
        MessageOut(role="assistant", content=agent._RANGE_QUESTION),
        MessageOut(role="user", content="데이터 수집 얘기부터 SNS 분석까지"),
    ]
    assert agent._continuation_intent(history, "데이터 수집 얘기부터 SNS 분석까지") == "log"


def test_recommend_excludes_previously_shown(monkeypatch, session_factory, workspace_conv):
    """"비슷한 다른 것도 보여줘"는 직전 추천에 나온 공모전을 다시 보여주지 않는다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("recommend", json.dumps([{"ordinal": 1, "id": 11, "title": "AI 해커톤"}])),
    )

    def _detail(cid: int) -> CompetitionDetailOut:
        return CompetitionDetailOut(id=cid, title=f"공모전{cid}")

    monkeypatch.setattr(agent, "GeminiClient", lambda: _CannedLLM("추천 답변"))
    monkeypatch.setattr(
        agent, "extract_keyword_and_filters",
        lambda user_msgs, **kw: ("마케팅", CompetitionSearchFilters()),
    )
    monkeypatch.setattr(
        agent, "semantic_search", lambda keyword, k: [_detail(11), _detail(33)]
    )
    monkeypatch.setattr(agent, "get_competition_detail", _detail)

    history = [MessageOut(role="user", content="비슷한 다른 것도 보여줘")]
    agent._handle_recommend(
        history, "비슷한 다른 것도 보여줘", conv_id, session_factory=session_factory
    )

    with session_factory() as session:
        rows = (
            session.execute(
                select(Message)
                .where(Message.conversation_id == conv_id, Message.role == "recommend")
                .order_by(Message.id.desc())
            )
            .scalars()
            .all()
        )
        latest = json.loads(rows[0].content)
        assert [e["id"] for e in latest] == [33]  # 직전에 보여준 11은 제외


def test_recommend_prize_context_uses_previous_list(monkeypatch, session_factory, workspace_conv):
    """"상금 더 큰 거"의 기준값으로 직전 목록의 1등 상금 최댓값이 추출기에 전달된다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("recommend", json.dumps([
            {"ordinal": 1, "id": 11, "title": "A", "first_prize_amount": 3_000_000},
            {"ordinal": 2, "id": 22, "title": "B", "first_prize_amount": 5_000_000},
        ])),
    )
    captured: dict = {}

    def _fake_extract(user_msgs, **kw):
        captured.update(kw)
        return None, CompetitionSearchFilters()

    monkeypatch.setattr(agent, "extract_keyword_and_filters", _fake_extract)
    monkeypatch.setattr(agent, "GeminiClient", lambda: _CannedLLM("조건을 알려주세요"))

    history = [MessageOut(role="user", content="상금이 더 큰 거 없어?")]
    agent._handle_recommend(
        history, "상금이 더 큰 거 없어?", conv_id, session_factory=session_factory
    )
    assert captured["max_known_prize"] == 5_000_000


@pytest.fixture()
def conv_after_detail_chat(session_factory: sessionmaker[Session]) -> dict:
    """추천 목록 + 특정 공모전에 대한 문답이 끝난 대화. (user_id, conversation_id)"""
    with session_factory() as session:
        user = User(email="a@contest-helper.io", name="동영", interests=[], skills=[])
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.flush()
        session.add_all(
            [
                Message(
                    conversation_id=conv.id,
                    role="recommend",
                    content=json.dumps(
                        [
                            {"ordinal": 1, "id": 11, "title": "국가데이터 활용대회"},
                            {"ordinal": 2, "id": 22, "title": "디자인 공모전"},
                        ],
                        ensure_ascii=False,
                    ),
                ),
                Message(
                    conversation_id=conv.id,
                    role="user",
                    content="국가데이터 활용대회의 공식 홈페이지는 어디야?",
                ),
                Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content="해당 공모전의 공식 홈페이지는 국가데이터처 누리집입니다.",
                ),
            ]
        )
        session.commit()
        return {"user_id": user.id, "conversation_id": conv.id}


def test_workspace_create_resolves_demonstrative_from_context(
    session_factory, conv_after_detail_chat
):
    """"이거 준비하려고 하는데 워크스페이스 만들어줘"의 '이거'가 직전에 얘기한 공모전으로 풀린다."""
    reply = agent._handle_create_workspace(
        conv_after_detail_chat["conversation_id"], conv_after_detail_chat["user_id"],
        "아니 이거 준비하려고 하는데 워크스페이스 만들어ㅜ저",
        session_factory=session_factory, llm=_CannedLLM("11"),
    )
    assert "국가데이터 활용대회" in reply
    with session_factory() as session:
        ws = session.query(Workspace).first()
        assert ws.contest_id == 11
        assert ws.name == "국가데이터 활용대회"


def test_workspace_create_ambiguous_reference_asks_again(
    session_factory, conv_after_detail_chat
):
    reply = agent._handle_create_workspace(
        conv_after_detail_chat["conversation_id"], conv_after_detail_chat["user_id"],
        "이거로 워크스페이스 만들어줘",
        session_factory=session_factory, llm=_CannedLLM("모호"),
    )
    assert "다시 말씀해" in reply
    with session_factory() as session:
        assert session.query(Workspace).count() == 0


def test_llm_resolver_rejects_hallucinated_id(session_factory, conv_after_detail_chat):
    """LLM 이 목록에 없는 id 를 답하면 버리고 미연결로 처리한다."""
    history = agent.load_history(
        conv_after_detail_chat["conversation_id"], session_factory=session_factory
    )
    result = agent._resolve_contest_by_llm(
        "이거로 할래", conv_after_detail_chat["conversation_id"], history,
        llm=_CannedLLM("999"), session_factory=session_factory,
    )
    assert result == (None, None, False)


def test_select_resolves_demonstrative_from_context(
    session_factory, conv_after_detail_chat
):
    """"이걸로 할게"도 대화 맥락으로 어느 공모전인지 해석해 생성을 제안한다."""
    reply = agent._handle_select(
        conv_after_detail_chat["conversation_id"], "이걸로 할게",
        session_factory=session_factory, llm=_CannedLLM("11"),
    )
    assert reply is not None
    assert "국가데이터 활용대회" in reply
    assert "워크스페이스를 만들까요" in reply  # _OFFER_MARKERS 와 짝


# --------------------------------------------------------------------------- #
# S-02 적재
# --------------------------------------------------------------------------- #


def test_keyword_fallback_classifies_share_and_wrapup():
    assert agent._classify_intent_by_keyword("저장 말고 유진한테만 공유해줘")["intent"] == "share"
    assert agent._classify_intent_by_keyword("오늘은 여기까지만 할게")["intent"] == "wrapup"
    # 기존 저장 요청은 여전히 log.
    assert agent._classify_intent_by_keyword("오늘 작업한 거 저장해줘")["intent"] == "log"


def test_partial_save_asks_range_without_saving(session_factory, workspace_conv):
    _add_messages(
        session_factory, workspace_conv["conversation_id"],
        ("user", "트렌드 데이터 수집했어"), ("assistant", "좋아요"),
    )
    reply = agent._handle_log(
        workspace_conv["conversation_id"], workspace_conv["owner_id"],
        "이 부분만 저장해줘", session_factory=session_factory, llm=_CannedLLM("요약"),
    )
    assert "어느 부분부터 어느 부분까지" in reply
    with session_factory() as session:
        assert (
            session.query(Message).filter_by(
                conversation_id=workspace_conv["conversation_id"], role="log"
            ).count()
            == 0
        )


def test_range_answer_scopes_summary_prompt(session_factory, workspace_conv):
    """범위 답변 턴에서는 지정 구간만 요약하라는 지시가 프롬프트에 들어간다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("user", "트렌드 데이터 수집했어"),
        ("assistant", "좋아요"),
        ("user", "이 부분만 저장해줘"),
        ("assistant", agent._RANGE_QUESTION),
        ("user", "데이터 수집 얘기만"),
    )
    llm = _CannedLLM("요약: 수집 완료\n키워드: #데이터")
    agent._handle_log(
        conv_id, workspace_conv["owner_id"], "데이터 수집 얘기만",
        session_factory=session_factory, llm=llm,
    )
    assert "데이터 수집 얘기만" in llm.last_prompt
    assert "지정한 구간만 요약" in llm.last_prompt


def test_log_summarizes_only_since_last_log(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("user", "어제 한 브랜드 조사 내용"),
        ("log", "제목: 어제 로그\n요약: 브랜드 조사"),
        ("user", "오늘은 SNS 반응률 분석했어"),
        ("assistant", "좋네요"),
        ("user", "오늘 작업한 거 저장해줘"),
    )
    llm = _CannedLLM("요약: SNS 분석\n키워드: #SNS")
    agent._handle_log(
        conv_id, workspace_conv["owner_id"], "오늘 작업한 거 저장해줘",
        session_factory=session_factory, llm=llm,
    )
    assert "SNS 반응률" in llm.last_prompt
    assert "어제 한 브랜드 조사" not in llm.last_prompt


def test_merge_creates_preview_then_confirm_replaces_log(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("log", "제목: 트렌드 수집\n요약: 구매율 18% 증가\n키워드: #트렌드"),
        ("user", "오늘은 온라인 비중 67%까지 확인했어"),
        ("assistant", "좋아요"),
        ("user", "지난번에 저장한 거랑 합쳐줘"),
    )
    llm = _CannedLLM("제목: 트렌드 수집\n요약: 구매율 18%↑, 온라인 비중 67%\n키워드: #트렌드")
    reply = agent._handle_log(
        conv_id, workspace_conv["owner_id"], "지난번에 저장한 거랑 합쳐줘",
        session_factory=session_factory, llm=llm,
    )
    assert "이대로 저장할까요" in reply  # _OFFER_MARKERS(logmerge)와 짝
    with session_factory() as session:
        # 아직 기존 로그는 그대로, 미리보기(draft)만 생겼다.
        logs = session.query(Message).filter_by(conversation_id=conv_id, role="log").all()
        assert len(logs) == 1 and "구매율 18% 증가" in logs[0].content
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log_draft").count() == 1

    confirm = agent._handle_log_merge_confirm(conv_id, session_factory=session_factory)
    assert "업데이트" in confirm
    with session_factory() as session:
        logs = session.query(Message).filter_by(conversation_id=conv_id, role="log").all()
        assert len(logs) == 1 and "온라인 비중 67%" in logs[0].content
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log_draft").count() == 0


def test_share_sends_to_teammate_without_logging(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("user", "오늘 SNS 반응률 데이터 정리했어"),
        ("assistant", "좋아요"),
        ("user", "저장 말고 유진한테만 공유해줘"),
    )
    reply = agent._handle_share(
        conv_id, workspace_conv["owner_id"], "저장 말고 유진한테만 공유해줘",
        session_factory=session_factory, llm=_CannedLLM("요약: SNS 정리\n키워드: #SNS"),
    )
    assert "유진" in reply and "저장하지 않았" in reply

    with session_factory() as session:
        # 실행 로그는 남지 않는다.
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log").count() == 0
        # 수신자(유진)의 워크스페이스 대화에 공유 메시지 + 알림이 생겼다.
        mate_conv = (
            session.query(Conversation)
            .filter_by(workspace_id=workspace_conv["workspace_id"], user_id=workspace_conv["mate_id"])
            .first()
        )
        assert mate_conv is not None
        contents = [
            m.content
            for m in session.query(Message).filter_by(conversation_id=mate_conv.id).all()
        ]
        assert any("공유했어요" in c and "SNS 정리" in c for c in contents)


def test_share_unknown_recipient_asks_who(session_factory, workspace_conv):
    reply = agent._handle_share(
        workspace_conv["conversation_id"], workspace_conv["owner_id"],
        "저장 말고 민수한테만 공유해줘",
        session_factory=session_factory, llm=_CannedLLM("요약"),
    )
    assert "누구에게" in reply and "유진" in reply


def test_wrapup_offers_save_and_yes_leads_to_log():
    reply = agent._handle_wrapup()
    assert "실행 로그에 저장해 드릴까요" in reply  # _OFFER_MARKERS(log)와 짝
    history = [MessageOut(role="assistant", content=reply), MessageOut(role="user", content="응")]
    assert agent._accepted_offer_intent(history, "응") == "log"


def test_weak_task_match_asks_confirmation_then_completes(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    with session_factory() as session:
        session.add(
            Task(
                workspace_id=workspace_conv["workspace_id"],
                title="경쟁 브랜드 포지셔닝 조사",
                status="todo",
            )
        )
        session.commit()
    _add_messages(
        session_factory, conv_id,
        ("user", "오늘 브랜드 자료 좀 봤어"),
        ("assistant", "좋아요"),
        ("user", "저장해줘"),
    )
    # 겹치는 단어가 "브랜드" 하나뿐 → 자동 완료 대신 확인 질문.
    reply = agent._handle_log(
        conv_id, workspace_conv["owner_id"], "저장해줘",
        session_factory=session_factory,
        llm=_CannedLLM("요약: 브랜드 자료 검토\n키워드: #브랜드"),
    )
    assert "완료 처리할까요" in reply and "경쟁 브랜드 포지셔닝 조사" in reply
    with session_factory() as session:
        task = session.query(Task).first()
        assert task.status == "todo"

    # "응" 수락 → taskdone 인텐트 → 완료 처리.
    history = [MessageOut(role="assistant", content=reply), MessageOut(role="user", content="응")]
    assert agent._accepted_offer_intent(history, "응") == "taskdone"
    done_reply = agent._handle_taskdone(conv_id, history, session_factory=session_factory)
    assert "완료 처리했어요" in done_reply
    with session_factory() as session:
        assert session.query(Task).first().status == "done"


class _BoomLLM:
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


class _FakeToolLLM:
    """지정한 이름의 도구를 찾아 실행하는 가짜 오케스트레이터 LLM.

    chat() 의 도구 우선 경로(_chat_with_tools)가 핸들러를 도구로 올바르게
    노출·실행하는지 검증한다. 핸들러 내부의 generate() 호출엔 generate_text 를 준다.
    """

    def __init__(self, call: str, kwargs: dict | None = None, generate_text: str = "요약: 작업\n키워드: #작업") -> None:
        self.call = call
        self.kwargs = kwargs or {}
        self.generate_text = generate_text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self.generate_text

    def generate_with_tools(self, prompt: str, tools: list) -> str:  # noqa: ARG002
        fn = next(t for t in tools if t.__name__ == self.call)
        return fn(**self.kwargs)


def test_wants_log_save_guard():
    """작업 보고는 저장 요청이 아니고, 명시 요청·저장 제안 수락은 저장 요청이다."""
    assert not agent._wants_log_save("오늘 데이터셋 3개 정리했어", [])
    assert agent._wants_log_save("오늘 작업한 거 저장해줘", [])
    assert agent._wants_log_save("지난번에 저장한 거랑 합쳐줘", [])
    offer = [MessageOut(role="assistant", content="오늘 작업한 내용을 실행 로그로 저장해 드릴까요?")]
    assert agent._wants_log_save("응", offer)
    assert not agent._wants_log_save("아니 됐어", offer)


def test_save_log_tool_refuses_mere_work_report(session_factory, workspace_conv):
    """모델이 작업 보고에 save_work_log 를 불러도 가드가 저장을 막는다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(session_factory, conv_id, ("user", "오늘 상권 데이터 시각화 초안 만들어봤어"))
    llm = _FakeToolLLM("save_work_log")
    # 가드가 [도구 미실행] 힌트를 반환 → 기록되지 않아 그 텍스트가 그대로 응답이 됨
    reply = agent.chat(
        conv_id, workspace_conv["owner_id"], session_factory=session_factory, llm=llm
    )
    assert "[도구 미실행]" in reply  # FakeLLM 은 도구 반환값을 그대로 돌려주므로
    with session_factory() as session:
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log").count() == 0


def test_format_detail_includes_all_collected_fields():
    """'자세히'는 우리가 모은 모든 정보(주최·키워드·기간·상금·자격·설명·링크)를 보여준다."""
    from datetime import date as date_cls

    d = CompetitionDetailOut(
        id=1,
        title="국가데이터 활용대회",
        organizer="국가데이터처",
        host_type="정부기관",
        category=["학술/논문"],
        keywords=["데이터", "AI"],
        target=["대학생", "일반인"],
        start_date=date_cls(2026, 7, 1),
        deadline=date_cls(2026, 8, 9),
        total_prize_amount=10_000_000,
        first_prize_amount=5_000_000,
        participation_type="team",
        team_config="3인 이하",
        is_career_benefit=True,
        requirements=["국내 거주자"],
        evaluation_criteria=["데이터 활용도 40%", "창의성 30%"],
        description="국가 데이터 활용 아이디어를 발굴하는 대회입니다.",
        url="https://example.com",
        status="진행중",
    )
    from worker import competition_agent

    out = competition_agent._format_detail(d)
    for expected in (
        "국가데이터처", "정부기관", "학술/논문", "데이터, AI", "대학생, 일반인",
        "2026-07-01 ~ 2026-08-09", "총상금 10,000,000원", "1등 상금 5,000,000원",
        "3인 이하", "취업·인턴 연계", "국내 거주자", "데이터 활용도 40%",
        "아이디어를 발굴", "https://example.com", "진행중",
    ):
        assert expected in out, f"누락: {expected}"


def test_chat_tool_path_show_details_relays_verbatim(monkeypatch, session_factory, workspace_conv):
    """카드 클릭("N번 더 자세히")이 show_competition_details 로 흘러 전체 정보가 그대로 전달된다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("recommend", json.dumps([{"ordinal": 1, "id": 11, "title": "국가데이터 활용대회"}], ensure_ascii=False)),
        ("user", "1번 공모전 더 자세히 알려줘"),
    )
    detail = CompetitionDetailOut(
        id=11, title="국가데이터 활용대회", organizer="국가데이터처",
        requirements=["국내 거주자"], evaluation_criteria=["창의성 30%"],
    )
    real_registry = agent.build_registry()
    monkeypatch.setattr(
        agent, "build_registry",
        lambda: {**real_registry, "get_competition_detail": lambda cid: detail if cid == 11 else None},
    )
    reply = agent.chat(
        conv_id, workspace_conv["owner_id"],
        session_factory=session_factory,
        llm=_FakeToolLLM("show_competition_details", kwargs={"competition_id": 11}),
    )
    assert "국가데이터처" in reply and "국내 거주자" in reply and "창의성 30%" in reply


def test_chat_tool_path_routes_save_log(session_factory, workspace_conv):
    """도구 우선 경로: 모델이 save_work_log 도구를 고르면 실행 로그가 저장된다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("user", "오늘 트렌드 데이터 정리했어"),
        ("assistant", "좋아요"),
        ("user", "오늘 작업한 거 저장해줘"),
    )
    reply = agent.chat(
        conv_id, workspace_conv["owner_id"],
        session_factory=session_factory, llm=_FakeToolLLM("save_work_log"),
    )
    assert "저장했어요" in reply
    with session_factory() as session:
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log").count() == 1


def test_chat_tool_path_routes_update_workspace(session_factory, workspace_conv):
    """어제 버그 형태: 워크스페이스가 있는 상태의 "연결해줘"가 update_workspace 로 흐른다."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("recommend", json.dumps([{"ordinal": 1, "id": 11, "title": "FUTURE FINANCE 챌린지"}], ensure_ascii=False)),
        ("user", "1번 공모전으로 바꿔 연결해줘"),
    )
    reply = agent.chat(
        conv_id, workspace_conv["owner_id"],
        session_factory=session_factory,
        llm=_FakeToolLLM("update_workspace", generate_text="없음"),
    )
    assert "FUTURE FINANCE 챌린지" in reply
    with session_factory() as session:
        assert session.get(Workspace, workspace_conv["workspace_id"]).contest_id == 11


def test_chat_tool_path_routes_complete_task(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    with session_factory() as session:
        session.add(
            Task(workspace_id=workspace_conv["workspace_id"], title="트렌드 데이터 수집", status="todo")
        )
        session.commit()
    _add_messages(session_factory, conv_id, ("user", "트렌드 데이터 수집 끝냈어, 완료 처리해줘"))
    reply = agent.chat(
        conv_id, workspace_conv["owner_id"],
        session_factory=session_factory,
        llm=_FakeToolLLM("complete_task", kwargs={"task_title": "트렌드 데이터 수집"}),
    )
    assert "완료 처리했어요" in reply
    with session_factory() as session:
        assert session.query(Task).first().status == "done"


def test_new_chat_adopts_member_workspace(session_factory, workspace_conv):
    """팀원이 (할 일 클릭이 아니라) 새 채팅으로 시작해도 저장이 거절되지 않는다.

    미연결 대화 + 워크스페이스 인텐트(log) → 소속 워크스페이스 자동 연결.
    """
    with session_factory() as session:
        conv = Conversation(user_id=workspace_conv["mate_id"])  # workspace_id 없음
        session.add(conv)
        session.flush()
        session.add_all(
            [
                Message(conversation_id=conv.id, role="user", content="오늘 트렌드 데이터 정리했어"),
                Message(conversation_id=conv.id, role="assistant", content="좋아요"),
                Message(conversation_id=conv.id, role="user", content="오늘 작업한 거 저장해줘"),
            ]
        )
        session.commit()
        conv_id = conv.id

    # LLM 이 죽어도 키워드 폴백(log) + 요약 폴백으로 저장까지 이어져야 한다.
    reply = agent.chat(
        conv_id, workspace_conv["mate_id"],
        session_factory=session_factory, llm=_BoomLLM(),
    )

    assert "저장했어요" in reply
    with session_factory() as session:
        assert session.get(Conversation, conv_id).workspace_id == workspace_conv["workspace_id"]
        assert session.query(Message).filter_by(conversation_id=conv_id, role="log").count() == 1


def test_adopt_noop_when_user_has_no_workspace(session_factory):
    """소속 워크스페이스가 없으면 기존 안내 문구가 그대로 나온다."""
    with session_factory() as session:
        user = User(email="solo@contest-helper.io", name="솔로", interests=[], skills=[])
        session.add(user)
        session.flush()
        conv = Conversation(user_id=user.id)
        session.add(conv)
        session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="오늘 작업한 거 저장해줘"))
        session.commit()
        conv_id, user_id = conv.id, user.id

    reply = agent.chat(conv_id, user_id, session_factory=session_factory, llm=_BoomLLM())
    assert "워크스페이스" in reply  # "아직 연결된 워크스페이스가 없어요" 안내 유지
    with session_factory() as session:
        assert session.get(Conversation, conv_id).workspace_id is None


def test_plan_assigns_by_llm_named_assignee(session_factory, workspace_conv):
    """계획의 담당자 칸(이름)이 실제 assignee 로 저장되고, 매칭 실패는 라운드로빈 폴백."""
    conv_id = workspace_conv["conversation_id"]
    _add_messages(
        session_factory, conv_id,
        ("user", "유진이는 데이터 분석 경험이 있어"),
        ("user", "주차별로 계획 짜고 팀원별로 할 일 나눠줘"),
    )
    tools = {
        "create_tasks": lambda workspace_id, tasks: tasks_tool.create_tasks(
            workspace_id=workspace_id, tasks=tasks, session_factory=session_factory
        )
    }
    reply = agent._handle_plan(
        conv_id, "주차별로 계획 짜고 팀원별로 할 일 나눠줘", tools,
        session_factory=session_factory,
        llm=_CannedLLM(
            "1주차 | 유진 | 관련 데이터셋 탐색\n"
            "1주차 | 채원 | 공모전 양식·평가 기준 분석\n"
            "2주차 | 없는사람 | 분석 방향성 설계"
        ),
    )

    with session_factory() as session:
        demo_yujin = session.query(User).filter_by(email="demo.yujin@conmate.local").first()
        demo_chaewon = session.query(User).filter_by(email="demo.chaewon@conmate.local").first()
        by_title = {
            t.title: t.assignee_id
            for t in session.query(Task).filter_by(workspace_id=workspace_conv["workspace_id"]).all()
        }
    # 담당자 칸의 이름이 그대로 assignee 가 된다(제목·담당 불일치 제거).
    assert by_title["관련 데이터셋 탐색"] == demo_yujin.id
    assert by_title["공모전 양식·평가 기준 분석"] == demo_chaewon.id
    # 매칭 안 되는 이름은 라운드로빈 폴백으로라도 반드시 배정된다.
    assert by_title["분석 방향성 설계"] is not None
    # 응답에도 담당자가 표기된다.
    assert "관련 데이터셋 탐색 — 유진" in reply


def test_strong_task_match_still_autocompletes(session_factory, workspace_conv):
    conv_id = workspace_conv["conversation_id"]
    with session_factory() as session:
        session.add(
            Task(
                workspace_id=workspace_conv["workspace_id"],
                title="트렌드 데이터 수집",
                status="todo",
            )
        )
        session.commit()
    _add_messages(
        session_factory, conv_id,
        ("user", "오늘 트렌드 데이터 수집 마쳤어"),
        ("assistant", "좋아요"),
        ("user", "저장해줘"),
    )
    reply = agent._handle_log(
        conv_id, workspace_conv["owner_id"], "저장해줘",
        session_factory=session_factory,
        llm=_CannedLLM("요약: 트렌드 데이터 수집 완료\n키워드: #트렌드 #데이터"),
    )
    assert "완료 처리: 트렌드 데이터 수집" in reply
    with session_factory() as session:
        assert session.query(Task).first().status == "done"
