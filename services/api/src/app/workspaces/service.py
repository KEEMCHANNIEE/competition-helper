"""워크스페이스/멤버십 비즈니스 로직 + 권한 체크.

권한 위반은 HTTPException(403), 미존재는 404 로 통일한다.
"""

from __future__ import annotations

import json

from contest_helper_core.models import (
    Conversation,
    Message,
    Recommendation,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from contest_helper_core.schemas import TaskIn
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def get_workspace_or_404(db: Session, workspace_id: int) -> Workspace:
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="워크스페이스를 찾을 수 없습니다.",
        )
    return ws


def is_member(db: Session, workspace_id: int, user_id: int) -> bool:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    return member is not None


def require_member(db: Session, workspace_id: int, user_id: int) -> None:
    if not is_member(db, workspace_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="워크스페이스 멤버만 접근할 수 있습니다.",
        )


def require_owner(db: Session, ws: Workspace, user_id: int) -> None:
    if ws.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="워크스페이스 소유자만 가능합니다.",
        )


def create_workspace(
    db: Session, *, name: str, owner: User, contest_id: int | None = None
) -> Workspace:
    """팀 생성. 생성자를 owner 로 두고 멤버로도 등록한다."""
    ws = Workspace(name=name, owner_id=owner.id, contest_id=contest_id)
    db.add(ws)
    db.flush()  # ws.id 확보

    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
    db.commit()
    db.refresh(ws)
    return ws


def list_my_workspaces(db: Session, user_id: int) -> list[Workspace]:
    """사용자가 멤버인 워크스페이스를 최신순(id 내림차순)으로 반환한다."""
    return list(
        db.scalars(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.id.desc())
        ).all()
    )


def list_logs(db: Session, workspace_id: int) -> list[tuple[Message, User]]:
    """워크스페이스에 연결된 대화들의 실행 로그(role='log')를 작성자와 함께 최신순으로 반환한다.

    실행 로그는 새 테이블 없이 Message(role='log') 로 저장된다(스키마 재사용). 작성자는
    대화 소유자(conversation.user_id) 로 본다. (S-02 STEP02)
    """
    rows = db.execute(
        select(Message, User)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .where(
            Conversation.workspace_id == workspace_id,
            Message.role == "log",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
    ).all()
    return [(m, u) for m, u in rows]


def list_reports(db: Session, workspace_id: int) -> list[tuple[Message, User]]:
    """워크스페이스 주간 리포트(role='report') 목록을 작성자와 함께 최신순으로 반환한다. (S-03 STEP01)"""
    rows = db.execute(
        select(Message, User)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .where(
            Conversation.workspace_id == workspace_id,
            Message.role == "report",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
    ).all()
    return [(m, u) for m, u in rows]


def _format_report_body(overall: dict, member_data: list[dict]) -> str:
    """worker.format_weekly_report 와 동일한 텍스트 형식(프론트 파싱 규약)을 만든다."""
    lines = [f"전체 진행률: {overall['percent']}% ({overall['done']}/{overall['total']} 완료)"]
    if member_data:
        lines += ["", "[팀원별 진행률]"]
        lines += [
            f"- {m['name']}: {m['percent']}% ({m['done']}/{m['total']})"
            for m in member_data
        ]
    inc_lines: list[str] = []
    for m in member_data:
        inc = m["incomplete"]
        if not inc:
            continue
        if m["done"] == 0 and m["total"]:
            inc_lines.append(f"- {m['name']}: 전체 미완료")
        else:
            inc_lines.append(f"- {m['name']}: {', '.join(inc)}")
    if inc_lines:
        lines += ["", "[미완료]"] + inc_lines
    return "\n".join(lines)


def generate_weekly_report(db: Session, *, ws: Workspace) -> Message:
    """주간 리포트를 집계해 role='report' 메시지로 워크스페이스에 저장하고 반환한다. (S-03 STEP01)

    '주간 리포트 생성해줘' 채팅(worker._handle_report)과 같은 형식이며, 워크스페이스에서
    버튼으로 직접 생성하거나 매주 일요일 자정 cron 이 이 함수를 호출하도록 감쌀 수 있다.
    """
    tasks = list(db.scalars(select(Task).where(Task.workspace_id == ws.id)))
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    overall = {
        "percent": round(done / total * 100) if total else 0,
        "done": done,
        "total": total,
    }
    member_data: list[dict] = []
    for m, u in list_members(db, ws.id):
        mine = [t for t in tasks if t.assignee_id == u.id]
        md = sum(1 for t in mine if t.status == "done")
        member_data.append(
            {
                "name": u.name or u.email,
                "percent": round(md / len(mine) * 100) if mine else 0,
                "done": md,
                "total": len(mine),
                "incomplete": [t.title for t in mine if t.status != "done"],
            }
        )

    existing = (
        db.scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.workspace_id == ws.id, Message.role == "report")
        )
        or 0
    )
    week = existing + 1
    content = f"{week}주차 주간 리포트\n{_format_report_body(overall, member_data)}"

    # 리포트 Message 를 붙일 대화(없으면 소유자용으로 하나 생성).
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.workspace_id == ws.id)
        .order_by(Conversation.id.asc())
    )
    if conv is None:
        conv = Conversation(user_id=ws.owner_id, workspace_id=ws.id)
        db.add(conv)
        db.flush()
    msg = Message(conversation_id=conv.id, role="report", content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _latest_proposal(db: Session, workspace_id: int) -> Message | None:
    """워크스페이스에서 가장 최근 제안(role='proposal') 메시지를 반환한다(없으면 None)."""
    return db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.workspace_id == workspace_id, Message.role == "proposal")
        .order_by(Message.id.desc())
    )


