import time
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker, get_db
from app.models import AsyncTask, JobApplication, Resume, ResumeChunk, ResumeTemplate, ResumeVersion, User
from app.prompts import ADAPT_JD_PROMPT, OPTIMIZE_RESUME_PROMPT, PARSE_RESUME_PROMPT
from app.schemas import (
    ResumeAdaptJDRequest,
    ResumeAdaptJDTaskResponse,
    ResumeChunkResponse,
    ResumeListItemResponse,
    ResumeOptimizeRequest,
    ResumeReindexResponse,
    ResumeResponse,
    ResumeUpdateRequest,
    ResumeVersionResponse,
)
from app.services.ats_scoring import build_ats_report
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.document_export import content_disposition, resume_to_docx_bytes, safe_filename
from app.services.knowledge_base import (
    build_rag_context,
    compact_json,
    retrieve_knowledge,
    serialize_rag_references,
)
from app.services.llm_client import get_llm_client
from app.services.rerank_service import rerank_status
from app.services.resume_index import (
    delete_resume_vectors,
    ensure_resume_chunks,
    reindex_resume_chunks,
    retrieve_resume_evidence,
)
from app.services.resume_parser import ResumeParser
from app.services.resume_versions import (
    build_version_compare,
    create_resume_version,
    ensure_original_version,
    mark_resume_version_current,
)
from app.services.task_queue import TaskCancelled, create_task, enqueue_task, update_task
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.services.usage_telemetry import record_usage
from app.utils.storage import delete_uploaded_file, is_allowed_file, save_upload_file
from app.utils.time import utc_now

router = APIRouter(prefix="/api/resumes", tags=["resumes"])
settings = get_settings()

FORBIDDEN_RESUME_PHRASES = ("面向该 JD", "可重点呈现", "岗位要求")
NON_RESUME_OUTPUT_KEYS = {
    "jd_alignment",
    "recommended_focus",
    "advice",
    "suggestions",
    "analysis",
    "optimization_advice",
    "recommended_changes",
}


