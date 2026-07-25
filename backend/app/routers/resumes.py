from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid
import time

from app.database import get_db
from app.models import User, Resume, ResumeTemplate
from app.schemas import (
    ResumeResponse,
    ResumeListItemResponse,
    ResumeCreateRequest,
    ResumeUpdateRequest,
    ResumeOptimizeRequest,
    ResumeAdaptJDRequest,
    ResumeAdaptJDResponse,
)
from app.services.auth_service import get_current_user
from app.services.audit import log_audit_event
from app.services.business import ensure_feature_available, record_usage
from app.services.knowledge_base import (
    build_rag_context,
    compact_json,
    retrieve_knowledge,
    serialize_rag_references,
)
from app.services.resume_parser import ResumeParser
from app.services.llm_client import get_llm_client
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.config import get_settings
from app.prompts import PARSE_RESUME_PROMPT, OPTIMIZE_RESUME_PROMPT, ADAPT_JD_PROMPT
from app.utils.storage import delete_uploaded_file, save_upload_file, is_allowed_file

router = APIRouter(prefix="/api/resumes", tags=["resumes"])
settings = get_settings()


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
            )
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
    await ensure_feature_available("resume_upload", db, current_user.id, settings)

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
            )
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
        parsed_data = await llm.chat_completion_json(messages)
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

    log_audit_event(
        db,
        event_type="resume.update",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"title_changed": req.title is not None, "parsed_changed": req.parsed_data is not None, "optimized_changed": req.optimized_data is not None},
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
    await ensure_feature_available("resume_optimize", db, current_user.id, settings)

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
    optimized_data = await llm.chat_completion_json(messages)
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


@router.post("/{resume_id}/adapt-jd", response_model=ResumeAdaptJDResponse)
async def adapt_jd(
    resume_id: uuid.UUID,
    req: ResumeAdaptJDRequest,
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
    await ensure_feature_available("jd_adapt", db, current_user.id, settings)

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{req.jd_text} {compact_json(resume.optimized_data or resume.parsed_data)}",
        categories=["resume_writing", "job_knowledge"],
        limit=6,
    )
    rag_context = build_rag_context(rag_snippets)
    prompt = ADAPT_JD_PROMPT.format(
        jd_text=f"{req.jd_text}\n\n{rag_context}",
        resume_data=str(resume.optimized_data or resume.parsed_data),
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="JD 适配结果不可用，请稍后重试")
    response["rag_references"] = serialize_rag_references(rag_snippets)
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="jd_adapt",
        started_at=started_at,
    )

    resume.jd_text = req.jd_text
    resume.match_score = float(response.get("match_score", 0))
    if response.get("optimized_resume"):
        resume.optimized_data = response["optimized_resume"]
    log_audit_event(
        db,
        event_type="resume.adapt_jd",
        resource_type="resume",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=resume.organization_id,
        resource_id=str(resume.id),
        request=request,
        metadata={"jd_length": len(req.jd_text), "match_score": response.get("match_score", 0)},
    )
    record_usage(
        db,
        current_user.id,
        "jd_adapt",
        organization_id=resume.organization_id,
        metadata={"resume_id": str(resume.id), "jd_length": len(req.jd_text), **llm_metadata},
    )
    await db.commit()

    return ResumeAdaptJDResponse(
        jd_requirements=response.get("jd_requirements", {}),
        match_score=float(response.get("match_score", 0)),
        weak_points=response.get("weak_points", []),
        optimized_resume=response.get("optimized_resume", {}),
        rag_references=response.get("rag_references", []),
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
