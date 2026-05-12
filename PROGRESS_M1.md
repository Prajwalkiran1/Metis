# M1 — User & Auth Service: Complete

Last updated: 2026-05-12.

Status: ✅ **complete** (backend). Next module: M2 — Academic Service.

---

## Where M1 fits in the bigger picture

Metis is a six-layer university platform (per `CLAUDE (1).md` line 93). M1 is the foundation everything else builds on:

- It owns `users`, `colleges`, `roles`, `permissions`, `auth_sessions`, `user_invites`, `password_reset_tokens`, `consents`, `audit_logs`, `login_attempts`.
- It is responsible for issuing access tokens that every other module (M2 academic, M3 attendance, M4 marks…) consumes for authn + tenant isolation via `college_id`.
- The `user.enrolled` event hook is marked with a TODO at the invite-accept site — wiring lands when an event bus exists (likely with M2).

---

## Endpoints shipped

```
GET    /api/v1/health
GET    /api/v1/ready                       db + redis pings, per-check status

POST   /api/v1/auth/login                  rate-limited; lockout via Redis
POST   /api/v1/auth/refresh                rotates the auth_sessions row
POST   /api/v1/auth/logout
POST   /api/v1/auth/reset-password/request OTP via email, always 200
POST   /api/v1/auth/reset-password/confirm

POST   /api/v1/users                       admin invite-create
GET    /api/v1/users/me
GET    /api/v1/users/{user_id}             self or admin, same college
PATCH  /api/v1/users/{user_id}             self profile edit
PATCH  /api/v1/users/{user_id}/role        admin role swap
POST   /api/v1/users/{user_id}/face-enroll AES-GCM encrypted stub, inline consent

POST   /api/v1/invites                     admin issues OTP for an invited user
POST   /api/v1/invites/accept              OTP -> password -> active
```

---

## Files shipped

### Pre-existing (3 earlier commits — kept for the new-session reader)
| File | Role |
|---|---|
| `package.json`, `services/api/pyproject.toml`, `README.md`, `.gitignore`, `CLAUDE (1).md` | Repo scaffold + spec |
| `services/api/.env.example`, `services/api/app/__init__.py`, `services/api/app/main.py`, `services/api/app/core/config.py`, `services/api/app/core/logging.py` | FastAPI bootstrap |
| `services/api/app/modules/system/router.py` | `/health` + `/ready` (real pings since commit `56d4667`) |
| `services/api/alembic.ini`, `services/api/alembic/env.py`, `services/api/alembic/script.py.mako` | Alembic setup |
| `services/api/alembic/versions/0001_updated_at_trigger.py` | The single `set_updated_at()` PG function used by every table trigger |
| `services/api/alembic/versions/0002_baseline_schema.py` | 11-table baseline + indexes + triggers + 3 enums |
| `services/api/app/core/db.py` | Async SQLAlchemy engine + mixins (`TimestampedMixin`, `SoftDeleteMixin`) |
| `services/api/app/modules/users/models.py` | All M1 ORM models in one registry |

