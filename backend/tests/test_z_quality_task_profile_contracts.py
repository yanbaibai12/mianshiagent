from __future__ import annotations

import os
import sys
import tempfile
import types
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

if "app.main" not in sys.modules:
    _DB_PATH = Path(tempfile.gettempdir()) / f"quality_task_contract_{uuid.uuid4().hex}.db"
    _DB_PATH.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
    os.environ["SECRET_KEY"] = "quality-task-contract-secret-key-long-enough"
    os.environ["DEBUG"] = "false"
    os.environ["APP_ENV"] = "local"
    os.environ["AUTO_CREATE_DB"] = "true"
    os.environ["LLM_PROVIDER"] = "local"
    os.environ["LLM_ALLOW_FALLBACK"] = "false"
    os.environ["VECTOR_STORE_BACKEND"] = "keyword"
    os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
    os.environ["EMBEDDING_PROVIDER"] = "hash"
    os.environ["RERANK_PROVIDER"] = "none"

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def register_user(client: TestClient):
    from app.database import async_session_maker
    from app.models import OrganizationMember, User

    email = f"contracts-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "nickname": "Contract User"},
    )
    assert response.status_code == 200, response.text

    async def load():
        async with async_session_maker() as db:
            user = await db.scalar(select(User).where(User.email == email))
            membership = await db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
            return user.id, membership.organization_id

    return email, async_session_maker, load


def test_data_sanitizers_bound_and_redact_untrusted_values():
    from app.services import data_sanitization

    long_label = "x" * 50
    labels = data_sanitization.clean_labels(
        ["  Alpha  ", "alpha", "", "Beta,", long_label] + [str(i) for i in range(20)]
    )
    assert labels[:3] == ["Alpha", "Beta", "x" * 40]
    assert len(labels) == 12
    assert data_sanitization.clean_labels(None) == []

    redacted = data_sanitization.redact_sensitive_text("a@example.com 13800138000 sk-abcdefghijklmnop")
    assert redacted == "[email_redacted] [phone_redacted] [key_redacted]"
    assert data_sanitization.redact_sensitive_text(None) == ""
    metadata = data_sanitization.safe_metadata(
        {
            "email": "secret@example.com",
            "note": "call 13800138000",
            "count": 2,
            "items": ["a@example.com", 3],
            "nested": {"ignored": True},
            "": "ignored",
        }
    )
    assert "email" not in metadata and "nested" not in metadata
    assert metadata["note"] == "call [phone_redacted]"
    assert metadata["items"][0] == "[email_redacted]"
    assert data_sanitization.safe_metadata(None) == {}


