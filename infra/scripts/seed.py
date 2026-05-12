"""Seed the BMSCE pilot tenant: one college, baseline roles + permissions,
three demo users (admin / teacher / student), all active with known
passwords. Idempotent — re-running is a no-op once the college exists.

Run via `npm run seed`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# When invoked as `python -m infra.scripts.seed` from the project root the
# `services/api` package isn't on sys.path. Add it.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.modules.users.models import (  # noqa: E402
    College,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)


DEMO_PASSWORD = "MetisDemo!2026"

ROLES = [
    ("admin", "Full institutional admin"),
    ("teacher", "Teaching staff"),
    ("student", "Enrolled student"),
]

# Coarse-grained permission catalogue. Full RBAC matrix lands when modules need it.
PERMISSIONS = [
    ("user.read", "Read any user in the same college"),
    ("user.write", "Create/update users in the same college"),
    ("user.role_change", "Change another user's role"),
    ("attendance.mark", "Mark attendance for a session"),
    ("marks.write", "Enter marks for an assessment"),
    ("content.publish", "Publish course content"),
    ("comms.send", "Send broadcast communications"),
]

ROLE_PERMISSIONS = {
    "admin": [p[0] for p in PERMISSIONS],
    "teacher": ["user.read", "attendance.mark", "marks.write", "content.publish", "comms.send"],
    "student": ["user.read"],
}


DEMO_USERS = [
    ("admin@bmsce.edu.in", "BMSCE Admin", UserRole.admin),
    ("teacher@bmsce.edu.in", "BMSCE Teacher", UserRole.teacher),
    ("student@bmsce.edu.in", "BMSCE Student", UserRole.student),
]


async def _seed() -> None:
    async with SessionLocal() as session:
        # College
        existing = await session.execute(select(College).where(College.code == "BMSCE"))
        college = existing.scalar_one_or_none()
        created_college = False
        if college is None:
            college = College(
                id=uuid4(),
                name="B.M.S. College of Engineering",
                code="BMSCE",
                dpdp_data_fiduciary_name="B.M.S. Educational Trust",
            )
            session.add(college)
            await session.flush()
            created_college = True

        # Roles
        for name, desc in ROLES:
            r = await session.execute(select(Role).where(Role.name == name))
            if r.scalar_one_or_none() is None:
                session.add(Role(name=name, description=desc))

        # Permissions
        for name, desc in PERMISSIONS:
            p = await session.execute(select(Permission).where(Permission.name == name))
            if p.scalar_one_or_none() is None:
                session.add(Permission(name=name, description=desc))

        await session.flush()

        # Role -> Permission map
        for role_name, perm_names in ROLE_PERMISSIONS.items():
            role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
            for pname in perm_names:
                perm = (
                    await session.execute(select(Permission).where(Permission.name == pname))
                ).scalar_one()
                exists = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if exists.scalar_one_or_none() is None:
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

        # Demo users
        created_users: list[str] = []
        for email, name, role in DEMO_USERS:
            existing_user = await session.execute(
                select(User).where(
                    User.college_id == college.id,
                    User.email == email,
                    User.deleted_at.is_(None),
                )
            )
            if existing_user.scalar_one_or_none() is not None:
                continue
            session.add(
                User(
                    college_id=college.id,
                    email=email,
                    name=name,
                    role=role,
                    status=UserStatus.active,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
            )
            created_users.append(email)

        await session.commit()

    print("=" * 60)
    print("Metis seed complete.")
    print("=" * 60)
    if created_college:
        print("College: B.M.S. College of Engineering (BMSCE) — created")
    else:
        print("College: B.M.S. College of Engineering (BMSCE) — existed")
    if created_users:
        print("Created users:")
        for email in created_users:
            print(f"  {email}  password: {DEMO_PASSWORD}")
    else:
        print("Demo users already existed. Use password:", DEMO_PASSWORD)
    print("=" * 60)


async def main() -> None:
    try:
        await _seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
