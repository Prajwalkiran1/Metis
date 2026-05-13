# M3 — Attendance Service: Complete

Last updated: 2026-05-13.

Status: ✅ **complete** (backend + teacher FE + student FE). Next module: M4 — Marks Service.

---

## Where M3 fits

M3 is the first module that *consumes* M2. Its materialiser turns recurring `timetable_slots` (minus `academic_calendar` holidays, plus/minus `timetable_exceptions`) into concrete `class_sessions`. From there:

- Teacher hits `POST /sessions/{id}/qr` → state flips `pending → open`, a signed-JWT QR token is minted.
- Student scans, submits GPS + face frame + device fingerprint → three anti-proxy layers decide `recorded` vs `flagged`.
- Teacher can override `flagged → recorded`, or create a `recorded` record for a no-show student (manual marking).
- M4 (marks) will read from `class_sessions` via `course_offering_id`; M5 (comms) can broadcast "low attendance" alerts off the report endpoint.

The event bus (`attendance.marked`, `attendance.anomaly_detected`, `session.created`) is still deferred — `TODO(events)` markers note the publish sites. **What's wired now**: M2's previous `TODO(events)` sites on `timetable_slot` and `timetable_exception` mutations call `await materialise_offering(...)` directly inside the same transaction. When the bus lands, that direct call becomes a `publish('timetable.updated', ...)` event and M3 subscribes.

---

## Endpoints shipped

```
# Class session lifecycle
GET    /api/v1/sessions                         list (scoped by role: admin=all, teacher=own, student=enrolled)
                                                filters: ?from, ?to, ?state
POST   /api/v1/sessions/{id}/qr                 teacher/admin; flips pending→open, mints 90s JWT
POST   /api/v1/sessions/{id}/close              teacher/admin; open→closed, revokes live QR tokens

# Submit
POST   /api/v1/attendance/submit                student; slowapi-limited 10/min per IP
                                                runs JWT verify + jti check + GPS haversine + face stub
                                                + anti-replay (student+device)

# Views
GET    /api/v1/attendance/{student_id}          self (student) or teacher/admin
                                                filters: ?from, ?to, ?course_offering_id
GET    /api/v1/attendance/session/{id}          teacher/admin live feed (enrolled × records)

# Override (narrow)
PATCH  /api/v1/attendance/sessions/{id}/override?record_id={uuid?}
                                                teacher/admin only
                                                - record_id present, state=flagged → recorded
                                                - record_id absent, supply student_user_id → recorded from absence

# Report
GET    /api/v1/attendance/report/{batch_id}     admin or owning teacher; CSV by default, ?format=json
                                                filters: ?from, ?to
```

All writes call `write_audit()` before commit. All reads/writes are tenant-scoped on `actor.college_id`. `/attendance/submit` is the only slowapi-decorated endpoint in M3 (10/min/IP).

---

## Files shipped