@pytest.mark.asyncio
async def test_task_queue_lifecycle_backends_and_metrics(client: TestClient, monkeypatch):
    from app.database import async_session_maker
    from app.models import AsyncTask, User
    from app.services import task_queue
    from app.utils.time import utc_now

    email = f"queue-{uuid.uuid4().hex}@example.com"
    assert (
        client.post(
            "/api/auth/register", json={"email": email, "password": "password123", "nickname": "Queue"}
        ).status_code
        == 200
    )
    local_settings = SimpleNamespace(
        TASK_QUEUE_BACKEND="local",
        TASK_QUEUE_NAME="contracts",
        TASK_REDIS_URL="",
        TASK_ALLOW_LOCAL_FALLBACK=True,
        TASK_MAX_RETRIES=2,
        TASK_JOB_TIMEOUT_SECONDS=30,
        TASK_RESULT_TTL_SECONDS=60,
        TASK_FAILURE_TTL_SECONDS=120,
    )
    monkeypatch.setattr(task_queue, "get_settings", lambda: local_settings)
    assert task_queue.normalize_queue_backend("rq") == "redis_rq"
    assert task_queue.normalize_queue_backend("unknown") == "local"
    assert task_queue.task_queue_runtime_status()["backend"] == "local"

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        task = await task_queue.create_task(
            db,
            user_id=user.id,
            task_type="resume.rewrite",
            resource_type="resume",
            resource_id="r1",
            input_payload={"x": 1},
        )
        assert task.status == "queued" and task.max_retries == 2
        await task_queue.update_task(
            db,
            task,
            status="running",
            progress=150,
            stage="x" * 250,
            result_payload={"ok": True},
            error_type="E" * 140,
            error_message="m" * 4100,
        )
        assert task.progress == 100 and len(task.stage) == 200
        assert task.started_at and task.last_heartbeat_at
        await task_queue.update_task(db, task, status="success", progress=-5)
        assert task.progress == 0 and task.ended_at

        terminal = await task_queue.cancel_task(db, task)
        assert terminal.status == "success"
        active = await task_queue.create_task(db, user_id=user.id, task_type="active")
        await task_queue.cancel_task(db, active)
        assert active.cancel_requested and active.status == "cancelled"
        active.cancel_requested = True
        with pytest.raises(task_queue.TaskCancelled):
            await task_queue.update_task(db, active, status="running", progress=25)
        assert active.status == "cancelled"

        local_task = await task_queue.create_task(db, user_id=user.id, task_type="local")
        background = BackgroundTasks()
        runner = MagicMock()
        await task_queue.enqueue_task(
            db,
            local_task,
            background_tasks=background,
            local_runner=runner,
            rq_runner_path="worker.run",
        )
        assert local_task.queue_backend == "local" and len(background.tasks) == 1

        missing_context = await task_queue.create_task(db, user_id=user.id, task_type="missing-context")
        with pytest.raises(HTTPException) as exc:
            await task_queue.enqueue_task(
                db,
                missing_context,
                background_tasks=None,
                local_runner=runner,
                rq_runner_path="worker.run",
            )
        assert exc.value.status_code == 503 and missing_context.status == "failed"

        with pytest.raises(HTTPException):
            await task_queue.retry_task(
                db,
                task,
                background_tasks=background,
                local_runner=runner,
                rq_runner_path="worker.run",
            )
        exhausted = await task_queue.create_task(db, user_id=user.id, task_type="exhausted")
        exhausted.status = "failed"
        exhausted.retry_count = exhausted.max_retries
        with pytest.raises(HTTPException):
            await task_queue.retry_task(
                db,
                exhausted,
                background_tasks=background,
                local_runner=runner,
                rq_runner_path="worker.run",
            )
        retryable = await task_queue.create_task(db, user_id=user.id, task_type="retryable")
        retryable.status = "failed"
        await task_queue.retry_task(
            db,
            retryable,
            background_tasks=background,
            local_runner=runner,
            rq_runner_path="worker.run",
        )
        assert retryable.status == "retrying" and retryable.retry_count == 1

        redis_settings = SimpleNamespace(**vars(local_settings))
        redis_settings.TASK_QUEUE_BACKEND = "redis"
        redis_settings.TASK_REDIS_URL = "redis://example"
        monkeypatch.setattr(task_queue, "get_settings", lambda: redis_settings)

        fake_client = SimpleNamespace(ping=lambda: True)
        redis_module = types.SimpleNamespace(Redis=SimpleNamespace(from_url=lambda *args, **kwargs: fake_client))

        class FakeQueue:
            def __init__(self, name, connection):
                self.name = name
                self.connection = connection

            def enqueue(self, *args, **kwargs):
                return SimpleNamespace(id="rq-job-1")

        monkeypatch.setitem(sys.modules, "redis", redis_module)
        monkeypatch.setitem(sys.modules, "rq", types.SimpleNamespace(Queue=FakeQueue))
        assert task_queue.task_queue_runtime_status()["available"] is True
        redis_task = await task_queue.create_task(db, user_id=user.id, task_type="redis")
        await task_queue.enqueue_task(
            db,
            redis_task,
            background_tasks=None,
            local_runner=runner,
            rq_runner_path="worker.run",
        )
        assert redis_task.external_job_id == "rq-job-1"

        def broken_from_url(*args, **kwargs):
            raise ConnectionError("offline")

        monkeypatch.setitem(
            sys.modules,
            "redis",
            types.SimpleNamespace(Redis=SimpleNamespace(from_url=broken_from_url)),
        )
        status = task_queue.task_queue_runtime_status()
        assert status["available"] is False and "ConnectionError" in status["error"]
        fallback_task = await task_queue.create_task(db, user_id=user.id, task_type="fallback")
        await task_queue.enqueue_task(
            db,
            fallback_task,
            background_tasks=background,
            local_runner=runner,
            rq_runner_path="worker.run",
        )
        assert fallback_task.queue_backend == "local_fallback"

        redis_settings.TASK_ALLOW_LOCAL_FALLBACK = False
        failed_task = await task_queue.create_task(db, user_id=user.id, task_type="redis-fail")
        with pytest.raises(HTTPException) as exc:
            await task_queue.enqueue_task(
                db,
                failed_task,
                background_tasks=background,
                local_runner=runner,
                rq_runner_path="worker.run",
            )
        assert exc.value.status_code == 503 and failed_task.status == "failed"

        metrics_task = AsyncTask(
            user_id=user.id,
            task_type="metrics",
            status="failed",
            progress=50,
            stage="failed",
            queue_backend="local",
            queue_name="local",
            error_type="RuntimeError",
            error_message="boom",
            enqueued_at=utc_now() - timedelta(seconds=3),
            started_at=utc_now() - timedelta(seconds=2),
            ended_at=utc_now() - timedelta(seconds=1),
        )
        db.add(metrics_task)
        await db.commit()
        redis_settings.TASK_QUEUE_BACKEND = "local"
        metrics = await task_queue.task_queue_metrics(db)
        assert metrics["status_counts"]["failed"] >= 1
        assert metrics["avg_queue_wait_ms"] > 0 and metrics["avg_execution_ms"] > 0
        assert any(item["error_type"] for item in metrics["recent_errors"])


