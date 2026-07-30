import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session_maker
from app.models import AsyncTask


async def run_task_async(task_id: str) -> None:
    parsed_task_id = uuid.UUID(str(task_id))
    async with async_session_maker() as db:
        task = await db.scalar(select(AsyncTask).where(AsyncTask.id == parsed_task_id))
        if not task or task.status == "cancelled":
            return
        task_type = task.task_type

    if task_type == "resume.adapt_jd":
        from app.routers.resumes import _run_resume_adapt_jd_task

        await _run_resume_adapt_jd_task(str(parsed_task_id))
        return
    if task_type == "job.adapt_resume":
        from app.routers.jobs import _run_job_adapt_task

        await _run_job_adapt_task(str(parsed_task_id))
        return
    raise RuntimeError(f"Unsupported async task type: {task_type}")


def run_task(task_id: str) -> None:
    asyncio.run(run_task_async(task_id))