def get_pending_proposal(db: Session, workspace_id: int) -> dict | None:
    """미적용(applied=false) 최신 제안의 payload(dict)를 반환한다(없으면 None)."""
    msg = _latest_proposal(db, workspace_id)
    if msg is None:
        return None
    try:
        payload = json.loads(msg.content)
    except (json.JSONDecodeError, TypeError):
        return None
    return None if payload.get("applied") else payload


def apply_latest_proposal(db: Session, *, ws: Workspace) -> dict | None:
    """최신 제안을 실제 계획에 반영한다(팀장 승인 후 호출). (S-03 STEP02)

    reschedule: 지정된 미완료 Task 들의 week_no 를 +1 하여 다음 주로 이동한다.
    반영 후 제안을 applied=true 로 표시(중복 반영 방지). 반영할 제안이 없으면 None.
    """
    msg = _latest_proposal(db, ws.id)
    if msg is None:
        return None
    try:
        payload = json.loads(msg.content)
    except (json.JSONDecodeError, TypeError):
        return None
    if payload.get("applied"):
        return {"already_applied": True, "label": payload.get("label", "")}

    moved = 0
    if payload.get("kind") == "reschedule":
        for tid in payload.get("task_ids", []):
            t = db.get(Task, tid)
            if t is not None and t.status != "done":
                t.week_no = (t.week_no or 1) + 1
                moved += 1

    payload["applied"] = True
    msg.content = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return {
        "moved": moved,
        "member_id": payload.get("member_id"),
        "member": payload.get("member_name", ""),
        "label": payload.get("label", ""),
    }


def create_notification(
    db: Session, *, workspace_id: int, recipient_id: int, text: str
) -> None:
    """수신자에게 알림을 보낸다(role='notify' 메시지, 스키마 재사용). (S-03 STEP03)

    수신자가 이 워크스페이스에서 소유한 대화(없으면 생성)에 알림 메시지를 남긴다.
    수신자가 채팅/워크스페이스에 입장하면 미확인 알림으로 조회된다.
    """
    conv = db.scalar(
        select(Conversation)
        .where(
            Conversation.workspace_id == workspace_id,
            Conversation.user_id == recipient_id,
        )
        .order_by(Conversation.id.asc())
    )
    if conv is None:
        conv = Conversation(user_id=recipient_id, workspace_id=workspace_id)
        db.add(conv)
        db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            role="notify",
            content=json.dumps({"text": text, "read": False}, ensure_ascii=False),
        )
    )
    db.commit()


