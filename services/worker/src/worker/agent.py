"""에이전트의 "머리" — 추천(stub) + 대화(stub) + 대화기억 로더(배관, 완전구현).

이 모듈은 두 가지 종류의 코드를 담는다.

1) **과제(stub)** — AI 담당이 채울 두뇌:
   - ``run(payload)``  : 추천 능력. (기존)
   - ``chat(conversation_id, user_id)`` : 대화형 능력(추천/공부/계획). (신규)

2) **배관(완전 구현)** — 두뇌가 바로 쓸 수 있는 보조 함수:
   - ``load_history(conversation_id)`` : 대화 메시지 기록 로드.

배관/과제 경계 원칙: 큐·상태기계·DB 영속화·기억 로드는 미리 구현해 두고,
"무엇을 답할지"(추론/도구선택/LLM 호출)만 과제로 남긴다.

추천 루프 의사코드 (TECH-SPEC §3 AI):

    user = load_user(payload.user_id)                       # App DB 조회
    query = build_query(user.interests, user.skills)        # 관심사·스킬 → 쿼리
    candidates = semantic_search(query, k=payload.limit * 3)  # 후보 넉넉히
    recos = []
    for c in candidates[: payload.limit]:
        reason = llm.generate(prompt(user, c))              # "왜 너에게 맞는지"
        recos.append(
            RecommendationOut(
                competition_id=c.id, title=c.title, reason=reason
            )
        )
    return recos

고려사항(추천):
    - 후보 0건이면 빈 리스트 반환(예외 X).
    - LLM 실패 시 폴백 이유 문자열로 대체(작업 전체를 실패시키지 말 것).
    - 반환은 반드시 ``list[RecommendationOut]`` 이고 길이는 ``payload.limit`` 이하.
    - DB 저장은 배관(worker.main.handle_job)이 한다. 여기서 직접 저장하지 말 것.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable

from contest_helper_core.db import get_engine
from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
    TaskIn,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from worker import competition_agent
from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.competitions import (
    get_competition_detail,
    search_competitions,
)
from worker.mcp_tools.registry import build_registry
from worker.mcp_tools.web_search import web_search
from worker.progress_agent import (
    evaluate_progress,
    format_weekly_report,
    weekly_report,
)
from worker.rag import semantic_search
from worker.search_filters import apply_filters, extract_keyword_and_filters
from worker.style import STYLE_GUIDE

# 의도 분류는 LLM(GeminiClient.generate)이 담당한다. 이 키워드 dict 는 LLM 호출이
# 실패했을 때(자격증명 문제·네트워크 장애 등) 쓰는 규칙 기반 폴백 전용이다.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    # share 는 "저장 말고 C한테만 공유해줘"처럼 저장 표현이 섞이므로 log 보다 먼저 검사.
    "share": ["한테만 공유", "에게만 공유", "한테 공유", "에게 공유", "만 공유해"],
    # log 는 "워크스페이스에 저장해줘" 처럼 workspace 키워드와 겹치므로 workspace 보다 먼저 검사.
    "log": ["저장해", "기록해", "실행 로그", "작업한 거", "오늘 한 거", "로그로 남겨"],
    # wrapup 은 오늘 작업을 마무리하는 발화(S-02 STEP01 "오늘은 여기까지만 할게").
    "wrapup": ["여기까지만", "오늘은 여기까지", "이만할게", "이만 할게", "다음에 이어서"],
    # workspace 는 plan("계획 만들") 과 혼동되지 않도록 먼저 검사한다.
    "workspace": ["워크스페이스 만들", "워크스페이스 생성", "워크스페이스 열", "작업공간 만들"],
    # wsedit 은 "만들어줘"(workspace)와 겹치지 않는 "바꿔/수정/변경" 표현만 잡는다.
    # 이름을 "workspace_edit"이 아니라 "wsedit"으로 짓는 이유: _classify_intent의 매칭이
    # "intent in raw" 부분 문자열 검사라, "workspace"가 "workspace_edit"의 부분 문자열이면
    # LLM이 정확히 "workspace_edit"이라고 답해도 앞의 "workspace"로 잘못 매칭돼버린다.
    "wsedit": [
        "워크스페이스 이름", "워크스페이스 수정", "이름 바꿔", "이름을 바꿔", "이름으로 바꿔",
        "공모전 변경", "공모전으로 바꿔", "공모전으로 변경", "공모전 연결", "다시 연결",
    ],
    # wsinfo 는 조회("현황/상태/어떤")라 workspace(생성)·wsedit(수정) 표현과 겹치지 않는다.
    "wsinfo": [
        "워크스페이스 현황", "워크스페이스 상태", "어떤 워크스페이스", "무슨 워크스페이스",
        "워크스페이스 정보", "워크스페이스 알려줘",
    ],
    # select 는 직전 추천 목록에서 하나를 고르는 발화("1번으로 할게", "OO대회로 하자").
    # 예전엔 아무 인텐트에도 안 걸려 study 로 새면서 워크스페이스 생성으로 이어지지
    # 못했다. "확정" 은 주제 확정("첫 번째 주제로 확정 ... 계획 짜줘", S-01 STEP05)이
    # plan 대신 여기 걸리지 않도록 넣지 않는다.
    "select": [
        "로 할게", "로 하자", "로 결정", "로 진행하자", "이걸로", "그걸로", "번으로 갈게",
    ],
    # topic 은 "주제 추천" 처럼 recommend("추천") 과 겹칠 수 있어 recommend 보다 먼저 둔다.
    "topic": ["주제 추천", "주제 제안", "주제 후보", "주제 정해", "주제 뽑", "무슨 주제", "어떤 주제"],
    # advice 는 특정 할 일을 "어떻게 시작/진행"할지 방법을 묻는 질문(S-02 STEP01).
    # plan("계획/일정") 과 겹치지 않도록 "어떻게 ~" 표현 위주로 잡고 plan 보다 먼저 검사.
    "advice": ["어떻게 시작", "어떻게 하면 좋을", "어떻게 진행하면", "어떻게 접근", "어디서부터", "어떻게 해야 할"],
    # "주차" 는 계획 저장 후 "1주차 줄여줘" 같은 수정 요청이 plan 으로 다시 오게 한다.
    "plan": ["계획", "일정", "역할", "스케줄", "마감까지", "주차"],
    # "찾아줘"만 넣으면 "수상작 찾아줘"처럼 이미 언급된 공모전에 대한 사실 질문(study)까지
    # 걸려버려서, 새 공모전 탐색 의미가 뚜렷한 표현으로만 좁힌다.
    "recommend": ["추천", "공모전 찾아줘", "공모전 알려줘", "뭐가 있어"],
    # teamstatus 는 팀 전체(팀원별) 실행 현황(S-02 STEP03). progress(개인)보다 먼저 검사.
    "teamstatus": [
        "팀 전체 진행", "팀 전체 현황", "팀 진행 현황", "전체 진행 현황",
        "팀 현황", "팀원별 현황", "누가 뭐 했", "누가 무엇을",
    ],
    # riskcheck 는 팀장이 현황+다음 주 계획의 리스크 점검을 요청(S-03 STEP02).
    "riskcheck": ["현황 어때", "계획 괜찮", "이대로 괜찮", "다음 주 계획", "리스크 점검", "점검해줘", "괜찮을까"],
    "progress": ["진행률", "진행 상황", "진행상황", "어디까지"],
    # report 는 팀 전체 주간 집계. progress(개인)와 구분되도록 "리포트/주간" 위주로.
    "report": ["주간 리포트", "주간 보고", "주간 현황", "리포트 보여", "팀 리포트"],
    # background 는 자기소개성 진술이라 넓게 잡되, 다른 인텐트가 먼저 걸리도록 맨 뒤에 둔다.
    "background": ["경험이 있", "경험 있", "해봤", "해본 적", "잘해", "잘합니다", "관심이 많", "관심 많", "관심이 있"],
}
_VALID_INTENTS = (*_INTENT_KEYWORDS.keys(), "study")

# 워크스페이스가 있어야 동작하는 인텐트. 대화가 미연결이면 chat() 이 사용자의 소속
# 워크스페이스에 자동 연결한다(_adopt_workspace_if_missing). 생성·선택 계열
# (workspace/wsedit/select)은 새 워크스페이스를 만들거나 바꾸는 흐름이라 제외.
_WORKSPACE_INTENTS = frozenset(
    {
        "log", "share", "logmerge", "taskdone", "plan", "progress",
        "teamstatus", "riskcheck", "report", "advice", "wsinfo",
    }
)


def _adopt_workspace_if_missing(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """미연결 대화를 사용자의 (가장 최근) 소속 워크스페이스에 연결한다.

    팀원이 메인 화면의 "할 일 클릭"이 아니라 새 채팅으로 시작하면 대화에
    workspace_id 가 없어 저장/계획/공유가 전부 거절되는 문제의 안전망.
    소속 워크스페이스가 없으면 아무것도 하지 않는다(기존 안내 문구 유지).
    """
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.workspace_id is not None:
            return
        member_ws = (
            session.execute(
                select(WorkspaceMember.workspace_id)
                .where(WorkspaceMember.user_id == user_id)
                .order_by(WorkspaceMember.id.desc())
            )
            .scalars()
            .first()
        )
        if member_ws is None:
            return
        conv.workspace_id = member_ws
        session.commit()

def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다. (과제 stub)

    Args:
        payload: 작업 입력 (job_id, user_id, limit).

    Returns:
        길이 ``<= payload.limit`` 인 ``RecommendationOut`` 리스트.
    """
    session_factory = _default_session_factory()
    with session_factory() as session:
        user = session.get(User, payload.user_id)

    if user is None:
        return []

    # 관심사·스킬로 키워드 쿼리 생성
    query_parts = (user.interests or []) + (user.skills or [])
    keyword = " ".join(query_parts[:3]) if query_parts else None

    tools = build_registry()
    candidates = tools["search_competitions"](
        keyword=keyword, open_only=True, limit=payload.limit * 3
    )
    if not candidates:
        return []

    llm = GeminiClient()
    recos: list[RecommendationOut] = []

    for c in candidates[: payload.limit]:
        try:
            prompt = f"""사용자 정보:
- 관심사: {", ".join(user.interests or [])}
- 스킬: {", ".join(user.skills or [])}

공모전 정보:
- 제목: {c.title}
- 카테고리: {", ".join(c.category)}
- 마감: {c.deadline}
- 주최: {c.organizer or c.host or ""}

이 사용자에게 위 공모전을 추천하는 이유를 2~3문장으로 설명해 주세요."""
            reason = llm.generate(prompt)
        except Exception:
            reason = f"{c.title} 공모전이 관심사와 관련이 있습니다."

        recos.append(
            RecommendationOut(
                competition_id=c.id,
                title=c.title,
                reason=reason,
            )
        )

    return recos


