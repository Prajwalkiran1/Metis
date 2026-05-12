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

## Module map (M1 + M2)

```
app/
├── main.py
├── core/                # config, logging, db, redis, security, deps, audit, ratelimit, crypto
└── modules/
    ├── system/          # /health, /ready
    ├── auth/            # /auth/*  (login, refresh, logout, password reset)
    ├── users/           # /users/* (CRUD, role/status, profile photo, face enroll)
    ├── invites/         # /invites/* (create, accept)
    ├── consents/        # internal helpers + consent records
    └── academic/        # /departments, /courses, /batches, /sections, /rooms,
                         # /course-offerings, /timetable, /academic-calendar
```
