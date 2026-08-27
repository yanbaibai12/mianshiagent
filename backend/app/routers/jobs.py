import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker, get_db
from app.models import AsyncTask, Interview, JobApplication, Resume, ResumeVersion, User
from app.schemas import (
    InterviewResponse,
    JobApplicationCreateRequest,
    JobApplicationResponse,
    JobApplicationUpdateRequest,
    ResumeAdaptJDTaskResponse,
)
from app.services.ats_scoring import build_ats_report
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.document_export import content_disposition, resume_to_docx_bytes, safe_filename
from app.services.task_queue import TaskCancelled, create_task, enqueue_task, update_task
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.services.usage_telemetry import record_usage
from app.utils.time import utc_now

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
settings = get_settings()


def _flatten_dimension_items(ats_report: dict, key: str, limit: int = 6) -> list[str]:
    items: list[str] = []
    for dimension in ats_report.get("dimensions") or []:
        values = dimension.get(key) if isinstance(dimension, dict) else None
        if isinstance(values, list):
            items.extend(str(item) for item in values if item)
        elif values:
            items.append(str(values))
    seen = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:limit]


def _application_review_from_ats(ats_report: dict, *, has_optimized_version: bool = False) -> dict:
    score = float(ats_report.get("total_score") or 0)
    missing_top = [str(item) for item in ats_report.get("missing_top") or [] if item]
    covered = _flatten_dimension_items(ats_report, "covered", 8)
    risks = _flatten_dimension_items(ats_report, "risk", 8)
    evidence = ats_report.get("requirement_evidence") if isinstance(ats_report.get("requirement_evidence"), list) else []
    evidence_count = len(evidence)

    if score >= 82 and evidence_count >= 3 and len(missing_top) <= 2:
        decision = "apply_now"
        decision_label = "建议投递"
        priority = "high"
        summary = "匹配度和简历证据较强，可以进入投递版导出与面试准备。"
    elif score >= 68:
        decision = "revise_before_apply"
        decision_label = "先改再投"
        priority = "medium"
        summary = "具备投递基础，但需要先补强缺口和表达证据，再导出投递版。"
    elif score >= 52:
        decision = "low_priority"
        decision_label = "低优先级"
        priority = "low"
        summary = "存在明显缺口，建议只在岗位很重要或可补充真实经历时投入优化。"
    else:
        decision = "not_recommended"
        decision_label = "暂不建议"
        priority = "hold"
        summary = "当前简历证据与 JD 差距较大，不建议直接投入完整投递材料。"

    blockers = [*missing_top[:4], *risks[:4]]
    if not blockers and score < 82:
        blockers = ["缺少足够可验证的项目证据或结果指标"]

    actions = []
    if missing_top:
        actions.append(f"补充或改写与 {missing_top[0]} 相关的真实项目/实习证据，不能编造不存在的经历。")
    if risks:
        actions.append(f"先处理格式或证据风险：{risks[0]}。")
    if evidence_count < 3:
        actions.append("为核心要求补充至少 2-3 条可追溯到原简历的证据片段。")
    if not has_optimized_version:
        actions.append("通过岗位简历优化生成 JD 版本后，再导出投递版 Word。")
    actions.append("导出前检查正文无 JSON 字段、系统话术和无法证明的数据。")

    reviewer_checks = [
        {
            "name": "事实边界",
            "status": "pass" if evidence_count >= 3 else "warning",
            "detail": "优化内容需要全部来自原简历证据，缺口只能进入建议，不能写入经历正文。",
        },
        {
            "name": "ATS 解析",
            "status": "pass" if score >= 68 else "warning",
            "detail": "检查硬技能、关键词和项目证据是否能被机器解析，不只看措辞是否好看。",
        },
        {
            "name": "投递材料",
            "status": "pass" if has_optimized_version else "todo",
            "detail": "生成投递版后还需要检查 Word/PDF 可读性、文件名和修改前后对照。",
        },
    ]

    return {
        "decision": decision,
        "decision_label": decision_label,
        "priority": priority,
        "score": round(score, 1),
        "summary": summary,
        "strengths": covered[:5],
        "blockers": blockers[:6],
        "actions_before_apply": actions[:6],
        "reviewer_checks": reviewer_checks,
        "evidence_count": evidence_count,
        "source": "ats_preflight_reviewer",
    }


async def _preflight_job_application(db: AsyncSession, job: JobApplication, resume: Resume) -> dict:
    ats_report = await build_ats_report(db, resume, job.jd_text)
    review = _application_review_from_ats(
        ats_report,
        has_optimized_version=bool(job.current_resume_version_id),
    )
    ats_report["application_review"] = review
    return ats_report


