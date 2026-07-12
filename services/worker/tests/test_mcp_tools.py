"""mcp_tools 과제 계약 테스트 — 현재는 NotImplementedError 로 FAIL.

TODO(AI 담당): worker/mcp_tools/* 를 구현해 이 테스트를 통과시킬 것.
"""

from __future__ import annotations

from contest_helper_core.schemas import CompetitionOut
from worker.mcp_tools import competitions, registry, semantic


def test_registry_exposes_expected_tools():
    reg = registry.build_registry()
    assert isinstance(reg, dict)
    for name in ("search_competitions", "get_competition_detail", "semantic_search"):
        assert name in reg
        assert callable(reg[name])


def test_search_competitions_returns_competition_out_list():
    results = competitions.search_competitions(keyword="AI", limit=5)
    assert isinstance(results, list)
    assert all(isinstance(c, CompetitionOut) for c in results)


def test_get_competition_detail_returns_competition_out():
    detail = competitions.get_competition_detail(1)
    assert detail is None or isinstance(detail, CompetitionOut)


def test_semantic_search_tool_returns_competition_out_list():
    results = semantic.semantic_search("AI 해커톤", k=3)
    assert isinstance(results, list)
    assert all(isinstance(c, CompetitionOut) for c in results)


