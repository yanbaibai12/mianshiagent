from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings

AlertSeverity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class SystemAlert:
    key: str
    severity: AlertSeverity
    title: str
    message: str
    recommendation: str
    feature: str = "system"

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "recommendation": self.recommendation,
            "feature": self.feature,
        }


def _status_count(metrics: dict[str, Any], status: str) -> int:
    return int((metrics.get("status_counts") or {}).get(status, 0) or 0)


def _task_failure_rate(queue_metrics: dict[str, Any]) -> float:
    counts = queue_metrics.get("status_counts") or {}
    total = sum(int(value or 0) for value in counts.values())
    failed = int(counts.get("failed") or 0)
    return 0.0 if total <= 0 else failed / total


def _top_release_alerts(release: dict[str, Any]) -> list[SystemAlert]:
    alerts: list[SystemAlert] = []
    for check in release.get("checks") or []:
        severity = check.get("severity")
        if severity not in {"critical", "warning"}:
            continue
        alerts.append(
            SystemAlert(
                key=f"release.{check.get('key', 'unknown')}",
                severity="critical" if severity == "critical" else "warning",
                title="发布检查未通过" if severity == "critical" else "发布检查存在风险",
                message=str(check.get("message") or ""),
                recommendation=str(check.get("recommendation") or ""),
                feature="release",
            )
        )
    return alerts[:8]


def build_system_alerts(
    *,
    settings: Settings,
    release: dict[str, Any],
    request_metrics: dict[str, Any],
    queue_metrics: dict[str, Any],
    vector_status: dict[str, Any],
    rerank_status: dict[str, Any],
) -> dict[str, Any]:
    alerts = _top_release_alerts(release)
    runtime = queue_metrics.get("runtime") or {}
    is_production = settings.is_production

    if runtime.get("backend") == "redis_rq" and not runtime.get("available", True):
        alerts.append(
            SystemAlert(
                key="queue.redis_unavailable",
                severity="critical",
                title="Redis 队列不可用",
                message=str(runtime.get("error") or "Redis/RQ 无法连接"),
                recommendation="检查 Redis 服务、TASK_REDIS_URL、网络策略和 RQ worker 进程。",
                feature="task_queue",
            )
        )

    if (queue_metrics.get("backend_counts") or {}).get("local_fallback"):
        alerts.append(
            SystemAlert(
                key="queue.local_fallback_used",
                severity="critical" if is_production else "warning",
                title="任务发生本地 fallback",
                message="已有长任务没有进入 Redis/RQ，而是降级到本地后台任务。",
                recommendation="排查 Redis 入队失败原因，并把 TASK_ALLOW_LOCAL_FALLBACK 在生产环境关闭。",
                feature="task_queue",
            )
        )

    failure_rate = _task_failure_rate(queue_metrics)
    if failure_rate >= 0.1 or _status_count(queue_metrics, "failed") >= 3:
        alerts.append(
            SystemAlert(
                key="queue.failure_rate",
                severity="critical" if failure_rate >= 0.2 else "warning",
                title="任务失败率偏高",
                message=f"最近任务失败率约 {round(failure_rate * 100, 1)}%，失败任务 {_status_count(queue_metrics, 'failed')} 个。",
                recommendation="优先查看最近错误、request_id、LLM/embedding 失败原因，并对失败任务执行重试或修复数据。",
                feature="task_queue",
            )
        )

    if vector_status.get("enabled") and not vector_status.get("available"):
        alerts.append(
            SystemAlert(
                key="rag.vector_unavailable",
                severity="critical",
                title="知识库向量检索不可用",
                message=str(vector_status.get("last_error") or "Qdrant collection 不可用或维度不匹配"),
                recommendation="检查 QDRANT_URL、collection 维度、BGE-M3 1024 维配置，并重建知识库索引。",
                feature="rag",
            )
        )

    chunk_count = int(vector_status.get("chunk_count") or 0)
    points_count = int(vector_status.get("points_count") or 0)
    if chunk_count > 0 and points_count < chunk_count:
        alerts.append(
            SystemAlert(
                key="rag.knowledge_index_lag",
                severity="warning",
                title="知识库索引落后于 SQL 数据",
                message=f"SQL 知识切片 {chunk_count} 个，Qdrant 知识点 {points_count} 个。",
                recommendation="在系统巡检页执行“导入面试题库并同步索引”，或运行 scripts/import_interview_knowledge.py。",
                feature="rag",
            )
        )

    resume_chunk_count = int(vector_status.get("resume_chunk_count") or 0)
    resume_points_count = int(vector_status.get("resume_points_count") or 0)
    if resume_chunk_count > 0 and resume_points_count < resume_chunk_count:
        alerts.append(
            SystemAlert(
                key="rag.resume_index_lag",
                severity="warning",
                title="简历向量索引未完全回填",
                message=f"SQL 简历切片 {resume_chunk_count} 个，Qdrant 简历点 {resume_points_count} 个。",
                recommendation="在系统巡检页执行“回填简历向量索引”，确保岗位证据检索可用。",
                feature="rag",
            )
        )

    rerank_call = rerank_status.get("last_call") if isinstance(rerank_status.get("last_call"), dict) else {}
    if rerank_call.get("fallback_used"):
        alerts.append(
            SystemAlert(
                key="rag.rerank_fallback",
                severity="warning",
                title="重精排发生 fallback",
                message=str(rerank_call.get("failure_reason") or "rerank 服务失败后返回原始排序"),
                recommendation="检查 bge-reranker-v2-m3 权重、显存/内存、远程 rerank 服务和超时配置。",
                feature="rag",
            )
        )

    total_requests = int(request_metrics.get("total_requests") or 0)
    error_requests = sum(
        int(count or 0)
        for status_code, count in (request_metrics.get("status_counts") or {}).items()
        if str(status_code).startswith("5")
    )
    if total_requests >= 20 and error_requests / max(1, total_requests) >= 0.05:
        alerts.append(
            SystemAlert(
                key="api.error_rate",
                severity="critical" if error_requests / total_requests >= 0.1 else "warning",
                title="接口 5xx 比例偏高",
                message=f"当前进程记录 {error_requests}/{total_requests} 个 5xx 请求。",
                recommendation="查看结构化日志中的 request_id、error_type 和慢接口路径，并补充失败重试或降级提示。",
                feature="api",
            )
        )

    severity_rank = {"critical": 3, "warning": 2, "info": 1}
    deduped: dict[str, SystemAlert] = {}
    for alert in alerts:
        existing = deduped.get(alert.key)
        if existing is None or severity_rank[alert.severity] > severity_rank[existing.severity]:
            deduped[alert.key] = alert
    ordered = sorted(deduped.values(), key=lambda item: (-severity_rank[item.severity], item.key))
    critical = sum(1 for item in ordered if item.severity == "critical")
    warning = sum(1 for item in ordered if item.severity == "warning")
    return {
        "health": "critical" if critical else "warning" if warning else "ok",
        "critical_count": critical,
        "warning_count": warning,
        "alerts": [item.to_dict() for item in ordered[:20]],
    }