@router.get("", response_model=list[JobApplicationResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JobApplication).where(JobApplication.user_id == current_user.id).order_by(JobApplication.updated_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=JobApplicationResponse)
async def create_job(
    req: JobApplicationCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org = await resolve_request_organization(request, db, current_user)
    if req.resume_id:
        resume = await db.scalar(select(Resume).where(Resume.id == req.resume_id, Resume.user_id == current_user.id))
        if not resume:
            raise HTTPException(status_code=404, detail="绑定的简历不存在")
    job = JobApplication(
        user_id=current_user.id,
        organization_id=org.id,
        resume_id=req.resume_id,
        company=(req.company or "").strip(),
        title=req.title.strip(),
        jd_text=req.jd_text,
        status="draft",
    )
    db.add(job)
    await db.flush()
    log_audit_event(
        db,
        event_type="job.create",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=str(job.id),
        request=request,
        metadata={"title": job.title, "company": job.company, **tenant_metadata(org)},
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/preflight", response_model=JobApplicationResponse)
async def preflight_job(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    if not job.resume_id:
        raise HTTPException(status_code=400, detail="请先绑定简历")
    resume = await db.scalar(select(Resume).where(Resume.id == job.resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="绑定简历不存在")
    ats_report = await _preflight_job_application(db, job, resume)
    job.match_score = float(ats_report.get("total_score") or 0)
    job.ats_report = ats_report
    log_audit_event(
        db,
        event_type="job.preflight",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
        metadata={
            "resume_id": str(resume.id),
            "match_score": job.match_score,
            "decision": (ats_report.get("application_review") or {}).get("decision"),
        },
    )
    record_usage(
        db,
        current_user.id,
        "job_preflight",
        organization_id=job.organization_id,
        metadata={
            "job_id": str(job.id),
            "resume_id": str(resume.id),
            "match_score": job.match_score,
            "decision": (ats_report.get("application_review") or {}).get("decision"),
        },
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobApplicationResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    return job


@router.put("/{job_id}", response_model=JobApplicationResponse)
async def update_job(
    job_id: uuid.UUID,
    req: JobApplicationUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    if req.resume_id is not None:
        resume = await db.scalar(select(Resume).where(Resume.id == req.resume_id, Resume.user_id == current_user.id))
        if not resume:
            raise HTTPException(status_code=404, detail="绑定的简历不存在")
        job.resume_id = req.resume_id
    if req.title is not None and req.title.strip():
        job.title = req.title.strip()
    if req.company is not None:
        job.company = req.company.strip()
    if req.jd_text is not None and req.jd_text.strip():
        job.jd_text = req.jd_text
    if req.status is not None:
        job.status = req.status
    log_audit_event(
        db,
        event_type="job.update",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.delete("/{job_id}")
async def delete_job(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    log_audit_event(
        db,
        event_type="job.delete",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
    )
    await db.delete(job)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{job_id}/interview", response_model=InterviewResponse)
async def create_interview_for_job(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    if not job.resume_id:
        raise HTTPException(status_code=400, detail="请先绑定简历")
    resume = await db.scalar(select(Resume).where(Resume.id == job.resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="绑定简历不存在")
    interview = Interview(
        user_id=current_user.id,
        organization_id=job.organization_id or resume.organization_id,
        resume_id=resume.id,
        jd_text=job.jd_text,
    )
    db.add(interview)
    await db.flush()
    job.interview_id = interview.id
    job.status = "interviewing"
    log_audit_event(
        db,
        event_type="job.create_interview",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
        metadata={"interview_id": str(interview.id), "resume_id": str(resume.id)},
    )
    record_usage(
        db,
        current_user.id,
        "interview_create",
        organization_id=interview.organization_id,
        metadata={"resume_id": str(resume.id), "job_id": str(job.id)},
    )
    await db.commit()
    await db.refresh(interview)
    return interview


@router.get("/{job_id}/resume/export")
async def export_job_delivery_resume(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    if not job.resume_id:
        raise HTTPException(status_code=400, detail="请先绑定简历")
    resume = await db.scalar(select(Resume).where(Resume.id == job.resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="绑定简历不存在")
    version = None
    if job.current_resume_version_id:
        version = await db.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == job.current_resume_version_id,
                ResumeVersion.resume_id == resume.id,
                ResumeVersion.user_id == current_user.id,
            )
        )
    data = version.data if version else resume.optimized_data if isinstance(resume.optimized_data, dict) else resume.parsed_data
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="当前岗位没有可导出的简历版本")
    title = f"{job.company}_{job.title}_投递版简历" if job.company else f"{job.title}_投递版简历"
    filename = safe_filename(title, ".docx")
    content = resume_to_docx_bytes(
        data,
        title=title,
        jd_text=job.jd_text,
        ats_report=version.ats_report if version else job.ats_report if isinstance(job.ats_report, dict) else {},
        change_details=version.change_details if version else data.get("change_details") if isinstance(data.get("change_details"), list) else [],
        job_context={"company": job.company, "title": job.title},
    )
    log_audit_event(
        db,
        event_type="job.export_delivery_resume",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
        metadata={"filename": filename, "resume_id": str(resume.id), "version_id": str(version.id) if version else None},
    )
    await db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": content_disposition(filename)},
    )


async def _run_job_adapt_task(task_id: str) -> None:
    from app.routers.resumes import _adapt_resume_to_jd

    async with async_session_maker() as db:
        task = await db.scalar(select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id)))
        if not task:
            return
        try:
            await update_task(db, task, status="running", progress=10, stage="正在加载岗位任务")
            await db.commit()
            payload = task.input_payload or {}
            job_id = uuid.UUID(str(payload.get("job_id")))
            job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == task.user_id))
            if not job:
                raise RuntimeError("岗位任务不存在")
            if not job.resume_id:
                raise RuntimeError("岗位任务没有绑定简历")
            resume = await db.scalar(select(Resume).where(Resume.id == job.resume_id, Resume.user_id == task.user_id))
            if not resume:
                raise RuntimeError("绑定简历不存在")

            job.status = "matching"
            await update_task(db, task, progress=30, stage="正在执行 JD 匹配与简历优化")
            await db.commit()
            result_payload = await _adapt_resume_to_jd(db, resume, job.jd_text, source_task_id=task.id, source_job_id=job.id)
            job.status = "optimized"
            job.match_score = float(resume.match_score or 0)
            ats_report = result_payload["ats_report"]
            ats_report["application_review"] = _application_review_from_ats(
                ats_report,
                has_optimized_version=bool(result_payload.get("version_id")),
            )
            job.ats_report = ats_report
            if result_payload.get("version_id"):
                job.current_resume_version_id = uuid.UUID(result_payload["version_id"])
            await update_task(
                db,
                task,
                status="success",
                progress=100,
                stage="岗位简历优化完成",
                result_payload={
                    "job_id": str(job.id),
                    "resume_id": str(resume.id),
                    "version_id": result_payload.get("version_id"),
                    "match_score": float(job.match_score or 0),
                    "ats_report": ats_report,
                },
            )
            await db.commit()
        except TaskCancelled:
            await db.rollback()
            task = await db.scalar(select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id)))
            if task:
                task.status = "cancelled"
                task.stage = "任务已取消"
                task.ended_at = utc_now()
                task.updated_at = utc_now()
                await db.commit()
        except Exception as exc:
            await db.rollback()
            task = await db.scalar(select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id)))
            if task:
                await update_task(
                    db,
                    task,
                    status="failed",
                    progress=max(task.progress or 0, 95),
                    stage="岗位简历优化失败",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                await db.commit()


@router.post("/{job_id}/adapt-resume-task", response_model=ResumeAdaptJDTaskResponse)
async def adapt_resume_for_job_task(
    job_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.scalar(select(JobApplication).where(JobApplication.id == job_id, JobApplication.user_id == current_user.id))
    if not job:
        raise HTTPException(status_code=404, detail="岗位任务不存在")
    if not job.resume_id:
        raise HTTPException(status_code=400, detail="请先绑定简历")
    task = await create_task(
        db,
        user_id=current_user.id,
        organization_id=job.organization_id,
        task_type="job.adapt_resume",
        resource_type="job",
        resource_id=str(job.id),
        input_payload={"job_id": str(job.id)},
    )
    log_audit_event(
        db,
        event_type="job.adapt_resume_task",
        resource_type="job",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=job.organization_id,
        resource_id=str(job.id),
        request=request,
        metadata={"task_id": str(task.id)},
    )
    await db.commit()
    await db.refresh(task)
    await enqueue_task(
        db,
        task,
        background_tasks=background_tasks,
        local_runner=_run_job_adapt_task,
        rq_runner_path="app.workers.task_worker.run_task",
    )
    await db.commit()
    await db.refresh(task)
    return ResumeAdaptJDTaskResponse(task=task)
