import uuid
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Resume, Interview, InterviewQuestion
from app.schemas import (
    InterviewCreateRequest,
    InterviewResponse,
    InterviewQuestionResponse,
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    InterviewReportResponse,
)
from app.services.auth_service import get_current_user
from app.services.audit import log_audit_event
from app.services.business import ensure_feature_available, record_usage
from app.services.knowledge_base import build_rag_context, compact_json, retrieve_knowledge
from app.services.llm_client import get_llm_client
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.config import get_settings
from app.prompts import GENERATE_QUESTIONS_PROMPT, SCORE_ANSWER_PROMPT, SUMMARIZE_INTERVIEW_PROMPT
from app.utils.time import utc_now

router = APIRouter(prefix="/api/interviews", tags=["interviews"])
settings = get_settings()


def _fallback_point(exp: dict[str, Any]) -> dict[str, str]:
    title = exp.get("name") or exp.get("company") or exp.get("role") or "核心经历"
    description = exp.get("description") or "；".join(exp.get("highlights", [])[:3]) or str(exp)[:260]
    return {"id": f"local-{abs(hash(title))}", "title": title, "description": description}


def _fallback_question_items(point_title: str) -> list[dict[str, str]]:
    subject = point_title or "该经历"
    return [
        {"question_text": f"请介绍一下{subject}的背景、目标，以及你在其中承担的角色。"},
        {"question_text": f"围绕{subject}，你具体做了哪些关键动作或实现步骤？"},
        {"question_text": f"当时为什么选择这个方案？有没有比较过其他方案或做过取舍？"},
        {"question_text": f"推进{subject}时遇到的最大困难是什么？你是如何定位并解决的？"},
        {"question_text": f"{subject}最终取得了什么结果？如果再做一次你会如何优化？"},
    ]


async def _get_resume(resume_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> Resume:
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.post("", response_model=InterviewResponse)
async def create_interview(
    req: InterviewCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await _get_resume(req.resume_id, current_user.id, db)
    org = await resolve_request_organization(request, db, current_user)
    await ensure_feature_available("interview_create", db, current_user.id, settings)
    interview = Interview(
        user_id=current_user.id,
        organization_id=resume.organization_id or org.id,
        resume_id=resume.id,
        jd_text=req.jd_text,
    )
    db.add(interview)
    await db.flush()
    log_audit_event(
        db,
        event_type="interview.create",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"resume_id": str(resume.id), "has_jd": bool(req.jd_text), **tenant_metadata(org)},
    )
    record_usage(db, current_user.id, "interview_create", organization_id=interview.organization_id, metadata={"resume_id": str(resume.id)})
    await db.commit()
    await db.refresh(interview)
    return interview


@router.get("", response_model=list[InterviewResponse])
async def list_interviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.user_id == current_user.id).order_by(Interview.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    return interview


@router.delete("/{interview_id}")
async def delete_interview(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    log_audit_event(
        db,
        event_type="interview.delete",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"status": interview.status},
    )
    await db.delete(interview)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{interview_id}/generate-questions")
async def generate_questions(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    existing_result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    existing_questions = existing_result.scalars().all()
    if existing_questions:
        return {"count": len(existing_questions), "message": "题目已存在"}

    resume = await _get_resume(interview.resume_id, current_user.id, db)
    data = resume.optimized_data or resume.parsed_data or {}

    llm = get_llm_client(settings)
    questions = []
    llm_calls = []

    # 合并工作经历和项目经历
    experiences = list(data.get("experience", [])) + list(data.get("projects", []))
    if not experiences:
        experiences = [
            {
                "name": resume.title,
                "description": (resume.original_text or data.get("summary") or "")[:500],
                "interview_points": [],
            }
        ]

    for exp in experiences:
        points = exp.get("interview_points", []) or [_fallback_point(exp)]
        for point in points:
            rag_snippets = await retrieve_knowledge(
                db,
                f"{point.get('title', '')} {point.get('description', '')} {compact_json(exp, 1200)} {interview.jd_text or ''}",
                categories=["interview_rubric", "job_knowledge"],
                limit=4,
            )
            rag_context = build_rag_context(rag_snippets)
            prompt = GENERATE_QUESTIONS_PROMPT.format(
                point_title=point.get("title", ""),
                point_description=point.get("description", ""),
                experience_context=f"{str(exp)}\n\n{rag_context}",
            )
            messages = [{"role": "user", "content": prompt}]
            started_at = time.monotonic()
            response = await llm.chat_completion_json(messages)
            llm_calls.append(
                llm.build_usage_metadata(
                    messages,
                    response,
                    feature="question_generation",
                    started_at=started_at,
                )["llm"]
            )

            if isinstance(response, list):
                items = response
            else:
                items = response.get("questions", [])

            if len(items) < 5:
                items = (items or []) + _fallback_question_items(point.get("title", ""))[len(items):]

            for item in items[:5]:
                questions.append(
                    InterviewQuestion(
                        interview_id=interview.id,
                        resume_point_id=point.get("id") or f"{exp.get('company', '')}-{point.get('title', '')}",
                        point_title=point.get("title", ""),
                        sequence=len(questions) + 1,
                        question=item.get("question_text") or item.get("question", ""),
                    )
                )

    db.add_all(questions)
    log_audit_event(
        db,
        event_type="interview.generate_questions",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"question_count": len(questions)},
    )
    record_usage(
        db,
        current_user.id,
        "question_generation",
        organization_id=interview.organization_id,
        metadata={
            "interview_id": str(interview.id),
            "question_count": len(questions),
            "llm_calls": llm_calls,
        },
    )
    await db.commit()
    return {"count": len(questions), "message": "题目生成成功"}


@router.get("/{interview_id}/questions", response_model=list[InterviewQuestionResponse])
async def list_questions(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion)
        .where(InterviewQuestion.interview_id == interview.id)
        .order_by(InterviewQuestion.created_at, InterviewQuestion.sequence)
    )
    return result.scalars().all()


