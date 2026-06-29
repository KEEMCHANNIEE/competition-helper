# 에이전트 개발 가이드 (참고용 예시 코드)

- 작성일: 2026-06-29
- 대상: 🟨 AI 담당 2명
- **주의:** 이 문서의 코드는 **이해를 돕는 참고 예시**다. 실제 과제 파일(`services/worker/src/worker/*`)을 어떻게 채우면 되는지 "감"을 주기 위한 것. 그대로 복붙하기보다 의미를 이해하고 본인 코드로 작성할 것. (출제자는 이 문서를 그대로 줄지/일부만 줄지 선택)

---

## 0. 4개 부품과 파일 매핑

```
두뇌(LLM)      = llm.py          : Gemini 호출 (생성·임베딩)
손(도구)       = rag.py, mcp_tools/ : LLM이 부르는 logical 함수 (벡터검색·DB검색)
도구 사용 규약  = function calling : 모델이 "이 도구 불러줘" → 코드가 실행 → 결과 반환
루프/조합      = agent.py        : 위를 엮어 추천 생성
```

**불변의 계약 (절대 바꾸지 말 것):** `agent.run(payload)` 은 반드시
`list[RecommendationOut]` 을 돌려줘야 한다. 저장·상태관리·큐는 `main.py`(배관)가 한다.

```python
# contest_helper_core/schemas.py 에 이미 정의됨 — 그대로 import 해서 쓴다
class RecommendationOut(BaseModel):
    competition_id: int
    title: str
    reason: str            # LLM이 생성한 "왜 너에게 맞는지"
    score: float | None = None
```

---

## 1. `llm.py` — 두뇌 (Gemini)

`google-genai` SDK 하나로 **Gemini API(키)** 와 **Vertex AI(서비스계정)** 둘 다 된다.
추상화 클래스 뒤에 두면 나중에 provider 교체도 쉽다.

```python
# services/worker/src/worker/llm.py  (예시)
from __future__ import annotations
from typing import Protocol
from google import genai
from contest_helper_core.config import get_settings


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...
    def embed(self, text: str) -> list[float]: ...


class GeminiClient:
    """google-genai 기반 기본 구현."""

    def __init__(self) -> None:
        s = get_settings()
        # 경로 1) 개발: API 키
        if s.gemini_api_key:
            self._client = genai.Client(api_key=s.gemini_api_key)
        # 경로 2) 클라우드: Vertex AI (서비스계정)
        else:
            self._client = genai.Client(
                vertexai=True, project=s.google_cloud_project, location=s.vertex_location
            )

    def generate(self, prompt: str) -> str:
        resp = self._client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        return resp.text or ""

    def embed(self, text: str) -> list[float]:
        # text-embedding-004 = 768차원 → models.EMBEDDING_DIM 과 일치
        resp = self._client.models.embed_content(
            model="text-embedding-004", contents=text
        )
        return list(resp.embeddings[0].values)
```

> 학습 포인트: `generate`/`embed` 한 곳에서 **Langfuse 추적**(토큰·지연)을 감싸면 LLM 관측이 된다(보너스 K2).

---

## 2. `rag.py` — 손 ① 의미 검색 (logical, pgvector)

검색 자체는 **결정적 코드**다. "의미 기반"인 이유는 키워드가 아니라 임베딩 벡터의
거리(코사인)로 가까운 걸 찾기 때문. pgvector가 `cosine_distance` 를 제공한다.

```python
# services/worker/src/worker/rag.py  (예시)
from __future__ import annotations
from sqlalchemy import select
from contest_helper_core.db import get_engine
from contest_helper_core.models import Embedding
from contest_helper_core.schemas import CompetitionOut
from worker.llm import GeminiClient
from worker.mcp_tools import competitions as comp_tools


def semantic_search(query: str, k: int) -> list[CompetitionOut]:
    # 1) 쿼리를 같은 임베딩 모델로 벡터화
    query_vec = GeminiClient().embed(query)

    # 2) App DB(embeddings)에서 코사인 거리로 가장 가까운 k개 competition_id
    from sqlalchemy.orm import Session
    with Session(get_engine()) as s:
        rows = s.execute(
            select(Embedding.competition_id)
            .order_by(Embedding.embedding.cosine_distance(query_vec))
            .limit(k)
        ).scalars().all()

    # 3) 공모전 상세는 읽기전용 소스(contests)에서 채워 CompetitionOut 로
    results: list[CompetitionOut] = []
    for cid in rows:
        detail = comp_tools.get_competition_detail(cid)
        if detail:
            results.append(detail)
    return results
```

