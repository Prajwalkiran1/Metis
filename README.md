# Metis

AI-native university platform for BMSCE pilot. Role-based web app (student / teacher / admin) with smart attendance, AI tutor, AI insights, comms, marks, and content management.

> Status: M1 (User & Auth) in progress. See `CLAUDE (1).md` for the full project spec and `docs/modules/M1.md` for the M1 module spec once published.

## Repo layout

```
apps/web              Next.js 14 frontend (App Router)
apps/mobile           PWA attendance client (later)
services/api          FastAPI backend (modular: users, academic, attendance, …)
services/ai           AI services (M7 learning engine, M8 insights — later)
infra/docker          Local docker-compose stack
infra/scripts         Seeding and operational scripts
docs/adr              Architecture Decision Records
docs/modules          Per-module specs (M1.md, M2.md, …)
tests/                Cross-service integration and e2e tests
```

## Prerequisites

- Node.js ≥ 20 + npm 11
- Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker Desktop (for local Postgres + Redis), **or** a Supabase + Upstash project for cloud-mode dev

## Quickstart (local)

```bash
# 1. Install backend deps
cd services/api && uv sync --all-extras

# 2. Start Postgres + Redis
npm run infra:up

# 3. Apply migrations and seed
npm run migrate
npm run seed

# 4. Run the API (port 8000) and the web app (port 3000) in two terminals
npm run dev:api
npm run dev:web
```

Seeded credentials (printed to the API log on first seed): `admin@bmsce.edu.in`, `teacher@bmsce.edu.in`, `student@bmsce.edu.in`.

## Environment

Copy `.env.example` to `.env` (api) and `.env.local` (web) and adjust:

- `services/api/.env` — DB URL, Redis URL, JWT secret, face encryption key, CORS origins
- `apps/web/.env.local` — `NEXT_PUBLIC_API_BASE_URL`

For cloud mode (Supabase + Upstash) point `DATABASE_URL` and `REDIS_URL` at your provisioned services and skip `npm run infra:up`.

## License

MIT.
