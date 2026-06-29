"""공모전 DB(읽기 전용) 접근 계층.

App DB 와 절대 엔진/세션을 공유하지 않는다(contest_helper_core.competition_db 사용).
SQL 은 항상 파라미터 바인딩한다.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import text

from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.schemas import CompetitionOut


class CompetitionRepository(Protocol):
    """라우터가 의존하는 추상 인터페이스. 테스트는 FakeRepo 로 대체."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]: ...


class SqlCompetitionRepository:
    """실제 공모전 DB 를 읽는 구현."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]:
        """진행중인 공모전을 마감 임박순으로 반환.

        실제 소스 스키마: contests(end_date=마감일, homepage=외부링크, status=진행중/마감).
        end_date/homepage 를 deadline/url 로 alias 해 CompetitionOut 에 매핑한다.
        """
        sql = text(
            """
            SELECT id, title, organizer, host,
                   category, target, keywords,
                   start_date,
                   end_date AS deadline,
                   homepage AS url,
                   poster_url, total_prize_amount,
                   participation_type, status
            FROM contests
            WHERE status = '진행중'
            ORDER BY end_date ASC NULLS LAST
            LIMIT :limit
            """
        )
        with competition_session_factory()() as session:
            rows = session.execute(sql, {"limit": limit}).mappings()
            return [CompetitionOut.model_validate(dict(row)) for row in rows]
