"""task assignments — split tasks into a header + per-assignee row

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-15

M10d shipped tasks as one row per (assigner, single assignee). Real
workflows need N assignees per task — paper-setting committees, multi-
invigilator CIEs. This migration:

1. Creates `task_assignments` (id PK, task_id FK, assignee_user_id FK,
   status, status_updated_at, decline_reason, timestamps, soft-delete).
   Partial unique index on (task_id, assignee_user_id) WHERE
   deleted_at IS NULL prevents duplicate assignments per task.

2. Backfills from the existing tasks rows — one assignment row per
   existing task, copying assigned_to_user_id + status +
   status_updated_at + decline_reason. The status enum on the new
   table reuses the task_status enum type the old column used.

3. Drops the assignee + status fields from tasks. The Task row now
   represents the assignment intent (what + when + by whom) and the
   per-assignee execution state lives entirely in task_assignments.
   Aggregate task state is derived at read time.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the new table.
    op.create_table(
        "task_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignee_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "accepted",
                "declined",
                "completed",
                "cancelled",
                name="task_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_task_assignments_task_id",
        "task_assignments",
        ["task_id"],
    )
    op.create_index(
        "ix_task_assignments_assignee_user_id",
        "task_assignments",
        ["assignee_user_id"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_assignments_task_assignee_active
        ON task_assignments (task_id, assignee_user_id)
        WHERE deleted_at IS NULL
        """
    )

    # 2. Backfill: one assignment per existing task.
    op.execute(
        """
        INSERT INTO task_assignments (
            id, task_id, assignee_user_id, status,
            status_updated_at, decline_reason,
            created_at, updated_at, deleted_at
        )
        SELECT
            gen_random_uuid(),
            t.id,
            t.assigned_to_user_id,
            t.status,
            t.status_updated_at,
            t.decline_reason,
            t.created_at,
            t.updated_at,
            t.deleted_at
        FROM tasks t
        WHERE t.deleted_at IS NULL
        """
    )

    # 3. Drop the per-assignee columns from tasks. The Task row now
    #    carries only the header (who assigned what, when due).
    op.drop_column("tasks", "assigned_to_user_id")
    op.drop_column("tasks", "status")
    op.drop_column("tasks", "status_updated_at")
    op.drop_column("tasks", "decline_reason")


def downgrade() -> None:
    # Restore tasks columns.
    op.add_column(
        "tasks",
        sa.Column(
            "assigned_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "accepted",
                "declined",
                "completed",
                "cancelled",
                name="task_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column("tasks", sa.Column("decline_reason", sa.Text(), nullable=True))

    # Restore best-effort: when a task had multiple assignments after
    # the migration, pick the most-recent assignment row by created_at.
    op.execute(
        """
        UPDATE tasks t
        SET assigned_to_user_id = sub.assignee_user_id,
            status = sub.status,
            status_updated_at = sub.status_updated_at,
            decline_reason = sub.decline_reason
        FROM (
            SELECT DISTINCT ON (task_id)
                task_id, assignee_user_id, status,
                status_updated_at, decline_reason
            FROM task_assignments
            WHERE deleted_at IS NULL
            ORDER BY task_id, created_at DESC
        ) sub
        WHERE t.id = sub.task_id
        """
    )
    # Now lock the restored columns to NOT NULL where the old contract
    # required it. assigned_to_user_id was NOT NULL; status was NOT NULL.
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN assigned_to_user_id SET NOT NULL"
    )
    op.execute("ALTER TABLE tasks ALTER COLUMN status SET NOT NULL")

    op.drop_index(
        "uq_task_assignments_task_assignee_active",
        table_name="task_assignments",
    )
    op.drop_index(
        "ix_task_assignments_assignee_user_id",
        table_name="task_assignments",
    )
    op.drop_index(
        "ix_task_assignments_task_id",
        table_name="task_assignments",
    )
    op.drop_table("task_assignments")
