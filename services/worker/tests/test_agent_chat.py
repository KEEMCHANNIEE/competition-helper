"""agent.chat 과제 계약 테스트 — 현재는 NotImplementedError 로 FAIL.

TODO(AI 담당): worker/agent.py 의 chat() 을 구현해 이 테스트를 통과시킬 것.
이 테스트는 대화형 에이전트의 기대 동작(계약)을 문서화한다.
"""

from __future__ import annotations

import pytest

from worker import agent


def test_chat_returns_assistant_text():
    # 구현 후: 대화 기록을 읽고 의도(추천/공부/계획)에 맞는 답변 문자열을 돌려줘야 한다.
    reply = agent.chat(conversation_id=1, user_id=1)
    assert isinstance(reply, str)
    assert reply  # 빈 문자열이 아니어야 함


def test_chat_currently_not_implemented():
    # 구현 완료 후 이 테스트는 삭제/교체한다(미구현 상태 가드).
    with pytest.raises(NotImplementedError):
        agent.chat(conversation_id=1, user_id=1)
