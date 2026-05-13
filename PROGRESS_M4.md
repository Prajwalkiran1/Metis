# M4 — Marks Service: Complete

Last updated: 2026-05-13.

Status: ✅ **complete** (backend + teacher FE + student FE + parent FE). Next module: M5 — Communication Service.

---

## Where M4 fits

M4 is the second module that *consumes* M2 directly. Each `assessment` lives under a `course_offering`, so the teacher binding (M2) and tenant scope (M1) flow into every mark write. M4 also introduces the **first non-M1 user role**: `parent`. The `guardian_links` table is the auth-side join — admin verifies a parent ↔ student relationship and from then on the parent can read (only) the linked student's history through `/parent/marks`.

`marks_audit` is a **distinct table** from M1's cross-cutting `audit_logs`. It captures the value-level history (old → new per mark) that powers the `/teacher/marks` edit-log Dialog. `write_audit()` still fires on every M4 write into `audit_logs` for the standard actor/action trail.

The event bus (`marks.updated`, `assessment.created`, `assessment.locked`) is still deferred — `TODO(events)` markers note the publish sites in `marks/service.py`. M5 will likely be the trigger to actually build the bus, since its features need read-after-write notification.

Where M3 went out of its way to consume M2 in-transaction (`_rematerialise_for_event`), M4 reads M2 but never has to write back into it. So no new lazy-import bridges were needed.

---

## Endpoints shipped

```
# Assessments (lifecycle)
POST   /api/v1/assessments                       teacher/admin; 201
                                                 body: { course_offering_id, type, name, max_marks, weight_percent?, scheduled_date? }
GET    /api/v1/assessments                       authenticated; scoped by role
                                                 filters: ?course_offering_id ?type ?state ?include_deleted ?limit ?offset
GET    /api/v1/assessments/{id}                  scoped (teacher of offering / enrolled student / admin)
PATCH  /api/v1/assessments/{id}                  teacher/admin; rejects mutation when locked unless actor=admin
DELETE /api/v1/assessments/{id}                  teacher/admin; 204; rejected if any marks exist
PATCH  /api/v1/assessments/{id}/lock             teacher/admin; body { lock: bool, reason? }
                                                 - lock=true: state→locked, child marks flip to mark.state=locked + marks_audit row each
                                                 - lock=false: admin only; reason required
GET    /api/v1/assessments/{id}/roster           teacher of offering / admin; one row per enrolled student + current mark
GET    /api/v1/assessments/{id}/stats            teacher of offering / admin; mean/median/stddev/min/max over non-absent marks

# Marks
PUT    /api/v1/marks/{assessment_id}/{student_user_id}  teacher/admin; single-cell upsert; old/new captured in marks_audit
                                                        body: { marks_obtained?, is_absent, reason? }
PUT    /api/v1/marks/bulk                               teacher/admin; multipart: file=CSV, assessment_id, dry_run
                                                        best-effort: valid rows commit, invalid rows returned with codes
                                                        CSV headers: student_uid, marks_obtained, is_absent
GET    /api/v1/marks/{student_user_id}/history          self / linked parent / teacher / admin
                                                        filters: ?course_offering_id
GET    /api/v1/marks/{mark_id}/audit                    teacher of offering / admin; chronological value-level trail

# Grade rules (per course_offering)
GET    /api/v1/grade-rules?course_offering_id={uuid}    authenticated; falls back to a sensible default ruleset
                                                        if no rows exist for the offering
PUT    /api/v1/grade-rules                              teacher/admin; replace-all per offering
                                                        body: GradeRuleSet (weights must sum to 100)

# Parent (read-only)
GET    /api/v1/parent/children                          role=parent; verified-linked students only
GET    /api/v1/parent/marks                             role=parent; per-child marks history

# Admin guardian-link management
POST   /api/v1/admin/guardian-links                     admin; auto-creates a parent-role user with status=active
                                                        when parent_email is new; returns a one-time `parent_initial_password`
DELETE /api/v1/admin/guardian-links/{id}                admin; 204; hard-deletes the link row
```

All writes call `write_audit()` before commit. All reads/writes are tenant-scoped on `actor.college_id`. No rate limits on M4 endpoints — the CSV endpoint is admin-protected at the role level and treated as trusted.

---

## Files shipped