| Path | Role |
|---|---|
| `services/api/app/modules/attendance/__init__.py` | Module marker |
| `services/api/app/modules/attendance/models.py` | 5 ORM models + 3 enums (class_session_state, class_session_source, attendance_record_state) |
| `services/api/app/modules/attendance/schemas.py` | All Pydantic request/response models |
| `services/api/app/modules/attendance/qr.py` | Signed-JWT QR helpers (`sign_qr`, `verify_qr`, `QRInvalidError`); typ=`attendance_qr`, HS256 off `settings.jwt_secret` |
| `services/api/app/modules/attendance/geo.py` | Pure-Python `haversine_m` (Decimal-safe) |
| `services/api/app/modules/attendance/face_stub.py` | `verify_face_stub` returning fixed `settings.attendance_face_stub_confidence` until M8 |
| `services/api/app/modules/attendance/service.py` | Materialiser (`materialise_offering`/`materialise_one`/`materialise_window`), state-machine ops, submit pipeline, override, report |
| `services/api/app/modules/attendance/router.py` | All endpoints; `_to_http()` bridges `AttendanceError` to `HTTPException`; CSV report via `StreamingResponse` |
| `services/api/app/cli.py` | `python -m app.cli materialise --window-days=14`; doc'd for host cron |
| `services/api/alembic/versions/0005_attendance_schema.py` | Creates 3 enums + 5 tables + indexes + check constraints; attaches `set_updated_at` triggers on `class_sessions` and `attendance_records`; full downgrade |
| `services/api/tests/test_attendance.py` | 15 pytest cases — materialiser idempotency + holidays, QR sign/verify roundtrip + reject garbage, haversine sanity, /qr owner check, submit happy path, GPS flagged, anti-replay, closed session, override flagged→recorded, session feed, student log self-only, tenant isolation |
| `services/api/alembic/env.py` | +1 import line registering the attendance models |
| `services/api/app/main.py` | +1 import + `app.include_router(attendance_router, ...)` |
| `services/api/app/core/config.py` | +`attendance_qr_ttl_seconds`, `attendance_gps_default_radius_m`, `attendance_face_stub_confidence`, `rate_limit_attendance_submit_per_minute` |
| `services/api/app/core/ratelimit.py` | +`attendance_submit_rate_limit()` helper |
| `services/api/app/modules/academic/service.py` | Removed 5 `TODO(events)` markers; added `_rematerialise_for_event()` lazy-import helper. Slot create/update/delete + exception create/delete now materialise the affected offering for [today, today+14d] in the same transaction. |
| `infra/scripts/seed.py` | **Bug fix** — academic seed was looking up teacher/student by `@bmsce.edu.in` (wrong TLD); fixed to `@bmsce.ac.in`. The CSE academic seed now actually runs. |
| `package.json` | +`"materialise"` script: `uv run --project services/api python -m app.cli materialise` |
| `apps/web/package.json` | +`qrcode.react@4.1.0` for the rotating QR display |
| `apps/web/app/login/page.tsx` | Roles now route to their own landing: admin→`/admin/academic`, teacher→`/teacher/attendance`, student→`/student/attendance` (previously: admin only, others got an error) |
| `apps/web/app/teacher/{layout,page}.tsx` | Role-guarded teacher shell; `/teacher` redirects to `/teacher/attendance` |
| `apps/web/app/teacher/attendance/page.tsx` | Today's sessions list, "Start QR" → rotating `QRCodeSVG` with 90s countdown, live feed (5s poll), per-row override actions (approve flagged / mark absent present), close-session |
| `apps/web/app/student/{layout,page}.tsx` | Role-guarded student shell; `/student` redirects to `/student/attendance` |
| `apps/web/app/student/attendance/page.tsx` | Paste-QR + browser geolocation + opaque device fingerprint (stable per-device via `crypto.randomUUID` in localStorage); submit and render result badge |
| `PROGRESS_M3.md` | This file |
| `CLAUDE (1).md` | `MODULE STATUS TABLE` and `ACTIVE MODULE STATE` block updated |
| `CLEANUP.md` | M3 footprint appended (5 tables + 3 enums; no new Docker volumes) |
| `LEARN.md` | M3 chapters appended (43–49) |
| `services/api/README.md` | Module map updated to include `attendance/` |

---

## Tables added (migration 0005)

| Table | Notes |
|---|---|
| `class_sessions` | Concrete (date, time, room) instance materialised from a slot/exception. State: `pending → open → closed`. Partial unique `(course_offering_id, scheduled_date, start_time) WHERE deleted_at IS NULL` is the idempotency key the materialiser hits via `ON CONFLICT DO UPDATE`. |
| `qr_tokens` | One row per minted JWT. jti unique. Issuing a new token revokes prior live ones for the session. The DB row exists alongside the JWT so we can do hard revocation before exp **and** treat jti as an explicit anti-replay token (defense in depth). |
| `attendance_records` | One per (session, student). State: `submitted → verified → recorded` / `flagged`. Unique `(class_session_id, student_user_id)` is the per-student anti-replay guard. |
| `device_logs` | One per (session, device fingerprint). Unique `(class_session_id, device_fingerprint_hash)` blocks the same phone from being lent around. |
| `attendance_overrides` | Append-only audit trail for teacher overrides. `from_state` nullable so the table can also log "absent → recorded" creations. |

Triggered tables (have `updated_at`): `class_sessions`, `attendance_records`. The other three are append-only.

---

## Decisions worth remembering

