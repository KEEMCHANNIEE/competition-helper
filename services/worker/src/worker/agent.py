"""에이전트의 "머리" — 추천 + 대화 + 대화기억 로더(배관, 완전구현).

이 모듈은 두 가지 종류의 코드를 담는다.

1) 에이전트 두뇌:
   - ``run(payload)``  : 추천 능력.
   - ``chat(conversation_id, user_id)`` : 대화형 능력(추천/공부/계획).

2) 배관(완전 구현):
   - ``load_history(conversation_id)`` : 대화 메시지 기록 로드.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Conversation, Message, User
from contest_helper_core.schemas import (
    MessageOut,
    RecommendationOut,
    RecommendJobPayload,
    TaskIn,
)
from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.competitions import (
    KNOWN_CATEGORIES,
    KNOWN_TARGETS,
    TARGET_NO_RESTRICTION,
    CompetitionDetailOut,
    CompetitionSearchFilters,
    get_competition_detail,
    search_competitions,
)
from worker.mcp_tools.registry import build_registry
from worker.mcp_tools.web_search import web_search
from worker.progress_agent import evaluate_progress
from worker.rag import semantic_search

logger = logging.getLogger(__name__)

# 의도 분류는 LLM(GeminiClient.generate)이 담당한다. 이 키워드 dict 는 LLM 호출이
# 실패했을 때(자격증명 문제·네트워크 장애 등) 쓰는 규칙 기반 폴백 전용이다.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "plan": ["계획", "일정", "역할", "스케줄", "마감까지"],
    "recommend": ["추천", "찾아줘", "공모전 알려줘", "뭐가 있어"],
    "progress": ["진행률", "진행 상황", "진행상황", "어디까지"],
}
_VALID_INTENTS = (*_INTENT_KEYWORDS.keys(), "study")


def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다.

    Args:
        payload: 작업 입력 (job_id, user_id, limit).

    Returns:
        길이 ``<= payload.limit`` 인 ``RecommendationOut`` 리스트.
    """
    logger.info("[추천] 시작 job_id=%s user_id=%s limit=%s", payload.job_id, payload.user_id, payload.limit)

    session_factory = _default_session_factory()
    with session_factory() as session:
        user = session.get(User, payload.user_id)

    if user is None:
        logger.warning("[추천] user_id=%s 없음 → 빈 리스트 반환", payload.user_id)
        return []

    # 관심사·스킬로 키워드 쿼리 생성
    query_parts = (user.interests or []) + (user.skills or [])
    keyword = " ".join(query_parts[:3]) if query_parts else None

    candidates = search_competitions(keyword=keyword, open_only=True, limit=payload.limit * 3)
    logger.info("[추천] 후보 %d건 (keyword=%r)", len(candidates), keyword)
    if not candidates:
        logger.info("[추천] 후보 없음 → 빈 리스트 반환")
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

    logger.info("[추천] 완료 %d건 반환", len(recos))
    return recos


def chat(
    conversation_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
) -> str:
    """대화형 에이전트의 한 턴을 실행해 어시스턴트 답변 텍스트를 반환한다.

    의도(추천/공부/계획/진행률)를 마지막 메시지에서 분류하고, 의도에 맞는
    핸들러를 호출해 답변 텍스트를 반환한다.

    Args:
        conversation_id: 대화 세션 id.
        user_id: 말을 건 사용자 id.

    Returns:
        어시스턴트가 사용자에게 보낼 답변 텍스트. (DB 저장은 배관이 한다)
    """
    logger.info("[chat] 시작 conversation_id=%s user_id=%s", conversation_id, user_id)

    history = load_history(conversation_id, session_factory=session_factory)

    if not history:
        logger.info("[chat] 대화 기록 없음 → 인사 메시지 반환")
        return "안녕하세요! 공모전 추천, 정보 조회, 준비 계획 수립을 도와드릴 수 있어요. 어떤 도움이 필요하신가요?"

    last_user_msg = next(
        (m.content for m in reversed(history) if m.role == "user"), ""
    )

    message: dict = _classify_intent(last_user_msg, history=history, llm=llm)  # {"intent": ..., "matched_on": ...}
    logger.info(
        "[chat] 의도 분류: %s (matched_on=%s) msg=%r",
        message["intent"], message["matched_on"], last_user_msg[:80],
    )
    tools = build_registry()

    if message["intent"] == "plan":
        logger.info("[chat] → _handle_plan 로 라우팅")
        return _handle_plan(
            conversation_id, last_user_msg, tools, session_factory=session_factory
        )
    if message["intent"] == "recommend":
        logger.info("[chat] → _handle_recommend 로 라우팅")
        return _handle_recommend(history, last_user_msg)
    if message["intent"] == "progress":
        logger.info("[chat] → _handle_progress 로 라우팅")
        return _handle_progress(
            conversation_id, user_id, tools, session_factory=session_factory, llm=llm
        )
    logger.info("[chat] → _handle_study 로 라우팅")
    return _handle_study(last_user_msg, llm=llm)


