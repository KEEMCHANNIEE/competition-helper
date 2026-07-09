"""pgvector 의미 검색.

흐름:
    1. LLMClient.embed(query) 로 쿼리 임베딩.
    2. App DB embeddings 테이블에서 cosine_distance top-k 검색.
    3. competition_id 로 공모전 상세 조회 후 CompetitionDetailOut 리스트 반환.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Embedding
from worker.llm import GeminiClient
from worker.mcp_tools.competitions import CompetitionDetailOut, get_competition_detail


def semantic_search(query: str, k: int) -> list[CompetitionDetailOut]:
    """쿼리와 의미적으로 유사한 공모전 top-k 를 반환한다.

    Args:
        query: 자연어 검색 쿼리(예: 사용자 관심사·스킬 결합).
        k: 반환할 최대 결과 수.

    Returns:
        유사도 내림차순 CompetitionDetailOut 리스트(최대 k 건).
    """
    llm = GeminiClient()
    vec = llm.embed(query)

    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with session_factory() as session:
        rows = session.execute(
            select(Embedding)
            .order_by(Embedding.embedding.cosine_distance(vec))
            .limit(k)
        ).scalars().all()

    results: list[CompetitionDetailOut] = []
    for row in rows:
        detail = get_competition_detail(row.competition_id)
        if detail:
            results.append(detail)

    return results
