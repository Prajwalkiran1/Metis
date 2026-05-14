"""HOD-scoped read-only placeholder endpoints.

The full M10 workflow ships in later sessions (M10a..e). This module
ships only the `/hod/dashboard` placeholder so the new HOD shell on the
frontend has a real endpoint to hit instead of a 404.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.core.db import SessionDep
from app.core.deps import require_hod
from app.modules.academic.models import (
    CourseOffering,
    Course,
    Department,
    Section,
)
from app.modules.users.models import User

router = APIRouter(prefix="/hod", tags=["hod"])


class TeachingOfferingOut(BaseModel):
    id: UUID
    course_code: str
    course_title: str
    section_name: str
    academic_term: str


class HodDashboardOut(BaseModel):
    department: dict[str, Any]
    teaching_offerings: list[TeachingOfferingOut]
    placeholder: dict[str, Any]


@router.get("/dashboard", response_model=HodDashboardOut)
async def hod_dashboard(
    session: SessionDep,
    actor: User = Depends(require_hod),
) -> HodDashboardOut:
    """Welcome + own teaching offerings + 'M10 will populate this' marker.

    Shipped intentionally bare. The full HOD overview (defaulter lists,
    eligibility heatmap, condonation queue, etc.) lives in M10.
    """
    if actor.hod_of_department_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "hod_dept_missing",
                "message": "HOD user has no department assignment",
            },
        )
    dept = await session.get(Department, actor.hod_of_department_id)
    if dept is None or dept.deleted_at is not None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "dept_not_found",
                "message": "department not found",
            },
        )

    rows = (
        await session.execute(
            select(
                CourseOffering.id,
                Course.code,
                Course.title,
                Section.name,
                CourseOffering.academic_term,
            )
            .join(Course, Course.id == CourseOffering.course_id)
            .join(Section, Section.id == CourseOffering.section_id)
            .where(
                and_(
                    CourseOffering.teacher_user_id == actor.id,
                    CourseOffering.deleted_at.is_(None),
                    CourseOffering.is_active.is_(True),
                )
            )
            .order_by(CourseOffering.academic_term.desc(), Course.code)
        )
    ).all()

    teaching = [
        TeachingOfferingOut(
            id=r.id,
            course_code=r.code,
            course_title=r.title,
            section_name=r.name,
            academic_term=r.academic_term,
        )
        for r in rows
    ]

    # Lightweight counts so the dashboard isn't completely empty. Numbers are
    # informational only — the M10 dashboard will replace them with real
    # widgets (defaulters, eligibility heatmap, condonations).
    dept_offering_count = (
        await session.execute(
            select(func.count(CourseOffering.id))
            .join(Course, Course.id == CourseOffering.course_id)
            .where(
                Course.department_id == dept.id,
                CourseOffering.deleted_at.is_(None),
                CourseOffering.is_active.is_(True),
            )
        )
    ).scalar_one()

    return HodDashboardOut(
        department={"id": str(dept.id), "code": dept.code, "name": dept.name},
        teaching_offerings=teaching,
        placeholder={
            "message": "M10 will populate this dashboard with department analytics.",
            "department_active_offerings": int(dept_offering_count),
        },
    )
