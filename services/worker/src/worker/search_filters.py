"""공모전 검색 조건(키워드 + 구조화 필터) 추출·적용 공용 모듈.

agent(추천 인텐트)와 competition_agent(study 재검색 도구) 양쪽에서 쓴다.
agent → competition_agent 방향의 기존 import 에 얹으면 순환이 생기므로,
둘 다 여기에 의존하는 형태로 분리했다.

키워드 추출과 필터 추출은 원래 별도 LLM 호출 2회였는데, 추천 턴 지연을 줄이기
위해 JSON 한 번에 뽑는다. 실패 시엔 (None, 빈 필터)로 안전하게 폴백한다 —
키워드 None 은 "아직 분야 파악 안 됨 → 검색 대신 질문" 흐름과 동일하게 동작한다.
"""

from __future__ import annotations

import json
from datetime import date

from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.competitions import (
    KNOWN_CATEGORIES,
    KNOWN_TARGETS,
    TARGET_NO_RESTRICTION,
    CompetitionDetailOut,
    CompetitionSearchFilters,
)


def extract_keyword_and_filters(
    user_msgs: list[str],
    *,
    llm: LLMClient | None = None,
    max_known_prize: int | None = None,
) -> tuple[str | None, CompetitionSearchFilters]:
    """사용자 발화들에서 검색 키워드와 구조화 필터를 LLM 호출 1회로 추출한다.

    Args:
        user_msgs: 시간순 사용자 발화 목록(최근 5개만 사용).
        llm: LLM 클라이언트(미지정 시 GeminiClient). 테스트는 가짜 주입.
        max_known_prize: 직전 추천 목록의 1등 상금 최댓값. "상금 더 큰 거"처럼
            상대 표현을 절대값(min_prize)으로 환산하는 기준으로 프롬프트에 주입.

    Returns:
        (keyword | None, CompetitionSearchFilters). 키워드가 파악 안 되면 None.
    """
    if not user_msgs:
        return None, CompetitionSearchFilters()

    recent = user_msgs[-5:]
    latest = recent[-1]
    earlier = " / ".join(recent[:-1]) if len(recent) > 1 else "(없음)"
    today = date.today().isoformat()
    category_options = ", ".join(KNOWN_CATEGORIES)
    target_options = ", ".join(KNOWN_TARGETS)
    prize_context = (
        f"\n직전에 보여준 추천 목록의 1등 상금 최댓값: {max_known_prize:,}원 — "
        f'"상금 더 큰/더 높은 거" 같은 상대 표현은 이 값을 초과하는 min_prize'
        f"(예: {max_known_prize + 1})로 환산하세요."
        if max_known_prize
        else ""
    )

    prompt = f"""다음은 사용자와 공모전 도우미의 대화에서 사용자 발언만 모은 것입니다.
아래 JSON 스키마에 맞춰, 사용자가 명시적으로 언급한 조건만 채우고 언급 안 된 필드는
반드시 null 로 두세요. 설명이나 코드블록 없이 JSON 객체 하나만 출력하세요.

오늘 날짜: {today} (마감일 관련 상대 표현("이번 주까지", "준비 기간 3주 필요" 등)은 이 날짜 기준으로 계산하세요){prize_context}

중요: 이전 발언에서 파악된 조건·키워드는 기본으로 유지하세요. 최신 발언이 이전 조건과
명백히 충돌하거나("다른 분야도 보여줘", "말고 다른 거", "그거 말고" 등) 새 조건을
언급할 때만 그 필드를 null로 되돌리거나 새 값으로 교체하세요. 최신 발언이 단순
진행 요청·의견(예: "공모전부터 정해야되는거 아냐?", "빨리 추천해줘")이라 특정
조건에 대한 언급이 없다면, 그 필드는 이전 발언에서 파악된 값을 그대로 유지하세요.

스키마:
{{
  "keyword": "검색 키워드(분야·카테고리 위주 한국어 1~3단어)" 또는 null,  // 분야 정보가 정말 없으면 null
  "category": ["분야1", "분야2"] 또는 null,     // 반드시 다음 중에서만 골라라: {category_options}
  "target": ["대학생", "일반인"] 또는 null,      // 반드시 다음 중에서만 골라라: {target_options}
  "has_prize": true, false, 또는 null,          // 금액과 상관없이 "상금이 있는지"만 물었으면 true
  "min_prize": 정수 또는 null,                  // 구체적 최소 금액을 말했거나, 상대 표현("더 큰")을 위 기준값으로 환산할 수 있을 때
  "participation_type": "individual" 또는 "team" 또는 null,
  "is_career_benefit": true, false, 또는 null,  // 취업·인턴 연계를 원한다고 했으면
  "deadline_before": "YYYY-MM-DD" 또는 null,     // 이 날짜 전 마감만 원하면(상대 표현은 오늘 날짜 기준 환산)
  "deadline_after": "YYYY-MM-DD" 또는 null       // 마감까지 여유가 필요하면("준비 기간 3주는 필요해" → 오늘 + 3주)
}}

이전 발언(참고용 — 최신 발언과 충돌하면 무시): {earlier}
최신 발언(가장 중요): {latest}

JSON:"""

    try:
        client = llm or GeminiClient()
        raw = client.generate(prompt).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        keyword_raw = data.pop("keyword", None)
        filters = CompetitionSearchFilters.model_validate(data)
    except Exception:
        return None, CompetitionSearchFilters()

    keyword = (keyword_raw or "").strip() if isinstance(keyword_raw, str) else ""
    if not keyword or keyword == "없음":
        return None, filters
    return keyword[:50], filters


def apply_filters(
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
        if filters.deadline_after is not None and c.deadline and c.deadline <= filters.deadline_after:
            return False
        return True

    return [c for c in results if keep(c)]
