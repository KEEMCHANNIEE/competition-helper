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
from contest_helper_core.models import Message
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
)


def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다. (과제 stub)

    Args:
        payload: 작업 입력 (job_id, user_id, limit).

    Returns:
        길이 ``<= payload.limit`` 인 ``RecommendationOut`` 리스트.
    """
    raise NotImplementedError("TODO(AI 담당): agent.run 추천 루프를 구현하세요.")


def chat(conversation_id: int, user_id: int) -> str:
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
    raise NotImplementedError("TODO(AI 담당): agent.chat 대화형 에이전트 구현")


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
