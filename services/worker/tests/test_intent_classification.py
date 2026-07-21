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


def test_classify_intent_parses_share_and_wrapup_llm_answers():
    assert agent._classify_intent(
        "저장 말고 유진한테만 공유해줘", llm=_CannedLLM("share")
    ) == {"intent": "share", "matched_on": "llm"}
    assert agent._classify_intent(
        "오늘은 여기까지만 할게", llm=_CannedLLM("wrapup")
    ) == {"intent": "wrapup", "matched_on": "llm"}


def test_share_keyword_fallback_beats_log_when_llm_fails():
    # "저장"이 섞여 있어도 "~한테만 공유"가 핵심이면 log 가 아니라 share.
    result = agent._classify_intent("저장 말고 유진한테만 공유해줘", llm=_BoomLLM())
    assert result == {"intent": "share", "matched_on": "keyword"}


def test_wrapup_keyword_fallback_when_llm_fails():
    result = agent._classify_intent("오늘은 여기까지만 할게", llm=_BoomLLM())
    assert result == {"intent": "wrapup", "matched_on": "keyword"}