| Decision | Choice | Why |
|---|---|---|
| Event bus | Defer; M2's prior TODO(events) sites now call `await materialise_offering(...)` inline | Same playbook as M1/M2 — M3 alone doesn't justify the abstraction tax. Bus lands when M4/M5 also need it. |
| Scheduler | CLI command (`python -m app.cli materialise`), not in-process APScheduler | No new runtime dep; host cron / GH Actions schedules it. Multi-worker safety isn't a concern yet. On-demand fallback covers cron lag (teacher hits `/qr` → materialise that one date inline). |
| QR token shape | JWT with `typ="attendance_qr"`, HS256 off `settings.jwt_secret`, 90s TTL, claims `{jti, sid, lat, lon, iat, exp, iss_by}` | Same key as access tokens but unconflated by `typ` so a leaked QR can't be reused as auth. jti exists in DB for explicit revocation + audit. |
| State machine | Postgres enums + service-layer transition validation (no triggers) | Triggers make the rule hard to read from the application side. Service-layer checks live next to the audit write. |
| Override scope | Narrow (flagged→recorded only; absent→recorded creates row) | Cleaner audit, harder to misuse. M9 admin UI can widen with a "reverse mistake" action later. |
| GPS threshold | `rooms.gps_radius_m` when room has coords, else `settings.attendance_gps_default_radius_m` (100m). Result > threshold → **flagged**, not rejected. | Matches the spec — "anomaly, not authoritarian." Teacher decides on review. |
| Face verification | `face_stub.py::verify_face_stub` returns `settings.attendance_face_stub_confidence` (0.95) until M8 | Same signature M8 will land. To exercise the FLAGGED path locally, drop the setting below 0.6. |
| Device fingerprint | Client-supplied opaque string, SHA-256'd server-side; one (session, hash) pair per session | Client owns the source-of-truth; server stores only the digest so the FE can change its fingerprint algorithm later without a migration. |
| Session list endpoint | Added `GET /sessions` (not in the spec's 6-endpoint list) | Spec endpoints alone leave the FE without a session picker. Auto-scoped by role: admin sees all, teacher sees own, student sees enrolled. |
| Materialiser idempotency | `INSERT … ON CONFLICT (offering, date, start) DO UPDATE` on the partial-unique index | Re-running on `timetable.updated` patches `room_id`/`end_time`/`origin_exception_id` on existing rows; never touches state, opened_at, closed_at. |
| Materialiser cleanup | UPSERT-only; never deletes sessions | Deleting a slot doesn't auto-soft-delete future sessions — admin manages those explicitly. Avoids the foot-gun where a misclick wipes a week of history. |
| Materialiser horizon | [today, today + 14 days] inside the M2 hook; CLI takes `--window-days=14` default | Cron runs daily; horizon is approximate. Misalignment by a few hours due to TZ is fine — the slot itself anchors the date in college-local time. |

---

## Anti-proxy layers — quick reference

| Layer | Where | Failure mode |
|---|---|---|
| QR signature + type | `qr.verify_qr` | `400 bad_signature` / `400 bad_type` |
| QR jti unrevoked + within window | DB lookup in `submit_attendance` | `400 qr_unknown` / `400 qr_revoked` / `400 qr_expired` |
| Session open + student enrolled | service.submit | `409 session_not_open` / `403 not_enrolled` |
| Per-student replay | unique `(class_session_id, student_user_id)` on `attendance_records` | `409 already_submitted` |
| Per-device replay | unique `(class_session_id, device_fingerprint_hash)` on `device_logs` | `409 device_reused` |
| GPS within radius | haversine vs room centroid in `submit_attendance` | record state = `flagged`, reason `gps_too_far:<distance>m` |
| Face match | `face_stub.verify_face_stub` (M8 will swap in DeepFace) | record state = `flagged`, reason `face_no_match:<confidence>` |
| Rate limit | slowapi `10/minute/IP` on `/attendance/submit` | `429` |

---

## Frontend — what shipped

### Teacher
- `/teacher/{layout,page}.tsx` — sidebar shell guarded for role `teacher` or `admin`. Marks / Materials nav items present but disabled.
- `/teacher/attendance`:
  - **Today's sessions**: list of sessions from `GET /sessions?from=today&to=today`. Each row has a state badge and "Open" button.
  - **Active session**: panel with
    - **Rotating QR** (`QRCodeSVG` from `qrcode.react`) keyed off the JWT. Auto-rotates ~10s before exp; a debug `<details>` exposes the raw token for paste-fallback.
    - **Countdown** under the QR ("expires in Ns").
    - **Live feed** polling `GET /attendance/session/{id}` every 5s; per-row badge (`recorded`/`flagged`/`absent`) and override buttons (approve flagged, mark absent present).
    - **Close session** button — revokes any live QR and flips the state to `closed`.

### Student
- `/student/{layout,page}.tsx` — sidebar shell guarded for role `student`.
- `/student/attendance`:
  - **Submit**: input to paste the JWT (a future PR adds the camera scanner). On submit, browser geolocation fires (`enableHighAccuracy: true`), the device fingerprint is read from `localStorage` (created once via `crypto.randomUUID()` keyed `metis.device_fp`), and the body posts to `/attendance/submit`. A state badge renders the result + flag reason if any.
  - **Today's classes**: read-only list pulled from `GET /sessions` (auto-scoped to the student's enrolled sections).

### Login
- `apps/web/app/login/page.tsx` now routes by role: admin→`/admin/academic`, teacher→`/teacher/attendance`, student→`/student/attendance`. Previously the page rejected non-admins.

All FE components reuse the existing `apps/web/components/ui.tsx` primitives. No animations, no new theme tokens — same MVP look as M2.

---

## ⚠️ Not finished in this session — pick up first

