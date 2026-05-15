"""Service layer for M10b — elective registration + dissolution + cascade.

This file is the home of the most behaviourally complex logic in the
platform: the *cascade*. When a student is migrated from one elective
option to another, four downstream tables can be affected:

  1. `course_registrations`  — the source-of-truth elective state
  2. `enrollments`           — only when the offering's section changes
  3. `lab_batch_members`     — old offering's lab batch must release them
  4. `academic_overrides`    — append a typed audit row

`attendance_records` and `marks` are intentionally **preserved**: the
old offering's history stays in place for M3/M4 to reason about. The
new offering's eligibility starts from zero attendance once the migration
commits.

Everything that mutates state runs inside `async with session.begin()`.
If anything raises, the whole transaction rolls back — partial migration
across these tables is the worst possible bug.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.event_bus import publish as publish_event
from app.modules.academic.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    EnrollmentState,
    Section,
)
from app.modules.users.models import User, UserRole
from app.modules.workflow.models import (
    AcademicOverride,
    CourseRegistration,
    ElectiveGroup,
    ElectiveGroupOption,
    LabBatch,
    LabBatchMember,
    OverrideType,
    SemesterSetup,
    SemesterSetupState,
)
from app.modules.workflow.service import WorkflowError, _get_active_setup


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _get_setup_or_404(
    session: AsyncSession, *, setup_id: UUID, college_id: UUID
) -> SemesterSetup:
    return await _get_active_setup(
        session, setup_id=setup_id, college_id=college_id
    )


async def _get_option_or_404(
    session: AsyncSession, *, option_id: UUID, college_id: UUID
) -> ElectiveGroupOption:
    row = await session.execute(
        select(ElectiveGroupOption).where(
            ElectiveGroupOption.id == option_id,
            ElectiveGroupOption.college_id == college_id,
            ElectiveGroupOption.deleted_at.is_(None),
        )
    )
    opt = row.scalar_one_or_none()
    if opt is None:
        raise WorkflowError("not_found", "elective option not found", 404)
    return opt


async def _get_group_or_404(
    session: AsyncSession, *, eg_id: UUID, college_id: UUID
) -> ElectiveGroup:
    row = await session.execute(
        select(ElectiveGroup).where(
            ElectiveGroup.id == eg_id,
            ElectiveGroup.college_id == college_id,
            ElectiveGroup.deleted_at.is_(None),
        )
    )
    eg = row.scalar_one_or_none()
    if eg is None:
        raise WorkflowError("not_found", "elective group not found", 404)
    return eg


def _require_hod_for_setup(actor: User, setup: SemesterSetup) -> None:
    if (
        actor.role != UserRole.hod
        or actor.hod_of_department_id != setup.department_id
    ):
        raise WorkflowError("forbidden", "HOD of this department only", 403)


def _window_status(setup: SemesterSetup, now: datetime) -> tuple[bool, str]:
    """Returns (is_open, reason). Reason is the same string the API hands
    back to the client so the UI can render a precise message.
    """
    if setup.state not in (
        SemesterSetupState.published,
        SemesterSetupState.active,
    ):
        return False, "not_published"
    if setup.registration_opens_at is None or setup.registration_closes_at is None:
        return False, "window_not_set"
    if now < setup.registration_opens_at:
        return False, "not_yet_open"
    if now >= setup.registration_closes_at:
        return False, "closed"
    return True, "open"


async def _find_active_enrollment(
    session: AsyncSession,
    *,
    student_id: UUID,
    academic_term_id: UUID,
) -> Enrollment | None:
    """Locate the student's section enrollment for the given term."""
    rows = await session.execute(
        select(Enrollment).where(
            Enrollment.student_user_id == student_id,
            Enrollment.academic_term_id == academic_term_id,
            Enrollment.withdrawn_at.is_(None),
            Enrollment.enrollment_state == EnrollmentState.active,
        )
    )
    return rows.scalars().first()


async def _find_offering_for_option(
    session: AsyncSession,
    *,
    setup: SemesterSetup,
    course_id: UUID,
    section_id: UUID,
) -> CourseOffering | None:
    """The course_offering matching this elective option for a student in
    a particular section. Returns None when the HOD hasn't yet created an
    offering for the (course, section) pair — the caller decides what to
    do (registration view shows it as unavailable; cascade raises).
    """
    rows = await session.execute(
        select(CourseOffering).where(
            CourseOffering.college_id == setup.college_id,
            CourseOffering.course_id == course_id,
            CourseOffering.section_id == section_id,
            CourseOffering.academic_term_id == setup.academic_term_id,
            CourseOffering.deleted_at.is_(None),
        )
    )
    return rows.scalars().first()


