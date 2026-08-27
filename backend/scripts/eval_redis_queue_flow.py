import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_PATH = Path(tempfile.gettempdir()) / f"mianshiagent_redis_queue_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "redis-queue-eval-secret-key-that-is-long-enough"
os.environ["DEBUG"] = "false"
os.environ["APP_ENV"] = "local"
os.environ["AUTO_CREATE_DB"] = "true"
os.environ["LLM_PROVIDER"] = "local"
os.environ["LLM_ALLOW_FALLBACK"] = "false"
os.environ["VECTOR_STORE_BACKEND"] = "keyword"
os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["RERANK_PROVIDER"] = "none"
os.environ["TASK_QUEUE_BACKEND"] = "redis_rq"
os.environ["TASK_ALLOW_LOCAL_FALLBACK"] = "false"
os.environ.setdefault("TASK_REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("TASK_QUEUE_NAME", f"mianshiagent_eval_{uuid.uuid4().hex[:8]}")

from redis import Redis  # noqa: E402
from rq import Queue, SimpleWorker  # noqa: E402
from rq.timeouts import TimerDeathPenalty  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import async_session_maker, init_db  # noqa: E402
from app.models import AsyncTask, Resume, ResumeVersion, User  # noqa: E402
from app.services.task_queue import create_task, enqueue_task  # noqa: E402
from app.utils.security import get_password_hash  # noqa: E402
from app.workers.task_worker import run_task  # noqa: E402

SAMPLE_RESUME = {
    "personal": {"name": "Redis Eval", "job_intent": "AI Agent 应用开发"},
    "skills": ["Python", "FastAPI", "Redis", "RAG", "Qdrant", "Agent"],
    "projects": [
        {
            "name": "面试简历 Agent",
            "role": "后端开发",
            "description": "负责 FastAPI 接口、Redis 任务队列、RAG 检索、简历版本和报告导出。",
            "tech_stack": ["Python", "FastAPI", "Redis", "Qdrant", "RAG"],
        }
    ],
    "experience": [
        {
            "company": "示例科技",
            "role": "后端实习生",
            "highlights": ["参与接口联调、日志排查和 SQL 优化。"],
        }
    ],
}


async def create_and_enqueue() -> str:
    await init_db()
    async with async_session_maker() as db:
        user = User(
            email=f"redis-eval-{uuid.uuid4().hex}@example.com",
            password_hash=get_password_hash("password123"),
            nickname="Redis Eval",
        )
        db.add(user)
        await db.flush()
        resume = Resume(
            user_id=user.id,
            title="Redis 队列验收简历",
            original_text=json.dumps(SAMPLE_RESUME, ensure_ascii=False),
            parsed_data=SAMPLE_RESUME,
        )
        db.add(resume)
        await db.flush()
        task = await create_task(
            db,
            user_id=user.id,
            task_type="resume.adapt_jd",
            resource_type="resume",
            resource_id=str(resume.id),
            input_payload={
                "resume_id": str(resume.id),
                "jd_text": "岗位要求：熟悉 Python、FastAPI、Redis、RAG、Agent，有接口联调、优化和结果交付经验。",
            },
        )
        await db.commit()
        await db.refresh(task)
        await enqueue_task(
            db,
            task,
            background_tasks=None,
            local_runner=run_task,
            rq_runner_path="app.workers.task_worker.run_task",
        )
        await db.commit()
        return str(task.id)


async def load_result(task_id: str) -> dict:
    async with async_session_maker() as db:
        task = await db.scalar(select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id)))
        version_count = await db.scalar(
            select(func.count()).select_from(ResumeVersion).where(ResumeVersion.source_task_id == uuid.UUID(task_id))
        )
        return {
            "task_id": task_id,
            "status": task.status if task else "missing",
            "progress": task.progress if task else 0,
            "stage": task.stage if task else "",
            "queue_backend": task.queue_backend if task else "",
            "external_job_id": task.external_job_id if task else "",
            "error_type": task.error_type if task else None,
            "error_message": task.error_message if task else None,
            "version_count": int(version_count or 0),
        }


def main() -> int:
    try:
        connection = Redis.from_url(os.environ["TASK_REDIS_URL"])
        connection.ping()
        queue = Queue(os.environ["TASK_QUEUE_NAME"], connection=connection)
        queue.empty()
        task_id = asyncio.run(create_and_enqueue())
        worker = SimpleWorker([queue], connection=connection)
        worker.death_penalty_class = TimerDeathPenalty
        worker.work(burst=True)
        result = asyncio.run(load_result(task_id))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "success" and result["version_count"] >= 1 else 1
    finally:
        _DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