# --------------------------------------------------------------------------- #
# 과제(stub) 내부 헬퍼: 의도 분류 + 능력별 처리
# --------------------------------------------------------------------------- #


def _classify_intent(
    text: str, *, history: list[MessageOut] | None = None, llm: LLMClient | None = None
) -> dict:
    """사용자의 마지막 메시지를 LLM 으로 추천/공부/계획/진행률 중 하나로 분류한다.

    search_agent 쪽 도구를 부를지, create_tasks/evaluate_progress 를 부를지
    결정하는 dict 메시지. LLM 호출이 실패하면(자격증명·네트워크 등) 규칙 기반
    키워드 매칭으로 폴백한다(전체 대화가 죽지 않도록).

    ``history`` 를 넘기면 최근 대화 흐름을 프롬프트에 포함해, "3명이요" 처럼
    직전 질문에 대한 짧은 답변만으로는 의도를 알 수 없는 메시지도 같은 흐름
    (예: 추천 요구사항 파악 중)으로 유지되도록 분류를 돕는다.
    """
    if not text:
        return {"intent": "study", "matched_on": "default"}

    context_block = ""
    if history:
        recent = history[-6:]
        lines = [
            f"{'사용자' if m.role == 'user' else '어시스턴트'}: {m.content}"
            for m in recent
        ]
        context_block = "\n\n최근 대화 흐름:\n" + "\n".join(lines) + "\n"

    prompt = f"""당신은 공모전 준비를 돕는 챗봇의 의도 분류기입니다.
아래 사용자 메시지를 다음 네 가지 중 정확히 하나로 분류하고, 그 단어 하나만 답하세요.
다른 설명이나 문장부호 없이 단어 하나만 출력해야 합니다.

- plan: 준비 계획·일정·역할 분담을 요청
- recommend: 공모전 추천·검색을 요청
- progress: 지금까지의 진행 상황·진척도를 물어봄
- study: 그 외(개념 설명, 잡담 등)
{context_block}
주의: 최근 대화가 이미 특정 흐름(예: 추천을 위해 관심분야·참여형태·목표를 묻는 중) 안에
있고 마지막 사용자 메시지가 그 질문에 대한 짧은 답변("네", "대학생이요", "혼자요" 등)으로
보인다면, 명확한 주제 전환이 없는 한 그 흐름과 같은 의도로 분류하세요.

마지막 사용자 메시지: "{text}"

분류 결과(단어 하나만):"""

    try:
        client = llm or GeminiClient()
        raw = client.generate(prompt).strip().lower()
    except Exception:
        logger.warning("[의도분류] LLM 호출 실패 → 키워드 폴백", exc_info=True)
        return _classify_intent_by_keyword(text)

    logger.info("[의도분류] LLM 원본 응답: %r", raw)
    for intent in _VALID_INTENTS:
        if intent in raw:
            return {"intent": intent, "matched_on": "llm"}
    # LLM 이 넷 중 하나로 파싱 안 되는 답을 준 경우도 폴백.
    logger.info("[의도분류] LLM 응답 파싱 실패 → 키워드 폴백")
    return _classify_intent_by_keyword(text)


def _classify_intent_by_keyword(text: str) -> dict:
    """LLM 이 실패하거나 애매하게 답했을 때 쓰는 규칙 기반 폴백 분류."""
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            logger.info("[의도분류] 키워드 매칭: %s", intent)
            return {"intent": intent, "matched_on": "keyword"}
    logger.info("[의도분류] 키워드 매칭 없음 → study 기본값")
    return {"intent": "study", "matched_on": "default"}


