import hashlib
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AlertNotification
from app.utils.time import utc_now


SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


def _normalized_min_severity(value: str | None) -> str:
    normalized = (value or "critical").lower().strip()
    return normalized if normalized in SEVERITY_RANK else "critical"


def _destination_label(webhook_url: str) -> str:
    parsed = urlparse(webhook_url)
    if parsed.netloc:
        return parsed.netloc[:200]
    return "webhook"


def _alert_hash(alert: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(alert.get("key") or ""),
            str(alert.get("severity") or ""),
            str(alert.get("title") or ""),
            str(alert.get("message") or ""),
            str(alert.get("recommendation") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _eligible_alerts(alerts: dict[str, Any], *, min_severity: str) -> list[dict[str, Any]]:
    threshold = SEVERITY_RANK[_normalized_min_severity(min_severity)]
    eligible = []
    for alert in alerts.get("alerts") or []:
        severity = str(alert.get("severity") or "info").lower()
        if SEVERITY_RANK.get(severity, 0) >= threshold:
            eligible.append(alert)
    return eligible


async def build_alerting_status(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(AlertNotification.status, func.count())
            .group_by(AlertNotification.status)
        )
    ).all()
    recent = (
        await db.execute(
            select(AlertNotification)
            .order_by(AlertNotification.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    return {
        "enabled": settings.ALERT_NOTIFY_ENABLED,
        "configured": bool(settings.ALERT_NOTIFY_ENABLED and settings.ALERT_WEBHOOK_URL),
        "webhook_configured": bool(settings.ALERT_WEBHOOK_URL),
        "token_configured": bool(settings.ALERT_WEBHOOK_TOKEN),
        "min_severity": _normalized_min_severity(settings.ALERT_MIN_SEVERITY),
        "dedupe_minutes": settings.ALERT_DEDUPE_MINUTES,
        "status_counts": {str(status): int(count) for status, count in status_rows},
        "recent": [
            {
                "id": str(item.id),
                "alert_key": item.alert_key,
                "severity": item.severity,
                "feature": item.feature,
                "title": item.title,
                "destination": item.destination,
                "status": item.status,
                "attempts": item.attempts,
                "error_type": item.error_type,
                "error_message": (item.error_message or "")[:240],
                "sent_at": item.sent_at,
                "created_at": item.created_at,
            }
            for item in recent
        ],
    }


async def dispatch_system_alerts(
    db: AsyncSession,
    *,
    settings: Settings,
    alerts: dict[str, Any],
    force: bool = False,
    min_severity: str | None = None,
) -> dict[str, Any]:
    severity = _normalized_min_severity(min_severity or settings.ALERT_MIN_SEVERITY)
    eligible = _eligible_alerts(alerts, min_severity=severity)
    destination = _destination_label(settings.ALERT_WEBHOOK_URL)

    result: dict[str, Any] = {
        "configured": bool(settings.ALERT_NOTIFY_ENABLED and settings.ALERT_WEBHOOK_URL),
        "enabled": settings.ALERT_NOTIFY_ENABLED,
        "min_severity": severity,
        "eligible_count": len(eligible),
        "sent_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "notifications": [],
    }
    if not result["configured"]:
        result["skipped_count"] = len(eligible)
        result["reason"] = "alert_webhook_not_configured"
        return result

    cutoff = utc_now() - timedelta(minutes=max(settings.ALERT_DEDUPE_MINUTES, 1))
    headers = {"content-type": "application/json"}
    if settings.ALERT_WEBHOOK_TOKEN:
        headers["authorization"] = f"Bearer {settings.ALERT_WEBHOOK_TOKEN}"

    for alert in eligible:
        message_hash = _alert_hash(alert)
        existing = None
        if not force:
            existing = await db.scalar(
                select(AlertNotification)
                .where(
                    AlertNotification.alert_key == str(alert.get("key") or "unknown"),
                    AlertNotification.message_hash == message_hash,
                    AlertNotification.status == "sent",
                    AlertNotification.created_at >= cutoff,
                )
                .order_by(AlertNotification.created_at.desc())
            )
        if existing:
            result["skipped_count"] += 1
            result["notifications"].append(
                {
                    "alert_key": existing.alert_key,
                    "status": "skipped",
                    "reason": "deduped",
                    "notification_id": str(existing.id),
                }
            )
            continue

        notification = AlertNotification(
            alert_key=str(alert.get("key") or "unknown")[:160],
            message_hash=message_hash,
            severity=str(alert.get("severity") or "info")[:20],
            feature=str(alert.get("feature") or "system")[:80],
            title=str(alert.get("title") or "系统告警")[:200],
            destination=destination,
            status="pending",
            attempts=0,
        )
        db.add(notification)
        await db.flush()

        payload = {
            "app": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "public_base_url": settings.PUBLIC_BASE_URL,
            "alert": {
                "key": notification.alert_key,
                "severity": notification.severity,
                "feature": notification.feature,
                "title": notification.title,
                "message": str(alert.get("message") or "")[:1000],
                "recommendation": str(alert.get("recommendation") or "")[:1000],
            },
            "created_at": utc_now().isoformat(),
        }
        try:
            notification.attempts += 1
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(settings.ALERT_WEBHOOK_URL, json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                notification.status = "sent"
                notification.sent_at = utc_now()
                result["sent_count"] += 1
            else:
                notification.status = "failed"
                notification.error_type = "WebhookStatusError"
                notification.error_message = f"HTTP {response.status_code}: {response.text[:300]}"
                result["failed_count"] += 1
        except Exception as exc:
            notification.status = "failed"
            notification.error_type = type(exc).__name__
            notification.error_message = str(exc)[:500]
            result["failed_count"] += 1
        notification.updated_at = utc_now()
        await db.flush()
        result["notifications"].append(
            {
                "alert_key": notification.alert_key,
                "status": notification.status,
                "notification_id": str(notification.id),
                "error_type": notification.error_type,
            }
        )

    return result
