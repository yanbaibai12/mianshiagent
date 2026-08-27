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


def _has_local_origin(origins: list[str] | str) -> bool:
    values = [item.strip() for item in origins.split(",")] if isinstance(origins, str) else origins
    return any("localhost" in origin or "127.0.0.1" in origin for origin in values)


def _is_local_endpoint(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return any(marker in normalized for marker in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))


def run_release_checks(settings: Settings) -> dict:
    checks: list[ReleaseCheck] = []
    is_production = settings.is_production
    secret_is_default = settings.SECRET_KEY in {
        "your-secret-key-here-change-in-production",
        "local-mvp-secret-change-before-production",
    }

    checks.append(
        ReleaseCheck(
            key="secret_key",
            severity="critical" if secret_is_default or len(settings.SECRET_KEY) < 32 else "pass",
            message="SECRET_KEY 使用默认值或长度过短"
            if secret_is_default or len(settings.SECRET_KEY) < 32
            else "SECRET_KEY 已配置",
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
            severity="critical"
            if is_production and settings.DATABASE_URL.startswith("sqlite")
            else "warning"
            if settings.DATABASE_URL.startswith("sqlite")
            else "pass",
            message="当前使用 SQLite" if settings.DATABASE_URL.startswith("sqlite") else "数据库配置可用于多人环境",
            recommendation="正式发布使用 PostgreSQL，并开启备份和迁移流程。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="auto_create_db",
            severity="critical" if is_production and settings.AUTO_CREATE_DB else "pass",
            message="生产环境不应在应用启动时自动建表"
            if is_production and settings.AUTO_CREATE_DB
            else "数据库建表策略可接受",
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
            severity="critical"
            if is_production and settings.LLM_ALLOW_FALLBACK
            else "warning"
            if settings.LLM_ALLOW_FALLBACK
            else "pass",
            message="LLM 失败会降级到本地规则结果" if settings.LLM_ALLOW_FALLBACK else "LLM 失败不会静默兜底",
            recommendation="收费产品应明确提示模型失败；如启用兜底，需要在前端和运营日志中标识结果来源。",
        )
    )

    explicit_core_models = [
        settings.LLM_JD_ADAPT_MODEL,
        settings.LLM_INTERVIEW_QUESTION_MODEL,
        settings.LLM_ANSWER_SCORE_MODEL,
        settings.LLM_INTERVIEW_REPORT_MODEL,
    ]
    llm_profiles_missing = any(not str(model or "").strip() for model in explicit_core_models)
    checks.append(
        ReleaseCheck(
            key="llm_profiles",
            severity="warning" if llm_profiles_missing else "pass",
            message="核心 AI 功能存在未显式配置的模型 profile"
            if llm_profiles_missing
            else "核心 AI 功能模型 profile 已显式配置",
            recommendation="为 JD 优化、面试出题、答案评分、报告生成分别配置 LLM_*_MODEL，并在 /api/system/status 查看 prompt_version 和 model。",
        )
    )

    cors_unsafe = "*" in settings.CORS_ALLOW_ORIGINS or (
        is_production and _has_local_origin(settings.CORS_ALLOW_ORIGINS)
    )
    checks.append(
        ReleaseCheck(
            key="cors",
            severity="critical" if cors_unsafe else "pass",
            message="CORS 包含 wildcard 或生产仍指向 localhost" if cors_unsafe else "CORS 白名单可接受",
            recommendation="生产只允许正式前端域名，例如 https://app.example.com。",
        )
    )

    host_unsafe = "*" in settings.TRUSTED_HOSTS or (
        is_production and any(host in {"localhost", "127.0.0.1", "testserver"} for host in settings.TRUSTED_HOSTS)
    )
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
            key="metrics",
            severity="pass" if settings.METRICS_ENABLED else "warning",
            message="运行指标已启用" if settings.METRICS_ENABLED else "运行指标未启用",
            recommendation="生产环境保持 METRICS_ENABLED=true，并接入网关/云监控告警。",
        )
    )

    alert_webhook_missing = settings.ALERT_NOTIFY_ENABLED and not settings.ALERT_WEBHOOK_URL
    alerting_absent = is_production and not settings.ALERT_NOTIFY_ENABLED
    checks.append(
        ReleaseCheck(
            key="alert_webhook",
            severity="critical" if alert_webhook_missing else "warning" if alerting_absent else "pass",
            message="告警通知已开启但缺少 Webhook 地址"
            if alert_webhook_missing
            else "生产环境未开启主动告警通知"
            if alerting_absent
            else "主动告警通知配置可接受",
            recommendation="生产环境建议配置 ALERT_NOTIFY_ENABLED=true、ALERT_WEBHOOK_URL 和 ALERT_MIN_SEVERITY，用于企业微信/飞书/Sentry 等外部告警渠道。",
        )
    )

    task_backend = settings.TASK_QUEUE_BACKEND.lower().strip()
    task_backend_ok = task_backend in {"redis", "rq", "redis-rq", "redis_rq"}
    checks.append(
        ReleaseCheck(
            key="task_queue_backend",
            severity="critical"
            if is_production and not task_backend_ok
            else "warning"
            if not task_backend_ok
            else "pass",
            message="长任务仍使用本地队列" if not task_backend_ok else "长任务队列已配置为 Redis/RQ",
            recommendation="生产环境设置 TASK_QUEUE_BACKEND=redis_rq，并独立启动 RQ worker；本地队列只允许开发调试。",
        )
    )

    redis_local = _is_local_endpoint(settings.TASK_REDIS_URL)
    checks.append(
        ReleaseCheck(
            key="task_redis_url",
            severity="critical"
            if is_production and task_backend_ok and redis_local
            else "warning"
            if task_backend_ok and redis_local
            else "pass",
            message="Redis 指向本机地址" if redis_local else "Redis 连接地址可接受",
            recommendation="生产环境使用独立 Redis 服务或云 Redis，并为 worker/API 使用同一个队列名和连接串。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="task_local_fallback",
            severity="critical"
            if is_production and settings.TASK_ALLOW_LOCAL_FALLBACK
            else "warning"
            if settings.TASK_ALLOW_LOCAL_FALLBACK
            else "pass",
            message="任务队列失败会降级到本地后台任务"
            if settings.TASK_ALLOW_LOCAL_FALLBACK
            else "任务队列失败不会静默本地降级",
            recommendation="生产环境设置 TASK_ALLOW_LOCAL_FALLBACK=false，避免多实例部署时任务丢失或重复执行。",
        )
    )

    vector_backend = settings.VECTOR_STORE_BACKEND.lower().strip()
    qdrant_enabled = vector_backend == "qdrant"
    qdrant_external = bool(settings.QDRANT_URL and not _is_local_endpoint(settings.QDRANT_URL))
    checks.append(
        ReleaseCheck(
            key="qdrant_external",
            severity="critical"
            if is_production and not (qdrant_enabled and qdrant_external)
            else "warning"
            if qdrant_enabled and not qdrant_external
            else "pass",
            message="Qdrant 未使用外部服务"
            if qdrant_enabled and not qdrant_external
            else "向量库不是 Qdrant"
            if not qdrant_enabled
            else "Qdrant 已配置外部服务",
            recommendation="生产环境设置 VECTOR_STORE_BACKEND=qdrant、QDRANT_URL=https://... 或内网服务地址；embedded Qdrant 只适合本地开发。",
        )
    )

    bge_m3_expected = settings.EMBEDDING_MODEL.lower().endswith("bge-m3") and settings.QDRANT_VECTOR_SIZE == 1024
    checks.append(
        ReleaseCheck(
            key="embedding_vector_size",
            severity="warning" if not bge_m3_expected else "pass",
            message="Embedding 模型与 Qdrant 维度需要复核" if not bge_m3_expected else "BGE-M3 与 1024 维索引配置一致",
            recommendation="使用 BAAI/bge-m3 时保持 QDRANT_VECTOR_SIZE=1024；切换模型必须重建知识库和简历索引。",
        )
    )

    embedding_hash = settings.EMBEDDING_PROVIDER.lower().strip() == "hash"
    checks.append(
        ReleaseCheck(
            key="embedding_provider",
            severity="critical" if is_production and embedding_hash else "warning" if embedding_hash else "pass",
            message="Embedding 仍使用 hash 开发兜底" if embedding_hash else "Embedding 服务已配置为真实模型",
            recommendation="生产环境使用 BGE-M3 本地服务或 OpenAI-compatible embedding 服务，不得使用 hash embedding。",
        )
    )

    checks.append(
        ReleaseCheck(
            key="embedding_fallback",
            severity="critical"
            if is_production and settings.EMBEDDING_ALLOW_FALLBACK
            else "warning"
            if settings.EMBEDDING_ALLOW_FALLBACK
            else "pass",
            message="Embedding 失败会降级到 hash"
            if settings.EMBEDDING_ALLOW_FALLBACK
            else "Embedding 失败不会静默降级",
            recommendation="生产环境保持 EMBEDDING_ALLOW_FALLBACK=false，失败时展示任务失败原因并允许重试。",
        )
    )

    rerank_disabled = settings.RERANK_PROVIDER.lower().strip() in {"", "none", "off"}
    checks.append(
        ReleaseCheck(
            key="rerank_provider",
            severity="warning" if rerank_disabled else "pass",
            message="未启用重精排" if rerank_disabled else "重精排已配置",
            recommendation="面试题库和简历证据召回建议接入 bge-reranker-v2-m3 或远程 rerank 服务，并保留召回评测集。",
        )
    )

    backup_missing = is_production and not settings.BACKUP_ENABLED
    checks.append(
        ReleaseCheck(
            key="backup",
            severity="critical" if backup_missing else "pass" if settings.BACKUP_ENABLED else "warning",
            message="生产环境缺少备份策略"
            if backup_missing
            else "备份策略已启用"
            if settings.BACKUP_ENABLED
            else "备份策略未启用",
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

    checks.append(
        ReleaseCheck(
            key="admin_emails",
            severity="pass" if settings.admin_email_list else "warning",
            message="管理员邮箱已配置" if settings.admin_email_list else "未配置管理员邮箱",
            recommendation="如启用受限运维 API，配置 ADMIN_EMAILS 并遵循最小权限和独立审计要求。",
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
            key="agent_shadow_runtime",
            severity="critical"
            if is_production and settings.AGENT_SHADOW_API_ENABLED
            else "warning"
            if settings.AGENT_SHADOW_API_ENABLED
            else "pass",
            message="生产环境启用了进程内 Agent Shadow API"
            if is_production and settings.AGENT_SHADOW_API_ENABLED
            else "Agent Shadow API 已启用，仅允许内部评测"
            if settings.AGENT_SHADOW_API_ENABLED
            else "Agent Shadow API 默认关闭",
            recommendation=(
                "生产环境必须保持 AGENT_SHADOW_API_ENABLED=false；PostgreSQL Run Store、租约锁与事务幂等"
                "已落地，但仍需真实 PostgreSQL、durable worker 和恢复演练后另行建设生产 Agent API。"
            ),
        )
    )

    postgres_store_mismatch = settings.AGENT_RUN_STORE_BACKEND == "postgresql" and not settings.DATABASE_URL.startswith(
        "postgresql+"
    )
    shadow_memory_outside_local = (
        settings.AGENT_SHADOW_API_ENABLED
        and settings.AGENT_RUN_STORE_BACKEND == "memory"
        and settings.APP_ENV.lower() not in {"local", "dev", "development", "test"}
    )
    checks.append(
        ReleaseCheck(
            key="agent_run_store",
            severity="critical"
            if postgres_store_mismatch or shadow_memory_outside_local
            else "warning"
            if settings.AGENT_RUN_STORE_BACKEND == "memory" and settings.AGENT_SHADOW_API_ENABLED
            else "pass",
            message="PostgreSQL Run Store 与数据库配置不匹配"
            if postgres_store_mismatch
            else "非本地 Shadow Runtime 仍使用内存 Run Store"
            if shadow_memory_outside_local
            else "本地 Shadow Runtime 使用内存 Run Store"
            if settings.AGENT_RUN_STORE_BACKEND == "memory" and settings.AGENT_SHADOW_API_ENABLED
            else "Agent Run Store 配置可接受",
            recommendation=(
                "AGENT_RUN_STORE_BACKEND=postgresql 时必须使用 postgresql+asyncpg 数据库；"
                "非本地 Shadow 评测必须使用迁移到 0018 的 PostgreSQL Run Store。"
            ),
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

    blockers = [f"{check['key']}: {check['message']}" for check in result["checks"] if check["severity"] == "critical"]
    raise RuntimeError("生产发布检查未通过：" + "；".join(blockers))
