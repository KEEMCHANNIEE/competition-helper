"""워크스페이스 에이전트 — 팀 적합도 평가.

팀원들의 관심사·스킬(``User.interests``/``skills``)과 이 워크스페이스가 준비하는
공모전의 지원자격·심사기준(``get_competition_detail``)을 LLM으로 종합해,
"우리 팀이 잘 할 수 있을까?" 질문에 대한 1회성 평가 텍스트를 만든다.

``progress_agent.evaluate_progress`` 와 달리 결과를 DB에 저장하지 않는다
(진행률처럼 누적 이력을 남길 이유가 없는, 그때그때의 대화형 답변이라서).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from contest_helper_core.db import get_engine
from contest_helper_core.models import User, Workspace, WorkspaceMember
from worker.llm import GeminiClient, LLMClient


def evaluate_team_fit(
    workspace_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
    tools: dict | None = None,
    llm: LLMClient | None = None,
) -> str:
    """워크스페이스 팀원 전체의 관심사·스킬을 공모전 요구사항과 비교 평가한다.

    Args:
        workspace_id: 평가할 워크스페이스 id.
        session_factory: 세션 팩토리(미지정 시 App DB). 테스트는 SQLite 팩토리 주입.
        tools: mcp 도구 레지스트리(미지정 시 ``build_registry()``).
        llm: LLM 클라이언트(미지정 시 ``GeminiClient``). 테스트는 가짜 주입.

    Returns:
        팀 적합도에 대한 자연어 평가 텍스트.
    """
    if session_factory is None:
        session_factory = _default_session_factory()
    if tools is None:
        from worker.mcp_tools.registry import build_registry

        tools = build_registry()

    members = _load_member_profiles(workspace_id, session_factory)
    if not members:
        return "아직 워크스페이스에 팀원이 없어요. 먼저 팀원을 초대해 주세요."

    competition = _load_competition(workspace_id, tools, session_factory)
    return _generate_assessment(members, competition, llm=llm)


def _load_member_profiles(
    workspace_id: int,
    session_factory: Callable[[], Session],
) -> list[dict]:
    with session_factory() as session:
        rows = (
            session.execute(
                select(User)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(WorkspaceMember.workspace_id == workspace_id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "name": u.name or u.email,
                "interests": u.interests or [],
                "skills": u.skills or [],
            }
            for u in rows
        ]


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
        return None


def _generate_assessment(members: list[dict], competition, *, llm: LLMClient | None = None) -> str:
    team_text = "\n".join(
        f"- {m['name']}: 관심사 {', '.join(m['interests']) or '없음'} / 스킬 {', '.join(m['skills']) or '없음'}"
        for m in members
    )

    if competition is None:
        comp_text = "연결된 공모전 정보 없음"
    else:
        comp_text = (
            f"{competition.title}\n"
            f"카테고리: {', '.join(competition.category) or '정보 없음'}\n"
            f"지원자격: {', '.join(competition.requirements) or '정보 없음'}\n"
            f"심사기준: {', '.join(competition.evaluation_criteria) or '정보 없음'}"
        )

    prompt = f"""당신은 공모전 준비 팀의 코치입니다. 아래 팀원 정보와 공모전 정보를 보고
이 팀이 이 공모전에서 얼마나 잘 할 수 있을지 평가해 주세요.

팀원:
{team_text}

공모전:
{comp_text}

다음 내용을 자연스러운 문장으로(제목 구분 없이) 4~6문장 이내로 작성하세요:
- 팀원 역량과 공모전 요구사항이 겹치는 강점
- 보완이 필요한 약점
- 종합 총평"""

    try:
        client = llm or GeminiClient()
        return client.generate(prompt)
    except Exception:
        return _fallback_assessment(members, competition)


def _fallback_assessment(members: list[dict], competition) -> str:
    names = ", ".join(m["name"] for m in members)
    if competition is None:
        return f"팀원({names})의 관심사·스킬은 확인했지만, 아직 연결된 공모전이 없어서 적합도를 판단하긴 어려워요."
    return f"팀원({names})이 {competition.title} 공모전을 준비하고 있어요. 지금은 상세 평가를 만들지 못했어요, 잠시 후 다시 물어봐 주세요."


def _default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