> 포인트: **임베딩 = App DB(우리 것)**, **공모전 상세 = 공모전 DB(읽기전용)**. 두 DB를 섞지 않고 id로 이어 붙인다.

---

## 3. `mcp_tools/` — 손 ② DB 검색 도구

`contests` 테이블(Supabase)을 읽는 평범한 SQL 함수. **항상 파라미터 바인딩**(인젝션 금지).

```python
# services/worker/src/worker/mcp_tools/competitions.py  (예시)
from __future__ import annotations
from sqlalchemy import text
from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.schemas import CompetitionOut

_COLS = """
    id, title, organizer, host, category, target, keywords,
    start_date, end_date AS deadline, homepage AS url,
    poster_url, total_prize_amount, participation_type, status
"""

def search_competitions(keyword: str | None = None, *, limit: int = 20) -> list[CompetitionOut]:
    """키워드(제목 포함) + 진행중 공모전 검색. keyword 없으면 전체."""
    sql = text(
        f"SELECT {_COLS} FROM contests "
        "WHERE status = '진행중' "
        "AND (:kw IS NULL OR title ILIKE '%' || :kw || '%') "
        "ORDER BY end_date ASC NULLS LAST LIMIT :limit"
    )
    with competition_session_factory()() as s:
        rows = s.execute(sql, {"kw": keyword, "limit": limit}).mappings()
        return [CompetitionOut.model_validate(dict(r)) for r in rows]


def get_competition_detail(competition_id: int) -> CompetitionOut | None:
    sql = text(f"SELECT {_COLS} FROM contests WHERE id = :id")
    with competition_session_factory()() as s:
        row = s.execute(sql, {"id": competition_id}).mappings().first()
        return CompetitionOut.model_validate(dict(row)) if row else None
```

```python
# services/worker/src/worker/mcp_tools/registry.py  (예시)
from worker.mcp_tools.competitions import search_competitions, get_competition_detail
from worker.rag import semantic_search

# function calling 에 넘길 도구 목록 (google-genai 는 파이썬 함수를 그대로 도구로 받는다)
TOOLS = [search_competitions, get_competition_detail, semantic_search]
```

---

## 4. `agent.py` — 조합 (두 가지 방식)

### 🟢 레벨 1 — RAG 파이프라인 (코드가 순서를 정함, 먼저 이걸로 동작)

```python
# services/worker/src/worker/agent.py  (예시 — 레벨 1)
from __future__ import annotations
from sqlalchemy.orm import Session
from contest_helper_core.db import get_engine
from contest_helper_core.models import User
from contest_helper_core.schemas import RecommendationOut, RecommendJobPayload
from worker import rag
from worker.llm import GeminiClient


def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    llm = GeminiClient()

    # 1) 유저 관심사/스킬 로드
    with Session(get_engine()) as s:
        user = s.get(User, payload.user_id)
    profile = ", ".join((user.interests or []) + (user.skills or []))

    # 2) (logical) 의미 검색으로 후보 추림
    candidates = rag.semantic_search(profile, k=payload.limit)

    # 3) 후보마다 LLM이 "왜 맞는지" 이유 생성
    out: list[RecommendationOut] = []
    for c in candidates:
        prompt = (
            f"사용자 관심사: {profile}\n"
            f"공모전: {c.title} (주최: {c.organizer}, 분야: {c.category})\n"
            "이 공모전이 이 사용자에게 왜 잘 맞는지 한국어 2문장으로 설명해줘."
        )
        reason = llm.generate(prompt)
        out.append(RecommendationOut(competition_id=c.id, title=c.title, reason=reason))
    return out
```
- 검색 호출을 **코드**가 결정. 예측 가능·저렴. LLM은 글쓰기만.