def chat(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """대화형 에이전트의 한 턴을 실행해 어시스턴트 답변 텍스트를 반환한다. (과제 stub)

    하나의 에이전트가 모드(능력)만 바꿔 동작한다 (DESIGN-V2 §2):
      - 추천: ``semantic_search`` / ``search_competitions`` 로 맞는 공모전 찾기.
      - 공부: 개념·방법 설명. 특정 공모전 사실은 ``get_competition_detail`` 로 확인(환각 방지).
      - 계획: 주제·일정·역할 정리 후 **``create_tasks`` 도구를 호출**해
              워크스페이스에 할 일(Task)을 실제로 저장.

    구현 의사코드:

        history = load_history(conversation_id)             # 이전 대화 로드(배관)
        intent = detect_intent(history)                     # 추천 / 공부 / 계획
        tools = build_registry()                            # mcp_tools 레지스트리
        # 의도에 맞는 도구를 골라 호출(계획이면 tools["create_tasks"](...))
        reply = llm.generate(prompt(history, intent, tool_results))
        return reply

    Args:
        conversation_id: 대화 세션 id (App DB ``conversations.id``).
        user_id: 말을 건 사용자 id.

    Returns:
        어시스턴트가 사용자에게 보낼 답변 텍스트. (DB 저장은 배관이 한다)
    """
    history = load_history(conversation_id, session_factory=session_factory)
    last_user_msg = next(
        (m.content for m in reversed(history) if m.role == "user"), ""
    )

    # 1차: 도구 호출 오케스트레이션 — 인텐트를 미리 분류하지 않고, LLM이 대화 전체를
    # 보고 필요한 도구(핸들러)를 직접 고른다. "마지막 문장만 보고 17지선다" 방식의
    # 고질적 오분류(select/wsedit 혼동 등)를 구조적으로 제거한다.
    # 실패(모델 오류·빈 응답·도구 예외) 시 아래의 기존 인텐트 라우터로 폴백한다.
    if last_user_msg.strip():
        try:
            return _chat_with_tools(
                conversation_id, user_id, history, last_user_msg,
                session_factory=session_factory, llm=llm,
            )
        except Exception as exc:  # noqa: BLE001 - 인텐트 폴백 라우터가 이어받는다
            print(
                f"[chat] conv={conversation_id} tool-agent 실패 → 인텐트 폴백: {exc}",
                flush=True,
            )

    # 2차(폴백): 기존 인텐트 분류 라우터.
    # 직전 답변이 "~해 볼까요?" 제안으로 끝났고 사용자가 짧게 수락한 경우,
    # "응/좋아" 가 study 로 새지 않도록 그 제안의 인텐트로 바로 확정한다.
    accepted = _accepted_offer_intent(history, last_user_msg)
    continuation = None if accepted else _continuation_intent(history, last_user_msg)
    if accepted:
        message: dict = {"intent": accepted, "matched_on": "offer"}
        if accepted in ("workspace", "wsedit"):
            # 수락 메시지("응")엔 순번·이름이 없으므로, 제안의 근거였던 직전 사용자
            # 발화("1번으로 할게")를 공모전 특정용 컨텍스트로 쓴다.
            user_msgs = [m.content for m in history if m.role == "user"]
            if len(user_msgs) >= 2:
                last_user_msg = user_msgs[-2]
    elif continuation and _classify_intent_by_keyword(last_user_msg)["intent"] in (
        "study", "background"
    ):
        # 직전 되묻기에 대한 자유 서술 답변("3주 정도 필요해")은 그 흐름으로 되돌린다.
        # 단, 답변에 뚜렷한 다른 명령("계획 짜줘" 등)이 있으면 그쪽을 우선한다.
        message = {"intent": continuation, "matched_on": "continuation"}
    else:
        message = _classify_intent(last_user_msg, llm=llm)  # {"intent": ..., "matched_on": ...}
    # 데모/디버그용 로그: worker 컨테이너 로그에서 intent 분류 결과를 실시간으로 본다.
    print(
        f"[chat] conv={conversation_id} intent={message['intent']} "
        f"(by {message['matched_on']}) msg={last_user_msg[:40]!r}",
        flush=True,
    )
    tools = build_registry()

    # 워크스페이스가 필요한 요청인데 이 대화가 미연결이면(팀원이 할 일 클릭이 아니라
    # 새 채팅으로 시작한 경우), 소속 워크스페이스에 자동 연결해 "워크스페이스가
    # 없어요" 거절로 막히지 않게 한다. 생성/선택 계열(workspace/select 등)은 새
    # 워크스페이스를 만드는 흐름이므로 제외한다.
    if message["intent"] in _WORKSPACE_INTENTS:
        _adopt_workspace_if_missing(
            conversation_id, user_id, session_factory=session_factory
        )

    if message["intent"] == "log":
        return _handle_log(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )
    if message["intent"] == "share":
        return _handle_share(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )
    if message["intent"] == "wrapup":
        return _handle_wrapup()
    if message["intent"] == "logmerge":
        return _handle_log_merge_confirm(
            conversation_id, session_factory=session_factory
        )
    if message["intent"] == "taskdone":
        return _handle_taskdone(
            conversation_id, history, session_factory=session_factory
        )
    if message["intent"] == "workspace":
        return _handle_create_workspace(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )
    if message["intent"] == "wsedit":
        return _handle_workspace_edit(
            conversation_id, last_user_msg, session_factory=session_factory, llm=llm
        )
    if message["intent"] == "wsinfo":
        return _handle_workspace_info(
            conversation_id, tools, session_factory=session_factory
        )
    if message["intent"] == "select":
        reply = _handle_select(
            conversation_id, last_user_msg, session_factory=session_factory, llm=llm
        )
        if reply is not None:
            return reply
        # 고를 추천 목록이 없었으면 일반 질문으로 취급(study 폴백).
    if message["intent"] == "background":
        return _handle_background(
            conversation_id, session_factory=session_factory
        )
    if message["intent"] == "topic":
        return _handle_topic(
            conversation_id, session_factory=session_factory, llm=llm
        )
    if message["intent"] == "plan":
        return _handle_plan(
            conversation_id, last_user_msg, tools,
            session_factory=session_factory, llm=llm,
        )
    if message["intent"] == "recommend":
        return _handle_recommend(
            history, last_user_msg, conversation_id, session_factory=session_factory
        )
    if message["intent"] == "teamstatus":
        return _handle_team_status(
            conversation_id, session_factory=session_factory
        )
    if message["intent"] == "riskcheck":
        return _handle_risk_check(
            conversation_id, tools, session_factory=session_factory, llm=llm
        )
    if message["intent"] == "report":
        return _handle_report(conversation_id, session_factory=session_factory)
    if message["intent"] == "progress":
        return _handle_progress(
            conversation_id, user_id, tools, session_factory=session_factory, llm=llm
        )
    if message["intent"] == "advice":
        return _handle_task_advice(
            conversation_id, last_user_msg, tools,
            session_factory=session_factory, llm=llm,
        )
    return competition_agent._handle_study(
        last_user_msg, history, conversation_id, tools, llm=llm, session_factory=session_factory
    )


def _chat_with_tools(
    conversation_id: int,
    user_id: int,
    history: list[MessageOut],
    last_user_msg: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """도구 호출 오케스트레이션으로 한 턴을 처리한다. (인텐트 분류 없음)

    기존 인텐트 핸들러들을 도구(파이썬 함수)로 감싸 LLM에 넘기고
    (``generate_with_tools`` — study 경로에서 검증된 패턴), 모델이 대화 맥락을 보고
    필요한 도구를 직접 호출한다. 순번↔id 해석·멱등성·알림 같은 결정적 로직은
    전부 도구(핸들러) 내부에 그대로 남는다.

    Raises:
        Exception: 모델 호출 실패·빈 응답 등. 호출부(chat)가 인텐트 라우터로 폴백.
    """
    client = llm or GeminiClient()
    registry = build_registry()

    # 행동 도구의 출력을 기록한다. 행동 도구가 실행된 턴은 모델의 재구성(요약·
    # 왜곡 위험)을 버리고 도구 출력을 그대로 최종 답변으로 쓴다 — 핸들러 응답은
    # 이미 완성된 사용자向 문장이고, 카드 저장 등 부수효과와 텍스트가 어긋나면
    # 안 되기 때문(예: 추천 카드를 저장해 놓고 "못 찾았다"고 말하는 사고 방지).
    action_outputs: list[str] = []
    callables = [
        _record_output(fn, action_outputs)
        for fn in _build_action_tools(
            conversation_id, user_id, history, last_user_msg, registry,
            session_factory=session_factory, llm=llm,
        )
    ]
    # study 경로의 조회 도구들(비교/상세/웹검색/팀적합도/저장목록)도 같이 노출한다.
    callables.extend(
        [
            competition_agent._make_compare_tool(registry),
            competition_agent._make_get_competition_detail_tool(registry),
            competition_agent._make_web_search_tool(registry),
        ]
    )
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is not None:
        callables.append(
            competition_agent._make_team_fit_tool(workspace_id, registry, session_factory)
        )
        callables.append(
            competition_agent._make_list_saved_tool(workspace_id, session_factory)
        )

    latest = competition_agent.load_latest_recommend_list(
        conversation_id, session_factory=session_factory
    )

    # 추천 카드 클릭은 프론트가 보내는 "고정 문구"(UI 계약)라 모델을 거치지 않고
    # 결정적으로 전체 상세를 보여준다 — 모델이 조회 도구로 요약해버리는 것 방지.
    card_click = re.match(r"^\s*([1-9])\s*번 공모전 더 자세히 알려줘\s*$", last_user_msg)
    if card_click and latest:
        n = int(card_click.group(1))
        if 1 <= n <= len(latest):
            reply = _show_details_reply(registry, latest[n - 1]["id"])
            if reply is not None:
                return reply

    recommend_block = ""
    if latest:
        listing = "\n".join(f"{e['ordinal']}. {e['title']} (id={e['id']})" for e in latest)
        recommend_block = f"""

[직전 추천/검색 목록 — 순번 ↔ 내부 id]
{listing}
사용자가 "첫 번째/1번/이거"처럼 가리키면 위 목록(또는 직전 대화)의 그 공모전을 뜻합니다.
조회 도구를 호출할 때는 이 id를 쓰고, id는 어떤 형태로도 사용자에게 노출하지 마세요."""

    convo = [m for m in history if m.role in ("user", "assistant")][-30:]
    history_text = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}" for m in convo
    )

    prompt = f"""당신은 공모전 준비를 돕는 팀 도우미입니다. 아래 대화의 다음 답변을 만드세요.

[도구 사용 규칙 — 반드시 지키세요]
1. 사용자가 행동을 요청하면(추천/재검색, 워크스페이스 생성·수정·현황, 주제 제안,
   계획 수립·수정, 작업 저장·공유·병합 확정, 할 일 완료, 진행률·팀 현황·리스크 점검·
   주간 리포트, 작업 시작 방법) 반드시 해당 도구를 실제로 호출한 뒤 그 결과로 답하세요.
   도구를 부르지 않고 "했다"고 말하는 것은 금지입니다.
2. 헷갈리기 쉬운 경우의 기준:
   - 새 공모전을 찾아/추천해 달라 → recommend_competitions (목록을 절대 지어내지 말 것)
   - 워크스페이스가 이미 있는데 "이 공모전으로 연결해줘/바꿔줘/이름 바꿔줘" → update_workspace
   - 워크스페이스가 아직 없고 만들어 달라거나 공모전을 확정하고 시작하자 → create_workspace
   - 직전 답변의 "~할까요?" 제안에 사용자가 "응/좋아"로 수락 → 그 제안에 해당하는 도구를 즉시 호출
3. 도구가 완성된 답변 문장을 반환하면 내용을 바꾸거나 요약하지 말고 그대로 전달하세요.
4. 특정 공모전의 사실(수상작·심사위원·자격·마감·비교)은 조회 도구를 호출한 뒤 답하세요. 짐작 금지.
   단, "자세히/상세히 알려줘"처럼 전체 정보를 요청하면 get_competition_detail 이 아니라
   show_competition_details 를 호출하세요(전체 정보를 줄이지 않고 그대로 보여줘야 합니다).
5. 개념 설명·잡담처럼 도구가 필요 없는 말은 그냥 답하세요.
   - 팀원이 자기 경험·강점을 소개하기만 한 경우: 도구를 부르지 말고 기억해 뒀다고
     답하며 다른 팀원의 배경을 물어보세요(주제 제안을 명시적으로 요청받기 전까지
     propose_topics 금지).
   - 오늘 한 작업을 이야기하기만 한 경우: 도구를 부르지 말고 작업 내용에 반응하며
     이어서 도우세요(저장을 명시적으로 요청받기 전까지 save_work_log 금지).
   - 사용자가 작업을 마무리하려 하면("오늘은 여기까지만") 실행 로그 저장을 제안하는
     질문으로 답하세요(도구 호출은 사용자가 수락한 다음 턴에).
6. 내부 고유번호(id)는 어떤 형태로도 사용자에게 노출하지 마세요.

{STYLE_GUIDE}{recommend_block}

[대화 기록]
{history_text}

사용자의 마지막 메시지: {last_user_msg}"""

    reply = client.generate_with_tools(prompt, tools=callables)
    # 행동 도구가 실행됐으면 그 출력이 곧 답변이다(모델의 재구성 무시).
    if action_outputs:
        return "\n\n".join(action_outputs).strip()
    if not reply or not reply.strip():
        raise RuntimeError("도구 오케스트레이션이 빈 응답을 반환했습니다")
    return reply.strip()


# 도구가 "실행하지 않기로" 판단했을 때 모델에게만 돌려주는 힌트의 접두어.
# 이 접두어가 붙은 출력은 최종 답변으로 기록하지 않는다(모델이 대화로 답하게).
_NO_RECORD = "[도구 미실행] "


def _show_details_reply(registry: dict, competition_id: int) -> str | None:
    """공모전 상세 전체를 보여주는 완성 답변을 만든다(없으면 None)."""
    detail = registry["get_competition_detail"](competition_id)
    if detail is None:
        return None
    return (
        "이 공모전에 대해 지금까지 모은 정보를 전부 정리했어요.\n\n"
        + competition_agent._format_detail(detail)
        + "\n\n이 공모전으로 정하시면 워크스페이스를 만들어 바로 준비를 시작할 수 있어요. 어떻게 할까요?"
    )


