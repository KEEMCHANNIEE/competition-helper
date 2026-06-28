"""추천 에이전트의 "머리" (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

이 함수는 worker.main 의 배관이 호출한다. 배관은 이미 완성돼 있으니
여러분은 ``run()`` 만 채우면 된다.

추천 루프 의사코드 (TECH-SPEC §3 AI):

    user = load_user(payload.user_id)                       # App DB 조회
    query = build_query(user.interests, user.skills)        # 관심사·스킬 → 쿼리
    candidates = semantic_search(query, k=payload.limit * 3)  # 후보 넉넉히
    recos = []
    for c in candidates[: payload.limit]:
        reason = llm.generate(prompt(user, c))              # "왜 너에게 맞는지"
        recos.append(
            RecommendationOut(
                competition_id=c.id, title=c.title, reason=reason
            )
        )
    return recos

고려사항:
    - 후보 0건이면 빈 리스트 반환(예외 X).
    - LLM 실패 시 폴백 이유 문자열로 대체(작업 전체를 실패시키지 말 것).
    - 반환은 반드시 ``list[RecommendationOut]`` 이고 길이는 ``payload.limit`` 이하.
    - DB 저장은 배관(worker.main.handle_job)이 한다. 여기서 직접 저장하지 말 것.
"""

from __future__ import annotations

from contest_helper_core.schemas import RecommendationOut, RecommendJobPayload


def run(payload: RecommendJobPayload) -> list[RecommendationOut]:
    """추천 작업 1건을 실행해 추천 결과 리스트를 반환한다.

    Args:
        payload: 작업 입력 (job_id, user_id, limit).

    Returns:
        길이 ``<= payload.limit`` 인 ``RecommendationOut`` 리스트.
    """
    raise NotImplementedError("TODO(AI 담당): agent.run 추천 루프를 구현하세요.")
