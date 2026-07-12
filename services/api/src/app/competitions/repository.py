"""공모전 DB(읽기 전용) 접근 계층.

App DB 와 절대 엔진/세션을 공유하지 않는다(contest_helper_core.competition_db 사용).
SQL 은 항상 파라미터 바인딩한다.
"""

from __future__ import annotations

import json
from typing import Protocol

from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.schemas import CompetitionOut
from sqlalchemy import text

# 실제 소스 데이터의 status 값은 'ACTIVE'/'CLOSED' 이다(한글 '진행중'/'마감' 도 병행 허용).
_OPEN_STATUSES = "('진행중', 'ACTIVE')"


class CompetitionRepository(Protocol):
    """라우터가 의존하는 추상 인터페이스. 테스트는 FakeRepo 로 대체."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]: ...

    def get_detail(self, competition_id: int) -> dict | None: ...


class SqlCompetitionRepository:
    """실제 공모전 DB 를 읽는 구현."""

    def list_open(self, limit: int = 20) -> list[CompetitionOut]:
        """진행중인 공모전을 마감 임박순으로 반환.

        실제 소스 스키마: contests(end_date=마감일, homepage=외부링크, status).
        end_date/homepage 를 deadline/url 로 alias 해 CompetitionOut 에 매핑한다.
        """
        sql = text(
            f"""
            SELECT id, title, organizer, host,
                   category, target, keywords,
                   start_date,
                   end_date AS deadline,
                   homepage AS url,
                   poster_url, total_prize_amount,
                   participation_type, status
            FROM contests
            WHERE status IN {_OPEN_STATUSES}
            ORDER BY end_date ASC NULLS LAST
            LIMIT :limit
            """
        )
        with competition_session_factory()() as session:
            rows = session.execute(sql, {"limit": limit}).mappings()
            return [CompetitionOut.model_validate(dict(row)) for row in rows]

    def get_detail(self, competition_id: int) -> dict | None:
        """단일 공모전 상세(원본 description JSONB 포함)를 dict 로 반환. 없으면 None.

        워크스페이스 화면이 공모전 정보를 풍부하게 표시하기 위해 description(중첩 JSON)까지
        내려준다. 프론트가 그대로 파싱해 쓴다(정규화는 프론트에서).
        """
        sql = text(
            """
            SELECT id, title, organizer, host,
                   category, target, keywords,
                   start_date,
                   end_date AS deadline,
                   homepage AS url,
                   poster_url, total_prize_amount,
                   participation_type, status,
                   description
            FROM contests
            WHERE id = :id
            """
        )
        with competition_session_factory()() as session:
            row = session.execute(sql, {"id": competition_id}).mappings().first()
        if row is None:
            return None
        data = dict(row)
        # description 은 JSONB(dict) 또는 JSON 문자열일 수 있다 → 항상 dict 로 정규화.
        desc = data.get("description")
        if isinstance(desc, str):
            try:
                data["description"] = json.loads(desc)
            except (ValueError, TypeError):
                data["description"] = {}
        elif desc is None:
            data["description"] = {}
        return data