def _record_output(fn: Callable, sink: list[str]) -> Callable:
    """도구 함수를 감싸 반환값을 sink 에 기록한다(이름·docstring·시그니처 보존)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        out = fn(*args, **kwargs)
        if not str(out).startswith(_NO_RECORD):
            sink.append(str(out))
        return out

    return wrapper


def _wants_log_save(last_user_msg: str, history: list[MessageOut]) -> bool:
    """이번 발화가 '명시적 저장 요청'인지 결정적으로 판단한다.

    모델(flash 계열)이 작업 보고("오늘 ~ 정리했어")에도 save_work_log 를 부르는
    과잉 호출을 도구 쪽에서 걸러내기 위한 가드. 다음 중 하나면 저장 요청으로 본다:
    - 저장/기록/병합 키워드가 발화에 직접 있음
    - 직전 답변의 저장 제안("저장해 드릴까요/저장할까요")에 대한 짧은 수락
    - 직전 답변이 부분 저장 범위 질문이었음(이번 발화 = 범위 지정)
    """
    if any(k in last_user_msg for k in ("저장", "기록", "남겨", "합쳐", "합치", "로그")):
        return True
    last_assistant = next(
        (m.content for m in reversed(history) if m.role == "assistant"), ""
    )
    if "어느 부분부터 어느 부분까지 저장할까요" in last_assistant:
        return True
    if ("저장해 드릴까요" in last_assistant or "저장할까요" in last_assistant) and (
        len(last_user_msg.strip()) <= 12
        and any(w in last_user_msg for w in _AFFIRMATIONS)
        and not any(n in last_user_msg for n in _NEGATIONS)
    ):
        return True
    return False


def _build_action_tools(
    conversation_id: int,
    user_id: int,
    history: list[MessageOut],
    last_user_msg: str,
    registry: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> list[Callable]:
    """행동(쓰기) 핸들러들을 LLM 도구로 감싼 클로저 목록을 만든다.

    docstring 이 곧 도구 선택 기준이다(Automatic Function Calling). 워크스페이스가
    필요한 도구는 진입 시 ``_adopt_workspace_if_missing`` 으로 미연결 대화를 소속
    워크스페이스에 붙인다(팀원이 새 채팅으로 시작한 경우 안전망).
    """

    def _adopt() -> None:
        _adopt_workspace_if_missing(
            conversation_id, user_id, session_factory=session_factory
        )

    def recommend_competitions() -> str:
        """새 공모전을 찾아 추천하거나, 조건을 바꿔 다시 검색한다.

        "공모전 추천해줘", "마감 여유 있는 다른 거 없어?", "상금 더 큰 거",
        "비슷한 다른 것도"처럼 새 공모전 탐색·재검색 요청이면 호출하세요.
        조건 파악·검색·목록 구성까지 완성된 답변을 반환합니다.
        주의: 이미 대화에 나온 공모전을 워크스페이스에 "연결/변경"해 달라는 요청은
        검색이 아닙니다 — 이 도구가 아니라 update_workspace 를 호출하세요.
        """
        return _handle_recommend(
            history, last_user_msg, conversation_id, session_factory=session_factory
        )

    def show_competition_details(competition_id: int) -> str:
        """공모전 하나의 상세 정보를 "빠짐없이 전부" 보여준다.

        "1번 공모전 더 자세히 알려줘", "이 공모전 자세히/상세 정보 보여줘"처럼
        전체 정보를 요청하면(추천 카드 클릭 포함) 호출하세요. competition_id 는
        [직전 추천/검색 목록]의 id 를 씁니다.
        특정 사실 하나만 묻는 질문(예: "혼자 나갈 수 있어?", "마감 언제야?")은
        이 도구가 아니라 get_competition_detail 로 확인해 그 부분만 답하세요.

        Args:
            competition_id: 상세를 보여줄 공모전의 내부 id.
        """
        reply = _show_details_reply(registry, competition_id)
        if reply is None:
            return (
                _NO_RECORD
                + "해당 id 의 공모전을 찾지 못했습니다. [직전 추천/검색 목록]의 id 를 확인해 다시 시도하세요."
            )
        return reply

    def create_workspace() -> str:
        """새 워크스페이스를 만들고 방금 얘기한 공모전을 연결한다.

        사용자가 워크스페이스를 만들어 달라고 하거나, 공모전을 확정하고 팀 준비를
        시작하자고 할 때 호출하세요. 어떤 공모전인지는 직전 대화에서 스스로 찾습니다.
        이미 연결된 워크스페이스가 있으면 새로 만들지 않고 안내만 합니다.
        """
        return _handle_create_workspace(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )

    def update_workspace() -> str:
        """이미 있는 워크스페이스의 이름을 바꾸거나 연결된 공모전을 바꾼다.

        "워크스페이스에 이 공모전 연결해줘", "그럼 지금 공모전 연결해줘"(직전 대화의
        그 공모전을 연결), "다른 공모전으로 바꿔줘", "이름 바꿔줘"처럼 기존
        워크스페이스의 설정 변경 요청이면 호출하세요. 자격 요건이 걱정돼도 사용자가
        연결을 요청했으면 먼저 연결부터 하세요.
        """
        _adopt()
        return _handle_workspace_edit(
            conversation_id, last_user_msg, session_factory=session_factory, llm=llm
        )

    def get_workspace_status() -> str:
        """지금 연결된 워크스페이스의 현황(공모전·팀원·할 일 진행)을 보여준다.

        "지금 어떤 워크스페이스야?", "워크스페이스 현황 알려줘"처럼 물으면 호출하세요.
        """
        _adopt()
        return _handle_workspace_info(
            conversation_id, registry, session_factory=session_factory
        )

    def propose_topics() -> str:
        """팀원들의 배경·강점을 종합해 공모전 주제 후보를 제안한다.

        "주제 추천해줘/정하자", 주제를 좁히거나 다시 제안해 달라는 "명시적 요청"일 때만
        호출하세요. 팀원이 자기 배경을 소개하기만 한 발화에는 호출하면 안 됩니다.
        """
        # 결정적 가드: "주제" 언급이나 주제 제안 수락이 아니면 실행하지 않는다.
        last_assistant = next(
            (m.content for m in reversed(history) if m.role == "assistant"), ""
        )
        accepted_topic_offer = "주제 후보를 제안해 볼까요" in last_assistant and any(
            w in last_user_msg for w in _AFFIRMATIONS
        )
        if "주제" not in last_user_msg and not accepted_topic_offer:
            return (
                _NO_RECORD
                + "이 발화는 주제 제안 요청이 아닙니다. 배경을 기억해 뒀다고 답하고 "
                "다른 팀원의 배경을 물어보세요."
            )
        _adopt()
        return _handle_topic(
            conversation_id, session_factory=session_factory, llm=llm
        )

    def create_or_revise_plan() -> str:
        """마감까지의 주차별 준비 계획을 세우거나 수정하고 팀원별로 배정한다.

        "계획 짜줘", "역할 나눠줘", "1주차 줄여줘", "B 일 줄여줘"처럼 계획
        수립·조정 요청이면 호출하세요. 기존 계획이 있으면 교체 방식으로 수정합니다.
        """
        _adopt()
        return _handle_plan(
            conversation_id, last_user_msg, registry,
            session_factory=session_factory, llm=llm,
        )

    def save_work_log() -> str:
        """오늘 작업한 대화 내용을 요약해 워크스페이스 실행 로그에 저장한다.

        사용자가 저장을 "명시적으로" 요청할 때만 호출하세요: "오늘 작업한 거
        저장해줘", "이 부분만 저장해줘", "지난번에 저장한 거랑 합쳐줘",
        저장 제안("저장해 드릴까요?")에 대한 수락("응/저장해줘") 등.
        주의: 작업 내용을 이야기하기만 한 발화(예: "오늘 데이터셋 3개 정리했어")에는
        절대 호출하지 말고, 대화로 반응하며 계속 작업을 도우세요.
        병합 미리보기("이대로 저장할까요?")에 대한 수락만 confirm_log_merge 입니다.
        """
        # 결정적 가드: 명시적 저장 요청이 아니면 실행하지 않는다(모델 과잉 호출 방어).
        if not _wants_log_save(last_user_msg, history):
            return (
                _NO_RECORD
                + "이 발화는 명시적 저장 요청이 아닙니다. 저장하지 않았습니다 — "
                "작업 내용에 대화로 반응하고, 필요하면 저장 여부를 물어보세요."
            )
        _adopt()
        return _handle_log(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )

    def confirm_log_merge() -> str:
        """직전의 로그 병합 미리보기를 확정해 기존 실행 로그를 교체한다.

        직전 어시스턴트 답변에 "이대로 저장할까요?"라는 병합 미리보기가 있고
        사용자가 수락("응/좋아")했을 때만 호출하세요. 그 문구가 직전 답변에 없다면
        절대 호출하지 마세요 — 일반 저장 요청은 save_work_log 입니다.
        """
        _adopt()
        return _handle_log_merge_confirm(
            conversation_id, session_factory=session_factory
        )

    def share_work_with_member() -> str:
        """작업 요약을 워크스페이스 전체 공개(로그) 대신 특정 팀원에게만 보낸다.

        "저장 말고 OO한테만 공유해줘"처럼 특정 팀원에게만 전달해 달라는 요청이면
        호출하세요. 수신자 특정·전송·알림까지 처리합니다.
        """
        _adopt()
        return _handle_share(
            conversation_id, user_id, last_user_msg,
            session_factory=session_factory, llm=llm,
        )

    def complete_task(task_title: str) -> str:
        """워크스페이스의 할 일 하나를 완료(done) 처리한다.

        사용자가 특정 할 일을 끝냈다고 하거나, 직전 답변의 "'OO' 할 일을 완료
        처리할까요?" 제안에 수락했을 때 그 제목으로 호출하세요.

        Args:
            task_title: 완료 처리할 할 일 제목(대화에 나온 제목 그대로).
        """
        _adopt()
        return _complete_task_by_title(
            conversation_id, task_title, session_factory=session_factory
        )

    def get_my_progress() -> str:
        """내(현재 사용자)의 할 일 진행률과 코멘트를 보여준다.

        "내 진행률 어때?", "어디까지 했지?"처럼 개인 진척을 물으면 호출하세요.
        """
        _adopt()
        return _handle_progress(
            conversation_id, user_id, registry,
            session_factory=session_factory, llm=llm,
        )

    def get_team_status() -> str:
        """팀 전체(팀원별)가 각각 무엇을 했는지 실행 현황을 보여준다.

        "팀 전체 진행 현황", "누가 뭐 했어?"처럼 팀 단위 현황을 물으면 호출하세요.
        """
        _adopt()
        return _handle_team_status(conversation_id, session_factory=session_factory)

    def check_plan_risks() -> str:
        """현재 현황을 근거로 다음 주 계획의 리스크를 진단하고 조치를 제안한다.

        "이번 주 현황 어때? 다음 주 계획 괜찮아?"처럼 점검·진단 요청이면 호출하세요.
        """
        _adopt()
        return _handle_risk_check(
            conversation_id, registry, session_factory=session_factory, llm=llm
        )

    def create_weekly_report() -> str:
        """팀 전체의 주간 리포트를 집계해 워크스페이스에 저장하고 보여준다.

        "주간 리포트 보여줘/만들어줘" 요청이면 호출하세요.
        """
        _adopt()
        return _handle_report(conversation_id, session_factory=session_factory)

    def advise_task_start() -> str:
        """맡은 할 일을 어떻게 시작하면 좋을지 공모전 맥락과 연결해 조언한다.

        "OO 해야 하는데 어떻게 시작하면 좋을까?"처럼 작업 방법을 물으면 호출하세요.
        """
        _adopt()
        return _handle_task_advice(
            conversation_id, last_user_msg, registry,
            session_factory=session_factory, llm=llm,
        )

    return [
        recommend_competitions,
        show_competition_details,
        create_workspace,
        update_workspace,
        get_workspace_status,
        propose_topics,
        create_or_revise_plan,
        save_work_log,
        confirm_log_merge,
        share_work_with_member,
        complete_task,
        get_my_progress,
        get_team_status,
        check_plan_risks,
        create_weekly_report,
        advise_task_start,
    ]


def _complete_task_by_title(
    conversation_id: int,
    task_title: str,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """제목으로 todo 할 일을 찾아 완료 처리한다(정확 일치 → 포함 일치 순)."""
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return "아직 연결된 워크스페이스가 없어서 완료 처리할 할 일이 없어요."

    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        todos = (
            session.execute(
                select(Task).where(
                    Task.workspace_id == workspace_id, Task.status == "todo"
                )
            )
            .scalars()
            .all()
        )
        task = next((t for t in todos if t.title == task_title), None)
        if task is None:
            wanted = task_title.strip()
            task = next(
                (t for t in todos if wanted and (wanted in t.title or t.title in wanted)),
                None,
            )
        if task is None:
            return f"'{task_title}' 할 일을 찾지 못했어요. 이미 완료됐거나 이름이 바뀌었을 수 있어요."
        task.status = "done"
        done_title = task.title
        session.commit()
    return f"✅ '{done_title}' 할 일을 완료 처리했어요. 이어서 진행할 작업이 있나요?"


# --------------------------------------------------------------------------- #
# 과제(stub) 내부 헬퍼: 의도 분류 + 능력별 처리
# --------------------------------------------------------------------------- #


# 어시스턴트가 답변 끝에 던지는 제안 문구 → 사용자가 수락하면 확정할 인텐트.
_OFFER_MARKERS: list[tuple[str, str]] = [
    ("주제 후보를 제안해 볼까요", "topic"),
    ("워크스페이스를 만들까요", "workspace"),
    ("바꿔 연결할까요", "wsedit"),
    ("계획을 짜 볼까요", "plan"),
    ("실행 로그에 저장해 드릴까요", "log"),
    ("이대로 저장할까요", "logmerge"),
    ("완료 처리할까요", "taskdone"),
]

# 어시스턴트의 되묻는 질문 → 사용자의 다음 답변(자유 서술)을 이어받을 인텐트.
# _OFFER_MARKERS 는 "응/좋아" 같은 짧은 수락 전용이고, 여기는 "3주 정도 필요해"처럼
# 내용이 있는 답변이 키워드/LLM 분류로 엉뚱하게 새지 않도록 직전 질문의 흐름으로 되돌린다.
_CONTINUATION_MARKERS: list[tuple[str, str]] = [
    ("어느 부분부터 어느 부분까지 저장할까요", "log"),      # 부분 저장 범위 답변
    ("준비 기간이 얼마나 필요", "recommend"),               # 마감 여유 재검색 조건 답변
]


def _continuation_intent(history: list[MessageOut], last_user_msg: str) -> str | None:
    """직전 어시스턴트의 되묻는 질문에 대한 답변이면 그 흐름의 인텐트를 반환한다."""
    if not last_user_msg.strip():
        return None
    last_assistant = next(
        (m.content for m in reversed(history) if m.role == "assistant"), ""
    )
    for marker, intent in _CONTINUATION_MARKERS:
        if marker in last_assistant:
            return intent
    return None
_AFFIRMATIONS = ("응", "네", "넵", "예", "그래", "좋아", "좋지", "콜", "오케이", "ㅇㅋ", "고고", "해줘", "해 줘", "부탁")
_NEGATIONS = ("아니", "안 ", "말고", "나중에", "됐어", "괜찮아")


def _accepted_offer_intent(history: list[MessageOut], last_user_msg: str) -> str | None:
    """직전 어시스턴트 답변의 제안("~해 볼까요?")을 사용자가 짧게 수락했으면 그 인텐트를 반환한다.

    "응"/"좋아" 같은 짧은 수락은 키워드·LLM 분류 모두 study 로 새기 쉬워서,
    제안-수락 짝을 여기서 먼저 확정한다. 길거나 부정이 섞인 메시지는 건드리지 않는다.
    """
    text = last_user_msg.strip()
    if not text or len(text) > 12:
        return None
    if any(neg in text for neg in _NEGATIONS):
        return None
    if not any(word in text for word in _AFFIRMATIONS):
        return None
    last_assistant = next(
        (m.content for m in reversed(history) if m.role == "assistant"), ""
    )
    for marker, intent in _OFFER_MARKERS:
        if marker in last_assistant:
            return intent
    return None


def _classify_intent(text: str, *, llm: LLMClient | None = None) -> dict:
    """사용자의 마지막 메시지를 LLM 으로 추천/공부/계획/진행률 중 하나로 분류한다.

    search_agent 쪽 도구를 부를지, create_tasks/evaluate_progress 를 부를지
    결정하는 dict 메시지. LLM 호출이 실패하면(자격증명·네트워크 등) 규칙 기반
    키워드 매칭으로 폴백한다(전체 대화가 죽지 않도록).
    """
    if not text:
        return {"intent": "study", "matched_on": "default"}

    # 프론트의 "할 일 클릭"(S-02 STEP01)은 "...어떻게 시작하면 좋을까?" 같은 고정 문구를 보낸다.
    # 이 표현들은 다른 인텐트와 겹치지 않으므로 LLM(오분류 잦음) 전에 advice 로 바로 확정한다.
    if any(k in text for k in _INTENT_KEYWORDS["advice"]):
        return {"intent": "advice", "matched_on": "keyword"}
    # "팀 전체 진행 현황"(S-02 STEP03)도 progress(개인)와 헷갈리기 쉬워 먼저 확정한다.
    if any(k in text for k in _INTENT_KEYWORDS["teamstatus"]):
        return {"intent": "teamstatus", "matched_on": "keyword"}
    # "현황 어때/계획 괜찮아?"(S-03 STEP02) 리스크 점검도 먼저 확정한다.
    if any(k in text for k in _INTENT_KEYWORDS["riskcheck"]):
        return {"intent": "riskcheck", "matched_on": "keyword"}
    # "OO로 하자/할게" 선택 발화는 LLM 이 wsedit/plan 으로 오분류하기 쉬워 먼저
    # 확정한다. 단, 워크스페이스 생성·계획 요청이 같이 있으면 그쪽이 우선.
    if any(k in text for k in _INTENT_KEYWORDS["select"]) and not any(
        k in text for k in _INTENT_KEYWORDS["workspace"] + _INTENT_KEYWORDS["plan"]
    ):
        return {"intent": "select", "matched_on": "keyword"}

    prompt = f"""당신은 공모전 준비를 돕는 챗봇의 의도 분류기입니다.
아래 사용자 메시지를 다음 목록 중 정확히 하나로 분류하고, 그 단어 하나만 답하세요.
다른 설명이나 문장부호 없이 단어 하나만 출력해야 합니다.

