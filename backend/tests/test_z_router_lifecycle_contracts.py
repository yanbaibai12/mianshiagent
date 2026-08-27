from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

if "app.main" not in sys.modules:
    _DB_PATH = Path(tempfile.gettempdir()) / f"router_contract_{uuid.uuid4().hex}.db"
    _DB_PATH.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
    os.environ["SECRET_KEY"] = "router-contract-secret-key-long-enough-123"
    os.environ["DEBUG"] = "false"
    os.environ["APP_ENV"] = "local"
    os.environ["AUTO_CREATE_DB"] = "true"
    os.environ["LLM_PROVIDER"] = "local"
    os.environ["LLM_ALLOW_FALLBACK"] = "false"
    os.environ["VECTOR_STORE_BACKEND"] = "keyword"
    os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
    os.environ["EMBEDDING_PROVIDER"] = "hash"
    os.environ["RERANK_PROVIDER"] = "none"
    os.environ["RATE_LIMIT_AUTH_REQUESTS"] = "1000"
    os.environ["RATE_LIMIT_API_REQUESTS"] = "5000"

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_RESUME = """Name: Test Candidate
Email: candidate@example.com
Phone: 13800138000
Target: Backend Engineer

Skills
Python, FastAPI, PostgreSQL, Redis, Docker, React

Projects
Enterprise Interview Agent Platform, Backend Lead, 2025.01-2026.06
Designed FastAPI endpoints, JWT authentication, resume parsing, RAG retrieval and mock interviews.
Built observable asynchronous task flows with Qdrant, Redis and PostgreSQL.
"""
JD_TEXT = "Hiring a Python backend engineer with FastAPI, PostgreSQL, Redis, Docker, RAG and API design experience."


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth_headers(client: TestClient, *, email: str | None = None) -> dict[str, str]:
    email = email or f"router-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "nickname": "Router Contract"},
    )
    assert response.status_code in {200, 400}, response.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def upload_resume(client: TestClient, headers: dict[str, str], title: str = "Lifecycle Resume") -> dict:
    response = client.post(
        "/api/resumes/upload",
        headers=headers,
        json={"title": title, "text": SAMPLE_RESUME},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_resume_and_job_full_crud_lifecycle(client: TestClient):
    headers = auth_headers(client)
    other_headers = auth_headers(client)
    resume = upload_resume(client, headers)
    resume_id = resume["id"]

    listed = client.get("/api/resumes", headers=headers)
    assert listed.status_code == 200 and any(item["id"] == resume_id for item in listed.json())
    assert client.get(f"/api/resumes/{resume_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/resumes/{uuid.uuid4()}/chunks", headers=headers).status_code == 404

    reindexed = client.post(f"/api/resumes/{resume_id}/reindex", headers=headers)
    assert reindexed.status_code == 200 and reindexed.json()["chunk_count"] >= 1

    parsed_data = dict(resume["parsed_data"])
    parsed_data["skills"] = ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "Qdrant"]
    updated = client.put(
        f"/api/resumes/{resume_id}",
        headers=headers,
        json={"title": "Enterprise Agent Resume", "parsed_data": parsed_data},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Enterprise Agent Resume"
    assert client.put(f"/api/resumes/{resume_id}", headers=headers, json={"title": "   "}).status_code == 400

    optimized_data = {
        "basic_info": {"name": "Test Candidate"},
        "summary": "Enterprise agent platform engineering experience",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "change_details": [{"field": "summary", "reason": "evidence based wording"}],
        "ats_report": {"total_score": 88},
    }
    optimized = client.put(f"/api/resumes/{resume_id}", headers=headers, json={"optimized_data": optimized_data})
    assert optimized.status_code == 200, optimized.text

    versions = client.get(f"/api/resumes/{resume_id}/versions", headers=headers)
    assert versions.status_code == 200 and len(versions.json()) >= 3
    delivery = client.post(f"/api/resumes/{resume_id}/versions/delivery", headers=headers)
    assert delivery.status_code == 200, delivery.text
    delivery_id = delivery.json()["id"]
    compared = client.get(f"/api/resumes/{resume_id}/versions/{delivery_id}/compare", headers=headers)
    assert compared.status_code == 200, compared.text
    assert {"base_version", "target_version", "score_delta"}.issubset(compared.json())
    rolled_back = client.post(
        f"/api/resumes/{resume_id}/versions/{versions.json()[-1]['id']}/rollback", headers=headers
    )
    assert rolled_back.status_code == 200, rolled_back.text

    original_export = client.get(f"/api/resumes/{resume_id}/export", headers=headers, params={"variant": "original"})
    assert original_export.status_code == 200
    assert original_export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert client.post(f"/api/resumes/{resume_id}/save-optimized", headers=headers).status_code == 200

    job = client.post(
        "/api/jobs",
        headers=headers,
        json={"title": "Python Backend Engineer", "company": "Example Tech", "jd_text": JD_TEXT, "resume_id": resume_id},
    )
    assert job.status_code == 200, job.text
    job_id = job.json()["id"]
    assert client.get("/api/jobs", headers=headers).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=other_headers).status_code == 404

    updated_job = client.put(
        f"/api/jobs/{job_id}",
        headers=headers,
        json={"title": "Senior Python Backend Engineer", "company": "Example R&D", "status": "matching"},
    )
    assert updated_job.status_code == 200, updated_job.text
    assert updated_job.json()["status"] == "matching"
    preflight = client.post(f"/api/jobs/{job_id}/preflight", headers=headers)
    assert preflight.status_code == 200, preflight.text
    assert "application_review" in preflight.json()["ats_report"]

    exported = client.get(f"/api/jobs/{job_id}/resume/export", headers=headers)
    assert exported.status_code == 200, exported.text
    interview = client.post(f"/api/jobs/{job_id}/interview", headers=headers)
    assert interview.status_code == 200, interview.text

    assert client.delete(f"/api/jobs/{job_id}", headers=other_headers).status_code == 404
    deleted_job = client.delete(f"/api/jobs/{job_id}", headers=headers)
    assert deleted_job.status_code == 200
    deleted_resume = client.delete(f"/api/resumes/{resume_id}", headers=headers)
    assert deleted_resume.status_code == 200
    assert client.get(f"/api/resumes/{resume_id}", headers=headers).status_code == 404


