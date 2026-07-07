"""MCP 도구 레지스트리 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

에이전트가 사용할 도구들을 한 곳에 등록·노출한다. 초기엔 in-process(이름→호출가능)
매핑으로 충분하고, 후에 MCP 서버 스펙으로 확장한다.

기대 계약(테스트 기준):
    reg = build_registry()
    reg["search_competitions"]   # competitions.search_competitions
    reg["get_competition_detail"]
    reg["semantic_search"]       # semantic.semantic_search
    reg["create_tasks"]          # tasks.create_tasks (계획 → 워크스페이스 저장)

구현 가이드: 아래 TOOLS 목록의 (이름 → 함수)를 그대로 dict 로 만들면 된다.
새 도구(예: web_search)는 TOOLS 에 한 줄 추가만 하면 자동 노출된다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from worker.mcp_tools import (
    competitions,
    progress,
    semantic,
    tasks,
    web_search as web_search_mod,
)

# 에이전트가 쓸 in-process 도구 목록. build_registry 가 이걸 dict 로 노출한다.
# (build_registry 자체는 과제 stub 이지만, 등록 대상은 여기 한 곳에 모아 둔다.)
TOOLS: dict[str, Callable[..., Any]] = {
    "search_competitions": competitions.search_competitions,
    "get_competition_detail": competitions.get_competition_detail,
    "semantic_search": semantic.semantic_search,
    "create_tasks": tasks.create_tasks,
    "save_progress": progress.save_progress,
    "web_search": web_search_mod.web_search,
}


def build_registry() -> dict[str, Callable[..., Any]]:
    """도구 이름 → 호출 가능 객체 매핑을 만든다.

    Returns:
        최소 ``search_competitions``, ``get_competition_detail``,
        ``semantic_search``, ``create_tasks`` 키를 갖는 도구 레지스트리.
    """
    return dict(TOOLS)