- workspace: 아직 없는 워크스페이스를 "새로" 만들어 달라는 요청일 때만 (예: "워크스페이스 만들어줘", "1번으로 워크스페이스 만들어줘"). "바꿔줘/수정해줘/변경해줘"처럼 이미 있는 걸 고치는 요청이면 절대 이게 아니라 wsedit.
- wsedit: 이미 있는 워크스페이스의 이름을 바꾸거나 연결된 공모전을 다른 것으로 바꿔 달라는 요청 (예: "워크스페이스 이름 바꿔줘", "1번 공모전으로 다시 연결해줘", "공모전 바꿔줘")
- wsinfo: 지금 연결된 워크스페이스가 뭔지, 그 현황·상태를 물어봄 (예: "지금 어떤 워크스페이스야?", "워크스페이스 현황 알려줘")
- select: 직전에 보여준 목록에서 하나를 골라 확정하는 발화. 순번("1번으로 할게", "첫 번째 걸로 하자")뿐 아니라 이름으로 고르는 것("그럼 OO공모전으로 하자")도 포함. 단, 같은 메시지에 워크스페이스 생성이나 계획 요청이 함께 있으면 select 가 아니라 그쪽(workspace/plan)으로 분류.
- log: 작업 내용을 저장/기록/남겨 달라고 "명시적으로" 요청할 때만 (예: "오늘 작업한 거 저장해줘", "지난번에 저장한 거랑 합쳐줘"). 단순히 오늘 한 일을 서술하면 study.
- share: 워크스페이스에 저장(공개)하는 대신 특정 팀원에게만 내용을 공유/전달해 달라는 요청 (예: "저장 말고 채원한테만 공유해줘"). "저장"이라는 말이 있어도 "말고 ~한테 공유"가 핵심이면 log 가 아니라 share.
- wrapup: 오늘 작업을 마무리하겠다는 발화 (예: "오늘은 여기까지만 할게", "이만 할게"). 저장 요청이 명시돼 있으면 log.
- background: 자기(팀원)의 경험·관심·강점을 소개하거나 진술 (예: "나는 데이터 분석 경험이 있어")
- topic: 주제/아이디어 후보를 제안해 달라고 "명시적으로" 요청할 때만
- advice: 이미 정해진 특정 할 일(작업)을 어떻게 시작·진행하면 좋을지 방법이나 방향을 물어봄 (예: "○○ 데이터 수집해야 하는데 어떻게 시작하면 좋을까?")
- plan: 준비 계획·일정·역할 분담을 요청. 이미 세운 계획의 수정·조정 요청도 포함 (예: "1주차 줄여줘", "계획 다시 짜줘")
- recommend: 아직 안 정한 "새 공모전"을 찾아/추천해 달라는 요청 (예: "공모전 추천해줘", "마케팅 관련 공모전 찾아줘")
- progress: (개인) 지금까지의 진행 상황·진척도를 물어봄
- teamstatus: 팀 전체(팀원별)가 각각 무엇을 했는지 실행 현황을 물어봄 (예: "팀 전체 진행 현황 알려줘", "누가 뭐 했어?")
- riskcheck: 현재 현황을 근거로 다음 주 계획의 리스크·문제를 점검/진단해 달라고 요청 (예: "이번 주 현황 어때? 다음 주 계획 괜찮아?")
- report: 팀 전체의 주간 리포트/집계 현황을 요청 (예: "주간 리포트 보여줘")
- study: 그 외(개념 설명, 질문, 잡담 등). 이미 언급된 공모전에 대한 사실 질문(작년 수상작, 심사위원, 참가자격, 비교 등 "찾아줘/알려줘"라고 물어도 새 공모전 탐색이 아니면 여기)도 포함

사용자 메시지: "{text}"

분류 결과(단어 하나만):"""

    try:
        client = llm or GeminiClient()
        raw = client.generate(prompt).strip().lower()
    except Exception:
        return _classify_intent_by_keyword(text)

    for intent in _VALID_INTENTS:
        if intent in raw:
            return {"intent": intent, "matched_on": "llm"}
    # LLM 이 넷 중 하나로 파싱 안 되는 답을 준 경우도 폴백.
    return _classify_intent_by_keyword(text)


def _classify_intent_by_keyword(text: str) -> dict:
    """LLM 이 실패하거나 애매하게 답했을 때 쓰는 규칙 기반 폴백 분류."""
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return {"intent": intent, "matched_on": "keyword"}
    return {"intent": "study", "matched_on": "default"}


# [데모] 팀원 전환용 데모 팀. api 의 workspaces/service._DEMO_TEAM 과 이메일이 동일해야
# 같은 사용자를 가리킨다. "네 명이 참가한다" 가정에 따라 워크스페이스에 자동 편성한다.
_DEMO_OWNER_NAME = "동영 (팀장)"
_DEMO_TEAM = [
    ("demo.yujin@conmate.local", "유진", "데이터 분석"),
    ("demo.chaewon@conmate.local", "채원", "기획"),
    ("demo.chaeeun@conmate.local", "채은", "디자인"),
]
# 이메일 → 데모 팀원 이름. 데모 계정으로 로그인한 상태에서 워크스페이스를 만들어도
# 그 계정을 "동영 (팀장)"으로 덮어쓰지 않도록 판별에 쓴다.
_DEMO_NAMES = {email: name for email, name, _ in _DEMO_TEAM}


def _ensure_team_members(session: Session, workspace_id: int, owner_id: int) -> list[int]:
    """워크스페이스에 데모 팀원(유진/채원/채은)을 보장하고 [owner, ...] id 목록을 반환한다."""
    owner = session.get(User, owner_id)
    if owner is not None:
        # owner 가 데모 팀원 계정(팀원 전환으로 로그인된 경우)이면 그 사람 이름을 지킨다.
        # 실제 사람(동영) 계정일 때만 "동영 (팀장)" 표기를 붙인다.
        if owner.email in _DEMO_NAMES:
            owner.name = _DEMO_NAMES[owner.email]
        elif owner.name != _DEMO_OWNER_NAME:
            owner.name = _DEMO_OWNER_NAME
    ids = [owner_id]
    for email, name, role in _DEMO_TEAM:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if user is None:
            user = User(email=email, name=name, interests=[], skills=[])
            session.add(user)
            session.flush()
        elif user.name != name:
            user.name = name  # 과거에 오염된 이름 자동 교정
        exists = session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role)
            )
        ids.append(user.id)
    return ids


def _handle_plan(
    conversation_id: int,
    last_user_msg: str,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """확정 주제·팀원 배경·공모전 마감을 참고해 주차별 계획을 LLM 으로 뽑아
    여러 개의 ``Task`` (week_no 포함)로 워크스페이스에 저장한다. (S-01 STEP05)

    이미 계획이 있으면 "추가"가 아니라 "교체"한다: 미완료(todo) 할 일을 지우고
    기존 계획+수정 요청을 반영한 새 계획으로 갈아끼운다(완료된 할 일은 보존).
    LLM 실패/파싱 실패 시엔 기존 계획을 건드리지 않는다(첫 계획일 때만
    메시지 전체를 할 일 1개로 저장하는 폴백).
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    # 맥락 수집: 확정 주제(role=topic), 팀원 배경, 공모전 마감.
    history = load_history(conversation_id, session_factory=session_factory)
    topic = next((m.content for m in reversed(history) if m.role == "topic"), "")
    backgrounds = "\n".join(
        f"- {m.content}"
        for m in history
        if m.role == "user"
        and m.content.strip()
        and _classify_intent_by_keyword(m.content)["intent"] in ("study", "background")
    )
    deadline = _load_deadline(workspace_id, tools, session_factory=session_factory)

    if session_factory is None:
        session_factory = _default_session_factory()

    # 팀원을 먼저 보장해 이름 목록을 확보한다 — 담당자는 LLM 이 계획에서 직접
    # 지정한다(제목 속 이름과 라운드로빈 배정이 어긋나는 문제 방지).
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        owner_id = ws.owner_id
        member_ids = _ensure_team_members(session, workspace_id, owner_id)
        # 표시 이름의 첫 토큰("동영 (팀장)" → "동영")을 매칭 키로 쓴다.
        name_by_id = {
            uid: ((session.get(User, uid).name or f"팀원{uid}").split()[0])
            for uid in member_ids
        }
        session.commit()
    id_by_name = {name: uid for uid, name in name_by_id.items()}

    # 기존 계획 파악 — 있으면 이번 요청은 "수정"이고, 미완료 할 일은 새 계획으로 교체한다.
    with session_factory() as session:
        existing = (
            session.execute(
                select(Task)
                .where(Task.workspace_id == workspace_id)
                .order_by(Task.week_no.asc(), Task.id.asc())
            )
            .scalars()
            .all()
        )
        prev_todo_ids = [t.id for t in existing if t.status != "done"]
        prev_plan_text = "\n".join(
            f"{t.week_no or 1}주차 | {name_by_id.get(t.assignee_id, '미정')} | {t.title}"
            for t in existing
            if t.status != "done"
        )
        done_titles = [t.title for t in existing if t.status == "done"]

    # 계획의 재료(주제·배경·마감·기존 계획)가 하나도 없으면 일반론을 지어내지 말고
    # 먼저 묻는다(참여 유도).
    if not existing and not topic and not backgrounds and not deadline:
        return (
            "계획을 짜기 전에 재료가 조금 필요해요. 어떤 공모전(또는 주제)을 준비하시나요? "
            "팀원들의 경험·강점도 알려주시면 역할 분담까지 함께 잡아 드릴게요."
        )

    revise_block = ""
    if prev_plan_text:
        done_block = (
            "\n이미 완료된 할 일 (새 계획에 다시 넣지 마세요):\n"
            + "\n".join(f"- {t}" for t in done_titles)
            if done_titles
            else ""
        )
        revise_block = f"""

[기존 계획 — 아직 미완료]
{prev_plan_text}
{done_block}
[수정 요청]
{last_user_msg}

기존 계획을 수정 요청에 맞게 고친 "전체 계획"을 출력하세요. 그대로 유지할 항목도 빠짐없이 다시 출력해야 합니다."""

    members_line = ", ".join(id_by_name)
    prompt = f"""당신은 공모전 팀의 준비 일정을 짜는 코치입니다.

확정 주제: {topic or "아직 미정"}
공모전 마감: {deadline or "미정"}
팀원(담당자 후보): {members_line}
팀원 배경(강점):
{backgrounds or "- (아직 입력된 배경 없음)"}

마감까지 4주 내외의 주차별 준비 계획을 세우세요.
- 각 주차에 팀이 수행할 구체적 할 일을 여러 개 나열합니다.
- 담당자는 반드시 위 "팀원(담당자 후보)" 목록의 이름 중 하나만 씁니다.
- 팀원 배경(강점)에 맞는 사람에게 배분하되, 특정 팀원에게 일이 몰리지 않게 하세요.
- 할 일 제목에는 사람 이름을 넣지 마세요 — 담당은 담당자 칸으로만 표현합니다.
- 두 명이 함께 하는 일은 한 줄로 쓰지 말고, 각자 맡을 몫으로 줄을 나눠 쓰세요.
- 반드시 아래 형식으로 "한 줄에 하나씩"만 출력하고, 다른 설명·머리말은 쓰지 마세요.

<주차숫자>주차 | <담당자> | <할 일 제목>

예시:
1주차 | {list(id_by_name)[0]} | 공모전 요강·심사기준 정리
1주차 | {list(id_by_name)[min(1, len(id_by_name) - 1)]} | 2030 소비 트렌드 데이터 수집
2주차 | {list(id_by_name)[min(2, len(id_by_name) - 1)]} | SNS 반응률-구매 전환율 교차 분석
3주차 | {list(id_by_name)[min(3, len(id_by_name) - 1)]} | 전략 수립 및 문서화
4주차 | {list(id_by_name)[0]} | 검토·수정 후 최종 제출{revise_block}"""

    try:
        raw = (llm or GeminiClient()).generate(prompt)
        plan = _parse_plan(raw, id_by_name=id_by_name)
    except Exception:
        plan = []

    if not plan:
        if prev_todo_ids:
            # 수정 생성에 실패했으면 기존 계획을 지우지 않고 그대로 둔다.
            return "지금은 계획을 수정하지 못했어요. 잠시 후 다시 요청해 주시겠어요?"
        # 폴백: 첫 계획인데 LLM 실패 시 메시지 전체를 할 일 1개로.
        plan = [TaskIn(title=last_user_msg[:200] or "계획 정리", week_no=1)]

    # 교체: 미완료 할 일 삭제(완료된 할 일은 작업 기록이므로 보존).
    replaced = 0
    if prev_todo_ids:
        with session_factory() as session:
            rows = (
                session.execute(select(Task).where(Task.id.in_(prev_todo_ids)))
                .scalars()
                .all()
            )
            for t in rows:
                session.delete(t)
            replaced = len(rows)
            session.commit()

    tools["create_tasks"](workspace_id=workspace_id, tasks=plan)

    # 담당자가 안 정해진 할 일만 라운드로빈으로 채운다(정상 경로에선 LLM 이
    # 계획에서 직접 지정하므로, 여기는 구형식 출력·이름 매칭 실패의 폴백).
    with session_factory() as session:
        tasks_rows = (
            session.execute(
                select(Task)
                .where(Task.workspace_id == workspace_id)
                .order_by(Task.week_no.asc(), Task.id.asc())
            )
            .scalars()
            .all()
        )
        unassigned = [t for t in tasks_rows if t.assignee_id is None]
        for i, t in enumerate(unassigned):
            t.assignee_id = member_ids[i % len(member_ids)]
        session.flush()

        # 최종 배정 결과(담당자 이름 포함)로 응답을 만든다.
        entries = [
            (t.week_no, t.title, name_by_id.get(t.assignee_id))
            for t in tasks_rows
            if t.status != "done"
        ]

        # [S-01 STEP05] 배분받은 팀원(owner 제외)에게 알림 → 각자 화면에 자동 반영됨을 알린다.
        owner = session.get(User, owner_id)
        owner_name = owner.name if owner and owner.name else "팀장"
        for uid in member_ids[1:]:
            cnt = sum(1 for t in tasks_rows if t.assignee_id == uid)
            if cnt:
                _notify_members(
                    session,
                    workspace_id,
                    [uid],
                    (
                        f"{owner_name}님이 계획을 조정했어요 — 내 담당 {cnt}개"
                        if replaced
                        else f"{owner_name}님이 주차별 계획을 세우고 할 일을 나눴어요 — 내 담당 {cnt}개"
                    ),
                )
        session.commit()

    return _format_plan_reply(entries, replaced=replaced, kept_done=len(done_titles))


def _parse_plan(raw: str, *, id_by_name: dict[str, int] | None = None) -> list[TaskIn]:
    """LLM 출력("N주차 | 담당자 | 할 일")을 파싱해 TaskIn 리스트로 만든다.

    담당자 칸이 없는 구형식("N주차 | 할 일")이나 팀원과 매칭 안 되는 이름은
    ``assignee_id=None`` 으로 두고, 호출부의 라운드로빈 폴백이 채운다.
    """
    plan: list[TaskIn] = []
    for line in raw.splitlines():
        assignee_id = None
        m = re.match(r"^\s*(\d+)\s*주차\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", line)
        if m:
            week, assignee_raw, title = int(m.group(1)), m.group(2), m.group(3)
            if id_by_name:
                tokens = re.findall(r"[가-힣A-Za-z0-9]+", assignee_raw)
                if tokens:
                    assignee_id = id_by_name.get(tokens[0])
        else:
            m = re.match(r"^\s*(\d+)\s*주차\s*[|:\-–]\s*(.+?)\s*$", line)
            if not m:
                continue
            week, title = int(m.group(1)), m.group(2)
        title = title.strip(" -•*").strip()
        if title:
            plan.append(TaskIn(title=title[:200], week_no=week, assignee_id=assignee_id))
        if len(plan) >= 16:  # 폭주 방지
            break
    return plan


