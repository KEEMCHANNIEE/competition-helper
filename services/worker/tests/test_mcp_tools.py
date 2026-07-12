"""mcp_tools 과제 계약 테스트 — 현재는 NotImplementedError 로 FAIL.

TODO(AI 담당): worker/mcp_tools/* 를 구현해 이 테스트를 통과시킬 것.
"""

from __future__ import annotations

import pytest
from contest_helper_core.schemas import CompetitionOut
from worker.mcp_tools import competitions, registry, semantic
from worker.mcp_tools.competitions import CompetitionDetailOut


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
    # get_competition_detail 은 에이전트 내부용으로 CompetitionOut 보다 풍부한
    # CompetitionDetailOut 을 반환한다(worker/mcp_tools/competitions.py 참고).
    detail = competitions.get_competition_detail(1)
    assert detail is None or isinstance(detail, CompetitionDetailOut)


@pytest.mark.skip(reason="semantic_search 가 실제 Gemini API/DB 호출 — mock 없인 CI 에서 멈춤. 구현 완료 후 skip 제거")
def test_semantic_search_tool_returns_competition_out_list():
    results = semantic.semantic_search("AI 해커톤", k=3)
    assert isinstance(results, list)
    assert all(isinstance(c, CompetitionOut) for c in results)


