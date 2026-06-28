"""의미 검색 도구 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

``rag.semantic_search`` 를 도구 인터페이스로 감싼다. 도구 시그니처는 안정적으로
두고, 내부 구현(임베딩·pgvector)은 rag 에 위임한다.
"""

from __future__ import annotations

from keenee_core.schemas import CompetitionOut


def semantic_search(query: str, k: int = 5) -> list[CompetitionOut]:
    """rag.semantic_search 위임 도구.

    Args:
        query: 자연어 검색 쿼리.
        k: 최대 결과 수.

    Returns:
        ``CompetitionOut`` 리스트(최대 ``k`` 건).
    """
    raise NotImplementedError("TODO(AI 담당): semantic.semantic_search 도구를 구현하세요.")