| Path | Role |
|---|---|
| `services/api/app/modules/marks/__init__.py` | Module marker |
| `services/api/app/modules/marks/models.py` | 5 ORM models + 4 enums (assessment_type, assessment_state, mark_state, guardian_relationship) |
| `services/api/app/modules/marks/schemas.py` | All Pydantic request/response models — incl. CSV `MarkBulkResponse`, `AssessmentRosterRow`, `ParentMarksView`, `StudentMarksHistory`, `MarkAuditEntry` |
| `services/api/app/modules/marks/service.py` | Assessment CRUD + lock cascade, single + bulk mark upsert, stats (Python `statistics`), student history, mark audit, grade rules upsert, parent + guardian link ops |
| `services/api/app/modules/marks/router.py` | All 17 endpoints; `_to_http()` bridges `MarksError` to `HTTPException`; multipart CSV via `UploadFile` + `Form` |
| `services/api/alembic/versions/0006_marks_schema.py` | Creates 4 new enums + 5 tables + indexes; attaches `set_updated_at` triggers on `assessments`, `marks`, `grade_rules`; full downgrade; **idempotent `ALTER TYPE user_role ADD VALUE 'parent'`** |
| `services/api/tests/test_marks.py` | 22 pytest cases — assessment CRUD + lock/unlock + role gating, single + bulk mark entry + above-max + non-enrolled rejection, dry-run CSV, stats incl. absent exclusion, student self-only history, grade-rule sum-to-100 + default ruleset, parent link + view + cross-student denial, mark audit timeline, roster ordering |
| `services/api/alembic/env.py` | +1 import line registering the marks models |
| `services/api/app/main.py` | +1 import + `app.include_router(marks_router, ...)` |
| `services/api/app/modules/users/models.py` | `UserRole.parent` added to the Python enum (matches the new Postgres enum value) |
| `apps/web/lib/api.ts` | FormData bodies pass through unmodified (multipart CSV upload works without forcing application/json) |
| `apps/web/lib/auth.ts` | `Role` union extended to include `"parent"` |
| `apps/web/app/login/page.tsx` | Login routes the `parent` role to `/parent/marks` |
| `apps/web/app/teacher/layout.tsx` | Marks nav item enabled (was `disabled: true`) |
| `apps/web/app/student/layout.tsx` | Marks nav item enabled |
| `apps/web/app/teacher/marks/page.tsx` | Full inventory: offering picker, assessment picker + "+ New" Dialog, marks-entry Table (live save on blur + absent toggle), client-side stats row, server-stats reconciliation, outlier badge, CSV upload→Validate→Commit, lock/unlock toggle with reason prompt, assessments history Card, per-row history Dialog calling `/marks/{id}/audit` |
| `apps/web/app/student/marks/page.tsx` | Full inventory: assessment table, percentile-vs-mean summary, recharts radar (subject avg %), recharts trend line (per-subject %), grade projection (current_total + need-SEE-for-pass + need-SEE-for-distinction) from `/grade-rules`, lazy-loaded jsPDF export |
| `apps/web/app/parent/layout.tsx` | New role-gated shell; rejects non-`parent` roles |
| `apps/web/app/parent/page.tsx` | Redirects `/parent` → `/parent/marks` |
| `apps/web/app/parent/marks/page.tsx` | Child Select dropdown (from `/parent/children`) + read-only marks table for the chosen child |
| `apps/web/package.json` | +`recharts@^2.13`, +`jspdf@^2.5`, +`jspdf-autotable@^3.8` |
| `PROGRESS_M4.md` | This file |

---

## Tables added (migration 0006)

| Table | Notes |
|---|---|
| `assessments` | Per `course_offering`; mutable until locked. Partial unique `(course_offering_id, type, name) WHERE deleted_at IS NULL`. Soft-delete. State enum `draft|open|locked` (we currently use `draft`↔`locked`; `open` is reserved for a future "students-can-see" flag). `locked_at` + `locked_by_user_id` snapshot the lock action. |
| `marks` | One row per `(assessment_id, student_user_id)`. NOT soft-deleted — losing marks would erase student history. CHECK `(is_absent XOR marks_obtained)` enforces the mutual exclusion. Cap of 1000 is a sanity ceiling; the real bound (`assessment.max_marks`) is service-validated cross-row. |
| `grade_rules` | Per `(course_offering_id, assessment_type)`. Teacher-replaceable as a set; weights must sum to 100 (service-checked). No soft-delete (rules are a current-state lookup). |
| `marks_audit` | Append-only `BigInteger` PK trail. Stores `action`, `old_value/new_value` as JSONB. Indexed by `(mark_id, created_at)` and `(assessment_id, created_at)` so the FE Dialog and any per-assessment audit queries are fast. |
| `guardian_links` | Read-only parent ↔ student verified mapping. `verified_at` is the gate that lets the parent see marks. Unique `(parent_user_id, student_user_id)`. |

