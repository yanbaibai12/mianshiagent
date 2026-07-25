import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import BillingAccount, Interview, Resume, UsageRecord, User
from app.utils.time import utc_now

FeatureKey = Literal[
    "resume_upload",
    "interview_create",
    "resume_optimize",
    "jd_adapt",
    "report_export",
]


@dataclass(frozen=True)
class FeatureRule:
    key: FeatureKey
    label: str
    free_quota_attr: str
    pro_quota_attr: str
    counter: Literal["active_resumes", "active_interviews", "monthly_usage"]


FEATURE_RULES: dict[FeatureKey, FeatureRule] = {
    "resume_upload": FeatureRule("resume_upload", "简历解析", "FREE_RESUME_QUOTA", "PRO_RESUME_QUOTA", "active_resumes"),
    "interview_create": FeatureRule("interview_create", "模拟面试", "FREE_INTERVIEW_QUOTA", "PRO_INTERVIEW_QUOTA", "active_interviews"),
    "resume_optimize": FeatureRule("resume_optimize", "模板优化", "FREE_OPTIMIZE_QUOTA", "PRO_OPTIMIZE_QUOTA", "monthly_usage"),
    "jd_adapt": FeatureRule("jd_adapt", "JD 定向完善", "FREE_JD_ADAPT_QUOTA", "PRO_JD_ADAPT_QUOTA", "monthly_usage"),
    "report_export": FeatureRule("report_export", "报告导出", "FREE_REPORT_EXPORT_QUOTA", "PRO_REPORT_EXPORT_QUOTA", "monthly_usage"),
}


