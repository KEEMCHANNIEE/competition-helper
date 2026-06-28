"""공모전 DB(읽기 전용) 접근 계층.

App DB 와 절대 엔진/세션을 공유하지 않는다(keenee_core.competition_db 사용).
SQL 은 항상 파라미터 바인딩한다.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from sqlalchemy import text

from keenee_core.competition_db import competition_session_factory
from keenee_core.schemas import CompetitionOut


class CompetitionRepository(Protocol):
    """라우터가 의존하는 추상 인터페이스. 테스트는 FakeRepo 로 대체."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]: ...


class SqlCompetitionRepository:
    """실제 공모전 DB 를 읽는 구현."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]:
        """마감(deadline)이 지나지 않은 공모전을 마감 임박순으로 반환.

        # TODO: 실제 공모전 DB 스키마에 맞게 치환.
        # 아래는 competitions(id, title, deadline, organizer, url) 가정.
        # 실제 테이블/컬럼명이 확정되면 SQL 의 테이블명·컬럼명만 바꾸면 된다.
        """
        sql = text(
            """
            SELECT id, title, deadline, organizer, url
            FROM competitions
            WHERE deadline IS NULL OR deadline >= :today
            ORDER BY deadline ASC NULLS LAST
            LIMIT :limit
            """
        )
        with competition_session_factory()() as session:
            rows = session.execute(
                sql, {"today": date.today(), "limit": limit}
            ).mappings()
            return [CompetitionOut.model_validate(dict(row)) for row in rows]
