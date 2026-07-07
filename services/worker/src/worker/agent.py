"""에이전트의 "머리" — 추천 + 대화 + 대화기억 로더(배관, 완전구현).

이 모듈은 두 가지 종류의 코드를 담는다.

1) 에이전트 두뇌:
   - ``run(payload)``  : 추천 능력.
   - ``chat(conversation_id, user_id)`` : 대화형 능력(추천/공부/계획).

2) 배관(완전 구현):
   - ``load_history(conversation_id)`` : 대화 메시지 기록 로드.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Conversation, Message
from contest_helper_core.models import Message, User
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
    TaskIn,
)
from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.registry import build_registry
from worker.progress_agent import evaluate_progress

# 의도 분류는 LLM(GeminiClient.generate)이 담당한다. 이 키워드 dict 는 LLM 호출이
# 실패했을 때(자격증명 문제·네트워크 장애 등) 쓰는 규칙 기반 폴백 전용이다.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "plan": ["계획", "일정", "역할", "스케줄", "마감까지"],
    "recommend": ["추천", "찾아줘", "공모전 알려줘", "뭐가 있어"],
    "progress": ["진행률", "진행 상황", "진행상황", "어디까지"],
}
_VALID_INTENTS = (*_INTENT_KEYWORDS.keys(), "study")
from worker.mcp_tools.competitions import get_competition_detail, search_competitions
from worker.mcp_tools.web_search import web_search
from worker.rag import semantic_search


def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다.

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

def chat(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """대화형 에이전트의 한 턴을 실행해 어시스턴트 답변 텍스트를 반환한다. (과제 stub)
    candidates = search_competitions(keyword=keyword, open_only=True, limit=payload.limit * 3)
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


def chat(conversation_id: int, user_id: int) -> str:  # noqa: ARG001
    """대화형 에이전트의 한 턴을 실행해 어시스턴트 답변 텍스트를 반환한다.

    의도(추천/공부/계획)를 마지막 메시지에서 감지하고, 필요 시 도구를 호출한 후
    LLM 으로 최종 답변을 생성한다.

    Args:
        conversation_id: 대화 세션 id.
        user_id: 말을 건 사용자 id.

    Returns:
        어시스턴트 답변 텍스트.
    """
    history = load_history(conversation_id)

    if not history:
        return "안녕하세요! 공모전 추천, 정보 조회, 준비 계획 수립을 도와드릴 수 있어요. 어떤 도움이 필요하신가요?"

    last_user_msg = next(
        (m.content for m in reversed(history) if m.role == "user"), ""
    )

    # 1단계: 대화 전체에서 검색 키워드 + 팀 선호도 추출
    search_keyword = _extract_search_keyword(history)
    participation = _extract_participation(history)
    logger.info("[검색] 추출된 키워드: %r | 참여형태: %r", search_keyword, participation)

    # 2단계: 키워드 있으면 시맨틱 검색 후 participation 필터링, 없으면 전체 검색
    if search_keyword:
        logger.info("[검색] 시맨틱 검색 시작")
        results = semantic_search(search_keyword, k=10)
        if participation:
            before = len(results)
            results = _filter_by_participation(results, participation)
            logger.info("[검색] 시맨틱 검색 %d건 → participation 필터 후 %d건", before, len(results))
        else:
            logger.info("[검색] 시맨틱 검색 결과: %d건", len(results))
        results = results[:5]
    else:
        results = []

    if not results:
        logger.info("[검색] 시맨틱 검색 0건 → 전체 활성 공모전 검색")
        results = search_competitions(keyword=None, open_only=True, participation=participation, limit=10)
        logger.info("[검색] 전체 검색 결과: %d건", len(results))

    if results:
        logger.info("[검색] DB 결과 상세 조회: %s", [c.title for c in results])
        tool_context = "\n\n[DB 검색 결과 - 아래 목록만 사용하고 없는 공모전은 절대 만들지 마세요]\n"
        for c in results:
            detail = get_competition_detail(c.id)
            if detail:
                deadline = f"마감: {detail.deadline}" if detail.deadline else ""
                categories = ", ".join(detail.category[:3])
                requirements = ", ".join(detail.requirements[:3]) if detail.requirements else "없음"
                prize = f"{detail.first_prize_amount:,}원" if detail.first_prize_amount else "미정"
                team = detail.team_config or "제한 없음"
                tool_context += (
                    f"- {detail.title}\n"
                    f"  {deadline} | 카테고리: {categories}\n"
                    f"  지원자격: {requirements}\n"
                    f"  1등 상금: {prize} | 팀구성: {team}\n"
                )
            else:
                deadline = f"마감: {c.deadline}" if c.deadline else ""
                tool_context += f"- {c.title} ({deadline})\n"
    else:
        # 3단계: DB에 아무것도 없으면 웹 검색
        logger.info("[검색] DB 0건 → 웹 검색: %r", last_user_msg[:50])
        web_results = web_search(f"{last_user_msg[:50]} 공모전 모집", max_results=5)
        logger.info("[검색] 웹 검색 결과: %d건", len(web_results))
        if web_results:
            logger.info("[검색] 웹 결과 사용: %s", [r.title for r in web_results])
            tool_context = "\n\n[웹 검색 결과 - 출처 URL을 함께 안내하세요]\n"
            for r in web_results:
                tool_context += f"- {r.title}\n  {r.snippet}\n  출처: {r.url}\n"
        else:
            logger.warning("[검색] DB + 웹 검색 모두 0건")
            tool_context = "\n\n[검색 결과 없음: DB와 웹 검색 모두 관련 공모전을 찾지 못했습니다. 솔직히 안내하세요.]"

    history_text = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}"
        for m in history
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
   요구사항이 충분히 파악된 경우에만 아래 [DB 검색 결과]를 활용해 추천하세요.
   검색 결과에 없는 공모전은 절대 만들어내지 마세요.