def list_user_notifications(db: Session, user_id: int) -> list[dict]:
    """사용자의 미확인 알림(role='notify', read=false)을 최신순으로 반환한다."""
    rows = db.scalars(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Message.role == "notify")
        .order_by(Message.id.desc())
    ).all()
    out: list[dict] = []
    for m in rows:
        try:
            payload = json.loads(m.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("read"):
            continue
        out.append({"id": m.id, "text": payload.get("text", "")})
    return out


def mark_user_notifications_read(db: Session, user_id: int) -> int:
    """사용자의 모든 알림을 확인 처리(read=true)한다. 반영 건수 반환."""
    rows = db.scalars(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Message.role == "notify")
    ).all()
    n = 0
    for m in rows:
        try:
            payload = json.loads(m.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not payload.get("read"):
            payload["read"] = True
            m.content = json.dumps(payload, ensure_ascii=False)
            n += 1
    db.commit()
    return n


def list_members(db: Session, workspace_id: int) -> list[tuple[WorkspaceMember, User]]:
    """워크스페이스 멤버 목록을 (멤버, 사용자) 쌍으로 반환한다(id 순)."""
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.id.asc())
    ).all()
    return [(m, u) for m, u in rows]


def shares_workspace(db: Session, user_a: int, user_b: int) -> bool:
    """두 사용자가 같은 워크스페이스의 멤버인지 확인한다(데모 세션 전환 권한 체크용)."""
    if user_a == user_b:
        return True
    a_ws = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_a)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == user_b,
            WorkspaceMember.workspace_id.in_(a_ws),
        )
    )
    return member is not None


# 데모용 팀 구성(팀원 전환 스위치를 위한 시드). 실제 제품에선 이메일 초대 흐름을 쓴다.
# 소유자(현재 로그인 사용자) = 동영(팀장), 나머지 3명은 데모 사용자로 생성.
_DEMO_OWNER_NAME = "동영 (팀장)"
_DEMO_TEAM = [
    ("demo.yujin@conmate.local", "유진", "데이터 분석"),
    ("demo.chaewon@conmate.local", "채원", "기획"),
    ("demo.chaeeun@conmate.local", "채은", "디자인"),
]
# 이메일 → 데모 팀원 이름. 데모 계정으로 로그인한 상태에서 데모팀을 세팅해도
# 그 계정을 "동영 (팀장)"으로 덮어쓰지 않도록 판별에 쓴다.
_DEMO_NAMES = {email: name for email, name, _ in _DEMO_TEAM}