### New in M1 completion
| Commit | File | What it does | Role in the architecture |
|---|---|---|---|
| `bd05d02` | `services/api/app/core/redis.py` | Lazy async `Redis` client + `get_redis` dep + `close_redis` on shutdown. | Shared singleton; auth lockout + slowapi + readiness all use it. |
| `bd05d02` | `services/api/app/core/security.py` | argon2 hash/verify, JWT sign/decode, opaque refresh-token + SHA-256 hash, OTP gen/hash. | One module owns every "secret-shaped" primitive. Modules never reach for argon2 / jose directly. |
| `bd05d02` | `services/api/app/core/crypto.py` | AES-256-GCM wrapper. Versioned blob layout (`[version][nonce][ct+tag]`) for face encryption. | Locks in the storage shape before M8's real biometrics land. |
| `bd05d02` | `services/api/app/core/ratelimit.py` | One slowapi `Limiter` keyed on remote address, Redis-backed. | All auth endpoints opt in via `@limiter.limit(auth_rate_limit())`. |
| `bd05d02` | `services/api/app/core/config.py` (modified) | `cors_origins` switched to `Annotated[..., NoDecode]` so CSV env values parse under pydantic-settings 2.6+. | Fix unblocking startup. |
| `56d4667` | `services/api/app/core/deps.py` | `get_current_user`, `require_role`, `require_admin`, `get_client_ip`, `get_user_agent`. | Single gate every authenticated endpoint passes through. |
| `56d4667` | `services/api/app/core/audit.py` | `write_audit(...)` appends to `audit_logs`. | Every mutating endpoint calls it. Tenant isolation via `college_id`. |
| `56d4667` | `services/api/app/modules/system/router.py` (rewritten) | Real `SELECT 1` + Redis `PING` in `/ready`. | Orchestrator can keep pods out of rotation until deps are healthy. |
| `56d4667` | `services/api/app/main.py` (modified) | slowapi handler + `SlowAPIMiddleware` + Redis-on-shutdown. | App composition point. |
| `35c5be9` | `services/api/app/core/email.py` | `console` + `resend` backends. | Used by password reset and invites. Real provider is a one-flag flip. |
| `35c5be9` | `services/api/app/modules/auth/{__init__,schemas,service,router}.py` | The whole auth slice. Lockout, login_attempts, session rotation, OTP-based password reset. | The auth surface every other module sits behind. |
| `e84fec0` (Commit 4) | `services/api/app/modules/users/{schemas,service,router}.py` | User CRUD + role + face-enroll. Cross-college access blocked in the service layer. | Tenant isolation is non-negotiable — enforced at the gateway and again here. |
| `e84fec0` | `services/api/app/modules/invites/{__init__,schemas,service,router}.py` | Issue + accept OTP-backed invites. Supersedes prior unused invites on re-issue. | Onboarding flow for admin-created users. |
| `e84fec0` | `services/api/app/modules/consents/{__init__,service}.py` | DPDP consent grant/withdraw helpers. Append-only history. | Called inline from face-enroll. No router — UI lives in M9. |
| Commit 5 | `infra/docker/docker-compose.yml` | Postgres 16 + Redis 7. Named volumes only. | Local dev stack. Cleanup is `docker compose down -v --rmi local`. |
| Commit 5 | `infra/scripts/seed.py` | Seeds BMSCE + roles + permissions + 3 demo users. Idempotent. | First-run developer experience. |
| Commit 5 | `services/api/tests/{__init__.py,conftest.py,test_auth.py}` | Pytest smoke suite covering happy path, lockout, refresh rotation, authn. | Regression guard for the auth surface. |
| Commit 5 | `CLEANUP.md` | Deletion checklist for the entire project (all modules). | "No traces left on disk" guarantee. |
| Commit 5 | `package.json` (modified) | `seed` and `test:api` run from repo root via `uv run --project services/api`. | Lets the seed import `infra` while still using the api venv. |

---

## Deferred — intentionally not done in M1

| Item | Where | Why deferred |
|---|---|---|
| Refresh-token family / reuse detection | `auth/service.py::rotate_refresh` (TODO marker) | Simple rotate+revoke is enough for M1 pilot. Reuse detection is a follow-up before going to production. |
| `FACE_ENROLLMENT_MIN_AGE` enforcement | `users/service.py::enroll_face` (TODO marker) | Needs a parental-consent flow — full design lands when we have a real face model in M8. |
| Profile-photo upload | `users/schemas.py::UserPatch.profile_photo_url` | No object-storage client yet. M6 (Content) ships the storage layer. |
| Event publishing (`user.enrolled`, `user.role_changed`) | `invites/service.py::accept_invite` (TODO marker), `users/service.py::change_role` | No event-bus infra in the repo. Likely lands with M2. |
| Frontend (`apps/web`) | `package.json` workspaces lists it but folder is empty | Backend-only M1 by agreement; frontend is a separate effort. |

---

## How to bring it up on a fresh machine

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # one-time: install uv
export PATH="$HOME/.local/bin:$PATH"

cd ~/code/personal/Metis
cd services/api && uv sync --all-extras && cd ../..    # creates services/api/.venv
cp services/api/.env.example services/api/.env         # then set JWT_SECRET + FACE_ENCRYPTION_KEY

npm run infra:up                                       # Postgres + Redis (docker compose)
npm run migrate                                        # alembic upgrade head
npm run seed                                           # admin@/teacher@/student@bmsce.edu.in
npm run dev:api                                        # http://localhost:8000/api/v1/docs
npm run test:api                                       # pytest
```

To wipe everything: see `CLEANUP.md`.

---

## Useful re-entry pointers

- Spec for the whole project: `CLAUDE (1).md`. M1 spec is lines 232–259.
- Module map: `services/api/README.md`.
- Cleanup playbook: `CLEANUP.md`.
- Migration convention: any new `updated_at` column → attach `set_updated_at` trigger in the migration. Function created in `0001_updated_at_trigger.py`.
- Model registry: `alembic/env.py` imports `app.modules.users.models`. Add new module imports there.
