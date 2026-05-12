# M2 — Academic Service: Complete

Last updated: 2026-05-12.

Status: ✅ **complete** (backend + admin FE). Next module: M3 — Attendance Service.

---

## Where M2 fits

M2 is the academic backbone. Every later module reads from these tables:

- **M3 attendance** materialises `class_sessions` from `timetable_slots` minus `academic_calendar` holidays and `timetable_exceptions`. Reads `rooms.lat/lon/gps_radius_m` for the GPS centroid check.
- **M4 marks** scopes assessments to a `course_offering_id` — that's the (course, section, semester, teacher) tuple this module owns.
- **M5 comms** targets announcements by `batch_id` / `section_id`.
- **M6/M7** organise materials and the RAG vector index per `course_id`.

Events `timetable.updated` and `session.created` are wired as `TODO(events)` markers — same playbook as M1's `user.enrolled`. The bus lands when M3 actually needs to consume.

---

## Endpoints shipped

```
# Departments
GET    /api/v1/departments                            list (filter: ?include_deleted, ?limit, ?offset)
POST   /api/v1/departments                            admin
GET    /api/v1/departments/{id}
PATCH  /api/v1/departments/{id}                       admin
DELETE /api/v1/departments/{id}                       admin (soft delete)

# Courses
GET    /api/v1/courses                                list (filter: ?department_id, ?semester, ?course_type)
POST   /api/v1/courses                                admin
GET    /api/v1/courses/{id}
PATCH  /api/v1/courses/{id}                           admin
DELETE /api/v1/courses/{id}                           admin

# Batches & sections
GET    /api/v1/batches                                list (filter: ?department_id, ?admission_year)
POST   /api/v1/batches                                admin
GET    /api/v1/batches/{id}
PATCH  /api/v1/batches/{id}                           admin
DELETE /api/v1/batches/{id}                           admin

GET    /api/v1/sections                               list (filter: ?batch_id)
POST   /api/v1/sections                               admin
GET    /api/v1/sections/{id}
PATCH  /api/v1/sections/{id}                          admin
DELETE /api/v1/sections/{id}                          admin
POST   /api/v1/sections/{id}/enrollments              admin (bulk add students)
GET    /api/v1/sections/{id}/students                 list active enrollments
DELETE /api/v1/sections/{id}/enrollments/{enr_id}     admin (sets withdrawn_at)

# Rooms
GET    /api/v1/rooms                                  list (filter: ?room_type)
POST   /api/v1/rooms                                  admin
GET    /api/v1/rooms/{id}
PATCH  /api/v1/rooms/{id}                             admin
DELETE /api/v1/rooms/{id}                             admin

# Course offerings (teacher↔course↔section binding)
GET    /api/v1/course-offerings                       list (filter: section, course, teacher, term)
POST   /api/v1/course-offerings                       admin
GET    /api/v1/course-offerings/{id}
PATCH  /api/v1/course-offerings/{id}                  admin (is_active toggle only)
DELETE /api/v1/course-offerings/{id}                  admin (soft — never mutate teacher in place)

# Timetable
GET    /api/v1/timetable/{section_id}                 weekly view (?from, ?to) — base slots + exceptions
POST   /api/v1/timetable                              admin; 409 on conflict unless ?force=true
PATCH  /api/v1/timetable/{slot_id}                    admin; re-runs conflict check
DELETE /api/v1/timetable/{slot_id}                    admin
POST   /api/v1/timetable/check-conflict               always 200; {has_conflicts, conflicts: [...]}
POST   /api/v1/timetable/exceptions                   admin; cancel | reschedule | room_change | extra
DELETE /api/v1/timetable/exceptions/{id}              admin

# Academic calendar
GET    /api/v1/academic-calendar                      list (?from, ?to, ?kind, ?department_id)
POST   /api/v1/academic-calendar                      admin
PATCH  /api/v1/academic-calendar/{id}                 admin
DELETE /api/v1/academic-calendar/{id}                 admin
```

All writes call `write_audit()` before commit. All reads/writes are tenant-scoped on `actor.college_id`. No rate limiting on M2 (matches M1 — slowapi is auth-only).

---

## Files shipped

