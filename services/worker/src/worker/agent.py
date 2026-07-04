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

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Conversation, Message
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
    TaskIn,
)
from worker.mcp_tools.registry import build_registry
from worker.progress_agent import evaluate_progress

# 의도 판단용 규칙 dict. LLM 없이도 "계획/추천/공부" 세 능력을 라우팅할 수 있게
# 키워드 → 의도 매핑만으로 최소 동작시킨다(1단계). 나중에 llm.generate 기반
# 분류로 교체해도 chat()의 나머지 구조는 그대로 재사용 가능하도록 분리해 둔다.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "plan": ["계획", "일정", "역할", "스케줄", "마감까지"],
    "recommend": ["추천", "찾아줘", "공모전 알려줘", "뭐가 있어"],
    "progress": ["진행률", "진행 상황", "진행상황", "어디까지"],
}

def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다. (과제 stub)

    Args:
        payload: 작업 입력 (job_id, user_id, limit).

    Returns:
        길이 ``<= payload.limit`` 인 ``RecommendationOut`` 리스트.
    """
    raise NotImplementedError("TODO(AI 담당): agent.run 추천 루프를 구현하세요.")


def chat(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
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

    message: dict = _classify_intent(last_user_msg)  # {"intent": ..., "matched_on": ...}
    tools = build_registry()

    if message["intent"] == "plan":
        return _handle_plan(
            conversation_id, last_user_msg, tools, session_factory=session_factory
        )
    if message["intent"] == "recommend":
        return _handle_recommend(last_user_msg, tools)
    if message["intent"] == "progress":
        return _handle_progress(
            conversation_id, user_id, tools, session_factory=session_factory
        )
    return _handle_study(last_user_msg)


# --------------------------------------------------------------------------- #
# 과제(stub) 내부 헬퍼: 의도 분류 + 능력별 처리
# --------------------------------------------------------------------------- #


def _classify_intent(text: str) -> dict:
    """사용자의 마지막 메시지를 규칙 기반으로 추천/공부/계획 중 하나로 분류한다.

    search_agent 쪽 도구를 부를지, create_tasks 를 부를지 결정하는 dict 메시지.
    나중에 llm.generate 기반 판단으로 바꿔도 반환 모양(dict)은 유지한다.
    """
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return {"intent": intent, "matched_on": "keyword"}
    return {"intent": "study", "matched_on": "default"}


def _handle_plan(
    conversation_id: int,
    last_user_msg: str,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

    # 1단계(규칙 기반): 메시지 전체를 할 일 하나로 저장. 다음 단계에서 LLM으로
    # 주차별 세부 계획(list[TaskIn])을 뽑도록 고도화한다.
    plan = [TaskIn(title=last_user_msg[:200] or "계획 정리", week_no=1)]
    saved = tools["create_tasks"](workspace_id=workspace_id, tasks=plan)
    titles = ", ".join(t.title for t in saved)
    return f"계획을 워크스페이스 할 일로 저장했어요: {titles}"


def _handle_recommend(last_user_msg: str, tools: dict) -> str:
    try:
        results = tools["search_competitions"](keyword=last_user_msg or None, limit=3)
    except NotImplementedError:
        # search_agent 파트가 아직 구현 전이어도 workspace_agent 쪽 흐름은 막지 않는다.
        return "추천 기능을 준비 중이에요. 조금만 기다려 주세요!"
    if not results:
        return "조건에 맞는 공모전을 못 찾았어요. 다른 키워드로 다시 물어봐 주세요."
    lines = [f"- {c.title} (마감 {c.deadline})" for c in results]
    return "이런 공모전은 어때요?\n" + "\n".join(lines)


def _handle_progress(
    conversation_id: int,
    user_id: int,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    if workspace_id is None:
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

    result = evaluate_progress(
        workspace_id, user_id, session_factory=session_factory, tools=tools
    )
    return (
        f"현재 진행률은 {result.percent}%예요 "
        f"(할 일 {result.task_total}개 중 {result.task_done}개 완료). {result.comment}"
    )


def _handle_study(last_user_msg: str) -> str:
    # 1단계(규칙 기반) 플레이스홀더. 다음 단계에서 llm.generate 로 교체.
    if not last_user_msg:
        return "무엇을 도와드릴까요? '추천해줘' / '계획 짜줘' 처럼 말씀해 주세요."
    return f"'{last_user_msg}'에 대해 알아보고 있어요. 조금 더 구체적으로 물어봐 주시겠어요?"


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
