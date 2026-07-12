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

from contest_helper_core.db import get_engine
from contest_helper_core.models import (
    Conversation,
    Message,
    Task,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceProgress,
)
from contest_helper_core.schemas import ProgressOut
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
    has_deadline = competition and competition.deadline
    deadline_line = f"마감: {competition.deadline}" if has_deadline else "마감 정보 없음"
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
            return f"마감까지 {max(days_left, 0)}일 남았는데 진행률이 {percent}%예요. 서둘러야 해요!"  # noqa: E501

    if percent >= 80:
        return f"진행률 {percent}%, 거의 다 왔어요!"
    if percent >= 40:
        return f"진행률 {percent}%, 순조롭게 진행 중이에요."
    return f"진행률 {percent}%예요. 이번 주 할 일부터 하나씩 처리해봐요."


def _default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


# --------------------------------------------------------------------------- #
# 주간 리포트 (S-03) — 신규 저장 없이 조회/집계만
# --------------------------------------------------------------------------- #


def weekly_report(
    workspace_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> dict:
    """워크스페이스의 주간 진행 리포트를 집계한다(신규 저장 없음, 읽기 전용). (S-03 STEP01)

    - 전체 진행률: 워크스페이스 Task 완료 비율.
    - 팀원별 진행률: 각 멤버의 최신 ``WorkspaceProgress`` 스냅샷(없으면 배정 Task 기준).
    - 미완료 할 일: todo 상태 Task 제목 목록.

    자동 실행(일요일 자정 cron)은 백엔드 배관이 이 함수를 호출하는 식으로 붙이면 된다.
    """
    if session_factory is None:
        session_factory = _default_session_factory()

    with session_factory() as session:
        tasks = (
            session.execute(select(Task).where(Task.workspace_id == workspace_id))
            .scalars()
            .all()
        )
        members = (
            session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id
                )
            )
            .scalars()
            .all()
        )
        snaps = (
            session.execute(
                select(WorkspaceProgress)
                .where(WorkspaceProgress.workspace_id == workspace_id)
                .order_by(WorkspaceProgress.computed_at.desc())
            )
            .scalars()
            .all()
        )
        member_ids = [m.user_id for m in members]
        users = (
            session.execute(select(User).where(User.id.in_(member_ids)))
            .scalars()
            .all()
        )
        name_by_id = {u.id: (u.name or u.email) for u in users}

    # user_id -> 최신 스냅샷(내림차순 정렬이므로 처음 본 게 최신).
    latest_by_user: dict[int, WorkspaceProgress] = {}
    for snap in snaps:
        latest_by_user.setdefault(snap.user_id, snap)

    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    overall_percent = round(done / total * 100) if total else 0

    member_reports = []
    for m in members:
        name = name_by_id.get(m.user_id, f"멤버 {m.user_id}")
        # 배정된 Task 기준을 우선 사용(스냅샷은 개인이 '진행 상황' 물었을 때만 생겨 편향됨).
        mine = [t for t in tasks if t.assignee_id == m.user_id]
        if mine:
            md = sum(1 for t in mine if t.status == "done")
            member_reports.append(
                {
                    "user_id": m.user_id,
                    "name": name,
                    "percent": round(md / len(mine) * 100),
                    "done": md,
                    "total": len(mine),
                    # 팀원별 미완료 할 일 제목(S-03 STEP01 "미완료" 섹션용).
                    "incomplete": [t.title for t in mine if t.status != "done"],
                }
            )
        else:
            snap = latest_by_user.get(m.user_id)
            member_reports.append(
                {
                    "user_id": m.user_id,
                    "name": name,
                    "percent": snap.percent if snap else 0,
                    "done": snap.task_done if snap else 0,
                    "total": snap.task_total if snap else 0,
                    "incomplete": [],
                }
            )

    incomplete = [t.title for t in tasks if t.status != "done"][:10]
    return {
        "workspace_id": workspace_id,
        "overall": {"percent": overall_percent, "done": done, "total": total},
        "members": member_reports,
        "incomplete_tasks": incomplete,
    }


def format_weekly_report(report: dict) -> str:
    """weekly_report 결과를 사람이 읽기 좋고 프론트가 파싱하기 쉬운 텍스트로 만든다.

    형식(주차 제목은 호출부에서 앞에 붙인다):
        전체 진행률: 63% (5/8 완료)

        [팀원별 진행률]
        - 동영 (팀장): 100% (2/2)
        ...

        [미완료]
        - 유진: 데이터 정리
        - 채은: 전체 미완료
    """
    o = report["overall"]
    lines = [f"전체 진행률: {o['percent']}% ({o['done']}/{o['total']} 완료)"]
    if report["members"]:
        lines += ["", "[팀원별 진행률]"]
        lines += [
            f"- {m['name']}: {m['percent']}% ({m['done']}/{m['total']})"
            for m in report["members"]
        ]
    # 미완료(팀원별): 일부만 남았으면 제목 나열, 하나도 못 했으면 "전체 미완료".
    inc_lines: list[str] = []
    for m in report["members"]:
        inc = m.get("incomplete") or []
        if not inc:
            continue
        if m["done"] == 0 and m["total"]:
            inc_lines.append(f"- {m['name']}: 전체 미완료")
        else:
            inc_lines.append(f"- {m['name']}: {', '.join(inc)}")
    if inc_lines:
        lines += ["", "[미완료]"] + inc_lines
    return "\n".join(lines)