[답변 형식 규칙]
- 실제 정보를 전달할 때(공모전 목록, 계획, 팁 등 여러 항목)만 아래 구조를 사용하세요.
- 여러 항목은 각각 <details><summary>제목</summary>내용</details> 형식으로 접을 수 있게 만드세요.
- 전체 요약은 <details> 밖에 2~3문장으로 먼저 쓰세요.
- 마크다운(**, ##, -)도 함께 사용 가능합니다.

[대화 기록]
{history_text}{tool_context}

위 대화에서 어시스턴트의 다음 답변을 작성해 주세요."""

    llm = GeminiClient()
    return llm.generate(prompt)


def _extract_search_keyword(history: list[MessageOut]) -> str | None:
    """대화 전체 사용자 메시지에서 공모전 검색 키워드를 추출한다.

    사용자가 여러 턴에 걸쳐 밝힌 분야·목표·조건을 합쳐 짧은 키워드로 만든다.
    파악된 정보가 없으면 None 을 반환해 전체 검색으로 fallback 한다.
    """
    history = load_history(conversation_id, session_factory=session_factory)
    last_user_msg = next(
        (m.content for m in reversed(history) if m.role == "user"), ""
    )

    message: dict = _classify_intent(last_user_msg, llm=llm)  # {"intent": ..., "matched_on": ...}
    tools = build_registry()

    if message["intent"] == "plan":
        return _handle_plan(
            conversation_id, last_user_msg, tools, session_factory=session_factory
        )
    if message["intent"] == "recommend":
        return _handle_recommend(history, last_user_msg)
    if message["intent"] == "progress":
        return _handle_progress(
            conversation_id, user_id, tools, session_factory=session_factory, llm=llm
        )
    return _handle_study(last_user_msg, llm=llm)


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

    prompt = f"""당신은 공모전 준비를 돕는 챗봇의 의도 분류기입니다.
아래 사용자 메시지를 다음 네 가지 중 정확히 하나로 분류하고, 그 단어 하나만 답하세요.
다른 설명이나 문장부호 없이 단어 하나만 출력해야 합니다.

- plan: 준비 계획·일정·역할 분담을 요청
- recommend: 공모전 추천·검색을 요청
- progress: 지금까지의 진행 상황·진척도를 물어봄
- study: 그 외(개념 설명, 잡담 등)

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


def _handle_recommend(history: list[MessageOut], last_user_msg: str) -> str:
    search_keyword = _extract_search_keyword(history)
    participation = _extract_participation(history)
    logger.info("[검색] 추출된 키워드: %r | 참여형태: %r", search_keyword, participation)

    if search_keyword:
        logger.info("[검색] 시맨틱 검색 시작")
        results = semantic_search(search_keyword, k=10)
        if participation:
            before = len(results)
            results = _filter_by_participation(results, participation)
            logger.info("[검색] 시맨틱 검색 %d건 → participation 필터 후 %d건", before, len(results))
        else:
            logger.info("[검색] 시맨틱 검색 결과: %d건", len(results))
        results = results[:5]
    else:
        results = []

    if not results:
        logger.info("[검색] 시맨틱 검색 0건 → 전체 활성 공모전 검색")
        results = search_competitions(keyword=None, open_only=True, participation=participation, limit=10)
        logger.info("[검색] 전체 검색 결과: %d건", len(results))

    if results:
        logger.info("[검색] DB 결과 상세 조회: %s", [c.title for c in results])
        tool_context = "\n\n[DB 검색 결과 - 아래 목록만 사용하고 없는 공모전은 절대 만들지 마세요]\n"
        for c in results:
            detail = get_competition_detail(c.id)
            if detail:
                deadline = f"마감: {detail.deadline}" if detail.deadline else ""
                categories = ", ".join(detail.category[:3])
                requirements = ", ".join(detail.requirements[:3]) if detail.requirements else "없음"
                prize = f"{detail.first_prize_amount:,}원" if detail.first_prize_amount else "미정"
                team = detail.team_config or "제한 없음"
                tool_context += (
                    f"- {detail.title}\n"
                    f"  {deadline} | 카테고리: {categories}\n"
                    f"  지원자격: {requirements}\n"
                    f"  1등 상금: {prize} | 팀구성: {team}\n"
                )
            else:
                deadline = f"마감: {c.deadline}" if c.deadline else ""
                tool_context += f"- {c.title} ({deadline})\n"
    else:
        logger.info("[검색] DB 0건 → 웹 검색: %r", last_user_msg[:50])
        web_results = web_search(f"{last_user_msg[:50]} 공모전 모집", max_results=5)
        logger.info("[검색] 웹 검색 결과: %d건", len(web_results))
        if web_results:
            logger.info("[검색] 웹 결과 사용: %s", [r.title for r in web_results])
            tool_context = "\n\n[웹 검색 결과 - 출처 URL을 함께 안내하세요]\n"
            for r in web_results:
                tool_context += f"- {r.title}\n  {r.snippet}\n  출처: {r.url}\n"
        else:
            logger.warning("[검색] DB + 웹 검색 모두 0건")
            tool_context = "\n\n[검색 결과 없음: DB와 웹 검색 모두 관련 공모전을 찾지 못했습니다. 솔직히 안내하세요.]"

    history_text = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}"
        for m in history
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
   요구사항이 충분히 파악된 경우에만 아래 [DB 검색 결과]를 활용해 추천하세요.
   검색 결과에 없는 공모전은 절대 만들어내지 마세요.

