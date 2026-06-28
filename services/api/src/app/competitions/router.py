"""공모전 탐색 라우터: GET /competitions?limit=."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from keenee_core.schemas import CompetitionOut

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
