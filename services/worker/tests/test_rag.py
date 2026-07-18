"""rag.semantic_search 과제 계약 테스트 — 현재는 NotImplementedError 로 FAIL.

TODO(AI 담당): worker/rag.py 를 구현해 이 테스트를 통과시킬 것.
"""

from __future__ import annotations

import pytest
from contest_helper_core.schemas import CompetitionOut
from worker import rag

_SKIP_REASON = "실제 Gemini API/DB 호출 — mock 없인 CI 에서 멈춤. 구현 완료 후 skip 제거"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_semantic_search_returns_k_results():
    results = rag.semantic_search("AI 해커톤", k=3)
    assert isinstance(results, list)
    assert len(results) <= 3
    assert all(isinstance(c, CompetitionOut) for c in results)