def _format_plan_reply(
    entries: list[tuple[int | None, str, str | None]],
    *,
    replaced: int = 0,
    kept_done: int = 0,
) -> str:
    """(주차, 제목, 담당자 이름) 목록을 주차별로 묶어 사람이 읽기 좋은 응답으로 만든다."""
    by_week: dict[int, list[str]] = {}
    for week, title, assignee in entries:
        line = f"- {title}" + (f" — {assignee}" if assignee else "")
        by_week.setdefault(week or 0, []).append(line)
    if replaced:
        head = f"기존 미완료 할 일 {replaced}개를 새 계획으로 교체했어요."
        if kept_done:
            head += f" (완료된 {kept_done}개는 그대로 뒀어요)"
    else:
        head = "주차별 계획을 워크스페이스에 저장했어요."
    lines = [head]
    for wk in sorted(by_week):
        lines.append(f"\n[{wk}주차]" if wk else "\n[기타]")
        lines.extend(by_week[wk])
    lines.append("\n조정하고 싶은 주차나 배분이 있나요? 말씀해 주시면 바로 반영할게요.")
    return "\n".join(lines)


def _load_deadline(
    workspace_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
):
    """워크스페이스에 연결된 공모전 마감일을 반환한다(없거나 실패 시 None)."""
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        contest_id = ws.contest_id if ws else None
    if contest_id is None:
        return None
    try:
        detail = tools["get_competition_detail"](contest_id)
        return getattr(detail, "deadline", None) if detail else None
    except Exception:  # noqa: BLE001 - 공모전 조회 실패해도 계획은 진행
        return None


def _handle_create_workspace(
    conversation_id: int,
    user_id: int,
    last_user_msg: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """대화에서 "워크스페이스 만들어줘" 요청을 받아 워크스페이스를 만들고
    현재 대화에 연결한다. (S-01 STEP03)

    - 이미 연결된 워크스페이스가 있으면 새로 만들지 않고 안내만 한다(멱등).
    - 메시지에 순번("1번으로 ...")이나 공모전 이름이 있으면, 직전 추천/검색 결과에서
      그 공모전을 찾아 연결한다(contest_id). 특정이 안 되면 공모전 미연결로 생성한다.
    - 팀원 초대·알림·섹션은 백엔드/다음 단계 몫이라, 여기선 소유자 1명 등록 +
      대화 연결까지만 책임진다.
    - 새 테이블/마이그레이션 없이 기존 Workspace/WorkspaceMember/Conversation 만 사용.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    # 메시지에 순번/이름이 있으면 직전 추천 목록에서 그 공모전을 찾는다.
    # "국가데이터 활용대회로 하자" → "워크스페이스 만들어 줘"처럼 선택이 앞 턴에
    # 있었던 경우까지 커버하도록 최근 선택 발화도 함께 본다.
    contest_id, contest_title, ambiguous = _extract_contest_with_context(
        last_user_msg, conversation_id, session_factory=session_factory, llm=llm
    )
    if ambiguous:
        return "어떤 공모전인지 정확히 특정하지 못했어요. 순번이나 공모전 이름으로 다시 말씀해 주시겠어요?"

    with session_factory() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            return "대화를 찾을 수 없어요. 잠시 후 다시 시도해 주세요."
        if conv.workspace_id is not None:
            ws = session.get(Workspace, conv.workspace_id)
            name = ws.name if ws else "워크스페이스"
            return f"이미 '{name}' 워크스페이스에 연결돼 있어요. 이어서 무엇을 도와드릴까요?"

        name = contest_title or _workspace_name_from(last_user_msg)
        ws = Workspace(name=name, owner_id=user_id, contest_id=contest_id)
        session.add(ws)
        session.flush()  # ws.id 확보
        session.add(
            WorkspaceMember(workspace_id=ws.id, user_id=user_id, role="owner")
        )
        conv.workspace_id = ws.id
        # [데모] "네 명이 참가한다" 가정 — 팀원(유진/채원/채은)을 자동 편성한다.
        member_ids = _ensure_team_members(session, ws.id, user_id)

        # [S-01 STEP03] 팀원(B·C·D, owner 제외)에게 새 워크스페이스 알림 발송.
        owner = session.get(User, user_id)
        owner_name = owner.name if owner and owner.name else "팀장"
        deadline = None
        if contest_id is not None:
            try:
                detail = build_registry()["get_competition_detail"](contest_id)
                deadline = getattr(detail, "deadline", None) if detail else None
            except Exception:  # noqa: BLE001 - 공모전 조회 실패해도 생성/알림은 진행
                deadline = None
        notify_text = f"{owner_name}님이 새 워크스페이스를 열었어요. {name}"
        if deadline:
            notify_text += f" · 마감 {deadline}"
        _notify_members(session, ws.id, member_ids[1:], notify_text)

        session.commit()

    linked = f"'{name}' 공모전에 맞춘 " if contest_id is not None else f"'{name}' "
    return (
        f"{linked}워크스페이스를 만들고 팀원들에게 알렸어요. "
        "주제를 잡으려면 팀원들의 경험·강점이 필요한데, 각자 어떤 걸 잘하는지 들려주시겠어요?"
    )


def _handle_workspace_edit(
    conversation_id: int,
    last_user_msg: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """이미 연결된 워크스페이스의 이름 또는 연결된 공모전을 바꾼다.

    이름 변경은 LLM으로 새 이름만 뽑고, 공모전 변경은 ``_extract_contest`` 를
    그대로 재사용한다(추천 목록에서 순번/이름으로 워크스페이스를 만들 때와
    동일한 메커니즘 — id는 사용자에게 노출하지 않는다). 둘 다 못 찾으면
    무엇을 바꾸고 싶은지 되묻고, 아무것도 바꾸지 않는다.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        # 워크스페이스가 없는데 메시지가 공모전을 가리키면(LLM 이 선택 발화를 wsedit
        # 으로 오분류한 경우 등) 거절 대신 생성을 제안한다.
        offer = _handle_select(
            conversation_id, last_user_msg, session_factory=session_factory, llm=llm
        )
        if offer is not None:
            return offer
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    new_name = _extract_new_workspace_name(last_user_msg, llm=llm)
    contest_id, contest_title, ambiguous = _extract_contest(
        last_user_msg, conversation_id, session_factory=session_factory
    )
    if new_name is None and contest_id is None and not ambiguous:
        # "지금 공모전 연결해줘"처럼 지시어만 있는 요청은 규칙(순번/이름)으로 못
        # 푼다 — 최근 대화에서 다루던 공모전을 LLM 으로 해석한다.
        history = load_history(conversation_id, session_factory=session_factory)
        contest_id, contest_title, ambiguous = _resolve_contest_by_llm(
            last_user_msg, conversation_id, history,
            llm=llm, session_factory=session_factory,
        )
    if ambiguous:
        return "어떤 공모전으로 바꿀지 정확히 특정하지 못했어요. 순번이나 공모전 이름으로 다시 말씀해 주시겠어요?"
    if new_name is None and contest_id is None:
        return "무엇을 바꾸고 싶으신가요? 새 이름이나 연결할 공모전(순번/이름)을 말씀해 주세요."

    changes: list[str] = []
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        if ws is None:
            return "워크스페이스를 찾을 수 없어요."

        if new_name:
            changes.append(f"이름: '{ws.name}' → '{new_name}'")
            ws.name = new_name
        if contest_id is not None:
            changes.append(f"연결된 공모전: '{contest_title}'")
            ws.contest_id = contest_id

        member_ids = (
            session.execute(
                select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
            )
            .scalars()
            .all()
        )
        notify_text = "워크스페이스 설정이 변경됐어요 — " + ", ".join(changes)
        _notify_members(session, workspace_id, list(member_ids), notify_text)

        session.commit()

    return "워크스페이스를 수정했어요 — " + ", ".join(changes) + ". 팀원들에게 알림도 보냈어요."


def _extract_new_workspace_name(text: str, *, llm: LLMClient | None = None) -> str | None:
    """메시지에서 워크스페이스에 붙이고 싶어하는 새 이름을 뽑는다. 없으면 None."""
    try:
        result = (llm or GeminiClient()).generate(
            f"다음 메시지가 워크스페이스 '이름'을 바꿔 달라는 요청인지 판단하세요.\n"
            f'"공모전으로 바꿔줘/연결해줘/변경해줘"처럼 어떤 공모전에 연결할지에 대한 '
            f'요청은 이름 변경이 아닙니다 — 그런 경우 반드시 \'없음\'을 반환하세요.\n'
            f"이름 변경 요청이 확실할 때만 그 새 이름을 반환하세요(따옴표·설명 없이).\n\n"
            f'예시 1) "이름을 KOSAC 준비팀으로 바꿔줘" → KOSAC 준비팀\n'
            f'예시 2) "1번 공모전으로 다시 연결해줘" → 없음 (이건 공모전 변경이지 이름 변경이 아님)\n'
            f'예시 3) "공모전 바꿔줘" → 없음\n\n'
            f'메시지: "{text}"\n'
            f"이름:"
        )
    except Exception:
        return None
    name = result.strip().strip("'\"")
    if not name or name == "없음":
        return None
    return name[:200]


def _handle_select(
    conversation_id: int,
    last_user_msg: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str | None:
    """추천 목록에서 하나를 고르는 발화("1번으로 할게")를 받아 다음 행동을 제안한다.

    예전엔 이런 선택 발화가 어떤 인텐트에도 안 걸려 study 로 새면서 워크스페이스
    생성으로 이어지지 못했다(생성 트리거 공백). 여기서 선택을 확인해 주고
    워크스페이스 생성(또는 이미 있으면 공모전 재연결)을 제안한다. 실제 실행은
    사용자가 수락하면 ``_accepted_offer_intent`` 가 workspace/wsedit 으로 잇는다.

    Returns:
        답변 텍스트. 참조할 추천 목록 자체가 없으면 None (호출부가 study 폴백).
    """
    # 주제 후보 목록이 추천 목록보다 최신이면 이 선택은 공모전이 아니라 주제 확정이다.
    if _topic_is_latest(conversation_id, session_factory=session_factory):
        return (
            "좋아요, 그 주제로 확정할게요. 이제 마감까지의 주차별 계획을 짜 볼까요? "
            "팀원별 역할 분담까지 같이 정리해 드려요."
        )

    contest_id, contest_title, ambiguous = _extract_contest(
        last_user_msg, conversation_id, session_factory=session_factory
    )
    if contest_id is None and not ambiguous:
        # "이걸로 할게"처럼 지시어만 있는 선택은 규칙으로 못 푼다 — 대화 맥락으로 해석.
        history = load_history(conversation_id, session_factory=session_factory)
        contest_id, contest_title, ambiguous = _resolve_contest_by_llm(
            last_user_msg, conversation_id, history,
            llm=llm, session_factory=session_factory,
        )
    if ambiguous:
        return "몇 번을 고르신 건지 정확히 모르겠어요. 순번이나 공모전 이름으로 다시 말씀해 주시겠어요?"
    if contest_id is None:
        return None

    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            f"'{contest_title}'로 정하셨네요, 좋은 선택이에요. "
            "팀원들과 준비를 시작하도록 이 공모전으로 워크스페이스를 만들까요?"
        )

    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        ws_name = ws.name if ws else "워크스페이스"
        already_linked = ws is not None and ws.contest_id == contest_id
    if already_linked:
        return f"'{contest_title}'는 이미 '{ws_name}' 워크스페이스에 연결돼 있어요. 이어서 무엇을 도와드릴까요?"
    return (
        f"'{contest_title}'로 정하셨네요. "
        f"지금 '{ws_name}' 워크스페이스의 공모전을 이걸로 바꿔 연결할까요?"
    )


def _topic_is_latest(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """이 대화에서 주제 후보(topic)가 추천 목록(recommend)보다 나중에 제시됐는지."""
    history = load_history(conversation_id, session_factory=session_factory)
    latest = next(
        (m.role for m in reversed(history) if m.role in ("topic", "recommend")), None
    )
    return latest == "topic"


def _handle_workspace_info(
    conversation_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """연결된 워크스페이스의 현황(공모전·팀원·할 일 진행)을 요약해 보여준다."""
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 이 대화에 연결된 워크스페이스가 없어요. "
            "공모전을 추천받아 고르시면 바로 만들어 드릴게요 — 어떤 분야에 관심 있으세요?"
        )

    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        if ws is None:
            return "워크스페이스를 찾을 수 없어요. 잠시 후 다시 시도해 주세요."
        ws_name = ws.name
        members = session.execute(
            select(User.name)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.id.asc())
        ).scalars().all()
        tasks_rows = session.execute(
            select(Task.status).where(Task.workspace_id == workspace_id)
        ).scalars().all()

    contest = _load_contest_brief(workspace_id, tools, session_factory=session_factory)
    if contest is not None:
        deadline = getattr(contest, "deadline", None)
        contest_line = f"{contest.title}" + (f" (마감 {deadline})" if deadline else "")
    else:
        contest_line = "아직 연결 안 됨"

    total = len(tasks_rows)
    done = sum(1 for s in tasks_rows if s == "done")
    task_line = (
        f"{done}/{total}개 완료 ({round(done / total * 100)}%)" if total else "아직 없음"
    )

    lines = [
        f"'{ws_name}' 워크스페이스 현황이에요.",
        f"- 공모전: {contest_line}",
        f"- 팀원 {len(members)}명: {', '.join(members)}" if members else "- 팀원: 아직 없음",
        f"- 할 일: {task_line}",
        "",
        "이름을 바꾸거나 다른 공모전으로 다시 연결할 수도 있어요. 조정할 게 있나요?",
    ]
    return "\n".join(lines)


def _notify_members(
    session: Session,
    workspace_id: int,
    recipient_ids: list[int],
    text: str,
) -> None:
    """수신자들에게 알림(role="notify")을 남긴다. 각자의 워크스페이스 대화(없으면 생성)에 저장.

    api.workspaces.service.create_notification 과 같은 방식(스키마 재사용). 수신자가
    채팅/워크스페이스에 입장하면 GET /notifications 로 조회돼 토스트로 뜬다.
    """
    for uid in recipient_ids:
        conv = (
            session.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.user_id == uid,
                )
                .order_by(Conversation.id.asc())
            )
            .scalars()
            .first()
        )
        if conv is None:
            conv = Conversation(user_id=uid, workspace_id=workspace_id)
            session.add(conv)
            session.flush()
        session.add(
            Message(
                conversation_id=conv.id,
                role="notify",
                content=json.dumps({"text": text, "read": False}, ensure_ascii=False),
            )
        )


_ORDINAL_WORDS = {"첫번째": 1, "첫": 1, "두번째": 2, "세번째": 3, "네번째": 4, "다섯번째": 5}