[답변 형식 규칙]
- 실제 정보를 전달할 때(공모전 목록, 계획, 팁 등 여러 항목)만 아래 구조를 사용하세요.
- 여러 항목은 각각 <details><summary>제목</summary>내용</details> 형식으로 접을 수 있게 만드세요.
- 전체 요약은 <details> 밖에 2~3문장으로 먼저 쓰세요.
- 마크다운(**, ##, -)도 함께 사용 가능합니다.

[대화 기록]
{history_text}{tool_context}

위 대화에서 어시스턴트의 다음 답변을 작성해 주세요."""

    llm = GeminiClient()
    return llm.generate(prompt)


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


def _handle_study(last_user_msg: str, *, llm: LLMClient | None = None) -> str:
    if not last_user_msg:
        return "무엇을 도와드릴까요? '추천해줘' / '계획 짜줘' 처럼 말씀해 주세요."
    client = llm or GeminiClient()
    return client.generate(
        f"당신은 공모전 준비를 돕는 도우미입니다. 아래 사용자 질문에 개념·방법을 "
        f"친절하게 설명해 주세요.\n\n사용자: {last_user_msg}"
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


def _extract_search_keyword(history: list[MessageOut]) -> str | None:
    """대화 전체 사용자 메시지에서 공모전 검색 키워드를 추출한다.

    사용자가 여러 턴에 걸쳐 밝힌 분야·목표·조건을 합쳐 짧은 키워드로 만든다.
    파악된 정보가 없으면 None 을 반환해 전체 검색으로 fallback 한다.
    """
    user_msgs = [m.content for m in history if m.role == "user"]
    if not user_msgs:
        return None

    combined = " / ".join(user_msgs[-5:])  # 최근 5개 사용자 메시지
    llm = GeminiClient()
    result = llm.generate(
        f"다음은 사용자와 공모전 도우미의 대화에서 사용자 발언만 모은 것입니다.\n"
        f"공모전 DB 검색에 쓸 핵심 키워드를 한국어로 1~3단어만 반환하세요.\n"
        f"분야·카테고리 위주로 추출하고, 설명 없이 키워드만 반환하세요.\n"
        f"파악된 정보가 없으면 '없음'이라고만 반환하세요.\n\n"
        f"사용자 발언: {combined}\n"
        f"키워드:"
    )
    keyword = result.strip()
    if not keyword or keyword == "없음":
        return None
    return keyword[:50]


def _extract_participation(history: list[MessageOut]) -> str | None:
    """대화 기록에서 팀/개인 참여 선호를 감지한다."""
    individual_kws = ["혼자", "개인", "1인", "단독", "solo"]
    team_kws = ["팀", "같이", "함께", "팀으로", "여럿", "다같이"]

    for m in reversed(history):
        if m.role != "user":
            continue
        text = m.content
        if any(kw in text for kw in team_kws):
            return "team"
        if any(kw in text for kw in individual_kws):
            return "individual"
    return None


def _filter_by_participation(
    results: list,
    participation: str,
) -> list:
    """시맨틱 검색 결과를 participation_type 기준으로 필터링한다."""
    if participation == "individual":
        allowed = {"individual", "individual_or_team", ""}
    else:  # team
        allowed = {"team", "individual_or_team", ""}

    return [r for r in results if (r.participation_type or "") in allowed]



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
    """대화의 메시지 기록을 created_at 오름차순으로 로드한다.

    Args:
        conversation_id: 대화 세션 id.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.

    Returns:
        시간순 ``MessageOut`` 리스트. 메시지가 없으면 빈 리스트.
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