def ensure_demo_team(db: Session, *, ws: Workspace) -> None:
    """워크스페이스에 데모 팀원(B/C/D)을 추가하고, 할 일을 4명에게 배정하며
    완료율을 다양하게 세팅한다(S-03 주간 리포트 데모용). 이미 있으면 재사용.

    - 소유자(A)는 현재 로그인 사용자. B/C/D 는 데모 사용자로 생성.
    - 할 일을 [A, B, C, D] 라운드로빈 배정.
    - 완료율 예시: A=100%, B=50%, C=100%, D=0% (시나리오 S-03 과 동일 느낌).
    """
    # 1) 소유자(동영) 표기 정리 + 나머지 팀원 확보/등록.
    owner = db.get(User, ws.owner_id)
    if owner is not None:
        # owner 가 데모 팀원 계정(팀원 전환으로 로그인된 경우)이면 그 사람 이름을 지킨다.
        if owner.email in _DEMO_NAMES:
            owner.name = _DEMO_NAMES[owner.email]
        else:
            owner.name = _DEMO_OWNER_NAME
    member_ids = [ws.owner_id]
    for email, name, role in _DEMO_TEAM:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, interests=[], skills=[])
            db.add(user)
            db.flush()
        elif user.name != name:
            user.name = name  # 과거에 오염된 이름 자동 교정
        if not is_member(db, ws.id, user.id):
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
        member_ids.append(user.id)

    # 2) 할 일 라운드로빈 배정 + 완료율 세팅.
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.workspace_id == ws.id)
            .order_by(Task.week_no.asc(), Task.id.asc())
        ).all()
    )
    # 멤버별 완료 비율(A/B/C/D).
    done_ratio = {member_ids[0]: 1.0, member_ids[1]: 0.5, member_ids[2]: 1.0, member_ids[3]: 0.0}
    per_member: dict[int, list[Task]] = {uid: [] for uid in member_ids}
    for i, t in enumerate(tasks):
        uid = member_ids[i % len(member_ids)]
        t.assignee_id = uid
        per_member[uid].append(t)
    for uid, mine in per_member.items():
        ratio = done_ratio.get(uid, 0.0)
        cutoff = round(len(mine) * ratio)
        for j, t in enumerate(mine):
            t.status = "done" if j < cutoff else "todo"

    db.commit()


def add_member(
    db: Session,
    *,
    ws: Workspace,
    actor: User,
    email: str,
    role: str = "member",
) -> WorkspaceMember:
    """멤버 초대(owner 만). 대상 사용자 미존재 404, 중복 초대 409."""
    require_owner(db, ws, actor.id)

    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="초대할 사용자를 찾을 수 없습니다.",
        )

    if is_member(db, ws.id, target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 멤버입니다.",
        )

    member = WorkspaceMember(workspace_id=ws.id, user_id=target.id, role=role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def attach_recommendations(
    db: Session,
    *,
    ws: Workspace,
    actor: User,
    recommendation_ids: list[int],
) -> int:
    """추천을 팀에 저장(멤버만). 적용된 행 수를 반환."""
    require_member(db, ws.id, actor.id)

    rows = db.scalars(
        select(Recommendation).where(Recommendation.id.in_(recommendation_ids))
    ).all()
    for r in rows:
        r.workspace_id = ws.id
    db.commit()
    return len(rows)


def list_recommendations(db: Session, workspace_id: int) -> list[Recommendation]:
    return list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.workspace_id == workspace_id)
            .order_by(Recommendation.id.asc())
        ).all()
    )


def list_tasks(db: Session, workspace_id: int) -> list[Task]:
    """워크스페이스 할 일 목록. week_no, id 순으로 정렬한다."""
    return list(
        db.scalars(
            select(Task)
            .where(Task.workspace_id == workspace_id)
            .order_by(Task.week_no.asc(), Task.id.asc())
        ).all()
    )


def add_task(
    db: Session, *, ws: Workspace, actor: User, payload: TaskIn
) -> Task:
    """할 일 1건 추가(멤버만)."""
    require_member(db, ws.id, actor.id)

    task = Task(
        workspace_id=ws.id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        week_no=payload.week_no,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


_TASK_STATUSES = ("todo", "done")


def update_task_status(
    db: Session, *, ws: Workspace, actor: User, task_id: int, new_status: str
) -> Task:
    """할 일 1건의 완료 상태를 바꾼다(멤버만). new_status 는 "todo"/"done"만 허용."""
    require_member(db, ws.id, actor.id)
    if new_status not in _TASK_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status 는 {_TASK_STATUSES} 중 하나여야 합니다.",
        )

    task = db.scalar(
        select(Task).where(Task.id == task_id, Task.workspace_id == ws.id)
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="할 일을 찾을 수 없습니다.",
        )

    task.status = new_status
    db.commit()
    db.refresh(task)
    return task
