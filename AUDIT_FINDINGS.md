# Metis — Walkthrough Audit & Rework Plan

> **How to run this plan**:
> 1. **Save this file in the repo** as `AUDIT_FINDINGS.md` at repo root, commit and push. Every future session reads from there.
> 2. **For each session**: open a fresh Claude Code session, paste the matching kick-off prompt from the "Kick-off prompts" section at the bottom of this file. That prompt is self-contained — it tells the new session which scope to work on and which open questions to confirm before writing code.
> 3. **At the end of each session**: ask the running Claude to wrap up (commit, push, update CLAUDE.md state) and to produce the kick-off prompt for the next session (it can copy the one in this file, plus any in-flight context).
> 4. **Open questions** specific to a session are surfaced in that session's kick-off prompt. Answer them inline before letting Claude write code.

---

## Context

The Metis academic platform reached a walkthrough-ready state at the end of the previous session (5,949 seeded users, M10a–e shipped, 147/147 tests passing). The user performed a thorough role-by-role walkthrough and surfaced 19 findings spanning real bugs, workflow-logic gaps, IA problems, and seed-scale concerns. This audit:

1. Reads the actual code for every finding and reports what the system does today.
2. Surfaces additional issues the walkthrough didn't catch.
3. Proposes a 6-session sequence to land the rework without bundling too much into any single session.
4. Calls out open architectural decisions that need the user's input before execution.

Modules in scope: shipped surfaces (M1, M2 rework, M10a–e) and seed. Out of scope: M3/M4 rework (already planned), M5/M6/M9/M11 (not started), and the entire AI layer (M7/M8 deferred).

---

## CRITICAL FINDINGS

Three items the user should know up front:

1. **B9 — Hall ticket and grade card always visible to students.** `get_my_hall_ticket` in `service_m10e.py:1010-1073` returns whatever exists regardless of `approved_at`. `list_grade_cards` returns regardless of `is_finalised`. Per the user's spec these are timed events — student should not see anything until HOD approves. **Action: gate both endpoints in Session 1.**

