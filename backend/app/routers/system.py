import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeDocument, ResumeChunk, User
from app.services.alerting import build_alerting_status, dispatch_system_alerts
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user, require_admin_user
from app.services.embedding_service import embedding_probe
from app.services.monitoring import build_system_alerts
from app.services.operations import build_backup_status, create_sqlite_backup, request_metrics
from app.services.release_checks import run_release_checks
from app.services.rerank_service import rerank_documents, rerank_status
from app.services.resume_index import reindex_all_resume_chunks
from app.services.task_queue import task_queue_metrics
from app.services.vector_store import vector_store_status

router = APIRouter(prefix="/api/system", tags=["system"])


class RerankProbeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    documents: list[str] = Field(min_length=2, max_length=20)


class ResumeReindexAllRequest(BaseModel):
    only_missing: bool = True
    limit: int | None = Field(default=None, ge=1, le=1000)


class AlertNotifyRequest(BaseModel):
    include_warnings: bool = False
    force: bool = False


def _rag_index_consistency(vector_status: dict[str, Any]) -> dict[str, Any]:
    chunk_count = int(vector_status.get("chunk_count") or 0)
    points_count = int(vector_status.get("points_count") or 0)
    resume_chunk_count = int(vector_status.get("resume_chunk_count") or 0)
    resume_points_count = int(vector_status.get("resume_points_count") or 0)
    configured_size = int(vector_status.get("configured_vector_size") or 0)
    actual_size = vector_status.get("actual_vector_size")
    resume_actual_size = vector_status.get("resume_actual_vector_size")
    knowledge_ratio = 1.0 if chunk_count == 0 else min(1.0, points_count / max(1, chunk_count))
    resume_ratio = 1.0 if resume_chunk_count == 0 else min(1.0, resume_points_count / max(1, resume_chunk_count))
    return {
        "knowledge_sql_chunks": chunk_count,
        "knowledge_vector_points": points_count,
        "knowledge_index_ratio": round(knowledge_ratio, 3),
        "resume_sql_chunks": resume_chunk_count,
        "resume_vector_points": resume_points_count,
        "resume_index_ratio": round(resume_ratio, 3),
        "knowledge_vector_size_ok": actual_size in {None, configured_size},
        "resume_vector_size_ok": resume_actual_size in {None, configured_size},
        "overall_ok": knowledge_ratio >= 0.95
        and resume_ratio >= 0.95
        and actual_size in {None, configured_size}
        and resume_actual_size in {None, configured_size},
    }


@router.get("/status")
async def status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = get_settings()
    database_ok = True
    database_error = None

    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        database_ok = False
        database_error = str(exc)

    document_count = 0
    chunk_count = 0
    resume_chunk_count = 0
    if database_ok:
        document_count = await db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0
        chunk_count = await db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
        resume_chunk_count = await db.scalar(select(func.count()).select_from(ResumeChunk)) or 0
    vector_status = await vector_store_status(db)
    queue_metrics = await task_queue_metrics(db)
    request_snapshot = request_metrics.snapshot()
    rerank_snapshot = rerank_status()
    release_snapshot = run_release_checks(settings)
    alerts = build_system_alerts(
        settings=settings,
        release=release_snapshot,
        request_metrics=request_snapshot,
        queue_metrics=queue_metrics,
        vector_status=vector_status,
        rerank_status=rerank_snapshot,
    )

    llm_provider = settings.LLM_PROVIDER.lower()
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "public_base_url": settings.PUBLIC_BASE_URL,
        "database": {
            "ok": database_ok,
            "driver": settings.DATABASE_URL.split("://", 1)[0],
            "error": database_error,
        },
        "llm": {
            "provider": llm_provider,
            "model": settings.LLM_MODEL,
            "profiles": settings.llm_profiles(),
            "configured": llm_provider == "local" or bool(settings.LLM_API_KEY),
            "local_fallback": llm_provider == "local" or not bool(settings.LLM_API_KEY),
            "fallback_allowed": settings.LLM_ALLOW_FALLBACK,
        },
        "rag": {
            "enabled": True,
            "retriever": settings.VECTOR_STORE_BACKEND,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "resume_chunk_count": resume_chunk_count,
            "vector_store": vector_status,
            "index_consistency": _rag_index_consistency(vector_status),
            "rerank": rerank_snapshot,
        },
        "limits": {
            "max_file_size_mb": round(settings.MAX_FILE_SIZE / 1024 / 1024, 1),
            "max_resume_text_length": settings.MAX_RESUME_TEXT_LENGTH,
            "max_jd_text_length": settings.MAX_JD_TEXT_LENGTH,
            "max_answer_length": settings.MAX_ANSWER_LENGTH,
        },
        "security": {
            "admin_enabled": bool(settings.admin_email_list),
            "cors_origins": settings.CORS_ALLOW_ORIGINS,
            "trusted_hosts": settings.TRUSTED_HOSTS,
            "docs_enabled": settings.ENABLE_DOCS,
            "auto_create_db": settings.AUTO_CREATE_DB,
            "rate_limit_window_seconds": settings.RATE_LIMIT_WINDOW_SECONDS,
            "auth_requests_per_window": settings.RATE_LIMIT_AUTH_REQUESTS,
            "api_requests_per_window": settings.RATE_LIMIT_API_REQUESTS,
        },
        "operations": {
            "metrics_enabled": settings.METRICS_ENABLED,
            "metrics": request_snapshot,
            "task_queue": queue_metrics,
            "alerting": await build_alerting_status(db, settings),
            "backup": build_backup_status(settings),
            "release": {
                "deployment_color": settings.DEPLOYMENT_COLOR,
                "release_channel": settings.RELEASE_CHANNEL,
                "canary_percent": settings.CANARY_PERCENT,
            },
        },
        "release": release_snapshot,
        "alerts": alerts,
    }


