"""v3: workspace_progress (워크스페이스 에이전트 진행 상황)

Revision ID: 0003_workspace_progress
Revises: 0002_v2_chat_tasks
Create Date: 2026-07-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_workspace_progress"
down_revision: str | None = "0002_v2_chat_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("task_done", sa.Integer(), nullable=False),
        sa.Column("task_total", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_workspace_progress_workspace_id", "workspace_progress", ["workspace_id"]
    )
    op.create_index(
        "ix_workspace_progress_user_id", "workspace_progress", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_progress_user_id", table_name="workspace_progress"
    )
    op.drop_index(
        "ix_workspace_progress_workspace_id", table_name="workspace_progress"
    )
    op.drop_table("workspace_progress")
