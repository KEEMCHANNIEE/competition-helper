"""agent.run 과제 계약 테스트 — 현재는 NotImplementedError 로 FAIL.

TODO(AI 담당): worker/agent.py 를 구현해 이 테스트를 통과시킬 것.
이 테스트는 기대 동작(계약)을 문서화한다.
"""

from __future__ import annotations

import pytest
from contest_helper_core.schemas import RecommendationOut, RecommendJobPayload
from worker import agent

_SKIP_REASON = "agent.run 이 실제 DB/Gemini API 호출 — mock 없인 CI 에서 멈춤. 구현 완료 후 skip 제거"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_run_returns_list_of_recommendation_out():
    payload = RecommendJobPayload(job_id="a-1", user_id=1, limit=3)
    result = agent.run(payload)
    assert isinstance(result, list)
    assert all(isinstance(r, RecommendationOut) for r in result)


@pytest.mark.skip(reason=_SKIP_REASON)
def test_run_respects_limit():
    payload = RecommendJobPayload(job_id="a-2", user_id=1, limit=2)
    result = agent.run(payload)
    assert len(result) <= payload.limit


