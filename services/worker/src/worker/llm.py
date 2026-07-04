"""LLM 추상화 계층 .

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

provider 교체(OpenAI 등)·관측(Langfuse 훅)을 이 추상화 뒤에서 흡수한다.
``agent``·``rag`` 는 구체 구현이 아니라 ``LLMClient`` 인터페이스에만 의존해야 한다.

google-genai SDK 메모:
    - Gemini API 키 경로: Client(api_key=settings.gemini_api_key)
    - Vertex AI 경로:     Client(vertexai=True, project=..., location=...)
    배포 단계에 따라 둘 중 하나를 고른다(설정으로 분기).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from google import genai

from contest_helper_core.config import Settings, get_settings

GENERATE_MODEL = "gemini-2.5-flash"


class LLMClient(ABC):
    """LLM provider 추상 인터페이스. agent/rag 는 이 타입에만 의존한다."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """프롬프트로 텍스트 생성(추천 이유 등)."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """텍스트를 임베딩 벡터(길이 EMBEDDING_DIM)로 변환."""
        raise NotImplementedError


class GeminiClient(LLMClient):
    """google-genai 기반 기본 구현 (스켈레톤).

    TODO(AI 담당): 생성자에서 설정에 따라 Gemini API / Vertex 경로를 골라
    클라이언트를 만들고, generate/embed 를 채워 아래 테스트를 통과시킬 것.
    """

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
        raise NotImplementedError("TODO(AI 담당): GeminiClient.embed 구현 필요.")
