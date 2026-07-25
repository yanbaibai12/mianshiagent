from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user, require_admin_user
from app.config import get_settings
from app.services.business import (
    build_admin_usage_summary,
    grant_plan_to_user,
    get_business_snapshot,
    get_or_create_billing_account,
    record_usage,
)

router = APIRouter(prefix="/api/business", tags=["business"])


class GrantPlanRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    plan: Literal["free", "pro", "enterprise"] = "pro"
    days: int | None = Field(default=30, ge=1, le=3650)
    notes: str | None = Field(default=None, max_length=500)


@router.get("/entitlements")
async def entitlements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_business_snapshot(db, current_user.id)


@router.post("/upgrade-request")
async def request_upgrade(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = get_settings()
    await get_or_create_billing_account(db, current_user.id)
    record_usage(
        db,
        current_user.id,
        "upgrade_request",
        metadata={
            "payment_provider": settings.PAYMENT_PROVIDER or "manual",
            "upgrade_contact": settings.BILLING_UPGRADE_CONTACT,
        },
    )
    log_audit_event(
        db,
        event_type="billing.upgrade_request",
        resource_type="billing_account",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        resource_id=str(current_user.id),
        request=request,
        metadata={"payment_provider": settings.PAYMENT_PROVIDER or "manual"},
    )
    await db.commit()

    return {
        "message": "升级意向已记录，请通过配置的联系方式或支付渠道开通权益。",
        "payment_provider": settings.PAYMENT_PROVIDER or "manual",
        "upgrade_contact": settings.BILLING_UPGRADE_CONTACT,
        "pro_monthly_price_cny": settings.PRO_MONTHLY_PRICE_CNY,
    }


@router.get("/admin/usage-summary")
async def admin_usage_summary(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await build_admin_usage_summary(db, days=days, limit=limit)


@router.post("/admin/grant-plan")
async def admin_grant_plan(
    req: GrantPlanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    account = await grant_plan_to_user(
        db,
        email=req.email,
        plan=req.plan,
        days=None if req.plan == "enterprise" else req.days,
        admin_user_id=current_user.id,
        notes=req.notes,
    )
    log_audit_event(
        db,
        event_type="billing.manual_grant",
        resource_type="billing_account",
        actor_user_id=current_user.id,
        target_user_id=account.user_id,
        resource_id=str(account.user_id),
        request=request,
        metadata={"plan": account.plan, "expires_at": str(account.expires_at) if account.expires_at else None},
    )
    await db.commit()
    await db.refresh(account)
    return {
        "message": "套餐已开通",
        "user_id": str(account.user_id),
        "plan": account.plan,
        "status": account.status,
        "source": account.source,
        "expires_at": account.expires_at,
    }