def _sanitize_resume_output(value):
    if isinstance(value, str):
        cleaned = value
        for phrase in FORBIDDEN_RESUME_PHRASES:
            cleaned = cleaned.replace(phrase, "")
        return " ".join(cleaned.split()) if cleaned != value else value
    if isinstance(value, list):
        return [_sanitize_resume_output(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_resume_output(item) for key, item in value.items()}
    return value


def _strip_non_resume_fields(value):
    if isinstance(value, list):
        return [_strip_non_resume_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_non_resume_fields(item)
            for key, item in value.items()
            if str(key).lower() not in NON_RESUME_OUTPUT_KEYS
        }
    return value


def _build_resume_evidence_context(ats_report: dict) -> str:
    evidence = ats_report.get("requirement_evidence") or []
    if not evidence:
        return "简历证据检索未命中明确片段，优化时只能基于原始结构化简历，不得新增事实。"
    lines = [
        "简历证据检索结果（只允许基于这些片段强化表达，不得编造未出现事实）：",
    ]
    for index, item in enumerate(evidence[:10], 1):
        lines.append(
            f"{index}. 要求：{item.get('requirement')}；模块：{item.get('section_label')}；"
            f"经历：{item.get('item_title')}；证据：{item.get('excerpt')}"
        )
    return "\n".join(lines)


async def _adapt_resume_to_jd(
    db: AsyncSession,
    resume: Resume,
    jd_text: str,
    *,
    source_task_id: uuid.UUID | None = None,
    source_job_id: uuid.UUID | None = None,
) -> dict:
    index_result = await ensure_resume_chunks(db, resume)
    ats_report = await build_ats_report(db, resume, jd_text)
    evidence_context = _build_resume_evidence_context(ats_report)

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{jd_text} {compact_json(resume.optimized_data or resume.parsed_data)}",
        categories=["resume_writing", "job_knowledge"],
        limit=6,
    )
    rag_context = build_rag_context(rag_snippets)
    prompt = ADAPT_JD_PROMPT.format(
        jd_text=(
            f"{jd_text}\n\n{rag_context}\n\n{evidence_context}\n\n"
            f"ATS 证据评分：{ats_report.get('total_score', 0)}；"
            f"Top 缺口：{'、'.join((ats_report.get('missing_top') or [])[:8])}"
        ),
        resume_data=str(resume.optimized_data or resume.parsed_data),
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages, feature="jd_adapt")
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="JD 适配结果不可用，请稍后重试")
    response = _sanitize_resume_output(response)
    if isinstance(response.get("optimized_resume"), dict):
        response["optimized_resume"] = _strip_non_resume_fields(response["optimized_resume"])
    response["rag_references"] = serialize_rag_references(rag_snippets)
    response["ats_report"] = ats_report
    response["resume_evidence"] = ats_report.get("requirement_evidence", [])
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="jd_adapt",
        started_at=started_at,
    )

    resume.jd_text = jd_text
    resume.match_score = float(ats_report.get("total_score", response.get("match_score", 0)))
    version = None
    if response.get("optimized_resume"):
        optimized_resume = response["optimized_resume"]
        if isinstance(optimized_resume, dict):
            optimized_resume["rag_references"] = response["rag_references"]
            optimized_resume["ats_report"] = ats_report
            optimized_resume["resume_evidence"] = response["resume_evidence"]
            optimized_resume["resume_index"] = index_result
            optimized_resume["change_details"] = response.get("change_details") or []
        resume.optimized_data = optimized_resume
        version = await create_resume_version(
            db,
            resume,
            version_type="jd_optimized",
            title=f"{resume.title} JD 优化版",
            jd_text=jd_text,
            data=optimized_resume if isinstance(optimized_resume, dict) else {},
            ats_report=ats_report,
            change_details=response.get("change_details") or [],
            source_task_id=source_task_id,
            source_job_id=source_job_id,
            created_by="jd_adapt",
        )

    return {
        "response": response,
        "ats_report": ats_report,
        "index_result": index_result,
        "llm_metadata": llm_metadata,
        "version_id": str(version.id) if version else None,
    }


@router.post("/upload", response_model=ResumeResponse)
async def upload_resume(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = ""
    text: Optional[str] = None
    file = None
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        payload = await request.json()
        title = str(payload.get("title") or "").strip()
        text = payload.get("text")
    elif content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"当前环境暂不支持文件上传，请先粘贴简历文本：{exc}",
            ) from exc
        title = str(form.get("title") or "").strip()
        text_value = form.get("text")
        text = str(text_value) if text_value else None
        uploaded = form.get("file")
        if uploaded is not None and hasattr(uploaded, "filename"):
            file = uploaded
    else:
        raise HTTPException(status_code=400, detail="请使用 JSON 文本或 multipart 文件上传")

    if not title:
        raise HTTPException(status_code=400, detail="请填写简历名称")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="简历名称不能超过 200 个字符")
    if not file and not text:
        raise HTTPException(status_code=400, detail="请上传文件或粘贴简历文本")
    org = await resolve_request_organization(request, db, current_user)

    original_text = ""
    original_file = None

    if file:
        if not is_allowed_file(file.filename or ""):
            raise HTTPException(status_code=400, detail="仅支持 PDF 和 DOCX 文件")
        file_path = None
        try:
            file_path = await save_upload_file(file)
            original_file = file_path
            original_text = ResumeParser.parse(file_path)
        except HTTPException:
            raise
        except Exception as exc:
            if file_path:
                delete_uploaded_file(file_path)
            raise HTTPException(
                status_code=400,
                detail=f"文件解析失败，请改用粘贴纯文本方式上传：{exc}",
            ) from exc
    elif text:
        original_text = text
    if len(original_text) > settings.MAX_RESUME_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"简历文本过长，不能超过 {settings.MAX_RESUME_TEXT_LENGTH} 个字符",
        )

    # 调用 LLM 解析简历
    llm = get_llm_client(settings)
    prompt = PARSE_RESUME_PROMPT.format(resume_text=original_text[:8000])
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    try:
        parsed_data = await llm.chat_completion_json(messages, feature="resume_parse")
        if not isinstance(parsed_data, dict):
            raise HTTPException(status_code=502, detail="简历结构化结果不可用，请稍后重试")
        llm_metadata = llm.build_usage_metadata(
            messages,
            parsed_data,
            feature="resume_parse",
            started_at=started_at,
        )
    except Exception:
        delete_uploaded_file(original_file)
        raise

    resume = Resume(
        user_id=current_user.id,
        organization_id=org.id,
        title=title,
        original_file=original_file,
        original_text=original_text,
        parsed_data=parsed_data,
    )
    db.add(resume)
    await db.flush()
    index_result = await reindex_resume_chunks(db, resume)
    await ensure_original_version(db, resume)
    log_audit_event(
        db,
        event_type="resume.upload",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=str(resume.id),
        request=request,
        metadata={"title": resume.title, "source": "file" if file else "text", **tenant_metadata(org)},
    )
    record_usage(
        db,
        current_user.id,
        "resume_upload",
        organization_id=org.id,
        metadata={
            "resume_id": str(resume.id),
            "text_length": len(original_text),
            "source": "file" if file else "text",
            "resume_chunk_count": index_result.get("chunk_count", 0),
            "resume_vector_status": (index_result.get("vector") or {}).get("status"),
            **llm_metadata,
        },
    )
    await db.commit()
    await db.refresh(resume)
    return resume


