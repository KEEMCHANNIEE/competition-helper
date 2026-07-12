"""공모전 DB 읽기 도구.

공모전 DB 는 읽기 전용. ``contest_helper_core.competition_db.competition_session_factory`` 로
세션을 얻고, SQL 은 항상 파라미터 바인딩한다(인젝션 금지).

실제 소스 테이블 = ``contests`` (Supabase Postgres). 주요 컬럼:
  id, title, organizer, host, host_type,
  category TEXT[], target TEXT[], keywords TEXT[],
  start_date DATE, end_date DATE(=마감),
  homepage(=외부링크), poster_url,
  total_prize_amount, first_prize_amount,
  participation_type, team_config, is_career_benefit,
  requirements TEXT[], evaluation_criteria TEXT[],
  description JSONB, status VARCHAR(진행중/마감), created_at, updated_at
부가 출처 테이블 = ``contests_sources`` (source_site, source_url, views, scrap_count ...).
CompetitionOut 매핑: deadline=end_date, url=homepage.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.schemas import CompetitionOut
from pydantic import BaseModel
from sqlalchemy import text

# contests.category/target 에 실제로 쓰이는 값(2026-07-09 기준 데이터 조사). 필터 추출
# 프롬프트에서 이 목록을 후보로 제시해, LLM이 DB에 없는 비슷한 말을 지어내는 걸 막는다.
KNOWN_CATEGORIES = [
    "사진/영상", "기타", "기획/아이디어", "디자인", "문학",
    "광고/마케팅", "예술", "학술/논문", "과학/공학",
]
KNOWN_TARGETS = [
    "대상 제한 없음", "대학생", "초등학생", "대학원생", "일반인",
    "동 연령대 청소년", "어린이", "중학생", "고등학생", "기타",
    "직장인/일반인", "청소년", "지역 제한",
]
# target 이 이 값을 포함하면 어떤 target 필터를 걸어도 항상 통과시킨다(= 응모 제한 없음).
TARGET_NO_RESTRICTION = "대상 제한 없음"

_SELECT = """
    SELECT id, title, organizer, host,
           category, target, keywords,
           start_date, end_date, homepage, poster_url,
           total_prize_amount, participation_type, status
    FROM contests
"""

_SELECT_DETAIL = """
    SELECT id, title, organizer, host, host_type,
           category, target, keywords,
           start_date, end_date, homepage, poster_url,
           total_prize_amount, first_prize_amount,
           participation_type, team_config, is_career_benefit,
           requirements, evaluation_criteria,
           description, status
    FROM contests