The `user_role` enum is extended with `parent` via `ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'parent'` — Postgres 12+ allows this inside a transaction; the new value is only read after commit so alembic's standard transactional-DDL wrapper is fine.

Triggered tables (have `updated_at`): `assessments`, `marks`, `grade_rules`. The append-only tables (`marks_audit`, `guardian_links`) have no `updated_at`.

---

## Decisions worth remembering

| Decision | Choice | Why |
|---|---|---|
| Mark mutability | Marks mutable in place; corrections trail in `marks_audit` | The teacher's natural flow is "fix the typo and move on"; an append-only `marks` table would have made the entry UI either tombstone-aware or surprisingly inconsistent. `marks_audit` is the durable record, not `marks`. |
| Lock semantics | `assessment.state` boolean-ish enum + cascade to `mark.state`. Teacher can lock; only admin can unlock, with a required `reason` | Simpler than a full state machine; the audit trail captures intent. Cascading to per-mark `state` lets future queries cheaply ask "is this mark frozen?" without joining back to assessments. |
| Audit table separation | New `marks_audit` table distinct from `audit_logs` | `audit_logs` is one row per write across the whole app; the FE per-mark history Dialog would need a full-table scan with filters to render. The denormalised JSONB old/new + indexed `(mark_id, created_at)` matches the access pattern exactly. |
| Grade-rule scope | Per `course_offering` × `assessment_type` | Teacher autonomy: one teacher can weight CIE1=15/CIE2=15/CIE3=15/SEE=50/assignment=5 and another can flip to assignment=15/SEE=40. Per-college would force a single weighting across departments; per-course would force every teacher of CS301 to agree. Per-offering is the right granularity. |
| Grade-rule storage | Replace-all on PUT (DELETE existing, INSERT new) | Atomic + matches the FE form's "edit the whole set" UX. Avoids partial-update races where two of three rule rows get committed and weights no longer sum to 100. |
| Default grade rules | Hardcoded fallback (CIE1=15, CIE2=15, CIE3=15, SEE=50, assignment=5, lab=0) when no rows exist | New offerings just work — the teacher can render the FE and see meaningful projection numbers before they bother to configure rules. The default matches VTU's standard internal/external split. |
| CSV upload semantics | Best-effort: per-row validation, valid rows commit, invalid rows returned with `{row_number, student_uid, code, message}` | The alternative (atomic batch) forces the teacher to either fix the CSV externally or accept all-or-nothing for a 60-student class. Best-effort + dry-run gives the same safety with better ergonomics. |
| CSV library | stdlib `csv.DictReader` | pandas/polars would add ~30MB to the wheel for one parsing call. The CSV is dozens of rows; stdlib is plenty. |
| Stats computation | Python `statistics` stdlib on demand; no Redis cache | Per-assessment populations are ≤120 students; computing mean/median/stddev is microseconds. Caching would add an invalidation cost on every mark write. |
| Parent role mechanism | New value on the `user_role` enum + new `guardian_links` table; admin-managed verified link; no parent self-signup | The verification step (`verified_at`) is the real ACL gate. Self-signup would require email-verify infrastructure we don't have yet. The `/admin/guardian-links` endpoint returns a one-time `parent_initial_password` so the admin can hand it over directly. |
| Parent access scope | Parent can only read marks for `verified_at IS NOT NULL` links; cross-student `/marks/.../history` returns 403 | Tightest sensible default; widening (e.g., admin override) can come later. |
| Cross-row CHECK on max_marks | Enforced in `service.set_mark` against `assessment.max_marks`; DB CHECK is only the sanity ceiling (≤1000) | Postgres CHECK can't reference another table. The service-layer check returns a friendly `above_max_marks` 409 with both values, which the FE shows verbatim. |
| Roster endpoint | New `GET /assessments/{id}/roster` returning `(student_user_id, name, usn, mark)` | Without it the teacher page would need to N+1 `/users/{id}` per row to fill in names. One JOIN at the API replaces 30+ FE calls. |
| Outlier flag | Client-side z-score |z|>2 against the current draft mean/stddev | Cheap, no server round-trip per keystroke. Server stats are still fetched after each save to reconcile so the badge is honest at rest. |

