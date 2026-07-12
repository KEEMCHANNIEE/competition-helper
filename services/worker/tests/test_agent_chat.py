"""agent.chat 계약 테스트.

대화형 에이전트의 기대 동작(계약)을 문서화한다.
"""

from __future__ import annotations

import pytest
from worker import agent

_SKIP_REASON = "agent.chat 이 실제 DB/Gemini API 호출 — mock 없인 CI 에서 멈춤. 주입 후 skip 제거"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_chat_returns_assistant_text():
    # 대화 기록을 읽고 의도(추천/공부/계획)에 맞는 답변 문자열을 돌려줘야 한다.
    reply = agent.chat(conversation_id=1, user_id=1)
    assert isinstance(reply, str)
    assert reply  # 빈 문자열이 아니어야 함