def test_community_experience_visibility_update_like_and_delete(client: TestClient):
    owner = auth_headers(client)
    viewer = auth_headers(client)
    payload = {
        "company": "Agent Tech",
        "position": "Backend Engineer",
        "city": "Shanghai",
        "rounds": "technical one, technical two, HR",
        "difficulty": "hard",
        "result": "offer",
        "tags": ["Python", "RAG", "Python"],
        "questions": ["How do you evaluate RAG?", "How do you make tasks idempotent?"],
        "process": "Two technical rounds focused on system design.",
        "content": "The interview covered FastAPI, PostgreSQL, RAG evaluation, idempotency and observability.",
        "visibility": "public",
        "is_anonymous": False,
        "allow_profile_usage": True,
    }
    created = client.post("/api/community/experiences", headers=owner, json=payload)
    assert created.status_code == 200, created.text
    experience_id = created.json()["id"]

    listed = client.get(
        "/api/community/experiences",
        headers=viewer,
        params={"q": "RAG", "company": "Agent", "tag": "Python", "difficulty": "hard", "result": "offer"},
    )
    assert listed.status_code == 200 and listed.json()["total"] >= 1
    detail = client.get(f"/api/community/experiences/{experience_id}", headers=viewer)
    assert detail.status_code == 200 and detail.json()["company"] == "Agent Tech"

    liked = client.post(f"/api/community/experiences/{experience_id}/like", headers=viewer)
    assert liked.status_code == 200 and liked.json()["like_count"] >= 1
    unauthorized_update = client.put(
        f"/api/community/experiences/{experience_id}",
        headers=viewer,
        json={"content": "A viewer must not be able to update this experience share."},
    )
    assert unauthorized_update.status_code == 404

    update_payload = {
        "company": "Agent Platform Tech",
        "position": "Agent Backend Engineer",
        "city": "Beijing",
        "rounds": "technical, cross-functional, HR",
        "difficulty": "medium",
        "result": "passed",
        "tags": ["FastAPI", "MCP"],
        "questions": ["How should an MCP tool allowlist work?"],
        "process": "A cross-functional round covered tool security policy.",
        "content": "The updated experience covers MCP allowlists, audit tracing and multi-agent handoffs.",
        "visibility": "private",
        "is_anonymous": True,
        "allow_profile_usage": False,
    }
    updated = client.put(f"/api/community/experiences/{experience_id}", headers=owner, json=update_payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["visibility"] == "private"
    assert client.get(f"/api/community/experiences/{experience_id}", headers=viewer).status_code == 404
    assert client.get(f"/api/community/experiences/{experience_id}", headers=owner).status_code == 200

    bank = client.get("/api/community/agent-questions", headers=owner, params={"limit": 3})
    assert bank.status_code == 200 and bank.json()["items"]
    question_id = bank.json()["items"][0]["id"]
    practiced = client.put(
        f"/api/community/agent-questions/{question_id}/practice",
        headers=owner,
        json={"mastery_status": "known", "is_favorite": True, "is_wrong": False},
    )
    assert practiced.status_code == 200, practiced.text
    for practice_filter in ("favorite", "wrong", "due", "unseen"):
        response = client.get(
            "/api/community/agent-questions",
            headers=owner,
            params={"practice_filter": practice_filter, "limit": 2},
        )
        assert response.status_code == 200
    assert client.get("/api/community/agent-questions/not-found", headers=owner).status_code == 404

    assert client.delete(f"/api/community/experiences/{experience_id}", headers=viewer).status_code == 404
    deleted = client.delete(f"/api/community/experiences/{experience_id}", headers=owner)
    assert deleted.status_code == 200
    assert client.get(f"/api/community/experiences/{experience_id}", headers=owner).status_code == 404


def test_router_authentication_and_missing_resource_guards(client: TestClient):
    missing = uuid.uuid4()
    assert client.get("/api/resumes").status_code == 401
    headers = auth_headers(client)
    paths = [
        ("get", f"/api/resumes/{missing}"),
        ("post", f"/api/resumes/{missing}/reindex"),
        ("get", f"/api/resumes/{missing}/versions"),
        ("post", f"/api/resumes/{missing}/versions/delivery"),
        ("post", f"/api/resumes/{missing}/save-optimized"),
        ("get", f"/api/jobs/{missing}"),
        ("post", f"/api/jobs/{missing}/preflight"),
        ("post", f"/api/jobs/{missing}/interview"),
        ("post", f"/api/jobs/{missing}/adapt-resume-task"),
        ("get", f"/api/tasks/{missing}"),
        ("post", f"/api/tasks/{missing}/retry"),
        ("post", f"/api/tasks/{missing}/cancel"),
        ("get", f"/api/training-plans/{missing}"),
        ("post", f"/api/training-plans/{missing}/regenerate"),
    ]
    for method, path in paths:
        response = getattr(client, method)(path, headers=headers)
        assert response.status_code == 404, (method, path, response.text)

    assert client.post("/api/resumes/upload", headers=headers, json={"title": "", "text": "x"}).status_code == 400
    assert client.post("/api/resumes/upload", headers=headers, json={"title": "x"}).status_code == 400
    no_resume_job = client.post(
        "/api/jobs", headers=headers, json={"title": "Job without resume", "company": "Test", "jd_text": JD_TEXT}
    )
    assert no_resume_job.status_code == 200
    assert client.post(f"/api/jobs/{no_resume_job.json()['id']}/adapt-resume-task", headers=headers).status_code == 400

@pytest.mark.asyncio
async def test_direct_router_functions_cover_persistence_and_audit_paths(client: TestClient):
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import jobs as jobs_router
    from app.routers import resumes as resumes_router
    from app.schemas import (
        JobApplicationCreateRequest,
        JobApplicationUpdateRequest,
        ResumeAdaptJDRequest,
        ResumeUpdateRequest,
    )

    email = f"direct-{uuid.uuid4().hex}@example.com"
    headers = auth_headers(client, email=email)
    resume_payload = upload_resume(client, headers, "Direct Router Resume")
    resume_id = uuid.UUID(resume_payload["id"])
    request = Request({"type": "http", "method": "POST", "path": "/direct", "headers": [], "client": ("test", 1)})

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert any(item.id == resume_id for item in await resumes_router.list_resumes(db=db, current_user=user))
        resume = await resumes_router.get_resume(resume_id, db=db, current_user=user)
        assert resume.id == resume_id
        chunks = await resumes_router.list_resume_chunks(resume_id, db=db, current_user=user)
        assert chunks
        reindex = await resumes_router.reindex_resume(resume_id, request, db=db, current_user=user)
        assert reindex.chunk_count >= 1
        versions = await resumes_router.list_resume_versions(resume_id, db=db, current_user=user)
        assert versions
        delivery = await resumes_router.create_delivery_version(resume_id, request, db=db, current_user=user)
        compared = await resumes_router.compare_resume_version(
            resume_id, delivery.id, base_version_id=versions[-1].id, db=db, current_user=user
        )
        assert compared["target_version"]["id"] == str(delivery.id)
        rolled_back = await resumes_router.rollback_resume_version(
            resume_id, versions[-1].id, request, db=db, current_user=user
        )
        assert rolled_back.id
        exported = await resumes_router.export_resume_docx(
            resume_id, request, variant="original", db=db, current_user=user
        )
        assert exported.body
        evidence = await resumes_router.retrieve_evidence_for_jd(
            resume_id, ResumeAdaptJDRequest(jd_text=JD_TEXT), db=db, current_user=user
        )
        assert "pipeline" in evidence
        updated = await resumes_router.update_resume(
            resume_id,
            ResumeUpdateRequest(
                title="Direct Updated Resume",
                optimized_data={"summary": "Verified backend experience", "ats_report": {"total_score": 80}},
            ),
            request,
            db=db,
            current_user=user,
        )
        assert updated.title == "Direct Updated Resume"
        saved = await resumes_router.save_optimized(resume_id, request, db=db, current_user=user)
        assert saved.id == resume_id

        job = await jobs_router.create_job(
            JobApplicationCreateRequest(
                title="Direct Backend Role", company="Direct Tech", jd_text=JD_TEXT, resume_id=resume_id
            ),
            request,
            db=db,
            current_user=user,
        )
        assert job.id
        jobs = await jobs_router.list_jobs(db=db, current_user=user)
        assert any(item.id == job.id for item in jobs)
        fetched = await jobs_router.get_job(job.id, db=db, current_user=user)
        assert fetched.id == job.id
        updated_job = await jobs_router.update_job(
            job.id,
            JobApplicationUpdateRequest(
                title="Direct Senior Backend Role", company="Direct Platform", status="matching"
            ),
            request,
            db=db,
            current_user=user,
        )
        assert updated_job.status == "matching"
        preflight = await jobs_router.preflight_job(job.id, request, db=db, current_user=user)
        assert preflight.ats_report.get("application_review")
        job_export = await jobs_router.export_job_delivery_resume(job.id, request, db=db, current_user=user)
        assert job_export.body
        interview = await jobs_router.create_interview_for_job(job.id, request, db=db, current_user=user)
        assert interview.id
        deleted = await jobs_router.delete_job(job.id, request, db=db, current_user=user)
        assert deleted["message"]
        deleted_resume = await resumes_router.delete_resume(resume_id, request, db=db, current_user=user)
        assert deleted_resume["message"]

@pytest.mark.asyncio
async def test_direct_community_router_question_and_experience_lifecycle(client: TestClient, monkeypatch):
    from datetime import date

    from fastapi import HTTPException
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import community
    from app.schemas import (
        AgentQuestionPracticeUpdateRequest,
        InterviewExperienceCreateRequest,
        InterviewExperienceUpdateRequest,
    )
    from app.services.interview_question_bank import load_agent_question_cards

    email = f"community-direct-{uuid.uuid4().hex}@example.com"
    auth_headers(client, email=email)
    request = Request({"type": "http", "method": "POST", "path": "/direct", "headers": [], "client": ("test", 1)})

    cards = load_agent_question_cards()
    assert cards
    question_id = str(cards[0]["id"])
    assert community._concise_answer({"focus": "RAG"}, [])
    assert community._concise_answer({}, [])
    assert community._next_review_for_status("known")
    assert community._next_review_for_status("review")
    assert community._next_review_for_status("unknown")
    assert community._next_review_for_status("unseen") is None
    assert community._clean_question_items([" Q1 ", "q1", "mail a@example.com"])
    assert community._clean_optional_text(" x ", 2) == "x"
    assert community._clean_optional_text("", 2) is None
    with pytest.raises(HTTPException):
        community._clean_required_text("", 10, "field")

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        listed = await community.list_agent_questions(
            q=None,
            section=None,
            difficulty=None,
            role=None,
            skill=None,
            practice_filter=None,
            limit=5,
            offset=0,
            db=db,
            current_user=user,
        )
        assert listed.items and listed.total >= len(listed.items)
        detail = await community.get_agent_question(question_id, db=db, current_user=user)
        assert detail.id == question_id
        with pytest.raises(HTTPException):
            await community.get_agent_question("missing-card", db=db, current_user=user)

        unknown = await community.update_agent_question_practice(
            question_id,
            AgentQuestionPracticeUpdateRequest(mastery_status="unknown", is_favorite=True),
            request,
            db=db,
            current_user=user,
        )
        assert unknown.is_wrong and unknown.is_favorite
        known = await community.update_agent_question_practice(
            question_id,
            AgentQuestionPracticeUpdateRequest(mastery_status="known"),
            request,
            db=db,
            current_user=user,
        )
        assert known.mastery_status == "known" and not known.is_wrong
        review = await community.update_agent_question_practice(
            question_id,
            AgentQuestionPracticeUpdateRequest(mastery_status="review", is_wrong=True),
            request,
            db=db,
            current_user=user,
        )
        assert review.is_wrong
        favorite = await community.list_agent_questions(
            q=None,
            section=None,
            difficulty=None,
            role=None,
            skill=None,
            practice_filter="favorite",
            limit=20,
            offset=0,
            db=db,
            current_user=user,
        )
        assert any(item.id == question_id for item in favorite.items)
        assert (await community.get_training_profile(request, db=db, current_user=user)).dimensions

        created = await community.create_experience(
            InterviewExperienceCreateRequest(
                company="Direct Company",
                position="Backend Engineer",
                city="Shanghai",
                interview_date=date(2026, 8, 20),
                rounds="phone, technical",
                difficulty="hard",
                result="offer",
                tags=["Python", "python", "RAG"],
                questions=["Explain RAG", "Explain RAG", "How Redis works"],
                process="Two technical rounds",
                content="Detailed interview experience with architecture and coding discussion.",
                visibility="public",
                is_anonymous=False,
                allow_profile_usage=True,
            ),
            request,
            db=db,
            current_user=user,
        )
        assert created.company == "Direct Company" and created.can_edit
        experiences = await community.list_experiences(
            request,
            q="architecture",
            company="Direct",
            tag="Python",
            difficulty="hard",
            result="offer",
            limit=10,
            offset=0,
            db=db,
            current_user=user,
        )
        assert experiences.total >= 1
        fetched = await community.get_experience(created.id, request, db=db, current_user=user)
        assert fetched.view_count >= 1
        updated = await community.update_experience(
            created.id,
            InterviewExperienceUpdateRequest(
                company="Updated Company",
                position="Senior Backend Engineer",
                city="Beijing",
                interview_date=date(2026, 8, 21),
                rounds="onsite",
                difficulty="medium",
                result="passed",
                tags=["FastAPI"],
                questions=["Explain async IO"],
                process="Onsite loop",
                content="Updated detailed interview experience with system design evidence.",
                visibility="private",
                is_anonymous=True,
                allow_profile_usage=False,
            ),
            request,
            db=db,
            current_user=user,
        )
        assert updated.company == "Updated Company" and updated.visibility == "private"
        liked = await community.like_experience(created.id, request, db=db, current_user=user)
        assert liked.like_count >= 1
        assert (await community.delete_experience(created.id, request, db=db, current_user=user))["message"]
        for operation in (
            lambda: community.get_experience(created.id, request, db=db, current_user=user),
            lambda: community.update_experience(
                created.id,
                InterviewExperienceUpdateRequest(company="Missing"),
                request,
                db=db,
                current_user=user,
            ),
            lambda: community.like_experience(created.id, request, db=db, current_user=user),
            lambda: community.delete_experience(created.id, request, db=db, current_user=user),
        ):
            with pytest.raises(HTTPException):
                await operation()

        original_loader = community.load_agent_question_cards
        monkeypatch.setattr(community, "load_agent_question_cards", lambda: (_ for _ in ()).throw(FileNotFoundError()))
        with pytest.raises(HTTPException) as exc:
            await community.list_agent_questions(db=db, current_user=user)
        assert exc.value.status_code == 404
        monkeypatch.setattr(community, "load_agent_question_cards", lambda: (_ for _ in ()).throw(ValueError("bad bank")))
        with pytest.raises(HTTPException) as exc:
            await community.list_agent_questions(db=db, current_user=user)
        assert exc.value.status_code == 400
        monkeypatch.setattr(community, "load_agent_question_cards", original_loader)


@pytest.mark.asyncio
async def test_direct_training_plan_and_task_routers(client: TestClient):
    from fastapi import BackgroundTasks, HTTPException
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import tasks as tasks_router
    from app.routers import training_plans as training_router
    from app.schemas import TrainingPlanGenerateRequest, TrainingPlanTaskUpdateRequest
    from app.services.task_queue import create_task

    email = f"training-direct-{uuid.uuid4().hex}@example.com"
    auth_headers(client, email=email)
    request = Request({"type": "http", "method": "POST", "path": "/direct", "headers": [], "client": ("test", 1)})

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        generated = await training_router.generate_plan(
            TrainingPlanGenerateRequest(), request, db=db, current_user=user
        )
        assert generated.tasks
        current = await training_router.current_plan(request, db=db, current_user=user)
        assert current.id == generated.id
        detail = await training_router.plan_detail(generated.id, request, db=db, current_user=user)
        assert detail.id == generated.id
        changed = await training_router.update_plan_task(
            generated.id,
            generated.tasks[0].id,
            TrainingPlanTaskUpdateRequest(status="completed"),
            request,
            db=db,
            current_user=user,
        )
        assert any(task.status == "completed" for task in changed.tasks)
        regenerated = await training_router.regenerate_plan(generated.id, request, db=db, current_user=user)
        assert regenerated.id == generated.id

        with pytest.raises(HTTPException):
            await training_router.plan_detail(uuid.uuid4(), request, db=db, current_user=user)
        with pytest.raises(HTTPException):
            await training_router.update_plan_task(
                generated.id,
                uuid.uuid4(),
                TrainingPlanTaskUpdateRequest(status="completed"),
                request,
                db=db,
                current_user=user,
            )
        with pytest.raises(HTTPException):
            await training_router.regenerate_plan(uuid.uuid4(), request, db=db, current_user=user)

        queued = await create_task(db, user_id=user.id, task_type="router-task")
        failed = await create_task(db, user_id=user.id, task_type="router-failed")
        failed.status = "failed"
        await db.commit()
        assert (await tasks_router.get_task(queued.id, db=db, current_user=user)).id == queued.id
        listed = await tasks_router.list_tasks(db=db, current_user=user)
        assert any(item.id == queued.id for item in listed)
        retried = await tasks_router.retry_async_task(
            failed.id,
            request,
            BackgroundTasks(),
            db=db,
            current_user=user,
        )
        assert retried.status == "retrying"
        cancelled = await tasks_router.cancel_async_task(queued.id, request, db=db, current_user=user)
        assert cancelled.status == "cancelled"
        for operation in (
            lambda: tasks_router.get_task(uuid.uuid4(), db=db, current_user=user),
            lambda: tasks_router.retry_async_task(
                uuid.uuid4(), request, BackgroundTasks(), db=db, current_user=user
            ),
            lambda: tasks_router.cancel_async_task(uuid.uuid4(), request, db=db, current_user=user),
        ):
            with pytest.raises(HTTPException):
                await operation()

@pytest.mark.asyncio
async def test_direct_interview_router_create_list_get_delete(client: TestClient):
    from fastapi import HTTPException
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import interviews
    from app.schemas import InterviewCreateRequest

    email = f"interview-direct-{uuid.uuid4().hex}@example.com"
    headers = auth_headers(client, email=email)
    resume = upload_resume(client, headers, "Direct Interview Resume")
    request = Request({"type": "http", "method": "POST", "path": "/direct", "headers": [], "client": ("test", 1)})

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        created = await interviews.create_interview(
            InterviewCreateRequest(
                resume_id=uuid.UUID(resume["id"]),
                jd_text=JD_TEXT,
                template_id="comprehensive",
                target_company="Direct Tech",
                target_position="Backend Engineer",
            ),
            request,
            db=db,
            current_user=user,
        )
        assert created.target_company == "Direct Tech"
        listed = await interviews.list_interviews(db=db, current_user=user)
        assert any(item.id == created.id for item in listed)
        assert await interviews.get_interview_templates(current_user=user)
        assert (await interviews.get_interview(created.id, db=db, current_user=user)).id == created.id
        with pytest.raises(HTTPException):
            await interviews._get_resume(uuid.uuid4(), user.id, db)
        with pytest.raises(HTTPException):
            await interviews.get_interview(uuid.uuid4(), db=db, current_user=user)
        with pytest.raises(HTTPException):
            await interviews.list_questions(uuid.uuid4(), db=db, current_user=user)

        disposable = await interviews.create_interview(
            InterviewCreateRequest(resume_id=uuid.UUID(resume["id"])),
            request,
            db=db,
            current_user=user,
        )
        assert (await interviews.delete_interview(disposable.id, request, db=db, current_user=user))["message"]
        with pytest.raises(HTTPException):
            await interviews.delete_interview(disposable.id, request, db=db, current_user=user)

@pytest.mark.asyncio
async def test_direct_interview_router_full_scored_lifecycle(client: TestClient):
    from fastapi import HTTPException
    from sqlalchemy import select
    from starlette.requests import Request
    from starlette.responses import Response

    from app.database import async_session_maker
    from app.models import User
    from app.routers import interviews
    from app.schemas import AnswerSubmitRequest, InterviewCreateRequest

    email = f"interview-full-{uuid.uuid4().hex}@example.com"
    headers = auth_headers(client, email=email)
    resume = upload_resume(client, headers, "Direct Full Interview Resume")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/direct/interview-full-lifecycle",
            "headers": [],
            "client": ("test", 1),
        }
    )

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        interview = await interviews.create_interview(
            InterviewCreateRequest(
                resume_id=uuid.UUID(resume["id"]),
                jd_text=JD_TEXT,
                template_id="technical_first",
                target_company="Lifecycle Tech",
                target_position="Backend Agent Engineer",
            ),
            request,
            db=db,
            current_user=user,
        )

        with pytest.raises(HTTPException) as missing_generation:
            await interviews.generate_questions(
                uuid.uuid4(), request, db=db, current_user=user
            )
        assert missing_generation.value.status_code == 404

        generated = await interviews.generate_questions(
            interview.id, request, db=db, current_user=user
        )
        assert generated["count"] >= 5
        assert generated["template"]["template_id"] == "technical_first"

        existing = await interviews.generate_questions(
            interview.id, request, db=db, current_user=user
        )
        assert existing["count"] == generated["count"]

        questions = await interviews.list_questions(
            interview.id, db=db, current_user=user
        )
        assert len(questions) >= 3
        assert any(question.evidence for question in questions)

        with pytest.raises(HTTPException) as missing_regeneration:
            await interviews.regenerate_question(
                interview.id,
                request,
                question_id=uuid.uuid4(),
                db=db,
                current_user=user,
            )
        assert missing_regeneration.value.status_code == 400

        regenerated = await interviews.regenerate_question(
            interview.id,
            request,
            question_id=questions[0].id,
            db=db,
            current_user=user,
        )
        assert regenerated.id == questions[0].id

        with pytest.raises(HTTPException) as premature_finish:
            await interviews.finish_interview(
                interview.id, request, db=db, current_user=user
            )
        assert premature_finish.value.status_code == 400

        with pytest.raises(HTTPException) as premature_report:
            await interviews.get_report(interview.id, db=db, current_user=user)
        assert premature_report.value.status_code == 400

        answer = AnswerSubmitRequest(
            answer=(
                "I designed an idempotent FastAPI workflow backed by PostgreSQL and Redis. "
                "The implementation used explicit state transitions, retry budgets, audit events, "
                "RAG evidence citations, latency metrics, and rollback drills. I validated the design "
                "with integration tests and measured failure recovery before release."
            )
        )
        with pytest.raises(HTTPException) as wrong_interview:
            await interviews.submit_answer(
                uuid.uuid4(),
                questions[0].id,
                answer,
                request,
                db=db,
                current_user=user,
            )
        assert wrong_interview.value.status_code == 404
        with pytest.raises(HTTPException) as wrong_question:
            await interviews.submit_answer(
                interview.id,
                uuid.uuid4(),
                answer,
                request,
                db=db,
                current_user=user,
            )
        assert wrong_question.value.status_code == 404

        scored_questions = []
        for question in questions[:3]:
            scored = await interviews.submit_answer(
                interview.id,
                question.id,
                answer,
                request,
                db=db,
                current_user=user,
            )
            assert scored.total_score is not None
            assert "technical_accuracy" in (scored.scores or {})
            scored_questions.append(scored)

        with pytest.raises(HTTPException) as force_after_answer:
            await interviews.generate_questions(
                interview.id,
                request,
                force=True,
                db=db,
                current_user=user,
            )
        assert force_after_answer.value.status_code == 400

        with pytest.raises(HTTPException) as answered_regeneration:
            await interviews.regenerate_question(
                interview.id,
                request,
                question_id=scored_questions[0].id,
                db=db,
                current_user=user,
            )
        assert answered_regeneration.value.status_code == 400

        report = await interviews.finish_interview(
            interview.id, request, db=db, current_user=user
        )
        assert report.total_score > 0
        assert report.report_details
        assert report.questions

        loaded_report = await interviews.get_report(
            interview.id, db=db, current_user=user
        )
        assert loaded_report.id == interview.id

        markdown = await interviews.export_report(
            interview.id, request, format="md", db=db, current_user=user
        )
        assert markdown["filename"].endswith(".md")
        assert markdown["content"]

        docx = await interviews.export_report(
            interview.id, request, format="docx", db=db, current_user=user
        )
        assert isinstance(docx, Response)
        assert len(docx.body) > 1000

        pdf = await interviews.export_report(
            interview.id, request, format="pdf", db=db, current_user=user
        )
        assert isinstance(pdf, Response)
        assert len(pdf.body) > 500

        with pytest.raises(HTTPException) as invalid_export:
            await interviews.export_report(
                interview.id, request, format="txt", db=db, current_user=user
            )
        assert invalid_export.value.status_code == 400

        with pytest.raises(HTTPException) as missing_finish:
            await interviews.finish_interview(
                uuid.uuid4(), request, db=db, current_user=user
            )
        assert missing_finish.value.status_code == 404
        with pytest.raises(HTTPException) as missing_report:
            await interviews.get_report(uuid.uuid4(), db=db, current_user=user)
        assert missing_report.value.status_code == 404