| Path | Role |
|---|---|
| `services/api/app/modules/academic/__init__.py` | Module marker |
| `services/api/app/modules/academic/models.py` | 10 ORM models + 4 enums |
| `services/api/app/modules/academic/schemas.py` | All Pydantic request/response models + generic `Page[T]` paginator + `ConflictCheckRequest/Response` |
| `services/api/app/modules/academic/service.py` | CRUD + audit-before-commit + conflict detection (three SQL variants) + enrollment add/withdraw + exception kind validation |
| `services/api/app/modules/academic/router.py` | All endpoints; `_to_http()` bridges `AcademicError` to `HTTPException` |
| `services/api/alembic/versions/0003_academic_schema.py` | Creates 4 enums + 10 tables + indexes (incl. partial-on-active-only uniques) + check constraints + attaches `set_updated_at` triggers; full downgrade |
| `services/api/tests/test_academic.py` | 12 pytest cases — CRUD, curriculum filter, enrollment, room constraint, offering uniqueness, conflict + force override, exception kinds, calendar, tenant isolation |
| `services/api/alembic/env.py` | +1 import line registering the academic models |
| `services/api/app/main.py` | +1 import + `app.include_router(academic_router, ...)` |
| `services/api/app/core/config.py` | +`default_timezone: str = "Asia/Kolkata"` |
| `infra/scripts/seed.py` | +`_seed_academic()`: CSE dept, CSE 2024-28 batch (A+B), 3 sem-3 courses, 2 rooms (LH-201 with BMSCE coords), 3 offerings, 2 back-to-back Wed slots, 1 student enrolled in CSE-2024-A, 1 holiday. Fully idempotent. |
| `services/api/README.md` | Module-map block updated to include `academic/` |
| `PROGRESS_M2.md` | This file |
| `CLAUDE (1).md` | `MODULE STATUS TABLE` and `ACTIVE MODULE STATE` block updated; `frontend:` section in the state block flipped to reflect the admin shell |
| `CLEANUP.md` | M2 footprint appended (10 tables + `apps/web/` bootstrap; no new Docker volumes — Postgres is shared) |
| `LEARN.md` | M2 chapters appended |
| `apps/web/package.json`, `tsconfig.json`, `next.config.mjs`, `tailwind.config.ts`, `postcss.config.js`, `next-env.d.ts`, `.env.example`, `.gitignore` | Next.js + Tailwind bootstrap |
| `apps/web/app/{layout.tsx,page.tsx,globals.css}` | Root shell |
| `apps/web/app/login/page.tsx` | Auth entry point |
| `apps/web/app/admin/{layout.tsx,page.tsx}` | Sidebar shell + auth guard |
| `apps/web/app/admin/academic/page.tsx` | Six-tab container |
| `apps/web/app/admin/academic/_tabs/{departments,courses,batches,rooms,timetable,calendar}.tsx` | The six tab modules |
| `apps/web/lib/{api.ts,auth.ts}` | Typed fetch client + localStorage helpers |
| `apps/web/components/ui.tsx` | Hand-rolled shadcn-style primitives |

---

## Tables added (migration 0003)

| Table | Notes |
|---|---|
| `departments` | `college_id`, `code`, `head_user_id` FK to users. Partial unique on `(college_id, code) WHERE deleted_at IS NULL`. |
| `courses` | `department_id`, `code`, `title`, `credits`, `semester`, `course_type` enum. Curriculum is `SELECT * FROM courses WHERE department_id=? AND semester=?`. |
| `batches` | Year cohort with `current_semester` advanced manually by admins. Partial unique `(college_id, department_id, admission_year)`. |
| `sections` | "A", "B" inside a batch. `class_teacher_user_id` optional FK. Partial unique `(batch_id, name)`. |
| `rooms` | `lat NUMERIC(9,6) NULL`, `lon NUMERIC(9,6) NULL`, `gps_radius_m`. Check `(lat IS NULL) = (lon IS NULL)`. M3 reads these. |
| `course_offerings` | The teacher↔course↔section binding for a term. **Never mutate teacher in place** — soft-delete + new row (M4 will FK this). Partial unique `(section_id, course_id, academic_term)`. |
| `timetable_slots` | Weekly recurring rule. `day_of_week 0–6` (ISO Mon=0). `room_id` nullable (online/TBD). |
| `timetable_exceptions` | Single table tagged by `kind` (cancel/reschedule/room_change/extra). Check constraints enforce per-kind invariants. Unique `(original_slot_id, exception_date)` for non-extra. |
| `academic_calendar` | Holidays, exams, events. `cancels_classes` boolean; `applies_to_department_id` nullable (NULL = college-wide). |
| `enrollments` | Append-mostly junction with `withdrawn_at` for soft withdraw. Bigserial PK. Partial unique `(student_user_id, section_id, academic_term)` while active. |

