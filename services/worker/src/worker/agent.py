"""에이전트의 "머리" — 추천 + 대화 + 대화기억 로더(배관, 완전구현).

이 모듈은 두 가지 종류의 코드를 담는다.

1) 에이전트 두뇌:
   - ``run(payload)``  : 추천 능력.
   - ``chat(conversation_id, user_id)`` : 대화형 능력(추천/공부/계획).

2) 배관(완전 구현):
   - ``load_history(conversation_id)`` : 대화 메시지 기록 로드.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Message, User
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
)
from worker.llm import GeminiClient
from worker.mcp_tools.competitions import search_competitions


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

    intent = _detect_intent(last_user_msg)

    tool_context = ""
    if intent == "recommend":
        results = search_competitions(keyword=last_user_msg[:50], open_only=True, limit=5)
        if results:
            tool_context = "\n\n[검색된 공모전]\n"
            for c in results:
                deadline = f"마감: {c.deadline}" if c.deadline else ""
                categories = ", ".join(c.category[:2])
                tool_context += f"- {c.title} ({deadline}, 카테고리: {categories})\n"

    history_text = "\n".join(
        f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}"
        for m in history
    )

    prompt = f"""당신은 공모전 도우미 AI입니다. 공모전 추천, 정보 안내, 준비 계획 수립을 도와드립니다.

[대화 기록]
{history_text}{tool_context}

위 대화에서 어시스턴트의 다음 답변을 작성해 주세요."""

    llm = GeminiClient()
    return llm.generate(prompt)


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
