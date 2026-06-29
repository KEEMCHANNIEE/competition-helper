"""v2: conversations, messages, workspaces.contest_id, tasks 확장

Revision ID: 0002_v2_chat_tasks
Revises: 0001_init
Create Date: 2026-06-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_v2_chat_tasks"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # workspaces 가 준비하는 공모전 연결.
    op.add_column(
        "workspaces",
        sa.Column("contest_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_workspaces_contest_id", "workspaces", ["contest_id"]
    )

    # tasks 풍부화: 설명·담당자·주차·생성시각.
    op.add_column("tasks", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "assignee_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column("tasks", sa.Column("week_no", sa.Integer(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])

    # 대화 세션.
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversations_user_id", "conversations", ["user_id"]
    )
    op.create_index(
        "ix_conversations_workspace_id", "conversations", ["workspace_id"]
    )

    # 대화 속 메시지.
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")

    op.drop_index("ix_tasks_assignee_id", table_name="tasks")
    op.drop_column("tasks", "created_at")
    op.drop_column("tasks", "week_no")
    op.drop_column("tasks", "assignee_id")
    op.drop_column("tasks", "description")

    op.drop_index("ix_workspaces_contest_id", table_name="workspaces")
    op.drop_column("workspaces", "contest_id")
