"""MCP 도구 레지스트리 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

에이전트가 사용할 도구들을 한 곳에 등록·노출한다. 초기엔 in-process(이름→호출가능)
매핑으로 충분하고, 후에 MCP 서버 스펙으로 확장한다.

기대 계약(테스트 기준):
    reg = build_registry()
    reg["search_competitions"]   # competitions.search_competitions
    reg["get_competition_detail"]
    reg["semantic_search"]       # semantic.semantic_search
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_registry() -> dict[str, Callable[..., Any]]:
    """도구 이름 → 호출 가능 객체 매핑을 만든다.

    Returns:
        최소 ``search_competitions``, ``get_competition_detail``,
        ``semantic_search`` 키를 갖는 도구 레지스트리.
    """
    raise NotImplementedError("TODO(AI 담당): build_registry 를 구현하세요.")
