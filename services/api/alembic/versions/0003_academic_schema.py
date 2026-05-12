"""academic schema for module 2

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12

Tables: departments, courses, batches, sections, rooms, course_offerings,
timetable_slots, timetable_exceptions, academic_calendar, enrollments.

Every table that has `updated_at` gets the `set_updated_at` BEFORE UPDATE
trigger (function created in 0001). `enrollments` is append-mostly and has
no `updated_at`, so it's excluded from the trigger list.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


TRIGGERED_TABLES = (
    "departments",
    "courses",
    "batches",
    "sections",
    "rooms",
    "course_offerings",
    "timetable_slots",
    "timetable_exceptions",
    "academic_calendar",
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
    # ── enums ────────────────────────────────────────────────────────────────
    course_type = postgresql.ENUM("core", "elective", "lab", name="course_type")
    course_type.create(op.get_bind(), checkfirst=True)

    room_type = postgresql.ENUM(
        "lecture", "lab", "seminar", "online", name="room_type"
    )
    room_type.create(op.get_bind(), checkfirst=True)

    exception_kind = postgresql.ENUM(
        "cancel", "reschedule", "room_change", "extra", name="timetable_exception_kind"
    )
    exception_kind.create(op.get_bind(), checkfirst=True)

    calendar_kind = postgresql.ENUM(
        "holiday", "exam", "event", "term_start", "term_end",
        name="academic_calendar_kind",
    )
    calendar_kind.create(op.get_bind(), checkfirst=True)

    # ── departments ──────────────────────────────────────────────────────────
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column(
            "head_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_departments_college_id", "departments", ["college_id"])
    op.create_index(
        "uq_departments_college_code_active",
        "departments",
        ["college_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── courses ──────────────────────────────────────────────────────────────
    op.create_table(
        "courses",
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
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("credits", sa.SmallInteger, nullable=False, server_default=sa.text("3")),
        sa.Column("semester", sa.SmallInteger, nullable=False),
        sa.Column(
            "course_type",
            postgresql.ENUM(name="course_type", create_type=False),
            nullable=False,
            server_default=sa.text("'core'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("semester BETWEEN 1 AND 12", name="ck_courses_semester_range"),
        sa.CheckConstraint("credits BETWEEN 0 AND 12", name="ck_courses_credits_range"),
    )
    op.create_index("ix_courses_college_id", "courses", ["college_id"])
    op.create_index(
        "uq_courses_college_code_active",
        "courses",
        ["college_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_courses_department_semester", "courses", ["department_id", "semester"]
    )

    # ── batches ──────────────────────────────────────────────────────────────
    op.create_table(
        "batches",
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
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("admission_year", sa.SmallInteger, nullable=False),
        sa.Column(
            "program_duration_years",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("4"),
        ),
        sa.Column(
            "current_semester",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "current_semester BETWEEN 1 AND 12", name="ck_batches_current_semester_range"
        ),
        sa.CheckConstraint(
            "admission_year BETWEEN 1900 AND 2100",
            name="ck_batches_admission_year_range",
        ),
    )
    op.create_index("ix_batches_college_id", "batches", ["college_id"])
    op.create_index(
        "uq_batches_college_dept_year_active",
        "batches",
        ["college_id", "department_id", "admission_year"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── sections ─────────────────────────────────────────────────────────────
    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batches.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(10), nullable=False),
        sa.Column(
            "class_teacher_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sections_college_id", "sections", ["college_id"])
    op.create_index("ix_sections_batch_id", "sections", ["batch_id"])
    op.create_index(
        "uq_sections_batch_name_active",
        "sections",
        ["batch_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_sections_class_teacher", "sections", ["class_teacher_user_id"]
    )

    # ── rooms ────────────────────────────────────────────────────────────────
    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("building", sa.String(80), nullable=True),
        sa.Column("floor", sa.SmallInteger, nullable=True),
        sa.Column("capacity", sa.SmallInteger, nullable=True),
        sa.Column(
            "room_type",
            postgresql.ENUM(name="room_type", create_type=False),
            nullable=False,
            server_default=sa.text("'lecture'"),
        ),
        sa.Column("lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("lon", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "gps_radius_m",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)", name="ck_rooms_lat_lon_both_or_neither"
        ),
        sa.CheckConstraint(
            "gps_radius_m BETWEEN 10 AND 1000", name="ck_rooms_gps_radius_range"
        ),
    )
    op.create_index("ix_rooms_college_id", "rooms", ["college_id"])
    op.create_index(
        "uq_rooms_college_code_active",
        "rooms",
        ["college_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── course_offerings ─────────────────────────────────────────────────────
    op.create_table(
        "course_offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id"),
            nullable=False,
        ),
        sa.Column(
            "teacher_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("academic_term", sa.String(20), nullable=False),
        sa.Column("semester", sa.SmallInteger, nullable=False),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_course_offerings_college_id", "course_offerings", ["college_id"])
    op.create_index(
        "uq_offerings_section_course_term_active",
        "course_offerings",
        ["section_id", "course_id", "academic_term"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_offerings_teacher_term",
        "course_offerings",
        ["teacher_user_id", "academic_term"],
    )
    op.create_index(
        "ix_offerings_section_term",
        "course_offerings",
        ["section_id", "academic_term"],
    )
    op.create_index(
        "ix_offerings_course_term",
        "course_offerings",
        ["course_id", "academic_term"],
    )

    # ── timetable_slots ──────────────────────────────────────────────────────
    op.create_table(
        "timetable_slots",
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
            "room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id"),
            nullable=True,
        ),
        sa.Column("day_of_week", sa.SmallInteger, nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("end_time", sa.Time(timezone=False), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("end_time > start_time", name="ck_slots_end_after_start"),
        sa.CheckConstraint(
            "effective_until >= effective_from",
            name="ck_slots_effective_until_after_from",
        ),
        sa.CheckConstraint(
            "day_of_week BETWEEN 0 AND 6", name="ck_slots_day_of_week_range"
        ),
    )
    op.create_index("ix_slots_college_id", "timetable_slots", ["college_id"])
    op.create_index(
        "ix_slots_room_day",
        "timetable_slots",
        ["room_id", "day_of_week"],
        postgresql_where=sa.text("deleted_at IS NULL AND room_id IS NOT NULL"),
    )
    op.create_index(
        "ix_slots_offering_day",
        "timetable_slots",
        ["course_offering_id", "day_of_week"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_slots_college_dow", "timetable_slots", ["college_id", "day_of_week"]
    )

    # ── timetable_exceptions ─────────────────────────────────────────────────
    op.create_table(
        "timetable_exceptions",
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
            "original_slot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("timetable_slots.id"),
            nullable=True,
        ),
        sa.Column("exception_date", sa.Date, nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="timetable_exception_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "new_room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id"),
            nullable=True,
        ),
        sa.Column("new_start_time", sa.Time(timezone=False), nullable=True),
        sa.Column("new_end_time", sa.Time(timezone=False), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind <> 'cancel') OR "
            "(new_room_id IS NULL AND new_start_time IS NULL AND new_end_time IS NULL)",
            name="ck_exceptions_cancel_has_no_overrides",
        ),
        sa.CheckConstraint(
            "(kind <> 'reschedule') OR "
            "(new_start_time IS NOT NULL AND new_end_time IS NOT NULL)",
            name="ck_exceptions_reschedule_has_times",
        ),
        sa.CheckConstraint(
            "(kind <> 'room_change') OR (new_room_id IS NOT NULL)",
            name="ck_exceptions_room_change_has_room",
        ),
        sa.CheckConstraint(
            "(kind <> 'extra') OR "
            "(original_slot_id IS NULL AND new_start_time IS NOT NULL "
            "AND new_end_time IS NOT NULL)",
            name="ck_exceptions_extra_has_no_parent_and_has_times",
        ),
        sa.CheckConstraint(
            "new_end_time IS NULL OR new_start_time IS NULL "
            "OR new_end_time > new_start_time",
            name="ck_exceptions_new_end_after_new_start",
        ),
    )
    op.create_index(
        "ix_timetable_exceptions_college_id",
        "timetable_exceptions",
        ["college_id"],
    )
    op.create_index(
        "uq_exceptions_slot_date",
        "timetable_exceptions",
        ["original_slot_id", "exception_date"],
        unique=True,
        postgresql_where=sa.text("original_slot_id IS NOT NULL"),
    )
    op.create_index("ix_exceptions_date", "timetable_exceptions", ["exception_date"])
    op.create_index(
        "ix_exceptions_offering_date",
        "timetable_exceptions",
        ["course_offering_id", "exception_date"],
    )

    # ── academic_calendar ────────────────────────────────────────────────────
    op.create_table(
        "academic_calendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="academic_calendar_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "applies_to_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=True,
        ),
        sa.Column(
            "cancels_classes",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_academic_calendar_college_id", "academic_calendar", ["college_id"]
    )
    op.create_index(
        "ix_calendar_college_date", "academic_calendar", ["college_id", "entry_date"]
    )

    # ── enrollments ──────────────────────────────────────────────────────────
    op.create_table(
        "enrollments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
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
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id"),
            nullable=False,
        ),
        sa.Column("academic_term", sa.String(20), nullable=False),
        sa.Column("semester", sa.SmallInteger, nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_enrollments_college_id", "enrollments", ["college_id"])
    op.create_index(
        "uq_enrollments_student_section_term_active",
        "enrollments",
        ["student_user_id", "section_id", "academic_term"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    op.create_index(
        "ix_enrollments_section_active",
        "enrollments",
        ["section_id"],
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    op.create_index(
        "ix_enrollments_student_term",
        "enrollments",
        ["student_user_id", "academic_term"],
    )

    # ── attach updated_at triggers ───────────────────────────────────────────
    for table in TRIGGERED_TABLES:
        _attach_updated_at_trigger(table)


def downgrade() -> None:
    for table in TRIGGERED_TABLES:
        _drop_updated_at_trigger(table)

    op.drop_table("enrollments")
    op.drop_table("academic_calendar")
    op.drop_table("timetable_exceptions")
    op.drop_table("timetable_slots")
    op.drop_table("course_offerings")
    op.drop_table("rooms")
    op.drop_table("sections")
    op.drop_table("batches")
    op.drop_table("courses")
    op.drop_table("departments")

    postgresql.ENUM(name="academic_calendar_kind").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="timetable_exception_kind").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="room_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="course_type").drop(op.get_bind(), checkfirst=True)
