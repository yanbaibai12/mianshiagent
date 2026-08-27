import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AsyncTask, User
from app.schemas import AsyncTaskResponse
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.task_queue import cancel_task, retry_task
from app.workers.task_worker import run_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=AsyncTaskResponse)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = await db.scalar(select(AsyncTask).where(AsyncTask.id == task_id, AsyncTask.user_id == current_user.id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("", response_model=list[AsyncTaskResponse])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AsyncTask).where(AsyncTask.user_id == current_user.id).order_by(AsyncTask.created_at.desc()).limit(50)
    )
    return result.scalars().all()


@router.post("/{task_id}/retry", response_model=AsyncTaskResponse)
async def retry_async_task(
    task_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = await db.scalar(select(AsyncTask).where(AsyncTask.id == task_id, AsyncTask.user_id == current_user.id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await retry_task(
        db,
        task,
        background_tasks=background_tasks,
        local_runner=run_task,
        rq_runner_path="app.workers.task_worker.run_task",
    )
    log_audit_event(
        db,
        event_type="task.retry",
        resource_type="async_task",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=task.organization_id,
        resource_id=str(task.id),
        request=request,
        metadata={"task_type": task.task_type, "retry_count": task.retry_count},
    )
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=AsyncTaskResponse)
async def cancel_async_task(
    task_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = await db.scalar(select(AsyncTask).where(AsyncTask.id == task_id, AsyncTask.user_id == current_user.id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await cancel_task(db, task)
    log_audit_event(
        db,
        event_type="task.cancel",
        resource_type="async_task",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=task.organization_id,
        resource_id=str(task.id),
        request=request,
        metadata={"task_type": task.task_type},
    )
    await db.commit()
    await db.refresh(task)
    return task
