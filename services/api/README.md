# services/api

FastAPI backend for Metis. Modular layout under `app/modules/` — each module owns its router, schemas, services, and (where applicable) its slice of the schema.

## Quickstart

```bash
# Install (uv handles the venv)
uv sync --all-extras

# Copy env template and edit
cp .env.example .env

# Run
uv run uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/api/v1/docs for OpenAPI.

## Module map (M1 + M2 + M3)

```
app/
├── main.py
├── cli.py               # `python -m app.cli materialise` — host-cron entry
├── core/                # config, logging, db, redis, security, deps, audit, ratelimit, crypto
└── modules/
    ├── system/          # /health, /ready
    ├── auth/            # /auth/*  (login, refresh, logout, password reset, google)
    ├── users/           # /users/* (CRUD, role/status, profile photo, face enroll)
    ├── invites/         # /invites/* (create, accept)
    ├── consents/        # internal helpers + consent records
    ├── academic/        # /departments, /courses, /batches, /sections, /rooms,
    │                    # /course-offerings, /timetable, /academic-calendar
    └── attendance/      # /sessions/*, /attendance/* — signed-JWT QR, GPS
                         # haversine, face stub (M8 will replace), state
                         # machine, narrow overrides, CSV report.
                         # service.materialise_offering is the M2→M3 hook.
```

### Cron / schedules

```bash
# Materialise class_sessions for the next 14 days across every college:
npm run materialise
# Or per-college, custom window:
uv run --project services/api python -m app.cli materialise \
  --college <uuid> --from 2026-08-01 --to 2026-08-14
```

Run this on a daily cron (host crontab, GH Actions, or whatever scheduler your environment provides). On-demand materialisation already happens when `/sessions/{id}/qr` is hit and a session row doesn't exist yet, so cron lag never blocks a teacher.
