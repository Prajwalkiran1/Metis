"""Service layer for M10 workflow.

M10a scope:
- Semester setup CRUD scoped to HOD's department
- Course assignment within a setup (creates a course_offering row plus an
  auto-linked assessment_scheme from the institutional template)
- Elective groups + options CRUD
- Publish flow: validate (>=1 course, every course has a teacher),
  transition draft → published → active in one transaction, insert
  admin_notifications row, then (post-commit) emit semester_setup.published.

All writes go through this layer so the router stays thin and easy to
audit. Errors raise `WorkflowError` which the router maps to HTTPException.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.event_bus import publish as publish_event
from app.modules.academic.models import (
    AcademicTerm,
    AssessmentScheme,
    AssessmentSchemeComponent,
    AssessmentSchemeTemplate,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Section,
)
from app.modules.users.models import User, UserRole
from app.modules.workflow.models import (
    AdminNotification,
    ElectiveGroup,
    ElectiveGroupOption,
    SemesterSetup,
    SemesterSetupState,
)
from app.modules.workflow.schemas import (
    CourseAssignmentCreate,
    CourseAssignmentPatch,
    ElectiveGroupCreate,
    ElectiveGroupOptionCreate,
    ElectiveGroupOptionPatch,
    ElectiveGroupPatch,
    SemesterSetupCreate,
    SemesterSetupPatch,
)


class WorkflowError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ── Authority helpers ───────────────────────────────────────────────────────
def _require_hod_for_dept(actor: User, department_id: UUID) -> None:
    """Allow only an HOD of the matching department through. Admins are NOT
    allowed to write — per CLAUDE.md authority table, the HOD owns this
    flow end to end. Admins get read-only oversight via the notifications
    feed and the GET endpoints.
    """
    if actor.role != UserRole.hod or actor.hod_of_department_id != department_id:
        raise WorkflowError("forbidden", "HOD of this department only", 403)


def _require_hod_or_admin_read(actor: User) -> None:
    if actor.role not in (UserRole.hod, UserRole.admin):
        raise WorkflowError("forbidden", "HOD or admin only", 403)


async def _get_active_setup(
    session: AsyncSession, *, setup_id: UUID, college_id: UUID
) -> SemesterSetup:
    row = await session.execute(
        select(SemesterSetup).where(
            SemesterSetup.id == setup_id,
            SemesterSetup.college_id == college_id,
            SemesterSetup.deleted_at.is_(None),
        )
    )
    setup = row.scalar_one_or_none()
    if setup is None:
        raise WorkflowError("not_found", "semester setup not found", 404)
    return setup


def _require_draft(setup: SemesterSetup) -> None:
    if setup.state != SemesterSetupState.draft:
        raise WorkflowError(
            "not_draft",
            f"setup is in state '{setup.state.value}' — only drafts are editable",
            409,
        )


# ── Setup CRUD ──────────────────────────────────────────────────────────────
async def list_setups(
    session: AsyncSession,
    *,
    actor: User,
    department_id: UUID | None = None,
    academic_term_id: UUID | None = None,
    state: SemesterSetupState | None = None,
) -> list[SemesterSetup]:
    """HODs see only their own dept; admins see all dept setups in the college."""
    if actor.role == UserRole.hod:
        if actor.hod_of_department_id is None:
            raise WorkflowError("hod_dept_missing", "HOD has no department", 400)
        dept_filter = actor.hod_of_department_id
    elif actor.role == UserRole.admin:
        dept_filter = department_id  # optional
    else:
        raise WorkflowError("forbidden", "HOD or admin only", 403)

    stmt = select(SemesterSetup).where(
        SemesterSetup.college_id == actor.college_id,
        SemesterSetup.deleted_at.is_(None),
    )
    if dept_filter is not None:
        stmt = stmt.where(SemesterSetup.department_id == dept_filter)
    if academic_term_id is not None:
        stmt = stmt.where(SemesterSetup.academic_term_id == academic_term_id)
    if state is not None:
        stmt = stmt.where(SemesterSetup.state == state)
    rows = await session.execute(stmt.order_by(SemesterSetup.created_at.desc()))
    return list(rows.scalars().all())


async def get_setup_detail(
    session: AsyncSession, *, actor: User, setup_id: UUID
) -> dict[str, Any]:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    # HOD scope: read scoped to own dept. Admin: anywhere in the college.
    if actor.role == UserRole.hod and actor.hod_of_department_id != setup.department_id:
        raise WorkflowError("forbidden", "not your department", 403)
    if actor.role not in (UserRole.hod, UserRole.admin):
        raise WorkflowError("forbidden", "HOD or admin only", 403)

    dept = await session.get(Department, setup.department_id)
    term = await session.get(AcademicTerm, setup.academic_term_id)

    # Course offerings for this setup = offerings on this (dept, term)
    # that fall under the HOD-driven publish flow.
    offering_rows = (
        await session.execute(
            select(
                CourseOffering,
                Course.code,
                Course.title,
                Course.course_type,
                Section.name.label("section_name"),
                User.name.label("teacher_name"),
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .join(User, User.id == CourseOffering.teacher_user_id, isouter=True)
            .where(
                CourseOffering.college_id == actor.college_id,
                Course.department_id == setup.department_id,
                CourseOffering.academic_term_id == setup.academic_term_id,
                CourseOffering.deleted_at.is_(None),
            )
            .order_by(Course.code)
        )
    ).all()
    courses = []
    for r in offering_rows:
        off = r[0]
        courses.append(
            {
                "id": off.id,
                "course_id": off.course_id,
                "course_code": r.code,
                "course_title": r.title,
                "course_type": r.course_type,
                "section_id": off.section_id,
                "section_name": r.section_name,
                "teacher_user_id": off.teacher_user_id,
                "teacher_name": r.teacher_name,
                "parent_offering_id": off.parent_offering_id,
                "assessment_scheme_id": off.assessment_scheme_id,
                "is_active": off.is_active,
            }
        )

    # Elective groups + options
    eg_rows = (
        await session.execute(
            select(ElectiveGroup)
            .where(
                ElectiveGroup.semester_setup_id == setup.id,
                ElectiveGroup.deleted_at.is_(None),
            )
            .order_by(ElectiveGroup.created_at)
        )
    ).scalars().all()
    elective_groups: list[dict[str, Any]] = []
    for eg in eg_rows:
        opt_rows = (
            await session.execute(
                select(
                    ElectiveGroupOption,
                    Course.code,
                    Course.title,
                    User.name.label("teacher_name"),
                )
                .join(Course, Course.id == ElectiveGroupOption.course_id)
                .join(
                    User,
                    User.id == ElectiveGroupOption.tentative_teacher_id,
                    isouter=True,
                )
                .where(
                    ElectiveGroupOption.elective_group_id == eg.id,
                    ElectiveGroupOption.deleted_at.is_(None),
                )
                .order_by(Course.code)
            )
        ).all()
        elective_groups.append(
            {
                "id": eg.id,
                "semester_setup_id": eg.semester_setup_id,
                "name": eg.name,
                "description": eg.description,
                "required_credits": eg.required_credits,
                "min_enrollment_to_run": eg.min_enrollment_to_run,
                "max_enrollment": eg.max_enrollment,
                "options": [
                    {
                        "id": o[0].id,
                        "elective_group_id": o[0].elective_group_id,
                        "course_id": o[0].course_id,
                        "course_code": o.code,
                        "course_title": o.title,
                        "tentative_teacher_id": o[0].tentative_teacher_id,
                        "tentative_teacher_name": o.teacher_name,
                        "is_dissolved": o[0].is_dissolved,
                    }
                    for o in opt_rows
                ],
            }
        )

    return {
        "id": setup.id,
        "college_id": setup.college_id,
        "department_id": setup.department_id,
        "academic_term_id": setup.academic_term_id,
        "state": setup.state,
        "drafted_by_user_id": setup.drafted_by_user_id,
        "published_at": setup.published_at,
        "archived_at": setup.archived_at,
        "notes": setup.notes,
        "created_at": setup.created_at,
        "updated_at": setup.updated_at,
        "department_name": dept.name if dept else "",
        "department_code": dept.code if dept else "",
        "academic_term_code": term.code if term else "",
        "courses": courses,
        "elective_groups": elective_groups,
    }


async def create_setup(
    session: AsyncSession, *, actor: User, payload: SemesterSetupCreate
) -> SemesterSetup:
    _require_hod_for_dept(actor, payload.department_id)

    # Term must exist in the same college.
    term = await session.get(AcademicTerm, payload.academic_term_id)
    if term is None or term.college_id != actor.college_id or term.deleted_at is not None:
        raise WorkflowError("bad_term", "academic term not found", 400)

    setup = SemesterSetup(
        college_id=actor.college_id,
        department_id=payload.department_id,
        academic_term_id=payload.academic_term_id,
        state=SemesterSetupState.draft,
        drafted_by_user_id=actor.id,
        notes=payload.notes,
    )
    session.add(setup)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_setup",
            "a setup for this department and term already exists",
            409,
        ) from e

    await write_audit(
        session,
        action="semester_setup.create",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "department_id": str(setup.department_id),
            "academic_term_id": str(setup.academic_term_id),
        },
    )
    await session.commit()
    await session.refresh(setup)
    return setup


async def patch_setup(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    payload: SemesterSetupPatch,
) -> SemesterSetup:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    if payload.notes is not None:
        setup.notes = payload.notes

    await write_audit(
        session,
        action="semester_setup.patch",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"notes": setup.notes},
    )
    await session.commit()
    await session.refresh(setup)
    return setup


async def delete_setup(
    session: AsyncSession, *, actor: User, setup_id: UUID
) -> None:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    setup.deleted_at = utcnow()
    await write_audit(
        session,
        action="semester_setup.delete",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Course assignments ─────────────────────────────────────────────────────
_COURSE_TYPE_TO_TEMPLATE_NAME = {
    CourseType.theory: "Theory Standard",
    CourseType.integrated: "Integrated Standard",
    CourseType.lab: "Theory Standard",  # lab inherits theory template by default
    CourseType.nptel: "NPTEL Standard",
}


async def _pick_institutional_template(
    session: AsyncSession,
    *,
    college_id: UUID,
    course_type: CourseType,
) -> AssessmentSchemeTemplate | None:
    """Find the institutional template matching this course type. Returns None
    if no template seeded — caller falls back to creating an empty scheme so
    the FK on course_offerings.assessment_scheme_id can still be NULL safely.
    """
    name = _COURSE_TYPE_TO_TEMPLATE_NAME[course_type]
    row = await session.execute(
        select(AssessmentSchemeTemplate).where(
            AssessmentSchemeTemplate.college_id == college_id,
            AssessmentSchemeTemplate.owner_department_id.is_(None),
            AssessmentSchemeTemplate.name == name,
            AssessmentSchemeTemplate.is_active.is_(True),
            AssessmentSchemeTemplate.deleted_at.is_(None),
        )
    )
    return row.scalar_one_or_none()


async def _link_scheme_from_template(
    session: AsyncSession,
    *,
    offering: CourseOffering,
    course_type: CourseType,
    actor: User,
) -> None:
    """Idempotent: if the offering already has a scheme linked, no-op.
    Otherwise instantiate the institutional template's components on a
    fresh AssessmentScheme row and link it back from the offering.
    """
    if offering.assessment_scheme_id is not None:
        return  # already linked — never double-create

    template = await _pick_institutional_template(
        session, college_id=offering.college_id, course_type=course_type
    )
    if template is None:
        return  # no template seeded; offering keeps assessment_scheme_id NULL

    scheme = AssessmentScheme(
        college_id=offering.college_id,
        course_offering_id=offering.id,
        template_id=template.id,
        configured_by_user_id=actor.id,
        is_locked=False,
    )
    session.add(scheme)
    try:
        await session.flush()
    except IntegrityError as e:
        # Belt-and-braces: the unique index already protects against this,
        # but if a parallel insert wins the race we surface a clean error.
        await session.rollback()
        raise WorkflowError(
            "scheme_link_conflict",
            "another scheme already exists for this offering",
            409,
        ) from e

    for comp in template.default_components or []:
        session.add(
            AssessmentSchemeComponent(
                college_id=offering.college_id,
                assessment_scheme_id=scheme.id,
                kind=comp["kind"],
                label=comp["label"],
                max_marks=Decimal(str(comp["max_marks"])),
                weight_percent=Decimal(str(comp["weight_percent"])),
                ordinal=int(comp.get("ordinal", 1)),
                metadata_json=comp.get("metadata", {}),
            )
        )

    offering.assessment_scheme_id = scheme.id
    await session.flush()


async def add_course(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    payload: CourseAssignmentCreate,
) -> CourseOffering:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    # The course must belong to the same college; cross-department is
    # explicitly allowed (per CLAUDE.md authority table).
    course = await session.get(Course, payload.course_id)
    if (
        course is None
        or course.college_id != actor.college_id
        or course.deleted_at is not None
    ):
        raise WorkflowError("bad_course", "course not found", 400)

    section = await session.get(Section, payload.section_id)
    if (
        section is None
        or section.college_id != actor.college_id
        or section.deleted_at is not None
    ):
        raise WorkflowError("bad_section", "section not found", 400)

    teacher = await session.get(User, payload.teacher_user_id)
    if (
        teacher is None
        or teacher.college_id != actor.college_id
        or teacher.deleted_at is not None
        or teacher.role not in (UserRole.teacher, UserRole.hod)
    ):
        raise WorkflowError("bad_teacher", "teacher not found", 400)

    parent_offering = None
    if payload.parent_offering_id is not None:
        parent_offering = await session.get(CourseOffering, payload.parent_offering_id)
        if (
            parent_offering is None
            or parent_offering.college_id != actor.college_id
            or parent_offering.academic_term_id != setup.academic_term_id
            or parent_offering.deleted_at is not None
        ):
            raise WorkflowError(
                "bad_parent_offering",
                "parent offering must belong to this setup",
                400,
            )

    term = await session.get(AcademicTerm, setup.academic_term_id)
    if term is None:
        raise WorkflowError("bad_term", "term not found", 400)

    offering = CourseOffering(
        college_id=actor.college_id,
        course_id=payload.course_id,
        section_id=payload.section_id,
        teacher_user_id=payload.teacher_user_id,
        # The legacy VARCHAR column is still required (NOT NULL); keep it
        # in sync with the canonical term code so M3/M4 readers don't break.
        academic_term=term.code,
        academic_term_id=term.id,
        semester=course.semester,
        is_active=True,
        parent_offering_id=payload.parent_offering_id,
    )
    session.add(offering)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise WorkflowError(
            "duplicate_offering",
            "this course is already assigned to this section for the term",
            409,
        ) from e

    await _link_scheme_from_template(
        session, offering=offering, course_type=course.course_type, actor=actor
    )

    await write_audit(
        session,
        action="semester_setup.course_add",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "setup_id": str(setup.id),
            "course_id": str(payload.course_id),
            "section_id": str(payload.section_id),
            "teacher_user_id": str(payload.teacher_user_id),
        },
    )
    await session.commit()
    await session.refresh(offering)
    return offering


async def patch_course(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    offering_id: UUID,
    payload: CourseAssignmentPatch,
) -> CourseOffering:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    offering = await session.get(CourseOffering, offering_id)
    if (
        offering is None
        or offering.college_id != actor.college_id
        or offering.deleted_at is not None
        or offering.academic_term_id != setup.academic_term_id
    ):
        raise WorkflowError("not_found", "course offering not found", 404)

    if payload.teacher_user_id is not None:
        teacher = await session.get(User, payload.teacher_user_id)
        if (
            teacher is None
            or teacher.college_id != actor.college_id
            or teacher.deleted_at is not None
            or teacher.role not in (UserRole.teacher, UserRole.hod)
        ):
            raise WorkflowError("bad_teacher", "teacher not found", 400)
        offering.teacher_user_id = payload.teacher_user_id

    if payload.parent_offering_id is not None:
        parent_offering = await session.get(
            CourseOffering, payload.parent_offering_id
        )
        if (
            parent_offering is None
            or parent_offering.college_id != actor.college_id
            or parent_offering.academic_term_id != setup.academic_term_id
            or parent_offering.deleted_at is not None
            or parent_offering.id == offering.id
        ):
            raise WorkflowError("bad_parent_offering", "invalid parent", 400)
        offering.parent_offering_id = payload.parent_offering_id

    await write_audit(
        session,
        action="semester_setup.course_patch",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()
    await session.refresh(offering)
    return offering


async def remove_course(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    offering_id: UUID,
) -> None:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    offering = await session.get(CourseOffering, offering_id)
    if (
        offering is None
        or offering.college_id != actor.college_id
        or offering.deleted_at is not None
        or offering.academic_term_id != setup.academic_term_id
    ):
        raise WorkflowError("not_found", "course offering not found", 404)

    offering.deleted_at = utcnow()
    offering.is_active = False
    await write_audit(
        session,
        action="semester_setup.course_remove",
        entity_type="course_offering",
        entity_id=offering.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
    )
    await session.commit()


# ── Elective groups ─────────────────────────────────────────────────────────
async def add_elective_group(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    payload: ElectiveGroupCreate,
) -> ElectiveGroup:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    eg = ElectiveGroup(
        college_id=actor.college_id,
        semester_setup_id=setup.id,
        name=payload.name.strip(),
        description=payload.description,
        required_credits=payload.required_credits,
        min_enrollment_to_run=payload.min_enrollment_to_run,
        max_enrollment=payload.max_enrollment,
    )
    session.add(eg)
    await session.flush()
    await session.commit()
    await session.refresh(eg)
    return eg


async def patch_elective_group(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    eg_id: UUID,
    payload: ElectiveGroupPatch,
) -> ElectiveGroup:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    eg = await session.get(ElectiveGroup, eg_id)
    if (
        eg is None
        or eg.semester_setup_id != setup.id
        or eg.deleted_at is not None
    ):
        raise WorkflowError("not_found", "elective group not found", 404)

    if payload.name is not None:
        eg.name = payload.name.strip()
    if payload.description is not None:
        eg.description = payload.description
    if payload.required_credits is not None:
        eg.required_credits = payload.required_credits
    if payload.min_enrollment_to_run is not None:
        eg.min_enrollment_to_run = payload.min_enrollment_to_run
    if payload.max_enrollment is not None:
        eg.max_enrollment = payload.max_enrollment

    await session.commit()
    await session.refresh(eg)
    return eg


async def delete_elective_group(
    session: AsyncSession, *, actor: User, setup_id: UUID, eg_id: UUID
) -> None:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    eg = await session.get(ElectiveGroup, eg_id)
    if (
        eg is None
        or eg.semester_setup_id != setup.id
        or eg.deleted_at is not None
    ):
        raise WorkflowError("not_found", "elective group not found", 404)

    eg.deleted_at = utcnow()
    # Cascade to options (soft) so an empty group disappears cleanly.
    opt_rows = (
        await session.execute(
            select(ElectiveGroupOption).where(
                ElectiveGroupOption.elective_group_id == eg.id,
                ElectiveGroupOption.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    now = utcnow()
    for opt in opt_rows:
        opt.deleted_at = now
    await session.commit()


# ── Elective group options ──────────────────────────────────────────────────
async def add_elective_option(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    eg_id: UUID,
    payload: ElectiveGroupOptionCreate,
) -> ElectiveGroupOption:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    eg = await session.get(ElectiveGroup, eg_id)
    if (
        eg is None
        or eg.semester_setup_id != setup.id
        or eg.deleted_at is not None
    ):
        raise WorkflowError("not_found", "elective group not found", 404)

    course = await session.get(Course, payload.course_id)
    if (
        course is None
        or course.college_id != actor.college_id
        or course.deleted_at is not None
    ):
        raise WorkflowError("bad_course", "course not found", 400)

    if payload.tentative_teacher_id is not None:
        teacher = await session.get(User, payload.tentative_teacher_id)
        if (
            teacher is None
            or teacher.college_id != actor.college_id
            or teacher.role not in (UserRole.teacher, UserRole.hod)
        ):
            raise WorkflowError("bad_teacher", "teacher not found", 400)

    opt = ElectiveGroupOption(
        college_id=actor.college_id,
        elective_group_id=eg.id,
        course_id=payload.course_id,
        tentative_teacher_id=payload.tentative_teacher_id,
    )
    session.add(opt)
    await session.flush()
    await session.commit()
    await session.refresh(opt)
    return opt


async def patch_elective_option(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    eg_id: UUID,
    option_id: UUID,
    payload: ElectiveGroupOptionPatch,
) -> ElectiveGroupOption:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    opt = await session.get(ElectiveGroupOption, option_id)
    if (
        opt is None
        or opt.elective_group_id != eg_id
        or opt.deleted_at is not None
    ):
        raise WorkflowError("not_found", "option not found", 404)

    if payload.tentative_teacher_id is not None:
        teacher = await session.get(User, payload.tentative_teacher_id)
        if (
            teacher is None
            or teacher.college_id != actor.college_id
            or teacher.role not in (UserRole.teacher, UserRole.hod)
        ):
            raise WorkflowError("bad_teacher", "teacher not found", 400)
        opt.tentative_teacher_id = payload.tentative_teacher_id

    await session.commit()
    await session.refresh(opt)
    return opt


async def delete_elective_option(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    eg_id: UUID,
    option_id: UUID,
) -> None:
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)

    opt = await session.get(ElectiveGroupOption, option_id)
    if (
        opt is None
        or opt.elective_group_id != eg_id
        or opt.deleted_at is not None
    ):
        raise WorkflowError("not_found", "option not found", 404)

    opt.deleted_at = utcnow()
    await session.commit()


# ── Publish flow ────────────────────────────────────────────────────────────
async def _validate_publishable(
    session: AsyncSession, *, setup: SemesterSetup
) -> None:
    """Per M10a contract: at least one course assignment AND every assigned
    course has a tentative teacher. Throws with a precise code on failure
    so the UI can light up the right error.
    """
    rows = (
        await session.execute(
            select(CourseOffering, Course.department_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(
                CourseOffering.college_id == setup.college_id,
                CourseOffering.academic_term_id == setup.academic_term_id,
                Course.department_id == setup.department_id,
                CourseOffering.deleted_at.is_(None),
            )
        )
    ).all()
    if not rows:
        raise WorkflowError(
            "publish_no_courses",
            "publish requires at least one course assignment",
            409,
        )
    # course_offerings.teacher_user_id is NOT NULL at the DB level, but a
    # patch-to-null path would surface as a 500 — surface a clean error
    # instead. (We also test this with a future patch endpoint refusing it.)
    for off, _dept_id in rows:
        if off.teacher_user_id is None:
            raise WorkflowError(
                "publish_teacher_missing",
                f"offering {off.id} has no tentative teacher",
                409,
            )


async def publish_setup(
    session: AsyncSession, *, actor: User, setup_id: UUID
) -> tuple[SemesterSetup, dict[str, Any]]:
    """Transition draft → published → active in one transaction. The
    admin_notifications row is inserted in the same transaction. The
    event_bus publish happens AFTER commit so the event reflects committed
    state.

    Returns (setup, payload). The payload is the event payload — the
    caller can hand it back to the response or ignore it.
    """
    setup = await _get_active_setup(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_dept(actor, setup.department_id)
    _require_draft(setup)
    await _validate_publishable(session, setup=setup)

    now = datetime.now(timezone.utc)
    # Per the build plan: "draft → published → active in one shot, both
    # timestamps recorded". `published_at` records when the HOD signed off;
    # the move to `active` reflects the term being live by that point.
    setup.state = SemesterSetupState.active
    setup.published_at = now

    notification_payload = {
        "semester_setup_id": str(setup.id),
        "department_id": str(setup.department_id),
        "academic_term_id": str(setup.academic_term_id),
        "published_at": now.isoformat(),
        "published_by_user_id": str(actor.id),
    }
    session.add(
        AdminNotification(
            college_id=setup.college_id,
            event_type="semester_setup.published",
            payload=notification_payload,
        )
    )

    await write_audit(
        session,
        action="semester_setup.publish",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={"state": "active", "published_at": now.isoformat()},
    )
    await session.commit()
    await session.refresh(setup)

    # Best-effort event after commit. Failure here never reverses the publish.
    payload = await publish_event(
        "semester_setup.published",
        {
            "semester_setup_id": str(setup.id),
            "department_id": str(setup.department_id),
            "academic_term_id": str(setup.academic_term_id),
            "published_at": now.isoformat(),
        },
        college_id=setup.college_id,
        actor_user_id=actor.id,
    )
    return setup, payload


# ── Admin notifications ─────────────────────────────────────────────────────
async def list_admin_notifications(
    session: AsyncSession,
    *,
    actor: User,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AdminNotification], int]:
    if actor.role != UserRole.admin:
        raise WorkflowError("forbidden", "admin only", 403)

    stmt = select(AdminNotification).where(
        AdminNotification.college_id == actor.college_id
    )
    total = (
        await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
    ).scalar_one()
    rows = await session.execute(
        stmt.order_by(AdminNotification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), int(total)