@router.get("/alerts")
async def system_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    settings = get_settings()
    vector_status = await vector_store_status(db)
    queue_metrics = await task_queue_metrics(db)
    release_snapshot = run_release_checks(settings)
    return build_system_alerts(
        settings=settings,
        release=release_snapshot,
        request_metrics=request_metrics.snapshot(),
        queue_metrics=queue_metrics,
        vector_status=vector_status,
        rerank_status=rerank_status(),
    )


@router.get("/rag/health")
async def rag_health(
    active: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vector_status = await vector_store_status(db)
    rerank_snapshot = rerank_status()
    payload: dict[str, Any] = {
        "active_probe": active,
        "vector_store": vector_status,
        "index_consistency": _rag_index_consistency(vector_status),
        "embedding": vector_status.get("embedding") or {},
        "rerank": rerank_snapshot,
        "recommendations": [],
    }
    if active:
        payload["embedding_probe"] = await asyncio.to_thread(embedding_probe)
        if rerank_snapshot.get("enabled"):
            order, observation = await asyncio.to_thread(
                rerank_documents,
                "RAG RRF Qdrant Redis Agent 面试题",
                [
                    "RAG 系统需要切片、embedding、召回、RRF 融合和重排。",
                    "普通登录接口主要关注密码校验、Token 和权限。",
                    "Redis 队列需要处理重试、幂等、进度和服务重启恢复。",
                ],
            )
            payload["rerank_probe"] = {"order": order, "observation": observation}

    if not payload["index_consistency"]["overall_ok"]:
        payload["recommendations"].append("执行 /api/system/admin/reindex-resumes 或重建 Qdrant collection，确保 SQL chunk 与向量点数一致。")
    embedding_last = payload.get("embedding_probe") or (payload.get("embedding") or {}).get("last_call") or {}
    if embedding_last.get("fallback_used"):
        payload["recommendations"].append("Embedding 发生 fallback，生产环境应检查 BGE-M3 服务和 1024 维向量配置。")
    rerank_last = (payload.get("rerank_probe") or {}).get("observation") or (rerank_snapshot.get("last_call") or {})
    if rerank_last.get("fallback_used"):
        payload["recommendations"].append("Reranker 发生 fallback，检查 bge-reranker-v2-m3 权重、远程服务或超时配置。")
    payload["health"] = "ok" if payload["index_consistency"]["overall_ok"] and not payload["recommendations"] else "warning"
    return payload


@router.post("/admin/alerts/notify")
async def admin_notify_alerts(
    req: AlertNotifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    settings = get_settings()
    vector_status = await vector_store_status(db)
    queue_metrics = await task_queue_metrics(db)
    release_snapshot = run_release_checks(settings)
    alerts = build_system_alerts(
        settings=settings,
        release=release_snapshot,
        request_metrics=request_metrics.snapshot(),
        queue_metrics=queue_metrics,
        vector_status=vector_status,
        rerank_status=rerank_status(),
    )
    result = await dispatch_system_alerts(
        db,
        settings=settings,
        alerts=alerts,
        min_severity="warning" if req.include_warnings else None,
        force=req.force,
    )
    log_audit_event(
        db,
        event_type="system.alert_notify",
        resource_type="system_alert",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        request=request,
        metadata={
            "eligible_count": result.get("eligible_count"),
            "sent_count": result.get("sent_count"),
            "failed_count": result.get("failed_count"),
            "skipped_count": result.get("skipped_count"),
            "configured": result.get("configured"),
        },
    )
    await db.commit()
    return result


@router.get("/release-checks")
async def release_checks(current_user: User = Depends(get_current_user)):
    settings = get_settings()
    return run_release_checks(settings)


@router.post("/rerank/probe")
async def rerank_probe(
    req: RerankProbeRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    order, observation = await asyncio.to_thread(rerank_documents, req.query, req.documents)
    return {
        "order": order,
        "observation": observation,
        "status": rerank_status(),
    }


@router.get("/admin/metrics")
async def admin_metrics(current_user: User = Depends(require_admin_user)):
    return request_metrics.snapshot()


@router.post("/admin/backup")
async def admin_backup(current_user: User = Depends(require_admin_user)):
    settings = get_settings()
    return create_sqlite_backup(settings)


@router.post("/admin/reindex-resumes")
async def admin_reindex_resumes(
    req: ResumeReindexAllRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    result = await reindex_all_resume_chunks(
        db,
        only_missing=req.only_missing,
        limit=req.limit,
    )
    log_audit_event(
        db,
        event_type="system.reindex_resumes",
        resource_type="resume_index",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=None,
        request=request,
        metadata={
            "only_missing": req.only_missing,
            "limit": req.limit,
            "processed_count": result.get("processed_count"),
            "chunk_count": result.get("chunk_count"),
            "indexed_count": result.get("indexed_count"),
            "failed_count": result.get("failed_count"),
        },
    )
    await db.commit()
    return result
