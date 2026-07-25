from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.audit import list_admin_audit_logs
from app.services.auth_service import require_admin_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/admin/logs")
async def admin_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None, max_length=80),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return {"logs": await list_admin_audit_logs(db, limit=limit, event_type=event_type)}