"""


class CompetitionSearchFilters(BaseModel):
    """자연어 요청에서 추출한 구조화 검색 필터.

    언급 안 된 필드는 반드시 None 이어야 한다(= 그 조건으로는 걸러내지 않음).
    """

    category: list[str] | None = None
    target: list[str] | None = None
    has_prize: bool | None = None  # 금액 상관없이 "상금이 있는지"만 물었을 때
    min_prize: int | None = None  # 구체적인 최소 금액을 언급했을 때
    participation_type: str | None = None  # "individual" | "team"
    is_career_benefit: bool | None = None
    deadline_before: date | None = None


class CompetitionDetailOut(BaseModel):
    """에이전트 내부용 공모전 상세 정보. CompetitionOut 보다 풍부한 필드를 포함한다."""

    id: int
    title: str
    organizer: str | None = None
    host: str | None = None
    host_type: str | None = None
    category: list[str] = []
    target: list[str] = []
    keywords: list[str] = []
    start_date: date | None = None
    deadline: date | None = None
    url: str | None = None
    poster_url: str | None = None
    total_prize_amount: int | None = None
    first_prize_amount: int | None = None
    participation_type: str | None = None
    team_config: str | None = None
    is_career_benefit: bool | None = None
    requirements: list[str] = []
    evaluation_criteria: list[str] = []
    description: str | None = None
    status: str | None = None


def _parse_array(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_description(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        text = value.get("text") or value.get("content")
        return str(text) if text else json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        try:
            d = json.loads(value)
            if isinstance(d, dict):
                text = d.get("text") or d.get("content")
                return str(text) if text else json.dumps(d, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        return value
    return str(value)


def _row_to_out(row) -> CompetitionOut:
    return CompetitionOut(
        id=row.id,
        title=row.title,
        organizer=row.organizer,
        host=row.host,
        category=_parse_array(row.category),
        target=_parse_array(row.target),
        keywords=_parse_array(row.keywords),
        start_date=row.start_date,
        deadline=row.end_date,
        url=row.homepage,
        poster_url=row.poster_url,
        total_prize_amount=row.total_prize_amount,
        participation_type=row.participation_type,
        status=row.status,
    )


def _row_to_detail(row) -> CompetitionDetailOut:
    return CompetitionDetailOut(
        id=row.id,
        title=row.title,
        organizer=row.organizer,
        host=row.host,
        host_type=row.host_type,
        category=_parse_array(row.category),
        target=_parse_array(row.target),
        keywords=_parse_array(row.keywords),
        start_date=row.start_date,
        deadline=row.end_date,
        url=row.homepage,
        poster_url=row.poster_url,
        total_prize_amount=row.total_prize_amount,
        first_prize_amount=row.first_prize_amount,
        participation_type=row.participation_type,
        team_config=row.team_config,
        is_career_benefit=row.is_career_benefit,
        requirements=_parse_array(row.requirements),
        evaluation_criteria=_parse_array(row.evaluation_criteria),
        description=_parse_description(row.description),
        status=row.status,
    )


def search_competitions(
    keyword: str | None = None,
    *,
    open_only: bool = True,
    before: date | None = None,
    participation: str | None = None,
    filters: CompetitionSearchFilters | None = None,
    limit: int = 20,
) -> list[CompetitionOut]:
    """키워드/마감/구조화 필터 조건으로 공모전을 검색한다.

    Args:
        keyword: 제목·설명에 포함될 키워드(없으면 전체).
        open_only: 마감이 지나지 않은 건만.
        before: 이 날짜 이전 마감만(선택). ``filters.deadline_before`` 와 함께 쓰이면 더 이른 쪽이 적용된다.
        participation: "individual"/"team" (선택). ``filters.participation_type`` 과 함께 쓰이면 이 값이 우선한다.
        filters: 자연어 요청에서 추출한 구조화 필터(분야/대상/최소상금/취업연계/마감 등).
        limit: 최대 결과 수.

    Returns:
        ``CompetitionOut`` 리스트.
    """
    conditions: list[str] = []
    params: dict = {"limit": limit}

    if keyword:
        conditions.append(
            "(title ILIKE :kw OR category::text ILIKE :kw OR keywords::text ILIKE :kw)"
        )
        params["kw"] = f"%{keyword}%"

    if open_only:
        conditions.append("status IN ('진행중', 'ACTIVE')")

    effective_participation = participation or (filters.participation_type if filters else None)
    if effective_participation == "individual":
        conditions.append("participation_type IN ('individual', 'individual_or_team')")
    elif effective_participation == "team":
        conditions.append("participation_type IN ('team', 'individual_or_team')")

    effective_before = before or (filters.deadline_before if filters else None)
    if effective_before:
        conditions.append("end_date < :before")
        params["before"] = effective_before

    if filters and filters.category:
        # category 컬럼은 진짜 배열이 아니라 JSON 문자열(text)로 저장되어 있어 ILIKE OR로 매칭한다.
        cat_conditions = []
        for i, cat in enumerate(filters.category):
            key = f"f_cat_{i}"
            cat_conditions.append(f"category ILIKE :{key}")
            params[key] = f"%{cat}%"
        conditions.append("(" + " OR ".join(cat_conditions) + ")")

    if filters and filters.target:
        # target 은 실제 text[] 컬럼이라 overlap 연산자(&&)를 그대로 쓸 수 있다.
        # "대상 제한 없음"은 누구나 지원 가능하다는 뜻이라 항상 통과하도록 후보에 끼워 넣는다.
        conditions.append("target && :f_target")
        params["f_target"] = [*filters.target, TARGET_NO_RESTRICTION]

    if filters and filters.has_prize is True:
        conditions.append("total_prize_amount IS NOT NULL AND total_prize_amount > 0")
    elif filters and filters.has_prize is False:
        conditions.append("(total_prize_amount IS NULL OR total_prize_amount = 0)")

    if filters and filters.min_prize is not None:
        conditions.append("total_prize_amount >= :f_min_prize")
        params["f_min_prize"] = filters.min_prize

    if filters and filters.is_career_benefit is not None:
        conditions.append("is_career_benefit = :f_career")
        params["f_career"] = filters.is_career_benefit

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = text(f"{_SELECT} {where} ORDER BY end_date ASC NULLS LAST LIMIT :limit")

    factory = competition_session_factory()
    with factory() as session:
        rows = session.execute(sql, params).fetchall()

    return [_row_to_out(r) for r in rows]


def get_competition_detail(competition_id: int) -> CompetitionDetailOut | None:
    """단일 공모전 상세를 조회한다 (에이전트 내부용 풍부한 정보 포함).

    Args:
        competition_id: 공모전 PK.

    Returns:
        ``CompetitionDetailOut`` (없으면 None).
    """
    sql = text(f"{_SELECT_DETAIL} WHERE id = :id")

    factory = competition_session_factory()
    with factory() as session:
        row = session.execute(sql, {"id": competition_id}).fetchone()

    return _row_to_detail(row) if row else None


def compare_competitions(competition_ids: list[int]) -> list[CompetitionDetailOut]:
    """여러 공모전 상세를 한 번에 조회해 비교용으로 반환한다.

    존재하지 않는 id는 조용히 건너뛴다(부분 조회 실패로 전체를 막지 않음).

    Args:
        competition_ids: 비교할 공모전 PK 목록.

    Returns:
        조회된 ``CompetitionDetailOut`` 리스트(요청 순서 유지, 없는 id는 제외).
    """
    results: list[CompetitionDetailOut] = []
    for cid in competition_ids:
        detail = get_competition_detail(cid)
        if detail is not None:
            results.append(detail)
    return results