def _month_start(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _remaining(limit: int | None, used: int) -> int | None:
    return None if limit is None else max(limit - used, 0)


def _llm_metrics(metadata: dict[str, Any] | None) -> dict[str, float | int]:
    metadata = metadata or {}
    llm = metadata.get("llm")
    llm_calls = metadata.get("llm_calls")
    calls: list[dict[str, Any]] = []
    if isinstance(llm, dict):
        calls.append(llm)
    if isinstance(llm_calls, list):
        calls.extend(item for item in llm_calls if isinstance(item, dict))

    return {
        "call_count": len(calls),
        "input_tokens": int(sum(float(item.get("estimated_input_tokens") or 0) for item in calls)),
        "output_tokens": int(sum(float(item.get("estimated_output_tokens") or 0) for item in calls)),
        "estimated_cost_cny": round(sum(float(item.get("estimated_cost_cny") or 0) for item in calls), 6),
    }


async def get_billing_account(db: AsyncSession, user_id: uuid.UUID) -> BillingAccount | None:
    result = await db.execute(
        select(BillingAccount).where(BillingAccount.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_billing_account(db: AsyncSession, user_id: uuid.UUID) -> BillingAccount:
    account = await get_billing_account(db, user_id)
    if account:
        return account

    account = BillingAccount(user_id=user_id, plan="free", status="active", source="system")
    db.add(account)
    await db.flush()
    return account


def resolve_plan(account: BillingAccount | None) -> str:
    if not account or account.status != "active":
        return "free"
    if account.expires_at and account.expires_at < utc_now():
        return "free"
    plan = (account.plan or "free").lower()
    return plan if plan in {"free", "pro", "enterprise"} else "free"


def _feature_limit(settings: Settings, plan: str, rule: FeatureRule) -> int | None:
    if plan == "enterprise":
        return None
    attr = rule.pro_quota_attr if plan == "pro" else rule.free_quota_attr
    value = int(getattr(settings, attr))
    return None if value < 0 else value


async def _feature_usage_count(db: AsyncSession, user_id: uuid.UUID, rule: FeatureRule) -> int:
    if rule.counter == "active_resumes":
        count = await db.scalar(
            select(func.count()).select_from(Resume).where(Resume.user_id == user_id)
        )
        return int(count or 0)

    if rule.counter == "active_interviews":
        count = await db.scalar(
            select(func.count()).select_from(Interview).where(Interview.user_id == user_id)
        )
        return int(count or 0)

    count = await db.scalar(
        select(func.coalesce(func.sum(UsageRecord.units), 0)).where(
            UsageRecord.user_id == user_id,
            UsageRecord.feature == rule.key,
            UsageRecord.created_at >= _month_start(),
        )
    )
    return int(count or 0)


async def get_usage_counts(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    return {
        "resumes": await _feature_usage_count(db, user_id, FEATURE_RULES["resume_upload"]),
        "interviews": await _feature_usage_count(db, user_id, FEATURE_RULES["interview_create"]),
        "resume_optimize": await _feature_usage_count(db, user_id, FEATURE_RULES["resume_optimize"]),
        "jd_adapt": await _feature_usage_count(db, user_id, FEATURE_RULES["jd_adapt"]),
        "report_export": await _feature_usage_count(db, user_id, FEATURE_RULES["report_export"]),
    }


async def build_feature_entitlements(
    db: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings,
    plan: str,
) -> list[dict[str, Any]]:
    features = []
    for rule in FEATURE_RULES.values():
        used = await _feature_usage_count(db, user_id, rule)
        limit = _feature_limit(settings, plan, rule)
        enforced = settings.BILLING_ENABLED and limit is not None
        features.append(
            {
                "key": rule.key,
                "label": rule.label,
                "used": used,
                "limit": limit,
                "remaining": _remaining(limit, used),
                "enforced": enforced,
                "can_use": True if not enforced else used < limit,
            }
        )
    return features


async def get_business_snapshot(db: AsyncSession, user_id: uuid.UUID) -> dict:
    settings = get_settings()
    account = await get_billing_account(db, user_id)
    plan = resolve_plan(account)
    usage = await get_usage_counts(db, user_id)
    features = await build_feature_entitlements(db, user_id, settings, plan)

    payment_provider = settings.PAYMENT_PROVIDER.strip().lower()
    checkout_available = settings.BILLING_ENABLED and payment_provider not in {"", "manual"}
    feature_map = {item["key"]: item for item in features}
    usage_payload = {
        **usage,
        "resume_optimizations": usage["resume_optimize"],
        "jd_adaptations": usage["jd_adapt"],
        "report_exports": usage["report_export"],
    }

    return {
        "plan": {
            "current": plan,
            "name": {"free": "免费体验版", "pro": "Pro 月卡", "enterprise": "机构版"}[plan],
            "status": account.status if account else "active",
            "source": account.source if account else "system",
            "expires_at": account.expires_at if account else None,
            "billing_enabled": settings.BILLING_ENABLED,
            "payment_provider": payment_provider or "manual",
            "checkout_available": checkout_available,
            "upgrade_contact": settings.BILLING_UPGRADE_CONTACT,
        },
        "usage": usage_payload,
        "quotas": {
            "free_resume_quota": settings.FREE_RESUME_QUOTA,
            "free_interview_quota": settings.FREE_INTERVIEW_QUOTA,
            "free_optimize_quota": settings.FREE_OPTIMIZE_QUOTA,
            "free_jd_adapt_quota": settings.FREE_JD_ADAPT_QUOTA,
            "free_report_export_quota": settings.FREE_REPORT_EXPORT_QUOTA,
            "pro_resume_quota": settings.PRO_RESUME_QUOTA,
            "pro_interview_quota": settings.PRO_INTERVIEW_QUOTA,
            "pro_optimize_quota": settings.PRO_OPTIMIZE_QUOTA,
            "pro_jd_adapt_quota": settings.PRO_JD_ADAPT_QUOTA,
            "pro_report_export_quota": settings.PRO_REPORT_EXPORT_QUOTA,
            "sprint_package_price_cny": settings.SPRINT_PACKAGE_PRICE_CNY,
        },
        "features": features,
        "entitlements": {
            "can_create_resume": bool(feature_map["resume_upload"]["can_use"]),
            "can_create_interview": bool(feature_map["interview_create"]["can_use"]),
            "can_optimize_resume": bool(feature_map["resume_optimize"]["can_use"]),
            "can_adapt_jd": bool(feature_map["jd_adapt"]["can_use"]),
            "can_export_report": bool(feature_map["report_export"]["can_use"]),
            "resume_remaining": feature_map["resume_upload"]["remaining"],
            "interview_remaining": feature_map["interview_create"]["remaining"],
            "optimize_remaining": feature_map["resume_optimize"]["remaining"],
            "jd_adapt_remaining": feature_map["jd_adapt"]["remaining"],
            "report_export_remaining": feature_map["report_export"]["remaining"],
            "paywall_active": settings.BILLING_ENABLED,
            "locked_features": [
                "PDF 报告导出",
                "多岗位 JD 批量适配",
                "更高面试场次额度",
                "专家复盘服务入口",
            ],
        },
        "upgrade": {
            "recommended_plan": "pro_monthly",
            "price_cny": settings.PRO_MONTHLY_PRICE_CNY,
            "sprint_package_price_cny": settings.SPRINT_PACKAGE_PRICE_CNY,
            "cta": "升级 Pro" if checkout_available else "联系管理员开通 Pro",
        },
        "plans": [
            {
                "key": "free",
                "name": "免费版",
                "price_cny": 0,
                "positioning": "完成一条简历到面试报告的体验链路",
            },
            {
                "key": "pro",
                "name": "Pro 月卡",
                "price_cny": settings.PRO_MONTHLY_PRICE_CNY,
                "positioning": "多岗位投递、反复优化和报告导出",
            },
            {
                "key": "enterprise",
                "name": "机构版",
                "price_cny": None,
                "positioning": "账号池、模板定制、知识库和部署支持",
            },
        ],
    }


async def ensure_feature_available(
    feature: FeatureKey,
    db: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    if not settings.BILLING_ENABLED:
        return

    rule = FEATURE_RULES[feature]
    account = await get_billing_account(db, user_id)
    plan = resolve_plan(account)
    limit = _feature_limit(settings, plan, rule)
    if limit is None:
        return

    used = await _feature_usage_count(db, user_id, rule)
    if used < limit:
        return

    raise HTTPException(
        status_code=402,
        detail=f"当前套餐的「{rule.label}」额度已用完：{used}/{limit}。请升级 Pro 或联系管理员人工开通权益。",
        headers={"X-Upgrade-Required": "true", "X-Billable-Feature": feature},
    )


def record_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    feature: FeatureKey | Literal[
        "upgrade_request",
        "manual_plan_grant",
        "payment_checkout",
        "payment_webhook",
        "question_generation",
        "answer_score",
        "interview_report",
    ],
    *,
    quantity: int = 1,
    organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageRecord:
    record = UsageRecord(
        user_id=user_id,
        organization_id=organization_id,
        feature=feature,
        units=quantity,
        record_metadata=metadata or {},
    )
    db.add(record)
    return record


async def build_admin_usage_summary(
    db: AsyncSession,
    *,
    days: int = 30,
    limit: int = 20,
) -> dict[str, Any]:
    safe_days = max(1, min(days, 365))
    safe_limit = max(1, min(limit, 100))
    cutoff = utc_now() - timedelta(days=safe_days)

    user_count = await db.scalar(select(func.count()).select_from(User))
    resume_count = await db.scalar(select(func.count()).select_from(Resume))
    interview_count = await db.scalar(select(func.count()).select_from(Interview))
    billing_count = await db.scalar(select(func.count()).select_from(BillingAccount))

    result = await db.execute(
        select(UsageRecord, User.email)
        .join(User, User.id == UsageRecord.user_id)
        .where(UsageRecord.created_at >= cutoff)
        .order_by(UsageRecord.created_at.desc())
    )
    rows = result.all()

    feature_map: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_llm_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    upgrade_requests = []
    recent_records = []

    for record, email in rows:
        feature = record.feature
        metrics = _llm_metrics(record.record_metadata)
        total_cost += float(metrics["estimated_cost_cny"])
        total_llm_calls += int(metrics["call_count"])
        total_input_tokens += int(metrics["input_tokens"])
        total_output_tokens += int(metrics["output_tokens"])

        feature_stats = feature_map.setdefault(
            feature,
            {
                "feature": feature,
                "units": 0,
                "record_count": 0,
                "llm_call_count": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_cost_cny": 0.0,
            },
        )
        feature_stats["units"] += int(record.units or 0)
        feature_stats["record_count"] += 1
        feature_stats["llm_call_count"] += int(metrics["call_count"])
        feature_stats["estimated_input_tokens"] += int(metrics["input_tokens"])
        feature_stats["estimated_output_tokens"] += int(metrics["output_tokens"])
        feature_stats["estimated_cost_cny"] = round(
            float(feature_stats["estimated_cost_cny"]) + float(metrics["estimated_cost_cny"]),
            6,
        )

        payload = {
            "id": str(record.id),
            "email": email,
            "feature": feature,
            "units": record.units,
            "created_at": record.created_at,
            "estimated_cost_cny": metrics["estimated_cost_cny"],
        }
        if len(recent_records) < safe_limit:
            recent_records.append(payload)
        if feature == "upgrade_request" and len(upgrade_requests) < safe_limit:
            upgrade_requests.append(
                {
                    **payload,
                    "metadata": record.record_metadata or {},
                }
            )

    return {
        "window_days": safe_days,
        "totals": {
            "users": int(user_count or 0),
            "resumes": int(resume_count or 0),
            "interviews": int(interview_count or 0),
            "billing_accounts": int(billing_count or 0),
            "usage_records": len(rows),
            "llm_call_count": total_llm_calls,
            "estimated_input_tokens": total_input_tokens,
            "estimated_output_tokens": total_output_tokens,
            "estimated_cost_cny": round(total_cost, 6),
        },
        "by_feature": sorted(feature_map.values(), key=lambda item: item["record_count"], reverse=True),
        "upgrade_requests": upgrade_requests,
        "recent_records": recent_records,
    }


async def grant_plan_to_user(
    db: AsyncSession,
    *,
    email: str,
    plan: Literal["free", "pro", "enterprise"],
    days: int | None,
    admin_user_id: uuid.UUID,
    notes: str | None = None,
) -> BillingAccount:
    normalized_email = email.strip().lower()
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在，请先让用户注册账号")

    account = await get_or_create_billing_account(db, user.id)
    account.plan = plan
    account.status = "active"
    account.source = "manual"
    account.expires_at = utc_now() + timedelta(days=days) if days else None
    account.notes = notes

    record_usage(
        db,
        user.id,
        "manual_plan_grant",
        metadata={
            "target_email": normalized_email,
            "plan": plan,
            "days": days,
            "admin_user_id": str(admin_user_id),
            "notes": notes,
        },
    )
    return account