@router.get("", response_model=list[ResumeListItemResponse])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Resume).where(Resume.user_id == current_user.id))
    return result.scalars().all()


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.get("/{resume_id}/chunks", response_model=list[ResumeChunkResponse])
async def list_resume_chunks(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    result = await db.execute(
        select(ResumeChunk)
        .where(ResumeChunk.resume_id == resume_id, ResumeChunk.user_id == current_user.id)
        .order_by(ResumeChunk.section, ResumeChunk.item_title, ResumeChunk.chunk_index)
    )
    return result.scalars().all()


@router.post("/{resume_id}/reindex", response_model=ResumeReindexResponse)
async def reindex_resume(
    resume_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    index_result = await reindex_resume_chunks(db, resume)
    log_audit_event(
        db,
        event_type="resume.reindex",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={
            "resume_chunk_count": index_result.get("chunk_count", 0),
            "resume_vector_status": (index_result.get("vector") or {}).get("status"),
        },
    )
    await db.commit()
    return ResumeReindexResponse(
        status=index_result.get("status", "unknown"),
        chunk_count=int(index_result.get("chunk_count", 0)),
        collection=index_result.get("collection", ""),
        vector=index_result.get("vector", {}),
    )


@router.get("/{resume_id}/versions", response_model=list[ResumeVersionResponse])
async def list_resume_versions(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    await ensure_original_version(db, resume)
    await db.commit()
    result = await db.execute(
        select(ResumeVersion)
        .where(ResumeVersion.resume_id == resume.id, ResumeVersion.user_id == current_user.id)
        .order_by(ResumeVersion.version_number.desc())
    )
    return result.scalars().all()


@router.post("/{resume_id}/versions/delivery", response_model=ResumeVersionResponse)
async def create_delivery_version(
    resume_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    data = resume.optimized_data if isinstance(resume.optimized_data, dict) else resume.parsed_data
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="当前简历没有可保存的结构化内容")
    version = await create_resume_version(
        db,
        resume,
        version_type="delivery",
        title=f"{resume.title} 投递版",
        jd_text=resume.jd_text,
        data=data,
        ats_report=data.get("ats_report") if isinstance(data.get("ats_report"), dict) else {},
        change_details=data.get("change_details") if isinstance(data.get("change_details"), list) else [],
        created_by="user",
    )
    log_audit_event(
        db,
        event_type="resume.version_delivery",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"version_id": str(version.id)},
    )
    await db.commit()
    await db.refresh(version)
    return version


@router.post("/{resume_id}/versions/{version_id}/rollback", response_model=ResumeResponse)
async def rollback_resume_version(
    resume_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    version = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id,
            ResumeVersion.resume_id == resume.id,
            ResumeVersion.user_id == current_user.id,
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    if version.version_type == "original":
        resume.parsed_data = version.data
        resume.optimized_data = None
        await reindex_resume_chunks(db, resume)
    else:
        resume.optimized_data = version.data
    await mark_resume_version_current(db, version)
    resume.jd_text = version.jd_text or resume.jd_text
    if isinstance(version.ats_report, dict) and version.ats_report.get("total_score") is not None:
        resume.match_score = float(version.ats_report.get("total_score"))
    log_audit_event(
        db,
        event_type="resume.version_rollback",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"version_id": str(version.id), "version_type": version.version_type},
    )
    await db.commit()
    await db.refresh(resume)
    return resume


@router.get("/{resume_id}/versions/{version_id}/compare")
async def compare_resume_version(
    resume_id: uuid.UUID,
    version_id: uuid.UUID,
    base_version_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    target = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id,
            ResumeVersion.resume_id == resume.id,
            ResumeVersion.user_id == current_user.id,
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="版本不存在")
    if base_version_id:
        base = await db.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == base_version_id,
                ResumeVersion.resume_id == resume.id,
                ResumeVersion.user_id == current_user.id,
            )
        )
    else:
        base = await db.scalar(
            select(ResumeVersion)
            .where(
                ResumeVersion.resume_id == resume.id,
                ResumeVersion.user_id == current_user.id,
                ResumeVersion.version_type == "original",
            )
            .order_by(ResumeVersion.version_number.asc())
        )
    if not base:
        raise HTTPException(status_code=404, detail="对比基线版本不存在")
    return build_version_compare(base, target)