Triggered tables (have `updated_at`): all of the above except `enrollments`.

---

## Decisions worth remembering

| Decision | Choice | Why |
|---|---|---|
| Module slicing | Single `academic/` folder, single files | Mirrors M1's `users/` shape. Refactor only at >500 LOC. |
| Student↔section linkage | Separate `enrollments` table | Supports electives, semester progression history, keeps M1's `users` table untouched. |
| Event bus | Defer with `TODO(events)` markers | Same playbook as M1's `user.enrolled`. Bus lands when M3 consumes. Marker sites: `service.py::add_enrollments`, `create_timetable_slot`, `patch_timetable_slot`, `delete_timetable_slot`, `create_timetable_exception`, `delete_timetable_exception`. |
| Timezone | `settings.default_timezone = "Asia/Kolkata"` | No DB migration on `colleges`. Refactor when multi-region matters. |
| Curriculum versioning | No separate table | Derive from `courses.department_id + courses.semester + courses.course_type`. |
| `room_id` nullable on slots | Yes | Online/TBD classes. Conflict detection skips room check when NULL. M3 must handle GPS-less sessions (face/QR only). |
| Course-offering teacher swaps | Soft-delete + new row, never in-place | Otherwise M4 marks silently rewrite historical authorship. PATCH endpoint only toggles `is_active`. |
| Conflict-check on POST/PATCH | 409 unless `?force=true` | Force is audit-logged with `"force_override": true` in `new_value`. |
| Exceptions during conflict check | Ignored | Exceptions are deviations the admin already approved. The exception-creation endpoint has its own narrower date-specific check. |

---

## Conflict detection — quick reference

Three SQL queries, each with the same half-open overlap predicate:

```sql
day_of_week = :dow
AND deleted_at IS NULL
AND (id != :exclude_slot_id OR :exclude_slot_id IS NULL)
AND start_time < :end_time
AND end_time   > :start_time
AND effective_from   <= :effective_until
AND effective_until  >= :effective_from
```

- **Room**: + `AND room_id = :room_id` (skipped when `room_id IS NULL`).
- **Teacher**: JOIN `course_offerings` AND `co.teacher_user_id = :teacher`.
- **Section**: JOIN `course_offerings` AND `co.section_id = :section`.

Returned as `{has_conflicts, conflicts: [{type, slot_id, course_offering_id, reason}]}`. POST/PATCH 409 unless `force=true`.

---

## How M3 will materialise class sessions (handoff note)

For each active `timetable_slot`:
1. Expand `effective_from..effective_until` to dates matching `day_of_week`.
2. Subtract `academic_calendar` rows where `cancels_classes=TRUE` (and `applies_to_department_id IS NULL OR matches the slot's department`).
3. Left-join `timetable_exceptions` on `(original_slot_id, exception_date)` to apply cancel/room_change/reschedule overrides.
4. Union with `kind='extra'` rows (no `original_slot_id`).
5. Each surviving (offering, date, room, start, end) becomes a `class_sessions` row.
6. M2 emits `session.created` (currently a TODO marker).

M3's consumer must be **idempotent on `timetable.updated`** — late room changes need to patch existing `class_sessions.room_id`.

---

## Frontend — what shipped

The `apps/web/` workspace bootstrapped from empty:

