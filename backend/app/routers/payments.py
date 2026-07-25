from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import PaymentOrder, User
from app.schemas import CheckoutCreateRequest, CheckoutCreateResponse, PaymentOrderResponse
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.business import record_usage
from app.services.payments import create_payment_order, find_payment_order, mark_order_paid, verify_webhook_signature
from app.services.tenancy import resolve_request_organization, tenant_metadata

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/checkout", response_model=CheckoutCreateResponse)
async def create_checkout(
    req: CheckoutCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = get_settings()
    org = await resolve_request_organization(request, db, current_user)
    order = await create_payment_order(
        db,
        user=current_user,
        organization=org,
        plan=req.plan,
        billing_cycle=req.billing_cycle,
        settings=settings,
    )
    record_usage(
        db,
        current_user.id,
        "payment_checkout",
        organization_id=org.id,
        metadata={"order_id": str(order.id), "plan": order.plan, "amount_cny": order.amount_cny},
    )
    log_audit_event(
        db,
        event_type="payment.checkout",
        resource_type="payment_order",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=str(order.id),
        request=request,
        metadata={"provider": order.provider, "plan": order.plan, "amount_cny": order.amount_cny, **tenant_metadata(org)},
    )
    await db.commit()
    return CheckoutCreateResponse(
        order_id=order.id,
        provider=order.provider,
        plan=order.plan,
        billing_cycle=order.billing_cycle,
        amount_cny=order.amount_cny,
        status=order.status,
        checkout_url=order.checkout_url,
        message="已创建支付订单" if order.checkout_url else "已创建订单，请按配置的支付渠道完成付款",
    )


@router.get("/orders", response_model=list[PaymentOrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PaymentOrder).where(PaymentOrder.user_id == current_user.id).order_by(PaymentOrder.created_at.desc())
    )
    return result.scalars().all()


@router.post("/webhook")
async def payment_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    raw_body = await request.body()
    verify_webhook_signature(settings, raw_body, request.headers.get("x-payment-signature"))
    payload = await request.json()
    order = await find_payment_order(db, payload)
    status = str(payload.get("status") or payload.get("event_type") or "").lower()
    if status not in {"paid", "payment.paid", "success"}:
        order.raw_payload = payload
        await db.commit()
        return {"message": "webhook 已记录", "status": order.status}

    account = await mark_order_paid(db, order, payload)
    record_usage(
        db,
        order.user_id,
        "payment_webhook",
        organization_id=order.organization_id,
        metadata={"order_id": str(order.id), "status": "paid", "provider_order_id": order.provider_order_id},
    )
    log_audit_event(
        db,
        event_type="payment.paid",
        resource_type="payment_order",
        actor_user_id=order.user_id,
        target_user_id=order.user_id,
        organization_id=order.organization_id,
        resource_id=str(order.id),
        request=request,
        metadata={"plan": account.plan, "provider_order_id": order.provider_order_id},
    )
    await db.commit()
    return {"message": "支付成功，套餐已开通", "order_id": str(order.id), "plan": account.plan}