def _extract_contest(
    text: str,
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[int | None, str | None, bool]:
    """직전 추천/검색 결과에서 순번 또는 이름으로 공모전을 찾아 (contest_id, 제목, 모호함여부)를 반환한다.

    사용자에게는 DB 고유번호(PK)를 노출하지 않으므로("1. OO공모전"처럼 순번만 보여줌),
    "12번으로"처럼 메시지 속 숫자를 그대로 PK로 쓰던 예전 방식은 더 이상 쓸 수 없다.
    대신 ``competition_agent.save_recommend_list`` 가 남긴 순번↔id↔제목 기록을 읽어서,
    (i) "1번"/"첫번째" 같은 순번 표현, (ii) 공모전 이름과의 단어 겹침으로 실제 id를 찾는다.

    - 참조 시도 자체가 없으면(추천 기록이 없거나 순번/이름 어느 쪽도 못 찾음) →
      (None, None, False) — 무리하게 추측하지 않고 공모전 미연결로 진행.
    - 순번을 댔는데 범위를 벗어나면(예: 목록엔 3개인데 "5번") → (None, None, True) —
      잘못 짚은 게 분명하므로 워크스페이스를 만들지 않고 다시 물어봐야 한다.
    """
    entries = competition_agent.load_latest_recommend_list(
        conversation_id, session_factory=session_factory
    )
    if not entries:
        return None, None, False

    ordinal_match = re.search(r"([1-9])\s*번", text)
    if ordinal_match:
        n = int(ordinal_match.group(1))
        if 1 <= n <= len(entries):
            entry = entries[n - 1]
            return entry["id"], entry["title"], False
        return None, None, True

    # "두 번째"처럼 표준 띄어쓰기가 들어오면 "두번째" 키에 안 걸리므로,
    # 공백을 걷어낸 문자열 기준으로 매칭한다.
    compact = text.replace(" ", "")
    for word, n in _ORDINAL_WORDS.items():
        if word in compact and n <= len(entries):
            entry = entries[n - 1]
            return entry["id"], entry["title"], False

    # 제목 단어가 메시지 안에 "부분문자열"로 있는지 센다. 토큰 집합 교집합 방식은
    # "국가데이터 활용대회로 하자"처럼 조사가 붙으면("활용대회로") 매칭이 깨진다.
    best, best_score = None, 0
    for entry in entries:
        title_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", entry["title"]))
        overlap = sum(1 for tok in title_tokens if tok in text)
        if overlap > best_score:
            best, best_score = entry, overlap
    if best is not None:
        return best["id"], best["title"], False

    return None, None, False


def _extract_contest_with_context(
    text: str,
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> tuple[int | None, str | None, bool]:
    """현재 메시지에서 공모전을 못 찾으면 최근 대화 맥락까지 동원해 찾는다.

    1차(규칙): 현재 메시지의 순번/제목 → 과거 선택 발화("국가데이터 활용대회로
    하자")의 순번/제목. 명확한 발화는 LLM 없이 결정적으로 처리한다.
    2차(LLM): "아니 이거 준비하려고 하는데 워크스페이스 만들어줘"처럼 지시어로만
    가리키는 발화는 규칙으로 못 푼다. 최근 대화와 추천 목록을 LLM에 주고 무엇을
    가리키는지 해석시킨다(``_resolve_contest_by_llm``). LLM 실패 시 미연결 폴백.
    """
    result = _extract_contest(text, conversation_id, session_factory=session_factory)
    if result[0] is not None or result[2]:
        return result

    history = load_history(conversation_id, session_factory=session_factory)
    user_msgs = [m.content for m in history if m.role == "user"]
    for msg in reversed(user_msgs[-5:]):
        if msg == text:
            continue
        if _classify_intent_by_keyword(msg)["intent"] != "select":
            continue
        rid, rtitle, ambiguous = _extract_contest(
            msg, conversation_id, session_factory=session_factory
        )
        if rid is not None and not ambiguous:
            return rid, rtitle, False

    return _resolve_contest_by_llm(
        text, conversation_id, history, llm=llm, session_factory=session_factory
    )


def _resolve_contest_by_llm(
    text: str,
    conversation_id: int,
    history: list[MessageOut],
    *,
    llm: LLMClient | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[int | None, str | None, bool]:
    """"이거/그 대회" 같은 지시 표현이 가리키는 공모전을 최근 대화 맥락으로 해석한다.

    추천/검색 기록(순번↔id↔제목)에 있는 공모전만 후보로 준다 — 목록 밖 id 를
    답하면(환각) 버린다. LLM 호출 실패 시 (None, None, False) 로 조용히 폴백해
    기존 규칙 기반 흐름과 동일하게 동작한다.

    Returns:
        (contest_id, 제목, 모호함여부). 대화에 근거가 없으면 (None, None, False),
        여러 개와 헷갈리면 (None, None, True) — 호출부가 되묻는다.
    """
    entries = competition_agent.load_latest_recommend_list(
        conversation_id, session_factory=session_factory
    )
    if not entries:
        return None, None, False

    recent = [m for m in history if m.role in ("user", "assistant")][-8:]
    convo = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content[:300]}"
        for m in recent
    )
    listing = "\n".join(f"- id={e['id']}: {e['title']}" for e in entries)
    prompt = f"""아래는 공모전 도우미와 사용자의 최근 대화, 그리고 대화에서 다뤄진 공모전 목록입니다.
사용자의 마지막 메시지가 목록 중 어느 공모전을 가리키는지 판단하세요.
"이거", "그 대회", "아까 그거"처럼 지시어만 있으면 직전 대화에서 다루던 공모전을 뜻합니다.

[공모전 목록]
{listing}

[최근 대화]
{convo}

[사용자의 마지막 메시지]
{text}

규칙:
- 가리키는 공모전이 분명하면 그 id 숫자 하나만 출력하세요.
- 대화에 근거가 없거나 어떤 공모전도 가리키지 않으면 '없음'만 출력하세요.
- 두 개 이상 중 무엇인지 확실하지 않으면 '모호'만 출력하세요.

답:"""

    try:
        raw = (llm or GeminiClient()).generate(prompt).strip()
    except Exception:  # noqa: BLE001 - LLM 실패 시 규칙 기반 결과(미연결)로 폴백
        return None, None, False

    if "모호" in raw:
        return None, None, True
    id_match = re.search(r"\d+", raw)
    if id_match is None:
        return None, None, False
    cid = int(id_match.group())
    entry = next((e for e in entries if e["id"] == cid), None)
    if entry is None:
        return None, None, False
    return entry["id"], entry["title"], False


def _workspace_name_from(text: str) -> str:
    """사용자 메시지에서 워크스페이스 이름을 추출한다. 뚜렷한 이름이 없으면 기본값.

    "워크스페이스 만들어줘"처럼 요청어만 있는 경우가 대부분이라, 요청 표현을
    걷어내고 남는 게 충분하지 않으면 기본 이름을 쓴다. (룰 기반 1단계)
    """
    cleaned = text.strip()
    for phrase in ("워크스페이스 만들어줘", "워크스페이스 만들어", "워크스페이스 생성해줘",
                   "워크스페이스 만들", "워크스페이스 생성", "워크스페이스 열어줘",
                   "작업공간 만들어줘", "만들어줘", "만들어", "생성해줘"):
        cleaned = cleaned.replace(phrase, "")
    cleaned = cleaned.strip(" '\"·-:,")
    return cleaned[:200] if len(cleaned) >= 2 else "새 워크스페이스"


# 부분 저장("이 부분만")·병합("합쳐줘") 요청을 구분하는 수식어. (S-02 STEP02 케이스)
_PARTIAL_SAVE_MARKERS = ("이 부분만", "이것만", "여기만", "요 부분만", "부분만 저장")
_MERGE_MARKERS = ("합쳐", "합치", "병합")
# 부분 저장 범위를 되묻는 질문. _CONTINUATION_MARKERS("어느 부분부터 어느 부분까지
# 저장할까요" → log)와 짝이므로 문구를 바꾸면 거기도 같이 바꿔야 한다.
_RANGE_QUESTION = (
    "네, 어느 부분부터 어느 부분까지 저장할까요? "
    "예: '데이터 수집 얘기부터 SNS 분석까지'처럼 알려주세요."
)


def _handle_log(
    conversation_id: int,
    user_id: int,
    last_user_msg: str = "",
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """오늘 진행한 작업 대화를 요약해 실행 로그(``Message(role="log")``)로 저장하고,
    내용과 관련된 할 일(Task)을 완료 처리한다. (S-02 STEP02)

    - "이 부분만 저장해줘" → 저장하지 않고 범위를 되묻는다. 범위 답변은
      ``_CONTINUATION_MARKERS`` 가 다시 log 로 이어준다.
    - "지난번에 저장한 거랑 합쳐줘" → 이전 로그와 병합한 미리보기를 보여주고
      확정("이대로 저장할까요?" → logmerge)을 기다린다.
    - 요약/키워드 생성은 LLM. 실패 시 최근 사용자 발화로 폴백.
    - 요약 대상은 "마지막 실행 로그 저장 이후"의 대화만(지난 저장분 중복 방지).
    - 완료 처리는 겹침이 뚜렷한(단어 2개 이상) todo Task 만 자동으로, 애매하면
      되묻는다("완료 처리할까요?" → taskdone).
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    # 부분 저장 요청인데 범위를 모르면 먼저 묻는다(전체를 덜컥 저장하지 않는다).
    if any(k in last_user_msg for k in _PARTIAL_SAVE_MARKERS):
        return _RANGE_QUESTION

    history = load_history(conversation_id, session_factory=session_factory)
    # 직전에 범위를 물었다면 이번 메시지가 그 범위 지정이다.
    last_assistant = next(
        (m.content for m in reversed(history) if m.role == "assistant"), ""
    )
    range_spec = (
        last_user_msg
        if "어느 부분부터 어느 부분까지 저장할까요" in last_assistant
        else None
    )

    convo = _convo_since_last_log(history)
    if not convo:
        return "저장할 작업 내용이 없어요. 먼저 오늘 한 작업을 이야기해 주세요."

    summary = _summarize_convo(convo, range_spec=range_spec, llm=llm)

    if session_factory is None:
        session_factory = _default_session_factory()

    merge_note = ""
    if any(k in last_user_msg for k in _MERGE_MARKERS):
        preview = _prepare_log_merge(
            conversation_id, summary, session_factory=session_factory, llm=llm
        )
        if preview is not None:
            return preview
        # 합칠 이전 로그가 없으면 새 로그로 저장하되 그 사실을 알린다.
        merge_note = "이전에 저장한 로그가 없어서 새 로그로 저장했어요.\n\n"

    completed_title: str | None = None
    confirm_title: str | None = None
    with session_factory() as session:
        todos = (
            session.execute(
                select(Task).where(
                    Task.workspace_id == workspace_id, Task.status == "todo"
                )
            )
            .scalars()
            .all()
        )
        best, score = _best_matching_task(summary, todos)
        # 로그 헤더로 쓸 제목: 완료 처리되는 할 일 제목(없으면 "작업 기록").
        # 실행 로그는 "제목: ...\n요약: ...\n키워드: ..." 형태로 저장한다(작성자·날짜는
        # 메시지 메타에서 읽으므로 content 엔 안 넣는다).
        log_title = best.title if best is not None and score >= 2 else "작업 기록"
        session.add(
            Message(
                conversation_id=conversation_id,
                role="log",
                content=f"제목: {log_title}\n{summary}",
            )
        )
        if best is not None and score >= 2:
            # 겹침이 뚜렷할 때만 자동 완료. 단어 1개 겹침은 오매칭이 잦아 되묻는다.
            best.status = "done"
            completed_title = best.title
        elif best is not None and score == 1:
            confirm_title = best.title
        session.commit()

    reply = merge_note + "오늘 작업을 실행 로그에 저장했어요.\n\n" + summary
    if completed_title:
        reply += f"\n\n✅ 관련 할 일 완료 처리: {completed_title}"
    elif confirm_title:
        reply += f"\n\n혹시 '{confirm_title}' 할 일에 해당하는 작업이었나요? 맞으면 완료 처리할까요?"
    return reply


def _convo_since_last_log(history: list[MessageOut]) -> list[MessageOut]:
    """마지막 실행 로그 저장 이후의 user/assistant 대화만 골라낸다(요약 대상 범위).

    로그를 저장한 적이 없으면 전체에서 최근 20개. 마지막 user 메시지(= "저장해줘"
    명령 자체)는 요약 대상에서 제외한다.
    """
    last_log_idx = next(
        (i for i in range(len(history) - 1, -1, -1) if history[i].role == "log"), -1
    )
    convo = [
        m
        for m in history[last_log_idx + 1:]
        if m.role in ("user", "assistant") and m.content.strip()
    ]
    if convo and convo[-1].role == "user":
        convo = convo[:-1]
    return convo[-20:]


def _summarize_convo(
    convo: list[MessageOut],
    *,
    range_spec: str | None = None,
    llm: LLMClient | None = None,
) -> str:
    """작업 대화를 "요약: ...\\n키워드: ..." 형식으로 요약한다. LLM 실패 시 발화 폴백."""
    convo_text = "\n".join(f"{m.role}: {m.content}" for m in convo)
    range_block = (
        f"\n\n중요: 사용자가 지정한 구간만 요약하세요 — \"{range_spec}\". "
        "이 구간에 해당하지 않는 내용은 요약과 키워드에 넣지 마세요."
        if range_spec
        else ""
    )
    prompt = f"""아래는 공모전 팀원이 오늘 진행한 작업 대화입니다.
핵심 내용을 요약하고 키워드를 뽑아, 아래 형식으로만 출력하세요(다른 말 금지).
"팀원이 실제로 수행한 작업"만 요약하세요 — 저장 완료 안내, 계획 목록 출력, 워크스페이스
설정 같은 시스템·어시스턴트 발화는 요약과 키워드에 넣지 마세요.

요약: <오늘 한 작업의 핵심 2~3문장>
키워드: #키워드1 #키워드2 #키워드3{range_block}

작업 대화:
{convo_text}"""

    try:
        return (llm or GeminiClient()).generate(prompt).strip()
    except Exception:
        recent = [m.content for m in convo if m.role == "user"][-3:]
        return "요약: " + " / ".join(recent)[:300] if recent else "요약: (내용 없음)"


def _load_latest_message(
    session: Session, conversation_id: int, role: str
) -> Message | None:
    """이 대화에서 해당 role 의 가장 최근 메시지를 반환한다."""
    return (
        session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role == role)
            .order_by(Message.id.desc())
        )
        .scalars()
        .first()
    )


def _prepare_log_merge(
    conversation_id: int,
    summary: str,
    *,
    session_factory: Callable[[], Session],
    llm: LLMClient | None = None,
) -> str | None:
    """이전 로그와 이번 요약을 병합한 미리보기를 만들어 확정을 기다린다. (S-02 STEP02)

    병합 결과는 ``role="log_draft"`` 로 저장해 두고, 사용자가 "응"으로 수락하면
    ``_handle_log_merge_confirm`` 이 기존 로그를 이 내용으로 교체한다.

    Returns:
        미리보기 응답 텍스트. 합칠 이전 로그가 없으면 None(호출부가 일반 저장 폴백).
    """
    with session_factory() as session:
        prev = _load_latest_message(session, conversation_id, "log")
    if prev is None:
        return None

    merge_prompt = f"""아래 [기존 실행 로그]와 [새 작업 요약]을 하나의 실행 로그로 병합하세요.
중복 내용은 합치고, 새 내용은 빠짐없이 반영하세요. 아래 형식으로만 출력하세요(다른 말 금지).

제목: <병합된 로그 제목 한 줄>
요약: <병합된 핵심 2~4문장>
키워드: #키워드1 #키워드2 #키워드3

[기존 실행 로그]
{prev.content}

[새 작업 요약]
{summary}"""
    try:
        merged = (llm or GeminiClient()).generate(merge_prompt).strip()
    except Exception:
        merged = f"{prev.content}\n\n[추가 내용]\n{summary}"

    with session_factory() as session:
        session.add(
            Message(conversation_id=conversation_id, role="log_draft", content=merged)
        )
        session.commit()

    return (
        "이전 로그와 합친 미리보기예요.\n\n"
        f"{merged}\n\n"
        "이대로 저장할까요? 고치고 싶은 부분이 있으면 말씀해 주세요."
    )


def _handle_log_merge_confirm(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """병합 미리보기("이대로 저장할까요?")를 수락하면 기존 로그를 병합본으로 교체한다."""
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        draft = _load_latest_message(session, conversation_id, "log_draft")
        if draft is None:
            return "저장 대기 중인 병합 내용이 없어요. '오늘 작업 저장해줘'처럼 다시 요청해 주시겠어요?"
        prev = _load_latest_message(session, conversation_id, "log")
        if prev is not None:
            prev.content = draft.content
            session.delete(draft)
        else:
            draft.role = "log"  # 교체할 원본이 없으면 병합본을 그대로 로그로 승격.
        session.commit()
    return "병합한 내용으로 실행 로그를 업데이트했어요. 이어서 진행할 작업이 있나요?"


def _handle_taskdone(
    conversation_id: int,
    history: list[MessageOut],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """"'OO' 할 일 완료 처리할까요?" 제안을 수락하면 그 할 일을 done 으로 바꾼다."""
    last_assistant = next(
        (m.content for m in reversed(history) if m.role == "assistant"), ""
    )
    m = re.search(r"'([^']+)' 할 일", last_assistant)
    if m is None:
        return "어떤 할 일을 완료 처리할지 찾지 못했어요. 할 일 이름을 말씀해 주시겠어요?"
    return _complete_task_by_title(
        conversation_id, m.group(1), session_factory=session_factory
    )


def _best_matching_task(text: str, tasks: list) -> tuple[Task | None, int]:
    """로그 내용과 제목이 가장 많이 겹치는 todo Task 와 겹친 단어 수를 반환한다.

    겹침 판단(자동 완료/되묻기/무시)은 호출부 몫이라 점수를 함께 돌려준다.
    """
    words = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", text))
    best, best_score = None, 0
    for t in tasks:
        overlap = len(words & set(re.findall(r"[가-힣A-Za-z0-9]{2,}", t.title)))
        if overlap > best_score:
            best, best_score = t, overlap
    return best, best_score


def _handle_wrapup() -> str:
    """오늘 작업을 마무리하는 발화("오늘은 여기까지만 할게")에 저장을 제안한다. (S-02 STEP01)

    "실행 로그에 저장해 드릴까요" 는 ``_OFFER_MARKERS`` (→ log)와 짝이라,
    "응" 수락이 바로 ``_handle_log`` 저장으로 이어진다.
    """
    return (
        "오늘도 수고하셨어요. 지금까지 진행한 내용을 실행 로그에 저장해 드릴까요? "
        "다음에 이어서 하실 거면 저장 없이 마무리해도 괜찮아요."
    )


def _handle_share(
    conversation_id: int,
    user_id: int,
    last_user_msg: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """작업 요약을 워크스페이스(전체 공개) 대신 특정 팀원에게만 전달한다. (S-02 STEP02)

    "저장 말고 C한테만 공유해줘" — 실행 로그(role="log")는 남기지 않고, 수신자의
    워크스페이스 대화에 요약 메시지를 넣은 뒤 알림(toast)까지 보낸다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어서 공유할 팀원을 찾을 수 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    if session_factory is None:
        session_factory = _default_session_factory()

    with session_factory() as session:
        rows = (
            session.execute(
                select(User)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(WorkspaceMember.workspace_id == workspace_id)
            )
            .scalars()
            .all()
        )
        sender = session.get(User, user_id)
        sender_name = (sender.name if sender and sender.name else "팀원")
        members = [(u.id, u.name or u.email) for u in rows if u.id != user_id]

    # 수신자 특정: 표시 이름의 첫 토큰("동영 (팀장)" → "동영")이 메시지에 있는 팀원.
    matches = [
        (uid, name)
        for uid, name in members
        if (name or "").split() and (name or "").split()[0] in last_user_msg
    ]
    if len(matches) != 1:
        names = ", ".join(name for _, name in members) or "(아직 없음)"
        return (
            f"누구에게 공유할까요? 지금 워크스페이스 팀원은 {names}이에요. "
            "이름을 말씀해 주시면 그분에게만 전달할게요."
        )
    recipient_id, recipient_name = matches[0]

    history = load_history(conversation_id, session_factory=session_factory)
    convo = _convo_since_last_log(history)
    if not convo:
        return "공유할 작업 내용이 없어요. 먼저 오늘 한 작업을 이야기해 주세요."
    summary = _summarize_convo(convo, llm=llm)

    with session_factory() as session:
        # 수신자의 워크스페이스 대화(없으면 생성)에 공유 메시지를 넣는다(_notify_members 와 동일 규약).
        conv = (
            session.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.user_id == recipient_id,
                )
                .order_by(Conversation.id.asc())
            )
            .scalars()
            .first()
        )
        if conv is None:
            conv = Conversation(user_id=recipient_id, workspace_id=workspace_id)
            session.add(conv)
            session.flush()
        session.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content=f"📩 {sender_name}님이 작업 내용을 공유했어요.\n\n{summary}",
            )
        )
        _notify_members(
            session,
            workspace_id,
            [recipient_id],
            f"{sender_name}님이 작업 내용을 공유했어요 — 채팅에서 확인해 보세요",
        )
        session.commit()

    return (
        f"{recipient_name}님에게만 공유했어요. 워크스페이스 실행 로그에는 저장하지 않았어요.\n\n"
        f"{summary}\n\n"
        "다른 팀원에게도 공유할 내용이 있나요?"
    )


