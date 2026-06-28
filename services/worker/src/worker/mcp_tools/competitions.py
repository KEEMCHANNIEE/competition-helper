"""공모전 DB 읽기 도구 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

공모전 DB 는 읽기 전용. ``keenee_core.competition_db.competition_session_factory`` 로
세션을 얻고, SQL 은 항상 파라미터 바인딩한다(인젝션 금지).
실제 테이블/컬럼명은 소스 DB 에 맞춰 치환 필요(C3).
"""

from __future__ import annotations

from datetime import date

from keenee_core.schemas import CompetitionOut


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