@router.get("/{resume_id}/export")
async def export_resume_docx(
    resume_id: uuid.UUID,
    request: Request,
    version_id: uuid.UUID | None = None,
    variant: str = "optimized",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    version = None
    if version_id:
        version = await db.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == version_id,
                ResumeVersion.resume_id == resume.id,
                ResumeVersion.user_id == current_user.id,
            )
        )
        if not version:
            raise HTTPException(status_code=404, detail="版本不存在")
    if version:
        data = version.data
        title = version.title
        jd_text = version.jd_text
    elif variant == "delivery":
        data = resume.optimized_data if isinstance(resume.optimized_data, dict) else resume.parsed_data
        title = f"{resume.title} 投递版"
        jd_text = resume.jd_text
    elif variant == "original":
        data = resume.parsed_data
        title = f"{resume.title} 原始版"
        jd_text = None
    else:
        data = resume.optimized_data if isinstance(resume.optimized_data, dict) else resume.parsed_data
        title = f"{resume.title} 优化版"
        jd_text = resume.jd_text
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="当前简历没有可导出的结构化内容")
    source_job = None
    if version and version.source_job_id:
        source_job = await db.scalar(
            select(JobApplication).where(
                JobApplication.id == version.source_job_id,
                JobApplication.user_id == current_user.id,
            )
        )
    job_context = {"company": source_job.company, "title": source_job.title} if source_job else None
    if source_job and variant == "delivery":
        title = f"{source_job.company}_{source_job.title}_投递版简历"
    filename = safe_filename(title, ".docx")
    content = resume_to_docx_bytes(
        data,
        title=title,
        jd_text=jd_text,
        ats_report=version.ats_report if version else data.get("ats_report") if isinstance(data.get("ats_report"), dict) else {},
        change_details=version.change_details if version else data.get("change_details") if isinstance(data.get("change_details"), list) else [],
        job_context=job_context,
    )
    log_audit_event(
        db,
        event_type="resume.export_docx",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"filename": filename, "variant": variant, "version_id": str(version.id) if version else None},
    )
    await db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/{resume_id}/retrieve-evidence")