def _handle_topic(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """대화에 쌓인 팀원 배경을 종합해 공모전 주제 후보를 제안한다. (S-01 STEP04)

    입력은 이 대화의 사용자 발화들(팀원들이 남긴 관심사·경험·강점)이다.
    생성한 주제 후보는 "주제 후보 섹션"에 해당하는 ``Message(role="topic")`` 로
    저장한다(구조화 컬럼 없이 content 텍스트로 — 새 테이블/마이그레이션 없음).

    심사 기준 대비 적합도·수상 사례 비교는 competition-agent 도구가 필요한 부분이라
    여기(1단계)선 팀원 배경 기반 후보 생성까지만 책임진다.
    """
    history = load_history(conversation_id, session_factory=session_factory)
    # 팀원 배경만 모은다. "워크스페이스 만들어줘"·"주제 제안해줘" 같은 명령 메시지는
    # 배경이 아니므로 제외한다(키워드 분류가 배경/일반 진술인 것만 = 명령성 발화 제외).
    backgrounds = "\n".join(
        f"- {m.content}"
        for m in history
        if m.role == "user"
        and m.content.strip()
        and _classify_intent_by_keyword(m.content)["intent"] in ("study", "background")
    )
    if not backgrounds:
        return (
            "주제 후보를 제안하려면 팀원들의 관심사·경험·강점을 먼저 알려주세요. "
            "예: '나는 데이터 분석 경험이 있어', '나는 브랜드 포지셔닝을 많이 봤어'"
        )

    prompt = f"""당신은 공모전 팀의 주제 기획을 돕는 코치입니다.
아래는 팀원들이 대화에서 남긴 배경·관심사·강점입니다.

{backgrounds}

이 팀에 잘 맞는 공모전 주제 후보를 정확히 2개 제안하세요.
각 후보는 다음 형식으로, 다른 설명 없이 작성하세요.

주제 후보 ①: <제목>
- 근거: <어떤 팀원의 어떤 강점이 이 주제에 어떻게 기여하는지 1~2문장>

주제 후보 ②: <제목>
- 근거: <위와 동일>"""

    try:
        client = llm or GeminiClient()
        candidates = client.generate(prompt).strip()
    except Exception:
        # LLM 실패 시에도 대화가 죽지 않도록 폴백 안내.
        return "지금은 주제 후보를 생성하지 못했어요. 잠시 후 다시 시도해 주세요."

    # 주제 후보를 role="topic" 으로 기록(주제 후보 섹션).
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="topic",
                content=candidates,
            )
        )
        session.commit()

    # 후보만 던지고 끝내지 않고 사용자의 선택을 끌어낸다(참여 유도).
    return (
        f"{candidates}\n\n"
        "둘 중 어느 쪽이 더 끌리나요? 좁히거나 두 후보를 섞어서 다시 제안할 수도 있어요."
    )


def _handle_background(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """팀원이 자기 배경(경험·관심·강점)을 소개하면 인정하고 주제 제안으로 이어지게 안내한다.

    배경 텍스트는 이미 일반 user 메시지로 저장돼 있어 _handle_topic 이 그대로 읽는다.
    여기선 별도 저장 없이, 지금까지 모인 배경 수를 세어 자연스러운 응답만 돌려준다.
    (S-01 STEP04 의 팀원 배경 수집 단계)
    """
    history = load_history(conversation_id, session_factory=session_factory)
    gathered = sum(
        1
        for m in history
        if m.role == "user"
        and m.content.strip()
        and _classify_intent_by_keyword(m.content)["intent"] in ("study", "background")
    )
    if gathered >= 3:
        return (
            f"기억해뒀어요. 배경이 {gathered}개 모여서 주제를 잡기에 충분해요. "
            "지금까지 모인 강점으로 주제 후보를 제안해 볼까요?"
        )
    return (
        f"기억해뒀어요. (지금까지 배경 {gathered}개) "
        "다른 팀원들은 어떤 경험이나 강점이 있나요?"
    )


def _handle_recommend(
    history: list[MessageOut],
    last_user_msg: str,
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """관심분야·참여형태·목표를 단계적으로 파악해 공모전을 추천한다. (S-01 STEP01)

    시맨틱 검색 → 구조화 필터 적용 → 부족하면 전체 검색 → 그래도 없으면 웹 검색 순으로
    폴백한다. DB에서 찾은 결과는 사용자에게 순번(1. 2. 3. ...)으로만 보여주고, 실제
    DB 고유번호는 노출하지 않는다 — 대신 ``Message(role="recommend")`` 로 순번↔id↔제목
    매핑을 저장해, 이후 "1번으로 워크스페이스 만들어줘" 같은 요청을 해석할 수 있게 한다.
    """
    # 마감 여유를 원하는 재검색("마감 촉박한데 다른 거 없어?")인데 필요한 준비 기간을
    # 모르면, 검색 대신 기간부터 되묻는다(S-01 STEP01 케이스). 사용자의 답변은
    # _CONTINUATION_MARKERS 가 다시 recommend 로 이어준다.
    if ("촉박" in last_user_msg or "여유" in last_user_msg) and not re.search(
        r"\d|[일이삼사오]\s*(?:주|달|개월)|한\s*달", last_user_msg
    ):
        return (
            "준비 기간이 얼마나 필요해요? '3주는 필요해'처럼 알려주시면 "
            "그 기간을 확보할 수 있는 공모전으로 다시 찾아볼게요."
        )

    prev_entries = competition_agent.load_latest_recommend_list(
        conversation_id, session_factory=session_factory
    )
    # "상금 더 큰 거" 같은 상대 조건을 절대값으로 환산할 기준(직전 목록의 1등 상금 최댓값).
    max_known_prize = max(
        (e.get("first_prize_amount") or 0 for e in prev_entries), default=0
    ) or None
    user_msgs = [m.content for m in history if m.role == "user"]
    search_keyword, filters = extract_keyword_and_filters(
        user_msgs, max_known_prize=max_known_prize
    )
    # "다른/비슷한 거 보여줘" 재검색이면 직전에 보여준 공모전은 결과에서 제외한다.
    exclude_ids = (
        [e["id"] for e in prev_entries]
        if prev_entries
        and any(k in last_user_msg for k in ("다른", "비슷", "말고"))
        else None
    )
    db_results: list | None = None  # role="recommend" 저장은 LLM 응답 생성 후 마지막에(경쟁조건 방지)

    if not search_keyword:
        # 관심 분야가 아직 파악 안 됐으면 검색 자체를 생략하고, LLM이 요구사항부터
        # 질문하게 한다(정보 없이 아무 공모전 목록이나 던지는 것 방지).
        tool_context = (
            "\n\n[검색 미실행: 아직 관심 분야·참여 형태가 파악되지 않았습니다. "
            "아래 규칙 1단계에 따라 검색 결과 없이 먼저 질문하세요. 절대로 번호가 매겨진 "
            "공모전 목록(1. 2. 3. ...)을 지어내서 보여주지 마세요 — 이 블록에 실제 "
            "[검색 결과]가 없다는 것은 검색 자체가 실행되지 않았다는 뜻입니다.]"
        )
    else:
        results = semantic_search(search_keyword, k=10)
        if exclude_ids:
            results = [c for c in results if c.id not in exclude_ids]
        results = apply_filters(results, filters)[:5]

        if not results:
            results = search_competitions(
                keyword=None, open_only=True, filters=filters,
                exclude_ids=exclude_ids, limit=5,
            )

        if results:
            # 상세 정보가 있으면 상세 객체를 저장해, role="recommend" 기록(→ 프론트 카드)에
            # 마감·상금·카테고리까지 실리게 한다.
            db_results = []
            tool_context = (
                "\n\n[검색 결과 - 아래 목록만 사용하고 없는 공모전은 절대 만들지 마세요. "
                "각 항목 앞의 번호를 그대로 답변에도 순서대로 남기세요(1. 2. 3. ...). "
                "내부 고유번호(id)는 어떤 형태로도 사용자에게 보여주면 안 됩니다.]\n"
            )
            for i, c in enumerate(results, start=1):
                detail = get_competition_detail(c.id)
                db_results.append(detail or c)
                if detail:
                    deadline = f"마감: {detail.deadline}" if detail.deadline else ""
                    categories = ", ".join(detail.category[:3])
                    requirements = ", ".join(detail.requirements[:3]) if detail.requirements else "없음"
                    prize = f"{detail.first_prize_amount:,}원" if detail.first_prize_amount else "미정"
                    team = detail.team_config or "제한 없음"
                    tool_context += (
                        f"{i}. {detail.title}\n"
                        f"  {deadline} | 카테고리: {categories}\n"
                        f"  지원자격: {requirements}\n"
                        f"  1등 상금: {prize} | 팀구성: {team}\n"
                    )
                else:
                    deadline = f"마감: {c.deadline}" if c.deadline else ""
                    tool_context += f"{i}. {c.title} ({deadline})\n"
        else:
            # DB에 아무것도 없으면 웹 검색. 워크스페이스 연결 대상이 아니므로 순번은 매기지 않는다.
            web_results = web_search(f"{last_user_msg[:50]} 공모전 모집", max_results=5)
            if web_results:
                tool_context = "\n\n[웹 검색 결과 - 출처 URL을 함께 안내하고, 번호는 매기지 마세요]\n"
                for r in web_results:
                    tool_context += f"- {r.title}\n  {r.snippet}\n  출처: {r.url}\n"
            else:
                tool_context = (
                    "\n\n[검색 결과 없음: DB와 웹 검색 모두 관련 공모전을 찾지 못했습니다. "
                    "솔직히 못 찾았다고 안내하세요. 절대로 번호가 매겨진 공모전 목록을 "
                    "지어내서 보여주면 안 됩니다 — 존재하지 않는 공모전을 만들어내는 것은 "
                    "심각한 오류입니다.]"
                )

    history_text = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}"
        for m in history
        if m.role in ("user", "assistant")
    )

    prompt = f"""당신은 공모전 도우미 AI입니다. 공모전 추천, 정보 안내, 준비 계획 수립을 도와드립니다.

[공모전 추천 흐름 규칙]
사용자가 공모전을 찾거나 추천을 요청할 때, 아래 순서를 따르세요.

1. 요구사항 파악 단계 (검색 결과를 사용하지 않음):
   대화 기록에서 아래 정보가 충분히 파악되지 않았으면 먼저 질문하세요.
   - 관심 분야 (예: 개발, 디자인, 마케팅, 데이터 등)
   - 참여 형태 (개인 / 팀, 팀이면 몇 명)
   - 목표 (포트폴리오, 상금, 경험 등)
   한 번에 모든 걸 물어보지 말고 자연스럽게 1~2가지씩 파악하세요.

2. 검색 결과 활용 단계:
   요구사항이 충분히 파악된 경우에만 아래 [검색 결과]를 활용해 추천하세요.
   검색 결과에 없는 공모전은 절대 만들어내지 마세요.

{STYLE_GUIDE}

[답변 형식 규칙]
- [검색 결과]가 있을 때: 마감·상금·자격 같은 상세 정보는 화면에 카드로 함께 표시되므로
  답변에서 반복하지 마세요. 왜 이 목록을 골랐는지 1~2문장으로 말한 뒤, 각 항목을
  "1. 공모전명 — 이 사용자에게 맞는 이유 한 줄" 형태로만 쓰세요(번호는 [검색 결과]의
  번호 그대로). 내부 고유번호(id)는 어떤 형태로도 사용자에게 보여주면 안 됩니다.
- 마지막은 사용자의 선택을 묻는 질문 1개로 마치세요(예: 더 자세히 볼 항목, 조건 변경 여부).
- 아래 [대화 기록] 뒤에 실제 [검색 결과]/[웹 검색 결과] 블록이 없다면, 번호가 매겨진
  공모전 목록을 절대로 스스로 만들어내지 마세요. 검색이 아직 안 됐거나 결과가 없다는
  사실을 그대로 말하고, 필요한 정보(분야/참여형태/목표 등)를 물어보세요.

[대화 기록]
{history_text}{tool_context}

위 대화에서 어시스턴트의 다음 답변을 작성해 주세요."""

    llm = GeminiClient()
    reply = llm.generate(prompt)

    # role="recommend" 저장은 응답 생성 "이후"(main.py 가 assistant 메시지를 쓰기 직전)에
    # 해야 폴링 쪽 "마지막 메시지가 user 면 pending" 판정이 이 중간 기록을 답변으로
    # 오인하는 창을 최소화한다(topic/log/report 와 동일한 타이밍).
    if db_results:
        competition_agent.save_recommend_list(
            conversation_id, db_results, session_factory=session_factory
        )

    return reply


