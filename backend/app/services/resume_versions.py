from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume, ResumeVersion


async def create_resume_version(
    db: AsyncSession,
    resume: Resume,
    *,
    version_type: str,
    title: str,
    data: dict[str, Any],
    jd_text: str | None = None,
    ats_report: dict[str, Any] | None = None,
    change_details: list[Any] | None = None,
    source_task_id: Any = None,
    parent_version_id: Any = None,
    source_job_id: Any = None,
    created_by: str = "system",
    notes: str | None = None,
    make_current: bool = True,
) -> ResumeVersion:
    if make_current:
        await db.execute(
            update(ResumeVersion)
            .where(ResumeVersion.resume_id == resume.id, ResumeVersion.is_current.is_(True))
            .values(is_current=False)
        )
    next_number = (
        await db.scalar(
            select(func.coalesce(func.max(ResumeVersion.version_number), 0) + 1).where(
                ResumeVersion.resume_id == resume.id
            )
        )
    ) or 1
    version = ResumeVersion(
        resume_id=resume.id,
        user_id=resume.user_id,
        organization_id=resume.organization_id,
        version_number=int(next_number),
        version_type=version_type,
        title=title[:200],
        jd_text=jd_text,
        data=data,
        ats_report=ats_report or {},
        change_details=change_details or [],
        source_task_id=source_task_id,
        parent_version_id=parent_version_id,
        source_job_id=source_job_id,
        is_current=make_current,
        created_by=created_by[:40],
        notes=notes,
    )
    db.add(version)
    await db.flush()
    return version


async def ensure_original_version(db: AsyncSession, resume: Resume) -> ResumeVersion | None:
    if not isinstance(resume.parsed_data, dict):
        return None
    existing = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.resume_id == resume.id,
            ResumeVersion.version_type == "original",
        )
    )
    if existing:
        return existing
    return await create_resume_version(
        db,
        resume,
        version_type="original",
        title=f"{resume.title} 原始版",
        data=resume.parsed_data,
        make_current=True,
    )


async def mark_resume_version_current(db: AsyncSession, version: ResumeVersion) -> None:
    await db.execute(
        update(ResumeVersion)
        .where(ResumeVersion.resume_id == version.resume_id, ResumeVersion.is_current.is_(True))
        .values(is_current=False)
    )
    version.is_current = True
    await db.flush()


def build_version_compare(base: ResumeVersion, target: ResumeVersion) -> dict[str, Any]:
    base_changes = base.change_details or []
    target_changes = target.change_details or []
    return {
        "base_version": {
            "id": str(base.id),
            "version_number": base.version_number,
            "title": base.title,
            "version_type": base.version_type,
        },
        "target_version": {
            "id": str(target.id),
            "version_number": target.version_number,
            "title": target.title,
            "version_type": target.version_type,
        },
        "score_delta": (
            float((target.ats_report or {}).get("total_score", 0) or 0)
            - float((base.ats_report or {}).get("total_score", 0) or 0)
        ),
        "change_count_delta": len(target_changes) - len(base_changes),
        "target_change_details": target_changes,
    }