async def retrieve_evidence_for_jd(
    resume_id: uuid.UUID,
    req: ResumeAdaptJDRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    index_result = await ensure_resume_chunks(db, resume)
    if index_result.get("status") != "already_indexed":
        await db.commit()
    snippets = await retrieve_resume_evidence(
        db,
        user_id=current_user.id,
        resume_id=resume.id,
        query=req.jd_text,
        limit=8,
    )
    return {
        "index": index_result,
        "results": [snippet.to_dict() for snippet in snippets],
        "pipeline": {
            "retrieval": "resume_keyword + resume_vector",
            "fusion": "rrf",
            "rerank": rerank_status(),
            "scope": "user_id + resume_id",
        },
    }


@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: uuid.UUID,
    req: ResumeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    if req.title is not None:
        title = req.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="简历名称不能为空")
        resume.title = title
    if req.parsed_data is not None:
        resume.parsed_data = req.parsed_data
    if req.optimized_data is not None:
        resume.optimized_data = req.optimized_data
    index_result = None
    if req.parsed_data is not None:
        index_result = await reindex_resume_chunks(db, resume)
        await create_resume_version(
            db,
            resume,
            version_type="manual_edit",
            title=f"{resume.title} 手动编辑版",
            data=req.parsed_data,
            created_by="user",
            notes="用户编辑了解析版结构化内容",
        )
    elif req.optimized_data is not None and isinstance(req.optimized_data, dict):
        await create_resume_version(
            db,
            resume,
            version_type="manual_edit",
            title=f"{resume.title} 手动编辑版",
            data=req.optimized_data,
            ats_report=req.optimized_data.get("ats_report") if isinstance(req.optimized_data.get("ats_report"), dict) else {},
            change_details=req.optimized_data.get("change_details") if isinstance(req.optimized_data.get("change_details"), list) else [],
            created_by="user",
            notes="用户编辑了优化版结构化内容",
        )

    log_audit_event(
        db,
        event_type="resume.update",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={
            "title_changed": req.title is not None,
            "parsed_changed": req.parsed_data is not None,
            "optimized_changed": req.optimized_data is not None,
            "resume_chunk_count": (index_result or {}).get("chunk_count"),
            "resume_vector_status": ((index_result or {}).get("vector") or {}).get("status"),
        },
    )
    await db.commit()
    await db.refresh(resume)
    return resume


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    original_file = resume.original_file
    await delete_resume_vectors(current_user.id, resume.id)
    log_audit_event(
        db,
        event_type="resume.delete",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"title": resume.title, "had_file": bool(original_file)},
    )
    await db.delete(resume)
    await db.commit()
    delete_uploaded_file(original_file)
    return {"message": "删除成功"}


@router.post("/{resume_id}/optimize", response_model=ResumeResponse)
async def optimize_resume(
    resume_id: uuid.UUID,
    req: ResumeOptimizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    template_result = await db.execute(
        select(ResumeTemplate).where(ResumeTemplate.id == req.template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{template.category} {template.name} {compact_json(resume.parsed_data)}",
        categories=["resume_writing", "job_knowledge"],
        limit=5,
    )
    rag_context = build_rag_context(rag_snippets)
    prompt = OPTIMIZE_RESUME_PROMPT.format(
        template_rules=f"{template.prompt}\n\n{rag_context}",
        resume_data=str(resume.parsed_data),
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    optimized_data = await llm.chat_completion_json(messages, feature="resume_optimize")
    if not isinstance(optimized_data, dict):
        raise HTTPException(status_code=502, detail="简历优化结果不可用，请稍后重试")
    optimized_data["rag_references"] = serialize_rag_references(rag_snippets)
    llm_metadata = llm.build_usage_metadata(
        messages,
        optimized_data,
        feature="resume_optimize",
        started_at=started_at,
    )

    resume.optimized_data = optimized_data
    resume.template_id = template.id
    await create_resume_version(
        db,
        resume,
        version_type="template_optimized",
        title=f"{resume.title} 模板优化版",
        data=optimized_data,
        change_details=optimized_data.get("change_details") if isinstance(optimized_data.get("change_details"), list) else [],
        created_by="template_optimize",
    )
    log_audit_event(
        db,
        event_type="resume.optimize",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"template_id": template.id},
    )
    record_usage(
        db,
        current_user.id,
        "resume_optimize",
        organization_id=resume.organization_id,
        metadata={"resume_id": str(resume.id), "template_id": template.id, **llm_metadata},
    )
    await db.commit()
    await db.refresh(resume)
    return resume


async def _enqueue_resume_adapt_jd_task(
    resume_id: uuid.UUID,
    jd_text: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    current_user: User,
) -> ResumeAdaptJDTaskResponse:
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id))
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    task = await create_task(
        db,
        user_id=current_user.id,
        organization_id=resume.organization_id,
        task_type="resume.adapt_jd",
        resource_type="resume",
        resource_id=str(resume.id),
        input_payload={"resume_id": str(resume.id), "jd_text": jd_text},
    )
    log_audit_event(
        db,
        event_type="resume.adapt_jd_task",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"task_id": str(task.id), "jd_length": len(jd_text)},
    )
    await db.commit()
    await db.refresh(task)
    await enqueue_task(
        db,
        task,
        background_tasks=background_tasks,
        local_runner=_run_resume_adapt_jd_task,
        rq_runner_path="app.workers.task_worker.run_task",
    )
    await db.commit()
    await db.refresh(task)
    return ResumeAdaptJDTaskResponse(task=task)


