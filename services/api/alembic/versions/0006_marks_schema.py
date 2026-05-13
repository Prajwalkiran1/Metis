"""marks schema for module 4

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-13

Tables: assessments, marks, grade_rules, marks_audit, guardian_links.

Three new Postgres enums:
- assessment_type        (cie1 | cie2 | cie3 | see | assignment | lab)
- assessment_state       (draft | open | locked)
- mark_state             (entered | locked)
- guardian_relationship  (father | mother | guardian | other)

Also extends the existing `user_role` enum with the value `parent` so
parent-of-student users can sign in via the existing M1 auth flow. The
value is added via `ALTER TYPE ... ADD VALUE IF NOT EXISTS` so re-runs
are idempotent. Postgres 12+ allows this inside a transaction; we don't
reference the new value until after commit so the standard alembic
transactional-DDL wrapper is fine.

Triggers: only tables with `updated_at` get the `set_updated_at` BEFORE
UPDATE trigger (function from 0001). `marks_audit` and `guardian_links`
are append-only.

`marks_audit` is distinct from the cross-cutting `audit_logs` table — it
stores value-level history (old → new per mark) so the FE edit-log
Dialog can render a per-mark timeline. `write_audit()` still fires for
every M4 write into `audit_logs` for the standard cross-cutting trail.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


TRIGGERED_TABLES = (
    "assessments",
    "marks",
    "grade_rules",
)


def _attach_updated_at_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER set_{table}_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def _drop_updated_at_trigger(table: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS set_{table}_updated_at ON {table};")


def upgrade() -> None:
    # Extend the existing user_role enum so the parent role can sign in.
    # IF NOT EXISTS keeps the migration idempotent on retry; the value is
    # only read after this transaction commits.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'parent'")

    # ── enums ────────────────────────────────────────────────────────────────
    assessment_type = postgresql.ENUM(
        "cie1", "cie2", "cie3", "see", "assignment", "lab",
        name="assessment_type",
    )
    assessment_type.create(op.get_bind(), checkfirst=True)

    assessment_state = postgresql.ENUM(
        "draft", "open", "locked", name="assessment_state"
    )
    assessment_state.create(op.get_bind(), checkfirst=True)

    mark_state = postgresql.ENUM("entered", "locked", name="mark_state")
    mark_state.create(op.get_bind(), checkfirst=True)

    guardian_relationship = postgresql.ENUM(
        "father", "mother", "guardian", "other", name="guardian_relationship"
    )
    guardian_relationship.create(op.get_bind(), checkfirst=True)

    # ── assessments ──────────────────────────────────────────────────────────
    op.create_table(
        "assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "course_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(name="assessment_type", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("max_marks", sa.Numeric(6, 2), nullable=False),
        sa.Column("weight_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("scheduled_date", sa.Date, nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="assessment_state", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "locked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "max_marks BETWEEN 0 AND 1000",
            name="ck_assessments_max_marks_range",
        ),
        sa.CheckConstraint(
            "weight_percent IS NULL OR weight_percent BETWEEN 0 AND 100",
            name="ck_assessments_weight_range",
        ),
    )
    op.create_index("ix_assessments_college_id", "assessments", ["college_id"])
    op.create_index(
        "ix_assessments_offering_type",
        "assessments",
        ["course_offering_id", "type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_assessments_offering_type_name_active",
        "assessments",
        ["course_offering_id", "type", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── marks ────────────────────────────────────────────────────────────────
    # One row per (assessment, student). Mutable in place; correction trail
    # lives in marks_audit. NOT soft-deleted — deleting marks would lose
    # historical grade context. Cap of 1000 is a sanity floor; the real
    # ceiling (assessment.max_marks) is checked at service layer.
    op.create_table(
        "marks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("marks_obtained", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "is_absent",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="mark_state", create_type=False),
            nullable=False,
            server_default=sa.text("'entered'"),
        ),
        sa.Column(
            "entered_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "last_modified_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(is_absent = true AND marks_obtained IS NULL) "
            "OR (is_absent = false AND marks_obtained IS NOT NULL)",
            name="ck_marks_absent_xor_value",
        ),
        sa.CheckConstraint(
            "marks_obtained IS NULL OR marks_obtained BETWEEN 0 AND 1000",
            name="ck_marks_obtained_sanity_range",
        ),
    )
    op.create_index("ix_marks_college_id", "marks", ["college_id"])
    op.create_index(
        "uq_marks_assessment_student",
        "marks",
        ["assessment_id", "student_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_marks_student_assessment",
        "marks",
        ["student_user_id", "assessment_id"],
    )

    # ── grade_rules ──────────────────────────────────────────────────────────
    # Per (course_offering, assessment_type). Replace-by-upsert on PUT; no
    # soft delete (rules are a current-state lookup, not an audit trail).
    op.create_table(
        "grade_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "course_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=False,
        ),
        sa.Column(
            "assessment_type",
            postgresql.ENUM(name="assessment_type", create_type=False),
            nullable=False,
        ),
        sa.Column("weight_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "passing_threshold_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("40.0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "weight_percent BETWEEN 0 AND 100",
            name="ck_grade_rules_weight_range",
        ),
        sa.CheckConstraint(
            "passing_threshold_percent BETWEEN 0 AND 100",
            name="ck_grade_rules_threshold_range",
        ),
    )
    op.create_index("ix_grade_rules_college_id", "grade_rules", ["college_id"])
    op.create_index(
        "uq_grade_rules_offering_type",
        "grade_rules",
        ["course_offering_id", "assessment_type"],
        unique=True,
    )

    # ── marks_audit ──────────────────────────────────────────────────────────
    # Append-only. Captures the actual value mutation (old/new JSONB) so the
    # FE edit-log Dialog can render a per-mark history. Distinct from
    # audit_logs, which captures the cross-cutting actor/action trail.
    op.create_table(
        "marks_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "mark_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("reason", sa.String(400), nullable=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_marks_audit_college_id", "marks_audit", ["college_id"]
    )
    op.create_index(
        "ix_marks_audit_mark_created",
        "marks_audit",
        ["mark_id", "created_at"],
    )
    op.create_index(
        "ix_marks_audit_assessment_created",
        "marks_audit",
        ["assessment_id", "created_at"],
    )

    # ── guardian_links ───────────────────────────────────────────────────────
    # Read-only mapping: a `parent`-role user is verified-linked to one or
    # more `student`-role users. Admin-managed for now; parent self-signup
    # is deferred. `verified_at` is the gate that allows the parent to see
    # the linked student's marks.
    op.create_table(
        "guardian_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "relationship",
            postgresql.ENUM(name="guardian_relationship", create_type=False),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_guardian_links_college_id", "guardian_links", ["college_id"]
    )
    op.create_index(
        "uq_guardian_links_parent_student",
        "guardian_links",
        ["parent_user_id", "student_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_guardian_links_parent_verified",
        "guardian_links",
        ["parent_user_id"],
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )
    op.create_index(
        "ix_guardian_links_student_verified",
        "guardian_links",
        ["student_user_id"],
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )

    # ── attach updated_at triggers ───────────────────────────────────────────
    for table in TRIGGERED_TABLES:
        _attach_updated_at_trigger(table)


def downgrade() -> None:
    for table in TRIGGERED_TABLES:
        _drop_updated_at_trigger(table)

    op.drop_table("guardian_links")
    op.drop_table("marks_audit")
    op.drop_table("grade_rules")
    op.drop_table("marks")
    op.drop_table("assessments")

    postgresql.ENUM(name="guardian_relationship").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="mark_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="assessment_state").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="assessment_type").drop(
        op.get_bind(), checkfirst=True
    )

    # Note: cannot drop a value from a Postgres enum cleanly. The 'parent'
    # value stays on user_role; that's safe because no rows reference it
    # after a downgrade (parent users would have been deleted upstream).
