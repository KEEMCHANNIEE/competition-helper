"""pgvector 의미 검색 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

흐름:
    1. ``LLMClient.embed(query)`` 로 쿼리 임베딩.
    2. App DB ``embeddings`` 테이블에서 pgvector 코사인/유클리드 top-k 검색.
       (SQLAlchemy + pgvector: ``Embedding.embedding.cosine_distance(vec)`` 정렬)
    3. 매칭된 competition_id 로 공모전 정보를 채워 ``CompetitionOut`` 리스트 반환.

고려사항:
    - 성능을 위해 ivfflat 인덱스 필요(마이그레이션에서 생성).
    - 결과는 최대 ``k`` 건. 후보가 부족하면 있는 만큼만.
"""

from __future__ import annotations

from contest_helper_core.schemas import CompetitionOut


def semantic_search(query: str, k: int) -> list[CompetitionOut]:
    """쿼리와 의미적으로 유사한 공모전 top-k 를 반환한다.

    Args:
        query: 자연어 검색 쿼리(예: 사용자 관심사·스킬 결합).
        k: 반환할 최대 결과 수.

    Returns:
        유사도 내림차순 ``CompetitionOut`` 리스트(최대 ``k`` 건).
    """
    raise NotImplementedError("TODO(AI 담당): rag.semantic_search 를 구현하세요.")