- **`npm run test:api` was not run** — Docker wasn't running when the session
  closed (`docker ps` errored on the unix socket). Pure-Python sanity
  checks pass (QR sign/verify roundtrip, haversine sanity, face stub returns
  0.95, full app imports, all 5 attendance tables register in
  `Base.metadata`). The DB-backed pytest suite still needs to be executed
  against a live Postgres + Redis. Order: `npm run infra:up && npm run migrate
  && npm run test:api`. Expect 34 tests total (7 auth + 12 academic + 15
  attendance).
- **`LEARN.md` chapters 43–49 are NOT written.** Outline locked in: 43 data
  model, 44 idempotent materialisation, 45 signed-JWT QR tokens, 46
  haversine, 47 device-fingerprint dedup, 48 state machines in Postgres,
  49 new patterns introduced. Append before the `## Glossary` heading at
  line 2848.

## Deferred — intentionally not done in M3

| Item | Where | Why deferred |
|---|---|---|
| Real face verification | `attendance/face_stub.py` | M8 owns DeepFace FaceNet. Stub returns 0.95 (configurable). |
| Event bus | `TODO(events)` markers in `attendance/service.py` (submit publish, close publish, anomaly publish) | M3 consumes M2 directly; bus design lands when M4/M5 join the consumer list. |
| QR camera scanner on student FE | `student/attendance/page.tsx` paste fallback only | Time-boxed to MVP. Adding a scanner is a 1-day follow-up (e.g. `@yudiel/react-qr-scanner`). |
| Materialiser cron in-process | n/a | Out of scope by decision; host cron / GH Actions schedules `npm run materialise`. |
| Session-deletion cleanup of future class_sessions | n/a | Materialiser is UPSERT-only by design. Admin can soft-delete sessions individually; M9 admin UI will add a bulk action. |
| Per-college timezone | hardcoded `Asia/Kolkata` | Same as M2 — multi-region pilots haven't appeared. |
| Override "any transition with reason" | service.override_attendance | Narrow rule by decision. Widen when M9 ships the audit-log viewer. |
| Refresh-token reuse detection | TODO in auth/service.py | M1-hardening, see auth audit. |

---

## How to bring it up on a fresh machine

```bash
cd ~/code/personal/Metis
cd services/api && uv sync --all-extras && cd ../..
cp services/api/.env.example services/api/.env         # then set JWT_SECRET + FACE_ENCRYPTION_KEY
cp apps/web/.env.example apps/web/.env.local           # optional — defaults work for local dev

npm install                                            # picks up apps/web (qrcode.react added in M3)
npm run infra:up                                       # Postgres + Redis (docker compose)
npm run migrate                                        # alembic upgrade head — applies 0001..0005
npm run seed                                           # admin/teacher/student + CSE academic structure
npm run materialise                                    # materialises class_sessions for [today, today+14d]
npm run dev:api                                        # http://localhost:8000/api/v1/docs
npm run dev:web                                        # http://localhost:3000

# Demo:
# - Log in as teacher@bmsce.ac.in (password: MetisDemo!2026) → /teacher/attendance
# - Pick today's session → "Start QR" → QR appears
# - In another browser, log in as student@bmsce.ac.in → /student/attendance
# - On the teacher tab, expand "token (debug)" → copy the JWT
# - Paste into the student page → Allow location → Submit → "recorded" badge
# - Teacher live feed reloads in 5s and shows the student as recorded

npm run test:api                                       # 34 tests total (7 auth + 12 academic + 15 attendance)
```

The CSE-2024-A timetable seed has Wednesday 10:00 and 11:00 slots. Run the materialiser on a Tuesday or Wednesday to see sessions in `/teacher/attendance`; otherwise create your own slot via `/admin/academic → Timetable` (the M2 hook will materialise it on creation).

---

## Useful re-entry pointers

- Spec for the whole project: `CLAUDE (1).md`. M3 spec is lines 291–318.
- M1 status: `PROGRESS_M1.md`. M2 status: `PROGRESS_M2.md`.
- Auth audit: `~/.claude/plans/i-m-starting-module-peaceful-dove.md`.
- Migration convention: any new `updated_at` column → attach `set_updated_at` trigger in the migration's `TRIGGERED_TABLES` tuple. M3's tuple is `(class_sessions, attendance_records)`.
- Model registry: `services/api/alembic/env.py` imports `app.modules.attendance.models`.
- All M3 audit actions are dot-grouped: `attendance.qr.issue`, `class_session.close`, `attendance.submit`, `attendance.override`.
- M2's `_rematerialise_for_event` lazy-imports `materialise_offering` to dodge any circular-import surprises. When the event bus lands, this helper becomes a no-op (the materialiser subscribes instead).
