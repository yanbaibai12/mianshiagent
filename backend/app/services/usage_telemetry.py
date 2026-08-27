from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageRecord

UsageFeature = Literal[
    "resume_upload",
    "interview_create",
    "resume_optimize",
    "jd_adapt",
    "report_export",
    "training_plan_generate",
    "training_plan_task_update",
    "training_plan_regenerate",
    "job_preflight",
    "question_generation",
    "answer_score",
    "interview_report",
]


def record_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    feature: UsageFeature,
    *,
    quantity: int = 1,
    organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageRecord:
    """Persist operational usage telemetry without enforcing commercial entitlements."""
    record = UsageRecord(
        user_id=user_id,
        organization_id=organization_id,
        feature=feature,
        units=quantity,
        record_metadata=metadata or {},
    )
    db.add(record)
    return record