@pytest.mark.asyncio
async def test_direct_system_operational_endpoints(client: TestClient, monkeypatch):
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import system

    email = f"system-direct-{uuid.uuid4().hex}@example.com"
    auth_headers(client, email=email)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/direct/system-operations",
            "headers": [],
            "client": ("test", 1),
        }
    )

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        status = await system.status(db=db, current_user=user)
        assert status["database"]["ok"] is True
        assert "release" in status and "operations" in status

        alerts = await system.system_alerts(db=db, current_user=user)
        assert "alerts" in alerts

        unhealthy_vector = {
            "chunk_count": 5,
            "points_count": 2,
            "resume_chunk_count": 4,
            "resume_points_count": 1,
            "configured_vector_size": 1024,
            "actual_vector_size": 768,
            "resume_actual_vector_size": 768,
            "embedding": {"last_call": {"fallback_used": True}},
        }

        async def fake_vector_status(_db):
            return unhealthy_vector

        monkeypatch.setattr(system, "vector_store_status", fake_vector_status)
        monkeypatch.setattr(
            system,
            "embedding_probe",
            lambda: {"ok": True, "fallback_used": True},
        )
        monkeypatch.setattr(
            system,
            "rerank_status",
            lambda: {"enabled": True, "last_call": {"fallback_used": True}},
        )
        monkeypatch.setattr(
            system,
            "rerank_documents",
            lambda query, documents: (
                list(reversed(range(len(documents)))),
                {"fallback_used": True, "query": query},
            ),
        )
        rag = await system.rag_health(active=True, db=db, current_user=user)
        assert rag["health"] == "warning"
        assert len(rag["recommendations"]) >= 3
        assert rag["rerank_probe"]["order"]

        release = await system.release_checks(current_user=user)
        assert "checks" in release
        rerank = await system.rerank_probe(
            system.RerankProbeRequest(query="agent rag", documents=["one", "two"]),
            current_user=user,
        )
        assert rerank["order"] == [1, 0]
        assert await system.admin_metrics(current_user=user) is not None

        monkeypatch.setattr(system, "create_sqlite_backup", lambda settings: {"status": "created"})
        assert (await system.admin_backup(current_user=user))["status"] == "created"

        async def fake_reindex(_db, *, only_missing, limit):
            return {
                "processed_count": 2,
                "chunk_count": 6,
                "indexed_count": 6,
                "failed_count": 0,
                "only_missing": only_missing,
                "limit": limit,
            }

        monkeypatch.setattr(system, "reindex_all_resume_chunks", fake_reindex)
        reindexed = await system.admin_reindex_resumes(
            system.ResumeReindexAllRequest(only_missing=False, limit=2),
            request,
            db=db,
            current_user=user,
        )
        assert reindexed["processed_count"] == 2

        async def fake_dispatch(_db, **kwargs):
            return {
                "configured": True,
                "eligible_count": 2,
                "sent_count": 2,
                "failed_count": 0,
                "skipped_count": 0,
            }

        monkeypatch.setattr(system, "dispatch_system_alerts", fake_dispatch)
        notified = await system.admin_notify_alerts(
            system.AlertNotifyRequest(include_warnings=True, force=True),
            request,
            db=db,
            current_user=user,
        )
        assert notified["sent_count"] == 2


