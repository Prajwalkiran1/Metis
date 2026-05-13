# CLEANUP — removing Metis from this machine

This file lists every place Metis writes data on the host, so deleting
the project leaves no trace beyond the baseline tools listed in
`CLAUDE_HEADER.md` (Homebrew, Git, Node, NVM, Python, pyenv, Docker
Desktop, VS Code, GitHub CLI, Claude Code).

Run the steps in order. Re-running any step is safe.

## 1. Stop and remove the Docker stack (drops data)

```bash
cd ~/code/personal/Metis
docker compose -f infra/docker/docker-compose.yml down -v --rmi local
```

`-v` deletes the named volumes (`metis_pgdata`, `metis_redisdata`), so
Postgres rows and Redis keys go with them. `--rmi local` removes
locally-tagged images (none today, but kept in the command so future
custom images get pruned). The official Postgres/Redis images stay in
Docker's image cache; remove them with:

```bash
docker image rm postgres:16-alpine redis:7-alpine  # optional, frees ~150MB
```

Sanity check — these should all return empty:

```bash
docker ps -a   | grep metis_
docker volume ls | grep metis_
```

## 2. Delete the project directory

```bash
rm -rf ~/code/personal/Metis
```

This removes:
- `services/api/.venv/` — the project-local Python venv created by `uv`
- `services/api/.env` — your local secrets
- `apps/web/node_modules/` — Next.js dependencies (added in M2)
- `apps/web/.next/` — Next.js build cache (added in M2)
- every source file and migration

## 3. Optional — remove uv

`uv` was installed during M1 to manage the Python venv. The standalone
installer dropped it at `~/.local/bin/uv`. Remove it only if you don't
want it for other projects:

```bash
rm -f ~/.local/bin/uv ~/.local/bin/uvx
rm -rf ~/.cache/uv      # uv's download cache, harmless to keep
rm -rf ~/.local/share/uv  # uv-managed Python toolchains, harmless to keep
```

## 4. Optional — clean GitHub remote and SSH

Only if you also want to retire the GitHub repository:

```bash
gh repo delete Prajwalkiran1/Metis --yes   # destructive — make sure you don't need it
```

The SSH key in `~/.ssh/id_ed25519` is part of the machine baseline and
is shared across all projects. **Do not** delete it.

## Per-module footprint to revisit as the project grows

When each module ships, append any new external state here so this doc
stays the single deletion checklist:

- [ ] M1 — Postgres tables, Redis keys, OTP emails (logged to console
      in dev — gone with the stack tear-down). No external services.
- [ ] M2 — Adds 10 Postgres tables (departments, courses, batches,
      sections, rooms, course_offerings, timetable_slots,
      timetable_exceptions, academic_calendar, enrollments) + 4 enum
      types. All inside the shared `metis_pgdata` volume — torn down by
      step 1. Adds `apps/web/` bootstrap: Next.js, Tailwind, shadcn-style
      primitives — `node_modules/` and `.next/` are removed by step 2.
      No new external services.
- [ ] M3 — Adds 5 Postgres tables (class_sessions, qr_tokens,
      attendance_records, device_logs, attendance_overrides) + 3 enum
      types (class_session_state, class_session_source,
      attendance_record_state) inside the shared `metis_pgdata` volume —
      torn down by step 1. Adds one frontend dependency
      (`qrcode.react@4.1.0`) which lives in `apps/web/node_modules/`
      and is removed by step 2. The student device fingerprint is
      stored in browser localStorage under key `metis.device_fp` —
      cleared automatically by `Application → Storage → Clear site
      data` in dev tools, or by clearing browser data for
      `localhost:3000`. No new external services.
- [ ] M5 (Comms) — will introduce a real email provider (Resend); add
      "remove sender domain / API key" step when M5 lands.
- [ ] M6 (Content) — object-storage bucket; add bucket-delete step.
- [ ] M7 / M8 (AI) — model artifacts and any vector DB; add purge step.
- [ ] M9 (Admin) — analytics warehouse, if any.

## Verification

After running steps 1–2, all of these should print nothing:

```bash
find ~/Library/Containers -path '*metis*' 2>/dev/null
find ~/.cache -path '*metis*' 2>/dev/null
ls ~/code/personal/Metis 2>/dev/null
docker volume ls | grep metis_
```
