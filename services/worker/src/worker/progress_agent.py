"""워크스페이스 에이전트 — 진행 상황 평가.

INPUT 1(요약 정보): 유진(search_agent) 쪽 "대화 요약 DB"는 아직 계획 단계라 없다.
대신 이 워크스페이스의 대화 기록(``Conversation``/``Message``)을 직접 모아
"사용자가 공부/준비한 내용"의 임시 대체 입력으로 쓴다. 나중에 진짜 요약 DB가
생기면 ``_load_study_summary`` 자리만 그걸로 바꿔 끼우면 된다.

INPUT 2(공모전 정보): ``mcp_tools.registry`` 의 ``get_competition_detail`` 도구.

CORE(이 모듈): 위 두 입력 + 이 워크스페이스의 ``Task`` 완료 비율을 합쳐
① 수치 진행률(%) 과 ② LLM 코멘트를 만들고, ``save_progress`` 도구로
"워크스페이스 DB"(``workspace_progress``)에 실제로 저장한다.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import Conversation, Message, Task, Workspace
from contest_helper_core.schemas import ProgressOut
from worker.llm import GeminiClient, LLMClient
from worker.mcp_tools.registry import build_registry

# 대화 기록에서 "공부한 내용" 텍스트로 가져올 최근 메시지 수(프롬프트 길이 제한용).
_HISTORY_LIMIT = 30


def evaluate_progress(
    workspace_id: int,
    user_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    llm: LLMClient | None = None,
    tools: dict | None = None,
) -> ProgressOut:
    """워크스페이스의 사용자별 진행 상황을 평가하고 저장한다.

    Args:
        workspace_id: 평가할 워크스페이스 id.
        user_id: 평가받는 사용자 id.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.
        llm: LLM 클라이언트(미지정 시 ``GeminiClient``). 테스트는 가짜 주입.
        tools: mcp 도구 레지스트리(미지정 시 ``build_registry()``).

    Returns:
        저장된 ``ProgressOut`` (percent, comment, task_done/total 포함).
    """
    if session_factory is None:
        session_factory = _default_session_factory()
    if tools is None:
        tools = build_registry()

    task_done, task_total = _load_task_progress(workspace_id, user_id, session_factory)
    percent = round(task_done / task_total * 100) if task_total else 0

    competition = _load_competition(workspace_id, tools, session_factory)
    study_summary = _load_study_summary(workspace_id, user_id, session_factory)

    comment = _generate_comment(
        percent=percent,
        task_done=task_done,
        task_total=task_total,
        competition=competition,
        study_summary=study_summary,
        llm=llm,
    )

    return tools["save_progress"](
        workspace_id=workspace_id,
        user_id=user_id,
        percent=percent,
        comment=comment,
        task_done=task_done,
        task_total=task_total,
        session_factory=session_factory,
    )


def _load_task_progress(
    workspace_id: int,
    user_id: int,
    session_factory: Callable[[], Session],
) -> tuple[int, int]:
    """(완료 수, 전체 수) 를 반환한다.

    이 사용자에게 배정된(assignee_id) 할 일이 있으면 그것만 세고,
    없으면(아직 담당자 분배 전) 워크스페이스 전체 할 일로 대체한다.
    """
    with session_factory() as session:
        all_tasks = (
            session.execute(select(Task).where(Task.workspace_id == workspace_id))
            .scalars()
            .all()
        )
    mine = [t for t in all_tasks if t.assignee_id == user_id]
    target = mine or all_tasks
    done = sum(1 for t in target if t.status == "done")
    return done, len(target)


def _load_competition(
    workspace_id: int,
    tools: dict,
    session_factory: Callable[[], Session],
):
    """워크스페이스가 준비하는 공모전 상세를 조회한다. 없거나 실패하면 None."""
    with session_factory() as session:
        ws = session.get(Workspace, workspace_id)
        contest_id = ws.contest_id if ws else None
    if contest_id is None:
        return None
    try:
        return tools["get_competition_detail"](contest_id)
    except NotImplementedError:
        # search_agent 파트가 아직 구현 전이어도 진행률 평가 자체는 막지 않는다.
        return None


def _load_study_summary(
    workspace_id: int,
    user_id: int,
    session_factory: Callable[[], Session],
) -> str:
    """워크스페이스 대화 기록을 시간순으로 이어붙여 "공부한 내용" 텍스트로 만든다."""
    with session_factory() as session:
        rows = (
            session.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.user_id == user_id,
                )
                .order_by(Message.created_at, Message.id)
            )
            .scalars()
            .all()
        )
    recent = rows[-_HISTORY_LIMIT:]
    return "\n".join(f"{m.role}: {m.content}" for m in recent)


def _generate_comment(
    *,
    percent: int,
    task_done: int,
    task_total: int,
    competition,
    study_summary: str,
    llm: LLMClient | None,
) -> str:
    deadline_line = f"마감: {competition.deadline}" if competition and competition.deadline else "마감 정보 없음"
    prompt = f"""당신은 공모전 준비 워크스페이스의 진행 상황을 평가하는 코치입니다.

- 할 일 진행률: {task_done}/{task_total} 건 완료 ({percent}%)
- 공모전 정보: {competition.title if competition else "연결된 공모전 없음"} ({deadline_line})
- 최근 대화/준비 내용:
{study_summary or "(대화 기록 없음)"}

위 정보를 보고, 이 사용자의 준비 상황에 대한 코멘트를 2문장 이내로 작성해 주세요.
(순조로운지, 마감 대비 지연되고 있는지, 다음에 뭘 하면 좋을지 위주로)"""

    try:
        # LLM 클라이언트 생성(자격증명 등)도 실패할 수 있으므로 try 안에서 만든다.
        client = llm or GeminiClient()
        return client.generate(prompt)
    except Exception:
        return _fallback_comment(percent, task_total, competition)


def _fallback_comment(percent: int, task_total: int, competition) -> str:
    """LLM 호출이 실패했을 때 쓰는 규칙 기반 코멘트."""
    if task_total == 0:
        return "아직 등록된 할 일이 없어요. 먼저 계획을 세워보는 건 어때요?"

    deadline = competition.deadline if competition else None
    if deadline is not None:
        from datetime import date

        days_left = (deadline - date.today()).days
        if days_left <= 7 and percent < 50:
            return f"마감까지 {max(days_left, 0)}일 남았는데 진행률이 {percent}%예요. 서둘러야 해요!"

    if percent >= 80:
        return f"진행률 {percent}%, 거의 다 왔어요!"
    if percent >= 40:
        return f"진행률 {percent}%, 순조롭게 진행 중이에요."
    return f"진행률 {percent}%예요. 이번 주 할 일부터 하나씩 처리해봐요."


def _default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