@router.post("/{interview_id}/questions/{question_id}/answer", response_model=AnswerSubmitResponse)
async def submit_answer(
    interview_id: uuid.UUID,
    question_id: uuid.UUID,
    req: AnswerSubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion).where(
            InterviewQuestion.id == question_id,
            InterviewQuestion.interview_id == interview.id,
        )
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    resume = await _get_resume(interview.resume_id, current_user.id, db)
    resume_context = str(resume.optimized_data or resume.parsed_data)

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{question.question} {req.answer} {resume_context[:1500]}",
        categories=["interview_rubric", "job_knowledge", "reporting"],
        limit=5,
    )
    rag_context = build_rag_context(rag_snippets)
    prompt = SCORE_ANSWER_PROMPT.format(
        question=question.question,
        answer=req.answer,
        resume_context=f"{resume_context[:4000]}\n\n{rag_context}",
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="评分结果不可用，请稍后重试")
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="answer_score",
        started_at=started_at,
    )

    scores = response.get("scores", {})
    total = response.get("total_score", 0)
    if not total and scores:
        total = sum(scores.values()) / len(scores)

    question.user_answer = req.answer
    question.scores = scores
    question.total_score = float(total)
    question.feedback = response.get("feedback", "")
    question.refined_answer = response.get("refined_answer", "")
    question.answered_at = utc_now()
    log_audit_event(
        db,
        event_type="interview.answer",
        resource_type="interview_question",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(question.id),
        request=request,
        metadata={"interview_id": str(interview.id), "answer_length": len(req.answer), "total_score": total},
    )
    record_usage(
        db,
        current_user.id,
        "answer_score",
        organization_id=interview.organization_id,
        metadata={"interview_id": str(interview.id), "question_id": str(question.id), **llm_metadata},
    )

    await db.commit()
    await db.refresh(question)

    return AnswerSubmitResponse.model_validate(question)


@router.post("/{interview_id}/regenerate-question")
async def regenerate_question(
    interview_id: uuid.UUID,
    request: Request,
    question_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    question_query = select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    if question_id:
        question_query = question_query.where(InterviewQuestion.id == question_id)
    else:
        question_query = question_query.where(InterviewQuestion.user_answer.is_(None)).order_by(InterviewQuestion.created_at)

    result = await db.execute(question_query)
    question = result.scalars().first()
    if not question:
        raise HTTPException(status_code=400, detail="没有可重新生成的问题")
    if question.user_answer:
        raise HTTPException(status_code=400, detail="已作答的问题不能换题，请选择未作答题目")

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        question.point_title or question.question,
        categories=["interview_rubric", "job_knowledge"],
        limit=4,
    )
    prompt = GENERATE_QUESTIONS_PROMPT.format(
        point_title=question.point_title or "该要点",
        point_description="",
        experience_context=build_rag_context(rag_snippets),
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="question_regeneration",
        started_at=started_at,
    )

    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        items = response.get("questions", [])
    else:
        raise HTTPException(status_code=502, detail="换题结果不可用，请稍后重试")

    if items:
        question.question = items[0].get("question_text") or items[0].get("question", question.question)
        log_audit_event(
            db,
            event_type="interview.regenerate_question",
            resource_type="interview_question",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=interview.organization_id,
            resource_id=str(question.id),
            request=request,
            metadata={"interview_id": str(interview.id)},
        )
        record_usage(
            db,
            current_user.id,
            "question_generation",
            organization_id=interview.organization_id,
            metadata={
                "interview_id": str(interview.id),
                "question_id": str(question.id),
                "mode": "regenerate",
                **llm_metadata,
            },
        )
        await db.commit()

    return InterviewQuestionResponse.model_validate(question)