2. **F12 — Not a security bug; an IA bug.** I verified the auth layer (`apps/web/lib/auth.ts`, teacher layout line 34). JWT and localStorage role do NOT swap when an HOD navigates to `/teacher/courses/[id]/scheme` — the teacher layout simply *accepts* the HOD role and renders its own sidebar + hardcoded "Metis · teacher" topbar string. The HOD then clicks a teacher sidebar link and lands deeper into the teacher app while still authenticated as HOD. Reading their own (HOD's) data, but in teacher chrome. **Action: role badge + better routing in Session 1.**

3. **Finding 19 — Git dual-remote IS working.** Both `Prajwalkiran1/Metis` and `deepthi-sm/Metis` are at `3c8ba54` (52 commits). The "14 commits in deepthi's repo" the user saw was a stale GitHub UI view. **No action needed; document only.**

---

## PHASE 1 — Audit of the User's 19 Findings

Each finding is reported with: what the code does today (paths + key references), accuracy verdict, severity, and complexity.

### Teacher findings

#### B1. Manual attendance — User says "only QR UI."
- **Today**: `apps/web/app/teacher/attendance/page.tsx:366-389` has a per-student "Mark present" button in the live feed that calls `PATCH /attendance/sessions/{id}/override` (backend at `services/api/app/modules/attendance/router.py:176-204`). The endpoint accepts either a `record_id` (override an existing flagged record) or a `student_user_id` in body (create a fresh recorded row).
- **Verdict**: **WRONG** as stated — the UI already has manual marking. It's just visually subordinate to the QR display.
- **Severity**: docs / IA-polish.
- **Complexity**: small (just document in CLAUDE.md; optionally rearrange the page so manual marking is more obvious).

#### B2. Ad-hoc class sessions for rescheduled classes.
- **Today**: `ClassSession` rows are created by the materialiser (`services/api/app/modules/attendance/service.py:107-305`) from `timetable_slots` minus holidays, applying `timetable_exceptions`. The `ClassSessionSource` enum has `materialised | extra | on_demand`, but `on_demand` has no writer. `TimetableException` schema supports `extra | reschedule | room_change` — but **no teacher-facing endpoint exists** to insert exception rows. Teachers cannot self-service room/time changes.
- **Verdict**: **CORRECT** — the schema is ready but the API surface isn't.
- **Severity**: workflow-logic (real BMSCE workflow requires this).
- **Complexity**: medium (new router endpoint + service guard + Pydantic schemas + small UI panel).

#### F3. Teacher dashboard with weekly timetable.
- **Today**: No `/teacher/dashboard` page exists. `/teacher/page.tsx` simply redirects to `/teacher/attendance` (apps/web/app/teacher/page.tsx:1-12). No timetable view anywhere in teacher-facing pages.
- **Verdict**: **CORRECT** — feature missing entirely.
- **Severity**: IA-polish.
- **Complexity**: medium (new page + leverage existing `TimetableSlot` query endpoints).

#### B4. "Create new assessment" button doesn't work; no courses listed.
- **Today**: `apps/web/app/teacher/marks/page.tsx:146-149` calls `GET /course-offerings?teacher_user_id=me.id`. The endpoint works. The legacy demo `teacher@bmsce.ac.in` user has **zero offerings assigned** in the seed (only the structured `teacher-cse-1@…` etc. get assignments).
- **Verdict**: **WRONG** as a bug; it's a **seed-data** symptom of the user logging in as `teacher@bmsce.ac.in`.
- **Severity**: seed-data.
- **Complexity**: small (assign the legacy teacher to one offering in the seed, or default the demo walkthrough to `teacher-cse-1@…`).

#### F5. Empty tasks tab for the test teacher account.
- **Today**: `apps/web/app/teacher/tasks/page.tsx` queries `/workflow/tasks?mode=mine`. The seed only assigns tasks to CSE teachers; non-CSE teachers see empty.
- **Verdict**: **CORRECT** — confirmed seed-data issue. Resolved by scope narrowing (Finding 18) or by adding one task per dept to the seed.
- **Severity**: seed-data.
- **Complexity**: small.

### Student findings

#### B6. Migrated elective not visible in registered courses list.
- **Today**: `service_m10b.py:273-457` `get_student_registration_view` returns `mandatory_courses` (table at top of page) and `groups` with `chosen_option_id` per group. After migration, the new course_registration row is `status='approved'` and the picker correctly highlights the new option. **But** the chosen elective is shown as a "picked option within a group", not surfaced in a consolidated "my registered courses" list alongside the mandatory ones.
- **Verdict**: **PARTIAL** — the data is correct; the IA is split. The user's expectation is a unified post-window "here are my N courses for this term" view.
- **Severity**: workflow-logic / IA — folded into B7 below.
- **Complexity**: medium when bundled with B7.

#### B7. Unified registration with ranked preferences.
- **Today**: Single-pick electives (`CourseRegistration` table has no `preference_rank` column). The `submit_student_registration` endpoint takes one option per group. Dissolution cascade in `service_m10b.py:1110-1200` requires the **HOD to pick the target option** — there's no per-student fallback chain. Capacity caps exist (`elective_group_options.max_enrollment`) but only enforced at submission time, not as part of dissolution arbitration.
- **Verdict**: **CORRECT** — none of ranked prefs, auto-fallback, or unified-locked-view exists today.
- **Severity**: workflow-logic.
- **Complexity**: large (new schema, cascade rewrite, UI state machine).

#### F8. Attendance % with eligibility indicators (CIE-60%, SEE-85%).
- **Today**: `apps/web/app/student/attendance/page.tsx` shows today's session list with state badges. No attendance % aggregation, no eligibility badges. M10e's `compute_subject_eligibility` (`service_m10e.py:220-280`) is fully implemented but **no UI consumer exists**.
- **Verdict**: **CORRECT** — eligibility surface is missing from the student view.
- **Severity**: workflow-logic.
- **Complexity**: medium (read-only consumer of an existing function; pure UI + thin aggregator endpoint).

#### B9. Hall ticket / grade card visibility gating.
- **Today**: Confirmed by direct read of `service_m10e.py:1010-1073` (`get_my_hall_ticket`) — no `approved_at` check, returns whatever exists. Same pattern for `list_grade_cards`. The student-facing pages always render whatever the endpoint returns.
- **Verdict**: **CORRECT — and the most concrete bug in the audit.**
- **Severity**: critical-bug (information disclosure of unapproved data).
- **Complexity**: small (one predicate per endpoint; existing history endpoint preserved for past versions).

#### F10. Marks visualisations weak.
- **Today**: `apps/web/app/student/marks/page.tsx` imports recharts (lines 5-16) but the rendering is a flat assessment table; no actual chart components are mounted. Library installed; visualisation not built.
- **Verdict**: **CORRECT** — defer to polish.
- **Severity**: IA-polish.
- **Complexity**: small (wire the already-installed library).

### HOD findings

#### F11. Dashboard flat 149-row table.
- **Today**: `apps/web/app/hod/dashboard/page.tsx:265-301` maps `teaching_offerings` into a linear table. The data shape is already nested-ready (offering has course, section, batch, year). Year-tabbed cards is a pure rendering refactor.
- **Verdict**: **CORRECT** — table is flat; year-tabbed cards is queryable from existing data.
- **Severity**: IA-polish.
- **Complexity**: medium (rendering refactor; no backend changes).

#### F12. "Configure" navigation → user perceives role swap.
- **Today** (verified by deep read):
  - `apps/web/app/hod/dashboard/page.tsx:223` `Configure →` link routes to `/teacher/courses/{id}/scheme`.
  - `apps/web/app/teacher/layout.tsx:34` accepts `hod` role explicitly (the comment on line 31-33 calls this out: "HODs follow links here from /hod/electives to configure schemes on offerings they don't necessarily teach").
  - `apps/web/app/teacher/layout.tsx:48-50` hardcodes the topbar string to `"Metis · teacher"`.
  - `apps/web/lib/auth.ts` — JWT is in localStorage; role is also in localStorage. **Neither is mutated by navigating to `/teacher/*`.** JWT remains the HOD's; role remains `hod`.
- **Verdict**: **CORRECT as a user complaint, but NOT a security bug.** The HOD is still authenticated as HOD; the UX simply lies about it. Once on `/teacher/*`, the teacher sidebar appears (Attendance / Marks / Tasks) and the HOD might click into one and see their own offerings (filtered as a teacher), reinforcing the "I'm in a teacher account" perception.
- **Severity**: critical-IA (perception of role swap is dangerous in an academic context even if the underlying auth is sound).
- **Complexity**: small (role badge + topbar showing actual role; optionally mirror the scheme editor under `/hod/*` so HODs never leave their app — see OPEN QUESTION A).

#### F13. Electives as sub-feature of semester setup.
- **Today**: Two surfaces manage the same data:
  - `apps/web/app/hod/semester-setup/[id]/page.tsx:54-82` already has nested `elective_groups: ElectiveGroup[]` with full CRUD for groups + options inline.
  - `apps/web/app/hod/electives/page.tsx` is a separate top-level page that duplicates enrollment-management views.
  Both surfaces work; they're duplicate IA.
- **Verdict**: **CORRECT** — the standalone page is redundant.
- **Severity**: IA-polish.
- **Complexity**: medium (consolidate UI; preserve deep-link redirects).

#### F14. Lab batches nested under integrated course offering.
- **Today**: `/hod/lab-batches` is a top-level page. The semester-setup detail page doesn't surface lab batches per offering — you navigate elsewhere to manage them.
- **Verdict**: **CORRECT** — nested IA would be more discoverable.
- **Severity**: IA-polish.
- **Complexity**: medium (route restructure + page extraction).

#### B15. Tasks one-task-per-teacher.
- **Today** (`services/api/app/modules/workflow/models.py:608-655`): `Task.assigned_to_user_id` is a single NOT NULL column. `service_m10d.py` create_task accepts one assignee. There is **no multi-assign surface**.
- **Verdict**: **CORRECT** — real workflows (paper-setting committee, multi-invigilator) cannot be modelled today.
- **Severity**: workflow-logic.
- **Complexity**: large (new `task_assignments` table, migration, cascade, list/update aggregation, UI multi-select).

#### F16. HOD-as-teacher view switching.
- **Today**: HOD can navigate to `/teacher/*` mechanically (layout accepts role) but no visible context switcher, no "I'm an HOD viewing teacher" indicator. Overlaps F12.
- **Verdict**: **CORRECT** — solved largely by F12's role badge.
- **Severity**: workflow-logic / IA.
- **Complexity**: small (CTA addition on /hod/dashboard).

### Admin

#### F17. Admin function inventory.
- **Today** — Wired admin pages:
  - `/admin/academic` — tabbed CRUD for departments, courses, batches, sections, rooms, course-offerings, timetable, academic-calendar (~10 sub-tabs)
  - `/admin/users` — table + bulk CSV import + status flip
  - `/admin/notifications` — feed for HOD publish events + condonations + dissolutions
  - `/admin/internal-deadlines` — institutional-hard + visibility into dept-soft + per-course rows
  
  Stubs (disabled in nav): `/admin/reports`, `/admin/system`. M9 (Admin Portal + Analytics) is explicitly "not started" per CLAUDE.md.
- **Verdict**: **CORRECT** — admin is minimal by design; the user perception of "data is a mess" is real because admin/academic is a 10-tab pile.
- **Severity**: IA-polish (M9 will replace).
- **Complexity**: large (M9 scope — out of audit cycle).

### Cross-cutting

#### Finding 18. Narrow seed scope.
- **Today**: `infra/scripts/seed.py` hardcodes 7 depts × 4 batches × 2-3 sections × 40 students = ~2,560 students, ~5,949 users, ~52K attendance records. Walkthrough is slow; data is overwhelming for a demo.
- **Verdict**: **CORRECT** — narrowing to 1 deep dept (CSE) + 3 stub depts halves the wall-clock and tightens the walkthrough story.
- **Severity**: seed-data.
- **Complexity**: small (refactor 5-6 loop bounds + a SCOPE config dict at the top of `seed.py`).

#### Finding 19. Git remote mismatch.
- **Today** (verified by `git ls-remote`):
  - `origin` push fans out to `Prajwalkiran1/Metis` + `deepthi-sm/Metis` (deepthi's repo is in `origin`'s second push URL).
  - Both remotes are at `3c8ba549946703a0f6e0bf799b59e762e3ff5ae6` (current HEAD = 52 commits).
  - `upstream` is also `deepthi-sm/Metis` (over HTTPS).
- **Verdict**: **WRONG** — the dual push is working correctly. The "14 commits in deepthi's repo" is a stale GitHub UI cache or the user looked at a different fork.
- **Severity**: docs.
- **Complexity**: small (note this in CLAUDE.md so future-you doesn't redo the diagnosis).

---

## PHASE 2 — Additional Findings the Walkthrough Didn't Surface

### A1. Zero frontend test coverage.
- No `.test.tsx`, no `vitest`, no jest, no playwright in `apps/web/`. Every backend module has tests (147 passing); the entire frontend ships untested.
- **Severity**: workflow-logic (regression risk grows with each session).
- **Complexity**: medium (setup vitest + react-testing-library + first few tests). Recommend a separate "frontend testing hardening" session OR fold into Session 6 (turns it into 2 days).

### A2. localStorage-based JWT storage.
- `apps/web/lib/auth.ts` stores access token in localStorage (XSS-readable). CLAUDE.md flags this for "M1-hardening." Refresh token rotation works but no token-family reuse detection (`auth/service.py:13-16` has a TODO).
- **Severity**: security (low-impact MVP; non-blocker for academic use case but should be fixed before any external-network deployment).
- **Complexity**: medium (migrate to httpOnly cookies; needs SSR cookie reading too).

### A3. `compute_subject_eligibility` has no UI consumer.
- The M10e function is fully implemented and tested but no page renders attendance %, CIE-60%, or SEE-85% badges to the student. This is the backend half of F8.
- **Severity**: workflow-logic.
- **Complexity**: small (aggregator endpoint + page).

### A4. Deprecated `grade_rules` table still in use.
- `services/api/app/modules/marks/service.py:1144, 1192` still reads/writes `grade_rules`. The migration plan deprecates this in favour of `assessment_schemes`. M4 rework will migrate consumers; CLAUDE.md tracks this. **Not an audit-cycle issue**; flagged for visibility.
- **Severity**: workflow-logic (held by M4 rework).
- **Complexity**: medium (held by M4).

### A5. Schema-ready tables with no consumer.
- `course_drops`, `eligibility_snapshots`, `nptel_enrollments` are declared in models and migrated, but no service reads or writes them. All three are intentional stubs (per `MIGRATION_PLAN.md` lines 352, 595, 618). **No action needed**; documenting.
- **Severity**: docs.

### A6. SEE result keyed by enrollment, not by (enrollment, course_offering).
- The partial unique index in `service_m10e.py` ensures **one current SEE row per enrollment**, but enrollment is per-section-not-per-course. The seed was forced to write one SEE row per student (not per subject) and represent per-subject grades inside the `grades_snapshot` JSON. The M10e service has the same constraint. This is **by design** per `MIGRATION_PLAN.md:1054` but it does limit the granularity of SEE re-evaluation when a single student wants to re-eval only one subject's marks among several.
- **Severity**: workflow-logic (might surface as a real limitation in production; not blocking now).
- **Complexity**: large (schema change + cascade rewrite if we want per-subject SEE).
- **Recommendation**: **document** the constraint clearly; revisit only if BMSCE policy requires per-subject re-eval rather than per-term.

### A7. N+1 risk in cascade loops.
- `service_m10b.py` dissolve + migrate loops fetch student lists with `.all()` then iterate. At seed scale (~640 focal-batch students, max ~30 per option) this is fine. If scale grows past 100 students per migration, eager-load joins should be considered.
- **Severity**: docs (monitor; not yet a real problem).

### A8. Pages whose enabled state isn't gated by readiness.
- `/student/hall-ticket` and `/student/grade-card` show "Loading…" then "no ticket yet" rather than being **hidden** from the sidebar when nothing is available. Better UX: hide the nav entry or show a clear "not yet released" state. Overlaps B9.
- **Severity**: IA-polish (folds into Session 1).

### A9. Events fire but no external subscriber.
- `event_bus.publish()` is called liberally throughout M10 (`semester_setup.published`, `grade_card.regenerated`, etc.). The only in-process subscriber today writes admin_notifications. M5/M7/M8 will subscribe later. No bug; AI deferral is intentional.
- **Severity**: docs.

---

## PHASE 3 — Proposed Session Sequence (6 sessions)

Rationale: bug-class first (cheap, restores correctness) → foundation (seed + small schema) → schema-heavy workflow rewrites → IA polish + docs wrap-up. Each session is sized to be executable as a single Claude Code session with its own end-state.

### Session 1 — Visibility gates + role-context indicator
**Size:** 1-day · **Depends on:** none

**Issues addressed:** B9 (critical bug), F12 (role IA), F16 (HOD-as-teacher CTA), B1 (docs), A8 (sidebar gating)

**Backend** — `services/api/app/modules/workflow/service_m10e.py`
- `get_my_hall_ticket` (line 1010): add `approved_at IS NOT NULL` predicate.
- `list_grade_cards` (line 2210): add `is_finalised = True` predicate for "current" view; keep history endpoint open for past-released cards.
- Update existing M10e tests to cover the gated paths (currently the tests likely auto-approve before reading).

**Frontend** — apps/web/
- New `components/RoleBadge.tsx`: reads role from localStorage, displays `<actual role>` vs `<route context>`, highlights when they differ.
- Wire `RoleBadge` into all five role layouts (`{admin,hod,teacher,student,parent}/layout.tsx`). Topbar string becomes dynamic, not hardcoded.
- `/hod/dashboard`: where HOD also teaches an offering, add a small "Open in teacher view" CTA.
- `/student/hall-ticket` + `/student/grade-card`: gracefully handle the gated 404 with a "not yet released by HOD" state.
- Hide `/student/hall-ticket` and `/student/grade-card` sidebar entries until at least one is available.

**Docs** — `CLAUDE.md`
- Note that B1 (teacher manual attendance) already ships in the UI.
- Note Finding 19 (git dual-remote) is verified working.

**Out of scope**: route reorganisation (whether to mirror scheme editor under `/hod/*` — see OPEN QUESTION A); JWT migration to cookies; M3 attendance rework.

---

### Session 2 — Seed scope narrow + ad-hoc class sessions
**Size:** 1-day (tight; can spill if seed regressions catch you) · **Depends on:** Session 1

**Issues addressed:** Finding 18 (scope narrow), B2 (ad-hoc sessions)

**Seed** — `infra/scripts/seed.py`
- Refactor to a SCOPE config dict at top of file: `{ "CSE": "deep", "ISE": "stub", "ECE": "stub", "CSE-DS": "stub" }`.
- Deep dept: 4 batches × 2 sections × 30 students × full workflow data (CSE focal).
- Stub depts: 1 batch × 1 section × 5 students; no electives, no lab batches, no SEE.
- Target totals: ~300 users, ~5K attendance records.
- Update existing test fixture assertions that depend on seed counts.

**Backend** — `services/api/app/modules/academic/`
- New endpoint `POST /academic/offerings/{id}/timetable-exceptions` (teacher or HOD scoped).
- Pydantic per `TimetableExceptionKind`: `extra` (date+time+room), `reschedule` (original_slot+new_date+new_time), `room_change` (slot+new_room).
- Service-layer ownership guard: actor must be the offering's teacher OR the dept's HOD.
- Existing materialiser already reads `TimetableException` — no changes needed there.

**Frontend** — `apps/web/app/teacher/courses/[id]/page.tsx`
- New "Record ad-hoc session" panel: kind tabs (Extra / Reschedule / Room change), form, list of recent exceptions for this offering, delete row.

**Tests** — `services/api/tests/`
- New cases for teacher creating each `TimetableExceptionKind`, and rejection when the actor doesn't own the offering.
- Update any test count assertions that fail against the narrower seed.

**Out of scope**: HOD override of teacher-created exceptions; bulk import; M3 attendance rework.

---

### Session 3 — Tasks one-to-many migration
**Size:** 2-day · **Depends on:** Session 1, Session 2 (tests/seed must be green first)

**Issues addressed:** B15 (multi-assign tasks)

**Schema** — new migration `0013_task_assignments.py`
- Create `task_assignments` table: `(id, task_id, assignee_user_id, status enum, decline_reason, status_updated_at, created_at)`.
- Unique constraint on `(task_id, assignee_user_id)` where status != 'deleted'.
- Backfill from existing `tasks.assigned_to_user_id` → one row per task.
- Drop `tasks.assigned_to_user_id` at end (or keep nullable + deprecated — OPEN QUESTION C).

**Backend** — `services/api/app/modules/workflow/`
- `models.py`: new `TaskAssignment` model + `Task` model loses single-assignee.
- `service_m10d.py`: `create_task(assignee_user_ids: list[UUID])` writes N rows in one tx; list/read paths aggregate by task.
- `router.py`: `POST /workflow/tasks` accepts list; `GET /workflow/tasks?mode=mine` returns my assignments joined with task; `GET /workflow/tasks?mode=assigned-by-me` returns aggregate.
- `schemas.py`: `TaskAssignmentRead` shape; `TaskCreate.assignee_user_ids` required non-empty.

**Frontend** — apps/web/
- `/hod/tasks/page.tsx`: multi-select teacher picker; row shows task + per-assignee status chips.
- `/teacher/tasks/page.tsx`: each teacher sees their own assignments only; data shape shifts from row-per-task to row-per-assignment.

**Tests**
- New: single-assignee (backwards-compat), three-assignee, partial accept/decline, all-decline, assignee removed.
- Update existing test_m10d task suites.

**Out of scope**: notification fan-out beyond current event publication; CSV import.

---

### Session 4 — Unified registration + ranked elective preferences
**Size:** 3-day (biggest piece in this cycle) · **Depends on:** Session 3

**Issues addressed:** B6 + B7 + F13 (partial — IA consolidation lands in Session 6)

**Schema** — new migration `0014_registration_preferences.py`
- New table `course_registration_preferences`: `(id, student_user_id, semester_setup_id, elective_group_id, course_id, preference_rank smallint CHECK 1<=rank<=N, created_at)`. Unique `(student, group, rank)`. Rank 1 maps to today's "chosen option".
- Existing `course_registrations` stays the committed-enrolment table. After window-close, the rank-1 (or surviving) preference is written into `course_registrations`.
- Backfill: existing single-pick rows become rank 1.

**Backend** — `services/api/app/modules/workflow/service_m10b.py`
- `submit_student_registration` accepts ranked prefs per slot.
- New `dissolve_elective_with_preferences` cascade: walks the rank chain — when rank 1 dissolves, move student to rank 2 if it exists and isn't full; otherwise rank 3; otherwise mark as needing manual HOD intervention.
- Capacity arbitration: deterministic order (registration_order or rank-then-time), matching existing displaceable logic.
- Emit existing `student.migrated` events with new metadata `{from_rank: 1, to_rank: 2, slot_id, depth}`.
- "Window status" endpoint that returns `is_open | locked_in` for the frontend.

**Frontend** — apps/web/
- `/student/registration/page.tsx`: full rewrite. Two states:
  - **OPEN**: unified picker. Mandatory courses shown as auto-enrolled, non-interactive. Each elective slot shows the option grid with rank selectors (1st/2nd/3rd dropdowns) for each option, OR a drag-to-rank UI.
  - **LOCKED**: single "My registered courses for Term X" table — one row per course, status column (Enrolled / Migrated-from-Y / Backlog).
- HOD electives view: keep `/hod/electives` for this session; show chain-depth info for migrations. Move to Session 6.

**Seed**
- Demo students get 3-rank preferences for elective slots.
- One end-to-end dissolution test scenario: dissolve rank-1, see migrants walk to rank-2.

**Tests**
- Single-pick legacy (rank-1-only submission).
- Full 3-rank submission.
- Dissolution rank-1 → rank-2 happy path.
- Rank-2 also full → rank-3 fallback.
- All preferences exhausted → HOD-intervention flag.
- Capacity-displacement during window-close finalisation.
- Re-submit edits in the same window.
- Window-closed submission rejection.

**Out of scope**: NPTEL UX redesign; backlog auto-registration changes; live capacity counters (cache concerns); moving `/hod/electives` page into semester-setup (Session 6).

---

### Session 5 — Student attendance eligibility surface
**Size:** 2-day · **Depends on:** Session 1 (role badges) and ideally Session 2 (narrowed seed makes tests fast). Independent of Sessions 3/4.

**Issues addressed:** F8 (eligibility indicators), A3 (consume `compute_subject_eligibility`)

**Backend** — `services/api/app/modules/attendance/`
- New endpoint `GET /attendance/me/eligibility-summary?term_id=...` (student-scoped).
- Service aggregator: loop the student's active enrollments, call `service_m10e.compute_subject_eligibility` per offering, return list of `{ offering_id, course_code, attendance_percent, cie_threshold_met, see_threshold_met, condonation_applied_percent }`.
- Cross-module import: confirm acceptable (m10e exports compute_subject_eligibility; attendance imports it).

**Frontend** — apps/web/
- `/student/attendance/page.tsx`: add per-course header card (attendance % large, CIE-60% green/red badge, SEE-85% green/red badge, condonation banner when applied).
- Optionally mirror to parent view if `/parent/attendance` exists.

**Tests**
- Synthetic attendance distributions: above 85, between 60 and 85, below 60.
- Condonation applied path.

**Out of scope**: M3 rework itself; live recompute on attendance entry (events already fire); F10 marks charts.

---

### Session 6 — IA polish + docs closure
**Size:** 1-day (push to 2 if frontend tests added — OPEN QUESTION E) · **Depends on:** Sessions 1–5

**Issues addressed:** F11 (HOD dashboard cards), F13 (full move of electives), F14 (lab-batches nesting), F3 (teacher dashboard), F10 (marks charts), final docs

**Frontend** — apps/web/
- `/hod/dashboard/page.tsx`: year-tabbed cards (group teaching offerings by batch year), needs-attention block at top.
- `/hod/semester-setup/[id]/page.tsx`: inline electives CRUD inside the setup detail; `/hod/electives` page becomes a redirect or is deleted; sidebar entry removed.
- Lab batches: nest under integrated course offering tab; remove top-level `/hod/lab-batches` (or redirect).
- New `/teacher/dashboard/page.tsx`: weekly timetable grid (Mon-Fri) using existing `TimetableSlot` reads.
- Marks pages: render 1–2 charts each (distribution + section average) using the already-installed recharts.

**Docs**
- `CLAUDE.md`: mark audit closed; update module status table; capture B1, F12, B9 closure notes; add post-rework walkthrough hints.
- `MIGRATION_PLAN.md`: add migrations 0013 + 0014.

**Tests**
- Manual smoke + visual review (no frontend test infra in this session unless answered yes in OPEN QUESTION E).

**Out of scope**: frontend test framework setup (separate hardening session — see A1); httpOnly cookie migration (separate); refresh-token reuse detection (separate); M4 grade_rules removal (held by M4 rework); any AI work.

---

## PHASE 4 — Open Questions

These are decisions where multiple reasonable approaches exist. Recommendation is given but not locked in.

### A. F12 — Badge only, or also mirror scheme editor under `/hod/*`?
The role badge (Session 1, planned) addresses the perceived swap. Mirroring `/teacher/courses/[id]/scheme` under `/hod/courses/[id]/scheme` is more semantically correct (HOD never leaves their app) but duplicates a non-trivial page (~700 lines). 

**Recommendation**: ship the badge in Session 1. If user feedback after walkthrough still shows confusion, mirror in a small Session 1.5. Confirm before starting Session 1.

### B. B2 — One polymorphic `POST /timetable-exceptions` endpoint or three?
Three (`/extra`, `/reschedule`, `/room-change`) is explicit and matches the three `TimetableExceptionKind` values; easier validation. One polymorphic with a discriminated union is fewer routes but fiddlier Pydantic. 

**Recommendation**: three endpoints. Confirm before Session 2.

### C. B15 — Drop `tasks.assigned_to_user_id` same migration, or deprecate-then-drop?
Same-session drop is cleaner. Deprecation gives a safety window but adds complexity. Only one read and one write site reference the column today (verified by grep). 

**Recommendation**: same-session drop. Confirm before Session 3.

### D. B7 — New `course_registration_preferences` table, or extend `course_registrations` with `preference_rank` + flag?
- Extending `course_registrations`: simpler join, but the table becomes a mix of "candidate" and "committed" rows; cascade gets harder.
- New preferences table: cleaner separation (intent vs commitment); `course_registrations` keeps its current well-tested cascade semantics.

**Recommendation**: new table. Confirm before Session 4.

### E. F11/F3/F10 polish + frontend tests in Session 6?
Currently 0% frontend test coverage. Session 6 adds three pages and edits more. Options:
- **Defer** test infra to a separate "frontend hardening" session — Session 6 stays 1-day, polish ships fast, tests follow.
- **Fold in** vitest + react-testing-library + first 5 tests — Session 6 becomes 2-day; polish + foundational tests ship together.

**Recommendation**: defer test infra. Confirm before Session 6.

### F. Should the user-facing walkthrough finding "I ended up in a teacher account" (F12) get a one-paragraph explanation in the in-product release notes?
The badge alone might not fully explain why the user perceived a swap. A short note in the HOD dashboard explaining "configuring a scheme opens the teacher-facing editor under HOD context — you remain logged in as HOD" could pre-empt re-discovery.

**Recommendation**: yes, add an inline note next to the Configure button. Tiny addition to Session 1.

### G. Ranked preferences depth — fixed 3 ranks or N?
Three is the BMSCE-typical pattern (1st/2nd/3rd choice). Some institutions use rank-all. Locking to 3 keeps the UI simple and the cascade bounded. 

**Recommendation**: cap at 3; document the limit as a configurable institutional policy in case future BMSCE-derived deployments want different.

### H. Should Session 2 (seed narrow) keep the legacy `student@bmsce.ac.in` enrolled in the surviving CSE 2024-A section, or move them to the deep dept's focal section (CSE 2024-A) with a fresh USN?
The legacy fixture is wired into multiple tests; keep their USN stable. The deep dept happens to be CSE so the existing enrollment carries over cleanly. **Recommendation**: keep. Trivial.

---

## Top 5 Most Important Findings (chat summary)

1. **B9 — Visibility gating bug** (information disclosure). Hall ticket + grade card return data regardless of approval/finalisation. Fix in Session 1.
2. **F12 — IA role confusion** (not a security bug). HOD clicks Configure → teacher chrome wraps the page → perceived as role swap. Fix with role badge in Session 1.
3. **B7 — Registration model rewrite**. Ranked preferences + auto-fallback + unified locked-in view is a 3-day rewrite (Session 4) touching schema, cascade, and the entire registration UI.
4. **B15 — Tasks one-to-many**. New `task_assignments` table + cascade + UI. 2 days (Session 3), feels small but the migration must be airtight.
5. **Finding 18 — Seed narrow** is the cheapest big-impact change. ~1 hour of seed.py editing for a 10× walkthrough speedup; foundation for everything that follows.

Plus one more not in the user's list:
- **A6 — SEE one-per-enrollment** is an underspecified design that limits per-subject re-eval. Not blocking now; flag for documentation. Document before BMSCE policy review.

---

## Sequence Summary

| # | Session | Size | Depends on |
|---|---|---|---|
| 1 | Visibility gates + role badge | 1d | — |
| 2 | Seed narrow + ad-hoc sessions | 1d | 1 |
| 3 | Tasks one-to-many | 2d | 1, 2 |
| 4 | Unified registration + ranked prefs | 3d | 3 |
| 5 | Student attendance eligibility | 2d | 1 |
| 6 | IA polish + docs | 1d | 1–5 |

Total: ~10 days across 6 sessions, depending on parallelisation of Session 5 with the schema sessions.

---

## Execution Order

1. **Step 0 (one-time setup)**: Copy this file's body to `AUDIT_FINDINGS.md` at repo root, commit it, and push. The file is the durable plan reference; every session reads from there.
2. **For each session**, open a fresh Claude Code session and paste the corresponding kick-off prompt below.
3. **Sessions run in order** (1 → 6); Session 5 can run in parallel with 3/4 if desired.

---

# Kick-off Prompts

Paste the matching prompt into a fresh Claude Code session, then let it run.
Every prompt assumes the working directory is the Metis repo root.

---

## Session 1 — Kick-off Prompt

```
You are executing Session 1 of the Metis post-audit rework plan. Read these
files at repo root before doing anything else:

  CLAUDE_HEADER.md       # commit voice rules — no AI attribution
  CLAUDE.md              # project intelligence (current state)
  AUDIT_FINDINGS.md      # the full audit plan — find Session 1 there
  MIGRATION_PLAN.md      # schema reference

Session 1 scope: "Visibility gates + role-context indicator". The exact
issue list, file paths, and out-of-scope are spelled out in AUDIT_FINDINGS.md
under "Session 1". Do not deviate from that scope.

OPEN QUESTION A (must be confirmed before writing code):
For F12, ship the role badge in Session 1 only, OR also mirror the scheme
editor route under /hod/courses/[id]/scheme so HODs never leave their app?
Default recommendation: badge only. Confirm with me.

OPEN QUESTION F (small):
Add an inline note next to the "Configure" button on /hod/dashboard
explaining "configuring a scheme opens the teacher-facing editor in HOD
context — you remain logged in as HOD"? Default recommendation: yes.

Contract:
- No AI attribution in commits (per CLAUDE_HEADER.md). No Co-Authored-By,
  no "Generated with Claude Code" lines.
- All 147 backend pytest tests must still pass at end of session.
- Frontend must compile cleanly (Next.js dev server should boot without
  type errors).
- Commit in logical groupings (backend gating, frontend role badge, docs).
- Do not push. I'll review then push.
- Update the ACTIVE MODULE STATE block in CLAUDE.md at end of session.

When done:
  1. Run pytest and report 147 pass.
  2. Spot-check /student/hall-ticket and /student/grade-card in the browser
     to confirm gating renders cleanly.
  3. Stage commits, present diffs for review.
  4. Produce the kick-off prompt for Session 2.

Start by reading the four files above, confirming the open questions
with me, then proposing your task list before writing code.
```

---

## Session 2 — Kick-off Prompt

```
You are executing Session 2 of the Metis post-audit rework plan. Read at
repo root: CLAUDE_HEADER.md, CLAUDE.md, AUDIT_FINDINGS.md, MIGRATION_PLAN.md.

Session 2 scope: "Seed scope narrow + ad-hoc class sessions". Full details
in AUDIT_FINDINGS.md under "Session 2".

Goals:
  1. Narrow seed to 1 deep CSE dept (4 batches × 2 sections × 30 students)
     plus 3 stub depts (ISE, ECE, CSE-DS) with skeletal data only. Target
     ~300 users total, ~5K attendance rows.
  2. Ship the teacher self-service ad-hoc class session endpoint (creates
     TimetableException rows of kind extra | reschedule | room_change),
     plus the UI panel on /teacher/courses/[id].

OPEN QUESTION B (confirm before writing):
One polymorphic POST /timetable-exceptions endpoint OR three (/extra,
/reschedule, /room-change)? Default recommendation: three endpoints,
matches the three TimetableExceptionKind values.

Contract:
- No AI attribution in commits.
- All backend tests must still pass after seed narrowing (some assertions
  about row counts will need adjustment — update them).
- The teacher ad-hoc endpoint must enforce: actor teaches this offering OR
  is HOD of its dept.
- The exceptions must flow through the existing materialiser without
  changes to attendance/service.py (read-only verification).
- Do not push. I'll review.
- Update CLAUDE.md state block at end.

When done:
  1. Run pytest with the narrowed seed: 147 pass.
  2. Run reset_demo + seed: report new row counts (target ~300 users).
  3. Manual smoke: teacher creates an "extra" session, attendance materialises.
  4. Commit; produce Session 3 kick-off prompt.

Start by reading the docs, confirming OQ B with me, then proposing the
task list.
```

---

## Session 3 — Kick-off Prompt

```
You are executing Session 3 of the Metis post-audit rework plan. Read at
repo root: CLAUDE_HEADER.md, CLAUDE.md, AUDIT_FINDINGS.md, MIGRATION_PLAN.md.

Session 3 scope: "Tasks one-to-many migration". Full details in
AUDIT_FINDINGS.md under "Session 3".

Goal: extend the Task model from one-assignee-per-task to N. New table
`task_assignments`, migration 0013, cascade through service_m10d.py,
update HOD and teacher tasks UIs.

OPEN QUESTION C (confirm before writing):
Drop tasks.assigned_to_user_id in the same migration that creates
task_assignments? Or deprecate-then-drop across two migrations? Default
recommendation: same-migration drop (only one read site and one write
site reference the column).

Contract:
- No AI attribution in commits.
- Migration 0013 must backfill cleanly from existing rows (one assignment
  row per old task).
- All M10d tests must be updated for the new shape; all 147 still pass.
- HOD tasks UI gets a multi-select teacher picker.
- Teacher tasks UI still shows row-per-assignment-for-me.
- Do not push.
- Update CLAUDE.md.

When done:
  1. Run migration; verify backfill.
  2. Run pytest: 147 pass.
  3. Re-seed; smoke-test HOD creates a 3-invigilator task → all 3 teachers
     see it; one accepts, two decline; HOD sees aggregate.
  4. Commit; produce Session 4 kick-off prompt.

Start by reading the docs, confirming OQ C with me, then proposing the
task list.
```

---

## Session 4 — Kick-off Prompt

```
You are executing Session 4 of the Metis post-audit rework plan. Read at
repo root: CLAUDE_HEADER.md, CLAUDE.md, AUDIT_FINDINGS.md, MIGRATION_PLAN.md.

Session 4 scope: "Unified registration with ranked preferences". This is
the biggest single session in the plan — schema change, cascade rewrite,
full /student/registration UI rewrite. Full details in AUDIT_FINDINGS.md
under "Session 4".

Goal: students rank elective options (1st/2nd/3rd choice) per slot during
registration. On dissolution, the cascade auto-walks the preference chain.
After window closes, the registration page shows a single "My registered
courses" list — no more picker, electives folded inline with mandatory.

OPEN QUESTIONS for this session:

D. Registration schema shape:
   - new course_registration_preferences table (clean separation between
     intent and committed enrolment), OR
   - extend course_registrations with preference_rank + chosen flag?
   Default recommendation: new table.

G. Preference depth: fixed 3 ranks, or N? Default: 3 (BMSCE-typical),
   document as institutional policy.

Contract:
- No AI attribution.
- New migration 0014_registration_preferences.
- Backfill: existing single-pick rows become rank 1.
- Cascade tests are critical — every dissolution path must walk the chain
  correctly, including rank-N-also-full → manual HOD intervention.
- All 147 backend tests must pass; new cases added for the chain walk.
- /student/registration becomes a state machine: window OPEN (picker) vs
  window CLOSED (locked-in view).
- Do not push.
- Update CLAUDE.md.

When done:
  1. Run migration; verify backfill.
  2. Re-seed: focal students should have 3-rank prefs.
  3. End-to-end test: dissolve a rank-1 option, see students walk to rank-2.
  4. Run pytest: 147+ pass.
  5. Commit; produce Session 5 kick-off prompt.

Start by reading the docs, confirming OQs D and G with me, then proposing
the task list. Brainstorm the cascade logic before writing it; this is
the trickiest piece in the plan.
```

---

## Session 5 — Kick-off Prompt

```
You are executing Session 5 of the Metis post-audit rework plan. Read at
repo root: CLAUDE_HEADER.md, CLAUDE.md, AUDIT_FINDINGS.md, MIGRATION_PLAN.md.

Session 5 scope: "Student attendance eligibility surface". Full details in
AUDIT_FINDINGS.md under "Session 5".

Goal: surface attendance % alongside CIE-60% and SEE-85% eligibility
badges on /student/attendance, by consuming the existing
compute_subject_eligibility function in M10e.

No open questions for this session — the design is well-pinned.

Contract:
- No AI attribution.
- New endpoint: GET /attendance/me/eligibility-summary (student-scoped).
- Backend aggregator loops the student's enrollments, calls
  compute_subject_eligibility per offering, returns the list.
- Frontend renders per-course header cards (attendance %, CIE badge,
  SEE badge, condonation banner if applied).
- All 147+ backend tests pass; new test_attendance_eligibility_view.py
  covers thresholds.
- Do not push.
- Update CLAUDE.md.

When done:
  1. Run pytest.
  2. Smoke: log in as student-1bm23cs001@bmsce.ac.in, see eligibility
     badges across courses.
  3. Commit; produce Session 6 kick-off prompt.

Start by reading the docs, then proposing the task list.
```

---

## Session 6 — Kick-off Prompt

```
You are executing Session 6 of the Metis post-audit rework plan (the
final session in this cycle). Read at repo root: CLAUDE_HEADER.md,
CLAUDE.md, AUDIT_FINDINGS.md, MIGRATION_PLAN.md.

Session 6 scope: "IA polish + docs closure". Full details in
AUDIT_FINDINGS.md under "Session 6".

Goals:
  1. HOD dashboard: flat 149-row table → year-tabbed cards (group by
     batch year, needs-attention block at top).
  2. Inline electives CRUD inside /hod/semester-setup/[id]; delete or
     redirect /hod/electives top-level page; remove sidebar entry.
  3. Nest lab batches under integrated course offering tabs; remove
     top-level /hod/lab-batches sidebar entry.
  4. New /teacher/dashboard with weekly timetable.
  5. Wire 1–2 recharts charts on student and teacher marks pages
     (already-installed library).
  6. Final CLAUDE.md update: mark audit closed, log all closures,
     update module status table.
  7. Final MIGRATION_PLAN.md update: log migrations 0013 + 0014.

OPEN QUESTION E (confirm before writing):
Ship Session 6 without frontend test infrastructure (vitest + react
testing library), OR fold a minimal test setup into this session?
Default recommendation: defer test infra to a separate hardening session.

Contract:
- No AI attribution.
- All 147+ backend tests still pass.
- Manual smoke + visual review of every refactored page.
- Do not push the final commits until I've reviewed.

When done:
  1. Run pytest.
  2. Run dev server, walk through every refactored page.
  3. Verify CLAUDE.md state block is up to date.
  4. Commit; report the full audit cycle as complete.

Start by reading the docs, confirming OQ E with me, then proposing the
task list. This is the wrap-up — be thorough about checking the earlier
sessions didn't leave any half-finished surfaces.
```

---

## After the cycle

Once Session 6 ships, the audit cycle is closed. Future sessions in scope:
- Frontend test infrastructure (vitest + RTL) — was deferred from Session 6.
- localStorage → httpOnly cookie JWT migration (M1-hardening).
- Refresh token reuse detection (M1-hardening).
- M3 attendance rework (separate plan; held by the M3 ACTIVE state in CLAUDE.md).
- M4 marks rework (consumes assessment_schemes; removes grade_rules).
- M5 comms, M6 content, M9 admin, M11 assignments — fresh module sessions per CLAUDE.md.
- AI layer (M7/M8) — only when academic core stabilises.
