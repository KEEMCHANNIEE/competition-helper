"""공모전 탐색 라우터: GET /competitions?limit=."""

from __future__ import annotations

from contest_helper_core.schemas import CompetitionOut
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.competitions.repository import CompetitionRepository
from app.deps import get_competition_repo

router = APIRouter(tags=["competitions"])


@router.get("/competitions", response_model=list[CompetitionOut])
def list_competitions(
    limit: int = Query(20, ge=1, le=100),
    repo: CompetitionRepository = Depends(get_competition_repo),
) -> list[CompetitionOut]:
    """마감 안 지난 공모전 목록. 공모전 DB 다운 시 503 으로 폴백."""
    try:
        return repo.list_open(limit=limit)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="공모전 DB 를 사용할 수 없습니다.",
        ) from exc


@router.get("/competitions/{competition_id}")
def get_competition(
    competition_id: int,
    repo: CompetitionRepository = Depends(get_competition_repo),
) -> dict:
    """단일 공모전 상세(원본 description 포함). 워크스페이스 화면의 공모전 정보 표시에 사용.

    공유 계약 CompetitionOut 에는 description(중첩 JSON)이 없어, 여기선 dict 로 내려준다.
    프론트에서 정규화해 쓴다.
    """
    try:
        detail = repo.get_detail(competition_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="공모전 DB 를 사용할 수 없습니다.",
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="공모전을 찾을 수 없습니다.",
        )
    return detail
