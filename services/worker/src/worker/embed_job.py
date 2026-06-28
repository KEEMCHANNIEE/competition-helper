"""공모전 임베딩 적재 잡 (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

흐름:
    1. 공모전 DB(읽기 전용)에서 공모전 목록을 읽는다.
    2. 아직 ``embeddings`` 에 없는(증분) 건만 골라 텍스트를 만든다.
    3. ``LLMClient.embed(text)`` 로 벡터화(배치 권장).
    4. App DB ``embeddings`` 테이블에 upsert.

고려사항:
    - 이미 임베딩된 competition_id 는 skip(증분).
    - 공모전 DB 와 App DB 는 엔진/세션을 절대 공유하지 않는다.
"""

from __future__ import annotations


def run() -> int:
    """신규 공모전을 임베딩해 embeddings 테이블에 적재한다.

    Returns:
        새로 적재한(임베딩한) 공모전 수.
    """
    raise NotImplementedError("TODO(AI 담당): embed_job.run 을 구현하세요.")
