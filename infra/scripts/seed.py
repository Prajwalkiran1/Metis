"""Seed the BMSCE pilot tenant: one college, baseline roles + permissions,
three demo users (admin / teacher / student), and a small academic
structure (CSE dept, 2024 batch, A+B sections, 3 sem-3 courses, 2 rooms,
3 course offerings, 2 timetable slots, 1 student enrollment, 1 holiday).
All idempotent — re-running is a no-op once the data exists.

Run via `npm run seed`.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# When invoked as `python -m infra.scripts.seed` from the project root the
# `services/api` package isn't on sys.path. Add it.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.db import SessionLocal, engine, utcnow  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.modules.academic.models import (  # noqa: E402
    AcademicCalendarEntry,
    AcademicCalendarKind,
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    Room,
    RoomType,
    Section,
    TimetableSlot,
)
from app.modules.users.models import (  # noqa: E402
    College,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)


DEMO_PASSWORD = "MetisDemo!2026"

ROLES = [
    ("admin", "Full institutional admin"),
    ("teacher", "Teaching staff"),
    ("student", "Enrolled student"),
]

# Coarse-grained permission catalogue. Full RBAC matrix lands when modules need it.
PERMISSIONS = [
    ("user.read", "Read any user in the same college"),
    ("user.write", "Create/update users in the same college"),
    ("user.role_change", "Change another user's role"),
    ("attendance.mark", "Mark attendance for a session"),
    ("marks.write", "Enter marks for an assessment"),
    ("content.publish", "Publish course content"),
    ("comms.send", "Send broadcast communications"),
]

ROLE_PERMISSIONS = {
    "admin": [p[0] for p in PERMISSIONS],
    "teacher": ["user.read", "attendance.mark", "marks.write", "content.publish", "comms.send"],
    "student": ["user.read"],
}


DEMO_USERS = [
    ("admin@bmsce.ac.in", "BMSCE Admin", UserRole.admin),
    ("teacher@bmsce.ac.in", "BMSCE Teacher", UserRole.teacher),
    ("student@bmsce.ac.in", "BMSCE Student", UserRole.student),
]


async def _seed() -> None:
    async with SessionLocal() as session:
        # College
        existing = await session.execute(select(College).where(College.code == "BMSCE"))
        college = existing.scalar_one_or_none()
        created_college = False
        if college is None:
            college = College(
                id=uuid4(),
                name="B.M.S. College of Engineering",
                code="BMSCE",
                dpdp_data_fiduciary_name="B.M.S. Educational Trust",
                email_domain="bmsce.ac.in",
            )
            session.add(college)
            await session.flush()
            created_college = True
        elif college.email_domain != "bmsce.ac.in":
            # Backfill for older seeds.
            college.email_domain = "bmsce.ac.in"

        # Roles
        for name, desc in ROLES:
            r = await session.execute(select(Role).where(Role.name == name))
            if r.scalar_one_or_none() is None:
                session.add(Role(name=name, description=desc))

        # Permissions
        for name, desc in PERMISSIONS:
            p = await session.execute(select(Permission).where(Permission.name == name))
            if p.scalar_one_or_none() is None:
                session.add(Permission(name=name, description=desc))

        await session.flush()

        # Role -> Permission map
        for role_name, perm_names in ROLE_PERMISSIONS.items():
            role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
            for pname in perm_names:
                perm = (
                    await session.execute(select(Permission).where(Permission.name == pname))
                ).scalar_one()
                exists = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if exists.scalar_one_or_none() is None:
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

        # Demo users
        created_users: list[str] = []
        for email, name, role in DEMO_USERS:
            existing_user = await session.execute(
                select(User).where(
                    User.college_id == college.id,
                    User.email == email,
                    User.deleted_at.is_(None),
                )
            )
            if existing_user.scalar_one_or_none() is not None:
                continue
            session.add(
                User(
                    college_id=college.id,
                    email=email,
                    name=name,
                    role=role,
                    status=UserStatus.active,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
            )
            created_users.append(email)

        await session.commit()

        # Academic structure (M2 demo data).
        await _seed_academic(session, college_id=college.id)

    print("=" * 60)
    print("Metis seed complete.")
    print("=" * 60)
    if created_college:
        print("College: B.M.S. College of Engineering (BMSCE) — created")
    else:
        print("College: B.M.S. College of Engineering (BMSCE) — existed")
    if created_users:
        print("Created users:")
        for email in created_users:
            print(f"  {email}  password: {DEMO_PASSWORD}")
    else:
        print("Demo users already existed. Use password:", DEMO_PASSWORD)
    print("Academic seed: CSE dept, CSE 2024-28 batch (A+B), 3 sem-3 courses,")
    print("  2 rooms, 3 course offerings, 2 Wed back-to-back timetable slots,")
    print("  1 student enrolled in CSE-2024-A, 1 holiday on 2026-08-15.")
    print("=" * 60)


async def _seed_academic(session: AsyncSession, *, college_id) -> None:
    """Idempotent academic seed for the BMSCE pilot tenant.

    The shape mirrors what M3 attendance + M4 marks will need to demo: one
    department, one current batch with two sections, a handful of courses
    in the active semester, two rooms (one with GPS coords for face/QR),
    teacher↔course bindings, two back-to-back timetable slots (a deliberate
    test of the half-open overlap rule), one enrolled student, and a
    holiday inside the term so M3 materialisation has something to skip.
    """
    # Demo teacher + student come from the user seed above.
    teacher = (
        await session.execute(
            select(User).where(
                User.college_id == college_id,
                User.email == "teacher@bmsce.ac.in",
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    student = (
        await session.execute(
            select(User).where(
                User.college_id == college_id,
                User.email == "student@bmsce.ac.in",
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if teacher is None or student is None:
        # Seed ordering invariant violated — bail without partial writes.
        return

    # ── Department ──────────────────────────────────────────────────────────
    dept = (
        await session.execute(
            select(Department).where(
                Department.college_id == college_id, Department.code == "CSE"
            )
        )
    ).scalar_one_or_none()
    if dept is None:
        dept = Department(
            college_id=college_id,
            name="Computer Science & Engineering",
            code="CSE",
        )
        session.add(dept)
        await session.flush()

    # ── Batch ───────────────────────────────────────────────────────────────
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.college_id == college_id,
                Batch.department_id == dept.id,
                Batch.admission_year == 2024,
                Batch.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        batch = Batch(
            college_id=college_id,
            department_id=dept.id,
            name="CSE 2024-28",
            admission_year=2024,
            program_duration_years=4,
            current_semester=3,
        )
        session.add(batch)
        await session.flush()

    # ── Sections A + B ──────────────────────────────────────────────────────
    sections: dict[str, Section] = {}
    for name in ("A", "B"):
        s = (
            await session.execute(
                select(Section).where(
                    Section.batch_id == batch.id,
                    Section.name == name,
                    Section.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if s is None:
            s = Section(
                college_id=college_id,
                batch_id=batch.id,
                name=name,
                class_teacher_user_id=teacher.id,
            )
            session.add(s)
            await session.flush()
        sections[name] = s

    # ── Courses (sem 3) ─────────────────────────────────────────────────────
    course_specs = [
        ("CS301", "Data Structures", 4, CourseType.theory),
        ("CS302", "Database Management Systems", 4, CourseType.theory),
        ("CS303", "Discrete Mathematics", 3, CourseType.theory),
    ]
    courses: dict[str, Course] = {}
    for code, title, credits, ctype in course_specs:
        c = (
            await session.execute(
                select(Course).where(
                    Course.college_id == college_id,
                    Course.code == code,
                    Course.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if c is None:
            c = Course(
                college_id=college_id,
                department_id=dept.id,
                code=code,
                title=title,
                credits=credits,
                semester=3,
                course_type=ctype,
            )
            session.add(c)
            await session.flush()
        courses[code] = c

    # ── Rooms ───────────────────────────────────────────────────────────────
    # BMSCE Basavanagudi campus coords (~12.9430°N, 77.5630°E).
    room_specs = [
        {
            "code": "LH-201",
            "building": "Main Block",
            "floor": 2,
            "capacity": 60,
            "room_type": RoomType.lecture,
            "lat": Decimal("12.943000"),
            "lon": Decimal("77.563000"),
            "gps_radius_m": 100,
        },
        {
            "code": "Lab-A",
            "building": "CS Block",
            "floor": 1,
            "capacity": 30,
            "room_type": RoomType.lab,
            "lat": None,
            "lon": None,
            "gps_radius_m": 100,
        },
    ]
    rooms: dict[str, Room] = {}
    for spec in room_specs:
        r = (
            await session.execute(
                select(Room).where(
                    Room.college_id == college_id,
                    Room.code == spec["code"],
                    Room.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if r is None:
            r = Room(college_id=college_id, **spec)
            session.add(r)
            await session.flush()
        rooms[spec["code"]] = r

    # ── Course offerings ────────────────────────────────────────────────────
    term = "2026-ODD"
    offering_specs = [
        ("CS301", "A"),
        ("CS301", "B"),
        ("CS302", "A"),
    ]
    offerings: dict[tuple[str, str], CourseOffering] = {}
    for course_code, section_name in offering_specs:
        course = courses[course_code]
        section = sections[section_name]
        o = (
            await session.execute(
                select(CourseOffering).where(
                    CourseOffering.section_id == section.id,
                    CourseOffering.course_id == course.id,
                    CourseOffering.academic_term == term,
                    CourseOffering.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if o is None:
            o = CourseOffering(
                college_id=college_id,
                course_id=course.id,
                section_id=section.id,
                teacher_user_id=teacher.id,
                academic_term=term,
                semester=3,
                is_active=True,
            )
            session.add(o)
            await session.flush()
        offerings[(course_code, section_name)] = o

    # ── Timetable slots (back-to-back Wed for CS-A) ─────────────────────────
    slot_specs = [
        (("CS301", "A"), time(10, 0), time(11, 0)),
        (("CS302", "A"), time(11, 0), time(12, 0)),
    ]
    for key, start, end in slot_specs:
        offering = offerings[key]
        existing = (
            await session.execute(
                select(TimetableSlot).where(
                    TimetableSlot.course_offering_id == offering.id,
                    TimetableSlot.day_of_week == 2,  # Wednesday
                    TimetableSlot.start_time == start,
                    TimetableSlot.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                TimetableSlot(
                    college_id=college_id,
                    course_offering_id=offering.id,
                    room_id=rooms["LH-201"].id,
                    day_of_week=2,
                    start_time=start,
                    end_time=end,
                    effective_from=date(2026, 8, 5),
                    effective_until=date(2026, 12, 30),
                )
            )

    # ── Enroll the demo student in CSE-2024-A ───────────────────────────────
    enrolled = (
        await session.execute(
            select(Enrollment).where(
                Enrollment.student_user_id == student.id,
                Enrollment.section_id == sections["A"].id,
                Enrollment.academic_term == term,
                Enrollment.withdrawn_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if enrolled is None:
        session.add(
            Enrollment(
                college_id=college_id,
                student_user_id=student.id,
                section_id=sections["A"].id,
                academic_term=term,
                semester=3,
                enrolled_at=utcnow(),
            )
        )

    # ── One Wednesday holiday inside the term (M3 must skip it) ─────────────
    holiday_date = date(2026, 8, 15)  # Independence Day (a Saturday in 2026)
    existing_hol = (
        await session.execute(
            select(AcademicCalendarEntry).where(
                AcademicCalendarEntry.college_id == college_id,
                AcademicCalendarEntry.entry_date == holiday_date,
                AcademicCalendarEntry.kind == AcademicCalendarKind.holiday,
                AcademicCalendarEntry.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_hol is None:
        session.add(
            AcademicCalendarEntry(
                college_id=college_id,
                entry_date=holiday_date,
                kind=AcademicCalendarKind.holiday,
                title="Independence Day",
                cancels_classes=True,
            )
        )

    await session.commit()


async def main() -> None:
    try:
        await _seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
