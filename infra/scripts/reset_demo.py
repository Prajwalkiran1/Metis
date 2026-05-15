"""Reset the Metis database for a fresh demo seed.

Drops every row from every application table while keeping the schema
and migration history intact. The single source of truth for "what's an
application table?" is `information_schema.tables` — anything in the
public schema that isn't `alembic_version` gets cleared.

Idempotent: running this twice in a row leaves the database in the same
empty state. The alembic head stays at whatever migration the codebase
last applied, so re-seeding doesn't need a migration re-run.

Run via:
    cd services/api && uv run python -m infra.scripts.reset_demo
or:
    uv run --project services/api python /Users/.../infra/scripts/reset_demo.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from sqlalchemy import text  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402


PRESERVED_TABLES = {"alembic_version"}


async def _list_app_tables(session) -> list[str]:
    rows = (
        await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        )
    ).all()
    return [r[0] for r in rows if r[0] not in PRESERVED_TABLES]


async def _row_count(session, table: str) -> int:
    return (
        await session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
    ).scalar_one()


async def reset() -> tuple[list[tuple[str, int]], str | None]:
    async with SessionLocal() as session:
        tables = await _list_app_tables(session)
        before = [(t, await _row_count(session, t)) for t in tables]

        # Single statement, atomic. RESTART IDENTITY resets sequences (so
        # BigInteger-PK tables like enrollments get fresh ids). CASCADE
        # follows FKs — every table in the public schema is listed, so
        # cascade has nothing to silently widen to.
        quoted = ", ".join(f'"{t}"' for t in tables)
        await session.execute(
            text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
        )
        await session.commit()

        after_total = 0
        for t in tables:
            after_total += await _row_count(session, t)
        head = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()

    assert after_total == 0, f"reset left {after_total} rows behind"
    return before, head


async def main() -> None:
    try:
        before, head = await reset()
    finally:
        await engine.dispose()

    total_before = sum(c for _, c in before)
    print("=" * 60)
    print(f"Metis DB reset complete. alembic_version: {head!r}")
    print(f"Cleared {total_before} rows across {len(before)} application tables.")
    print("=" * 60)
    populated = [(t, c) for t, c in before if c > 0]
    if populated:
        print("Tables that had data (before → 0):")
        for t, c in sorted(populated, key=lambda x: -x[1]):
            print(f"  {t:<32} {c:>10}")
    else:
        print("(All tables were already empty; reset was a no-op.)")
    print("=" * 60)
    print("Next: run `uv run python -m infra.scripts.seed` to repopulate.")


if __name__ == "__main__":
    asyncio.run(main())