def _handle_progress(
    conversation_id: int,
    user_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    result = evaluate_progress(
        workspace_id, user_id, session_factory=session_factory, tools=tools, llm=llm
    )
    return (
        f"현재 진행률은 {result.percent}%예요 "
        f"(할 일 {result.task_total}개 중 {result.task_done}개 완료). {result.comment}"
    )


def _handle_report(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """팀 전체의 주간 리포트를 집계해 워크스페이스에 저장(role="report")하고 보여준다. (S-03 STEP01)

    저장된 리포트는 워크스페이스의 '주간 리포트' 섹션에서 조회된다(GET /workspaces/{id}/reports).
    주차 번호는 기존 리포트 수 + 1 로 매긴다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )
    report = weekly_report(workspace_id, session_factory=session_factory)
    body = format_weekly_report(report)

    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        existing = (
            session.execute(
                select(func.count())
                .select_from(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Message.role == "report",
                )
            ).scalar()
            or 0
        )
        week = existing + 1
        content = f"{week}주차 주간 리포트\n{body}"
        session.add(
            Message(conversation_id=conversation_id, role="report", content=content)
        )
        session.commit()

    return (
        f"✅ {week}주차 주간 리포트가 생성됐어요! (워크스페이스 → 주간 리포트에서 확인)\n\n"
        f"{content}"
    )


def _log_title(content: str) -> str:
    """실행 로그 content('제목: ...\\n요약: ...')에서 제목을 뽑는다."""
    for line in (content or "").splitlines():
        if line.startswith("제목:"):
            return line[3:].strip() or "작업 기록"
    return "작업 기록"


def _handle_team_status(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """팀 전체(팀원별) 실행 현황을 채팅으로 요약한다. (S-02 STEP03)

    각 팀원이 남긴 실행 로그(role="log") 중 최신 것을 '이름 · 날짜 — 제목 ✅ 완료'로 보여주고,
    로그가 없으면 '아직 없음'. 팀장이 직접 물어보지 않아도 누가 무엇을 했는지 파악하게 한다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        members = session.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.id.asc())
        ).all()
        log_rows = session.execute(
            select(Conversation.user_id, Message.created_at, Message.content)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.workspace_id == workspace_id,
                Message.role == "log",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
        ).all()

    logs_by_user: dict[int, list] = {}
    for uid, created_at, content in log_rows:
        logs_by_user.setdefault(uid, []).append((created_at, content))

    lines = ["📋 팀 전체 진행 현황이에요.\n"]
    for m, u in members:
        name = u.name or u.email
        # owner 이름엔 이미 "(팀장)"이 들어있으니 역할을 덧붙이지 않는다.
        label = name if m.role == "owner" else f"{name} ({m.role})"
        entries = logs_by_user.get(u.id, [])
        if not entries:
            lines.append(f"- {label} · 아직 없음")
            continue
        created_at, content = entries[0]
        date = f"{created_at.month}/{created_at.day}" if created_at else ""
        extra = f" 외 {len(entries) - 1}건" if len(entries) > 1 else ""
        lines.append(
            f"- {label} · {date} — {_log_title(content)} ✅ 완료{extra}"
        )
    return "\n".join(lines)


def _handle_risk_check(
    conversation_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """현황을 근거로 다음 주 계획의 리스크를 진단하고 권장 조치를 제시한다. (S-03 STEP02)

    단순 현황 나열이 아니라 '가장 뒤처진 팀원의 미완료가 다음 주 진행을 어떻게 막는지'를
    LLM 으로 진단하고, 그와 짝이 되는 '미완료 과제를 다음 주로 이동' 제안(role="proposal")을
    저장한다. 팀장은 채팅의 '승인' 버튼으로 이 제안을 실제 계획에 반영할 수 있다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return (
            "아직 연결된 워크스페이스가 없어요. "
            "공모전을 정해 워크스페이스부터 만들면 이어서 도와드릴 수 있어요 — 준비 중인 공모전이 있나요?"
        )

    report = weekly_report(workspace_id, session_factory=session_factory)
    graded = [m for m in report["members"] if m["total"] > 0]
    lagging = min(graded, key=lambda m: m["percent"]) if graded else None
    lag_name = lagging["name"] if lagging else "특정 팀원"

    contest = _load_contest_brief(workspace_id, tools, session_factory=session_factory)
    contest_title = getattr(contest, "title", None) or "미정"
    deadline = getattr(contest, "deadline", None)

    status_lines = "\n".join(
        f"- {m['name']}: {m['percent']}% ({m['done']}/{m['total']}), "
        f"미완료: {', '.join(m['incomplete']) if m['incomplete'] else '없음'}"
        for m in report["members"]
    )

    prompt = f"""당신은 공모전 팀을 관리하는 PM 코치입니다.
팀장이 이번 주 현황과 다음 주 계획의 리스크를 물었습니다.
단순 현황 나열이 아니라 '리스크 진단 + 권장 조치'를 제시하세요.

[공모전] {contest_title} (마감 {deadline or "미정"})
[팀원 현황]
{status_lines}

특히 '{lag_name}' 의 미완료 작업이 다음 주 계획에 어떤 영향을 주는지(선행 자료·의존성) 진단하세요.

아래 형식으로만, 군더더기 없이 작성하세요.
🔍 리스크 진단
<{lag_name}의 미완료가 왜 다음 주 진행을 막는지 1~2문장, 공모전 맥락과 연결>

✅ 권장 조치
① <조치 1: {lag_name}의 미완료 과제를 다음 주 초반으로 이동>
② <조치 2: 관련 회의·의존 작업을 그 이후로 조정>

(진단과 권장 조치까지만 쓰고, '승인' 같은 버튼 문구는 쓰지 마세요.)"""

    try:
        text = (llm or GeminiClient()).generate(prompt).strip()
    except Exception:  # noqa: BLE001
        text = (
            f"🔍 리스크 진단\n{lag_name}의 미완료 작업은 다음 주 진행의 선행 자료라, 지금 두면 "
            f"다음 주 일정이 함께 밀립니다.\n\n"
            f"✅ 권장 조치\n① {lag_name}의 미완료 과제를 다음 주 초반으로 이동\n"
            f"② 관련 회의·의존 작업을 그 이후로 조정"
        )

    _save_reschedule_proposal(
        conversation_id, workspace_id, lagging, session_factory=session_factory
    )
    return text


def _save_reschedule_proposal(
    conversation_id: int,
    workspace_id: int,
    lagging: dict | None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """'미완료 과제를 다음 주로 이동' 제안을 role="proposal"(JSON)로 저장한다.

    팀장이 승인하면 api 가 이 제안을 실제 Task.week_no 이동으로 반영한다(팀장만 가능).
    """
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        owner_id = ws.owner_id if ws else None
        task_ids: list[int] = []
        member_name = lagging["name"] if lagging else ""
        member_id = lagging["user_id"] if lagging else None
        if lagging:
            rows = (
                session.execute(
                    select(Task).where(
                        Task.workspace_id == workspace_id,
                        Task.assignee_id == lagging["user_id"],
                        Task.status != "done",
                    )
                )
                .scalars()
                .all()
            )
            task_ids = [t.id for t in rows]
        payload = {
            "kind": "reschedule",
            "workspace_id": workspace_id,
            "owner_id": owner_id,
            "member_id": member_id,
            "member_name": member_name,
            "task_ids": task_ids,
            "label": f"{member_name}의 미완료 과제 {len(task_ids)}건을 다음 주로 이동",
            "applied": False,
        }
        session.add(
            Message(
                conversation_id=conversation_id,
                role="proposal",
                content=json.dumps(payload, ensure_ascii=False),
            )
        )
        session.commit()


def _load_contest_brief(
    workspace_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
):
    """워크스페이스에 연결된 공모전 상세를 반환한다(없거나 실패 시 None)."""
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        contest_id = ws.contest_id if ws else None
    if contest_id is None:
        return None
    try:
        return tools["get_competition_detail"](contest_id)
    except Exception:  # noqa: BLE001 - 공모전 조회 실패해도 조언은 진행
        return None


def _handle_task_advice(
    conversation_id: int,
    last_user_msg: str,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """정해진 할 일을 공모전 주제와 연결해 '어떻게 시작할지' 작업 방향을 LLM 으로 제시한다.

    (S-02 STEP01) 워크스페이스에 연결된 공모전 정보와 확정 주제를 프롬프트에 넣어,
    공모전 주제와 직접 연결된 접근 방법 3가지를 제시한다. LLM 실패 시 일반 폴백을 쓴다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    contest = None
    topic = ""
    if workspace_id is not None:
        contest = _load_contest_brief(
            workspace_id, tools, session_factory=session_factory
        )
        history = load_history(conversation_id, session_factory=session_factory)
        topic = next((m.content for m in reversed(history) if m.role == "topic"), "")

    contest_title = getattr(contest, "title", None) or "미정"
    categories = ", ".join(getattr(contest, "category", None) or [])
    keywords = ", ".join(getattr(contest, "keywords", None) or [])

    prompt = f"""당신은 공모전 팀을 돕는 실무 코치입니다.
팀원이 맡은 할 일을 '어떻게 시작하면 좋을지' 구체적인 작업 방향을 제시하세요.

[공모전]
- 제목: {contest_title}
- 분야/키워드: {categories or keywords or "미정"}
- 확정 주제: {topic or "아직 미정"}

[팀원의 질문]
{last_user_msg}

요구사항:
- 공모전 주제·분야와 직접 연결된 방향을 제시합니다.
- 접근 방법을 3가지로 나눠, 각 항목을 "①", "②", "③" 로 시작하는 한 줄 제목과 짧은 부연으로 제시합니다.
- 마지막에 "먼저 이것부터:" 로 시작하는, 가장 먼저 할 한 걸음을 한 문장으로 덧붙입니다.
- 인사말·군더더기 없이 바로 방향부터 제시하세요."""

    try:
        return (llm or GeminiClient()).generate(prompt).strip()
    except Exception:  # noqa: BLE001 - LLM 실패해도 흐름은 막지 않는다
        return (
            "이 작업은 이렇게 시작해 보세요.\n"
            "① 목표·범위 정의 — 무엇을, 어느 기간·대상까지 다룰지 먼저 정합니다.\n"
            "② 자료 출처 확보 — 공개 데이터·리포트·SNS 등 구할 수 있는 소스를 나열합니다.\n"
            "③ 정리 포맷 설계 — 이후 분석하기 쉽게 표 구조를 먼저 잡습니다.\n"
            "먼저 이것부터: ①의 목표·범위를 팀과 30분만 정리해 보세요."
        )


def _load_workspace_id(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> int | None:
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        conv = session.get(Conversation, conversation_id)
        return conv.workspace_id if conv else None


# --------------------------------------------------------------------------- #
# 배관(완전 구현): 대화 기억 로드
# --------------------------------------------------------------------------- #


def _default_session_factory() -> sessionmaker[Session]:
    """App DB 엔진에 바인딩된 세션 팩토리(기본값)."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def load_history(
    conversation_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> list[MessageOut]:
    """대화의 메시지 기록을 created_at 오름차순으로 로드한다. (배관, 과제 아님)

    과제(chat)가 바로 쓸 수 있도록 미리 구현해 둔 보조 함수다.
    DB 의 ``Message`` 행을 DTO(``MessageOut``)로 변환해 반환한다.

    Args:
        conversation_id: 대화 세션 id.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.

    Returns:
        시간순 ``MessageOut`` 리스트(role / content). 메시지가 없으면 빈 리스트.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    with session_factory() as session:
        rows = (
            session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
            .scalars()
            .all()
        )
        return [MessageOut(role=m.role, content=m.content) for m in rows]