---

## Frontend — what shipped

### Teacher (`/teacher/marks`)
- **Pickers**: offering Select (lists every offering taught by `me`), assessment Select inside that offering, "+ New" Dialog to create CIE/SEE/assignment/lab. The Dialog uses plain `useState` + manual validation (no react-hook-form here because the form is 4 fields and the existing courses-tab pattern is the only place RHF lives so far).
- **Marks-entry Table** with one row per enrolled student. USN | Name | Marks Input (number) | Absent Toggle | Outlier badge | Saved indicator | "history" Button.
  - Save-on-blur (numeric) and save-on-toggle (absent).
  - Disabled when `assessment.state === "locked"`.
  - Client-side z-score outlier flag using the current draft set.
- **Stats footer**: client-side `(count, absent, mean, median, stddev, min, max)` updates as the teacher types; server-side stats reconciled after each save (`GET /assessments/{id}/stats`).
- **CSV upload**: FileInput → "Validate" → preview Dialog showing committed count + per-row error table (red Badges per code) → "Commit (N)" button posts `dry_run=false`. Errors render as a `Table` of `{row, student_uid, code, message}` rows.
- **Lock/unlock**: button next to the assessment select. Lock = `confirm("Lock?")`. Unlock = `prompt("Reason?")` (admin-only; the FE doesn't check role — the API rejects with 403 if the actor is a teacher, and the alert surface returns the message).
- **Assessments-for-this-offering** Card below the entry table: list of all assessments with type/date/state badges. Click selects.
- **History Dialog**: per-row "history" Button opens a Dialog with the full `/marks/{mark_id}/audit` timeline — `created_at | action | old → new | reason | actor`.

### Student (`/student/marks`)
- **Assessment table**: course code · type · name · date · marks (or `absent` Badge) · class avg · state Badge.
- **Percentile summary**: "You scored at or above the class average on X% of N assessments with class statistics available." Approximate but cheap; the spec's "rank 12 / 60" depends on per-college ranking not in scope this session.
- **Radar chart** (`recharts`): one axis per subject, value = average marks % across that subject's assessments. Hidden when fewer than 2 subjects (a triangle radar is more confusing than informative).
- **Trend line** (`recharts`): chronological per-subject percentage line.
- **Grade projection** Table: per subject, `current_total`, `need_see_for_pass` (40), `need_see_for_distinction` (75). Derived from `/grade-rules` + current marks; if SEE weight is zero or the rules don't exist, shows `—` rather than misleading numbers.
- **PDF download**: lazy-loads `jspdf` + `jspdf-autotable` on click, writes a single-page table with course/type/name/date/marks/class avg.

### Parent (`/parent/marks`)
- **New `/parent/{layout,page}.tsx`**: role-gated shell with one nav item. `/parent` redirects to `/parent/marks`.
- **Child picker**: Select dropdown of every verified-linked student (`/parent/children`).
- **Read-only marks table**: same columns as `/student/marks` (course / type / name / date / marks / class avg / state) for the selected child. No radar / trend / PDF — those can land in a follow-up if a parent ever asks; mirroring everything would double the FE without a clear use case.
- **Login routing**: `apps/web/app/login/page.tsx` now sends `role === "parent"` to `/parent/marks` (previously rejected non-admins; M3 widened it for teacher/student; M4 adds parent).

All FE components reuse the existing `apps/web/components/ui.tsx` primitives. Same Tailwind look, no new theme tokens.

---

## Deferred — intentionally not done in M4

| Item | Where | Why deferred |
|---|---|---|
| Real event bus | `TODO(events)` markers in `marks/service.py` (assessment.created, mark.set, mark.bulk, assessment.lock/unlock publish sites) | M5 (Communications) is the natural trigger — it needs subscribe semantics. Building the bus for M4-alone publishes is the same abstraction tax M3 didn't pay. |
| Parent self-signup / invite flow | Only admin can link via `POST /admin/guardian-links` | M1's invite/OTP flow is heavier than the trust model needs right now; admins know their student rosters. |
| Parent attendance view | n/a | Out of scope for M4. The `guardian_links` table is module-agnostic; a future module can read it. |
| Parent radar/trend/PDF | `/parent/marks` is table-only | A parent rarely benefits from the per-subject projection; the student already has the heavier UI. Easy follow-up. |
| Rank "12 / 60 — 80th percentile" exact | Approximate percentile (above-mean fraction) on `/student/marks` | True ranking needs per-assessment fetch of every classmate's mark; would force either a backend rank endpoint or a heavy client computation. Add when the academic team requests it. |
| Mark rounding / curve adjustments | n/a | Out of scope — needs a college-policy lookup table and explicit teacher action. |
| AI grade anomaly flagging | n/a | M7+ territory. M4's outlier Badge is a |z|>2 heuristic, not an alert. |
| Multi-child enrollment for one parent across colleges | `guardian_links.college_id` is single-valued | A parent with kids in two BMSCE-style colleges is rare and the M1 user model is single-college. Cross-college parent dashboards are a separate problem. |
| Locked-assessment edit by admin via FE | API supports `reason`; FE doesn't expose it | Edge case; the API path works for break-glass corrections via curl. |
| LEARN.md chapters | n/a | `LEARN.md` is gitignored on Windows per the M3 closeout directive. |

---

## How to bring it up on a fresh machine

```bash
cd /c/Projects/metis                                  # Windows; or ~/code/personal/Metis on Mac
cd services/api && uv sync --all-extras && cd ../..
cp services/api/.env.example services/api/.env        # set JWT_SECRET + FACE_ENCRYPTION_KEY
cp apps/web/.env.example apps/web/.env.local

npm install                                           # apps/web picks up recharts + jspdf added in M4
npm run infra:up                                      # Postgres + Redis (docker compose)
npm run migrate                                       # alembic 0001..0006 (extends user_role enum + 5 new tables)
npm run seed                                          # admin/teacher/student + CSE academic structure
npm run materialise                                   # materialises class_sessions for [today, today+14d]

npm run dev:api                                       # http://localhost:8000/api/v1/docs  (search "marks", "assessments", "grade-rules", "parent")
npm run dev:web                                       # http://localhost:3000

# Demo path:
# - Log in as teacher@bmsce.ac.in → /teacher/marks → pick an offering → "+ New" → "CIE 1 — DBMS" max=30
# - Enter marks for the seeded enrolled student → blur the input → see ✓ + stats row recompute
# - Drag a CSV with student_uid,marks_obtained,is_absent → Validate → Commit
# - Lock the assessment; verify input fields go disabled and a "🔒" badge shows
# - As a separate browser tab: log in as student@bmsce.ac.in → /student/marks → see the row, radar (after a second subject), trend
# - Click "Download PDF" → marks-YYYY-MM-DD.pdf is saved
# - As admin: POST /api/v1/admin/guardian-links → copy `parent_initial_password` → log in as that parent → /parent/marks shows the linked child

npm run test:api                                      # 64 tests total (13 auth + 12 academic + 17 attendance + 22 marks)
```

The CSE-2024-A enrolled student in the seed makes a 1-student class. To test stats meaningfully, create extra enrollments (or use `_build_marks_setup` patterns from `tests/test_marks.py`).

---

## Useful re-entry pointers

- Spec for the whole project: `CLAUDE (1).md`. M4 spec is lines 322–346; screen inventory is lines 1045–1051 (student) and 1107–1114 (teacher).
- M3 status: `PROGRESS_M3.md`. M2 status: `PROGRESS_M2.md`. M1 status: `PROGRESS_M1.md`.
- Migration convention: any new `updated_at` column → attach `set_updated_at` trigger in the migration's `TRIGGERED_TABLES` tuple. M4's tuple is `(assessments, marks, grade_rules)`.
- Model registry: `services/api/alembic/env.py` imports `app.modules.marks.models`.
- All M4 audit actions are dot-grouped: `assessment.create`, `assessment.update`, `assessment.delete`, `assessment.lock`, `assessment.unlock`, `mark.set`, `mark.bulk`, `grade_rule.update`, `guardian.link`, `guardian.unlink`. Mark-row-level history lives in `marks_audit` with `mark.create`, `mark.update`, `mark.bulk_create`, `mark.bulk_update`, `mark.lock`, `mark.unlock`.
- `marks_audit` vs `audit_logs`: the former is value-level (old/new JSONB per mark), the latter is cross-cutting (actor/action/entity). Both fire from every M4 write.
- Adding `parent` to `user_role` uses `ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'parent'`. The Python `UserRole` enum in `app/modules/users/models.py` was extended to match — keep these in sync if a future migration adds another role.
- FE `apps/web/lib/api.ts` accepts `FormData` bodies unmodified. Use this pattern for any future multipart upload (CSV / image / file).
