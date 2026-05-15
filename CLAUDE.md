# CLAUDE.md — Metis Project Intelligence File

> Single source of truth for Claude Code sessions. Paste this file at the start of every session.
> Update the MODULE STATUS TABLE and ACTIVE MODULE STATE after every session.

---

## HOW TO USE THIS FILE

1. **Starting a session**: Tell Claude which module you're working on and paste this file. Claude reads module status, picks up where you left off, and brainstorms before writing code.
2. **Session contract**: Every session ends with runnable code — routes registered, UI screens navigable, no broken imports — even if features are stubs.
3. **Ending a session**: Ask Claude to "update the module state block" and paste the output back into this file.
4. **Brainstorm mode**: Say "let's brainstorm [module]" and Claude asks clarifying questions before writing code.
5. **Frontend-as-we-go**: Every session ships complete UI for its backend. No "backend now, UI later."
6. **No Claude attribution in commits**: Commits are authored as the developer. No `Co-Authored-By: Claude` lines. No "Generated with Claude Code" footers. Enforced by git config and reinforced per-session.

---

## PROJECT SNAPSHOT

```
PROJECT: Metis — AI-Native University Operating System
TARGET:  BMS College of Engineering, Bangalore (scales to all Indian engineering colleges)
BUILDER: Final-year CS (Data Science) student | Strong in ML/AI/data pipelines
TIMELINE: Full platform first, AI layer last
BUDGET:  Zero — free tiers only. Every infra decision must run free.
COMPLIANCE: DPDP Act 2023 — face biometric data never persisted to disk.
CODE STANDARD: Production-grade. Every file must be explainable in a technical interview.
REGULATIONS: Aligned with BMSCE academic rules — see "BMSCE REGULATIONS ANCHOR" section.
```

---

## WHAT METIS IS

- Role-based web platform: **Admin / HOD / Teacher / Student / Parent**
- **Academic Workflow Engine**: Department-driven, HOD-owned, admin-as-safety-net
- **Smart Attendance**: QR + GPS + face verification (face is M8-pluggable, stubbed until then)
- **Assessment + Grade Engine**: Flexible CIE/SEE schemes, NPTEL handling, eligibility, hall tickets, grade cards
- **Communication**: Announcements, DMs, notifications, per-post parent visibility
- **Content Management**: Material uploads (M7 RAG hooks ready, consumer deferred)
- **AI Layer (deferred)**: Learning Engine (M7) + Insights/Face (M8) — events already publishing, consumers plug in when built

## WHAT METIS IS NOT

- Generic ERP or SAP clone
- Basic CRUD portal
- Prototype — everything written to be deployable and defensible

---

## THE FIVE ROLES (AUTHORITY DISTRIBUTION)

The system is **HOD/teacher-centric**. Admin is the institutional safety net, not the routine operator.

### Admin
- Institutional invariants only: rooms (cross-department), academic calendar (term boundaries), holiday calendar, user bulk onboarding, assessment scheme **catalog** (templates), institutional eligibility thresholds, SEE date scheduling, feature flags, audit log visibility, AICTE compliance reports, system health
- Approves **only** when curriculum changes (new credit-bearing course mid-semester) or institution-wide policy exceptions
- Cannot edit HOD-drafted semester structure on their behalf
- Lightweight notification feed: cross-department resource conflicts, manually-flagged escalations, HOD publish events (informational)

