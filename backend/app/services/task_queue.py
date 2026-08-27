from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AsyncTask
from app.utils.time import utc_now

TERMINAL_STATUSES = {"success", "failed", "cancelled"}
RUNNABLE_STATUSES = {"queued", "retrying"}


class TaskCancelled(RuntimeError):
    pass


async def create_task(
    db: AsyncSession,
    *,
    user_id: Any,
    organization_id: Any = None,
    task_type: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> AsyncTask:
    settings = get_settings()
    task = AsyncTask(
        user_id=user_id,
        organization_id=organization_id,
        task_type=task_type,
        status="queued",
        progress=0,
        stage="已排队",
        queue_backend=settings.TASK_QUEUE_BACKEND,
        queue_name=settings.TASK_QUEUE_NAME if settings.TASK_QUEUE_BACKEND != "local" else "local",
        enqueued_at=utc_now(),
        resource_type=resource_type,
        resource_id=resource_id,
        input_payload=input_payload or {},
        result_payload={},
        max_retries=settings.TASK_MAX_RETRIES,
    )
    db.add(task)
    await db.flush()
    return task


async def update_task(
    db: AsyncSession,
    task: AsyncTask,
    *,
    status: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    result_payload: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> AsyncTask:
    if task.cancel_requested and status not in {None, "cancelled"}:
        task.status = "cancelled"
        task.progress = max(task.progress or 0, progress or 0)
        task.stage = "任务已取消"
        task.ended_at = utc_now()
        task.updated_at = utc_now()
        await db.flush()
        raise TaskCancelled("任务已取消")

    if status is not None:
        task.status = status
        if status == "running" and task.started_at is None:
            task.started_at = utc_now()
        if status in {"running", "retrying"}:
            task.last_heartbeat_at = utc_now()
        if status in TERMINAL_STATUSES:
            task.ended_at = utc_now()
    if progress is not None:
        task.progress = max(0, min(100, int(progress)))
    if stage is not None:
        task.stage = stage[:200]
    if result_payload is not None:
        task.result_payload = result_payload
    if error_type is not None:
        task.error_type = error_type[:120]
    if error_message is not None:
        task.error_message = error_message[:4000]
    task.updated_at = utc_now()
    await db.flush()
    return task


def normalize_queue_backend(value: str | None = None) -> str:
    backend = (value or get_settings().TASK_QUEUE_BACKEND or "local").lower().strip()
    if backend in {"redis", "rq", "redis-rq", "redis_rq"}:
        return "redis_rq"
    return "local"


def task_queue_runtime_status() -> dict[str, Any]:
    settings = get_settings()
    backend = normalize_queue_backend()
    payload: dict[str, Any] = {
        "backend": backend,
        "queue_name": settings.TASK_QUEUE_NAME if backend == "redis_rq" else "local",
        "redis_configured": bool(settings.TASK_REDIS_URL),
        "local_fallback_allowed": settings.TASK_ALLOW_LOCAL_FALLBACK,
        "available": True,
    }
    if backend != "redis_rq":
        return payload
    try:
        import redis

        client = redis.Redis.from_url(settings.TASK_REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        payload["available"] = True
    except Exception as exc:
        payload["available"] = False
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


async def enqueue_task(
    db: AsyncSession,
    task: AsyncTask,
    *,
    background_tasks: BackgroundTasks | None,
    local_runner: Callable[[str], Any],
    rq_runner_path: str,
) -> AsyncTask:
    settings = get_settings()
    backend = normalize_queue_backend()
    task.enqueued_at = utc_now()
    task.queue_backend = backend
    task.queue_name = settings.TASK_QUEUE_NAME if backend == "redis_rq" else "local"
    task.external_job_id = None
    task.cancel_requested = False

    if backend == "redis_rq":
        try:
            import redis
            from rq import Queue

            connection = redis.Redis.from_url(settings.TASK_REDIS_URL)
            queue = Queue(settings.TASK_QUEUE_NAME, connection=connection)
            job = queue.enqueue(
                rq_runner_path,
                str(task.id),
                job_timeout=settings.TASK_JOB_TIMEOUT_SECONDS,
                result_ttl=settings.TASK_RESULT_TTL_SECONDS,
                failure_ttl=settings.TASK_FAILURE_TTL_SECONDS,
            )
            task.external_job_id = job.id
            await db.flush()
            return task
        except Exception as exc:
            if not settings.TASK_ALLOW_LOCAL_FALLBACK:
                task.status = "failed"
                task.error_type = type(exc).__name__
                task.error_message = f"Redis/RQ 入队失败：{exc}"
                task.stage = "任务入队失败"
                task.ended_at = utc_now()
                await db.flush()
                await db.commit()
                raise HTTPException(status_code=503, detail="Redis/RQ 入队失败，请检查 Redis 和 worker") from exc
            task.queue_backend = "local_fallback"
            task.queue_name = "local"
            task.error_type = type(exc).__name__
            task.error_message = f"Redis/RQ 不可用，已使用本地 fallback：{exc}"

    if background_tasks is None:
        task.status = "failed"
        task.stage = "本地 fallback 缺少 BackgroundTasks"
        task.error_type = "TaskQueueConfigurationError"
        task.error_message = "当前请求上下文不能启动本地后台任务"
        task.ended_at = utc_now()
        await db.flush()
        await db.commit()
        raise HTTPException(status_code=503, detail="任务队列不可用")

    background_tasks.add_task(local_runner, str(task.id))
    await db.flush()
    return task


async def retry_task(
    db: AsyncSession,
    task: AsyncTask,
    *,
    background_tasks: BackgroundTasks | None,
    local_runner: Callable[[str], Any],
    rq_runner_path: str,
) -> AsyncTask:
    if task.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="只有失败或已取消任务可以重试")
    if task.retry_count >= task.max_retries:
        raise HTTPException(status_code=400, detail="任务重试次数已用完")
    task.retry_count += 1
    task.status = "retrying"
    task.progress = 0
    task.stage = "正在重新排队"
    task.error_type = None
    task.error_message = None
    task.result_payload = {}
    task.started_at = None
    task.ended_at = None
    task.updated_at = utc_now()
    await db.flush()
    return await enqueue_task(
        db,
        task,
        background_tasks=background_tasks,
        local_runner=local_runner,
        rq_runner_path=rq_runner_path,
    )


async def cancel_task(db: AsyncSession, task: AsyncTask) -> AsyncTask:
    if task.status in TERMINAL_STATUSES:
        return task
    task.cancel_requested = True
    task.status = "cancelled"
    task.stage = "任务已取消"
    task.ended_at = utc_now()
    task.updated_at = utc_now()
    await db.flush()
    return task


async def task_queue_metrics(db: AsyncSession) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(AsyncTask.status, func.count())
            .group_by(AsyncTask.status)
        )
    ).all()
    backend_rows = (
        await db.execute(
            select(AsyncTask.queue_backend, func.count())
            .group_by(AsyncTask.queue_backend)
        )
    ).all()
    recent_errors = (
        await db.execute(
            select(AsyncTask)
            .where(AsyncTask.status == "failed")
            .order_by(AsyncTask.updated_at.desc())
            .limit(10)
        )
    ).scalars().all()
    sampled_tasks = (
        await db.execute(
            select(AsyncTask)
            .where(AsyncTask.created_at.is_not(None))
            .order_by(AsyncTask.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    queue_waits = [
        (task.started_at - (task.enqueued_at or task.created_at)).total_seconds() * 1000
        for task in sampled_tasks
        if task.started_at and (task.enqueued_at or task.created_at)
    ]
    executions = [
        (task.ended_at - task.started_at).total_seconds() * 1000
        for task in sampled_tasks
        if task.started_at and task.ended_at
    ]
    return {
        "runtime": task_queue_runtime_status(),
        "status_counts": {status or "unknown": count for status, count in status_rows},
        "backend_counts": {backend or "unknown": count for backend, count in backend_rows},
        "avg_queue_wait_ms": round(sum(queue_waits) / len(queue_waits), 2) if queue_waits else 0,
        "avg_execution_ms": round(sum(executions) / len(executions), 2) if executions else 0,
        "recent_errors": [
            {
                "id": str(task.id),
                "task_type": task.task_type,
                "resource_type": task.resource_type,
                "resource_id": task.resource_id,
                "error_type": task.error_type,
                "error_message": (task.error_message or "")[:300],
                "updated_at": task.updated_at,
            }
            for task in recent_errors
        ],
    }
