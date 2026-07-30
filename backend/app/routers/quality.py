import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import QualityAnnotation, User
from app.schemas import (
    QualityAnnotationCreateRequest,
    QualityAnnotationResponse,
    QualityEvalCandidateResponse,
    QualityEvalCandidateStatusRequest,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user, require_admin_user
from app.services.quality import (
    build_quality_summary,
    clean_quality_labels,
    create_eval_candidate_if_needed,
    list_eval_candidates,
    redact_sensitive_text,
    resolve_quality_target,
    safe_annotation_metadata,
    update_eval_candidate_status,
)

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.post("/annotations", response_model=QualityAnnotationResponse)
async def create_quality_annotation(
    req: QualityAnnotationCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await resolve_quality_target(
        db,
        target_type=req.target_type,
        target_id=req.target_id,
        user_id=current_user.id,
    )
    annotation = QualityAnnotation(
        user_id=current_user.id,
        organization_id=target.get("organization_id"),
        target_type=req.target_type,
        target_id=req.target_id,
        score=req.score,
        labels=clean_quality_labels(req.labels),
        notes=redact_sensitive_text((req.notes or "").strip())[:1000] or None,
        status="open",
        reviewer_role="user",
        annotation_metadata=safe_annotation_metadata(req.metadata),
    )
    db.add(annotation)
    await db.flush()
    candidate = await create_eval_candidate_if_needed(db, annotation)
    log_audit_event(
        db,
        event_type="quality.annotation_create",
        resource_type=target["resource_type"],
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=annotation.organization_id,
        resource_id=target["resource_id"],
        request=request,
        metadata={
            "annotation_id": str(annotation.id),
            "target_type": annotation.target_type,
            "score": annotation.score,
            "labels": annotation.labels or [],
            "eval_candidate_id": str(candidate.id) if candidate else None,
        },
    )
    await db.commit()
    await db.refresh(annotation)
    return annotation


@router.get("/annotations", response_model=list[QualityAnnotationResponse])
async def list_quality_annotations(
    target_type: str | None = Query(default=None, max_length=60),
    target_id: str | None = Query(default=None, max_length=120),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(QualityAnnotation).where(QualityAnnotation.user_id == current_user.id)
    if target_type:
        stmt = stmt.where(QualityAnnotation.target_type == target_type)
    if target_id:
        stmt = stmt.where(QualityAnnotation.target_id == target_id)
    stmt = stmt.order_by(QualityAnnotation.created_at.desc()).limit(50)
    return (await db.execute(stmt)).scalars().all()


@router.get("/admin/summary")
async def admin_quality_summary(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await build_quality_summary(db, limit=limit)


@router.get("/admin/eval-candidates", response_model=list[QualityEvalCandidateResponse])
async def admin_eval_candidates(
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await list_eval_candidates(db, status=status, limit=limit)


@router.post("/admin/eval-candidates/{candidate_id}/status", response_model=QualityEvalCandidateResponse)
async def admin_update_eval_candidate_status(
    candidate_id: uuid.UUID,
    req: QualityEvalCandidateStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    candidate = await update_eval_candidate_status(db, candidate_id=candidate_id, status=req.status)
    log_audit_event(
        db,
        event_type="quality.eval_candidate_status",
        resource_type="quality_eval_candidate",
        actor_user_id=current_user.id,
        target_user_id=candidate.user_id,
        organization_id=candidate.organization_id,
        resource_id=str(candidate.id),
        request=request,
        metadata={"status": candidate.status, "target_type": candidate.target_type, "source_score": candidate.source_score},
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate
