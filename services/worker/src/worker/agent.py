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

import json
import re
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

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
from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.registry import build_registry
from worker.progress_agent import (
    evaluate_progress,
    format_weekly_report,
    weekly_report,
)

# 의도 분류는 LLM(GeminiClient.generate)이 담당한다. 이 키워드 dict 는 LLM 호출이
# 실패했을 때(자격증명 문제·네트워크 장애 등) 쓰는 규칙 기반 폴백 전용이다.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    # log 는 "워크스페이스에 저장해줘" 처럼 workspace 키워드와 겹치므로 workspace 보다 먼저 검사.
    "log": ["저장해", "기록해", "실행 로그", "작업한 거", "오늘 한 거", "로그로 남겨"],
    # workspace 는 plan("계획 만들") 과 혼동되지 않도록 먼저 검사한다.
    "workspace": ["워크스페이스 만들", "워크스페이스 생성", "워크스페이스 열", "작업공간 만들"],
    # topic 은 "주제 추천" 처럼 recommend("추천") 과 겹칠 수 있어 recommend 보다 먼저 둔다.
    "topic": ["주제 추천", "주제 제안", "주제 후보", "주제 정해", "주제 뽑", "무슨 주제", "어떤 주제"],
    # advice 는 특정 할 일을 "어떻게 시작/진행"할지 방법을 묻는 질문(S-02 STEP01).
    # plan("계획/일정") 과 겹치지 않도록 "어떻게 ~" 표현 위주로 잡고 plan 보다 먼저 검사.
    "advice": ["어떻게 시작", "어떻게 하면 좋을", "어떻게 진행하면", "어떻게 접근", "어디서부터", "어떻게 해야 할"],
    "plan": ["계획", "일정", "역할", "스케줄", "마감까지"],
    "recommend": ["추천", "찾아줘", "공모전 알려줘", "뭐가 있어"],
    # teamstatus 는 팀 전체(팀원별) 실행 현황(S-02 STEP03). progress(개인)보다 먼저 검사.
    "teamstatus": ["팀 전체 진행", "팀 전체 현황", "팀 진행 현황", "전체 진행 현황", "팀 현황", "팀원별 현황", "누가 뭐 했", "누가 무엇을"],
    # riskcheck 는 팀장이 현황+다음 주 계획의 리스크 점검을 요청(S-03 STEP02).
    "riskcheck": ["현황 어때", "계획 괜찮", "이대로 괜찮", "다음 주 계획", "리스크 점검", "점검해줘", "괜찮을까"],
    "progress": ["진행률", "진행 상황", "진행상황", "어디까지"],
    # report 는 팀 전체 주간 집계. progress(개인)와 구분되도록 "리포트/주간" 위주로.
    "report": ["주간 리포트", "주간 보고", "주간 현황", "리포트 보여", "팀 리포트"],
    # background 는 자기소개성 진술이라 넓게 잡되, 다른 인텐트가 먼저 걸리도록 맨 뒤에 둔다.
    "background": ["경험이 있", "경험 있", "해봤", "해본 적", "잘해", "잘합니다", "관심이 많", "관심 많", "관심이 있"],
}
_VALID_INTENTS = (*_INTENT_KEYWORDS.keys(), "study")

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

    message: dict = _classify_intent(last_user_msg, llm=llm)  # {"intent": ..., "matched_on": ...}
    # 데모/디버그용 로그: worker 컨테이너 로그에서 intent 분류 결과를 실시간으로 본다.
    print(
        f"[chat] conv={conversation_id} intent={message['intent']} "
        f"(by {message['matched_on']}) msg={last_user_msg[:40]!r}",
        flush=True,
    )
    tools = build_registry()

    if message["intent"] == "log":
        return _handle_log(
            conversation_id, user_id, session_factory=session_factory, llm=llm
        )
    if message["intent"] == "workspace":
        return _handle_create_workspace(
            conversation_id, user_id, last_user_msg, session_factory=session_factory
        )
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
        return _handle_recommend(last_user_msg, tools)
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
    return _handle_study(last_user_msg)


# --------------------------------------------------------------------------- #
# 과제(stub) 내부 헬퍼: 의도 분류 + 능력별 처리
# --------------------------------------------------------------------------- #


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

    prompt = f"""당신은 공모전 준비를 돕는 챗봇의 의도 분류기입니다.
아래 사용자 메시지를 다음 열두 가지 중 정확히 하나로 분류하고, 그 단어 하나만 답하세요.
다른 설명이나 문장부호 없이 단어 하나만 출력해야 합니다.

- workspace: 워크스페이스(작업 공간)를 새로 만들거나 열어 달라는 요청
- log: 작업 내용을 저장/기록/남겨 달라고 "명시적으로" 요청할 때만 (예: "오늘 작업한 거 저장해줘"). 단순히 오늘 한 일을 서술하면 study.
- background: 자기(팀원)의 경험·관심·강점을 소개하거나 진술 (예: "나는 데이터 분석 경험이 있어")
- topic: 주제/아이디어 후보를 제안해 달라고 "명시적으로" 요청할 때만
- advice: 이미 정해진 특정 할 일(작업)을 어떻게 시작·진행하면 좋을지 방법이나 방향을 물어봄 (예: "○○ 데이터 수집해야 하는데 어떻게 시작하면 좋을까?")
- plan: 준비 계획·일정·역할 분담을 요청
- recommend: 공모전 추천·검색을 요청
- progress: (개인) 지금까지의 진행 상황·진척도를 물어봄
- teamstatus: 팀 전체(팀원별)가 각각 무엇을 했는지 실행 현황을 물어봄 (예: "팀 전체 진행 현황 알려줘", "누가 뭐 했어?")
- riskcheck: 현재 현황을 근거로 다음 주 계획의 리스크·문제를 점검/진단해 달라고 요청 (예: "이번 주 현황 어때? 다음 주 계획 괜찮아?")
- report: 팀 전체의 주간 리포트/집계 현황을 요청 (예: "주간 리포트 보여줘")
- study: 그 외(개념 설명, 질문, 잡담 등)

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

    LLM 실패/파싱 실패 시엔 메시지 전체를 할 일 1개로 저장하는 폴백을 쓴다.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

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

    prompt = f"""당신은 공모전 팀의 준비 일정을 짜는 코치입니다.

확정 주제: {topic or "아직 미정"}
공모전 마감: {deadline or "미정"}
팀원 배경(강점):
{backgrounds or "- (아직 입력된 배경 없음)"}

마감까지 4주 내외의 주차별 준비 계획을 세우세요.
- 각 주차에 팀이 수행할 구체적 할 일을 여러 개 나열합니다.
- 팀원 배경(강점)에 맞게 역할이 드러나도록 작성합니다.
- 반드시 아래 형식으로 "한 줄에 하나씩"만 출력하고, 다른 설명·머리말은 쓰지 마세요.

<주차숫자>주차 | <할 일 제목>

예시:
1주차 | 공모전 요강·심사기준 정리
1주차 | 2030 소비 트렌드 데이터 수집
2주차 | SNS 반응률-구매 전환율 교차 분석
3주차 | 전략 수립 및 문서화
4주차 | 검토·수정 후 최종 제출"""

    try:
        raw = (llm or GeminiClient()).generate(prompt)
        plan = _parse_plan(raw)
    except Exception:
        plan = []

    if not plan:
        # 폴백: LLM 실패 시 메시지 전체를 할 일 1개로.
        plan = [TaskIn(title=last_user_msg[:200] or "계획 정리", week_no=1)]

    saved = tools["create_tasks"](workspace_id=workspace_id, tasks=plan)

    # [데모] 팀원을 보장하고 방금 만든 할 일을 4명에게 배정한다(주차별로 A/B/C/D 고르게).
    # (완료율은 각자 작업/시뮬레이션으로 채워지며, 여기선 배정만 한다.)
    if session_factory is None:
        session_factory = _default_session_factory()
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        member_ids = _ensure_team_members(session, workspace_id, ws.owner_id)
        tasks_rows = (
            session.execute(
                select(Task)
                .where(Task.workspace_id == workspace_id)
                .order_by(Task.week_no.asc(), Task.id.asc())
            )
            .scalars()
            .all()
        )
        # 주차 순서로 정렬된 할 일에 전역 라운드로빈으로 배정한다. 주당 할 일 수가
        # 팀원 수보다 적어도(예: 주 3개) 전체에 걸쳐 A/B/C/D 모두 고르게 받도록 보장한다.
        unassigned = [t for t in tasks_rows if t.assignee_id is None]
        for i, t in enumerate(unassigned):
            t.assignee_id = member_ids[i % len(member_ids)]
        session.flush()

        # [S-01 STEP05] 배분받은 팀원(owner 제외)에게 알림 → 각자 화면에 자동 반영됨을 알린다.
        owner = session.get(User, ws.owner_id)
        owner_name = owner.name if owner and owner.name else "팀장"
        for uid in member_ids[1:]:
            cnt = sum(1 for t in tasks_rows if t.assignee_id == uid)
            if cnt:
                _notify_members(
                    session,
                    workspace_id,
                    [uid],
                    f"{owner_name}님이 주차별 계획을 세우고 할 일을 나눴어요 — 내 담당 {cnt}개",
                )
        session.commit()

    return _format_plan_reply(saved)


def _parse_plan(raw: str) -> list[TaskIn]:
    """LLM 출력("N주차 | 할 일")을 파싱해 week_no 가 채워진 TaskIn 리스트로 만든다."""
    plan: list[TaskIn] = []
    for line in raw.splitlines():
        m = re.match(r"^\s*(\d+)\s*주차\s*[|:\-–]\s*(.+?)\s*$", line)
        if not m:
            continue
        title = m.group(2).strip(" -•*").strip()
        if title:
            plan.append(TaskIn(title=title[:200], week_no=int(m.group(1))))
        if len(plan) >= 16:  # 폭주 방지
            break
    return plan


def _format_plan_reply(saved) -> str:
    """저장된 Task 들을 주차별로 묶어 사람이 읽기 좋은 응답으로 만든다."""
    by_week: dict[int, list[str]] = {}
    for t in saved:
        by_week.setdefault(t.week_no or 0, []).append(t.title)
    lines = ["주차별 계획을 워크스페이스 할 일로 저장했어요."]
    for wk in sorted(by_week):
        lines.append(f"\n[{wk}주차]" if wk else "\n[기타]")
        lines.extend(f"- {title}" for title in by_week[wk])
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
) -> str:
    """대화에서 "워크스페이스 만들어줘" 요청을 받아 워크스페이스를 만들고
    현재 대화에 연결한다. (S-01 STEP03)

    - 이미 연결된 워크스페이스가 있으면 새로 만들지 않고 안내만 한다(멱등).
    - 메시지에 공모전 번호가 있으면("12번으로 ...") 그 공모전에 연결한다(contest_id).
      번호가 없으면 공모전 미연결로 생성하고 이름만 만든다.
    - 팀원 초대·알림·섹션은 백엔드/다음 단계 몫이라, 여기선 소유자 1명 등록 +
      대화 연결까지만 책임진다.
    - 새 테이블/마이그레이션 없이 기존 Workspace/WorkspaceMember/Conversation 만 사용.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    # 메시지에 공모전 번호가 있으면 그 공모전에 맞춰 만든다(추천 목록에서 고른 경우).
    contest_id, contest_title = _extract_contest(last_user_msg)

    with session_factory() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            return "대화를 찾을 수 없어요. 잠시 후 다시 시도해 주세요."
        if conv.workspace_id is not None:
            ws = session.get(Workspace, conv.workspace_id)
            name = ws.name if ws else "워크스페이스"
            return (
                f"이미 '{name}' 워크스페이스에 연결돼 있어요. "
                "'계획 짜줘'로 할 일을 나누거나 '진행 상황 알려줘'로 진척도를 확인해 보세요."
            )

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
        f"{linked}워크스페이스를 만들고 이 대화에 연결했어요. 팀원들에게 알림도 보냈어요. "
        "이제 '주제 후보 제안해줘', '계획 짜줘', '진행 상황 알려줘'를 이어서 해보세요."
    )


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


