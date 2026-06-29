"""공모전 DB 읽기 도구 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

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

from datetime import date

from contest_helper_core.schemas import CompetitionOut


def search_competitions(
    keyword: str | None = None,
    *,
    open_only: bool = True,
    before: date | None = None,
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
    raise NotImplementedError("TODO(AI 담당): search_competitions 를 구현하세요.")


def get_competition_detail(competition_id: int) -> CompetitionOut | None:
    """단일 공모전 상세를 조회한다.

    Args:
        competition_id: 공모전 PK.

    Returns:
        ``CompetitionOut`` (없으면 None).
    """
    raise NotImplementedError("TODO(AI 담당): get_competition_detail 을 구현하세요.")
