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
    pending = bool(rows) and rows[-1].role == "user"

    return ChatStateOut(
        conversation_id=conv.id,
        pending=pending,
        messages=messages,
    )
