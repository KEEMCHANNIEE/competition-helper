"""공모전 임베딩 적재 잡.

흐름:
    1. 공모전 DB(읽기 전용)에서 공모전 목록을 읽는다.
    2. 아직 embeddings 에 없는(증분) 건만 골라 텍스트를 만든다.
    3. LLMClient.embed(text) 로 벡터화.
    4. App DB embeddings 테이블에 upsert.

고려사항:
    - 공모전 DB 와 App DB 는 엔진/세션을 절대 공유하지 않는다.
"""

from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from contest_helper_core.competition_db import competition_session_factory
from contest_helper_core.db import get_engine
from contest_helper_core.models import Embedding
from worker.llm import GeminiClient


def _parse_array(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        parsed = json.loads(value)
        return [str(v) for v in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _build_text(row) -> str:
    categories = _parse_array(row.category)
    keywords = _parse_array(row.keywords)

    description = ""
    if row.description:
        if isinstance(row.description, dict):
            description = str(row.description.get("text", ""))[:300]
        elif isinstance(row.description, str):
            try:
                d = json.loads(row.description)
                description = str(d.get("text", ""))[:300]
            except (json.JSONDecodeError, TypeError):
                description = row.description[:300]

    parts = [
        f"제목: {row.title}",
        f"주최: {row.organizer or row.host or ''}",
        f"카테고리: {', '.join(categories)}",
        f"키워드: {', '.join(keywords)}",
    ]
    if description:
        parts.append(f"설명: {description}")

    return "\n".join(parts)


def run() -> int:
    """신규 공모전을 임베딩해 embeddings 테이블에 적재한다.

    Returns:
        새로 적재한(임베딩한) 공모전 수.
    """
    comp_factory = competition_session_factory()
    with comp_factory() as session:
        rows = session.execute(
            text(
                "SELECT id, title, organizer, host, category, keywords, description "
                "FROM contests"
            )
        ).fetchall()

    if not rows:
        return 0

    app_session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with app_session_factory() as session:
        existing_ids = set(
            session.execute(select(Embedding.competition_id)).scalars().all()
        )

    new_rows = [r for r in rows if r.id not in existing_ids]
    if not new_rows:
        return 0

    llm = GeminiClient()
    count = 0

    with app_session_factory() as session:
        for row in new_rows:
            text_content = _build_text(row)
            try:
                vector = llm.embed(text_content)
            except Exception:
                continue

            session.merge(
                Embedding(
                    competition_id=row.id,
                    text=text_content,
                    embedding=vector,
                )
            )
            count += 1

        session.commit()

    return count


if __name__ == "__main__":
    n = run()
    print(f"임베딩 완료: {n}건")
