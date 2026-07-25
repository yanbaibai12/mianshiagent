import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


def _request_ip(request: Request | None) -> str | None:
    if not request:
        return None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:80]
    return request.client.host[:80] if request.client and request.client.host else None


def _user_agent(request: Request | None) -> str | None:
    if not request:
        return None
    return (request.headers.get("user-agent") or "")[:300] or None


def log_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    resource_type: str,
    actor_user_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    record = AuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        organization_id=organization_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=_request_ip(request),
        user_agent=_user_agent(request),
        event_metadata=metadata or {},
    )
    db.add(record)
    return record


async def list_admin_audit_logs(
    db: AsyncSession,
    *,
    limit: int = 100,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    query = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(safe_limit)
    )
    if event_type:
        query = query.where(AuditLog.event_type == event_type)

    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "id": str(record.id),
            "actor_user_id": str(record.actor_user_id) if record.actor_user_id else None,
            "actor_email": email,
            "target_user_id": str(record.target_user_id) if record.target_user_id else None,
            "organization_id": str(record.organization_id) if record.organization_id else None,
            "event_type": record.event_type,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "ip_address": record.ip_address,
            "user_agent": record.user_agent,
            "metadata": record.event_metadata or {},
            "created_at": record.created_at,
        }
        for record, email in rows
    ]