@pytest.mark.asyncio
async def test_training_profile_detection_signals_and_focus(client: TestClient, monkeypatch):
    from app.database import async_session_maker
    from app.models import User
    from app.services import training_profile

    assert training_profile.clamp_mastery(-1) == 0
    assert training_profile.clamp_mastery(150) == 100
    assert training_profile.detect_training_dimensions("RAG embedding and tool calling") == ["rag", "tool_calling"]
    assert training_profile.detect_training_dimensions("LLM platform") == ["engineering"]
    assert training_profile.detect_training_dimensions("unrelated") == []

    email = f"profile-{uuid.uuid4().hex}@example.com"
    assert (
        client.post(
            "/api/auth/register", json={"email": email, "password": "password123", "nickname": "Profile"}
        ).status_code
        == 200
    )
    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        engineering = await training_profile.get_or_create_profile_dimension(
            db, user_id=user.id, dimension_key="invalid"
        )
        assert engineering.dimension_key == "engineering"
        again = await training_profile.get_or_create_profile_dimension(db, user_id=user.id, dimension_key="engineering")
        assert again.id == engineering.id
        dimensions = await training_profile.ensure_training_profile(db, user_id=user.id)
        assert len(dimensions) == len(training_profile.TRAINING_DIMENSIONS)

        known = await training_profile.apply_training_signal(
            db, user_id=user.id, dimension_keys=["rag", "rag", "invalid"], signal="known", source="quiz"
        )
        assert known[0].known_count == 1 and known[0].mastery_score == 68
        low = await training_profile.apply_training_signal(
            db, user_id=user.id, dimension_keys=["rag"], signal="low_score", source="interview"
        )
        assert low[0].low_score_count == 1 and low[0].weak_count == 1
        weak = await training_profile.apply_training_signal(
            db, user_id=user.id, dimension_keys=None, signal="review", source="practice"
        )
        assert weak[0].dimension_key == "engineering" and weak[0].weak_count == 1
        ordered = training_profile.weakest_dimensions(dimensions, limit=2)
        assert len(ordered) == 2
        context, items = await training_profile.training_focus_context(db, user_id=user.id, limit=3)
        assert context and items and "dimension_key" in items[0]

        high = [
            SimpleNamespace(
                mastery_score=90,
                weak_count=0,
                dimension_key="rag",
                dimension_label="RAG",
            )
        ]

        async def high_profile(*args, **kwargs):
            return high

        monkeypatch.setattr(training_profile, "ensure_training_profile", high_profile)
        assert await training_profile.training_focus_context(db, user_id=user.id) == ("", [])
