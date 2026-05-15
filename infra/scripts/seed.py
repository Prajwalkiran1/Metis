"""Comprehensive demo seed for the BMS College of Engineering tenant.

What this seeds (in dependency order):
  • 1 college (BMSCE), full RBAC catalogue, 5 institutional Consents per user.
  • 7 departments, 4 admission batches (2023–2026), 2–3 sections per
    (dept, batch). CSE and ISE get 3 sections; others get 2.
  • ~40 students per section (~2,400 total) with valid BMSCE USNs.
  • 1 admin, 7 HODs (linked via users.hod_of_department_id), ~50 teachers,
    ~2,500 parents linked via guardian_links.
  • 4 academic terms: 2025-Odd (archived stub), 2025-Even (fully populated,
    with SEE released for 80% of courses + a few re-evaluations and a
    backlog), 2026-Odd (current — registration closed, mid-semester, CIE-1
    marks entered for ~80%, CIE-2 upcoming), 2026-Even (future skeleton).
  • Per (dept, current/past term): semester_setup (state=active / archived),
    course_offerings, integrated theory↔lab pairs, NPTEL slots, lab batches
    with members + incharges, assessment_schemes linked from the 3
    institutional templates, 2 dept templates, AAT-30% schemes with
    matching academic_overrides[assessment_scheme_unlock] rows.
  • Elective groups for CSE + CSE-DS (3–5 options each) with realistic
    enrollment distribution: one healthy option, one under-strength
    (HOD-dashboard callout), one dissolved with migrated students.
  • Current-term CIE schedule: CIE-1 already past + marks entered; CIE-2
    two weeks out + published; CIE-3 not yet scheduled.
  • Internal deadlines: institutional_hard (admin), department_soft (HOD).
  • Past-term hall tickets (HOD-approved) and grade cards (some with
    'I' pending grades for SEE-not-yet-released courses, one with a v2
    triggered by a late SEE release).
  • Past-term SEE results with a couple of re-evaluation rows (improved,
    held) and a makeup. Past-term failures generate backlog
    course_registrations on 2026-Odd.
  • Tasks: HOD-CSE assigns 9 tasks (invigilation / paper-setting / eval)
    in mixed states.
  • admin_notifications: publish events + condonations + dissolution.
  • Events: `publish()` is best-effort; called for the canonical surfaces
    (semester_setup.published, hall_ticket.generated, see.marks_released).

Login credentials — all use password MetisDemo!2026:
  admin@bmsce.ac.in                       Admin
  hod-cse@bmsce.ac.in                     HOD, CSE (focal dept)
  hod-{ise,ece,csd,aiml,me,eee}@bmsce.ac.in
  teacher-cse-1@bmsce.ac.in … teacher-cse-N@bmsce.ac.in
  student-1bm23cs001@bmsce.ac.in          Focal student, CSE 2023 batch sec A
  parent-1bm23cs001-1@bmsce.ac.in         Focal student's first parent
  (every student/parent follows the same pattern; USN is the discoverable key)

Note on PDFs: hall ticket + grade card pdf_url fields are seeded with the
'inline:{version_id}' convention that M10e uses. The download routes
re-render the PDF on demand from the snapshot JSON. R2 wiring stays
deferred.

Run:
    cd /path/to/Metis
    uv run --project services/api python infra/scripts/reset_demo.py
    uv run --project services/api python infra/scripts/seed.py
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from sqlalchemy import insert, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.db import SessionLocal, engine, utcnow  # noqa: E402
from app.core.event_bus import publish  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.modules.academic.models import (  # noqa: E402
    AcademicCalendarEntry,
    AcademicCalendarKind,
    AcademicTerm,
    AssessmentComponentKind,
    AssessmentScheme,
    AssessmentSchemeComponent,
    AssessmentSchemeTemplate,
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    Enrollment,
    EnrollmentState,
    Room,
    RoomType,
    Section,
    TermType,
    TimetableSlot,
)
from app.modules.attendance.models import (  # noqa: E402
    AttendanceRecord,
    AttendanceRecordState,
    ClassSession,
    ClassSessionSource,
    ClassSessionState,
)
from app.modules.marks.models import (  # noqa: E402
    Assessment,
    AssessmentState,
    AssessmentType,
    GuardianLink,
    GuardianRelationship,
    Mark,
    MarkState,
)
from app.modules.users.models import (  # noqa: E402
    College,
    Consent,
    ConsentPurpose,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.modules.workflow.models import (  # noqa: E402
    AcademicOverride,
    AdminNotification,
    CIESchedule,
    CourseRegistration,
    DeadlineKind,
    ElectiveGroup,
    ElectiveGroupOption,
    GradeCard,
    GradeCardVersion,
    HallTicket,
    HallTicketVersion,
    InternalDeadline,
    LabBatch,
    LabBatchAssignment,
    LabBatchMember,
    OverrideType,
    ReEvaluation,
    SEEResult,
    SEEResultKind,
    SemesterSetup,
    SemesterSetupState,
    Task,
    TaskAssignment,
    TaskStatus,
    TaskType,
)
from app.modules.workflow.service_m10e import (  # noqa: E402
    approve_hall_tickets,
    generate_grade_card,
    generate_hall_ticket_for_student,
    regenerate_grade_card,
)

from _demo_names import parent_name, student_name, teacher_name  # noqa: E402


# ── Determinism ─────────────────────────────────────────────────────────────
RNG = random.Random(2026_05_15)

DEMO_PASSWORD = "MetisDemo!2026"  # noqa: S105 — dev seed only
# Computed lazily inside main() — running argon2id ~5,000 times burns
# minutes; computing once and re-using the hash for all demo users is
# safe because the password is identical for every account.
DEMO_PASSWORD_HASH: str | None = None


def get_demo_password_hash() -> str:
    global DEMO_PASSWORD_HASH
    if DEMO_PASSWORD_HASH is None:
        DEMO_PASSWORD_HASH = hash_password(DEMO_PASSWORD)
    return DEMO_PASSWORD_HASH

NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.date()


# ── Institution shape ───────────────────────────────────────────────────────
# Session 2 narrowed the demo to a single deep dept (CSE) + three stub
# depts. Stubs exist so cross-department flows (HOD list, audit feed,
# etc.) have non-trivial fixtures, but they carry only 1 batch × 1 section
# × 5 students. The deep dept gets 4 batches × 2 sections × 30 students
# (focal student in CSE 2023 section A still has full attendance/marks/
# hall-ticket/grade-card history). Past walkthroughs ran 5,950 users +
# 52K attendance rows; this scope cuts both by ~10×.
#
# SCOPE controls all per-dept dimensions in one place so future tweaks
# don't have to chase magic numbers through the seed functions.
# (code, name, three-char USN dept tag, sections-per-batch, teachers, courses)
DEPT_SPECS: list[tuple[str, str, str, int, int]] = [
    ("CSE",     "Computer Science & Engineering",          "CS", 2, 8),
    ("ISE",     "Information Science & Engineering",       "IS", 1, 2),
    ("ECE",     "Electronics & Communication Engineering", "EC", 1, 2),
    ("CSE-DS",  "Computer Science & Engineering — Data Science", "CD", 1, 2),
]

# Per-dept scope mode. "deep" → full workflow data; "stub" → minimal
# rows for IA cross-references.
SCOPE: dict[str, str] = {
    "CSE": "deep",
    "ISE": "stub",
    "ECE": "stub",
    "CSE-DS": "stub",
}


def is_deep(dept_code: str) -> bool:
    return SCOPE.get(dept_code) == "deep"


def students_per_section(dept_code: str) -> int:
    return 30 if is_deep(dept_code) else 5


def batch_years_for(dept_code: str) -> tuple[int, ...]:
    """Deep depts span all 4 admission batches; stubs carry only the
    focal year so the walkthrough has a face for each dept without
    inflating row counts."""
    return BATCH_YEARS if is_deep(dept_code) else (FOCAL_BATCH_YEAR,)

# Course catalogue per department. Keep it real-sounding; mix types so the
# seed exercises every assessment_scheme template + lab-batch flow.
# (code_suffix, title, semester, credits, course_type)
def _theory(code: str, title: str, sem: int, credits: int) -> tuple[str, str, int, int, str]:
    return code, title, sem, credits, "theory"


def _lab(code: str, title: str, sem: int, credits: int) -> tuple[str, str, int, int, str]:
    return code, title, sem, credits, "lab"


def _integ(code: str, title: str, sem: int, credits: int) -> tuple[str, str, int, int, str]:
    return code, title, sem, credits, "integrated"


def _nptel(code: str, title: str, sem: int, credits: int) -> tuple[str, str, int, int, str]:
    return code, title, sem, credits, "nptel"


COURSE_CATALOGUE: dict[str, list[tuple[str, str, int, int, str]]] = {
    "CSE": [
        _theory("101", "Engineering Mathematics-I", 1, 4),
        _theory("102", "Programming in C", 1, 3),
        _integ("103", "Engineering Physics", 1, 4),
        _theory("201", "Engineering Mathematics-II", 2, 4),
        _theory("202", "Data Structures", 3, 4),
        _integ("203", "Database Management Systems", 4, 4),
        _theory("301", "Operating Systems", 5, 4),
        _integ("302", "Computer Networks", 5, 4),
        _theory("303", "Software Engineering", 5, 3),
        _nptel("304", "NPTEL — Elective Slot", 5, 3),
        _theory("401", "Compiler Design", 6, 4),
        _integ("402", "Machine Learning", 6, 4),
        _theory("403", "Cloud Computing", 6, 3),
        _theory("501", "Big Data Analytics", 7, 3),
        _theory("502", "Deep Learning", 7, 4),
        _integ("503", "Cyber Security", 7, 4),
        _theory("504", "Cryptography & Network Security", 7, 3),
        _theory("505", "Distributed Systems", 7, 3),
        _nptel("506", "NPTEL — Domain Elective", 7, 3),
        _theory("507", "Blockchain Technology", 7, 3),
        _theory("601", "Project Phase-I", 8, 6),
        _theory("602", "Professional Elective-IV", 8, 3),
    ],
    "ISE": [
        _theory("101", "Engineering Mathematics-I", 1, 4),
        _theory("102", "Problem Solving with C", 1, 3),
        _integ("103", "Engineering Physics", 1, 4),
        _theory("201", "Engineering Mathematics-II", 2, 4),
        _theory("202", "Object Oriented Programming with Java", 3, 4),
        _integ("203", "DBMS for IS", 4, 4),
        _theory("301", "Web Technologies", 5, 4),
        _integ("302", "Mobile Application Development", 5, 4),
        _theory("303", "Information Retrieval", 5, 3),
        _nptel("304", "NPTEL — Elective Slot", 5, 3),
        _theory("401", "Data Mining", 6, 4),
        _integ("402", "AI for Information Systems", 6, 4),
        _theory("403", "ERP Systems", 6, 3),
        _theory("501", "Cloud Architecture", 7, 3),
        _theory("502", "DevOps", 7, 4),
        _integ("503", "Information Security", 7, 4),
        _theory("504", "Software Project Management", 7, 3),
        _nptel("505", "NPTEL — Domain Elective", 7, 3),
        _theory("506", "Internet of Things", 7, 3),
        _theory("507", "Recommender Systems", 7, 3),
        _theory("601", "Project Phase-I", 8, 6),
    ],
    "ECE": [
        _theory("101", "Engineering Mathematics-I", 1, 4),
        _integ("102", "Basic Electronics", 1, 4),
        _theory("201", "Engineering Mathematics-II", 2, 4),
        _integ("202", "Network Analysis", 3, 4),
        _theory("203", "Signals & Systems", 3, 3),
        _integ("301", "Analog Communication", 5, 4),
        _theory("302", "Digital Signal Processing", 5, 4),
        _theory("303", "Microcontrollers", 5, 3),
        _nptel("304", "NPTEL — Elective", 5, 3),
        _theory("401", "VLSI Design", 6, 4),
        _integ("402", "Embedded Systems", 6, 4),
        _theory("501", "Antenna Theory", 7, 3),
        _theory("502", "Wireless Communication", 7, 4),
        _integ("503", "Optical Communication", 7, 4),
        _nptel("504", "NPTEL — Domain", 7, 3),
        _theory("505", "Radar Systems", 7, 3),
        _theory("601", "Project Phase-I", 8, 6),
    ],
    "CSE-DS": [
        _theory("101", "Engineering Mathematics-I", 1, 4),
        _theory("102", "Python for Data Science", 1, 3),
        _integ("103", "Engineering Physics", 1, 4),
        _theory("201", "Engineering Mathematics-II", 2, 4),
        _theory("202", "Statistics for Data Science", 3, 4),
        _integ("203", "Database Systems", 4, 4),
        _theory("301", "Machine Learning Foundations", 5, 4),
        _integ("302", "Big Data Engineering", 5, 4),
        _theory("303", "Data Visualization", 5, 3),
        _nptel("304", "NPTEL — Elective", 5, 3),
        _integ("401", "Deep Learning", 6, 4),
        _theory("402", "Natural Language Processing", 6, 3),
        _theory("501", "Computer Vision", 7, 3),
        _theory("502", "Reinforcement Learning", 7, 4),
        _integ("503", "MLOps", 7, 4),
        _nptel("504", "NPTEL — Domain", 7, 3),
        _theory("505", "Time Series Analysis", 7, 3),
        _theory("601", "Project Phase-I", 8, 6),
    ],
}

# Admission batches. 2026-Odd is current; the focal cohort is 2023.
BATCH_YEARS = (2023, 2024, 2025, 2026)
BATCH_SEM_AT_CURRENT_TERM = {2023: 7, 2024: 5, 2025: 3, 2026: 1}
BATCH_SEM_AT_PAST_TERM = {2023: 6, 2024: 4, 2025: 2}  # 2026 batch wasn't yet enrolled

# Terms — codes follow BMSCE convention (year-Odd | year-Even).
TERMS = {
    "2025-ODD":  ("2025-ODD",  TermType.regular, date(2025, 8, 1),  date(2025, 12, 20)),
    "2025-EVEN": ("2025-EVEN", TermType.regular, date(2026, 1, 5),  date(2026, 5, 5)),
    "2026-ODD":  ("2026-ODD",  TermType.regular, date(2026, 7, 27), date(2026, 12, 12)),
    "2026-EVEN": ("2026-EVEN", TermType.regular, date(2027, 1, 4),  date(2027, 5, 4)),
}
CURRENT_TERM_CODE = "2026-ODD"
PAST_TERM_CODE = "2025-EVEN"
ARCHIVED_TERM_CODE = "2025-ODD"
FUTURE_TERM_CODE = "2026-EVEN"

# Pull the focal batch year (the one with the deepest data + walkthrough creds)
FOCAL_BATCH_YEAR = 2023
FOCAL_DEPT_CODE = "CSE"

# Per-section student counts are now scope-dependent — see SCOPE +
# students_per_section() above. The old `STUDENTS_PER_SECTION = 40`
# global is gone.

# Coarse-grained permission catalogue — matches the v1 seed so existing
# RBAC code keeps working.
ROLES = (
    ("admin", "Full institutional admin"),
    ("hod",   "Head of department"),
    ("teacher", "Teaching staff"),
    ("student", "Enrolled student"),
    ("parent",  "Linked parent / guardian"),
)
PERMISSIONS = (
    ("user.read", "Read any user in the same college"),
    ("user.write", "Create/update users in the same college"),
    ("user.role_change", "Change another user's role"),
    ("attendance.mark", "Mark attendance for a session"),
    ("marks.write", "Enter marks for an assessment"),
    ("content.publish", "Publish course content"),
    ("comms.send", "Send broadcast communications"),
    ("workflow.publish", "Publish a semester structure"),
)
ROLE_PERMISSIONS = {
    "admin":   [p[0] for p in PERMISSIONS],
    "hod":     ["user.read", "user.write", "marks.write", "content.publish", "comms.send", "workflow.publish"],
    "teacher": ["user.read", "attendance.mark", "marks.write", "content.publish", "comms.send"],
    "student": ["user.read"],
    "parent":  ["user.read"],
}


# ── USN + email helpers ─────────────────────────────────────────────────────
def make_usn(year_2digit: int, dept_usn_tag: str, roll: int) -> str:
    return f"1BM{year_2digit:02d}{dept_usn_tag}{roll:03d}"


def student_email(usn: str) -> str:
    return f"student-{usn.lower()}@bmsce.ac.in"


def parent_email(usn: str, n: int) -> str:
    return f"parent-{usn.lower()}-{n}@bmsce.ac.in"


def teacher_email(dept_code: str, n: int) -> str:
    return f"teacher-{dept_code.lower()}-{n}@bmsce.ac.in"


def hod_email(dept_code: str) -> str:
    return f"hod-{dept_code.lower()}@bmsce.ac.in"


# ── Pretty-printers (used at end-of-seed) ───────────────────────────────────
def banner(text_: str) -> None:
    print("=" * 70)
    print(text_)
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# 1. College + RBAC + admin
# ─────────────────────────────────────────────────────────────────────────────
async def seed_college_and_rbac(session: AsyncSession) -> College:
    college = College(
        name="B.M.S. College of Engineering",
        code="BMSCE",
        dpdp_data_fiduciary_name="B.M.S. Educational Trust",
        email_domain="bmsce.ac.in",
    )
    session.add(college)
    await session.flush()

    role_objs: dict[str, Role] = {}
    for name, desc in ROLES:
        r = Role(name=name, description=desc)
        session.add(r)
        role_objs[name] = r
    perm_objs: dict[str, Permission] = {}
    for name, desc in PERMISSIONS:
        p = Permission(name=name, description=desc)
        session.add(p)
        perm_objs[name] = p
    await session.flush()
    for rname, pnames in ROLE_PERMISSIONS.items():
        for pname in pnames:
            session.add(
                RolePermission(role_id=role_objs[rname].id, permission_id=perm_objs[pname].id)
            )
    await session.flush()
    return college


async def add_consents(session: AsyncSession, *, user_id: uuid.UUID, with_face: bool) -> None:
    """Privacy + (optional) face_enrollment consent — one row per purpose."""
    session.add(
        Consent(
            user_id=user_id,
            purpose=ConsentPurpose.face_attendance,
            consent_text_version="v1",
            granted_at=NOW,
        )
    )
    if with_face:
        session.add(
            Consent(
                user_id=user_id,
                purpose=ConsentPurpose.face_enrollment,
                consent_text_version="v1",
                granted_at=NOW,
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Academic terms (4 — past archived, past full, current, future)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_academic_terms(
    session: AsyncSession, college_id: uuid.UUID
) -> dict[str, AcademicTerm]:
    out: dict[str, AcademicTerm] = {}
    for code, (term_code, term_type, starts, ends) in TERMS.items():
        # Registration window depends on the term: past terms are closed;
        # the current term is mid-semester so the window has closed; the
        # future term hasn't opened yet.
        reg_opens, reg_closes = None, None
        if code == CURRENT_TERM_CODE:
            reg_opens = datetime.combine(starts - timedelta(days=14), time(9, 0)).replace(
                tzinfo=timezone.utc
            )
            reg_closes = datetime.combine(starts, time(23, 59)).replace(tzinfo=timezone.utc)
        elif code == FUTURE_TERM_CODE:
            reg_opens = datetime.combine(starts - timedelta(days=21), time(9, 0)).replace(
                tzinfo=timezone.utc
            )
            reg_closes = datetime.combine(starts, time(23, 59)).replace(tzinfo=timezone.utc)
        t = AcademicTerm(
            college_id=college_id,
            code=term_code,
            term_type=term_type,
            starts_on=starts,
            ends_on=ends,
            registration_opens_at=reg_opens,
            registration_closes_at=reg_closes,
        )
        session.add(t)
        out[code] = t
    await session.flush()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Departments + 4. Courses + 5. Batches/Sections + 6. Rooms
# ─────────────────────────────────────────────────────────────────────────────
async def seed_departments(
    session: AsyncSession, college_id: uuid.UUID
) -> dict[str, Department]:
    out: dict[str, Department] = {}
    for code, name, _usn_tag, _sections, _teachers in DEPT_SPECS:
        d = Department(college_id=college_id, name=name, code=code)
        session.add(d)
        out[code] = d
    await session.flush()
    return out


async def seed_rooms(session: AsyncSession, college_id: uuid.UUID) -> dict[str, Room]:
    """Lecture halls + labs across the campus. GPS coords roughly point at
    the BMSCE Basavanagudi campus (~12.9430°N, 77.5630°E)."""
    rooms: dict[str, Room] = {}
    base_lat, base_lon = Decimal("12.943000"), Decimal("77.563000")
    # Block A: lecture halls
    for n in range(1, 7):
        r = Room(
            college_id=college_id,
            code=f"LH-{n:02d}",
            building="Main Block",
            floor=(n - 1) // 3 + 1,
            capacity=60,
            room_type=RoomType.lecture,
            lat=base_lat,
            lon=base_lon,
            gps_radius_m=100,
        )
        session.add(r)
        rooms[r.code] = r
    # Block B: bigger lecture halls for cross-dept events / SEE exams
    for n in range(1, 4):
        r = Room(
            college_id=college_id,
            code=f"HALL-{n}",
            building="Examination Block",
            floor=1,
            capacity=120,
            room_type=RoomType.lecture,
            lat=base_lat,
            lon=base_lon,
            gps_radius_m=150,
        )
        session.add(r)
        rooms[r.code] = r
    # Per-dept labs
    for dept_code, _name, _tag, _sec, _t in DEPT_SPECS:
        for n in range(1, 3):
            r = Room(
                college_id=college_id,
                code=f"LAB-{dept_code}-{n}",
                building=f"{dept_code} Block",
                floor=n,
                capacity=30,
                room_type=RoomType.lab,
                lat=base_lat,
                lon=base_lon,
                gps_radius_m=80,
            )
            session.add(r)
            rooms[r.code] = r
    await session.flush()
    return rooms


async def seed_courses(
    session: AsyncSession, college_id: uuid.UUID, depts: dict[str, Department]
) -> dict[tuple[str, str], Course]:
    out: dict[tuple[str, str], Course] = {}
    for dept_code, courses in COURSE_CATALOGUE.items():
        dept = depts[dept_code]
        usn_tag = dict((d[0], d[2]) for d in DEPT_SPECS)[dept_code]
        for suffix, title, sem, credits, ctype in courses:
            code = f"{usn_tag}{suffix}"
            c = Course(
                college_id=college_id,
                department_id=dept.id,
                code=code,
                title=title,
                credits=credits,
                semester=sem,
                course_type=CourseType(ctype),
            )
            session.add(c)
            out[(dept_code, suffix)] = c
    await session.flush()
    return out


async def seed_batches_sections(
    session: AsyncSession, college_id: uuid.UUID, depts: dict[str, Department]
) -> tuple[dict[tuple[str, int], Batch], dict[tuple[str, int, str], Section]]:
    """4 admission batches × 7 depts × 2-3 sections each.

    Section A always exists. Section B for every dept. Section C only for
    CSE + ISE (the two large depts). Class-teacher remains NULL — set
    later when a real teacher exists.
    """
    batches: dict[tuple[str, int], Batch] = {}
    sections: dict[tuple[str, int, str], Section] = {}
    for dept_code, _name, _tag, sec_count, _t in DEPT_SPECS:
        years = batch_years_for(dept_code)
        for yr in years:
            current_sem = BATCH_SEM_AT_CURRENT_TERM[yr]
            b = Batch(
                college_id=college_id,
                department_id=depts[dept_code].id,
                name=f"{dept_code} {yr}-{yr + 4}",
                admission_year=yr,
                program_duration_years=4,
                current_semester=current_sem,
            )
            session.add(b)
            batches[(dept_code, yr)] = b
        await session.flush()
        for yr in years:
            section_names = ("A", "B", "C")[:sec_count]
            for sn in section_names:
                s = Section(
                    college_id=college_id,
                    batch_id=batches[(dept_code, yr)].id,
                    name=sn,
                )
                session.add(s)
                sections[(dept_code, yr, sn)] = s
        await session.flush()
    return batches, sections


# ─────────────────────────────────────────────────────────────────────────────
# 7. Users — admin, HODs, teachers, students, parents
# ─────────────────────────────────────────────────────────────────────────────
async def seed_admin(session: AsyncSession, college_id: uuid.UUID) -> User:
    admin = User(
        college_id=college_id,
        email="admin@bmsce.ac.in",
        name="BMSCE Admin",
        role=UserRole.admin,
        status=UserStatus.active,
        password_hash=get_demo_password_hash(),
    )
    session.add(admin)
    await session.flush()
    await add_consents(session, user_id=admin.id, with_face=False)
    return admin


async def seed_hods(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    depts: dict[str, Department],
) -> dict[str, User]:
    out: dict[str, User] = {}
    for dept_code, _name, _tag, _sec, _t in DEPT_SPECS:
        # CSE is the focal department. Use the legacy `hod@bmsce.ac.in`
        # address so the existing pytest suite (test_m10a/d/e and
        # test_m2_rework) keeps passing without per-test fixtures.
        email = "hod@bmsce.ac.in" if dept_code == FOCAL_DEPT_CODE else hod_email(dept_code)
        h = User(
            college_id=college_id,
            email=email,
            name=f"{teacher_name(RNG)} (HOD {dept_code})",
            role=UserRole.hod,
            status=UserStatus.active,
            password_hash=get_demo_password_hash(),
            hod_of_department_id=depts[dept_code].id,
        )
        session.add(h)
        out[dept_code] = h
    await session.flush()
    for u in out.values():
        await add_consents(session, user_id=u.id, with_face=False)
    return out


async def seed_legacy_test_users(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    teachers: dict[str, list[User]],
    sections: dict[tuple[str, int, str], Section],
    current_term: AcademicTerm,
) -> dict[str, User]:
    """Demo / pytest entry points that pre-date the demo seed rewrite.

    The test suite logs in as `teacher@bmsce.ac.in` and `student@bmsce.ac.in`
    in several places (test_marks, test_academic, test_m2_rework). They
    are not part of the bulk demographic data; they exist as stable
    fixtures so tests can pick a predictable user and walk through CRUD
    flows. The student gets a real enrollment so test_marks can wire it
    into a per-offering check without first creating a section row.
    """
    legacy: dict[str, User] = {}
    teacher = User(
        college_id=college_id,
        email="teacher@bmsce.ac.in",
        name="Legacy Demo Teacher",
        role=UserRole.teacher,
        status=UserStatus.active,
        password_hash=get_demo_password_hash(),
    )
    session.add(teacher)
    student = User(
        college_id=college_id,
        email="student@bmsce.ac.in",
        name="Legacy Demo Student",
        role=UserRole.student,
        status=UserStatus.active,
        password_hash=get_demo_password_hash(),
        usn="1BM24CS999",
    )
    session.add(student)
    await session.flush()
    await add_consents(session, user_id=teacher.id, with_face=False)
    await add_consents(session, user_id=student.id, with_face=True)
    # Enroll the legacy student in CSE 2024-A current-term so /admin/users
    # filters work and test_marks can set the student up against a real
    # offering it creates.
    section = sections.get(("CSE", 2024, "A"))
    if section is not None:
        session.add(
            Enrollment(
                college_id=college_id,
                student_user_id=student.id,
                section_id=section.id,
                academic_term=current_term.code,
                semester=BATCH_SEM_AT_CURRENT_TERM[2024],
                enrolled_at=NOW,
                enrollment_state=EnrollmentState.active,
                academic_term_id=current_term.id,
            )
        )
    legacy["teacher"] = teacher
    legacy["student"] = student
    await session.flush()
    return legacy


async def seed_teachers(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
) -> dict[str, list[User]]:
    out: dict[str, list[User]] = {}
    for dept_code, _name, _tag, _sec, n_teachers in DEPT_SPECS:
        out[dept_code] = []
        for n in range(1, n_teachers + 1):
            t = User(
                college_id=college_id,
                email=teacher_email(dept_code, n),
                name=teacher_name(RNG),
                role=UserRole.teacher,
                status=UserStatus.active,
                password_hash=get_demo_password_hash(),
            )
            session.add(t)
            out[dept_code].append(t)
    await session.flush()
    for ts in out.values():
        for t in ts:
            await add_consents(session, user_id=t.id, with_face=False)
    return out


async def seed_students_and_parents(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    sections: dict[tuple[str, int, str], Section],
) -> tuple[
    dict[str, User],          # usn → student
    dict[str, list[User]],    # usn → list of parents
    dict[tuple[str, int, str], list[User]],  # (dept, year, sec) → ordered student list
]:
    """Generate students per section deterministically. USN roll restarts
    at 001 for each (year, dept_tag) pair. Parents follow each student so
    they end up adjacent to their child in audit logs (helpful for demos).
    """
    students_by_usn: dict[str, User] = {}
    parents_by_usn: dict[str, list[User]] = {}
    students_by_section: dict[tuple[str, int, str], list[User]] = defaultdict(list)

    for dept_code, _name, usn_tag, _sec, _t in DEPT_SPECS:
        per_section = students_per_section(dept_code)
        for yr in batch_years_for(dept_code):
            section_count = dict((d[0], d[3]) for d in DEPT_SPECS)[dept_code]
            section_names = ("A", "B", "C")[:section_count]
            roll = 0
            for sn in section_names:
                for _ in range(per_section):
                    roll += 1
                    usn = make_usn(yr % 100, usn_tag, roll)
                    full_name, gender = student_name(RNG)
                    surname = full_name.split()[-1]
                    student = User(
                        college_id=college_id,
                        email=student_email(usn),
                        name=full_name,
                        role=UserRole.student,
                        status=UserStatus.active,
                        password_hash=get_demo_password_hash(),
                        usn=usn,
                    )
                    session.add(student)
                    students_by_usn[usn] = student
                    students_by_section[(dept_code, yr, sn)].append(student)

                    # 1 parent for ~85% of students, 2 for the rest. Mother
                    # always present; second slot is a father guardian.
                    parents = []
                    p1_is_mother = RNG.random() < 0.55
                    p1 = User(
                        college_id=college_id,
                        email=parent_email(usn, 1),
                        name=parent_name(RNG, surname, mother=p1_is_mother),
                        role=UserRole.parent,
                        status=UserStatus.active,
                        password_hash=get_demo_password_hash(),
                    )
                    session.add(p1)
                    parents.append(p1)
                    if RNG.random() < 0.30:
                        p2 = User(
                            college_id=college_id,
                            email=parent_email(usn, 2),
                            name=parent_name(RNG, surname, mother=not p1_is_mother),
                            role=UserRole.parent,
                            status=UserStatus.active,
                            password_hash=get_demo_password_hash(),
                        )
                        session.add(p2)
                        parents.append(p2)
                    parents_by_usn[usn] = parents
        # Flush per-department to keep the in-memory identity map manageable
        await session.flush()

    # Consents + guardian_links — bulk where we can. Run after all users
    # exist so IDs are stable.
    consent_rows: list[dict[str, Any]] = []
    gl_rows: list[dict[str, Any]] = []
    for usn, student in students_by_usn.items():
        # Face attendance + face enrollment for students.
        consent_rows.append(
            dict(
                id=uuid.uuid4(),
                user_id=student.id,
                purpose=ConsentPurpose.face_attendance,
                consent_text_version="v1",
                granted_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        consent_rows.append(
            dict(
                id=uuid.uuid4(),
                user_id=student.id,
                purpose=ConsentPurpose.face_enrollment,
                consent_text_version="v1",
                granted_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for idx, parent in enumerate(parents_by_usn[usn]):
            consent_rows.append(
                dict(
                    id=uuid.uuid4(),
                    user_id=parent.id,
                    purpose=ConsentPurpose.face_attendance,
                    consent_text_version="v1",
                    granted_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            rel = GuardianRelationship.mother if idx == 0 else GuardianRelationship.father
            gl_rows.append(
                dict(
                    id=uuid.uuid4(),
                    college_id=college_id,
                    parent_user_id=parent.id,
                    student_user_id=student.id,
                    relationship=rel,
                    verified_at=NOW,
                    created_at=NOW,
                    created_via="csv_bulk",
                )
            )
    # Bulk-insert in 1000-row chunks. SQLAlchemy `insert(Model)` works with
    # native enums when the value is the enum member itself.
    if consent_rows:
        for i in range(0, len(consent_rows), 1000):
            await session.execute(insert(Consent), consent_rows[i : i + 1000])
    if gl_rows:
        for i in range(0, len(gl_rows), 1000):
            await session.execute(insert(GuardianLink), gl_rows[i : i + 1000])
    await session.flush()
    return students_by_usn, parents_by_usn, students_by_section


# ─────────────────────────────────────────────────────────────────────────────
# 8. Assessment scheme templates (3 institutional + 2 dept)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_scheme_templates(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    depts: dict[str, Department],
) -> dict[str, AssessmentSchemeTemplate]:
    """3 institutional templates (theory/integrated/nptel) + 2 dept ones.

    Validation rules mirror BMSCE defaults so the M10c picker treats them
    as the source of truth.
    """
    templates: dict[str, AssessmentSchemeTemplate] = {}

    inst = [
        (
            "Theory Standard",
            "BMSCE default for theory courses",
            "theory",
            {
                "cie_count": 3, "cie_best_of": 2, "cie_equal_weights": True,
                "aat_max_percent": 40, "see_rescale_to": 50,
                "internal_threshold_main_percent": 40,
                "internal_threshold_makeup_percent": 60,
            },
            [
                {"kind": "cie", "label": "CIE-1", "max_marks": 40, "weight_percent": 20, "ordinal": 1, "metadata": {"best_of_group": "cie"}},
                {"kind": "cie", "label": "CIE-2", "max_marks": 40, "weight_percent": 20, "ordinal": 2, "metadata": {"best_of_group": "cie"}},
                {"kind": "cie", "label": "CIE-3", "max_marks": 40, "weight_percent": 20, "ordinal": 3, "metadata": {"best_of_group": "cie"}},
                {"kind": "aat", "label": "AAT", "max_marks": 20, "weight_percent": 10, "ordinal": 4},
                {"kind": "see", "label": "SEE", "max_marks": 100, "weight_percent": 50, "ordinal": 5},
            ],
        ),
        (
            "Integrated Standard",
            "BMSCE default for integrated (theory + lab) courses",
            "integrated",
            {
                "cie_count": 3, "cie_best_of": 2, "cie_equal_weights": True,
                "lab_required": True, "see_rescale_to": 50,
                "internal_threshold_main_percent": 40,
                "internal_threshold_makeup_percent": 60,
            },
            [
                {"kind": "cie", "label": "CIE-1", "max_marks": 20, "weight_percent": 10, "ordinal": 1, "metadata": {"best_of_group": "cie"}},
                {"kind": "cie", "label": "CIE-2", "max_marks": 20, "weight_percent": 10, "ordinal": 2, "metadata": {"best_of_group": "cie"}},
                {"kind": "cie", "label": "CIE-3", "max_marks": 20, "weight_percent": 10, "ordinal": 3, "metadata": {"best_of_group": "cie"}},
                {"kind": "lab", "label": "Lab", "max_marks": 25, "weight_percent": 25, "ordinal": 4},
                {"kind": "aat", "label": "AAT", "max_marks": 5, "weight_percent": 5, "ordinal": 5},
                {"kind": "see", "label": "SEE", "max_marks": 100, "weight_percent": 50, "ordinal": 6},
            ],
        ),
        (
            "NPTEL Standard",
            "BMSCE default for NPTEL / MOOC courses",
            "nptel",
            {"no_attendance": True, "no_cie": True, "carry_over_allowed": True},
            [
                {"kind": "nptel_assignment", "label": "NPTEL Assignments", "max_marks": 40, "weight_percent": 40, "ordinal": 1},
                {"kind": "nptel_final", "label": "NPTEL Final Exam", "max_marks": 60, "weight_percent": 60, "ordinal": 2},
            ],
        ),
    ]
    for name, desc, ctype, vrules, comps in inst:
        t = AssessmentSchemeTemplate(
            college_id=college_id,
            owner_department_id=None,
            name=name,
            description=desc,
            applies_to_course_type=ctype,
            validation_rules=vrules,
            default_components=comps,
            is_active=True,
        )
        session.add(t)
        templates[name] = t

    # Two department templates so /hod/scheme-templates has interesting
    # content: CSE has a CIE-heavier variant; ECE has an integrated lab
    # template biased toward practicals.
    cse_template = AssessmentSchemeTemplate(
        college_id=college_id,
        owner_department_id=depts["CSE"].id,
        name="CSE Theory — Programming-heavy",
        description="More AAT weight for project-style courses (e.g., Compiler Design)",
        applies_to_course_type="theory",
        validation_rules={
            "cie_count": 3, "cie_best_of": 2, "cie_equal_weights": True,
            "aat_max_percent": 40, "see_rescale_to": 50,
        },
        default_components=[
            {"kind": "cie", "label": "CIE-1", "max_marks": 40, "weight_percent": 15, "ordinal": 1, "metadata": {"best_of_group": "cie"}},
            {"kind": "cie", "label": "CIE-2", "max_marks": 40, "weight_percent": 15, "ordinal": 2, "metadata": {"best_of_group": "cie"}},
            {"kind": "cie", "label": "CIE-3", "max_marks": 40, "weight_percent": 15, "ordinal": 3, "metadata": {"best_of_group": "cie"}},
            {"kind": "aat", "label": "AAT (Project)", "max_marks": 30, "weight_percent": 15, "ordinal": 4},
            {"kind": "see", "label": "SEE", "max_marks": 100, "weight_percent": 50, "ordinal": 5},
        ],
        is_active=True,
    )
    ece_template = AssessmentSchemeTemplate(
        college_id=college_id,
        owner_department_id=depts["ECE"].id,
        name="ECE Integrated — Lab-heavy",
        description="Higher lab weight for hardware-oriented integrated courses",
        applies_to_course_type="integrated",
        validation_rules={
            "cie_count": 3, "cie_best_of": 2, "cie_equal_weights": True,
            "lab_required": True, "see_rescale_to": 50,
        },
        default_components=[
            {"kind": "cie", "label": "CIE-1", "max_marks": 20, "weight_percent": 7, "ordinal": 1, "metadata": {"best_of_group": "cie"}},
            {"kind": "cie", "label": "CIE-2", "max_marks": 20, "weight_percent": 7, "ordinal": 2, "metadata": {"best_of_group": "cie"}},
            {"kind": "cie", "label": "CIE-3", "max_marks": 20, "weight_percent": 7, "ordinal": 3, "metadata": {"best_of_group": "cie"}},
            {"kind": "lab", "label": "Lab", "max_marks": 30, "weight_percent": 30, "ordinal": 4},
            {"kind": "aat", "label": "AAT", "max_marks": 5, "weight_percent": 4, "ordinal": 5},
            {"kind": "see", "label": "SEE", "max_marks": 100, "weight_percent": 45, "ordinal": 6},
        ],
        is_active=True,
    )
    session.add(cse_template)
    session.add(ece_template)
    templates["CSE Theory — Programming-heavy"] = cse_template
    templates["ECE Integrated — Lab-heavy"] = ece_template
    await session.flush()
    return templates


# ─────────────────────────────────────────────────────────────────────────────
# 9. Semester setups + course offerings + lab batches + schemes
#    (For each (dept × term in {past, current}).)
# ─────────────────────────────────────────────────────────────────────────────
def _courses_for_semester(dept_code: str, semester: int) -> list[tuple[str, str, int, int, str]]:
    """Pick 5–7 courses for a department's given semester. The catalogue is
    already organised by semester; if too few rows exist we pad from
    semester±1 to keep the setup non-trivial.
    """
    pool = [c for c in COURSE_CATALOGUE[dept_code] if c[2] == semester]
    if len(pool) < 5:
        adj = [c for c in COURSE_CATALOGUE[dept_code] if c[2] in (semester - 1, semester + 1)]
        pool.extend(adj)
    # Order: theory then integrated then nptel for deterministic-looking output
    pool.sort(key=lambda c: ("theory_integrated_nptel_lab".find(c[4]), c[0]))
    return pool[:7]


async def _make_scheme_from_template(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    course_type: str,
    templates: dict[str, AssessmentSchemeTemplate],
    offering_id: uuid.UUID,
    configured_by: uuid.UUID,
    aat_override_band: bool = False,
    actor_for_override: uuid.UUID | None = None,
) -> AssessmentScheme:
    """Pick the institutional template that matches course_type, instantiate
    an AssessmentScheme + components row-set linked to the offering.

    `aat_override_band=True` boosts the AAT weight into the 20-40% band
    and records an academic_override[assessment_scheme_unlock] row — the
    HOD-authorised path from CLAUDE.md.
    """
    template_name = {
        "theory": "Theory Standard",
        "integrated": "Integrated Standard",
        "nptel": "NPTEL Standard",
        "lab": "Integrated Standard",  # lab side inherits parent's scheme in reality
    }[course_type]
    template = templates[template_name]

    scheme = AssessmentScheme(
        college_id=college_id,
        course_offering_id=offering_id,
        template_id=template.id,
        configured_by_user_id=configured_by,
        is_locked=False,
    )
    session.add(scheme)
    await session.flush()

    for comp in template.default_components:
        weight = Decimal(str(comp["weight_percent"]))
        max_marks = Decimal(str(comp["max_marks"]))
        if aat_override_band and comp["kind"] == "aat":
            weight = Decimal("30")  # push into the 20–40% band
            max_marks = Decimal("30")
        session.add(
            AssessmentSchemeComponent(
                college_id=college_id,
                assessment_scheme_id=scheme.id,
                kind=AssessmentComponentKind(comp["kind"]),
                label=comp["label"],
                max_marks=max_marks,
                weight_percent=weight,
                ordinal=comp["ordinal"],
                is_dropped_in_best_of=False,
                metadata_json=comp.get("metadata", {}),
            )
        )
    await session.flush()

    if aat_override_band and actor_for_override is not None:
        session.add(
            AcademicOverride(
                college_id=college_id,
                override_type=OverrideType.assessment_scheme_unlock,
                actor_user_id=actor_for_override,
                target_course_offering_id=offering_id,
                target_entity_type="assessment_scheme",
                target_entity_id=scheme.id,
                old_value={"aat_weight_percent": 10},
                new_value={"aat_weight_percent": 30},
                reason="HOD pushed AAT into 20–40% band for project-heavy course",
            )
        )
    return scheme


async def seed_setup_for_term(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    depts: dict[str, Department],
    hods: dict[str, User],
    teachers: dict[str, list[User]],
    batches: dict[tuple[str, int], Batch],
    sections: dict[tuple[str, int, str], Section],
    courses: dict[tuple[str, str], Course],
    templates: dict[str, AssessmentSchemeTemplate],
    rooms: dict[str, Room],
    term: AcademicTerm,
    term_code: str,
    batch_year: int,
    is_current: bool,
) -> tuple[
    dict[str, SemesterSetup],         # dept_code → setup
    dict[uuid.UUID, CourseOffering],  # offering id → offering (for cascading later)
    dict[tuple[str, str], list[CourseOffering]],  # (dept_code, course_suffix) → offerings by section
    dict[uuid.UUID, list[LabBatch]],  # offering_id → labs
]:
    """Build a setup per department for the given batch_year + term.

    Course offerings get created per (course, section) within that batch.
    Integrated theory↔lab pairing: the lab-side offering points at its
    theory partner via parent_offering_id, and the lab inherits the
    parent's scheme (so we don't create a duplicate scheme on the lab).
    """
    setups: dict[str, SemesterSetup] = {}
    offerings_by_id: dict[uuid.UUID, CourseOffering] = {}
    offerings_by_course: dict[tuple[str, str], list[CourseOffering]] = defaultdict(list)
    labs_by_offering: dict[uuid.UUID, list[LabBatch]] = defaultdict(list)

    setup_state = SemesterSetupState.active if is_current else SemesterSetupState.archived
    published_at = NOW - timedelta(days=14 if is_current else 200)
    archived_at = None if is_current else NOW - timedelta(days=60)

    semester = (
        BATCH_SEM_AT_CURRENT_TERM[batch_year]
        if is_current
        else BATCH_SEM_AT_PAST_TERM.get(batch_year)
    )
    if semester is None:
        return setups, offerings_by_id, offerings_by_course, labs_by_offering

    # We allow one cross-dept teacher assignment to exercise the
    # cross-department flow: CSE-DS's HOD teaches one CSE Data Visualization
    # course. Only attempt this for the focal batch year on the current
    # term so we don't have to wire it for every term-year combo.
    cross_dept_hod = hods.get("CSE-DS") if (is_current and batch_year == FOCAL_BATCH_YEAR) else None

    for dept_code, _name, _tag, _sec_count, _t in DEPT_SPECS:
        setup = SemesterSetup(
            college_id=college_id,
            department_id=depts[dept_code].id,
            academic_term_id=term.id,
            state=setup_state,
            drafted_by_user_id=hods[dept_code].id,
            published_at=published_at,
            archived_at=archived_at,
            notes=(
                f"{dept_code} {semester}-sem structure for {term_code}. "
                "Seeded by demo data."
            ),
        )
        session.add(setup)
        setups[dept_code] = setup
    await session.flush()

    for dept_code, _name, _tag, sec_count, _t in DEPT_SPECS:
        chosen_courses = _courses_for_semester(dept_code, semester)
        section_names = ("A", "B", "C")[:sec_count]
        dept_teachers = teachers[dept_code]
        if not dept_teachers:
            continue

        # Track theory offerings per course to pair with labs for integrated.
        theory_by_course_section: dict[tuple[str, str], CourseOffering] = {}

        for course_idx, (suffix, _title, _sem, _credits, ctype) in enumerate(chosen_courses):
            course = courses[(dept_code, suffix)]
            assigned_teacher_pool = dept_teachers
            # NPTEL: coordinator is just the first dept teacher.
            # Cross-dept teaching is one course: CSE-DS HOD teaches the CSE
            # Data Visualization course (suffix 503 doesn't exist for CSE
            # so we just pick the first integrated course in CSE setup).
            for sn in section_names:
                section = sections[(dept_code, batch_year, sn)]
                teacher_user = assigned_teacher_pool[course_idx % len(assigned_teacher_pool)]
                # Cross-dept demo: CSE setup, first course of section A, switch
                # to CSE-DS HOD so /hod/dashboard's "my teaching offerings"
                # shows non-CSE-DS courses too.
                if (
                    cross_dept_hod is not None
                    and dept_code == "CSE"
                    and sn == "A"
                    and course_idx == 0
                ):
                    teacher_user = cross_dept_hod

                offering = CourseOffering(
                    college_id=college_id,
                    course_id=course.id,
                    section_id=section.id,
                    teacher_user_id=teacher_user.id,
                    academic_term=term.code,
                    academic_term_id=term.id,
                    semester=semester,
                    is_active=True,
                )
                session.add(offering)
                await session.flush()
                offerings_by_id[offering.id] = offering
                offerings_by_course[(dept_code, suffix)].append(offering)

                # Schemes
                aat_override = (
                    is_current
                    and dept_code == "CSE"
                    and suffix == "401"  # Compiler Design — first one with the heavier AAT
                    and sn == "A"
                )
                await _make_scheme_from_template(
                    session,
                    college_id=college_id,
                    course_type=ctype,
                    templates=templates,
                    offering_id=offering.id,
                    configured_by=teacher_user.id,
                    aat_override_band=aat_override,
                    actor_for_override=hods[dept_code].id if aat_override else None,
                )
                # link FK on the offering itself
                offering.assessment_scheme_id = (
                    (
                        await session.execute(
                            select(AssessmentScheme.id).where(
                                AssessmentScheme.course_offering_id == offering.id
                            )
                        )
                    ).scalar_one()
                )

                if ctype in ("theory", "integrated"):
                    theory_by_course_section[(suffix, sn)] = offering

                # For integrated courses, create a paired lab-side offering
                # within the same setup. The lab inherits the theory's
                # scheme by FK; the scheme row itself stays parent-side.
                if ctype == "integrated":
                    lab_offering = CourseOffering(
                        college_id=college_id,
                        course_id=course.id,
                        section_id=section.id,
                        teacher_user_id=teacher_user.id,
                        academic_term=term.code,
                        academic_term_id=term.id,
                        semester=semester,
                        is_active=True,
                        parent_offering_id=offering.id,
                    )
                    # Append "-LAB" by re-using the same course row; the
                    # uniqueness index is on (section, course, term), so we
                    # can't add a second offering for the same course
                    # in the same section. Workaround for the seed: the
                    # parent offering itself represents the integrated
                    # theory+lab pair, and the LabBatch rows pin the lab
                    # facet to it. M10c never duplicates the offering; the
                    # "lab" side appears only when M3/M4 splits attendance
                    # and marks. So we skip the lab offering row here.
                    _ = lab_offering  # documented intent; not added.

                # Lab batches for integrated. 2–3 batches per section, each
                # 10–20 members.
                if ctype == "integrated":
                    section_students_list = []  # will be populated later
                    lab_count = RNG.choice([2, 2, 3])
                    for li in range(lab_count):
                        batch_name = f"Batch {chr(ord('A') + li)}"
                        lab = LabBatch(
                            college_id=college_id,
                            course_offering_id=offering.id,
                            section_id=section.id,
                            name=batch_name,
                            display_order=li + 1,
                        )
                        session.add(lab)
                        await session.flush()
                        labs_by_offering[offering.id].append(lab)
                        # Assign incharge: batch 1 → main theory teacher,
                        # batches 2+ → other dept teachers.
                        incharge = (
                            teacher_user
                            if li == 0
                            else dept_teachers[(course_idx + li) % len(dept_teachers)]
                        )
                        session.add(
                            LabBatchAssignment(
                                college_id=college_id,
                                lab_batch_id=lab.id,
                                teacher_user_id=incharge.id,
                                role="batch_incharge",
                                assigned_at=NOW - timedelta(days=10),
                            )
                        )
        await session.flush()

    # Publish events for the current term (M10a invariant: emit
    # semester_setup.published on transition into the published/active
    # state). For past terms, the event was already fired long ago and the
    # admin_notification row would have been archived — skip.
    if is_current:
        for dept_code, setup in setups.items():
            await publish(
                "semester_setup.published",
                {"setup_id": str(setup.id), "department_id": str(setup.department_id)},
                college_id=college_id,
                actor_user_id=hods[dept_code].id,
            )
            # The M10a subscriber writes admin_notifications; do the same
            # directly so /admin/notifications has content even with
            # subscribers disabled at seed time (APP_ENV may not be 'dev').
            session.add(
                AdminNotification(
                    college_id=college_id,
                    event_type="semester_setup.published",
                    payload={
                        "setup_id": str(setup.id),
                        "department_id": str(setup.department_id),
                        "department_code": dept_code,
                        "term_code": term.code,
                    },
                    created_at=NOW - timedelta(days=14),
                )
            )
    await session.flush()

    return setups, offerings_by_id, offerings_by_course, labs_by_offering


# ─────────────────────────────────────────────────────────────────────────────
# 10. Elective groups (CSE + CSE-DS only)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_electives_for_setup(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    dept_code: str,
    setup: SemesterSetup,
    teachers: dict[str, list[User]],
    courses: dict[tuple[str, str], Course],
    hod: User,
) -> dict[str, list[ElectiveGroupOption]]:
    """Create one or two elective groups for the dept. Returns a map
    keyed by group name → options, so the caller can register students.
    """
    out: dict[str, list[ElectiveGroupOption]] = {}
    if dept_code not in ("CSE", "CSE-DS"):
        return out

    # Group: Professional Elective III — students choose one of three CSE
    # 7th-sem courses. Add a fourth dissolved option for the demo.
    group_courses_by_dept = {
        "CSE": [
            ("Professional Elective III", "Choose one professional elective", [
                ("Cyber Security", "CS503"),
                ("Cryptography & Network Security", "CS504"),
                ("Distributed Systems", "CS505"),
                ("Blockchain Technology", "CS507"),
            ]),
        ],
        "CSE-DS": [
            ("Domain Elective II", "Choose one advanced data-science elective", [
                ("Computer Vision", "CD501"),
                ("Reinforcement Learning", "CD502"),
                ("Time Series Analysis", "CD505"),
            ]),
        ],
    }
    for group_name, group_desc, course_specs in group_courses_by_dept[dept_code]:
        group = ElectiveGroup(
            college_id=college_id,
            semester_setup_id=setup.id,
            name=group_name,
            description=group_desc,
            min_enrollment_to_run=10,
            max_enrollment=None,
        )
        session.add(group)
        await session.flush()
        opts: list[ElectiveGroupOption] = []
        for i, (label, course_code) in enumerate(course_specs):
            usn_tag = dict((d[0], d[2]) for d in DEPT_SPECS)[dept_code]
            suffix = course_code.replace(usn_tag, "")
            course = courses.get((dept_code, suffix))
            if course is None:
                continue
            tentative = teachers[dept_code][i % len(teachers[dept_code])]
            opt = ElectiveGroupOption(
                college_id=college_id,
                elective_group_id=group.id,
                course_id=course.id,
                tentative_teacher_id=tentative.id,
            )
            session.add(opt)
            opts.append(opt)
        await session.flush()
        out[group_name] = opts

    # For CSE: dissolve the last option (Blockchain Technology) and route
    # its migrants to the first option (Cyber Security). Write the
    # academic_override audit row.
    if dept_code == "CSE" and out:
        opts = out["Professional Elective III"]
        if len(opts) >= 4:
            survivor = opts[0]
            dissolved = opts[-1]
            dissolved.is_dissolved = True
            dissolved.dissolved_at = NOW - timedelta(days=7)
            dissolved.dissolved_by_user_id = hod.id
            dissolved.dissolved_reason = "Low enrollment (3 students) — below min_enrollment_to_run"
            dissolved.migrated_to_option_id = survivor.id
            session.add(
                AcademicOverride(
                    college_id=college_id,
                    override_type=OverrideType.student_migration,
                    actor_user_id=hod.id,
                    target_entity_type="elective_group_option",
                    target_entity_id=dissolved.id,
                    old_value={"option_id": str(dissolved.id), "status": "active"},
                    new_value={"option_id": str(survivor.id), "status": "migrated"},
                    reason="Dissolved Blockchain Technology — 3 students below min_to_run",
                )
            )
            session.add(
                AdminNotification(
                    college_id=college_id,
                    event_type="elective.dissolved",
                    payload={
                        "elective_group_id": str(opts[0].elective_group_id),
                        "dissolved_option_id": str(dissolved.id),
                        "migrated_to_option_id": str(survivor.id),
                        "migrated_count": 3,
                    },
                    created_at=NOW - timedelta(days=7),
                )
            )

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 11. Enrollments + course registrations (for one (term, batch_year))
# ─────────────────────────────────────────────────────────────────────────────
async def seed_enrollments_for_term(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    students_by_section: dict[tuple[str, int, str], list[User]],
    sections: dict[tuple[str, int, str], Section],
    term: AcademicTerm,
    batch_year: int,
    is_current: bool,
) -> dict[uuid.UUID, int]:
    """Bulk-create enrollments for every student in the batch. Returns a
    map of student.id → enrollment.id so downstream callers (SEE,
    grade cards) can FK without re-querying.
    """
    semester = (
        BATCH_SEM_AT_CURRENT_TERM[batch_year]
        if is_current
        else BATCH_SEM_AT_PAST_TERM.get(batch_year)
    )
    if semester is None:
        return {}

    enroll_rows: list[dict[str, Any]] = []
    enrolled_at = NOW - timedelta(days=120 if not is_current else 21)
    for (dept_code, yr, sn), section in sections.items():
        if yr != batch_year:
            continue
        students = students_by_section.get((dept_code, yr, sn), [])
        for stu in students:
            enroll_rows.append(
                dict(
                    college_id=college_id,
                    student_user_id=stu.id,
                    section_id=section.id,
                    academic_term=term.code,
                    semester=semester,
                    enrolled_at=enrolled_at,
                    withdrawn_at=None,
                    enrollment_state=EnrollmentState.active,
                    academic_term_id=term.id,
                )
            )
    if not enroll_rows:
        return {}
    # Bulk-insert in chunks; return IDs by re-querying.
    for i in range(0, len(enroll_rows), 1000):
        await session.execute(insert(Enrollment), enroll_rows[i : i + 1000])
    await session.flush()
    # Build map student_user_id → enrollment.id (the most recent for this term)
    rows = (
        await session.execute(
            select(Enrollment.id, Enrollment.student_user_id).where(
                Enrollment.college_id == college_id,
                Enrollment.academic_term_id == term.id,
            )
        )
    ).all()
    return {sid: eid for eid, sid in rows}


async def register_focal_batch_electives(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    setup: SemesterSetup,
    elective_groups_by_dept: dict[str, dict[str, list[ElectiveGroupOption]]],
    students_by_section: dict[tuple[str, int, str], list[User]],
    dept_code: str,
    batch_year: int,
) -> int:
    """Distribute focal-batch students across elective options. Returns
    the count of migrated rows the cascade should reflect.
    """
    section_count = dict((d[0], d[3]) for d in DEPT_SPECS)[dept_code]
    section_names = ("A", "B", "C")[:section_count]
    all_students: list[User] = []
    for sn in section_names:
        all_students.extend(students_by_section.get((dept_code, batch_year, sn), []))

    groups = elective_groups_by_dept.get(dept_code, {})
    if not groups:
        return 0

    migrated_count = 0
    for group_name, options in groups.items():
        active_opts = [o for o in options if not o.is_dissolved]
        dissolved_opts = [o for o in options if o.is_dissolved]
        # Distribute weighted: first option gets the most (popular), last
        # gets the least (under-strength signal for HOD dashboard).
        if not active_opts:
            continue
        for i, student in enumerate(all_students):
            if dept_code == "CSE" and dissolved_opts and i < 3:
                # 3 students were on the dissolved option, migrated to the
                # survivor. Write a course_registration row with
                # status='migrated' so /student/dashboard banner triggers.
                migrated_count += 1
                session.add(
                    CourseRegistration(
                        college_id=college_id,
                        student_user_id=student.id,
                        semester_setup_id=setup.id,
                        elective_group_id=dissolved_opts[0].elective_group_id,
                        elective_group_option_id=dissolved_opts[0].id,
                        course_id=dissolved_opts[0].course_id,
                        status="migrated",
                        is_backlog=False,
                    )
                )
                # New row pointing at the survivor (matches the cascade output)
                session.add(
                    CourseRegistration(
                        college_id=college_id,
                        student_user_id=student.id,
                        semester_setup_id=setup.id,
                        elective_group_id=active_opts[0].elective_group_id,
                        elective_group_option_id=active_opts[0].id,
                        course_id=active_opts[0].course_id,
                        status="approved",
                        is_backlog=False,
                    )
                )
                continue
            # Skew distribution: 50% to first option, 30% second, 15%
            # third, 5% fourth (if present). Creates one healthy, one
            # under-strength on /hod/electives.
            r = RNG.random()
            if r < 0.50:
                pick = active_opts[0]
            elif r < 0.80 and len(active_opts) > 1:
                pick = active_opts[1]
            elif r < 0.95 and len(active_opts) > 2:
                pick = active_opts[2]
            elif len(active_opts) > 3:
                pick = active_opts[3]
            else:
                pick = active_opts[-1]
            session.add(
                CourseRegistration(
                    college_id=college_id,
                    student_user_id=student.id,
                    semester_setup_id=setup.id,
                    elective_group_id=pick.elective_group_id,
                    elective_group_option_id=pick.id,
                    course_id=pick.course_id,
                    status="approved",
                    is_backlog=False,
                )
            )
    await session.flush()
    return migrated_count


# ─────────────────────────────────────────────────────────────────────────────
# 12. Class sessions + attendance (focal batch only — to keep volume sane)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_class_sessions_and_attendance(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    offerings_by_course: dict[tuple[str, str], list[CourseOffering]],
    students_by_section: dict[tuple[str, int, str], list[User]],
    sections: dict[tuple[str, int, str], Section],
    rooms: dict[str, Room],
    term: AcademicTerm,
    is_current: bool,
    weeks: int,
    focal_dept_only: bool,
) -> tuple[int, int]:
    """Create N weeks of class_sessions (3/week per offering) and one
    attendance record per (session, enrolled student). Returns
    (sessions_count, attendance_count).
    """
    # Pick the date range — past term wraps from term.starts_on to ends_on;
    # current term covers `weeks` weeks ending today.
    if is_current:
        last_session_date = TODAY - timedelta(days=2)
        first_session_date = last_session_date - timedelta(weeks=weeks)
    else:
        first_session_date = term.starts_on
        last_session_date = first_session_date + timedelta(weeks=weeks)
    # Skip past today even for past-term — sessions in the future make no sense
    if last_session_date > TODAY:
        last_session_date = TODAY - timedelta(days=1)

    # 3 sessions per week on Mon/Wed/Fri
    weekday_targets = (0, 2, 4)  # Mon, Wed, Fri
    session_rows: list[dict[str, Any]] = []
    attendance_rows: list[dict[str, Any]] = []
    sessions_created = 0
    attendance_created = 0

    lecture_rooms = [r for r in rooms.values() if r.room_type == RoomType.lecture]

    # Build (offering, students-list) pairs only for offerings whose
    # course is in the focal cohort. For each section's students we use
    # the offering's section.
    target_sections: dict[uuid.UUID, list[User]] = {}
    for (dept_code, yr, sn), stu_list in students_by_section.items():
        if focal_dept_only and dept_code != FOCAL_DEPT_CODE:
            continue
        if yr != FOCAL_BATCH_YEAR:
            continue
        target_sections[sections[(dept_code, yr, sn)].id] = stu_list

    for offerings in offerings_by_course.values():
        for offering in offerings:
            # Filter by term — caller may pass a single all-offerings map
            # for both past and current invocations.
            if offering.academic_term_id != term.id:
                continue
            if offering.section_id not in target_sections:
                continue
            students = target_sections[offering.section_id]
            if not students:
                continue
            # Pick attendance pattern per student deterministically so the
            # same usn always lands in the same pattern bucket.
            patterns: dict[uuid.UUID, str] = {}
            for s in students:
                seed_byte = s.id.int & 0xFF
                if seed_byte < 178:
                    patterns[s.id] = "healthy"   # 70%
                elif seed_byte < 230:
                    patterns[s.id] = "warning"   # 20%
                else:
                    patterns[s.id] = "danger"    # 10%

            # Pass 1: emit class_sessions for the date range, capture ids.
            per_offering_sessions: list[tuple[uuid.UUID, datetime, datetime]] = []
            current = first_session_date
            while current <= last_session_date:
                if current.weekday() in weekday_targets:
                    start_t = time(10 + (current.weekday() // 2), 0)
                    end_t = time(start_t.hour + 1, 0)
                    sid = uuid.uuid4()
                    opened_at = datetime.combine(current, start_t).replace(tzinfo=timezone.utc)
                    closed_at = datetime.combine(current, end_t).replace(tzinfo=timezone.utc)
                    session_rows.append(
                        dict(
                            id=sid,
                            college_id=college_id,
                            course_offering_id=offering.id,
                            room_id=RNG.choice(lecture_rooms).id,
                            scheduled_date=current,
                            start_time=start_t,
                            end_time=end_t,
                            state=ClassSessionState.closed,
                            source=ClassSessionSource.materialised,
                            origin_slot_id=None,
                            origin_exception_id=None,
                            opened_at=opened_at,
                            closed_at=closed_at,
                            created_at=opened_at,
                            updated_at=closed_at,
                        )
                    )
                    sessions_created += 1
                    per_offering_sessions.append((sid, opened_at, closed_at))
                current += timedelta(days=1)

            # Flush this offering's class_sessions before we emit
            # attendance_records that FK them. Avoids the FK-ordering
            # bug where 5,000 attendance rows queue up referencing
            # sessions still sitting in the un-inserted buffer.
            if session_rows:
                await session.execute(insert(ClassSession), session_rows)
                session_rows = []

            # Pass 2: per-session attendance rows.
            for sid, opened_at, _closed_at in per_offering_sessions:
                submit_at = opened_at + timedelta(minutes=2)
                verified_at = submit_at + timedelta(minutes=1)
                for student in students:
                    bucket = patterns[student.id]
                    threshold = {"healthy": 0.90, "warning": 0.70, "danger": 0.50}[bucket]
                    present = RNG.random() < threshold
                    rm = RNG.random()
                    if rm < 0.60:
                        face_match = False
                        face_conf = Decimal("0.000")
                        method_qr = uuid.uuid4()
                    elif rm < 0.85:
                        face_match = False
                        face_conf = Decimal("0.000")
                        method_qr = None
                    else:
                        face_match = present
                        face_conf = Decimal("0.950") if present else Decimal("0.300")
                        method_qr = None
                    attendance_rows.append(
                        dict(
                            id=uuid.uuid4(),
                            college_id=college_id,
                            class_session_id=sid,
                            student_user_id=student.id,
                            state=(
                                AttendanceRecordState.verified
                                if present
                                else AttendanceRecordState.flagged
                            ),
                            submitted_at=submit_at,
                            verified_at=verified_at if present else None,
                            recorded_at=verified_at if present else None,
                            flagged_reason=None if present else "absent",
                            gps_lat=None,
                            gps_lon=None,
                            gps_distance_m=None,
                            face_match=face_match,
                            face_confidence=face_conf,
                            qr_token_jti=method_qr,
                            device_log_id=None,
                            created_at=submit_at,
                            updated_at=verified_at or submit_at,
                        )
                    )
                    attendance_created += 1

            if len(attendance_rows) >= 5000:
                await session.execute(insert(AttendanceRecord), attendance_rows)
                attendance_rows = []

    if session_rows:
        await session.execute(insert(ClassSession), session_rows)
    if attendance_rows:
        await session.execute(insert(AttendanceRecord), attendance_rows)
    await session.flush()
    return sessions_created, attendance_created


# ─────────────────────────────────────────────────────────────────────────────
# 13. Assessments + marks (CIE-1 current; CIE 1+2+3+AAT past)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_assessments_and_marks(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    offerings_by_course: dict[tuple[str, str], list[CourseOffering]],
    students_by_section: dict[tuple[str, int, str], list[User]],
    sections: dict[tuple[str, int, str], Section],
    term: AcademicTerm,
    is_current: bool,
    focal_dept_only: bool,
) -> tuple[int, int]:
    """Create assessment rows and student marks. For the current term,
    only CIE-1 is fully entered + a partial AAT for 40% of offerings.
    For the past term, CIE-1/2/3 + AAT are all entered.
    """
    assessment_specs: list[tuple[AssessmentType, str, Decimal]] = []
    if is_current:
        assessment_specs = [(AssessmentType.cie1, "CIE-1", Decimal("40"))]
        partial_aat = True
    else:
        assessment_specs = [
            (AssessmentType.cie1, "CIE-1", Decimal("40")),
            (AssessmentType.cie2, "CIE-2", Decimal("40")),
            (AssessmentType.cie3, "CIE-3", Decimal("40")),
        ]
        partial_aat = False

    # Sections to consider (focal cohort)
    target_section_ids: set[uuid.UUID] = set()
    for (dept_code, yr, sn), sect in sections.items():
        if focal_dept_only and dept_code != FOCAL_DEPT_CODE:
            continue
        if yr != FOCAL_BATCH_YEAR:
            continue
        target_section_ids.add(sect.id)

    assessments_created = 0
    marks_created = 0
    mark_rows: list[dict[str, Any]] = []

    # Pre-pick teachers per offering to use as entered_by/modified_by.
    for offerings in offerings_by_course.values():
        for offering in offerings:
            if offering.academic_term_id != term.id:
                continue
            if offering.section_id not in target_section_ids:
                continue
            students = []
            for (_d, _y, _s), section in sections.items():
                if section.id == offering.section_id:
                    students = students_by_section[(_d, _y, _s)]
                    break

            # Build assessment rows for this offering.
            for atype, label, max_marks in assessment_specs:
                a = Assessment(
                    college_id=college_id,
                    course_offering_id=offering.id,
                    type=atype,
                    name=label,
                    max_marks=max_marks,
                    weight_percent=Decimal("20") if is_current else Decimal("20"),
                    scheduled_date=(
                        term.starts_on + timedelta(days=30) if is_current else None
                    ),
                    state=AssessmentState.locked if not is_current else AssessmentState.open,
                    locked_at=NOW - timedelta(days=30) if not is_current else None,
                    locked_by_user_id=offering.teacher_user_id if not is_current else None,
                )
                session.add(a)
                await session.flush()
                assessments_created += 1
                # 80% of students have entered marks for the current term;
                # 100% for past. A couple of students are explicitly absent
                # so M4's best-2-of-3 sees the gap.
                for idx, student in enumerate(students):
                    if is_current and idx >= int(len(students) * 0.80):
                        break
                    # 2-3 students absent (per offering, deterministic on idx)
                    is_absent = idx in (3, 17, 29) and atype == AssessmentType.cie1
                    if is_absent:
                        score = None
                    else:
                        # Decimal between 0 and max_marks; bias toward 60–85%
                        base = Decimal(str(max_marks)) * Decimal(
                            str(RNG.uniform(0.55, 0.92))
                        )
                        # Round to 2 decimals
                        score = base.quantize(Decimal("0.01"))
                    mark_rows.append(
                        dict(
                            id=uuid.uuid4(),
                            college_id=college_id,
                            assessment_id=a.id,
                            student_user_id=student.id,
                            marks_obtained=score,
                            is_absent=is_absent,
                            state=MarkState.entered if is_current else MarkState.locked,
                            entered_by_user_id=offering.teacher_user_id,
                            last_modified_by_user_id=offering.teacher_user_id,
                            created_at=NOW - timedelta(days=10),
                            updated_at=NOW - timedelta(days=5),
                        )
                    )
                    marks_created += 1
            # AAT — current term partial (40% of offerings have it);
            # past term: every offering has it.
            include_aat = (not is_current) or RNG.random() < 0.40
            if include_aat:
                a_aat = Assessment(
                    college_id=college_id,
                    course_offering_id=offering.id,
                    type=AssessmentType.assignment,
                    name="AAT",
                    max_marks=Decimal("20"),
                    weight_percent=Decimal("10"),
                    state=AssessmentState.locked if not is_current else AssessmentState.open,
                    locked_at=NOW - timedelta(days=15) if not is_current else None,
                    locked_by_user_id=offering.teacher_user_id if not is_current else None,
                )
                session.add(a_aat)
                await session.flush()
                assessments_created += 1
                for student in students:
                    base = Decimal("20") * Decimal(str(RNG.uniform(0.50, 0.95)))
                    score = base.quantize(Decimal("0.01"))
                    mark_rows.append(
                        dict(
                            id=uuid.uuid4(),
                            college_id=college_id,
                            assessment_id=a_aat.id,
                            student_user_id=student.id,
                            marks_obtained=score,
                            is_absent=False,
                            state=MarkState.entered if is_current else MarkState.locked,
                            entered_by_user_id=offering.teacher_user_id,
                            last_modified_by_user_id=offering.teacher_user_id,
                            created_at=NOW - timedelta(days=10),
                            updated_at=NOW - timedelta(days=5),
                        )
                    )
                    marks_created += 1

            if len(mark_rows) >= 2000:
                await session.execute(insert(Mark), mark_rows)
                mark_rows = []

    if mark_rows:
        await session.execute(insert(Mark), mark_rows)
    await session.flush()
    return assessments_created, marks_created


# ─────────────────────────────────────────────────────────────────────────────
# 14. SEE results, re-evaluations, hall tickets, grade cards (past term)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_see_and_grade_cards(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    enrollment_map: dict[uuid.UUID, int],
    offerings_by_course: dict[tuple[str, str], list[CourseOffering]],
    students_by_usn: dict[str, User],
    students_by_section: dict[tuple[str, int, str], list[User]],
    sections: dict[tuple[str, int, str], Section],
    term: AcademicTerm,
    hods: dict[str, User],
    courses: dict[tuple[str, str], Course],
) -> dict[str, int]:
    """For the focal CSE 2023 batch only: generate SEE results (80%
    released, 20% pending), grade cards with versions, a couple of
    re-evaluations, and one late-SEE regenerated v2.
    """
    counts = {"see_results": 0, "re_evaluations": 0, "hall_tickets": 0, "grade_cards": 0}

    # Target offerings: focal dept (CSE), focal batch (2023), in past term
    target_offerings: list[CourseOffering] = []
    target_section_ids: set[uuid.UUID] = set()
    for (dept_code, yr, sn), sect in sections.items():
        if dept_code != FOCAL_DEPT_CODE or yr != FOCAL_BATCH_YEAR:
            continue
        target_section_ids.add(sect.id)
    for offerings in offerings_by_course.values():
        for offering in offerings:
            if (
                offering.academic_term_id == term.id
                and offering.section_id in target_section_ids
            ):
                target_offerings.append(offering)

    # Heads-up: students from the focal sections only.
    focal_students: list[User] = []
    for (dept_code, yr, sn), stu_list in students_by_section.items():
        if dept_code == FOCAL_DEPT_CODE and yr == FOCAL_BATCH_YEAR:
            focal_students.extend(stu_list)

    if not target_offerings or not focal_students:
        return counts

    # Tag 20% of offerings as 'pending' SEE so grade cards have I grades
    pending_offerings = set(
        RNG.sample(target_offerings, max(1, int(len(target_offerings) * 0.20)))
    )

    csv_batch_id = uuid.uuid4()
    hod_user = hods[FOCAL_DEPT_CODE]

    # The schema only allows ONE current SEE row per enrollment (partial
    # unique on `enrollment_id WHERE is_current`). Per-subject SEE marks
    # are represented in the grade_card snapshot JSON, not as
    # per-(enrollment, course) rows. So we create one SEE row per
    # focal student for the past term.
    see_rows: list[dict[str, Any]] = []
    student_enrollment = enrollment_map
    pending_student_ids: set[uuid.UUID] = set()
    # Roughly 20% of focal students have NO SEE row yet — simulates
    # the "results not released" path that triggers I grades. Force the
    # first focal student into the pending bucket so the v2 grade card
    # demo (late SEE release → flip) always has a subject to flip.
    pending_student_ids.add(focal_students[0].id)
    for stu in focal_students[1:]:
        if RNG.random() < 0.20:
            pending_student_ids.add(stu.id)

    for stu in focal_students:
        if stu.id in pending_student_ids:
            continue
        enroll_id = student_enrollment.get(stu.id)
        if enroll_id is None:
            continue
        r = RNG.random()
        if r < 0.08:
            score = Decimal(str(RNG.uniform(15, 39))).quantize(Decimal("0.01"))
        elif r < 0.30:
            score = Decimal(str(RNG.uniform(40, 60))).quantize(Decimal("0.01"))
        else:
            score = Decimal(str(RNG.uniform(60, 92))).quantize(Decimal("0.01"))
        see_rows.append(
            dict(
                id=uuid.uuid4(),
                college_id=college_id,
                enrollment_id=enroll_id,
                kind=SEEResultKind.original,
                marks_obtained=score,
                max_marks=Decimal("100"),
                uploaded_at=NOW - timedelta(days=45),
                uploaded_by_user_id=hod_user.id,
                csv_upload_batch_id=csv_batch_id,
                notes="Original SEE upload",
                superseded_by=None,
                is_current=True,
                created_at=NOW - timedelta(days=45),
                updated_at=NOW - timedelta(days=45),
            )
        )
        counts["see_results"] += 1

    if see_rows:
        for i in range(0, len(see_rows), 1000):
            await session.execute(insert(SEEResult), see_rows[i : i + 1000])
    await session.flush()

    # Two re-evaluations on the first focal section's first two students
    # that actually have a current SEE row (skip the pending ones — the
    # first focal student is in pending_student_ids on purpose).
    if focal_students:
        focal_section_students = [
            s for s in students_by_section[
                (FOCAL_DEPT_CODE, FOCAL_BATCH_YEAR, "A")
            ]
            if s.id not in pending_student_ids
        ][:2]
        for idx, stu in enumerate(focal_section_students):
            enroll_id = student_enrollment.get(stu.id)
            if enroll_id is None:
                continue
            original = (
                await session.execute(
                    select(SEEResult).where(
                        SEEResult.enrollment_id == enroll_id,
                        SEEResult.is_current.is_(True),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if original is None:
                continue
            improved = idx == 0
            revised_marks = (
                (original.marks_obtained or Decimal("50")) + Decimal("6")
                if improved
                else original.marks_obtained
            )
            # Flip the original first so the partial unique on
            # is_current=true doesn't trip when the new row lands.
            original.is_current = False
            await session.flush()
            revised = SEEResult(
                college_id=college_id,
                enrollment_id=enroll_id,
                kind=SEEResultKind.re_evaluation,
                marks_obtained=revised_marks,
                max_marks=Decimal("100"),
                uploaded_at=NOW - timedelta(days=15),
                uploaded_by_user_id=hod_user.id,
                csv_upload_batch_id=uuid.uuid4(),
                notes="Re-eval upload",
                is_current=True,
            )
            session.add(revised)
            await session.flush()
            original.superseded_by = revised.id
            session.add(
                ReEvaluation(
                    college_id=college_id,
                    enrollment_id=enroll_id,
                    requested_by_student_user_id=stu.id,
                    requested_at=NOW - timedelta(days=22),
                    status="completed",
                    original_see_result_id=original.id,
                    revised_see_result_id=revised.id,
                    outcome="improved" if improved else "held",
                    reason="Student requested re-evaluation for paper recount",
                    resolved_at=NOW - timedelta(days=15),
                    resolved_by_user_id=hod_user.id,
                )
            )
            counts["re_evaluations"] += 1

    # Hall tickets — delegate to the M10e service so the eligibility
    # snapshot has the canonical shape the UI consumes
    # (course_offering_id, course_type, attendance_percent, cie_percent,
    # *_eligible, reason). The service builds the snapshot from the
    # seeded class_sessions + attendance + marks rows.
    ticket_ids: list[uuid.UUID] = []
    for stu in focal_students:
        try:
            ticket, _version, _is_new = await generate_hall_ticket_for_student(
                session,
                actor=hod_user,
                student_user_id=stu.id,
                academic_term_id=term.id,
            )
            ticket_ids.append(ticket.id)
            counts["hall_tickets"] += 1
        except Exception as e:
            # Skip students with no enrollment in this term — shouldn't
            # happen for the focal cohort but be defensive.
            print(f"  hall_ticket skipped for {stu.usn}: {e}")
    # Batch-approve all generated tickets so /hod/hall-tickets shows them
    # already approved (matches the past-term completed state).
    if ticket_ids:
        await approve_hall_tickets(
            session, actor=hod_user, hall_ticket_ids=ticket_ids
        )

    # Grade cards — call generate_grade_card per focal student. The
    # service reads the current SEE row + per-subject internal marks and
    # produces the canonical grades_snapshot shape.
    for stu in focal_students:
        try:
            await generate_grade_card(
                session,
                actor=hod_user,
                student_user_id=stu.id,
                academic_term_id=term.id,
                trigger_reason="initial",
            )
            counts["grade_cards"] += 1
        except Exception as e:
            print(f"  grade_card skipped for {stu.usn}: {e}")

    # Late-SEE simulation: the focal student #0 didn't have a SEE row,
    # so their v1 grade card came out with I grades. Insert a SEE result
    # for one of their enrollments and trigger regeneration so v2 ships
    # with a real grade. This is exactly what the M10e SEE-upload path
    # does in production, minus the CSV ceremony.
    first_student = focal_students[0]
    first_enrollment_id = enrollment_map.get(first_student.id)
    if first_enrollment_id is not None:
        existing = (
            await session.execute(
                select(SEEResult).where(
                    SEEResult.enrollment_id == first_enrollment_id,
                    SEEResult.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                SEEResult(
                    college_id=college_id,
                    enrollment_id=first_enrollment_id,
                    kind=SEEResultKind.original,
                    marks_obtained=Decimal("72.00"),
                    max_marks=Decimal("100"),
                    uploaded_at=NOW - timedelta(days=3),
                    uploaded_by_user_id=hod_user.id,
                    csv_upload_batch_id=uuid.uuid4(),
                    notes="Late SEE release",
                    is_current=True,
                )
            )
            await session.flush()
            try:
                await regenerate_grade_card(
                    session,
                    actor=hod_user,
                    student_user_id=first_student.id,
                    academic_term_id=term.id,
                    trigger_reason="see_released",
                )
            except Exception as e:
                print(f"  grade_card v2 regen skipped: {e}")

    return counts


# ─────────────────────────────────────────────────────────────────────────────
# 15. CIE schedule for current term (CIE-1 past published; CIE-2 future)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_cie_schedule(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    offerings_by_course: dict[tuple[str, str], list[CourseOffering]],
    rooms: dict[str, Room],
    term: AcademicTerm,
) -> int:
    """CIE-1 sits 14 days back (past, published). CIE-2 sits 14 days ahead
    (future, published). CIE-3 unscheduled. Per-offering rows; we keep
    this targeted at the focal dept to avoid 100+ scheduled exams.
    """
    cie1_at = datetime.combine(TODAY - timedelta(days=14), time(10, 0)).replace(tzinfo=timezone.utc)
    cie2_at = datetime.combine(TODAY + timedelta(days=14), time(10, 0)).replace(tzinfo=timezone.utc)
    rooms_list = list(rooms.values())
    count = 0
    for offerings in offerings_by_course.values():
        for offering in offerings:
            if offering.academic_term_id != term.id:
                continue
            session.add(
                CIESchedule(
                    college_id=college_id,
                    course_offering_id=offering.id,
                    cie_number=1,
                    scheduled_at=cie1_at,
                    duration_minutes=60,
                    room_id=RNG.choice(rooms_list).id,
                    is_published=True,
                    published_at=NOW - timedelta(days=21),
                )
            )
            session.add(
                CIESchedule(
                    college_id=college_id,
                    course_offering_id=offering.id,
                    cie_number=2,
                    scheduled_at=cie2_at,
                    duration_minutes=60,
                    room_id=RNG.choice(rooms_list).id,
                    is_published=True,
                    published_at=NOW - timedelta(days=3),
                )
            )
            count += 2
    await session.flush()
    return count


# ─────────────────────────────────────────────────────────────────────────────
# 16. Internal deadlines + tasks + admin overrides
# ─────────────────────────────────────────────────────────────────────────────
async def seed_deadlines_tasks_overrides(
    session: AsyncSession,
    *,
    college_id: uuid.UUID,
    admin_user: User,
    hods: dict[str, User],
    teachers: dict[str, list[User]],
    students_by_section: dict[tuple[str, int, str], list[User]],
    depts: dict[str, Department],
    term: AcademicTerm,
) -> dict[str, int]:
    counts = {"deadlines": 0, "tasks": 0, "overrides": 0, "notifications": 0}

    # Institutional hard stop — admin owns
    session.add(
        InternalDeadline(
            college_id=college_id,
            academic_term_id=term.id,
            department_id=None,
            course_offering_id=None,
            deadline_at=NOW + timedelta(days=45),
            kind=DeadlineKind.institutional_hard.value,
            set_by_user_id=admin_user.id,
            notes="Institution-wide internal deadline for 2026-Odd CIE/AAT entry.",
        )
    )
    counts["deadlines"] += 1
    # Per-dept soft target — HOD owns
    for dept_code, hod in hods.items():
        session.add(
            InternalDeadline(
                college_id=college_id,
                academic_term_id=term.id,
                department_id=depts[dept_code].id,
                course_offering_id=None,
                deadline_at=NOW + timedelta(days=30),
                kind=DeadlineKind.department_soft.value,
                set_by_user_id=hod.id,
                notes=f"{dept_code} soft deadline — keep us ahead of institutional cut.",
            )
        )
        counts["deadlines"] += 1
    await session.flush()

    # HOD-CSE assigns tasks to CSE teachers in mixed states. 8 single-
    # assignee tasks span the state machine; one multi-assignee task
    # demonstrates the post-Session-3 task_assignments shape (three
    # invigilators on the same CIE — one accepted, one pending, one
    # declined).
    hod_cse = hods["CSE"]
    cse_teachers = teachers["CSE"]
    single_assignee_tasks = [
        (TaskStatus.pending, "Invigilate CIE-2 for CS501", TaskType.invigilation),
        (TaskStatus.pending, "Set CIE-2 paper for CS502", TaskType.paper_setting),
        (TaskStatus.pending, "Evaluate CS505 mid-term scripts", TaskType.evaluation),
        (TaskStatus.accepted, "Invigilate CIE-2 for CS503", TaskType.invigilation),
        (TaskStatus.accepted, "Set AAT rubric for CS502", TaskType.paper_setting),
        (TaskStatus.completed, "Conduct makeup CIE for CS501", TaskType.makeup_exam),
        (TaskStatus.completed, "Evaluate AAT submissions for CS401", TaskType.evaluation),
        (TaskStatus.declined, "Invigilate CIE-1 for CS502", TaskType.invigilation),
    ]
    for state, title, ttype in single_assignee_tasks:
        teacher = cse_teachers[RNG.randint(0, len(cse_teachers) - 1)]
        task = Task(
            college_id=college_id,
            assigned_by_user_id=hod_cse.id,
            task_type=ttype,
            title=title,
            description="Assigned via demo seed for /hod/tasks + /teacher/tasks walkthrough.",
            due_at=NOW + timedelta(days=RNG.randint(3, 21)),
        )
        session.add(task)
        await session.flush()
        session.add(
            TaskAssignment(
                task_id=task.id,
                assignee_user_id=teacher.id,
                status=state,
                status_updated_at=(
                    NOW - timedelta(days=RNG.randint(1, 14))
                    if state != TaskStatus.pending
                    else None
                ),
                decline_reason=(
                    "Conflicting class slot"
                    if state == TaskStatus.declined
                    else None
                ),
            )
        )
        counts["tasks"] += 1

    # Multi-assignee showcase — three invigilators for the same CIE.
    multi_task = Task(
        college_id=college_id,
        assigned_by_user_id=hod_cse.id,
        task_type=TaskType.invigilation,
        title="Department-wide invigilation pool — CIE-2 hall A/B/C",
        description=(
            "Three invigilators share the same CIE. Each transitions their "
            "own assignment row independently; the HOD dashboard rolls the "
            "aggregate up via status_counts."
        ),
        due_at=NOW + timedelta(days=10),
    )
    session.add(multi_task)
    await session.flush()
    multi_assignees = [
        (cse_teachers[0], TaskStatus.accepted),
        (cse_teachers[1 % len(cse_teachers)], TaskStatus.pending),
        (cse_teachers[2 % len(cse_teachers)], TaskStatus.declined),
    ]
    for teacher, state in multi_assignees:
        session.add(
            TaskAssignment(
                task_id=multi_task.id,
                assignee_user_id=teacher.id,
                status=state,
                status_updated_at=(
                    NOW - timedelta(days=RNG.randint(1, 5))
                    if state != TaskStatus.pending
                    else None
                ),
                decline_reason=(
                    "Travel for conference that week"
                    if state == TaskStatus.declined
                    else None
                ),
            )
        )
    counts["tasks"] += 1
    await session.flush()

    # Academic overrides — 3 attendance condonations + 1 mark unlock.
    # Pick three focal students for the condonations.
    focal_section_students = students_by_section.get(
        (FOCAL_DEPT_CODE, FOCAL_BATCH_YEAR, "A"), []
    )
    for stu in focal_section_students[:3]:
        session.add(
            AcademicOverride(
                college_id=college_id,
                override_type=OverrideType.attendance_condonation,
                actor_user_id=hod_cse.id,
                target_student_user_id=stu.id,
                target_entity_type="user",
                target_entity_id=stu.id,
                old_value={"attendance_percent": 82.0},
                new_value={"attendance_percent": 85.0, "condonation_percent": 3.0},
                reason="Medical leave — doctor's note submitted via /student/profile",
            )
        )
        counts["overrides"] += 1
        session.add(
            AdminNotification(
                college_id=college_id,
                event_type="attendance.condonation",
                payload={
                    "student_user_id": str(stu.id),
                    "department_code": FOCAL_DEPT_CODE,
                    "condonation_percent": 3.0,
                },
                created_at=NOW - timedelta(days=RNG.randint(2, 10)),
            )
        )
        counts["notifications"] += 1
    # Mark unlock — one example
    session.add(
        AcademicOverride(
            college_id=college_id,
            override_type=OverrideType.mark_lock_unlock,
            actor_user_id=hod_cse.id,
            target_entity_type="assessment",
            reason="Teacher on leave — HOD unlocked CIE-1 marks to correct a duplicate entry",
        )
    )
    counts["overrides"] += 1

    await session.flush()
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Top-level coordinator
# ─────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    started = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    async with SessionLocal() as session:
        college = await seed_college_and_rbac(session)
        college_id = college.id
        admin_user = await seed_admin(session, college_id)
        terms = await seed_academic_terms(session, college_id)
        depts = await seed_departments(session, college_id)
        rooms = await seed_rooms(session, college_id)
        courses = await seed_courses(session, college_id, depts)
        batches, sections = await seed_batches_sections(session, college_id, depts)
        hods = await seed_hods(session, college_id=college_id, depts=depts)
        teachers = await seed_teachers(session, college_id=college_id)
        students_by_usn, parents_by_usn, students_by_section = (
            await seed_students_and_parents(
                session,
                college_id=college_id,
                sections=sections,
            )
        )
        templates = await seed_scheme_templates(
            session, college_id=college_id, depts=depts
        )
        legacy_users = await seed_legacy_test_users(
            session,
            college_id=college_id,
            teachers=teachers,
            sections=sections,
            current_term=terms[CURRENT_TERM_CODE],
        )
        await session.commit()

    counts["users"] = len(students_by_usn) + sum(len(p) for p in parents_by_usn.values()) + sum(
        len(ts) for ts in teachers.values()
    ) + len(hods) + 1

    # Setups for past + current term, focal batch
    async with SessionLocal() as session:
        past_term = terms[PAST_TERM_CODE]
        current_term = terms[CURRENT_TERM_CODE]
        past_setups, past_off_by_id, past_off_by_course, past_labs = (
            await seed_setup_for_term(
                session,
                college_id=college_id,
                depts=depts,
                hods=hods,
                teachers=teachers,
                batches=batches,
                sections=sections,
                courses=courses,
                templates=templates,
                rooms=rooms,
                term=past_term,
                term_code=PAST_TERM_CODE,
                batch_year=FOCAL_BATCH_YEAR,
                is_current=False,
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        cur_setups, cur_off_by_id, cur_off_by_course, cur_labs = (
            await seed_setup_for_term(
                session,
                college_id=college_id,
                depts=depts,
                hods=hods,
                teachers=teachers,
                batches=batches,
                sections=sections,
                courses=courses,
                templates=templates,
                rooms=rooms,
                term=current_term,
                term_code=CURRENT_TERM_CODE,
                batch_year=FOCAL_BATCH_YEAR,
                is_current=True,
            )
        )
        await session.commit()

    counts["offerings"] = len(past_off_by_id) + len(cur_off_by_id)
    counts["lab_batches"] = sum(len(v) for v in past_labs.values()) + sum(
        len(v) for v in cur_labs.values()
    )

    # Elective groups (current term, CSE + CSE-DS only)
    async with SessionLocal() as session:
        elective_groups_by_dept: dict[str, dict[str, list[ElectiveGroupOption]]] = {}
        for dept_code in ("CSE", "CSE-DS"):
            setup = (
                await session.execute(
                    select(SemesterSetup).where(
                        SemesterSetup.department_id == depts[dept_code].id,
                        SemesterSetup.academic_term_id == current_term.id,
                    )
                )
            ).scalar_one()
            groups = await seed_electives_for_setup(
                session,
                college_id=college_id,
                dept_code=dept_code,
                setup=setup,
                teachers=teachers,
                courses=courses,
                hod=hods[dept_code],
            )
            elective_groups_by_dept[dept_code] = groups
        await session.commit()

    # Enrollments — past term + current term focal-batch + light enrollments
    # for other batches in current term so /admin/users + /student looks
    # plausible everywhere.
    async with SessionLocal() as session:
        past_enrollment_map = await seed_enrollments_for_term(
            session,
            college_id=college_id,
            students_by_section=students_by_section,
            sections=sections,
            term=past_term,
            batch_year=FOCAL_BATCH_YEAR,
            is_current=False,
        )
        # Current-term focal cohort
        cur_enrollment_map = await seed_enrollments_for_term(
            session,
            college_id=college_id,
            students_by_section=students_by_section,
            sections=sections,
            term=current_term,
            batch_year=FOCAL_BATCH_YEAR,
            is_current=True,
        )
        # Light enrollments for other batches in current term.
        for yr in BATCH_YEARS:
            if yr == FOCAL_BATCH_YEAR:
                continue
            await seed_enrollments_for_term(
                session,
                college_id=college_id,
                students_by_section=students_by_section,
                sections=sections,
                term=current_term,
                batch_year=yr,
                is_current=True,
            )
        await session.commit()

    counts["enrollments_past"] = len(past_enrollment_map)
    counts["enrollments_current_focal"] = len(cur_enrollment_map)

    # Register focal-batch electives for CSE + CSE-DS
    async with SessionLocal() as session:
        for dept_code in ("CSE", "CSE-DS"):
            setup = (
                await session.execute(
                    select(SemesterSetup).where(
                        SemesterSetup.department_id == depts[dept_code].id,
                        SemesterSetup.academic_term_id == current_term.id,
                    )
                )
            ).scalar_one()
            # Re-load options from DB (in-session lookup) for the cascade
            opts_by_group: dict[str, list[ElectiveGroupOption]] = defaultdict(list)
            opt_rows = (
                await session.execute(
                    select(ElectiveGroupOption, ElectiveGroup.name).join(
                        ElectiveGroup, ElectiveGroup.id == ElectiveGroupOption.elective_group_id
                    ).where(ElectiveGroup.semester_setup_id == setup.id)
                )
            ).all()
            for opt, gname in opt_rows:
                opts_by_group[gname].append(opt)
            await register_focal_batch_electives(
                session,
                college_id=college_id,
                setup=setup,
                elective_groups_by_dept={dept_code: opts_by_group},
                students_by_section=students_by_section,
                dept_code=dept_code,
                batch_year=FOCAL_BATCH_YEAR,
            )
        await session.commit()

    # Re-load offerings into a fresh session so attendance/marks can scan them
    async with SessionLocal() as session:
        all_offerings = (
            await session.execute(
                select(CourseOffering).where(CourseOffering.college_id == college_id)
            )
        ).scalars().all()
        offerings_by_course_fresh: dict[tuple[str, str], list[CourseOffering]] = defaultdict(list)
        for o in all_offerings:
            offerings_by_course_fresh[(str(o.course_id), str(o.section_id))].append(o)

        # 6 weeks of past sessions for the focal current-term offerings
        cur_sessions, cur_attendance = await seed_class_sessions_and_attendance(
            session,
            college_id=college_id,
            offerings_by_course=offerings_by_course_fresh,
            students_by_section=students_by_section,
            sections=sections,
            rooms=rooms,
            term=current_term,
            is_current=True,
            weeks=6,
            focal_dept_only=True,
        )
        # 14 weeks for the past term focal cohort
        past_sessions, past_attendance = await seed_class_sessions_and_attendance(
            session,
            college_id=college_id,
            offerings_by_course=offerings_by_course_fresh,
            students_by_section=students_by_section,
            sections=sections,
            rooms=rooms,
            term=past_term,
            is_current=False,
            weeks=14,
            focal_dept_only=True,
        )
        await session.commit()

    counts["class_sessions"] = cur_sessions + past_sessions
    counts["attendance_records"] = cur_attendance + past_attendance

    # Assessments + marks
    async with SessionLocal() as session:
        all_offerings = (
            await session.execute(
                select(CourseOffering).where(CourseOffering.college_id == college_id)
            )
        ).scalars().all()
        offerings_by_course_fresh = defaultdict(list)
        for o in all_offerings:
            offerings_by_course_fresh[(str(o.course_id), str(o.section_id))].append(o)
        cur_a, cur_m = await seed_assessments_and_marks(
            session,
            college_id=college_id,
            offerings_by_course=offerings_by_course_fresh,
            students_by_section=students_by_section,
            sections=sections,
            term=current_term,
            is_current=True,
            focal_dept_only=True,
        )
        past_a, past_m = await seed_assessments_and_marks(
            session,
            college_id=college_id,
            offerings_by_course=offerings_by_course_fresh,
            students_by_section=students_by_section,
            sections=sections,
            term=past_term,
            is_current=False,
            focal_dept_only=True,
        )
        await session.commit()

    counts["assessments"] = cur_a + past_a
    counts["marks"] = cur_m + past_m

    # SEE + hall tickets + grade cards (past term)
    async with SessionLocal() as session:
        all_offerings = (
            await session.execute(
                select(CourseOffering).where(CourseOffering.college_id == college_id)
            )
        ).scalars().all()
        offerings_by_course_fresh = defaultdict(list)
        for o in all_offerings:
            offerings_by_course_fresh[(str(o.course_id), str(o.section_id))].append(o)
        see_counts = await seed_see_and_grade_cards(
            session,
            college_id=college_id,
            enrollment_map=past_enrollment_map,
            offerings_by_course=offerings_by_course_fresh,
            students_by_usn=students_by_usn,
            students_by_section=students_by_section,
            sections=sections,
            term=past_term,
            hods=hods,
            courses=courses,
        )
        await session.commit()
    counts.update(see_counts)

    # CIE schedule + deadlines + tasks + overrides
    async with SessionLocal() as session:
        all_offerings = (
            await session.execute(
                select(CourseOffering).where(CourseOffering.college_id == college_id)
            )
        ).scalars().all()
        offerings_by_course_fresh = defaultdict(list)
        for o in all_offerings:
            offerings_by_course_fresh[(str(o.course_id), str(o.section_id))].append(o)
        # CIE schedule only for focal-dept current-term offerings
        cse_offerings_only: dict[tuple[str, str], list[CourseOffering]] = defaultdict(list)
        for k, offs in offerings_by_course_fresh.items():
            cse_offerings_only[k] = [
                o for o in offs
                if o.academic_term_id == current_term.id
                and any(
                    sect.id == o.section_id
                    for (dc, yr, _sn), sect in sections.items()
                    if dc == FOCAL_DEPT_CODE
                )
            ]
        cie_count = await seed_cie_schedule(
            session,
            college_id=college_id,
            offerings_by_course=cse_offerings_only,
            rooms=rooms,
            term=current_term,
        )
        counts["cie_schedule"] = cie_count

        dt_counts = await seed_deadlines_tasks_overrides(
            session,
            college_id=college_id,
            admin_user=admin_user,
            hods=hods,
            teachers=teachers,
            students_by_section=students_by_section,
            depts=depts,
            term=current_term,
        )
        counts.update(dt_counts)
        await session.commit()

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    _print_summary(counts, elapsed)


def _print_summary(counts: dict[str, int], elapsed: float) -> None:
    banner("Metis demo seed complete.")
    print(f"Took {elapsed:.1f}s.")
    print()
    print("Row counts:")
    for k, v in counts.items():
        print(f"  {k:<32} {v:>10,}")
    print()
    banner("Login credentials (password: MetisDemo!2026)")
    print(f"  admin@bmsce.ac.in                Admin")
    # The focal HOD email is the legacy address (`hod@`) so the existing
    # pytest fixtures keep finding the CSE HOD. Other HODs follow the
    # `hod-{dept}@` convention.
    print(f"  hod@bmsce.ac.in                  HOD CSE (focal dept)")
    for dept_code, *_ in DEPT_SPECS:
        if dept_code == FOCAL_DEPT_CODE:
            continue
        print(f"  {hod_email(dept_code):<32} HOD {dept_code}")
    print(f"  {teacher_email('CSE', 1):<32} Teacher in CSE")
    focal_usn = make_usn(
        FOCAL_BATCH_YEAR % 100,
        dict((d[0], d[2]) for d in DEPT_SPECS)[FOCAL_DEPT_CODE],
        1,
    )
    print(f"  {student_email(focal_usn):<32} CSE 2023 batch student #1 (USN {focal_usn})")
    print(f"  {parent_email(focal_usn, 1):<32} Parent of above")
    print(f"  teacher@bmsce.ac.in              Legacy test fixture (CSE-adjacent)")
    print(f"  student@bmsce.ac.in              Legacy test fixture (CSE 2024-A enrollment)")
    print()
    banner("Suggested walkthrough order")
    print(
        "  /admin/users               — see ~5,000 users with USN+role filters\n"
        "  /admin/academic            — departments, courses, batches, sections,\n"
        "                                offerings, rooms\n"
        "  /admin/notifications       — publish events + condonations + dissolved\n"
        "  /admin/internal-deadlines  — institutional hard stop + dept-soft rows\n"
        "  /hod/dashboard             — CSE HOD's view (login as hod-cse)\n"
        "  /hod/semester-setup        — published-active setup for 2026-Odd\n"
        "  /hod/electives             — healthy / under-strength / dissolved options\n"
        "  /hod/lab-batches           — integrated CSE offerings, batches A/B/C\n"
        "  /hod/scheme-templates      — institutional + dept-owned templates\n"
        "  /hod/cie-schedule          — CIE-1 published past, CIE-2 published future\n"
        "  /hod/tasks                 — 9 tasks across pending/accepted/done/declined\n"
        "  /hod/hall-tickets          — past-term tickets HOD-approved\n"
        "  /hod/see-upload            — past-term SEE results, supersede chain visible\n"
        "  /hod/re-eval               — improved + held re-eval rows\n"
        "  /teacher/courses           — login as teacher-cse-1, see assigned offerings\n"
        "  /student/dashboard         — login as the focal student\n"
        "  /student/registration      — mandatory + elective picks (window closed)\n"
        "  /student/hall-ticket       — focal-term ticket download\n"
        "  /student/grade-card        — focal student v2 (late SEE release)\n"
        "  /parent/dashboard          — login as parent-1bm23cs001-1\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
