"""의미 검색 도구 — rag.semantic_search 위임."""

from __future__ import annotations

from worker.mcp_tools.competitions import CompetitionDetailOut


def semantic_search(query: str, k: int = 5) -> list[CompetitionDetailOut]:
    """rag.semantic_search 위임 도구.

    Args:
        query: 자연어 검색 쿼리.
        k: 최대 결과 수.

    Returns:
        CompetitionDetailOut 리스트(최대 k 건).
    """
    from worker import rag

    return rag.semantic_search(query, k)
