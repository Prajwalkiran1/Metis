"""attendance schema for module 3

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-13

Tables: class_sessions, qr_tokens, attendance_records, device_logs,
attendance_overrides.

Two new Postgres enums:
- class_session_state    (pending | open | closed)
- attendance_record_state (submitted | verified | recorded | flagged)

Triggers: only tables with `updated_at` get the `set_updated_at` BEFORE
UPDATE trigger (function from 0001). qr_tokens / device_logs /
attendance_overrides are append-mostly and have no `updated_at`.

Idempotent materialisation of class_sessions relies on the partial
unique index `(course_offering_id, scheduled_date, start_time) WHERE
deleted_at IS NULL`. Anti-replay relies on:
- attendance_records uniqueness on (class_session_id, student_user_id)
- device_logs uniqueness on (class_session_id, device_fingerprint_hash)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


TRIGGERED_TABLES = (
    "class_sessions",
    "attendance_records",
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
    class_session_state = postgresql.ENUM(
        "pending", "open", "closed", name="class_session_state"
    )
    class_session_state.create(op.get_bind(), checkfirst=True)

    attendance_record_state = postgresql.ENUM(
        "submitted", "verified", "recorded", "flagged",
        name="attendance_record_state",
    )
    attendance_record_state.create(op.get_bind(), checkfirst=True)

    class_session_source = postgresql.ENUM(
        "materialised", "extra", "on_demand", name="class_session_source"
    )
    class_session_source.create(op.get_bind(), checkfirst=True)

    # ── class_sessions ───────────────────────────────────────────────────────
    op.create_table(
        "class_sessions",
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
        sa.Column("scheduled_date", sa.Date, nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("end_time", sa.Time(timezone=False), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="class_session_state", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "source",
            postgresql.ENUM(name="class_session_source", create_type=False),
            nullable=False,
            server_default=sa.text("'materialised'"),
        ),
        sa.Column(
            "origin_slot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("timetable_slots.id"),
            nullable=True,
        ),
        sa.Column(
            "origin_exception_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("timetable_exceptions.id"),
            nullable=True,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "end_time > start_time", name="ck_class_sessions_end_after_start"
        ),
    )
    op.create_index(
        "ix_class_sessions_college_id", "class_sessions", ["college_id"]
    )
    op.create_index(
        "ix_class_sessions_offering_date",
        "class_sessions",
        ["course_offering_id", "scheduled_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_class_sessions_college_date",
        "class_sessions",
        ["college_id", "scheduled_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_class_sessions_offering_date_start_active",
        "class_sessions",
        ["course_offering_id", "scheduled_date", "start_time"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── qr_tokens ────────────────────────────────────────────────────────────
    # JWTs are stateless, but persisting the jti enables (a) hard revocation
    # before exp, (b) auditing which token a student submitted, and (c) an
    # explicit anti-replay guard alongside the JWT signature check.
    op.create_table(
        "qr_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "class_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("class_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "jti",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("centroid_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("centroid_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "issued_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "valid_until > valid_from", name="ck_qr_tokens_valid_window"
        ),
        sa.CheckConstraint(
            "(centroid_lat IS NULL) = (centroid_lon IS NULL)",
            name="ck_qr_tokens_centroid_both_or_neither",
        ),
    )
    op.create_index("ix_qr_tokens_college_id", "qr_tokens", ["college_id"])
    op.create_index(
        "ix_qr_tokens_session_valid",
        "qr_tokens",
        ["class_session_id", "valid_until"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # ── device_logs ──────────────────────────────────────────────────────────
    op.create_table(
        "device_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "class_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("class_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "device_fingerprint_hash", sa.String(64), nullable=False
        ),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_device_logs_college_id", "device_logs", ["college_id"])
    op.create_index(
        "uq_device_logs_session_fingerprint",
        "device_logs",
        ["class_session_id", "device_fingerprint_hash"],
        unique=True,
    )

    # ── attendance_records ───────────────────────────────────────────────────
    op.create_table(
        "attendance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "class_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("class_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(name="attendance_record_state", create_type=False),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flagged_reason", sa.String(200), nullable=True),
        sa.Column("gps_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("gps_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("gps_distance_m", sa.Integer, nullable=True),
        sa.Column("face_match", sa.Boolean, nullable=False),
        sa.Column("face_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "qr_token_jti",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "device_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device_logs.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "face_confidence BETWEEN 0 AND 1",
            name="ck_attendance_records_face_conf_range",
        ),
        sa.CheckConstraint(
            "(gps_lat IS NULL) = (gps_lon IS NULL)",
            name="ck_attendance_records_gps_both_or_neither",
        ),
    )
    op.create_index(
        "ix_attendance_records_college_id", "attendance_records", ["college_id"]
    )
    op.create_index(
        "uq_attendance_records_session_student",
        "attendance_records",
        ["class_session_id", "student_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_attendance_records_student_session",
        "attendance_records",
        ["student_user_id", "class_session_id"],
    )

    # ── attendance_overrides ─────────────────────────────────────────────────
    # Append-only audit trail. The actual mutation goes on attendance_records;
    # this table records the who/why/when. `from_state` is nullable because
    # the override can also create an attendance_record for a student who
    # never submitted (the "marked present manually" case).
    op.create_table(
        "attendance_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "college_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("colleges.id"),
            nullable=False,
        ),
        sa.Column(
            "class_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("class_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "attendance_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_records.id"),
            nullable=True,
        ),
        sa.Column(
            "student_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "from_state",
            postgresql.ENUM(
                name="attendance_record_state", create_type=False
            ),
            nullable=True,
        ),
        sa.Column(
            "to_state",
            postgresql.ENUM(
                name="attendance_record_state", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(400), nullable=False),
        sa.Column(
            "overridden_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_attendance_overrides_college_id",
        "attendance_overrides",
        ["college_id"],
    )
    op.create_index(
        "ix_attendance_overrides_session",
        "attendance_overrides",
        ["class_session_id"],
    )
    op.create_index(
        "ix_attendance_overrides_record",
        "attendance_overrides",
        ["attendance_record_id"],
    )

    # ── attach updated_at triggers ───────────────────────────────────────────
    for table in TRIGGERED_TABLES:
        _attach_updated_at_trigger(table)


def downgrade() -> None:
    for table in TRIGGERED_TABLES:
        _drop_updated_at_trigger(table)

    op.drop_table("attendance_overrides")
    op.drop_table("attendance_records")
    op.drop_table("device_logs")
    op.drop_table("qr_tokens")
    op.drop_table("class_sessions")

    postgresql.ENUM(name="class_session_source").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="attendance_record_state").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="class_session_state").drop(
        op.get_bind(), checkfirst=True
    )
