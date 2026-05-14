"""m2 rework — additive schema (new tables, enums, columns)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-15

Adds the schema scaffolding the M10 academic workflow + M3/M4 rework will
build on. No data is touched here — that's 0008. No constraint tightening —
that's 0009.

Key shape changes vs the original MIGRATION_PLAN.md (which assumed a
slightly different live schema):

- The `course_type` enum is REWRITTEN from (core|elective|lab) to
  (theory|lab|integrated|nptel). The plan's `ADD VALUE 'nptel'` alone
  would have left `core/elective` orphaned. The rewrite drops the old
  enum, creates the new one, and remaps existing rows in the same
  transaction (core→theory, elective→theory, lab→lab). The default
  server_default flips from 'core' to 'theory'.
- Tables that reference an academic term (semester_setups, hall_tickets,
  grade_cards, internal_deadlines) FK a new `academic_terms` table
  rather than the existing VARCHAR(20) `academic_term` columns on
  course_offerings/enrollments. Backfill happens in 0008; the VARCHAR
  columns stay nullable-FK-companion until a future cleanup migration.
- New tables that reference an enrollment use BIGINT, matching the
  existing `enrollments.id` BIGINT PK (the plan wrote UUID).
- `users.usn` already exists from the 0002 baseline at VARCHAR(40); we
  do NOT add it again. Format/uniqueness CHECKs land in 0009.
- HOD↔department link: this migration adds `users.hod_of_department_id`
  as the new canonical column. The legacy `departments.head_user_id`
  stays put for backfill in 0008 and code that still reads it; it gets
  deprecated in favor of the new column going forward.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


# Tables that have updated_at and need the set_updated_at BEFORE UPDATE trigger.
TRIGGERED_TABLES = (
    "academic_terms",
    "semester_setups",
    "elective_groups",
    "elective_group_options",
    "course_registrations",
    "lab_batches",
    "assessment_scheme_templates",
    "assessment_schemes",
    "assessment_scheme_components",
    "nptel_enrollments",
    "internal_deadlines",
    "cie_schedule",
    "tasks",
    "hall_tickets",
    "grade_cards",
    "see_results",
    "re_evaluations",
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
    # ── 1. Extend user_role enum with 'hod' ─────────────────────────────────
    # Idempotent. The new value is only referenced in 0008 backfill.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'hod'")

    # ── 2. New enums ────────────────────────────────────────────────────────
    term_type = postgresql.ENUM("regular", "fast_track", name="term_type")
    term_type.create(op.get_bind(), checkfirst=True)

    enrollment_state = postgresql.ENUM(
        "active", "dropped", "withdrawn", "migrated", name="enrollment_state"
    )
    enrollment_state.create(op.get_bind(), checkfirst=True)

    semester_setup_state = postgresql.ENUM(
        "draft", "published", "active", "archived", name="semester_setup_state"
    )
    semester_setup_state.create(op.get_bind(), checkfirst=True)

    assessment_component_kind = postgresql.ENUM(
        "cie", "aat", "lab", "assignment", "see", "nptel_assignment", "nptel_final",
        name="assessment_component_kind",
    )
    assessment_component_kind.create(op.get_bind(), checkfirst=True)

    task_status = postgresql.ENUM(
        "pending", "accepted", "declined", "completed", "cancelled",
        name="task_status",
    )
    task_status.create(op.get_bind(), checkfirst=True)

    task_type = postgresql.ENUM(
        "invigilation", "paper_setting", "evaluation", "makeup_exam", "other",
        name="task_type",
    )
    task_type.create(op.get_bind(), checkfirst=True)

    override_type = postgresql.ENUM(
        "attendance_condonation",
        "eligibility_override",
        "mark_lock_unlock",
        "student_migration",
        "lab_batch_reassignment",
        "assessment_scheme_unlock",
        "see_marks_correction",
        "makeup_cie_authorization",
        name="override_type",
    )
    override_type.create(op.get_bind(), checkfirst=True)

    grade_status = postgresql.ENUM(
        "pending", "released", "i_incomplete", "x_pending",
        "s", "a", "b", "c", "d", "e", "f", "na",
        name="grade_status",
    )
    grade_status.create(op.get_bind(), checkfirst=True)

    see_result_kind = postgresql.ENUM(
        "original", "re_evaluation", "makeup", name="see_result_kind"
    )
    see_result_kind.create(op.get_bind(), checkfirst=True)

    # ── 3. Rewrite course_type enum (core|elective|lab → theory|lab|integrated|nptel) ──
    # Live enum has (core, elective, lab). New value set is BMSCE-aligned.
    # Strategy: drop server default → rename old type → create new type →
    # ALTER COLUMN with USING expression to remap → set new default → drop old.
    op.execute("ALTER TABLE courses ALTER COLUMN course_type DROP DEFAULT")
    op.execute("ALTER TYPE course_type RENAME TO course_type_old")
    op.execute(
        "CREATE TYPE course_type AS ENUM ('theory', 'lab', 'integrated', 'nptel')"
    )
    op.execute(
        """
        ALTER TABLE courses
        ALTER COLUMN course_type TYPE course_type
        USING (
            CASE course_type::text
                WHEN 'core' THEN 'theory'::course_type
                WHEN 'elective' THEN 'theory'::course_type
                WHEN 'lab' THEN 'lab'::course_type
                ELSE 'theory'::course_type
            END
        )
        """
    )
    op.execute(
        "ALTER TABLE courses ALTER COLUMN course_type SET DEFAULT 'theory'"
    )
    op.execute("DROP TYPE course_type_old")

    # ── 4. New columns on existing tables ───────────────────────────────────
    # users: HOD↔dept link (new canonical column; departments.head_user_id stays
    # legacy until later cleanup). Index is partial because the column is NULL
    # for non-HOD users.
    op.add_column(
        "users",
        sa.Column(
            "hod_of_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_hod_dept",
        "users",
        ["hod_of_department_id"],
        postgresql_where=sa.text("hod_of_department_id IS NOT NULL"),
    )

    # ── 5. academic_terms (new) ─────────────────────────────────────────────
    op.create_table(
        "academic_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column(
            "term_type",
            postgresql.ENUM(name="term_type", create_type=False),
            nullable=False,
            server_default=sa.text("'regular'"),
        ),
        sa.Column("starts_on", sa.Date, nullable=True),
        sa.Column("ends_on", sa.Date, nullable=True),
        sa.Column(
            "registration_opens_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "registration_closes_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_academic_terms_college_code_active",
        "academic_terms",
        ["college_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # course_offerings: parent_offering_id (theory↔lab pairing), assessment_scheme_id
    # (FK added in 0009 after backfill), academic_term_id (FK; VARCHAR column stays).
    op.add_column(
        "course_offerings",
        sa.Column(
            "parent_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_offerings_parent",
        "course_offerings",
        ["parent_offering_id"],
        postgresql_where=sa.text("parent_offering_id IS NOT NULL"),
    )
    op.add_column(
        "course_offerings",
        sa.Column(
            "assessment_scheme_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "course_offerings",
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_offerings_academic_term_id",
        "course_offerings",
        ["academic_term_id"],
        postgresql_where=sa.text("academic_term_id IS NOT NULL"),
    )

    # enrollments: state + academic_term_id (FK companion to existing VARCHAR).
    op.add_column(
        "enrollments",
        sa.Column(
            "enrollment_state",
            postgresql.ENUM(name="enrollment_state", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        "enrollments",
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_enrollments_academic_term_id",
        "enrollments",
        ["academic_term_id"],
        postgresql_where=sa.text("academic_term_id IS NOT NULL"),
    )

    # guardian_links: provenance.
    op.add_column(
        "guardian_links",
        sa.Column(
            "created_via",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'admin_manual'"),
        ),
    )

    # marks: per-row parent visibility flag.
    op.add_column(
        "marks",
        sa.Column(
            "parent_visible",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── 6. semester_setups ──────────────────────────────────────────────────
    op.create_table(
        "semester_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=False,
        ),
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="semester_setup_state", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "drafted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_semester_setups_dept_term_active",
        "semester_setups",
        ["college_id", "department_id", "academic_term_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_semester_setups_state",
        "semester_setups",
        ["state"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 7. elective_groups + elective_group_options ─────────────────────────
    op.create_table(
        "elective_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "semester_setup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("semester_setups.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("required_credits", sa.SmallInteger, nullable=True),
        sa.Column(
            "min_enrollment_to_run",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column("max_enrollment", sa.SmallInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_elective_groups_setup",
        "elective_groups",
        ["semester_setup_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "elective_group_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "elective_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_groups.id"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column(
            "tentative_teacher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "is_dissolved",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dissolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("dissolved_reason", sa.Text, nullable=True),
        sa.Column(
            "migrated_to_option_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_group_options.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_elective_options_group",
        "elective_group_options",
        ["elective_group_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 8. course_registrations ─────────────────────────────────────────────
    op.create_table(
        "course_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "semester_setup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("semester_setups.id"),
            nullable=False,
        ),
        sa.Column(
            "elective_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_groups.id"),
            nullable=True,
        ),
        sa.Column(
            "elective_group_option_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("elective_group_options.id"),
            nullable=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'approved'"),
        ),
        sa.Column(
            "is_backlog",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "backlog_source_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_creg_student_setup",
        "course_registrations",
        ["student_user_id", "semester_setup_id"],
    )
    op.create_index(
        "ix_creg_backlog",
        "course_registrations",
        ["student_user_id"],
        postgresql_where=sa.text("is_backlog = true AND deleted_at IS NULL"),
    )

    # ── 9. lab_batches + members + assignments ──────────────────────────────
    op.create_table(
        "lab_batches",
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
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column(
            "display_order",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_lab_batches_offering_name_active",
        "lab_batches",
        ["course_offering_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_lab_batches_offering",
        "lab_batches",
        ["course_offering_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "lab_batch_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "lab_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lab_batches.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_reason", sa.Text, nullable=True),
    )
    op.create_index(
        "uq_lab_batch_members_active",
        "lab_batch_members",
        ["lab_batch_id", "student_user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_lab_batch_members_student",
        "lab_batch_members",
        ["student_user_id"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "lab_batch_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "lab_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lab_batches.id"),
            nullable=False,
        ),
        sa.Column(
            "teacher_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'batch_incharge'"),
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unassigned_reason", sa.Text, nullable=True),
    )
    op.create_index(
        "uq_lab_batch_assignments_active",
        "lab_batch_assignments",
        ["lab_batch_id", "teacher_user_id", "role"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_index(
        "ix_lab_batch_assignments_teacher",
        "lab_batch_assignments",
        ["teacher_user_id"],
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )

    # ── 10. assessment_scheme_templates + schemes + components ──────────────
    op.create_table(
        "assessment_scheme_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("applies_to_course_type", sa.String(20), nullable=False),
        sa.Column(
            "validation_rules",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "default_components",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheme_tpl_dept",
        "assessment_scheme_templates",
        ["owner_department_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_scheme_tpl_type",
        "assessment_scheme_templates",
        ["applies_to_course_type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "assessment_schemes",
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
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_scheme_templates.id"),
            nullable=True,
        ),
        sa.Column(
            "configured_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "is_locked",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_assessment_schemes_offering_active",
        "assessment_schemes",
        ["course_offering_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "assessment_scheme_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "assessment_scheme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_schemes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="assessment_component_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("max_marks", sa.Numeric(6, 2), nullable=False),
        sa.Column("weight_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "ordinal",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_dropped_in_best_of",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "weight_percent BETWEEN 0 AND 100",
            name="ck_scheme_comp_weight_range",
        ),
        sa.CheckConstraint(
            "max_marks BETWEEN 0 AND 1000",
            name="ck_scheme_comp_max_marks_range",
        ),
    )
    op.create_index(
        "uq_scheme_components_scheme_label_active",
        "assessment_scheme_components",
        ["assessment_scheme_id", "label"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_scheme_components_scheme",
        "assessment_scheme_components",
        ["assessment_scheme_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 11. nptel_enrollments ───────────────────────────────────────────────
    op.create_table(
        "nptel_enrollments",
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
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "specific_nptel_course_name", sa.String(200), nullable=False
        ),
        sa.Column("specific_nptel_course_url", sa.Text, nullable=True),
        sa.Column("certificate_url", sa.Text, nullable=True),
        sa.Column(
            "certificate_verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "certificate_verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "certificate_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "completion_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_nptel_enrollments_offering_student_active",
        "nptel_enrollments",
        ["course_offering_id", "student_user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_nptel_enrollments_student",
        "nptel_enrollments",
        ["student_user_id", "completion_status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 12. internal_deadlines ──────────────────────────────────────────────
    op.create_table(
        "internal_deadlines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
        sa.Column(
            "course_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=True,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "set_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "is_frozen",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "frozen_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_internal_deadlines_term_kind",
        "internal_deadlines",
        ["academic_term_id", "kind"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_internal_deadlines_offering",
        "internal_deadlines",
        ["course_offering_id"],
        postgresql_where=sa.text(
            "course_offering_id IS NOT NULL AND deleted_at IS NULL"
        ),
    )

    # ── 13. cie_schedule ────────────────────────────────────────────────────
    op.create_table(
        "cie_schedule",
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
        sa.Column("cie_number", sa.SmallInteger, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "duration_minutes",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "is_published",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "cie_number BETWEEN 1 AND 3",
            name="ck_cie_schedule_number_range",
        ),
    )
    op.create_index(
        "uq_cie_schedule_offering_number_active",
        "cie_schedule",
        ["course_offering_id", "cie_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_cie_schedule_offering",
        "cie_schedule",
        ["course_offering_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_cie_schedule_published",
        "cie_schedule",
        ["is_published", "scheduled_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 14. tasks ───────────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "task_type",
            postgresql.ENUM(name="task_type", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("related_entity_type", sa.String(50), nullable=True),
        sa.Column(
            "related_entity_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="task_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decline_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tasks_assignee",
        "tasks",
        ["assigned_to_user_id", "status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tasks_assigner",
        "tasks",
        ["assigned_by_user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 15. hall_tickets + versions ─────────────────────────────────────────
    op.create_table(
        "hall_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        # FK to hall_ticket_versions added (DEFERRABLE) in 0009 to break cycle.
        sa.Column(
            "current_version_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_hall_tickets_student_term_active",
        "hall_tickets",
        ["student_user_id", "academic_term_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_hall_tickets_term",
        "hall_tickets",
        ["academic_term_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "hall_ticket_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "hall_ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hall_tickets.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.SmallInteger, nullable=False),
        sa.Column("pdf_url", sa.Text, nullable=False),
        sa.Column("eligibility_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "generated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "hall_ticket_id", "version_number", name="uq_htv_ticket_version"
        ),
    )
    op.create_index(
        "ix_htv_ticket",
        "hall_ticket_versions",
        ["hall_ticket_id", "version_number"],
    )

    # ── 16. grade_cards + versions ──────────────────────────────────────────
    op.create_table(
        "grade_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "academic_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academic_terms.id"),
            nullable=False,
        ),
        sa.Column(
            "current_version_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "is_finalised",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_grade_cards_student_term_active",
        "grade_cards",
        ["student_user_id", "academic_term_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_grade_cards_student",
        "grade_cards",
        ["student_user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "grade_card_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "grade_card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grade_cards.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.SmallInteger, nullable=False),
        sa.Column("pdf_url", sa.Text, nullable=False),
        sa.Column("grades_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "generated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("trigger_reason", sa.String(50), nullable=False),
        sa.UniqueConstraint(
            "grade_card_id", "version_number", name="uq_gcv_card_version"
        ),
    )
    op.create_index(
        "ix_gcv_card",
        "grade_card_versions",
        ["grade_card_id", "version_number"],
    )

    # ── 17. see_results (BIGINT FK to enrollments) ──────────────────────────
    op.create_table(
        "see_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.BigInteger,
            sa.ForeignKey("enrollments.id"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="see_result_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("marks_obtained", sa.Numeric(6, 2), nullable=True),
        sa.Column("max_marks", sa.Numeric(6, 2), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "csv_upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "superseded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("see_results.id"),
            nullable=True,
        ),
        sa.Column(
            "is_current",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_see_results_enrollment",
        "see_results",
        ["enrollment_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Single-current-per-enrollment unique index lands in 0009.

    # ── 18. re_evaluations ──────────────────────────────────────────────────
    op.create_table(
        "re_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.BigInteger,
            sa.ForeignKey("enrollments.id"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "request_window_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'requested'"),
        ),
        sa.Column(
            "original_see_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("see_results.id"),
            nullable=False,
        ),
        sa.Column(
            "revised_see_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("see_results.id"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_re_evaluations_student",
        "re_evaluations",
        ["requested_by_student_user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_re_evaluations_status",
        "re_evaluations",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 19. academic_overrides (typed semantic actions) ─────────────────────
    op.create_table(
        "academic_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "override_type",
            postgresql.ENUM(name="override_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "target_student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "target_course_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=True,
        ),
        sa.Column("target_entity_type", sa.String(50), nullable=True),
        sa.Column(
            "target_entity_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence_url", sa.Text, nullable=True),
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_academic_overrides_student",
        "academic_overrides",
        ["target_student_user_id"],
        postgresql_where=sa.text("target_student_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_academic_overrides_actor",
        "academic_overrides",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_academic_overrides_type",
        "academic_overrides",
        ["override_type"],
    )

    # ── 20. eligibility_snapshots ───────────────────────────────────────────
    op.create_table(
        "eligibility_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "course_offering_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_offerings.id"),
            nullable=False,
        ),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attendance_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("cie_eligibility", postgresql.JSONB, nullable=False),
        sa.Column("see_eligible", sa.Boolean, nullable=False),
        sa.Column("makeup_see_eligible", sa.Boolean, nullable=False),
        sa.Column("internal_marks_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("internal_threshold_met", sa.Boolean, nullable=True),
        sa.Column(
            "condonation_applied_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_finalised",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_eligsnap_student_offering",
        "eligibility_snapshots",
        ["student_user_id", "course_offering_id", "as_of_at"],
    )
    op.create_index(
        "ix_eligsnap_finalised",
        "eligibility_snapshots",
        ["is_finalised", "as_of_at"],
        postgresql_where=sa.text("is_finalised = true"),
    )

    # ── 21. course_drops (schema-ready, deferred UI) ────────────────────────
    op.create_table(
        "course_drops",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.BigInteger,
            sa.ForeignKey("enrollments.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "initiated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_course_drops_enrollment",
        "course_drops",
        ["enrollment_id"],
    )

    # ── 22. updated_at triggers for every new triggered table ──────────────
    for tbl in TRIGGERED_TABLES:
        _attach_updated_at_trigger(tbl)


def downgrade() -> None:
    # Drop triggers first.
    for tbl in TRIGGERED_TABLES:
        _drop_updated_at_trigger(tbl)

    # Drop new tables in reverse dependency order.
    op.drop_table("course_drops")
    op.drop_table("eligibility_snapshots")
    op.drop_table("academic_overrides")
    op.drop_table("re_evaluations")
    op.drop_table("see_results")
    op.drop_table("grade_card_versions")
    op.drop_table("grade_cards")
    op.drop_table("hall_ticket_versions")
    op.drop_table("hall_tickets")
    op.drop_table("tasks")
    op.drop_table("cie_schedule")
    op.drop_table("internal_deadlines")
    op.drop_table("nptel_enrollments")
    op.drop_table("assessment_scheme_components")
    op.drop_table("assessment_schemes")
    op.drop_table("assessment_scheme_templates")
    op.drop_table("lab_batch_assignments")
    op.drop_table("lab_batch_members")
    op.drop_table("lab_batches")
    op.drop_table("course_registrations")
    op.drop_table("elective_group_options")
    op.drop_table("elective_groups")
    op.drop_table("semester_setups")

    # Drop new columns on existing tables (reverse order).
    op.drop_column("marks", "parent_visible")
    op.drop_column("guardian_links", "created_via")
    op.drop_index(
        "ix_enrollments_academic_term_id", table_name="enrollments"
    )
    op.drop_column("enrollments", "academic_term_id")
    op.drop_column("enrollments", "enrollment_state")
    op.drop_index(
        "ix_offerings_academic_term_id", table_name="course_offerings"
    )
    op.drop_column("course_offerings", "academic_term_id")
    op.drop_column("course_offerings", "assessment_scheme_id")
    op.drop_index("ix_offerings_parent", table_name="course_offerings")
    op.drop_column("course_offerings", "parent_offering_id")

    op.drop_table("academic_terms")

    op.drop_index("ix_users_hod_dept", table_name="users")
    op.drop_column("users", "hod_of_department_id")

    # Revert course_type enum back to (core|elective|lab).
    op.execute("ALTER TABLE courses ALTER COLUMN course_type DROP DEFAULT")
    op.execute("ALTER TYPE course_type RENAME TO course_type_old")
    op.execute("CREATE TYPE course_type AS ENUM ('core', 'elective', 'lab')")
    op.execute(
        """
        ALTER TABLE courses
        ALTER COLUMN course_type TYPE course_type
        USING (
            CASE course_type::text
                WHEN 'theory' THEN 'core'::course_type
                WHEN 'integrated' THEN 'core'::course_type
                WHEN 'lab' THEN 'lab'::course_type
                WHEN 'nptel' THEN 'core'::course_type
                ELSE 'core'::course_type
            END
        )
        """
    )
    op.execute(
        "ALTER TABLE courses ALTER COLUMN course_type SET DEFAULT 'core'"
    )
    op.execute("DROP TYPE course_type_old")

    # Drop new enums.
    sa.Enum(name="see_result_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="grade_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="override_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="assessment_component_kind").drop(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(name="semester_setup_state").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="enrollment_state").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="term_type").drop(op.get_bind(), checkfirst=True)

    # Note: 'hod' value on user_role enum cannot be removed cleanly without
    # dropping/recreating the type. We leave it; HOD-role users would have
    # been deleted upstream before this downgrade runs.