# ── Registration window ─────────────────────────────────────────────────────
async def set_registration_window(
    session: AsyncSession,
    *,
    actor: User,
    setup_id: UUID,
    opens_at: datetime,
    closes_at: datetime,
) -> SemesterSetup:
    """HOD sets the window. Setup must be at least published (typically
    'active' because publish flips state to 'active' immediately in M10a).
    """
    setup = await _get_setup_or_404(
        session, setup_id=setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)
    if setup.state not in (SemesterSetupState.published, SemesterSetupState.active):
        raise WorkflowError(
            "not_published",
            f"setup is '{setup.state.value}' — publish first",
            409,
        )
    if closes_at <= opens_at:
        raise WorkflowError("bad_window", "closes_at must be after opens_at", 400)
    setup.registration_opens_at = opens_at
    setup.registration_closes_at = closes_at
    await write_audit(
        session,
        action="semester_setup.window_set",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=actor.id,
        college_id=actor.college_id,
        new_value={
            "registration_opens_at": opens_at.isoformat(),
            "registration_closes_at": closes_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(setup)
    return setup


# ── Student registration view ───────────────────────────────────────────────
async def _setup_for_student(
    session: AsyncSession, *, student: User
) -> SemesterSetup | None:
    """The current-term setup for the student's department.

    A student belongs to a department via their active section enrollment
    (sections → batches → departments). M10b's MVP looks at the most
    recent active enrollment to determine this. The setup must be in a
    post-draft state to be visible to the student.
    """
    rows = await session.execute(
        select(Enrollment, Section)
        .join(Section, Section.id == Enrollment.section_id)
        .where(
            Enrollment.student_user_id == student.id,
            Enrollment.withdrawn_at.is_(None),
            Enrollment.enrollment_state == EnrollmentState.active,
        )
        .order_by(Enrollment.enrolled_at.desc())
    )
    enroll_row = rows.first()
    if enroll_row is None:
        return None
    enrollment, section = enroll_row
    # The department comes from the batch the section belongs to.
    from app.modules.academic.models import Batch  # local — avoids cycles

    batch = await session.get(Batch, section.batch_id)
    if batch is None:
        return None

    # The setup must be for (department, term) and published/active.
    rows2 = await session.execute(
        select(SemesterSetup).where(
            SemesterSetup.college_id == student.college_id,
            SemesterSetup.department_id == batch.department_id,
            SemesterSetup.academic_term_id == enrollment.academic_term_id,
            SemesterSetup.deleted_at.is_(None),
            SemesterSetup.state.in_(
                [SemesterSetupState.published, SemesterSetupState.active]
            ),
        )
    )
    return rows2.scalars().first()


async def _option_enrollment_count(
    session: AsyncSession, *, option_id: UUID
) -> int:
    """Number of students currently registered for the option (status='approved')."""
    n = (
        await session.execute(
            select(func.count(CourseRegistration.id)).where(
                CourseRegistration.elective_group_option_id == option_id,
                CourseRegistration.status == "approved",
                CourseRegistration.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return int(n)


async def get_student_registration_view(
    session: AsyncSession, *, student: User
) -> dict[str, Any]:
    setup = await _setup_for_student(session, student=student)
    if setup is None:
        return {
            "semester_setup_id": None,
            "academic_term_code": None,
            "department_code": None,
            "window": {
                "is_open": False,
                "opens_at": None,
                "closes_at": None,
                "reason": "no_setup",
            },
            "mandatory_courses": [],
            "groups": [],
            "migration_alert": None,
        }

    now = datetime.now(timezone.utc)
    is_open, reason = _window_status(setup, now)
    dept = await session.get(Department, setup.department_id)
    term = await session.get(AcademicTerm, setup.academic_term_id)

    enrollment = await _find_active_enrollment(
        session, student_id=student.id, academic_term_id=setup.academic_term_id
    )

    # Mandatory courses = course_offerings in this setup whose course is
    # NOT referenced by any elective_group_option. We scope to the student's
    # section so they only see their own offerings.
    elective_course_ids_q = select(ElectiveGroupOption.course_id).where(
        ElectiveGroupOption.elective_group_id.in_(
            select(ElectiveGroup.id).where(
                ElectiveGroup.semester_setup_id == setup.id,
                ElectiveGroup.deleted_at.is_(None),
            )
        ),
        ElectiveGroupOption.deleted_at.is_(None),
    )
    mandatory_rows = []
    if enrollment is not None:
        rows = (
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
                    CourseOffering.college_id == setup.college_id,
                    CourseOffering.academic_term_id == setup.academic_term_id,
                    CourseOffering.section_id == enrollment.section_id,
                    CourseOffering.deleted_at.is_(None),
                    Course.id.not_in(elective_course_ids_q),
                )
                .order_by(Course.code)
            )
        ).all()
        for r in rows:
            off = r[0]
            mandatory_rows.append(
                {
                    "course_offering_id": off.id,
                    "course_id": off.course_id,
                    "course_code": r.code,
                    "course_title": r.title,
                    "course_type": r.course_type,
                    "section_name": r.section_name,
                    "teacher_name": r.teacher_name,
                }
            )

    # Groups
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

    # Pre-fetch current registrations for this student in this setup
    cur_rows = (
        await session.execute(
            select(CourseRegistration).where(
                CourseRegistration.student_user_id == student.id,
                CourseRegistration.semester_setup_id == setup.id,
                CourseRegistration.deleted_at.is_(None),
                CourseRegistration.status.in_(["approved", "pending"]),
            )
        )
    ).scalars().all()
    chosen_by_group = {r.elective_group_id: r.elective_group_option_id for r in cur_rows if r.elective_group_id is not None}

    groups: list[dict[str, Any]] = []
    for eg in eg_rows:
        opt_rows = (
            await session.execute(
                select(
                    ElectiveGroupOption,
                    Course.code,
                    Course.title,
                    Course.course_type,
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
        options_view = []
        for o in opt_rows:
            opt = o[0]
            count = await _option_enrollment_count(session, option_id=opt.id)
            is_full = (
                opt.max_enrollment is not None and count >= opt.max_enrollment
            )
            options_view.append(
                {
                    "option_id": opt.id,
                    "course_id": opt.course_id,
                    "course_code": o.code,
                    "course_title": o.title,
                    "course_type": o.course_type,
                    "tentative_teacher_id": opt.tentative_teacher_id,
                    "tentative_teacher_name": o.teacher_name,
                    "current_enrollment": count,
                    "min_enrollment_to_run": eg.min_enrollment_to_run,
                    "max_enrollment": opt.max_enrollment,
                    "is_dissolved": opt.is_dissolved,
                    "is_full": is_full,
                }
            )
        groups.append(
            {
                "elective_group_id": eg.id,
                "name": eg.name,
                "description": eg.description,
                "required_credits": eg.required_credits,
                "options": options_view,
                "chosen_option_id": chosen_by_group.get(eg.id),
            }
        )

    # Migration alert: any course_registrations for this student in this
    # setup with status='migrated'. Surfaces a "Your elective was changed"
    # banner until M5 owns notifications.
    migrated_rows = (
        await session.execute(
            select(CourseRegistration).where(
                CourseRegistration.student_user_id == student.id,
                CourseRegistration.semester_setup_id == setup.id,
                CourseRegistration.status == "migrated",
                CourseRegistration.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    migration_alert: dict | None = None
    if migrated_rows:
        migration_alert = {
            "count": len(migrated_rows),
            "message": (
                "One or more of your electives was changed by your HOD. "
                "Your new assignment is shown below."
            ),
        }

    return {
        "semester_setup_id": setup.id,
        "academic_term_code": term.code if term else None,
        "department_code": dept.code if dept else None,
        "window": {
            "is_open": is_open,
            "opens_at": setup.registration_opens_at,
            "closes_at": setup.registration_closes_at,
            "reason": reason,
        },
        "mandatory_courses": mandatory_rows,
        "groups": groups,
        "migration_alert": migration_alert,
    }


async def submit_student_registration(
    session: AsyncSession,
    *,
    student: User,
    choices: list[tuple[UUID, UUID]],
) -> list[CourseRegistration]:
    """Idempotent: subsequent submissions replace prior 'approved' rows
    for the same group. Each elective group must have exactly one choice.
    Validates: window open, options live in this setup's groups, option
    not dissolved, option not at capacity (when capped), student belongs
    to a section that has an offering for the chosen course.
    """
    setup = await _setup_for_student(session, student=student)
    if setup is None:
        raise WorkflowError("no_setup", "no semester setup for your term", 400)

    now = datetime.now(timezone.utc)
    is_open, reason = _window_status(setup, now)
    if not is_open:
        raise WorkflowError(
            "window_closed", f"registration is {reason.replace('_', ' ')}", 400
        )

    enrollment = await _find_active_enrollment(
        session, student_id=student.id, academic_term_id=setup.academic_term_id
    )
    if enrollment is None:
        raise WorkflowError(
            "no_enrollment", "you have no active enrollment for this term", 400
        )

    # Fetch all groups in this setup once.
    eg_rows = (
        await session.execute(
            select(ElectiveGroup).where(
                ElectiveGroup.semester_setup_id == setup.id,
                ElectiveGroup.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    eg_ids = {eg.id for eg in eg_rows}
    if not choices and eg_ids:
        raise WorkflowError(
            "choices_required",
            f"must pick one option per elective group ({len(eg_ids)} expected)",
            400,
        )

    # Each group must appear exactly once.
    seen_groups: set[UUID] = set()
    options_lookup: dict[UUID, ElectiveGroupOption] = {}
    for eg_id, opt_id in choices:
        if eg_id in seen_groups:
            raise WorkflowError(
                "duplicate_group", f"group {eg_id} chosen twice", 400
            )
        seen_groups.add(eg_id)
        if eg_id not in eg_ids:
            raise WorkflowError(
                "bad_group", f"group {eg_id} not in this setup", 400
            )
        opt = await _get_option_or_404(
            session, option_id=opt_id, college_id=student.college_id
        )
        if opt.elective_group_id != eg_id:
            raise WorkflowError(
                "bad_option", "option does not belong to this group", 400
            )
        if opt.is_dissolved:
            raise WorkflowError(
                "option_dissolved", "this option has been dissolved", 400
            )
        # Capacity (when capped). We allow the existing student's own seat
        # to count toward "current" so they can re-submit the same choice
        # even when capped.
        if opt.max_enrollment is not None:
            existing = (
                await session.execute(
                    select(CourseRegistration).where(
                        CourseRegistration.student_user_id == student.id,
                        CourseRegistration.elective_group_option_id == opt.id,
                        CourseRegistration.status == "approved",
                        CourseRegistration.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if existing is None:
                count = await _option_enrollment_count(session, option_id=opt.id)
                if count >= opt.max_enrollment:
                    raise WorkflowError(
                        "option_full",
                        "this option is at capacity",
                        409,
                    )

        # Offering must exist for the student's section.
        offering = await _find_offering_for_option(
            session,
            setup=setup,
            course_id=opt.course_id,
            section_id=enrollment.section_id,
        )
        if offering is None:
            raise WorkflowError(
                "no_offering",
                f"no offering of {opt.course_id} for your section yet",
                409,
            )
        options_lookup[eg_id] = opt

    if seen_groups != eg_ids:
        missing = eg_ids - seen_groups
        raise WorkflowError(
            "choices_required",
            f"missing pick for groups: {sorted(map(str, missing))}",
            400,
        )

    # Idempotent upsert: for each group, locate the prior 'approved' row
    # (if any) and patch it; otherwise insert. The prior row keeps its
    # created_at so by_registration_order is stable.
    out_rows: list[CourseRegistration] = []
    for eg_id, opt in options_lookup.items():
        prior = (
            await session.execute(
                select(CourseRegistration).where(
                    CourseRegistration.student_user_id == student.id,
                    CourseRegistration.semester_setup_id == setup.id,
                    CourseRegistration.elective_group_id == eg_id,
                    CourseRegistration.status == "approved",
                    CourseRegistration.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if prior is None:
            row = CourseRegistration(
                college_id=student.college_id,
                student_user_id=student.id,
                semester_setup_id=setup.id,
                elective_group_id=eg_id,
                elective_group_option_id=opt.id,
                course_id=opt.course_id,
                status="approved",
                is_backlog=False,
            )
            session.add(row)
            out_rows.append(row)
        else:
            prior.elective_group_option_id = opt.id
            prior.course_id = opt.course_id
            out_rows.append(prior)

    await write_audit(
        session,
        action="student_registration.submit",
        entity_type="semester_setup",
        entity_id=setup.id,
        actor_user_id=student.id,
        college_id=student.college_id,
        new_value={
            "choices": [
                {"elective_group_id": str(eg_id), "option_id": str(opt.id)}
                for eg_id, opt in options_lookup.items()
            ],
        },
    )
    await session.commit()
    for r in out_rows:
        await session.refresh(r)
    return out_rows


async def get_student_registration_status(
    session: AsyncSession, *, student: User
) -> list[CourseRegistration]:
    rows = await session.execute(
        select(CourseRegistration).where(
            CourseRegistration.student_user_id == student.id,
            CourseRegistration.deleted_at.is_(None),
        ).order_by(CourseRegistration.created_at.desc())
    )
    return list(rows.scalars().all())


# ── HOD enrollment view ─────────────────────────────────────────────────────
async def get_group_enrollment_view(
    session: AsyncSession, *, actor: User, eg_id: UUID
) -> dict[str, Any]:
    eg = await _get_group_or_404(session, eg_id=eg_id, college_id=actor.college_id)
    setup = await _get_setup_or_404(
        session, setup_id=eg.semester_setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)

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

    options: list[dict[str, Any]] = []
    for o in opt_rows:
        opt = o[0]
        count = await _option_enrollment_count(session, option_id=opt.id)
        if count < eg.min_enrollment_to_run:
            status: Literal["under_subscribed", "over_subscribed", "healthy"] = (
                "under_subscribed"
            )
        elif opt.max_enrollment is not None and count > opt.max_enrollment:
            status = "over_subscribed"
        else:
            status = "healthy"

        students_q = await session.execute(
            select(CourseRegistration, User)
            .join(User, User.id == CourseRegistration.student_user_id)
            .where(
                CourseRegistration.elective_group_option_id == opt.id,
                CourseRegistration.status == "approved",
                CourseRegistration.deleted_at.is_(None),
            )
            .order_by(CourseRegistration.created_at, CourseRegistration.id)
        )
        students = [
            {
                "student_user_id": u.id,
                "usn": u.usn,
                "name": u.name,
                "registered_at": cr.created_at,
            }
            for cr, u in students_q.all()
        ]
        options.append(
            {
                "option_id": opt.id,
                "course_id": opt.course_id,
                "course_code": o.code,
                "course_title": o.title,
                "tentative_teacher_id": opt.tentative_teacher_id,
                "tentative_teacher_name": o.teacher_name,
                "is_dissolved": opt.is_dissolved,
                "current_enrollment": count,
                "status": status,
                "students": students,
            }
        )

    return {
        "elective_group_id": eg.id,
        "semester_setup_id": eg.semester_setup_id,
        "name": eg.name,
        "min_enrollment_to_run": eg.min_enrollment_to_run,
        "max_enrollment": eg.max_enrollment,
        "options": options,
    }


# ── The cascade core ────────────────────────────────────────────────────────
async def _perform_student_migration(
    session: AsyncSession,
    *,
    college_id: UUID,
    setup: SemesterSetup,
    student_id: UUID,
    elective_group_id: UUID,
    from_option: ElectiveGroupOption,
    to_option: ElectiveGroupOption,
    actor: User,
    reason_code: Literal[
        "elective_dissolved",
        "manual_migration",
        "capacity_redistribution",
    ],
    reason_text: str,
) -> dict[str, Any]:
    """Move one student from `from_option` to `to_option`.

    Writes inside the current open transaction (caller manages
    `session.begin()`). Returns a diagnostic dict the caller aggregates
    into the cascade summary.

    Steps:
      1. Locate the student's active enrollment for the setup's term.
      2. Locate old + new course_offerings (course_id × student section).
      3. Patch the elective course_registrations row: old → 'migrated',
         new row → 'approved' (the new row has a fresh created_at).
      4. If new section ≠ old section: withdraw the old enrollment and
         create a new one for the new section. Within-section: no-op.
      5. Soft-remove old offering's lab_batch_members for this student.
      6. Append `academic_overrides` (override_type='student_migration').

    The function does **not** publish events — caller emits after commit.
    """
    if from_option.id == to_option.id:
        raise WorkflowError(
            "bad_target", "from and to options must differ", 400
        )
    if from_option.elective_group_id != to_option.elective_group_id:
        raise WorkflowError(
            "bad_target", "options must be in the same group", 400
        )
    if to_option.is_dissolved:
        raise WorkflowError("target_dissolved", "target option is dissolved", 400)

    enrollment = await _find_active_enrollment(
        session, student_id=student_id, academic_term_id=setup.academic_term_id
    )
    if enrollment is None:
        raise WorkflowError(
            "no_enrollment", "student has no active enrollment for this term", 400
        )

    old_offering = await _find_offering_for_option(
        session,
        setup=setup,
        course_id=from_option.course_id,
        section_id=enrollment.section_id,
    )
    new_offering = await _find_offering_for_option(
        session,
        setup=setup,
        course_id=to_option.course_id,
        section_id=enrollment.section_id,
    )
    if old_offering is None:
        raise WorkflowError(
            "no_source_offering",
            "old offering not found for student's section",
            409,
        )
    if new_offering is None:
        raise WorkflowError(
            "no_target_offering",
            "target offering not found for student's section",
            409,
        )

    # 1. course_registrations
    old_reg = (
        await session.execute(
            select(CourseRegistration).where(
                CourseRegistration.student_user_id == student_id,
                CourseRegistration.semester_setup_id == setup.id,
                CourseRegistration.elective_group_id == elective_group_id,
                CourseRegistration.elective_group_option_id == from_option.id,
                CourseRegistration.status == "approved",
                CourseRegistration.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if old_reg is None:
        # The student isn't actually on this option (likely already moved).
        # That's not a per-student failure — the dissolve / cap loops simply
        # skip them. Raise a precise code so callers can decide.
        raise WorkflowError(
            "no_registration", "student not registered on source option", 409
        )

    old_reg.status = "migrated"
    new_reg = CourseRegistration(
        college_id=college_id,
        student_user_id=student_id,
        semester_setup_id=setup.id,
        elective_group_id=elective_group_id,
        elective_group_option_id=to_option.id,
        course_id=to_option.course_id,
        status="approved",
        is_backlog=False,
    )
    session.add(new_reg)
    await session.flush()  # surface FK / unique violations promptly

    # 2. enrollments — only mutated when section changes
    enrollment_mutations = 0
    if old_offering.section_id != new_offering.section_id:
        enrollment.enrollment_state = EnrollmentState.migrated
        enrollment.withdrawn_at = utcnow()
        new_enrollment = Enrollment(
            college_id=college_id,
            student_user_id=student_id,
            section_id=new_offering.section_id,
            academic_term=enrollment.academic_term,
            academic_term_id=enrollment.academic_term_id,
            semester=enrollment.semester,
            enrolled_at=utcnow(),
            enrollment_state=EnrollmentState.active,
        )
        session.add(new_enrollment)
        enrollment_mutations = 1
        await session.flush()

    # 3. lab_batch_members for old offering — soft remove
    batch_member_rows = (
        await session.execute(
            select(LabBatchMember)
            .join(LabBatch, LabBatch.id == LabBatchMember.lab_batch_id)
            .where(
                LabBatchMember.student_user_id == student_id,
                LabBatchMember.removed_at.is_(None),
                LabBatch.course_offering_id == old_offering.id,
                LabBatch.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    now = utcnow()
    for m in batch_member_rows:
        m.removed_at = now
        m.removed_reason = "migrated_to_other_offering"

    # 4. academic_overrides — append-only audit
    session.add(
        AcademicOverride(
            college_id=college_id,
            override_type=OverrideType.student_migration,
            actor_user_id=actor.id,
            target_student_user_id=student_id,
            target_course_offering_id=old_offering.id,
            target_entity_type="course_registration",
            target_entity_id=old_reg.id,
            old_value={
                "elective_group_option_id": str(from_option.id),
                "course_offering_id": str(old_offering.id),
                "section_id": str(old_offering.section_id),
            },
            new_value={
                "elective_group_option_id": str(to_option.id),
                "course_offering_id": str(new_offering.id),
                "section_id": str(new_offering.section_id),
            },
            reason=reason_text,
        )
    )

    return {
        "student_id": str(student_id),
        "from_course_offering_id": str(old_offering.id),
        "to_course_offering_id": str(new_offering.id),
        "elective_group_id": str(elective_group_id),
        "reason": reason_code,
        "lab_batch_memberships_removed": len(batch_member_rows),
        "enrollment_rows_mutated": enrollment_mutations,
    }


async def _measure_preserved_history(
    session: AsyncSession,
    *,
    student_ids: list[UUID],
    offering_ids: list[UUID],
) -> dict[str, int]:
    """Count attendance + marks rows that would be preserved by the
    cascade. These are NOT mutated; the count is informational for the
    preview UI ("60 attendance records preserved").
    """
    if not student_ids or not offering_ids:
        return {"attendance_records_preserved": 0, "marks_preserved": 0}

    # attendance_records → class_sessions(course_offering_id)
    from app.modules.attendance.models import AttendanceRecord, ClassSession
    from app.modules.marks.models import Assessment, Mark

    att = (
        await session.execute(
            select(func.count(AttendanceRecord.id))
            .join(ClassSession, ClassSession.id == AttendanceRecord.class_session_id)
            .where(
                AttendanceRecord.student_user_id.in_(student_ids),
                ClassSession.course_offering_id.in_(offering_ids),
            )
        )
    ).scalar_one()
    marks = (
        await session.execute(
            select(func.count(Mark.id))
            .join(Assessment, Assessment.id == Mark.assessment_id)
            .where(
                Mark.student_user_id.in_(student_ids),
                Assessment.course_offering_id.in_(offering_ids),
            )
        )
    ).scalar_one()
    return {
        "attendance_records_preserved": int(att),
        "marks_preserved": int(marks),
    }


# ── Dissolve (preview + commit) ─────────────────────────────────────────────
async def _registered_students_on_option(
    session: AsyncSession, *, option_id: UUID
) -> list[UUID]:
    rows = await session.execute(
        select(CourseRegistration.student_user_id)
        .where(
            CourseRegistration.elective_group_option_id == option_id,
            CourseRegistration.status == "approved",
            CourseRegistration.deleted_at.is_(None),
        )
        .order_by(CourseRegistration.created_at, CourseRegistration.id)
    )
    return [r[0] for r in rows.all()]


async def dissolve_option_preview(
    session: AsyncSession,
    *,
    actor: User,
    eg_id: UUID,
    option_id: UUID,
    target_option_id: UUID,
) -> dict[str, Any]:
    """Returns the blast-radius without mutating. Same auth as dissolve."""
    eg = await _get_group_or_404(session, eg_id=eg_id, college_id=actor.college_id)
    setup = await _get_setup_or_404(
        session, setup_id=eg.semester_setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)

    from_opt = await _get_option_or_404(
        session, option_id=option_id, college_id=actor.college_id
    )
    to_opt = await _get_option_or_404(
        session, option_id=target_option_id, college_id=actor.college_id
    )
    if from_opt.elective_group_id != eg.id or to_opt.elective_group_id != eg.id:
        raise WorkflowError(
            "bad_target", "options must be in this group", 400
        )
    if from_opt.id == to_opt.id:
        raise WorkflowError(
            "bad_target", "target must differ from source", 400
        )
    if to_opt.is_dissolved:
        raise WorkflowError("target_dissolved", "target option is dissolved", 400)
    if from_opt.is_dissolved:
        raise WorkflowError(
            "source_dissolved", "this option is already dissolved", 409
        )

    student_ids = await _registered_students_on_option(
        session, option_id=from_opt.id
    )

    # Approximate per-student lookups for blast radius. Walk each student
    # and compute what would happen.
    affected_offering_ids: set[UUID] = set()
    enrollment_mutations = 0
    lab_member_count = 0
    per_student: list[dict[str, Any]] = []
    for sid in student_ids:
        enrollment = await _find_active_enrollment(
            session, student_id=sid, academic_term_id=setup.academic_term_id
        )
        if enrollment is None:
            per_student.append(
                {"student_id": str(sid), "skipped": "no_enrollment"}
            )
            continue
        old_off = await _find_offering_for_option(
            session,
            setup=setup,
            course_id=from_opt.course_id,
            section_id=enrollment.section_id,
        )
        new_off = await _find_offering_for_option(
            session,
            setup=setup,
            course_id=to_opt.course_id,
            section_id=enrollment.section_id,
        )
        if old_off is None or new_off is None:
            per_student.append(
                {"student_id": str(sid), "skipped": "missing_offering"}
            )
            continue
        affected_offering_ids.add(old_off.id)
        affected_offering_ids.add(new_off.id)
        if old_off.section_id != new_off.section_id:
            enrollment_mutations += 1
        # lab_batch_members count for old offering for this student
        n = (
            await session.execute(
                select(func.count(LabBatchMember.id))
                .join(LabBatch, LabBatch.id == LabBatchMember.lab_batch_id)
                .where(
                    LabBatchMember.student_user_id == sid,
                    LabBatchMember.removed_at.is_(None),
                    LabBatch.course_offering_id == old_off.id,
                    LabBatch.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        lab_member_count += int(n)
        per_student.append(
            {
                "student_id": str(sid),
                "from_course_offering_id": str(old_off.id),
                "to_course_offering_id": str(new_off.id),
            }
        )

    preserved = await _measure_preserved_history(
        session,
        student_ids=student_ids,
        offering_ids=list(affected_offering_ids),
    )
    return {
        "students_migrated": len(
            [p for p in per_student if "skipped" not in p]
        ),
        "attendance_records_preserved": preserved["attendance_records_preserved"],
        "marks_preserved": preserved["marks_preserved"],
        "lab_batch_memberships_removed": lab_member_count,
        "enrollment_rows_mutated": enrollment_mutations,
        "affected_offering_ids": [str(i) for i in affected_offering_ids],
        "per_student": per_student,
    }


async def dissolve_option(
    session: AsyncSession,
    *,
    actor: User,
    eg_id: UUID,
    option_id: UUID,
    target_option_id: UUID,
    reason: str,
    evidence_url: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Dissolve the option, migrate every approved registrant to
    `target_option_id`. ONE transaction wraps the whole loop — any
    per-student failure rolls back the entire dissolution.

    Returns (cascade_summary, dissolved_event_payload,
    student_migrated_event_payloads). The caller publishes the events
    AFTER commit.
    """
    eg = await _get_group_or_404(session, eg_id=eg_id, college_id=actor.college_id)
    setup = await _get_setup_or_404(
        session, setup_id=eg.semester_setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)

    from_opt = await _get_option_or_404(
        session, option_id=option_id, college_id=actor.college_id
    )
    to_opt = await _get_option_or_404(
        session, option_id=target_option_id, college_id=actor.college_id
    )
    if from_opt.elective_group_id != eg.id or to_opt.elective_group_id != eg.id:
        raise WorkflowError(
            "bad_target", "options must be in this group", 400
        )
    if from_opt.id == to_opt.id:
        raise WorkflowError("bad_target", "target must differ from source", 400)
    if to_opt.is_dissolved:
        raise WorkflowError("target_dissolved", "target option is dissolved", 400)
    if from_opt.is_dissolved:
        raise WorkflowError("source_dissolved", "already dissolved", 409)

    student_ids = await _registered_students_on_option(
        session, option_id=from_opt.id
    )

    per_student_diag: list[dict[str, Any]] = []
    affected_offering_ids: set[UUID] = set()
    student_migrated_payloads: list[dict[str, Any]] = []
    try:
        for sid in student_ids:
            diag = await _perform_student_migration(
                session,
                college_id=actor.college_id,
                setup=setup,
                student_id=sid,
                elective_group_id=eg.id,
                from_option=from_opt,
                to_option=to_opt,
                actor=actor,
                reason_code="elective_dissolved",
                reason_text=reason,
            )
            per_student_diag.append(diag)
            affected_offering_ids.add(UUID(diag["from_course_offering_id"]))
            affected_offering_ids.add(UUID(diag["to_course_offering_id"]))
            student_migrated_payloads.append(
                {
                    "student_id": diag["student_id"],
                    "from_course_offering_id": diag["from_course_offering_id"],
                    "to_course_offering_id": diag["to_course_offering_id"],
                    "elective_group_id": str(eg.id),
                    "reason": "elective_dissolved",
                }
            )

        # Flip the option's dissolved bit.
        from_opt.is_dissolved = True
        from_opt.dissolved_at = utcnow()
        from_opt.dissolved_by_user_id = actor.id
        from_opt.dissolved_reason = reason
        from_opt.migrated_to_option_id = to_opt.id

        await write_audit(
            session,
            action="elective_option.dissolve",
            entity_type="elective_group_option",
            entity_id=from_opt.id,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={
                "target_option_id": str(to_opt.id),
                "student_count": len(per_student_diag),
                "reason": reason,
                "evidence_url": evidence_url,
            },
        )
        await session.commit()
    except WorkflowError:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise WorkflowError("cascade_failed", f"dissolution failed: {e}", 500) from e

    preserved = await _measure_preserved_history(
        session,
        student_ids=student_ids,
        offering_ids=list(affected_offering_ids),
    )
    summary = {
        "students_migrated": len(per_student_diag),
        "attendance_records_preserved": preserved["attendance_records_preserved"],
        "marks_preserved": preserved["marks_preserved"],
        "lab_batch_memberships_removed": sum(
            d["lab_batch_memberships_removed"] for d in per_student_diag
        ),
        "enrollment_rows_mutated": sum(
            d["enrollment_rows_mutated"] for d in per_student_diag
        ),
        "affected_offering_ids": [str(i) for i in affected_offering_ids],
        "per_student": per_student_diag,
    }
    dissolved_payload = {
        "elective_group_id": str(eg.id),
        "dissolved_option_id": str(from_opt.id),
        "target_option_id": str(to_opt.id),
        "student_count_migrated": len(per_student_diag),
        "reason": reason,
    }
    return summary, dissolved_payload, student_migrated_payloads


# ── Manual migration ────────────────────────────────────────────────────────
async def migrate_student_manual(
    session: AsyncSession,
    *,
    actor: User,
    eg_id: UUID,
    student_id: UUID,
    from_option_id: UUID,
    to_option_id: UUID,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    eg = await _get_group_or_404(session, eg_id=eg_id, college_id=actor.college_id)
    setup = await _get_setup_or_404(
        session, setup_id=eg.semester_setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)

    from_opt = await _get_option_or_404(
        session, option_id=from_option_id, college_id=actor.college_id
    )
    to_opt = await _get_option_or_404(
        session, option_id=to_option_id, college_id=actor.college_id
    )
    if from_opt.elective_group_id != eg.id or to_opt.elective_group_id != eg.id:
        raise WorkflowError("bad_target", "options must be in this group", 400)
    if to_opt.is_dissolved:
        raise WorkflowError("target_dissolved", "target option is dissolved", 400)
    if to_opt.max_enrollment is not None:
        cur = await _option_enrollment_count(session, option_id=to_opt.id)
        if cur >= to_opt.max_enrollment:
            raise WorkflowError("target_full", "target option at capacity", 409)

    try:
        diag = await _perform_student_migration(
            session,
            college_id=actor.college_id,
            setup=setup,
            student_id=student_id,
            elective_group_id=eg.id,
            from_option=from_opt,
            to_option=to_opt,
            actor=actor,
            reason_code="manual_migration",
            reason_text=reason,
        )
        await write_audit(
            session,
            action="elective_option.manual_migrate",
            entity_type="course_registration",
            entity_id=UUID(diag["student_id"]),
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={
                "student_id": diag["student_id"],
                "from_option_id": str(from_opt.id),
                "to_option_id": str(to_opt.id),
                "reason": reason,
            },
        )
        await session.commit()
    except WorkflowError:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise WorkflowError("cascade_failed", f"migration failed: {e}", 500) from e

    preserved = await _measure_preserved_history(
        session,
        student_ids=[student_id],
        offering_ids=[
            UUID(diag["from_course_offering_id"]),
            UUID(diag["to_course_offering_id"]),
        ],
    )
    summary = {
        "students_migrated": 1,
        "attendance_records_preserved": preserved["attendance_records_preserved"],
        "marks_preserved": preserved["marks_preserved"],
        "lab_batch_memberships_removed": diag["lab_batch_memberships_removed"],
        "enrollment_rows_mutated": diag["enrollment_rows_mutated"],
        "affected_offering_ids": [
            diag["from_course_offering_id"],
            diag["to_course_offering_id"],
        ],
        "per_student": [diag],
    }
    student_migrated_payload = {
        "student_id": diag["student_id"],
        "from_course_offering_id": diag["from_course_offering_id"],
        "to_course_offering_id": diag["to_course_offering_id"],
        "elective_group_id": str(eg.id),
        "reason": "manual_migration",
    }
    return summary, student_migrated_payload


# ── Capacity cap ────────────────────────────────────────────────────────────
async def cap_option_capacity(
    session: AsyncSession,
    *,
    actor: User,
    eg_id: UUID,
    option_id: UUID,
    max_enrollment: int,
    redistribute_to_option_id: UUID | None,
    redistribute_strategy: Literal["by_registration_order", "manual"] | None,
) -> dict[str, Any]:
    """Set per-option cap. If existing enrollment > cap and a target +
    strategy are provided:
      - by_registration_order: keep first N by (created_at ASC, id ASC),
        displace the rest by cascading to target.
      - manual: return the displaced list without mutating; HOD reads
        names and runs manual_migrate per student.

    If no displacement is needed (current <= cap), just updates the cap.
    """
    eg = await _get_group_or_404(session, eg_id=eg_id, college_id=actor.college_id)
    setup = await _get_setup_or_404(
        session, setup_id=eg.semester_setup_id, college_id=actor.college_id
    )
    _require_hod_for_setup(actor, setup)

    opt = await _get_option_or_404(
        session, option_id=option_id, college_id=actor.college_id
    )
    if opt.elective_group_id != eg.id:
        raise WorkflowError("bad_option", "option not in this group", 400)
    if max_enrollment < 1:
        raise WorkflowError("bad_max", "max_enrollment must be >= 1", 400)

    cur_rows = (
        await session.execute(
            select(CourseRegistration, User)
            .join(User, User.id == CourseRegistration.student_user_id)
            .where(
                CourseRegistration.elective_group_option_id == opt.id,
                CourseRegistration.status == "approved",
                CourseRegistration.deleted_at.is_(None),
            )
            .order_by(CourseRegistration.created_at, CourseRegistration.id)
        )
    ).all()
    current = len(cur_rows)
    overflow = max(0, current - max_enrollment)

    # No overflow: just set the cap, commit, done.
    if overflow == 0:
        opt.max_enrollment = max_enrollment
        await write_audit(
            session,
            action="elective_option.cap_set",
            entity_type="elective_group_option",
            entity_id=opt.id,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={"max_enrollment": max_enrollment},
        )
        await session.commit()
        return {
            "new_max": max_enrollment,
            "displaced": [],
            "summary": None,
            "events": [],
        }

    # Overflow exists → must redistribute. Target + strategy required.
    if redistribute_to_option_id is None or redistribute_strategy is None:
        raise WorkflowError(
            "need_target",
            (
                f"{overflow} student(s) over cap — provide "
                "redistribute_to_option_id + redistribute_strategy"
            ),
            409,
        )
    to_opt = await _get_option_or_404(
        session,
        option_id=redistribute_to_option_id,
        college_id=actor.college_id,
    )
    if to_opt.elective_group_id != eg.id or to_opt.id == opt.id:
        raise WorkflowError(
            "bad_target", "redistribute target must be a sibling option", 400
        )
    if to_opt.is_dissolved:
        raise WorkflowError("target_dissolved", "target option is dissolved", 400)

    # Displaced students = the LATEST `overflow` rows by (created_at, id).
    displaced_rows = cur_rows[-overflow:]
    displaced_list = [
        {
            "student_user_id": u.id,
            "name": u.name,
            "usn": u.usn,
            "registered_at": cr.created_at,
        }
        for cr, u in displaced_rows
    ]

    if redistribute_strategy == "manual":
        # Just set the cap and return who got displaced. No cascade run.
        opt.max_enrollment = max_enrollment
        await write_audit(
            session,
            action="elective_option.cap_set_manual",
            entity_type="elective_group_option",
            entity_id=opt.id,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={
                "max_enrollment": max_enrollment,
                "displaced_count": len(displaced_list),
            },
        )
        await session.commit()
        return {
            "new_max": max_enrollment,
            "displaced": displaced_list,
            "summary": None,
            "events": [],
        }

    # by_registration_order — perform cascade for each displaced student.
    if to_opt.max_enrollment is not None:
        target_cur = await _option_enrollment_count(session, option_id=to_opt.id)
        if target_cur + len(displaced_list) > to_opt.max_enrollment:
            raise WorkflowError(
                "target_full",
                "target option cannot absorb the overflow",
                409,
            )

    per_student_diag: list[dict[str, Any]] = []
    student_migrated_payloads: list[dict[str, Any]] = []
    affected_offering_ids: set[UUID] = set()
    student_ids: list[UUID] = []
    try:
        for cr, _u in displaced_rows:
            sid = cr.student_user_id
            student_ids.append(sid)
            diag = await _perform_student_migration(
                session,
                college_id=actor.college_id,
                setup=setup,
                student_id=sid,
                elective_group_id=eg.id,
                from_option=opt,
                to_option=to_opt,
                actor=actor,
                reason_code="capacity_redistribution",
                reason_text=(
                    f"capacity_redistribution to {to_opt.id} "
                    f"(new cap={max_enrollment})"
                ),
            )
            per_student_diag.append(diag)
            affected_offering_ids.add(UUID(diag["from_course_offering_id"]))
            affected_offering_ids.add(UUID(diag["to_course_offering_id"]))
            student_migrated_payloads.append(
                {
                    "student_id": diag["student_id"],
                    "from_course_offering_id": diag["from_course_offering_id"],
                    "to_course_offering_id": diag["to_course_offering_id"],
                    "elective_group_id": str(eg.id),
                    "reason": "capacity_redistribution",
                }
            )

        opt.max_enrollment = max_enrollment
        await write_audit(
            session,
            action="elective_option.cap_set_redistributed",
            entity_type="elective_group_option",
            entity_id=opt.id,
            actor_user_id=actor.id,
            college_id=actor.college_id,
            new_value={
                "max_enrollment": max_enrollment,
                "redistribute_to_option_id": str(to_opt.id),
                "student_count": len(per_student_diag),
            },
        )
        await session.commit()
    except WorkflowError:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise WorkflowError("cascade_failed", f"cap failed: {e}", 500) from e

    preserved = await _measure_preserved_history(
        session,
        student_ids=student_ids,
        offering_ids=list(affected_offering_ids),
    )
    summary = {
        "students_migrated": len(per_student_diag),
        "attendance_records_preserved": preserved["attendance_records_preserved"],
        "marks_preserved": preserved["marks_preserved"],
        "lab_batch_memberships_removed": sum(
            d["lab_batch_memberships_removed"] for d in per_student_diag
        ),
        "enrollment_rows_mutated": sum(
            d["enrollment_rows_mutated"] for d in per_student_diag
        ),
        "affected_offering_ids": [str(i) for i in affected_offering_ids],
        "per_student": per_student_diag,
    }
    return {
        "new_max": max_enrollment,
        "displaced": [],
        "summary": summary,
        "events": student_migrated_payloads,
    }


# ── Post-commit event emission helpers ──────────────────────────────────────
async def emit_dissolution_events(
    *,
    college_id: UUID,
    actor: User,
    dissolved_payload: dict[str, Any],
    student_migrated_payloads: list[dict[str, Any]],
) -> None:
    """Emits AFTER commit. Each helper publishes one event."""
    await publish_event(
        "elective.dissolved",
        dissolved_payload,
        college_id=college_id,
        actor_user_id=actor.id,
    )
    for p in student_migrated_payloads:
        await publish_event(
            "student.migrated",
            p,
            college_id=college_id,
            actor_user_id=actor.id,
        )


async def emit_student_migrated(
    *,
    college_id: UUID,
    actor: User,
    payload: dict[str, Any],
) -> None:
    await publish_event(
        "student.migrated",
        payload,
        college_id=college_id,
        actor_user_id=actor.id,
    )