- **Next.js 14 App Router**, TypeScript strict, Tailwind, shadcn-style primitives (hand-rolled in `apps/web/components/ui.tsx` to avoid the shadcn CLI install ceremony — same API surface, plain Tailwind classes, easy to swap during the redesign phase).
- **`lib/api.ts`**: typed fetch client; auto-attaches `Bearer <access>` from localStorage; on 401 calls `/auth/refresh` (the HttpOnly cookie rides along), retries once, then clears local state.
- **`/login`**: react-hook-form + zod; on success, redirects to `/admin/academic`. Non-admins get a friendly message.
- **`/admin/*` shell**: sidebar (Academic / Users / Reports / System — the last three marked disabled, to be filled in by their respective modules); client-side auth guard redirects to `/login` if no token or role ≠ admin; "Sign out" calls `/auth/logout` then clears local state.
- **`/admin/academic`** with six tabs:
  - **Departments**: list + add + soft-delete.
  - **Courses**: list + filter by department/semester + add + soft-delete.
  - **Batches**: per-batch card with nested sections; add batch / add section / enroll students (paste UUIDs).
  - **Rooms**: list + add (with optional lat/lon/gps-radius for M3) + soft-delete.
  - **Timetable**: section selector → weekly slot list; "Add slot" dialog runs `POST /timetable/check-conflict` first; if conflicts come back, the dialog shows them inline (room / teacher / section) and replaces the Save button with a red **Save anyway (force)** button (which calls `/timetable?force=true` — audit-logged).
  - **Calendar**: list with from/to filter + add (holiday / exam / event / term_start / term_end).

All tabs use shadcn-style primitives only (Button, Card, Dialog, Tabs, Table, Badge, Input, Select, Field) — no custom palettes, no animations. Loading is plain "Loading…"; errors are plain red text. Matches the spec's bare-bones MVP rules.

---

## Deferred — intentionally not done in M2

| Item | Where | Why deferred |
|---|---|---|
| Student + teacher shells | `apps/web/app/(student)/`, `apps/web/app/(teacher)/` | Out of M2 scope. Each module that adds student/teacher features will ship its own sub-app slice. |
| Course-offering management UI | `/admin/academic` | Not in the spec's 6-tab inventory. Admins create offerings via Swagger / curl for now. UI lands naturally with M4 marks (which also needs an offering picker). |
| Event bus (`timetable.updated`, `session.created`, `user.enrolled`) | TODO markers in `academic/service.py` and `invites/service.py` | No event-bus infra yet. Likely lands with M3 since M3 is the first real consumer. |
| Curriculum versioning | n/a | Out of MVP scope. Add a `curricula` table only when curriculum revisions need to coexist (e.g., "2024 revision" vs "2020 revision"). |
| `colleges.timezone` column | Hardcoded `Asia/Kolkata` constant in `settings.default_timezone` | Add a migration when multi-region pilots appear. |
| Class session materialiser | M3 owns this | See handoff note above. |
| GET `/curriculum` dedicated endpoint | Use `GET /courses?department_id=X&semester=N&course_type=core` | Minimum viable; revisit if FE needs a richer view. |
| Server-side audit-log viewer UI | `/admin/system` | M9 deliverable. |

---

## How to bring it up on a fresh machine

```bash
cd ~/code/personal/Metis
cd services/api && uv sync --all-extras && cd ../..
cp services/api/.env.example services/api/.env         # then set JWT_SECRET + FACE_ENCRYPTION_KEY
cp apps/web/.env.example apps/web/.env.local           # optional — defaults work for local dev

npm install                                            # picks up apps/web (Next.js, Tailwind)
npm run infra:up                                       # Postgres + Redis (docker compose)
npm run migrate                                        # alembic upgrade head — applies 0001..0003
npm run seed                                           # admin/teacher/student + CSE academic structure
npm run dev:api                                        # http://localhost:8000/api/v1/docs
npm run dev:web                                        # http://localhost:3000 (login as admin@bmsce.edu.in / MetisDemo!2026)
npm run test:api                                       # 19 tests (7 auth + 12 academic)
```

To wipe everything: see `CLEANUP.md`.

---

## Useful re-entry pointers

- Spec for the whole project: `CLAUDE (1).md`. M2 spec is lines 263–290.
- M1 status / file map: `PROGRESS_M1.md`.
- This module's plan (incl. deferred FE plan): `~/.claude/plans/i-m-starting-module-peaceful-dove.md`.
- Migration convention reminder: any new `updated_at` column → attach `set_updated_at` trigger in the migration's `TRIGGERED_TABLES` tuple.
- Model registry: `services/api/alembic/env.py` imports `app.modules.academic.models`.
- All M2 audit actions use the dot-grouped verbs: `department.create`, `course.update`, `batch.delete`, `section.create`, `enrollment.create`, `enrollment.withdraw`, `room.update`, `course_offering.create/update/delete`, `timetable_slot.create/update/delete`, `timetable_exception.create/delete`, `academic_calendar.create/update/delete`.