def _extract_contest(text: str) -> tuple[int | None, str | None]:
    """메시지에서 공모전 번호를 찾아 (contest_id, 공모전 제목)을 반환한다.

    추천 목록이 "[12] KOSSDA... " 형태로 번호를 보여주므로, 사용자가 "12번으로
    워크스페이스 만들어줘"라고 하면 그 번호를 공모전 PK 로 본다. 번호가 없거나
    실제 공모전이 아니면 (None, None) — 공모전 미연결로 워크스페이스를 만든다.
    """
    m = re.search(r"\d+", text)
    if not m:
        return None, None
    cid = int(m.group())
    try:
        detail = build_registry()["get_competition_detail"](cid)
    except Exception:  # noqa: BLE001 - 조회 실패(미구현 포함) 시 미연결로 진행
        return None, None
    if detail is None:
        return None, None
    return cid, detail.title


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


def _handle_log(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """오늘 진행한 작업 대화를 요약해 실행 로그(``Message(role="log")``)로 저장하고,
    내용과 관련된 할 일(Task)을 완료 처리한다. (S-02 STEP02)

    - 요약/키워드 생성은 LLM. 실패 시 최근 사용자 발화로 폴백.
    - 실행 로그는 새 테이블 없이 role="log" 메시지로 저장(스키마 재사용).
    - 완료 처리는 로그 내용과 제목이 가장 많이 겹치는 todo Task 를 done 으로.
    """
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

    history = load_history(conversation_id, session_factory=session_factory)
    convo = [m for m in history if m.role in ("user", "assistant") and m.content.strip()]
    # 마지막 user 메시지(= "저장해줘" 명령 자체)는 요약 대상에서 제외.
    if convo and convo[-1].role == "user":
        convo = convo[:-1]
    convo = convo[-20:]
    if not convo:
        return "저장할 작업 내용이 없어요. 먼저 오늘 한 작업을 이야기해 주세요."

    convo_text = "\n".join(f"{m.role}: {m.content}" for m in convo)
    prompt = f"""아래는 공모전 팀원이 오늘 진행한 작업 대화입니다.
핵심 내용을 요약하고 키워드를 뽑아, 아래 형식으로만 출력하세요(다른 말 금지).

요약: <오늘 한 작업의 핵심 2~3문장>
키워드: #키워드1 #키워드2 #키워드3

작업 대화:
{convo_text}"""

    try:
        summary = (llm or GeminiClient()).generate(prompt).strip()
    except Exception:
        recent = [m.content for m in convo if m.role == "user"][-3:]
        summary = "요약: " + " / ".join(recent)[:300] if recent else "요약: (내용 없음)"

    if session_factory is None:
        session_factory = _default_session_factory()

    completed_title: str | None = None
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
        best = _best_matching_task(summary, todos)
        # 로그 헤더로 쓸 제목: 완료 처리되는 할 일 제목(없으면 "작업 기록").
        # 실행 로그는 "제목: ...\n요약: ...\n키워드: ..." 형태로 저장한다(작성자·날짜는
        # 메시지 메타에서 읽으므로 content 엔 안 넣는다).
        log_title = best.title if best is not None else "작업 기록"
        session.add(
            Message(
                conversation_id=conversation_id,
                role="log",
                content=f"제목: {log_title}\n{summary}",
            )
        )
        if best is not None:
            best.status = "done"
            completed_title = best.title
        session.commit()

    reply = "오늘 작업을 실행 로그에 저장했어요.\n\n" + summary
    if completed_title:
        reply += f"\n\n✅ 관련 할 일 완료 처리: {completed_title}"
    return reply


def _best_matching_task(text: str, tasks: list) -> "Task | None":
    """로그 내용과 제목이 가장 많이 겹치는 todo Task 를 고른다(겹치는 단어 1개 이상일 때만)."""
    words = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", text))
    best, best_score = None, 0
    for t in tasks:
        overlap = len(words & set(re.findall(r"[가-힣A-Za-z0-9]{2,}", t.title)))
        if overlap > best_score:
            best, best_score = t, overlap
    return best if best_score >= 1 else None


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

    return candidates


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
    return (
        f"좋아요, 팀원 배경으로 기억해뒀어요. (지금까지 {gathered}개) "
        "배경이 더 모이면 '주제 후보 제안해줘'라고 말해 주세요. "
        "여러 배경을 종합해 어울리는 공모전 주제를 제안해 드릴게요."
    )


# [임시/데모용 — competition-agent(유진) 확인 필요]
# search_competitions 의 keyword 는 title ILIKE '%kw%' 라 문장 전체를 넘기면 0건이다.
# 데모가 막히지 않게, 메시지에서 뽑은 후보 토큰으로 순차 검색하고 실패 시 열린 공모전으로
# 폴백한다. 정식 버전은 semantic_search / 사용자 프로필 기반으로 유진이 교체할 예정.
_RECOMMEND_STOPWORDS = (
    "추천", "공모전", "찾아줘", "찾아", "알려줘", "알려", "해줘", "해봐", "해보고", "해보",
    "관련", "관심", "있어", "있나", "없어", "없나", "뭐가", "뭐", "좀", "나가고", "나갈",
    "싶어", "싶은", "대회", "괜찮은", "적당한", "이번", "우리", "요즘",
)


def _recommend_keywords(text: str) -> list[str]:
    """사용자 메시지에서 검색에 쓸 후보 키워드 토큰들을 뽑는다(간단 규칙, 데모용)."""
    words = text.replace(",", " ").replace(".", " ").split()
    kept: list[str] = []
    for w in words:
        for s in _RECOMMEND_STOPWORDS:
            w = w.replace(s, "")
        w = w.strip(" '\"~!?()")
        if len(w) >= 2 and w not in kept:
            kept.append(w)
    return kept[:4]


def _handle_recommend(last_user_msg: str, tools: dict) -> str:
    try:
        results: list = []
        for kw in _recommend_keywords(last_user_msg):
            results = tools["search_competitions"](keyword=kw, limit=3)
            if results:
                break
        if not results:
            # 폴백: 특정 키워드가 안 맞으면 마감 임박한 열린 공모전을 보여준다.
            results = tools["search_competitions"](keyword=None, limit=3)
    except NotImplementedError:
        # search_agent 파트가 아직 구현 전이어도 workspace_agent 쪽 흐름은 막지 않는다.
        return "추천 기능을 준비 중이에요. 조금만 기다려 주세요!"
    if not results:
        return "지금은 열린 공모전을 찾지 못했어요. 잠시 후 다시 시도해 주세요."
    lines = [f"[{c.id}] {c.title} (마감 {c.deadline})" for c in results]
    return (
        "이런 공모전은 어때요?\n"
        + "\n".join(lines)
        + "\n\n마음에 드는 번호로 '○번으로 워크스페이스 만들어줘' 라고 말해보세요."
    )


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
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

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
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."
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
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

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
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

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


def _handle_study(last_user_msg: str) -> str:
    # 1단계(규칙 기반) 플레이스홀더. 다음 단계에서 llm.generate 로 교체.
    if not last_user_msg:
        return "무엇을 도와드릴까요? '추천해줘' / '계획 짜줘' 처럼 말씀해 주세요."
    return f"'{last_user_msg}'에 대해 알아보고 있어요. 조금 더 구체적으로 물어봐 주시겠어요?"


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
