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
from contest_helper_core.models import Message, User
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
)
from worker.llm import GeminiClient
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


def _detect_intent(message: str) -> str:
    """마지막 사용자 메시지에서 의도를 감지한다."""
    recommend_kws = [
        "추천", "찾아", "알려줘", "어떤 공모전", "공모전 있", "뭐가 있",
        "있을까", "있나", "있어요", "검색", "공모전 알",
    ]
    plan_kws = ["계획", "일정", "준비", "할일", "태스크", "task"]

    for kw in recommend_kws:
        if kw in message:
            return "recommend"
    for kw in plan_kws:
        if kw in message:
            return "plan"
    return "study"


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