@pytest.mark.asyncio
async def test_alerting_dispatch_success_dedupe_and_failure(client: TestClient, monkeypatch):
    from sqlalchemy import select

    from app.config import get_settings
    from app.database import async_session_maker
    from app.models import User
    from app.services import alerting

    email = f"alerting-direct-{uuid.uuid4().hex}@example.com"
    auth_headers(client, email=email)
    alerts = {
        "alerts": [
            {
                "key": "queue-lag",
                "severity": "warning",
                "feature": "queue",
                "title": "Queue lag",
                "message": "Queue wait time exceeded the objective.",
                "recommendation": "Scale workers and inspect retries.",
            },
            {
                "key": "release-blocked",
                "severity": "critical",
                "feature": "release",
                "title": "Release blocked",
                "message": "A release gate failed.",
                "recommendation": "Resolve the failed gate before deployment.",
            },
            {"key": "informational", "severity": "info", "title": "Info"},
        ]
    }
    base = get_settings()
    disabled = base.model_copy(
        update={
            "ALERT_NOTIFY_ENABLED": False,
            "ALERT_WEBHOOK_URL": "",
            "ALERT_MIN_SEVERITY": "invalid",
        }
    )

    async with async_session_maker() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        skipped = await alerting.dispatch_system_alerts(
            db, settings=disabled, alerts=alerts
        )
        assert skipped["reason"] == "alert_webhook_not_configured"
        assert skipped["eligible_count"] == 1

        configured = base.model_copy(
            update={
                "ALERT_NOTIFY_ENABLED": True,
                "ALERT_WEBHOOK_URL": "https://alerts.example.test/hooks/system",
                "ALERT_WEBHOOK_TOKEN": "test-token",
                "ALERT_MIN_SEVERITY": "warning",
                "ALERT_DEDUPE_MINUTES": 30,
            }
        )

        class FakeResponse:
            def __init__(self, status_code=204, text=""):
                self.status_code = status_code
                self.text = text

        class SuccessfulClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, *, json, headers):
                assert url == configured.ALERT_WEBHOOK_URL
                assert headers["authorization"] == "Bearer test-token"
                assert json["alert"]["severity"] in {"warning", "critical"}
                return FakeResponse()

        monkeypatch.setattr(alerting.httpx, "AsyncClient", SuccessfulClient)
        sent = await alerting.dispatch_system_alerts(
            db, settings=configured, alerts=alerts
        )
        assert sent["sent_count"] == 2
        await db.commit()

        status = await alerting.build_alerting_status(db, configured)
        assert status["configured"] is True
        assert status["status_counts"]["sent"] == 2
        assert len(status["recent"]) == 2

        deduped = await alerting.dispatch_system_alerts(
            db, settings=configured, alerts=alerts
        )
        assert deduped["skipped_count"] == 2

        class FailedStatusClient(SuccessfulClient):
            async def post(self, url, *, json, headers):
                return FakeResponse(503, "service unavailable")

        monkeypatch.setattr(alerting.httpx, "AsyncClient", FailedStatusClient)
        failed_status = await alerting.dispatch_system_alerts(
            db,
            settings=configured,
            alerts={"alerts": [alerts["alerts"][1]]},
            force=True,
        )
        assert failed_status["failed_count"] == 1

        class ExceptionClient(SuccessfulClient):
            async def post(self, url, *, json, headers):
                raise RuntimeError("network unavailable")

        monkeypatch.setattr(alerting.httpx, "AsyncClient", ExceptionClient)
        failed_exception = await alerting.dispatch_system_alerts(
            db,
            settings=configured,
            alerts={"alerts": [alerts["alerts"][0]]},
            force=True,
        )
        assert failed_exception["failed_count"] == 1
        assert failed_exception["notifications"][0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_direct_auth_and_account_export_delete(client: TestClient):
    from fastapi import HTTPException
    from sqlalchemy import select
    from starlette.requests import Request

    from app.database import async_session_maker
    from app.models import User
    from app.routers import account, auth
    from app.schemas import UserLoginRequest, UserRegisterRequest

    email = f"direct-auth-{uuid.uuid4().hex}@example.com"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/direct/auth-account",
            "headers": [],
            "client": ("test", 1),
        }
    )

    async with async_session_maker() as db:
        registered = await auth.register(
            UserRegisterRequest(
                email=email.upper(), password="password123", nickname="Direct Auth"
            ),
            request,
            db=db,
        )
        assert registered.email == email
        with pytest.raises(HTTPException) as duplicate:
            await auth.register(
                UserRegisterRequest(
                    email=email, password="password123", nickname="Duplicate"
                ),
                request,
                db=db,
            )
        assert duplicate.value.status_code == 400

        with pytest.raises(HTTPException) as invalid_login:
            await auth.login(
                UserLoginRequest(email=email, password="incorrect-password"),
                request,
                db=db,
            )
        assert invalid_login.value.status_code == 400

        token = await auth.login(
            UserLoginRequest(email=email, password="password123"),
            request,
            db=db,
        )
        assert token.access_token
        user = await db.scalar(select(User).where(User.email == email))
        assert (await auth.me(current_user=user)).id == user.id

        exported = await account.export_account_data(
            request, db=db, current_user=user
        )
        assert exported["user"]["email"] == email
        assert exported["organizations"]
        assert exported["audit_logs"]

        deleted = await account.delete_account(
            request, db=db, current_user=user
        )
        assert deleted["message"]
        assert await db.scalar(select(User).where(User.email == email)) is None
