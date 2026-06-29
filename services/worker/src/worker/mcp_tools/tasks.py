"""계획 저장 도구 — create_tasks (과제 stub).

TODO(AI 담당): 이 모듈을 구현해 아래 테스트를 통과시킬 것.

계획 능력(DESIGN-V2 §2)의 "행동" 도구다. 에이전트가 주차별 할 일·역할 분담을
정리하면 이 도구로 워크스페이스에 ``Task`` 행을 **실제로 저장**한다.
("에이전트가 대화를 넘어 실제 쓰기까지" 하는 단계.)

구현 가이드:
    - App DB 에 쓴다(공모전 DB 는 읽기 전용이므로 사용 금지).
    - 각 ``TaskIn`` → ``Task(workspace_id=..., title, description, assignee_id, week_no)`` 로 저장.
    - 저장 후 PK 가 채워진 결과를 ``TaskOut`` 리스트로 반환.
    - 부분 실패를 피하려면 한 트랜잭션으로 묶을 것.
"""

from __future__ import annotations

from contest_helper_core.schemas import TaskIn, TaskOut


def create_tasks(workspace_id: int, tasks: list[TaskIn]) -> list[TaskOut]:
    """계획(할 일 목록)을 워크스페이스에 ``Task`` 행으로 저장한다.

    Args:
        workspace_id: 할 일이 속할 워크스페이스 id.
        tasks: 저장할 할 일 입력 리스트.

    Returns:
        저장되어 id 가 채워진 ``TaskOut`` 리스트.
    """
    raise NotImplementedError("TODO(AI 담당): create_tasks 를 구현하세요.")