@router.post("/{interview_id}/finish", response_model=InterviewReportResponse)
async def finish_interview(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    questions = result.scalars().all()

    answered = [q for q in questions if q.user_answer]
    if len(answered) < 3:
        raise HTTPException(status_code=400, detail="至少完成 3 道题才能生成报告")

    # 准备总结输入
    qa_records = []
    for q in answered:
        qa_records.append({
            "question": q.question,
            "answer": q.user_answer,
            "scores": q.scores,
            "feedback": q.feedback,
        })

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{compact_json(qa_records, 4000)} {compact_json(interview.jd_text or '', 1000)}",
        categories=["interview_rubric", "reporting", "job_knowledge"],
        limit=6,
    )
    prompt = SUMMARIZE_INTERVIEW_PROMPT.format(
        questions_and_answers=f"{str(qa_records)}\n\n{build_rag_context(rag_snippets)}"
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="面试报告结果不可用，请稍后重试")
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="interview_report",
        started_at=started_at,
    )

    # 计算平均分
    total_scores = {key: [] for key in ["completeness", "logic", "consistency", "conciseness", "depth"]}
    for q in answered:
        if q.scores:
            for key in total_scores:
                if key in q.scores:
                    total_scores[key].append(q.scores[key])

    dimension_scores = {k: round(sum(v) / len(v), 1) if v else 0 for k, v in total_scores.items()}
    avg_total = sum(dimension_scores.values()) / len(dimension_scores) if dimension_scores else 0

    interview.status = "completed"
    interview.total_score = float(response.get("total_score", avg_total * 10))
    interview.dimension_scores = response.get("dimension_scores", dimension_scores)
    interview.summary = response.get("summary", "")
    interview.weak_points = response.get("weak_points", [])
    interview.suggestions = response.get("suggestions", [])
    log_audit_event(
        db,
        event_type="interview.finish",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"answered_count": len(answered), "total_score": interview.total_score},
    )
    record_usage(
        db,
        current_user.id,
        "interview_report",
        organization_id=interview.organization_id,
        metadata={"interview_id": str(interview.id), "answered_count": len(answered), **llm_metadata},
    )

    await db.commit()
    await db.refresh(interview)

    return InterviewReportResponse(
        id=interview.id,
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
        questions=[InterviewQuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{interview_id}/report", response_model=InterviewReportResponse)
async def get_report(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    if interview.status != "completed":
        raise HTTPException(status_code=400, detail="面试尚未结束，请先完成面试")

    result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    questions = result.scalars().all()

    return InterviewReportResponse(
        id=interview.id,
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
        questions=[InterviewQuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{interview_id}/report/export")
async def export_report(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = await get_report(interview_id, db, current_user)
    interview = await db.scalar(select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id))
    await ensure_feature_available("report_export", db, current_user.id, settings)

    lines = [
        f"# 面试总结报告\n",
        f"**总体评分**: {report.total_score}\n",
        f"**分项得分**: {report.dimension_scores}\n",
        f"\n## 表现总结\n\n{report.summary}\n",
        f"\n## 薄弱点\n",
    ]
    for i, point in enumerate(report.weak_points or [], 1):
        lines.append(f"{i}. {point}\n")

    lines.append("\n## 改进建议\n")
    for i, suggestion in enumerate(report.suggestions or [], 1):
        lines.append(f"{i}. {suggestion}\n")

    lines.append("\n## 答题详情\n")
    for q in report.questions:
        lines.append(f"\n### {q.question}\n")
        lines.append(f"**你的回答**: {q.user_answer or '未作答'}\n")
        if q.total_score is not None:
            lines.append(f"**评分**: {q.total_score}\n")
        if q.feedback:
            lines.append(f"**评语**: {q.feedback}\n")
        if q.refined_answer:
            lines.append(f"**精简答案**: {q.refined_answer}\n")

    content = "".join(lines)
    log_audit_event(
        db,
        event_type="interview.report_export",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id if interview else None,
        resource_id=str(interview_id),
        request=request,
        metadata={"filename": f"interview_report_{interview_id}.md"},
    )
    record_usage(
        db,
        current_user.id,
        "report_export",
        organization_id=interview.organization_id if interview else None,
        metadata={"interview_id": str(interview_id)},
    )
    await db.commit()
    return {"filename": f"interview_report_{interview_id}.md", "content": content}
