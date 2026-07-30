import hashlib
import hmac

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, BillingAccount, Interview, InterviewQuestion, Organization, OrganizationMember, PaymentOrder, QualityAnnotation, QualityEvalCandidate, Resume, UsageRecord, User
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.resume_index import delete_resume_vectors
from app.utils.storage import delete_uploaded_file
from app.utils.time import utc_now

router = APIRouter(prefix="/api/account", tags=["account"])
settings = get_settings()


def _dt(value):
    return value.isoformat() if value else None


def _anonymized_user_hash(user_id) -> str:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), str(user_id).encode("utf-8"), hashlib.sha256).hexdigest()[:20]


@router.get("/export")
async def export_account_data(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    billing = await db.scalar(select(BillingAccount).where(BillingAccount.user_id == current_user.id))
    resumes = (await db.execute(select(Resume).where(Resume.user_id == current_user.id))).scalars().all()
    interviews = (await db.execute(select(Interview).where(Interview.user_id == current_user.id))).scalars().all()
    usage_records = (await db.execute(select(UsageRecord).where(UsageRecord.user_id == current_user.id))).scalars().all()
    payment_orders = (await db.execute(select(PaymentOrder).where(PaymentOrder.user_id == current_user.id))).scalars().all()
    quality_annotations = (
        await db.execute(select(QualityAnnotation).where(QualityAnnotation.user_id == current_user.id))
    ).scalars().all()
    quality_eval_candidates = (
        await db.execute(select(QualityEvalCandidate).where(QualityEvalCandidate.user_id == current_user.id))
    ).scalars().all()
    organizations = (
        await db.execute(
            select(Organization, OrganizationMember)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == current_user.id)
            .order_by(Organization.created_at.asc())
        )
    ).all()
    audit_logs = (
        await db.execute(
            select(AuditLog)
            .where(or_(AuditLog.actor_user_id == current_user.id, AuditLog.target_user_id == current_user.id))
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()

    interview_payload = []
    for interview in interviews:
        questions = (
            await db.execute(
                select(InterviewQuestion)
                .where(InterviewQuestion.interview_id == interview.id)
                .order_by(InterviewQuestion.sequence)
            )
        ).scalars().all()
        interview_payload.append(
            {
                "id": str(interview.id),
                "resume_id": str(interview.resume_id) if interview.resume_id else None,
                "jd_text": interview.jd_text,
                "status": interview.status,
                "total_score": float(interview.total_score) if interview.total_score is not None else None,
                "dimension_scores": interview.dimension_scores,
                "summary": interview.summary,
                "weak_points": interview.weak_points,
                "suggestions": interview.suggestions,
                "created_at": _dt(interview.created_at),
                "updated_at": _dt(interview.updated_at),
                "questions": [
                    {
                        "id": str(question.id),
                        "resume_point_id": question.resume_point_id,
                        "point_title": question.point_title,
                        "sequence": question.sequence,
                        "question": question.question,
                        "user_answer": question.user_answer,
                        "scores": question.scores,
                        "total_score": float(question.total_score) if question.total_score is not None else None,
                        "feedback": question.feedback,
                        "refined_answer": question.refined_answer,
                        "answered_at": _dt(question.answered_at),
                        "created_at": _dt(question.created_at),
                    }
                    for question in questions
                ],
            }
        )

    payload = {
        "exported_at": _dt(utc_now()),
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "nickname": current_user.nickname,
            "created_at": _dt(current_user.created_at),
            "updated_at": _dt(current_user.updated_at),
        },
        "billing_account": None
        if not billing
        else {
            "plan": billing.plan,
            "status": billing.status,
            "source": billing.source,
            "expires_at": _dt(billing.expires_at),
            "notes": billing.notes,
            "created_at": _dt(billing.created_at),
            "updated_at": _dt(billing.updated_at),
        },
        "resumes": [
            {
                "id": str(resume.id),
                "organization_id": str(resume.organization_id) if resume.organization_id else None,
                "title": resume.title,
                "original_file": resume.original_file,
                "original_text": resume.original_text,
                "parsed_data": resume.parsed_data,
                "optimized_data": resume.optimized_data,
                "jd_text": resume.jd_text,
                "match_score": float(resume.match_score) if resume.match_score is not None else None,
                "template_id": resume.template_id,
                "is_default": resume.is_default,
                "created_at": _dt(resume.created_at),
                "updated_at": _dt(resume.updated_at),
            }
            for resume in resumes
        ],
        "interviews": interview_payload,
        "usage_records": [
            {
                "id": str(record.id),
                "feature": record.feature,
                "units": record.units,
                "metadata": record.record_metadata,
                "created_at": _dt(record.created_at),
            }
            for record in usage_records
        ],
        "organizations": [
            {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "status": org.status,
                "role": member.role,
                "created_at": _dt(org.created_at),
            }
            for org, member in organizations
        ],
        "payment_orders": [
            {
                "id": str(order.id),
                "organization_id": str(order.organization_id) if order.organization_id else None,
                "provider": order.provider,
                "provider_order_id": order.provider_order_id,
                "plan": order.plan,
                "billing_cycle": order.billing_cycle,
                "amount_cny": order.amount_cny,
                "currency": order.currency,
                "status": order.status,
                "checkout_url": order.checkout_url,
                "created_at": _dt(order.created_at),
                "paid_at": _dt(order.paid_at),
            }
            for order in payment_orders
        ],
        "quality_annotations": [
            {
                "id": str(annotation.id),
                "target_type": annotation.target_type,
                "target_id": annotation.target_id,
                "score": annotation.score,
                "labels": annotation.labels,
                "notes": annotation.notes,
                "status": annotation.status,
                "reviewer_role": annotation.reviewer_role,
                "metadata": annotation.annotation_metadata,
                "created_at": _dt(annotation.created_at),
                "updated_at": _dt(annotation.updated_at),
            }
            for annotation in quality_annotations
        ],
        "quality_eval_candidates": [
            {
                "id": str(candidate.id),
                "annotation_id": str(candidate.annotation_id) if candidate.annotation_id else None,
                "target_type": candidate.target_type,
                "target_id": candidate.target_id,
                "source_score": candidate.source_score,
                "priority": candidate.priority,
                "labels": candidate.labels,
                "issue_summary": candidate.issue_summary,
                "status": candidate.status,
                "metadata": candidate.candidate_metadata,
                "created_at": _dt(candidate.created_at),
                "updated_at": _dt(candidate.updated_at),
            }
            for candidate in quality_eval_candidates
        ],
        "audit_logs": [
            {
                "id": str(record.id),
                "event_type": record.event_type,
                "resource_type": record.resource_type,
                "resource_id": record.resource_id,
                "metadata": record.event_metadata,
                "created_at": _dt(record.created_at),
            }
            for record in audit_logs
        ],
    }
    log_audit_event(
        db,
        event_type="account.export",
        resource_type="account",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        resource_id=str(current_user.id),
        request=request,
        metadata={"resume_count": len(resumes), "interview_count": len(interviews)},
    )
    await db.commit()
    return payload


@router.delete("/delete")
async def delete_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resumes = (await db.execute(select(Resume).where(Resume.user_id == current_user.id))).scalars().all()
    resume_files = [resume.original_file for resume in resumes]

    anonymized_user = _anonymized_user_hash(current_user.id)
    await db.execute(
        update(AuditLog)
        .where(AuditLog.actor_user_id == current_user.id)
        .values(actor_user_id=None, resource_id=None, ip_address=None, user_agent=None, event_metadata={})
    )
    await db.execute(
        update(AuditLog)
        .where(AuditLog.target_user_id == current_user.id)
        .values(target_user_id=None, resource_id=None, ip_address=None, user_agent=None, event_metadata={})
    )
    log_audit_event(
        db,
        event_type="account.delete",
        resource_type="account",
        metadata={"anonymized_user": anonymized_user},
    )
    await db.delete(current_user)
    await db.commit()

    for resume in resumes:
        await delete_resume_vectors(current_user.id, resume.id)

    for file_path in resume_files:
        delete_uploaded_file(file_path)

    return {"message": "账号及关联数据已删除"}