### HOD (Head of Department)
- One per department; can additionally teach (uses `/teacher/*` for own offerings)
- Drafts and **self-publishes** semester structure (admin sees but doesn't approve)
- Designs elective groups, dissolves low-strength electives, migrates students
- Composes lab batches (flexible count — 2, 3, 5, whatever fits)
- Assigns teachers to courses (including cross-department, no admin approval — routine practice)
- Configures CIE schedules (dates, timings, order, venues) within institutional CIE windows
- Approves AAT weight >20% (BMSCE rule)
- Condones attendance up to 10% (BMSCE rule)
- Generates and approves hall tickets for own department (batch operation)
- Uploads SEE marks via CSV; uploads re-evaluation revised marks
- Authorises makeup CIE (rare) and makeup exam workflows
- Assigns tasks (invigilation, paper setting, evaluation duties) to department teachers
- Bulk-onboards parents via CSV for own department
- Sees department analytics, defaulter lists, eligibility status

### Teacher
- Owns day-to-day: attendance, marks, assignments, materials per offering
- Configures per-offering assessment scheme within HOD/admin templates
- Can edit attendance freely until internal deadline; HOD edits after deadline
- Can freeze own course early (per-course freeze, before institutional deadline)
- Can lock/unlock own marks (HOD is backup if teacher unavailable)
- Per-post parent visibility toggle on assignments, announcements, marks publications
- Composes lab batch incharges for integrated courses (HOD overrides if needed)
- Sees roster, student details, private teacher notes (not student-visible)
- NPTEL coordinator role: same teacher role, with an NPTEL offering assigned — coordinator's UI surfaces in `/teacher/courses/{offering_id}` when offering type is NPTEL

### Student
- Identified by **USN** (BMSCE pattern: `1BM` + 2-digit year + 2-letter dept + 3-digit roll, e.g., `1BM23CS001`)
- Registers for courses (mandatory auto-enrolled, electives selected, NPTEL slot selected with specific NPTEL course name)
- Views attendance, marks (with dynamic scheme rendering), assignments, materials, eligibility
- Downloads hall ticket (PDF, re-downloadable)
- Downloads grade card (PDF, multi-version, re-downloadable indefinitely)
- Sees backlog courses (failed/ineligible) auto-added to next semester
- Submits assignments (portal mode) or sees grade for offline-mode assignments
- Requests re-evaluation within HOD-set window

### Parent
- Strictly read-only on linked child(ren)
- Onboarded via admin/HOD CSV upload (Google Form → CSV → bulk parent account creation)
- Linked to student by **USN** in the CSV
- Sees attendance, marks, eligibility, assignments (only when teacher toggled "visible to parents" per post)
- Multiple children supported (up to 2 parent accounts per student — typically mother + father; or 1 guardian)
- Cannot see other students' data; API enforces parent-child link per request

---

## BMSCE REGULATIONS ANCHOR

Institutional rules baked into the eligibility engine and assessment workflows. All thresholds are configurable via `/admin/eligibility-config` but default to BMSCE policy.

### Attendance
- **85%** minimum in each course to qualify for main SEE (theory, lab, integrated separately)
- **60%** minimum per-CIE attendance to qualify for that CIE
- **HOD/Principal/Dean** can condone up to **10%** with documented reason
- **Make-up SEE**: requires 85% attendance also (no separate lower threshold)

### Internal Marks
- **40%** minimum in CIE to qualify for main SEE
- **60%** minimum in CIE to qualify for make-up SEE
- For integrated courses: threshold required **separately in theory AND practical** AND overall

### CIE Structure (default, configurable per scheme template)
- **3 internal tests**, **best 2 of 3** counted
- Default pattern: Test 1 + Test 2 = 80% of CIE; **AAT** = 20% (extendable to 40% with HOD approval)
- Total CIE = 50 marks (reduced from 100-mark internal pattern); SEE = 50 marks (reduced from 100)
- Missed CIE recorded as absent → automatically dropped via best-2-of-3 (no approval needed)
- Makeup CIE for rare cases (missed 2 of 3 with genuine reason) — HOD authorises

### SEE
- Conducted out of 100, rescaled proportionally to 50
- Admin schedules SEE dates (cross-department coordination)
- SEE marks often released semester(s) later — uses transitional grade `I` (incomplete) until released, displayed as "Pending" in UI
- HOD uploads via CSV when results land
- Re-evaluation: standard rule — **can only improve or hold, never reduce** marks

### Grade Card
- Generated at end of each semester per student
- Pending courses (SEE not released) show grade `I` with "Pending" label in UI
- Multi-version: re-evaluation, makeup completion, or late SEE release regenerates with new version
- Re-downloadable indefinitely; old versions retained

### NPTEL Courses (MOOC type)
- Course type: `nptel`
- One faculty assigned as **NPTEL Coordinator** per NPTEL slot per semester
- Students pick which specific NPTEL course (free-text course name field) within the slot
- Coordinator defines mark split (e.g., 40% assignments / 60% final exam) — applies uniformly to all students under the slot regardless of which specific NPTEL course they took
- No attendance tracking
- Student uploads NPTEL certificate as evidence; coordinator verifies + enters marks
- Pending if not completed in semester; can carry to next semester (retake until passed)
- Always visible on student dashboard until passed; appears on grade card of the semester they cleared it

### Hall Ticket
- Generated by system at end of internal deadline, batch-approved by HOD
- Shows per-subject eligibility status; ineligible subjects show **NA**
- One-time-generated PDF (re-downloadable but identical); student prints physical copy for exam hall
- Ineligible due to attendance OR <40% internals → must re-register course next semester

### Backlog Path (failed or ineligible)
- Auto-added to next semester's registration with `backlog` badge
- Must write makeup exam (separate assessment flow)
- Makeup result appears on grade card of the semester they cleared it
- Schema-ready for BMSCE Fast Track Semester (8-week backlog semester) — deferred from MVP

---

## AUTHORITY DISTRIBUTION (COMPLETE TABLE)

| Action | Admin | HOD | Teacher |
|---|---|---|---|
| Institutional eligibility thresholds | ✅ owner | — | — |
| Academic term boundaries | ✅ owner | — | — |
| Holiday calendar (institutional) | ✅ owner | adds dept events | — |
| Room CRUD (with GPS) | ✅ owner | — | — |
| Bulk user onboarding (CSV) | ✅ owner | adds individuals | — |
| Assessment scheme catalog (templates) | ✅ owner | adds dept-specific | picks per offering |
| Parent CSV onboarding | ✅ owner | own dept | — |
| Add credit-bearing course mid-sem | ✅ owner | — | — |
| SEE date scheduling | ✅ owner | — | — |
| Audit log viewer | ✅ owner | own dept scope | — |
| Semester structure draft + self-publish | sees, doesn't approve | ✅ owner | — |
| Elective groups design | — | ✅ owner | — |
| Elective dissolution + student migration | — | ✅ owner | — |
| Lab batch composition (flexible count) | — | ✅ owner | composes own course |
| Lab batch incharge assignment | — | ✅ overrides | ✅ assigns |
| Teacher-to-course assignment | — | ✅ direct | — |
| Cross-dept teacher assignment | — | ✅ direct, notifies other HOD | — |
| CIE date/time/venue scheduling | — | ✅ owner | — |
| Institutional CIE windows | ✅ broad window | — | — |
| AAT weight 0–20% | — | — | ✅ free |
| AAT weight 20–40% | — | ✅ approves | requests |
| Attendance condonation 0–10% | — | ✅ owner | flags only |
| Attendance condonation >10% | ✅ exceptional | — | — |
| Internal deadline (institutional hard stop) | ✅ owner | — | — |
| Internal deadline (dept soft target) | — | ✅ owner | — |
| Per-course freeze | — | overrides | ✅ owner |
| Attendance edit pre-deadline | — | — | ✅ free |
| Attendance edit post-deadline | — | ✅ with reason | — |
| Mark lock/unlock | — | unlocks if teacher unavailable | ✅ owner |
| Per-offering assessment scheme | — | overrides | ✅ within template |
| Hall ticket generation + approval | sees | ✅ batch-approves own dept | — |
| SEE marks CSV upload | own dept fallback | ✅ owner | — |
| Re-evaluation marks upload | — | ✅ owner | — |
| Makeup CIE authorisation | — | ✅ owner | conducts |
| Makeup exam authorisation | — | ✅ owner | conducts |
| Grade card generation trigger | — | ✅ triggers | — |
| Task assignment (invigilation etc.) | rare cross-dept | ✅ owner | accepts/declines |
| Per-post parent visibility | — | — | ✅ owner per post |
| Backlog auto-registration | — | sees, can override | — |

---

## FRONTEND PHILOSOPHY — FULL PLATFORM, MINIMAL POLISH

```
PHASE: Bare-bones functional UI. Every feature works. Zero design polish.
LATER: Visual redesign AFTER all features verified.

UI RULES (non-negotiable):
  ✅ Every feature in screen inventory MUST be present and functional
  ✅ shadcn/ui base components only (or hand-rolled shadcn-style primitives in apps/web/components/ui.tsx)
  ✅ Simple top nav + sidebar + content area
  ✅ No custom palettes, gradients, animations
  ✅ Tables for tabular, forms for input, cards for grouped info
  ✅ Every button does something (calls real or stub endpoint)
  ✅ Every form validates (react-hook-form + zod) and submits
  ✅ Loading: simple spinner or "Loading…"; errors: plain red text
  ✅ Mobile responsive enough not to break

UI NON-GOALS:
  ❌ Color schemes / brand identity
  ❌ Custom components when shadcn-style exists
  ❌ Hover effects, transitions, micro-interactions
  ❌ Design mockup matching
  ❌ Refactoring working UI for aesthetics

FRONTEND-AS-WE-GO RULE:
  Every backend endpoint shipped in a session has its UI wired and functional in the same session.
  No "backend now, frontend later" — that creates broken module states.
```

---

## ARCHITECTURE — 6 LAYERS

```
L1  CLIENT      /admin /hod /teacher /student /parent sub-apps
                → Next.js 14 App Router

L2  GATEWAY     API Gateway | WebSocket | Auth Service
                → Single entry; auth validated before forward

L3  CORE SVCS   M1 Users | M2 Academic | M3 Attendance | M4 Marks |
                M5 Comms | M6 Content | M9 Admin | M10 Workflow | M11 Assignments
                → FastAPI modular routers; REST internally; Redis pub/sub async

L4  AI LAYER    M7 Learning Engine | M8 Insights + Face Verify | LLM Orchestrator
                → DEFERRED. Stubs in place. Events publishing. Consumers plug in when ready.

L5  DATA        PostgreSQL (Supabase) | Qdrant (deferred — M7) | NetworkX→Neo4j (deferred — M7) |
                Redis (cache/queue/pub-sub) | Cloudflare R2 (files)

L6  INFRA       Vercel (frontend) | Render (backend) | Railway (AI services, when active) |
                Sentry | Grafana Cloud
```

---

## TECH STACK

| Layer | Technology | Why | Free Tier |
|---|---|---|---|
| Backend | FastAPI (Python) | Async, OpenAPI, Pydantic, ML-compatible | Yes |
| Frontend | Next.js 14 App Router | RSC, file routing, PWA, Vercel | Yes |
| Styling | Tailwind + shadcn-style primitives | Bare-bones MVP | Yes |
| DB | PostgreSQL (Supabase) | RLS, 500MB free | Yes |
| Vector DB | Qdrant (deferred) | M7-only | Yes |
| Cache/Queue/PubSub | Redis (Upstash) | Event bus, TTL, BullMQ | Yes |
| File storage | Cloudflare R2 | S3-compat, free egress, 10GB | Yes |
| Embeddings | sentence-transformers MiniLM-L6-v2 (deferred) | M7-only | Always free |
| Face verify | DeepFace FaceNet (deferred, M8) | CPU-capable, stubbed for now | Always free |
| LLM (deferred) | Gemini 1.5 Flash → Groq → Ollama | M7/M8-only | Yes |
| PDF generation | reportlab or weasyprint | Hall tickets, grade cards | Free |
| Auth | JWT 15min + refresh 7d | Stateless | — |
| Jobs | BullMQ on Redis | Background tasks | — |

---

## EVENT BUS — INTER-MODULE COMMUNICATION (BUILT IN M10)

Redis pub/sub. M10 ships the bus. All M1–M4 `TODO(events)` markers get wired during M10d.

```
Sync:   REST internal calls
Async:  Redis pub/sub (no module imports another's models)

Event                                  Publisher    Subscribers
────────────────────────────────────────────────────────────────────
user.enrolled                          M1           M2, [M7 when live]
user.role_changed                      M1           M9 audit
timetable.updated                      M2           M3 materialiser
session.created                        M2           M3
semester_setup.published               M10          M9 audit, M5 announce
elective.dissolved                     M10          M3, M4, M11 cascades
student.migrated                       M10          M3, M4, M11 cascades
student.needs_intervention             M10          M5 notify (audit Session 4)
lab_batch.composed                     M10          M3, M4
lab_batch.reassigned                   M10          M3, M4, M5 notify
assessment.scheme_configured           M10/M4       M9 audit
internal_deadline.crossed              M10          M3 freeze, M4 freeze
attendance.marked                      M3           [M8 when live], M9 analytics
attendance.overridden                  M3           M9 audit
attendance.eligibility_crossed         M3           M5 notify, [M8 when live]
marks.entered                          M4           [M8 when live], M9 analytics
marks.locked / marks.unlocked          M4           M9 audit
see.marks_released                     M10/M4       M5 notify, grade_card.regenerate
re_evaluation.completed                M10/M4       grade_card.regenerate
makeup.completed                       M10/M4       grade_card.regenerate
hall_ticket.generated                  M10          M5 notify
grade_card.regenerated                 M10/M4       M5 notify
assignment.created                     M11          M5 notify
assignment.submitted                   M11          M5 notify, [M8 when live]
assignment.graded                      M11          M4 AAT linkage, M5 notify
material.uploaded                      M6           [M7 when live]
notification.queued                    M5           delivery workers
task.assigned                          M10          M5 notify
parents.bulk_onboarded                 M10/M9       M5 notify (welcome emails)
```

---

## DATA LAYER RULES

```
Multi-tenancy:    Every table has college_id. Queries always WHERE college_id = ?
Soft deletes:     deleted_at TIMESTAMP NULL. Filter WHERE deleted_at IS NULL.
Audit trail:      Sensitive writes → audit_logs (actor_id, action, old_val, new_val, ts)
Typed overrides:  academic_overrides table (typed semantic actions: condonations, migrations, unlocks)
Timestamps:       created_at TIMESTAMPTZ DEFAULT NOW(), updated_at auto-trigger
USN:              Students identified by USN (BMSCE pattern: 1BM + YY + DD + RRR). Validated at create.
Face data:        NEVER stored. Only verification_confidence FLOAT in attendance_records.
Naming:           snake_case. FKs: {table_singular}_id.
SEE versioning:   see_results table — original + optional re_eval + optional makeup, each timestamped.
Grade cards:      grade_card_versions table — old PDFs retained, latest pointer.
```

---

## REPO STRUCTURE

```
metis/
├── apps/
│   └── web/                          Next.js 14
│       ├── app/
│       │   ├── (admin)/              admin sub-app
│       │   ├── (hod)/                HOD sub-app (NEW — ships in M2 rework)
│       │   ├── (teacher)/            teacher sub-app
│       │   ├── (student)/            student sub-app
│       │   └── (parent)/             parent sub-app
│       └── components/
├── services/
│   ├── api/                          FastAPI main backend
│   │   ├── app/
│   │   │   ├── modules/
│   │   │   │   ├── users/            M1 ✅
│   │   │   │   ├── academic/         M2 (rework)
│   │   │   │   ├── workflow/         M10 (NEW)
│   │   │   │   ├── attendance/       M3 (rework)
│   │   │   │   ├── marks/            M4 (rework)
│   │   │   │   ├── assignments/      M11 (NEW)
│   │   │   │   ├── comms/            M5
│   │   │   │   ├── content/          M6
│   │   │   │   └── admin/            M9
│   │   │   └── core/                 shared DB, auth, config, event_bus, eligibility
│   │   └── alembic/
│   ├── learning-engine/              M7 scaffold — empty FastAPI /health
│   └── insights-engine/              M8 scaffold — empty FastAPI /health
├── infra/
│   ├── docker/
│   └── scripts/
├── docs/
│   ├── adr/
│   └── modules/                      M10.md, M11.md (per-module specs)
└── tests/
```

---

## MODULE STATUS TABLE

> Update at the end of every session.

| Module | Status | Skeleton Live? | Features Done | Blocked By |
|---|---|---|---|---|
| M1 User Service | 🟢 Complete | Yes | All endpoints + auth + RBAC + Google OAuth + invite flow + (M2 rework) HOD role + bulk-CSV + /users list + /users/{id}/status | — |
| M2 Academic Service | 🟢 Rework complete | Yes (v1 + 22 new tables in 0007–0009, applied) | M2 rework: USN backfill, HOD role + canonical link, academic_terms, semester_setups, elective_groups, lab_batches, schemes (per-offering + 3 institutional templates), NPTEL, internal_deadlines, cie_schedule, tasks, hall_tickets, grade_cards, see_results, re_evaluations, academic_overrides, eligibility_snapshots, course_drops. **Migrations 0007–0012 applied locally and verified.** | — |
| M3 Attendance Service | 🟠 Rework pending | Yes (v1) | v1 shipped; rework adds: eligibility engine, 60%/85% thresholds, deadline freeze integration | M2 rework |
| M4 Marks Service | 🟠 Rework pending | Yes (v1) | v1 shipped; rework adds: scheme integration, NPTEL grading, SEE versioning, grade cards, re-eval, makeup | M2 rework, M10 |
| M5 Comms Service | 🔴 Not started | No | — | M1, M2 rework, M10 event bus |
| M6 Content Service | 🔴 Not started | No | — | M1, M2 rework |
| M9 Admin Portal + Analytics | 🔴 Not started | No | — | All others |
| M10 Academic Workflow | 🟢 Complete (M10a–e) | Yes (workflow module live) | M10a: SemesterSetup CRUD + self-publish + admin_notifications + event bus publisher. M10b: registration window, student elective registration, HOD elective dissolution + cascade (course_registrations + enrollments cross-section + lab_batch_members + academic_overrides in one transaction), manual migrate, capacity cap, dissolve preview, /student/dashboard + /student/registration + /hod/electives. M10c: lab batches (CRUD + members + auto-compose round-robin + incharges with HOD-override audit), per-offering scheme picker (template / clone / custom; teacher AAT ≤20%, HOD pushes to 40% with academic_overrides; lock = teacher, unlock = HOD; integrated lab side inherits from parent), dept scheme templates, /hod/lab-batches + /hod/scheme-templates + /teacher/courses/[id]/scheme + /hod/dashboard scheme-readiness card. M10d: internal deadlines (admin/HOD/teacher own institutional_hard/department_soft/per_course_freeze), CIE scheduling per offering with HOD-publish + ordering, tasks (HOD assigns dept-only, accept/decline/complete state machine), real Redis subscriber framework (psubscribe loop + in-process handler registry + admin_notifications writer for internal_deadline.crossed), /hod/cie-schedule + /hod/tasks + /teacher/tasks + /admin/internal-deadlines. M10e: eligibility engine (attendance ≥85% + CIE ≥40% from M3 v1 + M4 v1 sources), hall tickets (per-student + dept-batch generate + HOD approve + version regenerate + reportlab PDF render), SEE CSV upload + supersede chain, re-evaluation (student request within window + HOD CSV upload with improve-or-hold), makeup (HOD authorize + CSV upload), grade cards (auto-regenerate on SEE/re-eval/makeup with trigger_reason versions + SGPA + grade bands), /hod/hall-tickets + /hod/see-upload + /hod/re-eval + /hod/makeup + /student/hall-ticket + /student/grade-card + /student/re-eval. M10 complete; unblocks M3+M4 rework. | — |
| M11 Assignments | 🔴 Not started | No | NEW MODULE — assignments, portal+offline modes, AAT linkage, parent visibility | M2 rework, M10, M6 |
| M7 Learning Engine | ⚫ Deferred | No (scaffold) | AI layer — built last; integration points ready | scaffold exists |
| M8 Insights + Face Verify | ⚫ Deferred | No (scaffold) | AI layer — built last; M3 face-verify stub swappable | scaffold exists |

**Status legend**: 🔴 Not started · 🟡 Skeleton live · 🟠 Rework pending · 🟢 Complete · ⚫ Deferred

---

## BUILD SEQUENCE

**Phase A — Academic Refoundation**
1. **M2 rework** — schema additions (migrations 0007/0008/0009), USN backfill, HOD role, light UI updates (USN-aware admin pages, empty HOD shell)
2. **M10a — Semester Setup + Approval** — HOD draft/publish flow, admin notification feed
3. **M10b — Elective Registration + Dissolution + Cascade**
4. **M10c — Lab Batches + Assessment Scheme Templates + per-offering picker**
5. **M10d — CIE Scheduling + Tasks + Internal Deadlines + Event Bus (Redis pub/sub built here)**
6. **M10e — Hall Tickets + Grade Cards + SEE/Re-eval/Makeup workflows**
7. **M3 rework** — eligibility engine, freeze integration
8. **M4 rework** — scheme integration, NPTEL coordinator UI, grade cards, re-eval/makeup paths

**Phase B — Assignments + Communications**
9. **M11 — Assignments** — full lifecycle, portal+offline, AAT linkage, parent visibility per post
10. **M5 — Communications** — announcements, DMs, notification queue, parent notification fan-out

**Phase C — Content + Admin**
11. **M6 — Content** — uploads, library, versioning; **publishes `material.uploaded` events** (no consumer yet)
12. **M9 — Admin Portal + Analytics** — bulk onboarding, audit viewer, AICTE reports, system health, feature flags

**Phase D — Polish + Deploy**
13. E2E tests, DPDP audit, performance, production deploy

**Phase E — AI Layer (when ready)**
14. **M7 — Learning Engine** — consumes M6 events; tutor UI already exists, point at backend
15. **M8 — Insights + Face Verify** — consumes M3/M4 events; swaps M3 face stub; insights UI already exists

---

## AI DEFERRAL — INTEGRATION POINTS

See `AI_DEFERRAL_PLAN.md` for the full inventory. Summary:

- **M3 face-verify**: `app/modules/attendance/face_stub.py` returns 0.95 confidence. M8 swaps the implementation; signature stable.
- **M6 material upload**: publishes `material.uploaded`. M7 subscribes and ingests when built.
- **M3/M4 events**: `attendance.marked`, `marks.entered`, `assignment.submitted`, `student.migrated` all publish. M8 subscribes for risk scoring.
- **Teacher insights UI**: `/teacher/insights` ships with empty state — "Insights Engine not yet enabled."
- **Student tutor UI**: `/student/tutor` ships as placeholder route — "Tutor coming soon."
- **AI service scaffolds**: `services/learning-engine/` and `services/insights-engine/` are minimal FastAPI apps with `/health` endpoints. Deployment topology correct from day one.

**Core academic logic NEVER depends on M7/M8.** Everything in M1–M6, M9–M11 is fully functional without the AI layer.

---

## SESSION PROTOCOL

### Starting a session

```
Tell Claude:
  "I am working on [MODULE NAME]. Here is CLAUDE.md. [paste file]"

Claude will:
  1. Read MODULE STATUS TABLE — identify state
  2. Read ACTIVE MODULE STATE block
  3. Open with: "Before I write any code, let me confirm the plan..."
  4. Brainstorm/refine (questions, edge cases)
  5. Write session plan: skeleton vs full
  6. Build — schema first, event contracts first, then service, then UI
  7. End with runnable code + updated state block to paste back
```

### Session contract (Claude must honour)

```
✅ Schema migrations written and applied before service code
✅ Event publish/subscribe wired before business logic (post-M10)
✅ Frontend-as-we-go: every endpoint shipped has UI wired this session
✅ Skeleton rule: module router/pages registered, returning 200/placeholder, no broken imports
✅ Brainstorm before code: at least 3 clarifying questions answered
✅ One module per session: no bleeding into adjacent modules
✅ Update state block at end
✅ shadcn/ui or apps/web/components/ui.tsx primitives only
✅ react-hook-form + zod for all forms
✅ Real or stub endpoint calls, never hardcoded fake JSX arrays
✅ Loading: "Loading…" or spinner; errors: plain red text

❌ No Co-Authored-By: Claude lines in commits
❌ No "Generated with Claude Code" footers
❌ No custom palettes, animations, transitions
❌ No design mockup matching
❌ No deferring frontend work to a later session
```

### Commit message format

```
feat(workflow): add HOD semester setup draft/publish flow
fix(marks): correct best-2-of-3 when student missed CIE-3
chore(schema): add USN column to users with backfill
docs(adr): ADR-010 — assessment scheme catalog vs per-offering rules
```

No Claude attribution. Verify before pushing:
```bash
git log -1 --format='%an %ae'    # should show YOUR name, NOT Claude
git log -1 --format='%B'         # should NOT contain "Co-Authored-By: Claude" or "Generated with Claude Code"
```

---

## ACTIVE MODULE STATE

> Updated by Claude at the end of every session. Paste back into this file.

```yaml
last_updated: "2026-05-15"
active_module: audit_session_5_attendance_eligibility_surface

# Local DB head stays at 0014 — Session 5 is a pure consumer of the
# existing M10e eligibility engine, no schema changes. Adds
# GET /attendance/me/eligibility-summary plus per-course cards on the
# student attendance page. Pytest suite at 182 (Session 1: +3 gating;
# Session 2: +10 ad-hoc endpoint; Session 3: +3 net new task tests;
# Session 4: +13 ranked-prefs cascade + 6 existing-tests-rewritten;
# Session 5: +6 eligibility-summary tests). Boot order:
#   docker compose -f infra/docker/docker-compose.yml up -d
#   cd services/api && uv run alembic upgrade head
#
# Audit Sessions 1–5 shipped. The audit rework plan lives in
# AUDIT_FINDINGS.md at repo root; Session 6 closes the cycle.
#
# Audit closures from the walkthrough that needed no code:
# - B1: teacher manual attendance already ships in /teacher/attendance
#   (per-student "Mark present" button at lines 366–389 + override
#   endpoint). No change required.
# - Finding 19: git dual-remote (origin pushes to both Prajwalkiran1
#   and deepthi-sm) verified working in the audit. The "14 commits in
#   deepthi's repo" the user saw was a stale GitHub UI cache.
#
# Next session unblocks the M3 rework (eligibility engine refactor +
# 60%/85% threshold integration + freeze-deadline guards) followed by
# M4 rework (assessment_schemes-driven marks computation, NPTEL grading,
# SEE versioning consumed from M10e). The audit-rework cycle (Sessions
# 1–6) runs in parallel with the M3/M4 work — see AUDIT_FINDINGS.md.

module_states:

  M1_user_service:
    status: complete
    skeleton_live: true
    m2_rework_deltas:
      - "UserRole enum + Postgres user_role enum: added 'hod'"
      - "User.hod_of_department_id UUID NULL (canonical HOD↔dept link)"
      - "departments.head_user_id still present but DEPRECATED — code reads from users.hod_of_department_id going forward"
      - "USN length stays VARCHAR(40) from baseline; format CHECK in 0009 enforces 1BM+YY+DD+RRR"
      - "New endpoints: GET /users (admin paginated), PATCH /users/{id}/status, POST /users/bulk-csv (dry-run + commit)"
      - "PATCH /users/{id}/role now accepts hod_of_department_id; enforces one-HOD-per-dept at service layer"
      - "New deps: require_hod, require_hod_or_admin, require_teacher_hod_or_admin, require_dept_scope"
    known_issues_inherited:
      - "Refresh-token reuse detection not implemented (rotate+revoke only)"
      - "Access token in localStorage — XSS exposure; needs hardening"
      - "No MFA / passkeys"
      - "FACE_ENROLLMENT_MIN_AGE not enforced"

  M2_academic_service:
    status: rework_complete
    skeleton_live: true
    v1_shipped: "see CLAUDE-v1-archive.md — 10 tables, all endpoints, admin /admin/academic six-tab page"
    migrations_written:
      - "0007 additive: 22 new tables, 9 new enums, course_type enum rewritten (core/elective/lab → theory/lab/integrated/nptel), new columns on users/course_offerings/enrollments/guardian_links/marks/academic_terms"
      - "0008 backfill: academic_terms from VARCHAR codes, USNs for students, hod_of_department_id from departments.head_user_id, semester_setups from offerings, attendance_overrides→academic_overrides, grade_rules→assessment_schemes+components row-pivot, 3 institutional scheme templates per college"
      - "0009 constraints: USN NOT NULL/format/unique-per-college, FK course_offerings.assessment_scheme_id, AAT ≤40% CHECK, one-HOD-per-dept partial unique, deferred FKs for hall_tickets/grade_cards.current_version_id, single-current see_results"
    verify_sql_blocks: "services/api/alembic/verify/verify_0007.sql / verify_0008.sql / verify_0009.sql"
    plan_vs_live_corrections:
      - "course_type enum was (core|elective|lab); rewritten in 0007 with USING expression (core→theory, elective→theory, lab→lab)"
      - "academic_terms table created and backfilled from existing VARCHAR codes; new tables FK academic_term_id, legacy academic_term VARCHAR(20) preserved on course_offerings/enrollments"
      - "see_results/re_evaluations/course_drops use enrollment_id BIGINT (matches enrollments.id BIGINT PK), not UUID"
      - "0008 USN backfill joins enrollments→sections→batches→departments (the plan's enrollments.department_id does not exist)"
      - "0008 grade_rules pivot handles rows-per-assessment-type, not the wide-row shape the original plan assumed"
    ui_shipped:
      - "/admin/users — full table (name/email/USN/role/dept/status) with role/status/q filters, pagination, role-change dialog with HOD dept selector, status toggle, bulk-CSV import with dry-run preview"
      - "/admin/academic Courses tab — course_type selector now includes nptel + integrated"
      - "/hod/* — auth-guarded shell with sidebar (M10 entries disabled); /hod/dashboard reads /api/v1/hod/dashboard and renders welcome + dept overview placeholder + own teaching offerings"
      - "apps/web/lib/auth.ts Role union extended with 'hod'; login/page.tsx routes HODs to /hod/dashboard"
    deprecated_for_future_cleanup:
      - "departments.head_user_id (use users.hod_of_department_id)"
      - "attendance_overrides table (data migrated to academic_overrides; reader removed in M3 rework)"
      - "grade_rules table (pivoted into assessment_schemes/components; reader removed in M4 rework)"
      - "course_offerings.academic_term VARCHAR(20) (use academic_term_id)"
    blocked_by: none
    next_session_picks_up_at: "M2 rework done. Next is M10b (elective registration + dissolution + cascade)."
    m10a_followups_added_this_session:
      - "ORM backfill: AcademicTerm, AssessmentSchemeTemplate, AssessmentScheme, AssessmentSchemeComponent now in academic/models.py. CourseOffering ORM extended with parent_offering_id / academic_term_id / assessment_scheme_id (columns already lived in 0007)."
      - "GET /academic-terms (read-only, college-scoped) added so the HOD setup picker can populate term options before an admin terms-CRUD page exists."
      - "Seed adds hod@bmsce.ac.in (linked to CSE) with the demo password."

  M3_attendance_service:
    status: rework_pending
    skeleton_live: true
    v1_shipped: "see CLAUDE-v1-archive.md — 5 tables, 7 endpoints, state machine, signed JWT QR, GPS+face stub, overrides, CSV report"
    rework_scope:
      - "Eligibility computation engine (core/eligibility.py) — pure deterministic function called everywhere"
      - "60% per-CIE attendance threshold"
      - "85% main SEE threshold (already exists)"
      - "Integration with internal_deadlines — attendance edits frozen post-deadline (teacher-overridable until hard stop)"
      - "Per-course teacher freeze respect"
      - "academic_overrides integration for typed condonations"
    face_verify: "STAYS AS STUB — M8 swaps later"
    blocked_by: M2_rework
    next_session_picks_up_at: "After M2 rework"

  M4_marks_service:
    status: rework_pending
    skeleton_live: true
    v1_shipped: "see CLAUDE-v1-archive.md — 5 tables, 17 endpoints, CSV bulk, lock cascade, audit timeline, per-offering grade rules, parent role"
    rework_scope:
      - "Replace grade_rules table with assessment_schemes from M10"
      - "Best-2-of-3 CIE computation as reusable service function"
      - "AAT linkage point ready (M11 assignments feed into AAT components)"
      - "NPTEL grading path (separate from CIE/SEE)"
      - "SEE versioning: original → re_eval → makeup"
      - "40% / 60% threshold enforcement"
      - "Grade card generation (PDF via reportlab, R2 storage)"
      - "Pending state with I/X grades, displayed as 'Pending'"
      - "Backlog detection on SEE failure → emit student.backlog_added event"
    blocked_by: M2_rework, M10
    next_session_picks_up_at: "After M10"

  M10_academic_workflow:
    status: complete
    skeleton_live: true
    scope: "Workflow module COMPLETE across M10a–M10e — see docs/modules/M10.md"
    sub_sessions:
      a: "✅ shipped — Semester Setup CRUD + self-publish (HOD draft → active in one transaction); admin_notifications feed; HOD pages + admin notifications page; event bus publisher stub with stable payload contract"
      b: "✅ shipped — Registration window, student elective registration (idempotent), HOD elective dissolution + cascade (4 tables in one tx), manual single-student migration, capacity cap with by_registration_order / manual modes, dissolve preview (read-only blast radius), /student/dashboard + /student/registration + /hod/electives, /hod/dashboard under-subscribed callout"
      c: "✅ shipped — Lab batches (CRUD + bulk members + auto-compose round-robin + incharge assignments with HOD-override audit), per-offering scheme picker (template / clone / custom; AAT gating with academic_overrides on HOD-band; lock = teacher, unlock = HOD; integrated lab side inherits from parent), department-owned scheme templates, /hod/lab-batches + /hod/scheme-templates + /teacher/courses/[id]/scheme + /hod/dashboard scheme-readiness card"
      d: "✅ shipped — Internal deadlines (institutional_hard/department_soft/per_course_freeze with kind-aware authority), CIE schedule per offering (HOD-publish + scheduled_at ordering CHECK), tasks (HOD assigns dept-only with pending → accepted/declined/completed/cancelled state machine), real Redis subscriber loop in app.core.event_bus with in-process handler registry, workflow.subscribers writes admin_notifications on internal_deadline.crossed, /hod/cie-schedule + /hod/tasks + /teacher/tasks + /admin/internal-deadlines"
      e: "✅ shipped — Eligibility engine (attendance ≥85% from class_sessions + attendance_records; CIE ≥40% best-2-of-3 from M4 v1 marks; NPTEL waived), hall tickets (per-student + dept-batch generate + HOD approve + version regenerate + reportlab PDF stream), SEE CSV upload + supersede chain, re-evaluation (student request + HOD CSV upload with improve-or-hold rule), makeup (HOD authorize + CSV upload superseding prior current row), grade cards (auto-regenerate on SEE/re-eval/makeup with trigger_reason versions + SGPA + grade bands S/A/B/C/D/E/F/I), /hod/hall-tickets + /hod/see-upload + /hod/re-eval + /hod/makeup + /student/hall-ticket + /student/grade-card + /student/re-eval"
    m10a_shipped:
      schema:
        - "Migration 0010 — admin_notifications (id, college_id, event_type, payload jsonb, created_at, read_at). Index (college_id, created_at DESC)."
        - "Verify SQL at services/api/alembic/verify/verify_0010.sql"
      backend:
        - "services/api/app/modules/workflow/models.py — SemesterSetup, ElectiveGroup, ElectiveGroupOption, AdminNotification"
        - "services/api/app/modules/workflow/schemas.py — Pydantic in/out shapes incl. SemesterSetupDetail (with denormalised display fields)"
        - "services/api/app/modules/workflow/service.py — create/list/get/patch/delete setup, add/patch/remove course (auto-scheme-link idempotent), elective groups+options CRUD, publish (draft→active in one tx with admin_notifications row), list_admin_notifications"
        - "services/api/app/modules/workflow/router.py — split into hod_router (/hod/dashboard), workflow_router (/workflow/semester-setups/*), admin_notifications_router (/admin/notifications)"
        - "services/api/app/core/event_bus.py — best-effort publish() (structured log + Redis PUBLISH best-effort, never raises). Payload shape matches AI_DEFERRAL_PLAN.md."
        - "services/api/app/modules/academic/router.py — GET /academic-terms read-only"
      ui:
        - "/hod/semester-setup — index page (list by term, gated New-setup button)"
        - "/hod/semester-setup/[id] — full editor with notes autosave, course add/remove (type badges, integrated parent dropdown when course_type=lab), elective group + option CRUD, publish confirmation dialog. Read-only after publish."
        - "/hod/dashboard — surfaces current-term setup state (link to editor)"
        - "/admin/notifications — sortable table feed with department + event-type filters"
        - "/hod/layout.tsx — Semester setup nav link enabled. /admin/layout.tsx — Notifications nav link added"
      tests: "services/api/tests/test_m10a.py — 12 tests covering critical paths (HOD create-draft / cross-dept blocked / duplicate blocked / publish state transition / read-only-after-publish / publish validation / admin-read-only / admin notifications populated on publish / teacher write blocked / cross-department course assignment / idempotent scheme link / event payload shape)"
      seed: "infra/scripts/seed.py — hod@bmsce.ac.in (CSE HOD) created idempotently, password = MetisDemo!2026"
      authority_choices:
        - "Publish state: draft → active in one transaction (published timestamp recorded). 'published' state retained for the enum but the flow skips dwelling there per the build plan: HODs publish after the term is live."
        - "Auto-scheme-link: on course add, finds the institutional template matching the course_type (theory→Theory Standard, lab→Theory Standard, integrated→Integrated Standard, nptel→NPTEL Standard) and instantiates an AssessmentScheme + components row-set. Idempotent — service short-circuits if assessment_scheme_id is already non-null."
        - "RBAC: workflow writes require require_hod (admins blocked from writing per CLAUDE.md authority table). Admin can list and read setup details for oversight. /admin/notifications is admin-only."
        - "Admin notifications feed is sourced from a dedicated table, not from semester_setups, so M5 can wire mark-as-read without leaking state columns into the setup row."
        - "Event publisher logs + best-effort Redis PUBLISH. M10d swaps Redis to required-Redis with retry. Signature is stable."
      deferred_to_m10b_or_later:
        - "Lab batch composition (M10c)"
        - "HOD-side assessment scheme picker (M10c) — for now M10a auto-links the institutional template"
        - "CIE scheduling + tasks + internal deadlines (M10d)"
        - "Hall tickets + grade cards + SEE/re-eval/makeup (M10e)"
    m10b_shipped:
      schema:
        - "Migration 0011 — semester_setups.registration_opens_at / registration_closes_at + window-order CHECK (verify_0011.sql)"
        - "Migration 0012 — elective_group_options.max_enrollment + positive-cap CHECK (verify_0012.sql)"
      backend:
        - "services/api/app/modules/workflow/service_m10b.py — registration-window setter; student GET/POST/status; HOD enrollment view; _perform_student_migration (cascade core, transaction-aware); dissolve preview + commit; manual migrate; cap with by_registration_order or manual"
        - "services/api/app/modules/workflow/router.py — extended with /workflow/elective-groups/{id}/enrollment, /dissolve(+/preview), /migrate-student, /options/{id}/cap; /workflow/semester-setups/{id}/registration-window; new student_registration_router for /student/registration*"
        - "academic/models.py — EnrollmentState enum + academic_term_id col on Enrollment ORM (column already existed in DB)"
        - "workflow/models.py — CourseRegistration, LabBatch, LabBatchMember, AcademicOverride ORM; OverrideType enum; window cols on SemesterSetup; max_enrollment col on ElectiveGroupOption"
        - "deps.py — require_student dep"
      cascade_semantics:
        rule: "ONE transaction wraps the per-student cascade. Caller manages session.begin(); helper writes inside that context. Any failure rolls back all student migrations in the batch."
        writes:
          - "course_registrations: old row .status='migrated'; new row created with .status='approved'. Created_at on new row = migration time (later by_registration_order sees them at the end of the queue)."
          - "enrollments: only mutated when the new offering lives in a different section. Old enrollment → withdrawn_at=NOW + state='migrated'; new enrollment inserted for new section. Within-section: no-op."
          - "lab_batch_members: rows joined to the OLD offering's lab batches with removed_at=NULL are flipped to removed_at=NOW + removed_reason='migrated_to_other_offering'. New offering's batch composition is M10c."
          - "academic_overrides: append-only audit, override_type='student_migration', old_value/new_value JSON, reason text."
        preserved:
          - "attendance_records (FK to class_sessions which FKs course_offerings): untouched. M3 rework's eligibility engine reads course_registrations.status to ignore migrated electives."
          - "marks (FK to assessments which FK course_offerings): untouched. parent_visible flag stays as-is."
        post_commit:
          - "elective.dissolved event (dissolve flow)"
          - "student.migrated events — one per moved student"
      ui:
        - "/student/dashboard — window status, registration-progress callout, migration alert when course_registrations.status='migrated' exists"
        - "/student/registration — window-aware page with mandatory courses table + group-pick cards. Submit/Update label adapts to whether prior choices exist."
        - "/hod/electives — setup + group pickers, live enrollment table with under/over/healthy badges, per-option Cap and Dissolve dialogs (preview-before-confirm + type-the-name confirmation for dissolve), manual migrate dialog, per-option student lists below"
        - "/hod/dashboard — under-subscribed-count callout linking to /hod/electives"
        - "student shell — Dashboard + Registration nav entries"
      tests: "services/api/tests/test_m10b.py — 14 critical paths incl. window enforcement, idempotent re-submit, full cascade verification across all touched tables, preview is read-only, wrong-dept block, manual-to-dissolved reject, capacity redistribute order correctness, manual cap displaced-list mode, event payload shapes, transactional rollback on simulated downstream failure, attendance + marks preserved"
      authority_choices:
        - "Enrollment cascade: section-aware. Within-section migrations don't mutate enrollments; cross-section does. The M3 rework eligibility engine will read course_registrations.status='migrated' to discount the elective from the old offering's count without disrupting the section enrollment."
        - "Order tie-break: by_registration_order uses (created_at ASC, id ASC). Re-submission while window open patches the existing row, so re-pick doesn't bump you to the back of the queue. New migrated rows have a fresh created_at, so newly arrived migrants land at the tail."
        - "Manual into dissolved: rejected with target_dissolved. Reviving a dissolved option is out of scope."
        - "Preview auth: same require_hod_for_dept as dissolve. Same RBAC keeps the implementation simple."
        - "Notifications: emit student.migrated event only; M5 will wire user-facing notifications. M10b ships a temporary /student/dashboard banner for the migrated case that reads course_registrations.status directly."
    m10c_shipped:
      schema: "no new migration — M10c rides on the lab_batch_assignments / assessment_schemes / assessment_scheme_templates tables already in 0007."
      backend:
        - "services/api/app/modules/workflow/models.py — LabBatchAssignment ORM mapping (table from 0007)."
        - "services/api/app/modules/workflow/service_m10c.py — new file. Lab batch CRUD; bulk members with one-batch-per-offering invariant; auto_compose_batches (round-robin from active section enrollments; existing assignments preserved; emits lab_batch.composed); add_assignment (one incharge per batch, HOD override unassigns prior + emits lab_batch.reassigned + writes academic_overrides[lab_batch_reassignment]); per-offering scheme get/replace/patch_component/lock/unlock; AAT gating (≤20% teacher-free, 20–40% HOD with academic_overrides[assessment_scheme_unlock] audit, >40% rejected — also pinned by the per-row CHECK in 0009); REPLACE soft-deletes old components and inserts new (preserves Marks audit trail); integrated lab side (parent_offering_id set) reads parent's scheme and rejects writes with scheme_inherited; offering roster helper for the UI picker; dept scheme template CRUD with DELETE refusal while in use (template_in_use)."
        - "services/api/app/modules/workflow/router.py — extended with /workflow/course-offerings/{id}/lab-batches (+ /auto-compose, /roster), /workflow/lab-batches/{id}/{members,assignments}, /workflow/course-offerings/{id}/scheme/{lock,unlock,components/{cid}}, /workflow/scheme-templates (CRUD), /hod/scheme-readiness."
        - "services/api/app/modules/workflow/schemas.py — M10c shapes: LabBatchOut + assignments + members; SchemeOut/SchemeReplace/SchemeComponentPatch/SchemeLockRequest/SchemeUnlockRequest with one-of-three input validation; SchemeTemplateOut/Create/Patch; SchemeReadinessOut; OfferingRosterEntry."
      ui:
        - "/hod/lab-batches — setup + offering picker (filters integrated/lab), batches table with member counts + incharge + co-evaluators, Add/Auto-compose buttons, Manage dialog (Members tab from offering roster picker + Assignments tab with incharge/co-eval add+unassign + rename form)."
        - "/hod/scheme-templates — full template index with applies-to filter, institutional rows read-only, dept rows full CRUD; New + Use-as-base flows; live AAT-band and weight-total badges (amber at 20%, red at 40%); validation_rules JSON editor."
        - "/teacher/courses/[id]/scheme — scheme view with AAT/weight/lock badges, Replace-from-template + Clone-from-offering + Custom-edit dialogs, per-component PATCH dialog with AAT hint, Lock dialog, Unlock dialog (HOD-only, reason required). Inherited child shows banner + parent link, all writes hidden."
        - "/hod/dashboard — new Scheme-readiness card (counts + offerings table showing every unlocked-or-missing scheme with Configure deep-link)."
        - "/hod/semester-setup/[id] — every course row gains Configure scheme + Lab batches deep-links."
        - "/hod/electives — header gets Lab batches and Scheme templates quick-links."
        - "/hod/layout.tsx — Lab batches + Scheme templates nav entries enabled."
        - "/teacher/layout.tsx — accepts HOD role too so /hod/electives deep-links into /teacher/courses/{id}/scheme work."
      tests: "services/api/tests/test_m10c.py — 15 critical paths (HOD batch on integrated; theory rejects with course_type_incompatible; one-batch-per-offering invariant; auto-compose round-robin distribution + event payload; teacher assigns own incharge + HOD overrides + academic_overrides[lab_batch_reassignment] row; teacher AAT >20% → 403 aat_requires_hod; HOD pushes AAT to 30% → academic_overrides[assessment_scheme_unlock]; AAT >40% always rejected; lock blocks edits, HOD unlock writes academic_overrides; dept template create + cross-role write blocked; template DELETE blocked while in use; integrated lab side rejects writes with scheme_inherited; REPLACE soft-deletes old components + inserts new IDs; assessment.scheme_configured + lab_batch.composed + lab_batch.reassigned payload shape conforms to AI_DEFERRAL_PLAN.md)."
      authority_choices:
        - "Lab batch writes: HOD-of-the-offering's-dept OR teacher == offering.teacher_user_id. Admin reads. Matches CLAUDE.md authority table: HOD composer with teacher composing own course, HOD overrides on top."
        - "Scheme writes: teacher of offering OR HOD of dept. Admin is read-only for scheme. Aligns with the corrected mental model — teachers own their offering's scheme; HOD acts when an AAT extension or unlock is needed."
        - "AAT gating implemented per-total: ≤20% (any actor); 20–40% (HOD only, writes academic_overrides[assessment_scheme_unlock] reason='HOD pushed AAT into 20–40% band'); >40% rejected for everyone — also enforced per-row by ck_scheme_comp_aat_max_40pct on the table."
        - "Scheme REPLACE: existing scheme row is preserved (course_offerings.assessment_scheme_id never changes), components are soft-deleted and replaced. PATCH on a single component mutates in place to keep the marks audit shape stable. Re-using soft-deleted labels works because the partial unique index on (scheme_id, label) WHERE deleted_at IS NULL only counts live rows."
        - "Integrated lab side (parent_offering_id IS NOT NULL): GET returns the parent's scheme with inherited_from_offering_id set; POST/PATCH/lock/unlock all 400 with code='scheme_inherited' and the parent offering id so the UI deep-links to the right page."
        - "Dept templates: institutional templates (owner_department_id IS NULL) are read-only here (admin authoring deferred to M9). HOD-owned templates scoped to their dept. Cross-dept HODs cannot edit each other's templates. DELETE refuses with template_in_use while any AssessmentScheme.template_id still references the row."
        - "Auto-compose roster: active section enrollments only (queries Enrollment by section_id + term filter, ignores course_registrations). Mandatory labs never write course_registrations rows, and elective labs always have a section enrollment created via the M10b cascade — so a single source-of-truth covers both."
        - "Events: assessment.scheme_configured on replace/patch/lock/unlock; lab_batch.composed on auto-compose; lab_batch.reassigned only when a new incharge displaces an existing one. All emit AFTER commit via app.core.event_bus.publish (best-effort Redis + structured log; never raises)."
      deferred_to_m10d_or_later:
        - "Teacher-requests / HOD-approves token flow for AAT 20–40% — current path treats the HOD actor as the authoriser. Token request workflow can ride on top of the M10d tasks framework when needed."
        - "Per-batch member listing endpoint — UI currently picks from the offering roster and trusts backend skips for already-placed students. A dedicated GET /lab-batches/{id}/members can land later."
        - "Admin authoring of institutional templates — admin-side templates UI is M9 territory."
    m10d_shipped:
      schema: "no new migration — internal_deadlines / cie_schedule / tasks tables are all in 0007. M10d only adds ORM mappings."
      backend:
        - "services/api/app/modules/workflow/models.py — InternalDeadline (+ DeadlineKind enum-class for the VARCHAR kind column), CIESchedule, Task (+ TaskType, TaskStatus enums bound to the Postgres enum types from 0007)."
        - "services/api/app/modules/workflow/service_m10d.py — new file. Internal deadline CRUD with kind-aware authority (admin owns institutional_hard, HOD owns department_soft for their dept, teacher owns per_course_freeze for own offering — HOD overrides). One row per scope (in-app uniqueness check). Freeze toggle emits internal_deadline.crossed AFTER commit; unfreeze is silent. is_offering_frozen(offering_id) helper + get_offering_freeze_status (M3/M4 rework consumers). CIE schedule create/patch/delete with HOD+teacher writers; HOD-only publish flip + scheduled_at ordering CHECK. Tasks: HOD assigns to dept teachers only (cross-dept rejected; outside_teacher in fixture proves this), pending → accepted/declined/completed/cancelled state machine, decline requires reason, only assigner+admin can cancel. Every transition emits task.assigned / task.status_changed."
        - "services/api/app/modules/workflow/schemas.py — M10d shapes: InternalDeadlineOut/Create/Patch/FreezeRequest, CIEScheduleOut/Create/Patch, CIEPublishRequest, TaskOut/Create/StatusUpdate, OfferingFreezeStatus."
        - "services/api/app/modules/workflow/router.py — extended with /workflow/internal-deadlines (CRUD + freeze + course-offerings/{id}/freeze-status), /workflow/course-offerings/{id}/cie-schedule (list + create + publish), /workflow/cie-schedule/{id} (patch + delete), /workflow/tasks (CRUD + status transitions)."
        - "services/api/app/core/event_bus.py — subscriber side: on(event, handler) registry, start_subscriber()/stop_subscriber() + psubscribe('metis:events:*') loop with exponential backoff + cancellation handling. _dispatch is the test seam so the suite can exercise handlers without a live Redis pubsub roundtrip."
        - "services/api/app/modules/workflow/subscribers.py — workflow-side handler registry. Currently wires handle_internal_deadline_crossed which writes an admin_notifications row in its own session (so a failed handler doesn't poison the API request transaction)."
        - "services/api/app/main.py — lifespan integration: register_workflow_subscribers() + start_subscriber() on startup (skipped in APP_ENV=test), stop_subscriber() on shutdown."
      ui:
        - "/hod/cie-schedule — setup + offering picker, per-offering CIE-1/2/3 table with date/time/duration/room + inline edit, Publish-all / Unpublish-all button. Add buttons disabled when allPublished (and per-row edits/deletes disabled when the row itself is published)."
        - "/hod/tasks — table of department tasks with status filter, New task dialog (teacher picker from /users list, type + title + description + due_at), Cancel button for pending/accepted rows."
        - "/teacher/tasks — assignee view filtered by status, Accept/Decline (decline requires reason via dialog)/Complete buttons matching the state machine."
        - "/admin/internal-deadlines — institutional hard-stops table (create dialog + freeze/unfreeze dialog), department_soft + per_course_freeze rows shown read-only for cross-cutting visibility. Empty-state amber callout when no institutional hard-stop exists."
        - "/hod/layout.tsx — CIE schedule + Tasks nav entries enabled; /teacher/layout.tsx — Tasks entry added; /admin/layout.tsx — Internal deadlines entry added."
      tests: "services/api/tests/test_m10d.py — 15 critical paths: admin owns institutional_hard / HOD blocked; HOD owns department_soft + other-dept rejected; teacher per_course_freeze + outside-teacher rejected; freeze emits internal_deadline.crossed + flips offering freeze status via dept-soft cone; duplicate kind rejected; teacher creates CIE + HOD publishes (teacher can't publish); CIE date ordering rejected with cie_out_of_order; published CIE can't be deleted; HOD assigns task to dept teacher; cross-dept assignment blocked; accept→complete chain + can't transition from completed; decline requires reason; only assigner can cancel; subscriber registry dispatches to registered handlers (capture + flaky handler proves error isolation); admin_notifications row materialised by the internal_deadline.crossed handler."
      authority_choices:
        - "Three deadline kinds, three authorities: institutional_hard = admin; department_soft = HOD of that dept; per_course_freeze = teacher of offering (HOD also). Patches/deletes/freezes follow the same matrix; frozen deadlines refuse patches (deadline_frozen 409) so the audit story stays linear — unfreeze before editing."
        - "Freeze precedence (is_offering_frozen / get_offering_freeze_status): institutional_hard > department_soft > per_course_freeze. M3/M4 rework consumes this helper to gate attendance + marks edits."
        - "CIE publish is HOD-only (matches CLAUDE.md authority table). Teachers can draft CIE-1/2/3 dates but only the HOD flips is_published. Published rows are protected from delete; HOD can still PATCH a published row in case of a venue swap."
        - "Tasks stay inside the HOD's dept. Cross-dept assignment is rejected at the service layer (assignee must teach ≥1 offering in the actor's dept, or be the same dept's HOD). Same rule keeps the M9 reporting boundary clean."
        - "Subscriber side: in-process handlers (via on() + the lifespan-started psubscribe loop) for low-latency reactions inside the API; cross-service consumers (M5/M7/M8) subscribe to the same Redis channels separately. Handler errors are logged but never propagate, so one broken handler doesn't take down the rest. APP_ENV=test skips the live loop so pytest doesn't dangle background tasks during teardown — tests call _dispatch directly to validate the contract."
        - "internal_deadline.crossed is the only event with an in-app handler at M10d; the handler writes an admin_notifications row in a fresh session so a failure doesn't poison the API request that emitted the event. M5 will reuse the same plumbing for cross-role notification fan-out."
      deferred_to_m10e_or_later:
        - "Cron / scheduled scanner that auto-freezes deadlines when deadline_at passes — for now freeze is manual (admin or HOD flips the switch)."
        - "Cross-dept resource conflict notifications (when CIE rooms collide) — admin_notifications schema is ready; the producer lands when M9 admin analytics ships."
        - "Per-batch CIE schedules — current schedule is per-offering. Lab batches that run separate CIEs can be modelled later by allowing a lab_batch_id on cie_schedule rows."
    m10e_shipped:
      schema: "no new migration — hall_tickets / hall_ticket_versions / grade_cards / grade_card_versions / see_results / re_evaluations all came from 0007 + 0009. M10e only adds ORM mappings + a single dep (reportlab)."
      backend:
        - "services/api/app/modules/workflow/models.py — HallTicket, HallTicketVersion, GradeCard, GradeCardVersion, SEEResult (+ SEEResultKind enum), ReEvaluation ORMs."
        - "services/api/app/modules/workflow/service_m10e.py — single consolidated file: eligibility engine (attendance % from ClassSession+AttendanceRecord; CIE % best-2-of-3 from M4 v1 Mark+Assessment; NPTEL auto-eligible); hall ticket service (per-student generate, dept-batch generate, HOD approve, version regenerate, idempotent snapshot compare); SEE service (CSV upload by USN with supersede chain); re-evaluation (student request gated on see_not_released + already_requested; HOD CSV upload with improve-or-hold rule that supersedes original on equal/higher); makeup service (HOD authorize → placeholder makeup row, then HOD CSV upload supersedes whatever is current); grade card service (per-(student, term) versions keyed by trigger_reason='initial'|'see_released'|'re_eval'|'makeup_completed'; per-subject internal+see+total% computation; SGPA from BMSCE 10-point grade bands; is_finalised when every subject has a non-pending grade); reportlab PDF rendering for hall tickets + grade cards from the snapshot JSON, so files aren't persisted and pdf_url stays a logical 'inline:{version_id}' identifier."
        - "services/api/app/modules/workflow/schemas.py — HallTicket*/GradeCard*/SEEUpload*/ReEval*/Makeup* shapes plus the snapshot detail rows used by the UI."
        - "services/api/app/modules/workflow/router.py — extended with /workflow/hall-tickets (list+generate+batch+approve+me+version PDF stream), /workflow/see-results (upload+list), /workflow/re-evaluations (student request + HOD upload + list), /workflow/makeup (authorize+upload), /workflow/grade-cards (generate+list+version PDF stream)."
        - "services/api/pyproject.toml — added reportlab>=4.2.0 (pure Python, no native deps)."
      ui:
        - "/hod/hall-tickets — term picker, batch-generate button, per-student table with eligible/NA counts, multi-select approve, per-row PDF link."
        - "/hod/see-upload — setup + offering picker, CSV textarea (USN,marks), max_marks input, results table showing every SEE row including superseded history."
        - "/hod/re-eval — per-offering request queue with status/original/revised, CSV upload form for revised marks (improve-or-hold enforced by backend)."
        - "/hod/makeup — failed-students table (current SEE < 40%) for authorization, then CSV upload form for makeup marks; makeup row supersedes whatever is current."
        - "/student/hall-ticket — fetches /hall-tickets/me, shows latest version's per-subject snapshot with eligible/NA badges and reasons, current-version PDF download, version history list."
        - "/student/grade-card — one card per term with subjects table (internal/SEE/total/grade), SGPA badge, finalised badge, version history with trigger_reason badge + per-version PDF download."
        - "/student/re-eval — list of own re-eval requests with status/outcome, New-request dialog (course picker from /student/registration's mandatory courses + reason)."
        - "Navs: /hod/layout.tsx — Hall tickets, SEE upload, Re-evaluation, Makeup enabled. /student/layout.tsx — Hall ticket, Grade card, Re-evaluation added."
      tests: "services/api/tests/test_m10e.py — 17 critical paths: eligible / ineligible-attendance / ineligible-CIE / idempotent regenerate / PDF download streams application/pdf with %PDF magic / cross-student PDF forbidden / batch-generate + approve flow / SEE upload supersedes / SEE marks > max rejected / re-eval improve-or-hold (lower rejected, higher accepted) / re-eval without SEE rejected (see_not_released) / makeup authorize+upload supersedes / makeup without authorize rejected / grade card pending when no SEE / grade card auto-regenerates on SEE release with trigger_reason='see_released' and SGPA computed / student grade-card PDF streams / event payloads emitted (see.marks_released triggers grade_card.regenerated)."
      authority_choices:
        - "Hall tickets + grade cards: HOD generates and approves for own dept (admin sees but doesn't approve, per CLAUDE.md authority table). PDF download: students get their own; HOD gets own dept's; admin sees all."
        - "PDF storage strategy: NO bytes are persisted. The eligibility_snapshot / grades_snapshot JSON column is the durable artifact; reportlab regenerates the PDF deterministically from the snapshot on every download. pdf_url stores `inline:{version_id}` so R2 wiring stays a future swap without schema churn."
        - "Eligibility engine (BMSCE defaults): attendance ≥85% from closed class_sessions, CIE ≥40% best-2-of-3 from M4 v1 marks. NPTEL waived. The function signature is stable enough that the M3 rework can swap implementations without breaking M10e callers."
        - "SEE / re-eval / makeup supersede chain: only one is_current SEE row per enrollment (enforced by the partial unique index). Re-evaluation enforces improve-or-hold strictly (lower revised → rejected, equal/higher → supersedes original). Makeup is a separate attempt and may legitimately produce a lower score; it supersedes whatever is current."
        - "Grade card regeneration: triggered by the same actor (HOD) inside the SEE/re-eval/makeup transactions via regenerate_grade_card helper. Skipped silently when a student has no active enrollment. is_finalised flips to true once every subject has a non-pending grade — the M11 assignments AAT contribution will require a re-think when M4 rework lands."
        - "Eligibility snapshots stringify all UUIDs (`str(course_offering_id)`) so the JSON serialiser doesn't trip; comparison for idempotent re-runs ignores generated_at + version_number so a no-op regenerate doesn't bump versions."
      deferred_to_later:
        - "AICTE compliance export (admin reports) — schema-ready; producer lands in M9."
        - "Custom grade band overrides per college — currently hard-coded BMSCE bands; the M9 /admin/eligibility-config surface will read JSON config from a future colleges metadata column."
        - "Multi-version grade card UI showing per-version snapshot diffs — current UI lists versions with download links; a v1-vs-v2 visual diff is M9 work."
        - "R2 storage of PDFs — out of scope; current 'inline:{version_id}' URL means downloads always regenerate from the snapshot. When R2 wires up, a CDN-served signed URL replaces the inline identifier without ORM changes."
    blocked_by: none
    next_session_picks_up_at: "M10 complete. Next: M3 attendance rework (eligibility engine refactor + freeze guards), then M4 marks rework (scheme-driven computation + NPTEL + SEE chain consumption from M10e)."

  M11_assignments:
    status: not_started
    skeleton_live: false
    scope: "NEW MODULE — see docs/modules/M11.md"
    features:
      - "Assignment CRUD (title, description, deadline, max marks, file type allowlist, late policy, resubmission)"
      - "Portal mode: student submission via R2 presigned upload"
      - "Offline mode: no submissions, teacher enters marks directly"
      - "Scope: section-wide | batch-specific | individual"
      - "Optional AAT linkage to assessment scheme component"
      - "Per-post parent visibility toggle"
      - "Filters: submitted / missing / late / ungraded"
      - "Bulk download submissions"
      - "Grading + feedback + reviewed file upload"
      - "Resubmission tracking"
    blocked_by: M2_rework, M10, M6 (R2 setup)
    next_session_picks_up_at: "After M10"

  M5_comms_service:
    status: not_started
    blocked_by: M1, M2_rework, M10 event bus
    note: "Notification fan-out for parents lives here, respects per-post visibility toggles"

  M6_content_service:
    status: not_started
    blocked_by: M1, M2_rework
    note: "Publishes material.uploaded events; M7 consumer plugs in later"

  M9_admin_analytics:
    status: not_started
    blocked_by: All others
    note: "Lighter than originally scoped — most workflow lives in M10/HOD"

  M7_learning_engine:
    status: deferred
    scaffold_only: true
    note: "Empty FastAPI scaffold in services/learning-engine/ with /health. Build last."

  M8_insights_face:
    status: deferred
    scaffold_only: true
    note: "Empty FastAPI scaffold in services/insights-engine/ with /health. M3 face stub swappable. Build last."

audit_session_5:
  status: complete
  date: "2026-05-15"
  scope: "Student attendance eligibility surface — see AUDIT_FINDINGS.md Session 5 (closes F8 + A3)"
  schema: "no migration — pure consumer of the existing M10e eligibility engine."
  backend:
    - "attendance/service.py — new get_student_eligibility_summary(student, term_id=None) aggregator. Resolves the student's active enrollment for the requested term (defaults to most-recent active), pulls offerings under their section, and delegates each subject's threshold computation to workflow.service_m10e.compute_subject_eligibility. Cross-module import is one-way: attendance → workflow.service_m10e (workflow already imports attendance models, so no cycle)."
    - "attendance/schemas.py — new CourseEligibility + EligibilitySummary shapes. Field names mirror compute_subject_eligibility's return dict (attendance_percent, cie_percent, attendance_eligible, cie_eligible, overall_eligible, reason) so engine changes flow through without churn."
    - "attendance/router.py — new GET /attendance/me/eligibility-summary?term_id=<optional> with require_student dep. Read-only — pure aggregation over the eligibility engine."
  tests: "test_attendance_eligibility.py — 6 new tests (above-85%, between-60-85%, below-60% + low-CIE, NPTEL waived, HOD-blocked RBAC, term_id round-trip). Re-uses test_m10e's _build_fixture so we plant attendance + CIE marks at known thresholds without duplicating the fixture builder. Full suite: 182 passed (176 baseline + 6 new)."
  frontend:
    - "apps/web/app/student/attendance/page.tsx — fetches /attendance/me/eligibility-summary alongside today's sessions; renders a new 'Eligibility this term' card above the submit panel with per-course tiles (course code + title, large attendance %, Attendance ≥85% badge, CIE ≥40% badge with current %, overall eligible/ineligible chip, reason string when ineligible). NPTEL subjects render a 'eligibility waived' note instead of the badges. Card hides entirely when the student has no enrollment yet (non-fatal 404 swallowed)."
  authority_choices:
    - "Aggregator lives in the attendance module — the endpoint is /attendance/me/eligibility-summary, the cross-module import (workflow.service_m10e.compute_subject_eligibility) is one function and keeps the eligibility engine as single source of truth."
    - "Response shape passes through compute_subject_eligibility's existing return keys (attendance_percent, cie_percent, attendance_eligible, cie_eligible, overall_eligible, reason). The audit doc's suggested names (cie_threshold_met / see_threshold_met) were renamed-for-UX-only; using the engine's vocabulary means future M3 rework changes flow through without router churn."
    - "Threshold labels in the UI reflect what the engine actually checks: attendance ≥85% (the SEE-via-attendance qualification) and CIE ≥40% (the BMSCE internal-marks SEE qualification). The audit doc's 'CIE-60%' wording refers to the per-CIE attendance rule which is a separate metric not in the engine today; that lands when M3 rework ships."
    - "Condonation banner deferred — compute_subject_eligibility does not expose condonation info today; the eligibility_snapshots table has the column but no producer writes it. Surfacing the banner is M3 rework work, not Session 5."
    - "term_id query param is optional. Default behaviour: most-recent active enrollment by enrolled_at DESC. Pass term_id to view a past term's eligibility (useful for the focal CSE 2023 student who has historical data)."
    - "Card hidden gracefully when the eligibility endpoint returns no courses — empty state is implicit (no card rendered) rather than a 'no data' message; the existing 'Today's classes' panel still shows."
  closed_audit_items:
    - "F8 (attendance % with eligibility indicators) — closed. Per-course cards render attendance %, 85%, and 40% badges."
    - "A3 (compute_subject_eligibility has no UI consumer) — closed. The aggregator is now wired to /student/attendance."
  deferred_to_session_6_or_later:
    - "Session 6: IA polish + docs closure (HOD dashboard year-tabbed cards, electives inline in semester-setup, lab batches nested under integrated offerings, teacher dashboard, marks charts, final docs)."
    - "Out of scope / M3 rework: condonation banner, per-CIE attendance (60% rule), live recompute on attendance entry."

audit_session_4:
  status: complete
  date: "2026-05-15"
  scope: "Unified registration with ranked elective preferences — see AUDIT_FINDINGS.md Session 4 (closes B6 + B7)"
  schema:
    - "Migration 0014_course_registration_preferences — new table course_registration_preferences (id, college_id FK, semester_setup_id FK, student_user_id FK, elective_group_id FK, elective_group_option_id FK, preference_rank SMALLINT 1..3 CHECK, created_at, updated_at, deleted_at). Indexes: ix_crp_student_setup, ix_crp_option, partial unique uq_crp_student_group_rank_active (student, setup, group, rank) WHERE deleted_at IS NULL, partial unique uq_crp_student_group_option_active (no duplicate options across ranks within one group)."
    - "Backfill: every existing course_registrations row with elective_group_id IS NOT NULL AND status='approved' becomes a rank-1 preference. Migrated/cancelled/backlog rows are intentionally not backfilled (they're audit, not intent). 87 rank-1 prefs inserted from existing approved electives on local DB."
    - "course_registrations untouched — stays as the committed-enrolment surface. New status string 'needs_intervention' added by convention (column is VARCHAR(20), no enum change)."
    - "verify_0014.sql checks: column list, partial unique indexes, ck_crp_rank_range CHECK, backfill row count, rank=4 rejection, duplicate-rank rejection."
  backend:
    - "workflow/models.py — new CourseRegistrationPreference ORM (TimestampedMixin + SoftDeleteMixin). Sibling of CourseRegistration; no relationship attribute back — kept flat."
    - "workflow/schemas.py — replaced RegistrationChoice with GroupRankedChoice {elective_group_id, ranked_option_ids: list (1..3)}. Replaced RegistrationGroupView.chosen_option_id with preferences: list[PreferenceEntry]. Dropped target_option_id from DissolveRequest. Added CommittedCourseEntry / CommittedView / ResolveNeedsInterventionRequest. CascadeSummary gains students_needing_intervention. CapRequest.redistribute_to_option_id now optional. StudentRegistrationView.intervention_alert dict added."
    - "workflow/service_m10b.py — full rewrite of registration + cascade core. submit_student_registration accepts ranked option lists, validates per-group dedup, capacity check on rank-1 only (rank-2/3 may be currently-full as fallbacks), idempotent replace of prior prefs (soft-delete + insert fresh; rank-1 course_registrations row preserves created_at). New _init_walker_state + _walk_preference_chain helpers. _write_needs_intervention_row inline-writes the placeholder course_registrations row + academic_overrides row when the chain exhausts. dissolve_option drops target_option_id; cascade walks each student's chain in FIFO order on the dying option, fanning to multiple targets. dissolve_option_preview re-runs the walker simulation to project per-student outcomes. cap_option_capacity accepts redistribute_to_option_id=None with by_registration_order strategy — displaced students walk their own chain. New get_committed_view feeds the closed-state unified table (mandatory + elective rows with status enrolled/migrated_from/needs_intervention). New list_dept_needs_intervention + resolve_needs_intervention. emit_student_needs_intervention publisher helper. student.migrated payload gains from_rank/to_rank/chain_depth (additive). elective.dissolved payload drops target_option_id, gains students_needing_intervention. New student.needs_intervention event."
    - "workflow/router.py — DissolveRequest body no longer carries target_option_id; both /dissolve and /dissolve/preview accept it as a no-op marker so callers can still attach reason text to the preview if they want. /cap fans out student.needs_intervention events when the by_registration_order path produces them. POST /student/registration/electives accepts the new ranked shape. New GET /student/registration/committed → CommittedView. New GET /workflow/needs-intervention → list[NeedsInterventionEntry] (HOD-scoped). New POST /workflow/elective-groups/{eg_id}/resolve-needs-intervention → ManualMigrateResponse envelope (student.migrated event with reason='needs_intervention_resolved')."
  tests:
    - "test_m10b.py — 6 existing tests updated for the new request/response shapes; 13 new tests added: full 3-rank submit, rank-1-only back-compat, duplicate-option-within-group rejection, rank-2-dissolved rejection, rank-2-full allowed, idempotent re-submit with created_at preservation, cohort-splits-rank-2-cap-spills-to-rank-3 (the worked example), chain-exhausted → needs_intervention row + event, preview matches commit outcomes, cap-no-target-walks-chain, resolve_needs_intervention flips status to approved, backfilled-rank-1 drives dissolution into needs_intervention, committed view shows enrolled rows after window close."
    - "Full suite: 176 passed (163 baseline + 13 net new)."
  frontend:
    - "apps/web/app/student/registration/page.tsx — full rewrite. State machine driven by window.is_open: OPEN renders mandatory table + per-group GroupPicker (3 dropdowns 1st/2nd/3rd, dedupe-within-group filter, capacity hints on options, dissolved options excluded entirely from dropdowns, rank-1 sets the only required slot). CLOSED fetches /student/registration/committed and renders a single 'My registered courses' table with status badges (enrolled / migrated from <X> / needs HOD attention). Submit form copy explicitly warns about the rank-1-only-no-fallback path."
    - "apps/web/app/student/dashboard/page.tsx — new red intervention_alert banner variant rendered alongside the existing amber migration_alert. groups[].chosen_option_id → groups[].preferences in the local type."
    - "apps/web/app/hod/electives/page.tsx — dissolve form drops target_option_id field; the dialog now explains the cascade walk semantics and renders a per-student projected-outcomes table in the preview card (badges for rank, badges for needs-intervention). New top-level 'Needs HOD attention' card listing every intervention row in the dept with a Resolve button that opens a dialog hitting /workflow/elective-groups/{eg}/resolve-needs-intervention. CascadeSummary type extended with students_needing_intervention + per_student outcome metadata."
  seed:
    - "infra/scripts/seed.py — CourseRegistrationPreference imported. register_focal_batch_electives now writes 1-3 ranked preferences per student (rank-1 follows the existing weighted distribution; rank-2/3 are deterministic shuffles of remaining options; ~20% of students set only rank-1, the rest set 2 or 3). The 3 pre-seeded migrated demo students get rank-1=dissolved + rank-2=survivor as their pref history. A new 4th demo student with rank-1=dissolved only seeds a needs_intervention row + matching course_registrations placeholder. Verified post-seed counts: 154 active preferences (65 rank-1 / 55 rank-2 / 34 rank-3), 4 migrated rows, 1 needs_intervention row."
  authority_choices:
    - "OQ D — new course_registration_preferences table. Cleaner separation between intent (preferences) and committed enrolment (course_registrations); cascade walks pure intent without re-using the well-tested approve-row semantics."
    - "OQ G — fixed 3 ranks. CHECK 1..3 at the DB level. Documented as institutional policy; can be relaxed by widening the constraint if a future deployment requires more depth."
    - "needs_intervention placement: new status string on course_registrations (VARCHAR(20), no enum change). Old approved row flips to 'migrated'; new row inserted with option_id=NULL and course_id reusing the dissolved option's course_id as a display placeholder. M9 reports and the student dashboard query the same table."
    - "Rank-1-only student whose option dissolves → routes to needs_intervention (the student declined to set fallbacks; we never auto-pick on their behalf)."
    - "Picker UI: 3 dropdowns per group (1st required, 2nd/3rd optional). Selecting an option at one rank removes it from the others within the group. Dissolved options excluded entirely from the dropdown menu; full options selectable as fallbacks at ranks 2/3 (disabled at rank 1)."
    - "Cascade ordering: students on the dissolving option are walked in (course_registrations.created_at ASC, id ASC) order — FIFO on the dying option. Matches the existing by_registration_order tie-break and means the earliest registrant gets first dibs on rank-2."
    - "Walker state seeds `used` from _option_enrollment_count per option (excluding the dissolving one). The counter increments live during the walk, so when rank-2 fills mid-cascade the next student lands on rank-3 deterministically. exclude_option_ids is singleton {from_opt.id} — we do not recurse into chained dissolutions."
    - "student.migrated payload extended with from_rank/to_rank/chain_depth (additive — existing subscribers ignore). elective.dissolved drops target_option_id, gains students_needing_intervention. New student.needs_intervention event for the exhausted-chain path."
    - "Capacity-cap displacement: explicit redistribute_to_option_id still works for the single-target case (legacy behaviour). With redistribute_to_option_id=None and strategy='by_registration_order', displaced students walk their own preference chain — same cascade semantics as dissolution, including needs_intervention fall-through."
    - "Manual migrate stays unchanged. Resolving a needs_intervention row patches the existing row in place (preserves identity + created_at) instead of running _perform_student_migration, since there's no prior approved row to mutate."
  closed_audit_items:
    - "B6 (migrated elective not in registered courses list) — closed. The CLOSED-state unified view at /student/registration shows every committed course."
    - "B7 (unified registration with ranked preferences) — closed. Ranked picker on OPEN, locked-in list on CLOSED, auto-cascade through chain on dissolution."
  deferred_to_session_5_or_later:
    - "Session 5: student attendance eligibility surface (consumes compute_subject_eligibility)."
    - "Session 6: IA polish + docs closure (HOD dashboard year-tabbed cards, electives inline in semester-setup, lab batches nested under integrated offerings, teacher dashboard, marks charts)."

audit_session_3:
  status: complete
  date: "2026-05-15"
  scope: "Tasks one-to-many migration — see AUDIT_FINDINGS.md Session 3"
  schema:
    - "Migration 0013_task_assignments — creates task_assignments (id, task_id FK CASCADE, assignee_user_id FK, status, status_updated_at, decline_reason, created_at, updated_at, deleted_at). Partial unique index uq_task_assignments_task_assignee_active on (task_id, assignee_user_id) WHERE deleted_at IS NULL."
    - "Backfill: one task_assignments row per existing tasks row (status, status_updated_at, decline_reason all copied)."
    - "tasks loses the per-assignee columns in the same migration: assigned_to_user_id, status, status_updated_at, decline_reason. Task is now a pure header (who assigned what + when due)."
    - "verify_0013.sql checks: column list, partial unique index, dropped columns, backfill row counts, duplicate-assignment rejection."
  backend:
    - "workflow/models.py — new TaskAssignment ORM (TimestampedMixin + SoftDeleteMixin). Task ORM stripped of the dropped columns."
    - "workflow/schemas.py — TaskAssignmentOut, TaskOut with assignments[] + status_counts + is_complete derived fields, MyTaskAssignmentOut (teacher-side flat row with task header inline), TaskCreate.assignee_user_ids (list, 1-20), TaskAssignmentStatusUpdate."
    - "workflow/service_m10d.py — _validate_assignee_in_dept lifts the cross-dept guard into a reusable helper. create_task walks the assignee list (de-duped, ordered) and writes N TaskAssignment rows in one tx; any cross-dept assignee rolls back the whole creation. list_tasks now joins via task_assignments for the mine/department/status filters. list_my_task_assignments is the teacher-side flat-row endpoint. update_task_assignment_status replaces update_task_status — accept/decline/complete are assignee-only; cancel is assigner/admin-only. Events still publish task.assigned (with assignee_user_ids[]) and task.status_changed (with assignment_id + assignee_user_id)."
    - "workflow/router.py — POST /workflow/tasks accepts list, returns TaskOut. New GET /workflow/task-assignments/mine for the teacher view. New POST /workflow/task-assignments/{id}/status replaces the old per-task /tasks/{id}/status. The old endpoint is removed (was only one call site)."
  tests:
    - "test_m10d.py — existing 5 task tests rewritten for the new shape. +3 new tests: multi-assignee creation (3 assignees), cross-dept-in-list rollback, partial accept/cancel keeps is_complete=False, /task-assignments/mine returns flat rows."
    - "Full suite: 163 passed (160 from Sessions 1–2 + net +3 from this session)."
  frontend:
    - "apps/web/app/hod/tasks/page.tsx — multi-select assignee picker (scrollable checkbox list inside the New-task dialog), row shows per-assignee status chips with inline cancel buttons for pending/accepted; status_counts shown as a row of badges plus a 'done' chip when is_complete=true."
    - "apps/web/app/teacher/tasks/page.tsx — reshaped from row-per-task to row-per-assignment. Hits /workflow/task-assignments/mine (the new flat-row endpoint). Accept/Decline/Complete buttons act on the assignment_id, not the task_id."
  seed:
    - "infra/scripts/seed.py — 8 single-assignee tasks (covers pending/accepted/completed/declined) + 1 three-invigilator task showcasing the new shape. Total: 9 task rows + 11 task_assignment rows."
  authority_choices:
    - "OQ C — same-migration drop. Migration 0013 creates task_assignments + backfills + drops the per-assignee columns from tasks atomically. Cleaner schema, no interim dead column."
    - "Task aggregate state is derived: TaskOut.status_counts + TaskOut.is_complete are computed at read time from the assignment rows. No denormalised aggregate column on tasks. Trade-off: a small O(N_assignments) loop per task in the list path; partial index keeps lookups fast and the dept queue rarely exceeds tens of tasks."
    - "task.assigned event payload changed: assigned_to_user_id → assignee_user_ids (list). task.status_changed gains assignment_id + assignee_user_id so subscribers can scope per-assignee notifications without re-querying."
    - "PUT vs POST /status: kept POST to match the existing /tasks/{id}/status semantics; just the path swapped to /task-assignments/{id}/status."
    - "Cancellation lives on the assignment row, not the task — HOD can cancel one assignee while leaving the rest active. If the entire task should be cancelled, the HOD cancels every assignment individually (typically 1-3 calls). Bulk-cancel-at-task-level can land later if the workflow demands it."
  closed_audit_items:
    - "B15 (tasks one-to-many) — closed."
  deferred_to_session_4_or_later:
    - "Session 4: ranked elective preferences."
    - "Session 5: student attendance eligibility surface."
    - "Session 6: IA polish + docs closure."

audit_session_2:
  status: complete
  date: "2026-05-15"
  scope: "Seed scope narrow + teacher/HOD ad-hoc class sessions — see AUDIT_FINDINGS.md Session 2"
  backend:
    - "academic/service.py — new functions: create_extra_class_session, create_reschedule_exception, create_room_change_exception, list_offering_exceptions, delete_offering_exception. Shared finaliser _commit_offering_exception (flush → IntegrityError → 409 'duplicate_exception', audit row, _rematerialise_for_event, commit, refresh). Shared auth helper _require_offering_actor (admin always wins; teacher must own the offering; HOD must own the course's department)."
    - "academic/service.py — _detach_class_sessions_from_exception helper soft-deletes any class_sessions referencing the exception before the FK delete runs. Both the admin (delete_timetable_exception) and the new teacher/HOD (delete_offering_exception) paths use it. Fixes a latent bug in the existing admin delete that would have raised ForeignKeyViolation whenever the materialiser had already produced a class_session from the exception."
    - "academic/schemas.py — AdHocExtraCreate, AdHocRescheduleCreate, AdHocRoomChangeCreate. Each schema is tight to the kind: extra needs date+times+room; reschedule needs date+times (room optional); room_change needs date+room (times stay from the parent slot)."
    - "academic/router.py — POST /offerings/{id}/timetable-exceptions/{extra,reschedule,room-change}; GET /offerings/{id}/timetable-exceptions (list); DELETE /offerings/{id}/timetable-exceptions/{exception_id}. All five gated by Depends(require_teacher_hod_or_admin) and then by the service-layer ownership check."
    - "attendance/service.py — UNTOUCHED. The materialiser already consumes the four TimetableExceptionKind values; the new endpoints feed rows in the same shape the admin endpoint produced, so re-materialisation works without changes."
  tests:
    - "+10 critical-path tests in test_attendance.py: extra creates class_session of source='extra' (verified by querying ClassSession directly); reschedule anchors to recurring slot; room_change anchors to recurring slot with times NULL; reschedule on a non-slot weekday returns 400 'no_matching_slot'; bad time (end <= start) returns 400; student role rejected by the dependency layer; non-owner teacher → 403 'forbidden'; HOD of other dept → 403; list + delete round-trip works after the FK-detach fix; duplicate reschedule on (slot, date) → 409 'duplicate_exception'."
    - "Full suite: 160 passed (147 baseline + 3 from Session 1 + 10 new ad-hoc tests)."
  frontend:
    - "apps/web/app/teacher/courses/[id]/page.tsx — new course-hub page. Header shows course code+title+term+semester+type, with Configure-scheme and Take-attendance deep links. Ad-hoc panel below with three tabs (Extra / Reschedule / Room change), per-tab react-hook-form + zod schemas, plus a 'Recent exceptions' table with inline delete (confirm dialog → DELETE → refetch). The Configure / Attendance buttons link to the existing /teacher/courses/[id]/scheme and /teacher/attendance pages."
  seed:
    - "infra/scripts/seed.py — DEPT_SPECS cut from 7 depts to 4 (CSE deep + ISE/ECE/CSE-DS stubs). New SCOPE dict + is_deep() / students_per_section(dept_code) / batch_years_for(dept_code) helpers replace the old hardcoded STUDENTS_PER_SECTION=40 and full-BATCH_YEARS sweep."
    - "Deep dept CSE: 2 sections × 30 students × 4 batches = 240 students. Stub depts (ISE, ECE, CSE-DS): 1 section × 5 students × 1 batch (focal year only) = 15 students. Plus 1 legacy student + parents."
    - "Verified row counts after reset+seed cycle: 606 total users (admin 1 + HODs 4 + teachers 15 + students 256 + parents 330), 4 departments, 7 batches, 11 sections, 66 offerings, 868 class_sessions, 26,040 attendance records. Down from 5,950 users + 52K attendance records pre-narrow."
    - "AIML / ME / EEE entries removed from DEPT_SPECS and COURSE_CATALOGUE — the demo no longer touches those departments. Cross-dept walkthrough beats (CSE-DS HOD teaching one CSE course) still work because CSE-DS is one of the stubs."
    - "Focal cohort (CSE 2023 section A) still gets full attendance + marks + hall ticket + grade card history. Legacy test fixtures teacher@bmsce.ac.in, student@bmsce.ac.in (USN 1BM24CS999 enrolled in CSE 2024-A), hod@bmsce.ac.in preserved."
  authority_choices:
    - "OQ B — three endpoints (one per TimetableExceptionKind) over one polymorphic endpoint. Cleaner Pydantic schemas (each kind has its own required fields), simpler error messages, easier UI tab wiring."
    - "Ownership rule for the new endpoints: actor is admin (always), OR teacher == offering.teacher_user_id, OR HOD whose hod_of_department_id matches the course's department. Cross-dept teaching is supported (the cross-dept teacher counts as the offering's teacher and so passes the teacher leg; the HOD leg checks the course's dept, not the teacher's home dept)."
    - "Delete cascade: rather than introduce migration 0013 just to add ON DELETE SET NULL on class_sessions.origin_exception_id, the service soft-deletes dependent class_sessions before deleting the exception. _rematerialise_for_event then rebuilds a clean canonical class_session from the parent slot (for non-extra kinds). Extra-kind sessions just vanish, which matches their semantics — they had no recurring parent."
    - "Seed narrowing kept DEPT_SPECS as the source of truth and added SCOPE on top, instead of rewriting DEPT_SPECS into a richer struct. Smaller diff, easier to revert per-dept if a future walkthrough needs more breadth."
  closed_audit_items:
    - "B2 (ad-hoc class sessions) — closed."
    - "Finding 18 (seed narrow) — closed."
  deferred_to_session_3_or_later:
    - "Session 3: tasks one-to-many migration."
    - "Session 4: ranked elective preferences."
    - "Session 5: student attendance eligibility surface."
    - "Session 6: IA polish + docs closure."

audit_session_1:
  status: complete
  date: "2026-05-15"
  scope: "Visibility gates + role-context indicator — see AUDIT_FINDINGS.md Session 1"
  backend:
    - "service_m10e.get_my_hall_ticket — now requires approved_at IS NOT NULL. Students no longer see HOD-internal pre-approval state. Empty-state UI was already handled."
    - "service_m10e.list_grade_cards — student role filtered to is_finalised=True. HOD/admin paths unchanged so they keep seeing pending cards. History (past finalised cards) remains visible to students through the same endpoint."
    - "service_m10e.render_hall_ticket_pdf_for_version — student actor blocked with 404 not_yet_released until ticket is approved. Ownership check still runs first so cross-student attempts get 403."
    - "service_m10e.render_grade_card_pdf_for_version — student actor blocked with 404 not_yet_released until card is_finalised."
    - "WorkflowError codes added: 'not_yet_released' (404). Ownership errors stay as 'forbidden' (403)."
  tests:
    - "+3 critical-path tests in test_m10e.py: student_sees_no_hall_ticket_until_approved, student_sees_no_grade_card_until_finalised, student_pdf_blocked_until_released. All three cover the pre-release blocked state + post-release unblock path."
    - "Two pre-existing tests updated to match the new contract: test_hall_ticket_pdf_download_streams_pdf now approves before fetching, test_grade_card_pdf_download now uploads SEE before fetching. Both still assert the %PDF magic + content-type."
    - "Full suite: 150 passed (147 baseline + 3 new gating tests)."
  frontend:
    - "apps/web/components/RoleBadge.tsx — new client component. Reads getRole() and a routeContext prop; renders an amber Badge when they differ ('Logged in as HOD · viewing teacher panel'); falls through to a subtle neutral chip when they match."
    - "All five role layouts (admin/hod/teacher/student/parent) — replaced the hardcoded 'Metis · <role>' string with a stacked block: 'Metis' label + RoleBadge. The matching-role case keeps the visual minimal."
    - "/hod/dashboard scheme-readiness card — inline note above the offerings table: 'Configuring a scheme opens the teacher-facing editor in HOD context — you remain logged in as HOD.' Single note above the table (rather than per-row) keeps the table compact."
    - "/student/layout — Hall ticket and Grade card nav entries are now release-gated. Layout mounts call /workflow/hall-tickets/me and /workflow/grade-cards; entries stay visible during the in-flight check (no flash-hide) and only hide once both calls have confirmed empty. Backend gating + UI gating compose: a student with no releases never sees the entries; a student mid-term sees them appear the moment HOD approves."
    - "/student/hall-ticket + /student/grade-card empty-state copy tightened to explicitly mention HOD release / SEE landing as the unblock conditions."
  authority_choices:
    - "F12 — badge only this session (OQ A). Mirroring /teacher/courses/[id]/scheme under /hod/* was deferred. If walkthrough feedback after the badge ships still shows confusion, a Session 1.5 can pick up the route mirror."
    - "F (small) — inline note shipped on /hod/dashboard above the table, not per-row, to avoid repeating the same sentence on every offering."
    - "PDF gating extended to both render functions (not just the list endpoint) so a student who knows a version_id can't bypass the list filter."
    - "Sidebar gating uses 'tri-state' (null while in-flight, false when empty, true when populated). Hide only on false so the user never sees a brief flash where the entry appears then disappears."
  closed_audit_items:
    - "B9 (critical bug) — fully closed by backend gating + 3 new tests."
    - "F12 + F16 — partially closed (badge + dashboard note). Route mirror deferred per OQ A; F16 'HOD-as-teacher CTA' considered already addressed by the existing Configure link plus the new context note."
    - "A8 — student sidebar gating ships with this session."
    - "B1 + Finding 19 — closure notes captured in this state block."
  deferred_to_session_2_or_later:
    - "Session 2: seed narrow + ad-hoc class sessions."
    - "Session 3: tasks one-to-many."
    - "Session 4: ranked elective preferences."
    - "Session 5: student attendance eligibility surface."
    - "Session 6: IA polish + docs closure."

frontend:
  next_app_initialized: true
  tailwind_configured: true
  auth_pages: true
  admin_shell: true
  teacher_shell: true
  student_shell: true   # M10b: Dashboard + Registration nav entries added
  parent_shell: true
  hod_shell: true   # M10c: Lab batches + Scheme templates nav entries enabled
  admin_users_page: true   # shipped in M2 rework
  hod_semester_setup_pages: true   # shipped in M10a (index + editor)
  admin_notifications_page: true   # shipped in M10a
  student_dashboard_page: true   # shipped in M10b
  student_registration_page: true   # shipped in M10b
  hod_electives_page: true   # shipped in M10b
  hod_lab_batches_page: true   # shipped in M10c
  hod_scheme_templates_page: true   # shipped in M10c
  teacher_course_scheme_page: true   # shipped in M10c (/teacher/courses/[id]/scheme)
  teacher_course_hub_page: true   # shipped in audit Session 2 (/teacher/courses/[id]) — header + ad-hoc class session panel
  hod_dashboard_scheme_readiness: true   # shipped in M10c
  hod_cie_schedule_page: true   # shipped in M10d
  hod_tasks_page: true   # shipped in M10d
  teacher_tasks_page: true   # shipped in M10d
  admin_internal_deadlines_page: true   # shipped in M10d
  hod_hall_tickets_page: true   # shipped in M10e
  hod_see_upload_page: true   # shipped in M10e
  hod_re_eval_page: true   # shipped in M10e
  hod_makeup_page: true   # shipped in M10e
  student_hall_ticket_page: true   # shipped in M10e
  student_grade_card_page: true   # shipped in M10e
  student_re_eval_page: true   # shipped in M10e

infrastructure:
  supabase_project_created: false
  upstash_redis_created: false
  r2_bucket_created: false
  qdrant_deployed: false   # M7-only, deferred
  vercel_linked: false
  render_services: []
  sentry_configured: false

demo_seed_state:
  scripts:
    - "infra/scripts/reset_demo.py — TRUNCATE every public table except alembic_version. Preserves migration head (currently 0012). Idempotent + logs row counts."
    - "infra/scripts/seed.py — replaces the v1 seed with a comprehensive BMSCE-shaped demo. Curated Indian names from infra/scripts/_demo_names.py."
    - "Standard cycle: `uv run --project services/api python infra/scripts/reset_demo.py` then `uv run --project services/api python infra/scripts/seed.py`. Full cycle ~10s."
  what_exists_after_seed:
    institution: "1 college (BMSCE), 4 departments (CSE deep + ISE, ECE, CSE-DS stubs). Narrowed in audit Session 2."
    users: "~606 total — 1 admin, 4 HODs, 15 teachers, 256 students (240 CSE + 15 stubs + 1 legacy), 330 parents. CSE has 2 sections per batch × 4 batches × 30 students. Stub depts: 1 batch (focal year only) × 1 section × 5 students. Hashed once and reused (argon2id is expensive)."
    terms: "4 academic_terms — 2025-ODD (archived stub), 2025-EVEN (past, fully populated with SEE), 2026-ODD (current, mid-semester), 2026-EVEN (future skeleton). Registration windows closed for current, open in the future."
    focal_cohort: "CSE 2023 batch (currently sem 7) has the deepest data: full setup + course offerings, ~26K attendance rows across past+current, CIE-1 marks for ~80% of students, full past-term marks + SEE + grade cards. Stub depts carry only minimal rows for the IA cross-references (HOD list, audit feed, etc.)."
    schemes: "3 institutional templates (Theory / Integrated / NPTEL Standard) + 2 dept templates (CSE programming-heavy, ECE lab-heavy). Each offering instantiates from the matching template. CSE-Sem7-Compiler-Design has AAT=30% with an `assessment_scheme_unlock` academic_override audit row."
    electives: "CSE Professional Elective III has 4 options — one healthy, one under-strength (HOD-dashboard callout), one dissolved with 3 migrated students. CSE-DS has its own Domain Elective II group."
    workflow_data: "120 hall_tickets (HOD-approved), 120 grade_cards (one in v2 with trigger_reason='see_released' for the focal student #1), 98 see_results (96 originals + 2 re-eval revised), 2 re_evaluations (improved + held), 42 CIE schedule entries (CIE-1 + CIE-2 published), 9 tasks + 11 task_assignment rows (1 of those tasks has 3 assignees in mixed states post-Session-3), 8 internal_deadlines, 5 academic_overrides (condonations + scheme unlock + lab incharge + mark unlock + student migration), 11 admin_notifications. Session 4 adds: ~154 course_registration_preferences (65 rank-1 + 55 rank-2 + 34 rank-3 across focal cohort), 4 course_registrations.status='migrated' rows (3 demo cascade + 1 needs_intervention paired migrated), 1 course_registrations.status='needs_intervention' row (driving the HOD intervention queue on /hod/electives)."
    events: "Best-effort `publish()` calls fire for `semester_setup.published` (7 events) and `grade_card.regenerated` (1 event from the v2 trigger). The M10d subscriber writes admin_notifications when running; the seed also writes them directly so /admin/notifications has content even when Redis is offline."
  walkthrough_logins:
    password: "MetisDemo!2026"
    accounts:
      - "admin@bmsce.ac.in — admin"
      - "hod@bmsce.ac.in — CSE HOD (focal dept). Legacy address so existing pytest fixtures keep working."
      - "hod-ise@bmsce.ac.in (and hod-ece, hod-cse-ds) — stub-dept HODs."
      - "teacher-cse-1@bmsce.ac.in (and -2 through -8) — CSE teachers. Stub depts have teacher-{ise,ece,cse-ds}-1 / -2."
      - "student-1bm23cs001@bmsce.ac.in — focal student (CSE 2023, USN 1BM23CS001). Has a v2 grade card from the late-SEE flow."
      - "parent-1bm23cs001-1@bmsce.ac.in — focal student's first parent."
      - "teacher@bmsce.ac.in + student@bmsce.ac.in — legacy demo users retained for test_marks / test_academic / test_m2_rework fixtures. The student carries USN 1BM24CS999 and is enrolled in CSE-2024-A current term."
  notes:
    - "PDFs (hall ticket + grade card) are seeded with `inline:{version_id}` URLs matching the M10e convention. The /workflow/hall-tickets/{version_id}/download and /workflow/grade-cards/{version_id}/download routes regenerate bytes from the snapshot JSON on demand. R2 wiring stays deferred."
    - "RNG is seeded deterministically (random.Random(2026_05_15)) so re-running yields identical row counts (verified)."
    - "departments.name column already existed at migration 0007 — no new migration was needed for the demo seed."
```

---

## SCREEN INVENTORIES

> Each module's session must wire every screen listed. shadcn-style primitives only.

### `/admin/*`
- **/admin/users** — table (name, email, **USN**, role, dept, status); filters; bulk CSV import; role inline edit; activate/deactivate; onboarding status badge
- **/admin/parents/bulk-csv** — file upload, validate CSV (USN must match a student), preview, commit; emails credentials to parents
- **/admin/academic** — Departments / Courses (with NPTEL type) / Batches / Sections / Rooms / Course-Offerings / Timetable / Calendar
- **/admin/scheme-catalog** — Assessment scheme templates (institutional baseline; can flag department-specific)
- **/admin/terms** — Academic term CRUD, term_type (regular/fast_track schema-ready), boundary dates, registration windows
- **/admin/cie-windows** — Institutional CIE windows (e.g., "CIE-1 must fall in weeks 5–7")
- **/admin/see-schedule** — SEE date scheduling across departments
- **/admin/eligibility-config** — Institutional threshold config (attendance 60%/85%, CIE 40%/60% main/makeup)
- **/admin/internal-deadlines** — Institutional hard-stop deadline per term
- **/admin/notifications** — Feed of HOD publish events, condonations >10%, escalations
- **/admin/reports** — Attendance compliance, performance, AICTE export
- **/admin/system** — Health metrics, feature flags, audit log viewer, system config
- **/admin/audit** — Full audit log with filters (actor / action / entity / date range)

### `/hod/*` (NEW)
- **/hod/dashboard** — Department-wide summary: published-setup status, defaulter list, eligibility status, CIE schedule, tasks I assigned, condonations pending, my teaching offerings (link to /teacher)
- **/hod/semester-setup** — Draft / edit / publish semester structure; courses (incl. NPTEL), electives, integrated configs, tentative teacher assignments; "Publish" = self-publish (admin notified)
- **/hod/parents/bulk-csv** — Same as admin but scoped to own dept students
- **/hod/electives** — Live elective enrollment counts; dissolve / migrate / cap actions; cascade preview before commit
- **/hod/lab-batches** — Per-integrated-course batch composer (flexible count); assign batch incharges
- **/hod/cie-schedule** — Calendar view of CIEs across all department courses; date/time/venue/order; publish to students
- **/hod/tasks** — Assign invigilation/paper-setting/evaluation tasks to department teachers; track status (pending/accepted/completed/declined)
- **/hod/attendance-overrides** — Condonations queue; approve up to 10%
- **/hod/hall-tickets** — Generate for department, batch-approve, regenerate on policy change
- **/hod/see-upload** — CSV upload form for SEE results per course offering
- **/hod/re-eval** — Re-evaluation requests queue; upload revised CSV (improve-or-hold enforced)
- **/hod/makeup** — Authorise makeup CIE (rare); schedule makeup exams; upload makeup results
- **/hod/scheme-templates** — Department-specific scheme templates (extending the admin catalog)
- **/hod/analytics** — Department-wide attendance, marks distribution, defaulter list, eligibility heatmap

### `/teacher/*`
- **/teacher/dashboard** — Assigned offerings card grid (course, section, student count, attendance %, pending grading); today's classes; tasks assigned to me; quick actions
- **/teacher/courses/{offering_id}** — Course hub with tabs: Overview / Attendance / Marks / Assignments / Materials / Roster / Analytics
  - **Overview tab** — course info, students, batch breakdown if integrated, assessment scheme config
  - **Attendance tab** — take attendance (theory or per-batch for lab), QR mode, manual mode, overrides, historical editor, freeze button
  - **Marks tab** — assessment list, entry table with live stats, CSV upload, lock/unlock, edit log per row; for NPTEL offerings shows different layout (assignments + final exam split + certificate verification)
  - **Assignments tab** — list, create new, view submissions, grade; portal/offline modes; parent visibility toggle per assignment
  - **Materials tab** — uploads (M6 plumbing — placeholder until M6 ships)
  - **Roster tab** — student list with detail panel; private teacher notes
  - **Analytics tab** — class-level + per-student trends; defaulter list; eligibility status
- **/teacher/tasks** — Tasks assigned by HOD; accept/decline; mark complete
- **/teacher/insights** — Empty state placeholder; "Insights Engine not yet enabled" (M8 plug-in point)
- **/teacher/students/{usn}** — Cross-offering student detail page (only for students in offerings I teach)
- **/teacher/profile** — Same as M1 profile screen

### `/student/*`
- **/student/dashboard** — Current courses, attendance summary with safe/warning/critical badges, upcoming deadlines, pending assignments, internal marks overview, recent announcements, eligibility warnings, backlog courses (if any), NPTEL pending courses (carry-over)
- **/student/registration** — Open only during registration window; mandatory courses (auto-enrolled), elective group pickers (pick one per group), NPTEL slot picker (pick specific NPTEL course name); submit; status badge per choice
- **/student/courses/{offering_id}** — Course detail: info, faculty (theory teacher, lab batch incharges if integrated, my specific batch highlighted), tabs:
  - Attendance: overall %, CIE eligibility (per-CIE 60%), SEE eligibility (85%), session history, lab vs theory split
  - Marks: dynamic rendering based on assessment scheme (theory shows best-2-of-3 + AAT; integrated shows lab + best-2-of-3 + AAT; NPTEL shows assignments + final exam); SEE pending state shown as "Pending"
  - Assignments: pending/submitted/graded; submit (PDF/JPG/DOC/ZIP/text/multi-attach); view feedback
  - Materials: notes/PPTs/PDFs (M6 ready)
- **/student/hall-ticket** — Download hall ticket PDF (when generated by HOD); shows eligibility per subject (NA for ineligible)
- **/student/grade-card** — Download grade card PDF per semester; version history accessible; latest by default
- **/student/re-eval** — Request re-evaluation per course within HOD-set window; track status
- **/student/backlog** — Failed/ineligible courses; auto-registered in current semester; makeup exam schedule
- **/student/tutor** — Placeholder route; "Tutor coming soon" (M7 plug-in point)
- **/student/notifications** — Notifications feed (M5 plumbing)
- **/student/profile** — Standard profile + face enrollment + privacy centre

### `/parent/*`
- **/parent/dashboard** — Child picker (if multiple); attendance summary, internal marks, eligibility, upcoming deadlines, pending assignments, risk indicators, recent announcements (only those marked visible to parents)
- **/parent/courses/{offering_id}** — Same as student's course view but read-only; faculty contact info surfaced
- **/parent/marks** — Read-only marks table with breakdown; same scheme rendering as student
- **/parent/assignments** — Pending/submitted/late/missing/graded; teacher feedback only if teacher toggled visible
- **/parent/hall-ticket** — Download child's hall ticket
- **/parent/grade-card** — Download child's grade card
- **/parent/notifications** — Parent-visible notifications only
- **/parent/profile** — Standard profile; first-login forces password change

---

## ADR TEMPLATE

Every major technical decision goes in `docs/adr/ADR-NNN-title.md`.

```
# ADR-NNN: [Decision Title]
## Status: Accepted | Superseded by ADR-XXX | Deprecated
## Context
What is the problem or situation being decided?
## Decision
What did we decide?
## Consequences
What are the trade-offs? What becomes easier? What becomes harder?
## Alternatives Considered
- Option A: [description] — rejected because [reason]
- Option B: [description] — rejected because [reason]
```

---

## PRIVACY & COMPLIANCE (DPDP Act 2023)

```
Consent:           Explicit required before face biometric collection. Opt-out available
                   (fallback: teacher manual mark).
Purpose limit:     Face data only for attendance verification.
Data minimisation: Frame used for verification → immediately discarded. Embedding not stored.
Right to access:   Students request all personal data via Privacy Centre in app.
Right to erasure:  Student-initiated. Anonymised analytics retained for institutional reporting.
Breach notif:      Report to Data Protection Board within 72 hours.
Data fiduciary:    The college (BMSCE) is fiduciary. Metis is data processor → DPA agreement needed.

Parent data:       Parents are linked to students via guardian_links. Parent accounts have
                   strict per-request validation of parent-child link. No cross-student access.

Face data technical policy:
  Enrolled photo → FaceNet embedding (when M8 lands) → stored AES-256 encrypted in users table.
  Decryption key: environment variable (NOT in database).
  Attendance submission: live frame → M8 → cosine similarity → result returned → frame + live embedding
  DELETED FROM MEMORY. Persisted: attendance_records.verification_confidence FLOAT only.
```

---

*Metis CLAUDE.md — v2.0 — Frontend: bare-bones functional. Full platform first, AI last. Five-role model (Admin/HOD/Teacher/Student/Parent). BMSCE regulations anchor. Update MODULE STATUS TABLE and ACTIVE MODULE STATE after every session.*
