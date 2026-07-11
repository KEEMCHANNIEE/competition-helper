"""LLM 추상화 계층.

provider 교체(OpenAI 등)·관측(Langfuse 훅)을 이 추상화 뒤에서 흡수한다.
``agent``·``rag`` 는 구체 구현이 아니라 ``LLMClient`` 인터페이스에만 의존해야 한다.
"""

from __future__ import annotations

import typing
from abc import ABC, abstractmethod
from collections.abc import Callable

from google import genai

from contest_helper_core.config import Settings, get_settings

# gemini-2.5-flash 는 2026년 중 deprecated(404). gemini-flash-latest 는 과부하(503)가 잦아
# 가볍고 안정적인 flash-lite alias 사용(분류·짧은 생성엔 충분).
GENERATE_MODEL = "gemini-flash-lite-latest"
EMBED_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


def _with_real_annotations(fn: Callable) -> Callable:
    """도구 함수의 문자열 타입힌트를 실제 타입 객체로 바꿔 돌려준다.

    도구를 정의하는 모듈들이 ``from __future__ import annotations`` 를 쓰면 함수
    annotation 이 실제 타입이 아니라 문자열(``'str'``)이 된다. google-genai 의
    Automatic Function Calling 은 도구를 실행할 때 인자를 ``isinstance(값, 타입)``
    으로 검증하는데, 타입 자리에 문자열이 들어가면 ``isinstance() arg 2 must be a
    type`` 예외가 나서 "모든 도구 호출이 조용히 실패"한다. 여기서 미리
    ``get_type_hints`` 로 문자열을 실제 타입으로 풀어 그 문제를 막는다.
    """
    try:
        fn.__annotations__ = typing.get_type_hints(fn)
    except Exception:
        # 해석 실패 시(희귀) 원본 그대로 둔다 — 최소한 기존 동작은 유지.
        pass
    return fn


class LLMClient(ABC):
    """LLM provider 추상 인터페이스. agent/rag 는 이 타입에만 의존한다."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """프롬프트로 텍스트 생성(추천 이유 등)."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """텍스트를 임베딩 벡터(길이 EMBEDDING_DIM=768)로 변환."""
        raise NotImplementedError


class GeminiClient(LLMClient):
    """google-genai 기반 구현. Gemini API 키 또는 Vertex AI 경로를 설정으로 분기한다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.gemini_api_key:
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        else:
            self._client = genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.vertex_location,
            )

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=GENERATE_MODEL,
            contents=prompt,
        )
        return response.text

    def embed(self, text: str) -> list[float]:
        response = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config={"output_dimensionality": EMBEDDING_DIM},
        )
        return list(response.embeddings[0].values)

    def generate_with_tools(self, prompt: str, tools: list[Callable]) -> str:
        """도구(파이썬 함수) 목록을 넘겨, 필요할 때만 LLM이 알아서 호출하게 한다.

        google-genai의 Automatic Function Calling을 그대로 쓴다: 넘긴 함수의
        타입힌트·docstring으로 스펙을 자동 생성하고, 모델이 도구 호출을 요청하면
        SDK가 그 함수를 직접 실행해 결과를 다시 모델에 넣어준다. 우리 쪽에서
        "어떤 요청이면 어떤 도구를 쓸지" 미리 분기할 필요가 없다 — 도구의
        docstring이 곧 사용 기준이다.

        Args:
            prompt: 대화 맥락을 포함한 프롬프트.
            tools: LLM이 필요시 호출할 수 있는 파이썬 함수 목록.

        Returns:
            도구 호출까지 반영된 최종 답변 텍스트.
        """
        response = self._client.models.generate_content(
            model=GENERATE_MODEL,
            contents=prompt,
            config={"tools": [_with_real_annotations(fn) for fn in tools]},
        )
        return response.text
