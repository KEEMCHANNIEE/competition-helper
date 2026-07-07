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

from pydantic import BaseModel
from sqlalchemy import text

from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.schemas import CompetitionOut

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
    limit: int = 20,
) -> list[CompetitionOut]:
    """키워드/마감 조건으로 공모전을 검색한다.

    Args:
        keyword: 제목·설명에 포함될 키워드(없으면 전체).
        open_only: 마감이 지나지 않은 건만.
        before: 이 날짜 이전 마감만(선택).
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

    if participation == "individual":
        conditions.append("participation_type IN ('individual', 'individual_or_team')")
    elif participation == "team":
        conditions.append("participation_type IN ('team', 'individual_or_team')")

    if before:
        conditions.append("end_date < :before")
        params["before"] = before

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
