"""DuckDuckGo 웹 검색 도구.

DB에 없는 공모전 정보나 최신 정보를 외부 검색으로 보완한다.
API 키 없이 사용 가능하며, 에러 시 빈 리스트를 반환해 에이전트 흐름을 끊지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ddgs import DDGS


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def web_search(query: str, max_results: int = 5) -> list[SearchResult]:
    """DuckDuckGo로 웹 검색해 결과 리스트를 반환한다.

    Args:
        query: 검색 쿼리.
        max_results: 최대 결과 수.

    Returns:
        ``SearchResult`` 리스트. 검색 실패 시 빈 리스트.
    """
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=max_results)
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            )
            for r in raw
        ]
    except Exception:
        return []
