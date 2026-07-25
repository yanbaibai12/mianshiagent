import hashlib
import hmac
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import BillingAccount, Organization, PaymentOrder, User
from app.utils.time import utc_now


def plan_amount_cny(settings: Settings, plan: str, billing_cycle: str) -> int:
    if plan == "enterprise":
        return 0
    monthly = int(settings.PRO_MONTHLY_PRICE_CNY)
    if billing_cycle == "yearly":
        return monthly * 10
    if billing_cycle == "trial":
        return 0
    return monthly


def build_checkout_url(settings: Settings, order: PaymentOrder) -> str | None:
    if not settings.PAYMENT_CHECKOUT_BASE_URL:
        return None
    separator = "&" if "?" in settings.PAYMENT_CHECKOUT_BASE_URL else "?"
    return (
        f"{settings.PAYMENT_CHECKOUT_BASE_URL}{separator}"
        f"order_id={order.id}&amount_cny={order.amount_cny}&plan={order.plan}"
    )


async def create_payment_order(
    db: AsyncSession,
    *,
    user: User,
    organization: Organization | None,
    plan: str,
    billing_cycle: str,
    settings: Settings,
) -> PaymentOrder:
    provider = (settings.PAYMENT_PROVIDER or "manual").strip().lower()
    amount = plan_amount_cny(settings, plan, billing_cycle)
    order = PaymentOrder(
        user_id=user.id,
        organization_id=organization.id if organization else None,
        provider=provider,
        provider_order_id=f"local-{uuid.uuid4().hex}",
        plan=plan,
        billing_cycle=billing_cycle,
        amount_cny=amount,
        status="pending_manual" if provider == "manual" else "pending",
        raw_payload={},
    )
    db.add(order)
    await db.flush()
    order.checkout_url = build_checkout_url(settings, order)
    return order


def verify_webhook_signature(settings: Settings, raw_body: bytes, signature: str | None) -> None:
    if not settings.PAYMENT_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="未配置支付 webhook 密钥")
    expected = hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="支付 webhook 签名无效")


async def find_payment_order(db: AsyncSession, payload: dict[str, Any]) -> PaymentOrder:
    order_id = payload.get("order_id")
    provider_order_id = payload.get("provider_order_id")
    conditions = []
    if order_id:
        try:
            conditions.append(PaymentOrder.id == uuid.UUID(str(order_id)))
        except ValueError:
            pass
    if provider_order_id:
        conditions.append(PaymentOrder.provider_order_id == str(provider_order_id))
    if not conditions:
        raise HTTPException(status_code=400, detail="webhook 缺少 order_id 或 provider_order_id")

    result = await db.execute(select(PaymentOrder).where(or_(*conditions)))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="支付订单不存在")
    return order


async def mark_order_paid(db: AsyncSession, order: PaymentOrder, payload: dict[str, Any]) -> BillingAccount:
    if order.status == "paid":
        account = await db.get(BillingAccount, order.user_id)
        if account:
            return account

    order.status = "paid"
    order.provider_order_id = str(payload.get("provider_order_id") or order.provider_order_id or order.id)
    order.raw_payload = payload
    order.paid_at = utc_now()

    account = await db.get(BillingAccount, order.user_id)
    if not account:
        account = BillingAccount(user_id=order.user_id, organization_id=order.organization_id)
        db.add(account)
        await db.flush()

    account.plan = order.plan
    account.status = "active"
    account.source = "payment"
    account.organization_id = order.organization_id
    account.expires_at = None if order.plan == "enterprise" else utc_now() + timedelta(days=365 if order.billing_cycle == "yearly" else 30)
    account.notes = f"payment_order:{order.id}"
    return account
