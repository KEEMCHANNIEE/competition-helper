"""대화 라우터.

POST /chat               : 대화 생성/이어가기 → user 메시지 기록 → 큐 위임 → 202
GET  /chat/{conv_id}     : 대화의 메시지 목록 + pending 플래그 폴링 → ChatStateOut

api 는 LLM 을 직접 호출하지 않는다(무거운 작업은 worker 로 위임).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contest_helper_core.models import Conversation, Message, User
from contest_helper_core.schemas import ChatStateOut, MessageOut
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.queue import enqueue_chat
from app.deps import get_current_user, get_db, get_redis
from app.workspaces import service as workspace_service

if TYPE_CHECKING:
    from redis import Redis

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    workspace_id: int | None = None


class ChatAccepted(BaseModel):
    conversation_id: int
    job_id: str


def _get_owned_conversation(
    db: Session, conversation_id: int, user_id: int
) -> Conversation:
    """대화를 조회하고 소유자가 맞는지 확인한다. 없으면 404."""
    conv = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    if conv is None or conv.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="대화를 찾을 수 없습니다.",
        )
    return conv


@router.post(
    "/chat",
    response_model=ChatAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_chat_turn(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ChatAccepted:
    """대화 한 턴 접수. conversation_id 없으면 새 대화를 만든다."""
    if payload.conversation_id is None:
        conv = Conversation(
            user_id=current_user.id, workspace_id=payload.workspace_id
        )
        db.add(conv)
        db.flush()  # conv.id 확보
    else:
        conv = _get_owned_conversation(
            db, payload.conversation_id, current_user.id
        )

    db.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content=payload.message,
        )
    )
    db.commit()

    conversation_id = conv.id
    job_id = enqueue_chat(
        db, redis, user_id=current_user.id, conversation_id=conversation_id
    )
    return ChatAccepted(conversation_id=conversation_id, job_id=job_id)


class ConversationSummary(BaseModel):
    conversation_id: int
    title: str
    messages: list[MessageOut]


@router.get("/chat", response_model=list[ConversationSummary])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationSummary]:
    """현재 사용자의 대화 목록(메시지 포함, 최신순). 프론트가 새로고침 후 대화를 복원한다.

    role=user/assistant 를 채팅 말풍선으로 노출한다(topic/log 는 내부 기록이므로 제외).
    recommend 는 프론트가 추천 카드를 다시 그릴 수 있도록 함께 내려준다.
    """
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.id.desc())
    ).all()

    result: list[ConversationSummary] = []
    for conv in convs:
        rows = db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.role.in_(["user", "assistant", "recommend"]),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).all()
        if not any(m.role in ("user", "assistant") for m in rows):
            continue  # 빈 대화는 건너뛴다
        title = next((m.content for m in rows if m.role == "user"), "새 대화")[:20]
        result.append(
            ConversationSummary(
                conversation_id=conv.id,
                title=title,
                messages=[MessageOut(role=m.role, content=m.content) for m in rows],
            )
        )
    return result


class NotificationOut(BaseModel):
    id: int
    text: str


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    """현재 사용자의 미확인 알림 목록. 채팅/워크스페이스 입장 시 조회한다. (S-03 STEP03)"""
    return [
        NotificationOut(id=n["id"], text=n["text"])
        for n in workspace_service.list_user_notifications(db, current_user.id)
    ]


@router.post("/notifications/read")
def read_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """현재 사용자의 알림을 모두 확인 처리한다."""
    n = workspace_service.mark_user_notifications_read(db, current_user.id)
    return {"read": n}


@router.get("/chat/{conversation_id}", response_model=ChatStateOut)
def get_chat_state(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatStateOut:
    """대화 상태 폴링. 마지막 메시지가 user 면 아직 답하는 중(pending)."""
    conv = _get_owned_conversation(db, conversation_id, current_user.id)

    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()

    messages = [MessageOut(role=m.role, content=m.content) for m in rows]
    # pending 판정은 실제 대화(user/assistant) 기준. recommend/log 같은 내부 기록이
    # user 메시지 뒤·assistant 답변 앞에 저장되는 순간 폴링이 "답변 완료"로 오인해
    # 텍스트 없는 카드만 그리는 레이스를 막는다.
    convo_rows = [m for m in rows if m.role in ("user", "assistant")]
    pending = bool(convo_rows) and convo_rows[-1].role == "user"

    return ChatStateOut(
        conversation_id=conv.id,
        pending=pending,
        messages=messages,
    )
