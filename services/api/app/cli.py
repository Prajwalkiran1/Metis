"""Operational CLI for ad-hoc / scheduled jobs.

Run from the project root (uses uv to pick up services/api's venv):

    uv run --project services/api python -m app.cli materialise --window-days=14
    uv run --project services/api python -m app.cli materialise --college=<uuid> --from=2026-08-01 --to=2026-08-14

Schedule via host cron / systemd / GitHub Actions — see services/api/README.md.

Add new sub-commands here as modules need them.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.modules.attendance.service import materialise_window
from app.modules.users.models import College


async def _materialise(args: argparse.Namespace) -> int:
    from_date = (
        date.fromisoformat(args.from_date)
        if args.from_date
        else date.today()
    )
    to_date = (
        date.fromisoformat(args.to_date)
        if args.to_date
        else from_date + timedelta(days=args.window_days)
    )
    if to_date < from_date:
        print(f"error: --to ({to_date}) is before --from ({from_date})")
        return 2

    async with SessionLocal() as session:
        if args.college:
            college_ids = [UUID(args.college)]
        else:
            college_ids = (
                await session.execute(select(College.id))
            ).scalars().all()
        total = 0
        for cid in college_ids:
            n = await materialise_window(
                session, college_id=cid, from_date=from_date, to_date=to_date
            )
            total += n
            print(f"college={cid}: upserted {n} class_sessions")
        await session.commit()
    print(f"=== done. Total upserted: {total} (window {from_date}..{to_date})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser(
        "materialise",
        help="Materialise class_sessions from M2's timetable.",
    )
    m.add_argument(
        "--college",
        default=None,
        help="College UUID. Omit to run across every college.",
    )
    m.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="ISO date (defaults to today).",
    )
    m.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="ISO date (defaults to --from + --window-days).",
    )
    m.add_argument(
        "--window-days",
        type=int,
        default=14,
        help="Window length when --to is omitted (default 14).",
    )
    return parser


async def _amain() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.cmd == "materialise":
            return await _materialise(args)
    finally:
        await engine.dispose()
    return 1


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
