"""agent._classify_intent 계약 테스트.

의도 분류는 LLM 이 맡고, LLM 이 실패하거나 애매하게 답하면 키워드 기반으로
폴백해야 한다.
"""

from __future__ import annotations

from worker import agent


class _CannedLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self._text


class _BoomLLM:
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise RuntimeError("LLM down")


def test_classify_intent_uses_llm_answer():
    result = agent._classify_intent("이거 좀 도와줘", llm=_CannedLLM("plan"))
    assert result == {"intent": "plan", "matched_on": "llm"}


def test_classify_intent_parses_noisy_llm_answer():
    # 모델이 단어만 달라고 해도 가끔 설명을 덧붙일 수 있음 — 포함 여부로 파싱.
    result = agent._classify_intent("이거 좀 도와줘", llm=_CannedLLM("답변: recommend 입니다."))
    assert result == {"intent": "recommend", "matched_on": "llm"}


def test_classify_intent_falls_back_to_keyword_when_llm_fails():
    result = agent._classify_intent("이번주 계획 짜줘", llm=_BoomLLM())
    assert result == {"intent": "plan", "matched_on": "keyword"}


def test_classify_intent_falls_back_when_llm_answer_unparseable():
    result = agent._classify_intent("이번주 계획 짜줘", llm=_CannedLLM("음... 잘 모르겠어요"))
    assert result == {"intent": "plan", "matched_on": "keyword"}


def test_classify_intent_returns_study_default_for_empty_text():
    result = agent._classify_intent("", llm=_BoomLLM())
    assert result == {"intent": "study", "matched_on": "default"}
