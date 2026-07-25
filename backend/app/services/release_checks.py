from dataclasses import dataclass
from typing import Literal

from app.config import Settings

Severity = Literal["pass", "warning", "critical"]


@dataclass
class ReleaseCheck:
    key: str
    severity: Severity
    message: str
    recommendation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
            "recommendation": self.recommendation,
        }


def _has_local_origin(origins: list[str]) -> bool:
    return any("localhost" in origin or "127.0.0.1" in origin for origin in origins)


def run_release_checks(settings: Settings) -> dict:
    checks: list[ReleaseCheck] = []
    is_production = settings.is_production
    payment_provider = settings.PAYMENT_PROVIDER.strip().lower()
    secret_is_default = settings.SECRET_KEY in {
        "your-secret-key-here-change-in-production",
        "local-mvp-secret-change-before-production",
    }

    checks.append(
        ReleaseCheck(
            key="secret_key",
            severity="critical" if secret_is_default or len(settings.SECRET_KEY) < 32 else "pass",
            message="SECRET_KEY 使用默认值或长度过短" if secret_is_default or len(settings.SECRET_KEY) < 32 else "SECRET_KEY 已配置",
            recommendation="生产环境使用至少 32 位随机字符串，并通过密钥管理服务或环境变量注入。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="debug",
            severity="critical" if is_production and settings.DEBUG else "pass",
            message="生产环境不应开启 DEBUG" if is_production and settings.DEBUG else "DEBUG 配置可接受",
            recommendation="生产环境设置 DEBUG=false。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="docs",
            severity="critical" if is_production and settings.ENABLE_DOCS else "pass",
            message="生产环境不应公开 API 文档" if is_production and settings.ENABLE_DOCS else "API 文档暴露配置可接受",
            recommendation="生产环境设置 ENABLE_DOCS=false，仅在内网或测试环境开放 /docs。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="database",
            severity="critical" if is_production and settings.DATABASE_URL.startswith("sqlite") else "warning" if settings.DATABASE_URL.startswith("sqlite") else "pass",
            message="当前使用 SQLite" if settings.DATABASE_URL.startswith("sqlite") else "数据库配置可用于多人环境",
            recommendation="正式发布使用 PostgreSQL，并开启备份和迁移流程。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="auto_create_db",
            severity="critical" if is_production and settings.AUTO_CREATE_DB else "pass",
            message="生产环境不应在应用启动时自动建表" if is_production and settings.AUTO_CREATE_DB else "数据库建表策略可接受",
            recommendation="生产环境设置 AUTO_CREATE_DB=false，并通过 Alembic 执行迁移。",
        )
    )

    llm_local = settings.LLM_PROVIDER.lower() == "local" or not settings.LLM_API_KEY
    checks.append(
        ReleaseCheck(
            key="llm",
            severity="critical" if is_production and llm_local else "warning" if llm_local else "pass",
            message="当前使用本地 LLM 兜底或未配置真实模型 Key" if llm_local else "LLM 已配置",
            recommendation="正式收费前配置真实 LLM，并记录模型成本、失败率和降级策略。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="llm_fallback",
            severity="critical" if is_production and settings.LLM_ALLOW_FALLBACK else "warning" if settings.LLM_ALLOW_FALLBACK else "pass",
            message="LLM 失败会降级到本地规则结果" if settings.LLM_ALLOW_FALLBACK else "LLM 失败不会静默兜底",
            recommendation="收费产品应明确提示模型失败；如启用兜底，需要在前端和运营日志中标识结果来源。",
        )
    )

    cors_unsafe = "*" in settings.CORS_ALLOW_ORIGINS or (is_production and _has_local_origin(settings.CORS_ALLOW_ORIGINS))
    checks.append(
        ReleaseCheck(
            key="cors",
            severity="critical" if cors_unsafe else "pass",
            message="CORS 包含 wildcard 或生产仍指向 localhost" if cors_unsafe else "CORS 白名单可接受",
            recommendation="生产只允许正式前端域名，例如 https://app.example.com。",
        )
    )

    host_unsafe = "*" in settings.TRUSTED_HOSTS or (is_production and any(host in {"localhost", "127.0.0.1", "testserver"} for host in settings.TRUSTED_HOSTS))
    checks.append(
        ReleaseCheck(
            key="trusted_hosts",
            severity="critical" if host_unsafe else "pass",
            message="Trusted hosts 包含 wildcard 或生产仍使用本地域名" if host_unsafe else "Trusted hosts 可接受",
            recommendation="生产只允许 API 正式域名，例如 api.example.com。",
        )
    )

    https_missing = is_production and not settings.PUBLIC_BASE_URL.startswith("https://")
    checks.append(
        ReleaseCheck(
            key="https",
            severity="critical" if https_missing else "pass",
            message="生产公开地址不是 HTTPS" if https_missing else "公开地址协议可接受",
            recommendation="生产必须通过 HTTPS 访问，TLS 通常由 Nginx/CDN/网关终止。",
        )
    )

    token_too_long = settings.ACCESS_TOKEN_EXPIRE_MINUTES > 24 * 60
    checks.append(
        ReleaseCheck(
            key="token_ttl",
            severity="warning" if token_too_long else "pass",
            message="访问 Token 有效期超过 24 小时" if token_too_long else "Token 有效期可接受",
            recommendation="正式产品建议使用短 access token + refresh token，降低泄露影响。",
        )
    )

    rate_limit_weak = settings.RATE_LIMIT_AUTH_REQUESTS > 60 or settings.RATE_LIMIT_API_REQUESTS > 600
    checks.append(
        ReleaseCheck(
            key="rate_limit",
            severity="warning" if rate_limit_weak else "pass",
            message="限流阈值偏宽" if rate_limit_weak else "限流阈值可接受",
            recommendation="根据真实流量调整，并在多实例部署时切换到 Redis/网关限流。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="billing",
            severity="warning" if not settings.BILLING_ENABLED else "pass",
            message="计费/权益开关未开启" if not settings.BILLING_ENABLED else "计费/权益开关已开启",
            recommendation="正式收费前至少接入权益扣减，支付可先使用人工开通或第三方支付。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="metrics",
            severity="pass" if settings.METRICS_ENABLED else "warning",
            message="运行指标已启用" if settings.METRICS_ENABLED else "运行指标未启用",
            recommendation="生产环境保持 METRICS_ENABLED=true，并接入网关/云监控告警。",
        )
    )

    backup_missing = is_production and not settings.BACKUP_ENABLED
    checks.append(
        ReleaseCheck(
            key="backup",
            severity="critical" if backup_missing else "pass" if settings.BACKUP_ENABLED else "warning",
            message="生产环境缺少备份策略" if backup_missing else "备份策略已启用" if settings.BACKUP_ENABLED else "备份策略未启用",
            recommendation="生产环境配置 BACKUP_ENABLED=true、BACKUP_DIR 和 BACKUP_RETENTION_DAYS，并使用云数据库 PITR 或定时快照。",
        )
    )

    canary_invalid = settings.CANARY_PERCENT < 0 or settings.CANARY_PERCENT > 100
    checks.append(
        ReleaseCheck(
            key="canary",
            severity="critical" if canary_invalid else "pass",
            message="灰度比例必须在 0-100 之间" if canary_invalid else "灰度发布配置可接受",
            recommendation="使用 CANARY_PERCENT 控制灰度流量，DEPLOYMENT_COLOR 标识 blue/green 部署版本。",
        )
    )

    payment_missing = settings.BILLING_ENABLED and not payment_provider
    payment_invalid = bool(payment_provider) and payment_provider not in {"stripe", "wechatpay", "alipay", "manual"}
    checks.append(
        ReleaseCheck(
            key="payment_provider",
            severity="critical" if payment_invalid else "warning" if payment_missing else "pass",
            message="支付渠道配置不支持" if payment_invalid else "已开启计费但未配置支付渠道" if payment_missing else "支付渠道配置可接受",
            recommendation="国内优先配置微信支付/支付宝，海外优先 Stripe；早期 B 端可使用 manual。",
        )
    )

    webhook_required = settings.BILLING_ENABLED and payment_provider not in {"", "manual"} and not settings.PAYMENT_WEBHOOK_SECRET
    checks.append(
        ReleaseCheck(
            key="payment_webhook",
            severity="critical" if webhook_required else "pass" if settings.PAYMENT_WEBHOOK_SECRET or payment_provider == "manual" else "warning",
            message="真实支付缺少 webhook 签名密钥" if webhook_required else "支付 webhook 配置可接受" if settings.PAYMENT_WEBHOOK_SECRET or payment_provider == "manual" else "支付 webhook 未配置",
            recommendation="真实支付必须配置 PAYMENT_WEBHOOK_SECRET，并在支付网关回调中校验签名后再开通权益。",
        )
    )

    contact_missing = (
        (not settings.BILLING_ENABLED and not settings.BILLING_UPGRADE_CONTACT)
        or (
            settings.BILLING_ENABLED
            and payment_provider == "manual"
            and not settings.BILLING_UPGRADE_CONTACT
        )
    )
    checks.append(
        ReleaseCheck(
            key="billing_contact",
            severity="warning" if contact_missing else "pass",
            message="缺少升级联系方式" if contact_missing else "升级联系方式配置可接受",
            recommendation="PAYMENT_PROVIDER=manual 时配置 BILLING_UPGRADE_CONTACT，确保用户超额后能完成转化。",
        )
    )

    admin_missing = (
        is_production
        and settings.BILLING_ENABLED
        and payment_provider == "manual"
        and not settings.admin_email_list
    )
    checks.append(
        ReleaseCheck(
            key="admin_emails",
            severity="critical" if admin_missing else "pass" if settings.admin_email_list else "warning",
            message="manual 计费模式缺少管理员邮箱" if admin_missing else "管理员邮箱已配置" if settings.admin_email_list else "未配置管理员邮箱",
            recommendation="配置 ADMIN_EMAILS，用逗号分隔，可用于人工开通 Pro、查看用量和处理升级意向。",
        )
    )

    quota_invalid = any(
        value < 0
        for value in [
            settings.FREE_RESUME_QUOTA,
            settings.FREE_INTERVIEW_QUOTA,
            settings.FREE_OPTIMIZE_QUOTA,
            settings.FREE_JD_ADAPT_QUOTA,
            settings.FREE_REPORT_EXPORT_QUOTA,
            settings.PRO_RESUME_QUOTA,
            settings.PRO_INTERVIEW_QUOTA,
            settings.PRO_OPTIMIZE_QUOTA,
            settings.PRO_JD_ADAPT_QUOTA,
            settings.PRO_REPORT_EXPORT_QUOTA,
        ]
    )
    checks.append(
        ReleaseCheck(
            key="billing_quota",
            severity="critical" if quota_invalid else "pass",
            message="存在负数权益额度配置" if quota_invalid else "权益额度配置可接受",
            recommendation="所有免费版和 Pro 额度必须为 0 或正整数；如需无限制，使用企业版套餐逻辑处理。",
        )
    )

    quota_ladder_invalid = (
        settings.PRO_RESUME_QUOTA < settings.FREE_RESUME_QUOTA
        or settings.PRO_INTERVIEW_QUOTA < settings.FREE_INTERVIEW_QUOTA
        or settings.PRO_OPTIMIZE_QUOTA < settings.FREE_OPTIMIZE_QUOTA
        or settings.PRO_JD_ADAPT_QUOTA < settings.FREE_JD_ADAPT_QUOTA
        or settings.PRO_REPORT_EXPORT_QUOTA < settings.FREE_REPORT_EXPORT_QUOTA
    )
    checks.append(
        ReleaseCheck(
            key="billing_quota_ladder",
            severity="warning" if quota_ladder_invalid else "pass",
            message="Pro 权益额度低于免费版" if quota_ladder_invalid else "权益阶梯配置可接受",
            recommendation="付费权益至少应覆盖免费权益，并在核心功能上形成清晰升级理由。",
        )
    )

    price_invalid = settings.PRO_MONTHLY_PRICE_CNY <= 0 or settings.SPRINT_PACKAGE_PRICE_CNY <= 0
    checks.append(
        ReleaseCheck(
            key="billing_price",
            severity="critical" if settings.BILLING_ENABLED and price_invalid else "warning" if price_invalid else "pass",
            message="商业价格必须为正数" if price_invalid else "商业价格配置可接受",
            recommendation="检查 PRO_MONTHLY_PRICE_CNY 和 SPRINT_PACKAGE_PRICE_CNY，确保发布页展示与后台配置一致。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="public_base_url",
            severity="warning" if not settings.PUBLIC_BASE_URL else "pass",
            message="PUBLIC_BASE_URL 未配置" if not settings.PUBLIC_BASE_URL else "PUBLIC_BASE_URL 已配置",
            recommendation="配置为用户访问的正式前端地址，用于回调、导出和分享链接。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="release_gate",
            severity="pass" if settings.ENFORCE_RELEASE_CHECKS else "warning",
            message="生产发布阻断已启用" if settings.ENFORCE_RELEASE_CHECKS else "生产发布阻断未启用",
            recommendation="正式发布建议保持 ENFORCE_RELEASE_CHECKS=true，避免危险配置启动。",
        )
    )

    critical = [check for check in checks if check.severity == "critical"]
    warnings = [check for check in checks if check.severity == "warning"]
    return {
        "environment": settings.APP_ENV,
        "publishable": len(critical) == 0,
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "checks": [check.to_dict() for check in checks],
    }


def assert_release_ready(settings: Settings) -> None:
    if not settings.is_production or not settings.ENFORCE_RELEASE_CHECKS:
        return

    result = run_release_checks(settings)
    if result["publishable"]:
        return

    blockers = [
        f"{check['key']}: {check['message']}"
        for check in result["checks"]
        if check["severity"] == "critical"
    ]
    raise RuntimeError("生产发布检查未通过：" + "；".join(blockers))