def _handle_plan(
    conversation_id: int,
    last_user_msg: str,
    tools: dict,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    workspace_id = _load_workspace_id(conversation_id, session_factory=session_factory)
    logger.info("[계획] conversation_id=%s → workspace_id=%s", conversation_id, workspace_id)
    if workspace_id is None:
        logger.warning("[계획] 워크스페이스 미연결 → 안내 메시지 반환")
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

    # 1단계(규칙 기반): 메시지 전체를 할 일 하나로 저장. 다음 단계에서 LLM으로
    # 주차별 세부 계획(list[TaskIn])을 뽑도록 고도화한다.
    plan = [TaskIn(title=last_user_msg[:200] or "계획 정리", week_no=1)]
    saved = tools["create_tasks"](workspace_id=workspace_id, tasks=plan)
    titles = ", ".join(t.title for t in saved)
    logger.info("[계획] %d개 할일 저장 완료: %s", len(saved), titles)
    return f"계획을 워크스페이스 할 일로 저장했어요: {titles}"


def _handle_recommend(history: list[MessageOut], last_user_msg: str) -> str:
    search_keyword = _extract_search_keyword(history)
    filters = _extract_search_filters(history)
    logger.info(
        "[검색] 추출된 키워드: %r | 필터: %s",
        search_keyword, filters.model_dump(exclude_none=True),
    )

    if not search_keyword:
        # 관심 분야가 아직 파악 안 됐으면 검색 자체를 생략하고, LLM이 요구사항부터
        # 질문하게 한다(정보 없이 아무 공모전 목록이나 던지는 것 방지).
        logger.info("[검색] 키워드 없음 → 검색 생략, 요구사항 질문 단계로")
        tool_context = (
            "\n\n[검색 미실행: 아직 관심 분야·참여 형태가 파악되지 않았습니다. "
            "아래 규칙 1단계에 따라 검색 결과 없이 먼저 질문하세요.]"
        )
    else:
        logger.info("[검색] 시맨틱 검색 시작")
        results = semantic_search(search_keyword, k=10)
        before = len(results)
        results = _apply_filters(results, filters)
        logger.info("[검색] 시맨틱 검색 %d건 → 필터 적용 후 %d건", before, len(results))
        results = results[:5]

        if not results:
            logger.info("[검색] 시맨틱 검색 0건 → 전체 활성 공모전 검색")
            results = search_competitions(keyword=None, open_only=True, filters=filters, limit=10)
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
            # DB에 아무것도 없으면 웹 검색
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
    logger.info("[진행률] conversation_id=%s → workspace_id=%s", conversation_id, workspace_id)
    if workspace_id is None:
        logger.warning("[진행률] 워크스페이스 미연결 → 안내 메시지 반환")
        return "이 대화는 아직 워크스페이스에 연결돼 있지 않아요. 먼저 워크스페이스를 만들어 주세요."

    result = evaluate_progress(
        workspace_id, user_id, session_factory=session_factory, tools=tools, llm=llm
    )
    logger.info(
        "[진행률] %s%% (완료 %d/%d)", result.percent, result.task_done, result.task_total
    )
    return (
        f"현재 진행률은 {result.percent}%예요 "
        f"(할 일 {result.task_total}개 중 {result.task_done}개 완료). {result.comment}"
    )


def _handle_study(last_user_msg: str, *, llm: LLMClient | None = None) -> str:
    logger.info("[공부] 질문: %r", last_user_msg[:80])
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


def _extract_search_filters(
    history: list[MessageOut], *, llm: LLMClient | None = None
) -> CompetitionSearchFilters:
    """대화 전체에서 구조화된 검색 필터(분야/대상/최소상금/참여형태/취업연계/마감)를 추출한다.

    사용자가 실제로 언급한 조건만 채우고 나머지는 반드시 null로 두도록 프롬프트에
    명시한다(없는 조건을 LLM이 지어내 결과를 과도하게 걸러내는 것 방지). LLM 호출
    실패·JSON 파싱 실패 시 빈 필터(전부 None, 즉 무필터)로 안전하게 폴백한다.
    """
    user_msgs = [m.content for m in history if m.role == "user"]
    if not user_msgs:
        return CompetitionSearchFilters()

    combined = " / ".join(user_msgs[-5:])  # 최근 5개 사용자 메시지
    today = date.today().isoformat()
    category_options = ", ".join(KNOWN_CATEGORIES)
    target_options = ", ".join(KNOWN_TARGETS)
    prompt = f"""다음은 사용자와 공모전 도우미의 대화에서 사용자 발언만 모은 것입니다.
아래 JSON 스키마에 맞춰, 사용자가 명시적으로 언급한 조건만 채우고 언급 안 된 필드는
반드시 null 로 두세요. 설명이나 코드블록 없이 JSON 객체 하나만 출력하세요.

오늘 날짜: {today} (마감일 관련 표현("이번 주까지", "이번 달 안에" 등)은 이 날짜 기준으로 계산하세요)

스키마:
{{
  "category": ["분야1", "분야2"] 또는 null,     // 반드시 다음 중에서만 골라라: {category_options}
  "target": ["대학생", "일반인"] 또는 null,      // 반드시 다음 중에서만 골라라: {target_options}
  "has_prize": true, false, 또는 null,          // 금액과 상관없이 "상금이 있는지"만 물었으면 true
  "min_prize": 정수 또는 null,                  // 사용자가 구체적인 최소 금액을 언급했을 때만
  "participation_type": "individual" 또는 "team" 또는 null,
  "is_career_benefit": true, false, 또는 null,  // 취업·인턴 연계를 원한다고 했으면
  "deadline_before": "YYYY-MM-DD" 또는 null      // 이 날짜 전 마감만 원하면(상대 표현은 오늘 날짜 기준 환산)
}}

사용자 발언: {combined}

JSON:"""

    try:
        client = llm or GeminiClient()
        raw = client.generate(prompt).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        filters = CompetitionSearchFilters.model_validate(data)
    except Exception:
        logger.warning("[검색] 필터 추출 실패 → 무필터로 폴백", exc_info=True)
        return CompetitionSearchFilters()

    logger.info("[검색] 필터 추출 결과: %s", filters.model_dump(exclude_none=True))
    return filters


def _apply_filters(
    results: list[CompetitionDetailOut],
    filters: CompetitionSearchFilters,
) -> list[CompetitionDetailOut]:
    """구조화 필터를 semantic_search 결과에 Python 레벨로 적용한다.

    embeddings 는 App DB, contests 는 별도 읽기전용 DB라 SQL JOIN이 안 되므로
    (search_competitions 와 달리) 여기서는 이미 조회된 객체를 기준으로 걸러낸다.
    """

    def keep(c: CompetitionDetailOut) -> bool:
        if filters.participation_type == "individual" and c.participation_type not in (
            "individual", "individual_or_team", None, "",
        ):
            return False
        if filters.participation_type == "team" and c.participation_type not in (
            "team", "individual_or_team", None, "",
        ):
            return False
        if filters.category and not (set(filters.category) & set(c.category)):
            return False
        if (
            filters.target
            and TARGET_NO_RESTRICTION not in c.target
            and not (set(filters.target) & set(c.target))
        ):
            # "대상 제한 없음"이면 누구나 지원 가능하다는 뜻이라 target 필터를 걸지 않는다.
            return False
        if filters.has_prize is True:
            prize = c.total_prize_amount or c.first_prize_amount or 0
            if prize <= 0:
                return False
        if filters.has_prize is False:
            prize = c.total_prize_amount or c.first_prize_amount or 0
            if prize > 0:
                return False
        if filters.min_prize is not None:
            prize = c.total_prize_amount or c.first_prize_amount or 0
            if prize < filters.min_prize:
                return False
        if filters.is_career_benefit is not None and c.is_career_benefit != filters.is_career_benefit:
            return False
        if filters.deadline_before is not None and c.deadline and c.deadline >= filters.deadline_before:
            return False
        return True

    return [c for c in results if keep(c)]


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
        messages = [MessageOut(role=m.role, content=m.content) for m in rows]
        logger.info("[기록] conversation_id=%s 메시지 %d건 로드", conversation_id, len(messages))
        return messages