@router.post("/{resume_id}/adapt-jd", response_model=ResumeAdaptJDTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def adapt_jd(
    resume_id: uuid.UUID,
    req: ResumeAdaptJDRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _enqueue_resume_adapt_jd_task(
        resume_id,
        req.jd_text,
        request,
        background_tasks,
        db,
        current_user,
    )


async def _run_resume_adapt_jd_task(task_id: str) -> None:
    async with async_session_maker() as db:
        task = await db.scalar(select(AsyncTask).where(AsyncTask.id == uuid.UUID(task_id)))
        if not task:
            return
        try:
            await update_task(db, task, status="running", progress=10, stage="正在加载简历")
            await db.commit()

            payload = task.input_payload or {}
            resume_id = uuid.UUID(str(payload.get("resume_id")))
            jd_text = str(payload.get("jd_text") or "")
            resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == task.user_id))
            if not resume:
                raise RuntimeError("简历不存在")

            await update_task(db, task, progress=25, stage="正在检索简历证据")
            await db.commit()
            result_payload = await _adapt_resume_to_jd(db, resume, jd_text, source_task_id=task.id)
            await update_task(db, task, progress=90, stage="正在保存优化版本")
            await db.flush()

            response = result_payload["response"]
            record_usage(
                db,
                task.user_id,
                "jd_adapt",
                organization_id=resume.organization_id,
                metadata={
                    "resume_id": str(resume.id),
                    "jd_length": len(jd_text),
                    "async_task_id": str(task.id),
                    **result_payload["llm_metadata"],
                },
            )
            await update_task(
                db,
                task,
                status="success",
                progress=100,
                stage="JD 优化完成",
                result_payload={
                    "resume_id": str(resume.id),
                    "match_score": float(resume.match_score or 0),
                    "version_id": result_payload.get("version_id"),
                    "ats_report": result_payload["ats_report"],
                    "resume_evidence": response.get("resume_evidence", []),
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
                    stage="JD 优化失败",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                await db.commit()


@router.post("/{resume_id}/adapt-jd-task", response_model=ResumeAdaptJDTaskResponse)
async def adapt_jd_task(
    resume_id: uuid.UUID,
    req: ResumeAdaptJDRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _enqueue_resume_adapt_jd_task(
        resume_id,
        req.jd_text,
        request,
        background_tasks,
        db,
        current_user,
    )


@router.post("/{resume_id}/save-optimized", response_model=ResumeResponse)
async def save_optimized(
    resume_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    # 这里只是确认保存，实际优化结果已在 optimize/adapt-jd 时保存
    # 如果需要，可扩展为保存为新版本
    log_audit_event(
        db,
        event_type="resume.save_optimized",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
    )
    await db.commit()
    await db.refresh(resume)
    return resume
