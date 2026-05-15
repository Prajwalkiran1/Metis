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
| M10 Academic Workflow | 🟡 M10a + M10b shipped | Yes (workflow module live) | M10a: SemesterSetup CRUD + self-publish + admin_notifications + event bus publisher. M10b: registration window, student elective registration, HOD elective dissolution + cascade (course_registrations + enrollments cross-section + lab_batch_members + academic_overrides in one transaction), manual migrate, capacity cap, dissolve preview, /student/dashboard + /student/registration + /hod/electives. **M10c–e pending.** | — (for M10c) |
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
active_module: M10b_shipped

# Local DB head is now 0012 after M10b. Full pytest suite passes (100 tests).
# Next session is M10c (Lab Batches + Assessment Scheme Templates +
# per-offering picker UI). Boot order remains:
#   docker compose -f infra/docker/docker-compose.yml up -d
#   cd services/api && uv run alembic upgrade head
#
# Seed academic_calendar fix shipped this session — the lookup now uses
# scalars().first() instead of scalar_one_or_none() so dev DBs with
# pre-existing duplicate rows don't crash the seed.

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
    status: m10a_and_m10b_shipped
    skeleton_live: true
    scope: "NEW MODULE — see docs/modules/M10.md"
    sub_sessions:
      a: "✅ shipped — Semester Setup CRUD + self-publish (HOD draft → active in one transaction); admin_notifications feed; HOD pages + admin notifications page; event bus publisher stub with stable payload contract"
      b: "✅ shipped — Registration window, student elective registration (idempotent), HOD elective dissolution + cascade (4 tables in one tx), manual single-student migration, capacity cap with by_registration_order / manual modes, dissolve preview (read-only blast radius), /student/dashboard + /student/registration + /hod/electives, /hod/dashboard under-subscribed callout"
      c: "Lab Batches + Assessment Scheme Templates + per-offering picker"
      d: "CIE Scheduling + Tasks + Internal Deadlines + Event Bus (Redis pub/sub, real subscriber side)"
      e: "Hall Tickets + Grade Cards + SEE/Re-eval/Makeup workflows"
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
    blocked_by: none
    next_session_picks_up_at: "M10c — Lab Batches + Assessment Scheme Templates + per-offering picker UI"

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

frontend:
  next_app_initialized: true
  tailwind_configured: true
  auth_pages: true
  admin_shell: true
  teacher_shell: true
  student_shell: true   # M10b: Dashboard + Registration nav entries added
  parent_shell: true
  hod_shell: true   # M10b: Electives nav entry enabled
  admin_users_page: true   # shipped in M2 rework
  hod_semester_setup_pages: true   # shipped in M10a (index + editor)
  admin_notifications_page: true   # shipped in M10a
  student_dashboard_page: true   # shipped in M10b
  student_registration_page: true   # shipped in M10b
  hod_electives_page: true   # shipped in M10b

infrastructure:
  supabase_project_created: false
  upstash_redis_created: false
  r2_bucket_created: false
  qdrant_deployed: false   # M7-only, deferred
  vercel_linked: false
  render_services: []
  sentry_configured: false
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