### 🔵 레벨 2 — Tool-use 에이전트 (LLM이 도구 호출을 결정 = 진짜 에이전트)

```python
# services/worker/src/worker/agent.py  (예시 — 레벨 2, function calling)
from google.genai import types
from worker.mcp_tools.registry import TOOLS

def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    llm = GeminiClient()
    with Session(get_engine()) as s:
        user = s.get(User, payload.user_id)
    profile = ", ".join((user.interests or []) + (user.skills or []))

    prompt = (
        f"너는 공모전 추천 에이전트다. 사용자 관심사: {profile}.\n"
        f"제공된 도구로 적합한 공모전을 {payload.limit}개 찾고, 각각 추천 이유를 붙여라."
    )
    # google-genai: 파이썬 함수를 tools 로 주면 모델이 알아서 호출(자동 function calling)
    resp = llm._client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(tools=TOOLS),  # ← LLM이 search/semantic 호출 결정
    )
    # resp 에서 모델이 정리한 추천을 파싱해 RecommendationOut 리스트로 변환
    # (구조화 출력을 원하면 response_schema 로 JSON 강제 가능)
    ...
```
- 검색 함수는 레벨 1과 **똑같은 logical 코드**. 차이는 **호출 여부를 LLM이 결정**한다는 것. → MCP/function-calling 학습 목표 달성.

> 권장: **레벨 1로 먼저 초록불** → 그다음 같은 도구들을 레벨 2로 노출해 업그레이드.

---

## 5. `embed_job.py` — 선행 작업 (검색 대상 만들기)

RAG가 검색하려면 `embeddings` 테이블이 먼저 채워져 있어야 한다. 공모전 텍스트를
임베딩해 저장하는 잡(주기 실행 또는 1회 백필).

```python
# services/worker/src/worker/embed_job.py  (예시)
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from contest_helper_core.db import get_engine
from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.models import Embedding
from worker.llm import GeminiClient

def run() -> int:
    llm = GeminiClient()
    # 1) 공모전 DB에서 (id, 임베딩할 텍스트) 가져오기
    with competition_session_factory()() as cs:
        contests = cs.execute(text(
            "SELECT id, title, COALESCE(array_to_string(keywords, ' '), '') AS kw "
            "FROM contests WHERE status = '진행중'"
        )).mappings().all()

    # 2) App DB에 이미 있는 id 는 건너뛰고(증분), 없는 것만 임베딩 저장
    n = 0
    with Session(get_engine()) as s:
        existing = set(s.execute(select(Embedding.competition_id)).scalars())
        for c in contests:
            if c["id"] in existing:
                continue
            txt = f"{c['title']} {c['kw']}"
            s.add(Embedding(competition_id=c["id"], text=txt, embedding=llm.embed(txt)))
            n += 1
        s.commit()
    return n
```

---

## 6. 테스트로 완료 확인 (과제 채점 기준)

각 빈칸엔 이미 **실패 테스트**가 있다. 구현하면 초록불이 된다.

```bash
uv run pytest services/worker -v
# test_main_loop.py        : 배관 — 이미 통과해야 정상 (건드리지 말 것)
# test_rag.py / test_agent.py / test_mcp_tools.py : 지금 실패 → 구현하면 통과 = 과제 완료
```

---

## 7. 한 장 요약 (호출 흐름)

```
main.py(배관) ─► agent.run(payload)
                   │  user 로드
                   ├─ rag.semantic_search(profile, k)      ← 벡터검색(logical)
                   │     ├─ llm.embed(query)               ← 두뇌
                   │     └─ mcp_tools.get_competition_detail ← 공모전 DB 읽기
                   ├─ (레벨2) LLM이 mcp_tools 호출 결정      ← function calling
                   └─ llm.generate(prompt)  per 후보        ← "왜 맞는지" 생성
                   ▼
              list[RecommendationOut]  → main.py 가 DB 저장
```

검색 = logical 코드 / 판단·생성 = LLM. 이 분리만 기억하면 된다.
```
