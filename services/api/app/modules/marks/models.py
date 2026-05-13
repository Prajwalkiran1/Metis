"""SQLAlchemy ORM models for M4 (marks service).

Tables: assessments, marks, grade_rules, marks_audit, guardian_links.

Tenant isolation: every table has `college_id` (FK to colleges from M1).
`assessments` is soft-deleted; `marks` is not (deleting marks would lose
historical grade context — corrections flow through `marks_audit`
instead). `marks_audit` and `guardian_links` are append-only.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, SoftDeleteMixin, TimestampedMixin, new_uuid


# ── Enums ────────────────────────────────────────────────────────────────────
class AssessmentType(str, enum.Enum):
    cie1 = "cie1"
    cie2 = "cie2"
    cie3 = "cie3"
    see = "see"
    assignment = "assignment"
    lab = "lab"


class AssessmentState(str, enum.Enum):
    draft = "draft"
    open = "open"
    locked = "locked"


class MarkState(str, enum.Enum):
    entered = "entered"
    locked = "locked"


class GuardianRelationship(str, enum.Enum):
    father = "father"
    mother = "mother"
    guardian = "guardian"
    other = "other"


# ── assessments ──────────────────────────────────────────────────────────────
class Assessment(Base, TimestampedMixin, SoftDeleteMixin):
    __tablename__ = "assessments"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("colleges.id"),
        nullable=False,
        index=True,
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("course_offerings.id"),
        nullable=False,
    )
    type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, name="assessment_type", native_enum=True, create_type=False),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    weight_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[AssessmentState] = mapped_column(
        Enum(AssessmentState, name="assessment_state", native_enum=True, create_type=False),
        nullable=False,
        default=AssessmentState.draft,
        server_default=text("'draft'"),
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "max_marks BETWEEN 0 AND 1000",
            name="ck_assessments_max_marks_range",
        ),
        CheckConstraint(
            "weight_percent IS NULL OR weight_percent BETWEEN 0 AND 100",
            name="ck_assessments_weight_range",
        ),
        Index(
            "ix_assessments_offering_type",
            "course_offering_id",
            "type",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_assessments_offering_type_name_active",
            "course_offering_id",
            "type",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ── marks ────────────────────────────────────────────────────────────────────
class Mark(Base, TimestampedMixin):
    """One row per (assessment, student). Mutable in place; corrections trail
    is in `marks_audit`. NOT soft-deleted by design.
    """

    __tablename__ = "marks"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("colleges.id"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    marks_obtained: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    is_absent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    state: Mapped[MarkState] = mapped_column(
        Enum(MarkState, name="mark_state", native_enum=True, create_type=False),
        nullable=False,
        default=MarkState.entered,
        server_default=text("'entered'"),
    )
    entered_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    last_modified_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(is_absent = true AND marks_obtained IS NULL) "
            "OR (is_absent = false AND marks_obtained IS NOT NULL)",
            name="ck_marks_absent_xor_value",
        ),
        CheckConstraint(
            "marks_obtained IS NULL OR marks_obtained BETWEEN 0 AND 1000",
            name="ck_marks_obtained_sanity_range",
        ),
        Index(
            "uq_marks_assessment_student",
            "assessment_id",
            "student_user_id",
            unique=True,
        ),
        Index(
            "ix_marks_student_assessment",
            "student_user_id",
            "assessment_id",
        ),
    )


# ── grade_rules ──────────────────────────────────────────────────────────────
class GradeRule(Base, TimestampedMixin):
    __tablename__ = "grade_rules"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("colleges.id"),
        nullable=False,
        index=True,
    )
    course_offering_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("course_offerings.id"),
        nullable=False,
    )
    assessment_type: Mapped[AssessmentType] = mapped_column(
        Enum(AssessmentType, name="assessment_type", native_enum=True, create_type=False),
        nullable=False,
    )
    weight_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    passing_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("40.0"),
        default=Decimal("40.0"),
    )

    __table_args__ = (
        CheckConstraint(
            "weight_percent BETWEEN 0 AND 100",
            name="ck_grade_rules_weight_range",
        ),
        CheckConstraint(
            "passing_threshold_percent BETWEEN 0 AND 100",
            name="ck_grade_rules_threshold_range",
        ),
        Index(
            "uq_grade_rules_offering_type",
            "course_offering_id",
            "assessment_type",
            unique=True,
        ),
    )


# ── marks_audit ──────────────────────────────────────────────────────────────
class MarkAudit(Base):
    """Append-only value-level history of mark mutations."""

    __tablename__ = "marks_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("colleges.id"),
        nullable=False,
        index=True,
    )
    mark_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("marks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assessment_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("assessments.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    actor_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_marks_audit_mark_created", "mark_id", "created_at"),
        Index(
            "ix_marks_audit_assessment_created",
            "assessment_id",
            "created_at",
        ),
    )


# ── guardian_links ───────────────────────────────────────────────────────────
class GuardianLink(Base):
    """Verified parent ↔ student mapping. Admin-managed for now."""

    __tablename__ = "guardian_links"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    college_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("colleges.id"),
        nullable=False,
        index=True,
    )
    parent_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    student_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    relationship: Mapped[GuardianRelationship] = mapped_column(
        Enum(GuardianRelationship, name="guardian_relationship", native_enum=True, create_type=False),
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_guardian_links_parent_student",
            "parent_user_id",
            "student_user_id",
            unique=True,
        ),
        Index(
            "ix_guardian_links_parent_verified",
            "parent_user_id",
            postgresql_where=text("verified_at IS NOT NULL"),
        ),
        Index(
            "ix_guardian_links_student_verified",
            "student_user_id",
            postgresql_where=text("verified_at IS NOT NULL"),
        ),
    )
