import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TrainingPlan, User
from app.schemas import (
    TrainingPlanGenerateRequest,
    TrainingPlanResponse,
    TrainingPlanTaskUpdateRequest,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.business import record_usage
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.services.training_plans import (
    TrainingPlanError,
    generate_training_plan,
    get_current_plan,
    get_plan,
    normalize_week_start,
    training_plan_generation_lock,
    update_training_task,
)


router = APIRouter(prefix="/api/training-plans", tags=["training-plans"])


def _plan_response(plan: TrainingPlan) -> TrainingPlanResponse:
    return TrainingPlanResponse.model_validate(plan)


@router.post("/generate", response_model=TrainingPlanResponse)
async def generate_plan(
    req: TrainingPlanGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingPlanResponse:
    org = await resolve_request_organization(request, db, current_user)
    week_start = normalize_week_start(req.week_start)
    await db.commit()
    async with training_plan_generation_lock(current_user.id, org.id, week_start):
        try:
            plan, created = await generate_training_plan(
                db,
                user_id=current_user.id,
                organization_id=org.id,
                source_interview_id=req.source_interview_id,
                week_start=week_start,
            )
        except TrainingPlanError as exc:
            raise HTTPException(status_code=404 if "来源面试" in str(exc) else 400, detail=str(exc)) from exc
        log_audit_event(
            db,
            event_type="training_plan.generate",
            resource_type="training_plan",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=org.id,
            resource_id=str(plan.id),
            request=request,
            metadata={
                "created": created,
                "week_start": plan.week_start.isoformat(),
                "task_count": len(plan.tasks),
                "source_interview_id": str(plan.source_interview_id) if plan.source_interview_id else None,
                **tenant_metadata(org),
            },
        )
        if created:
            record_usage(
                db,
                current_user.id,
                "training_plan_generate",
                organization_id=org.id,
                metadata={
                    "plan_id": str(plan.id),
                    "task_count": len(plan.tasks),
                    "estimated_minutes": plan.estimated_minutes,
                },
            )
        await db.commit()
        return _plan_response(plan)


@router.get("/current", response_model=TrainingPlanResponse)
async def current_plan(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingPlanResponse:
    org = await resolve_request_organization(request, db, current_user)
    plan = await get_current_plan(db, user_id=current_user.id, organization_id=org.id)
    if not plan:
        raise HTTPException(status_code=404, detail="本周训练计划尚未生成")
    return _plan_response(plan)


@router.get("/{plan_id}", response_model=TrainingPlanResponse)
async def plan_detail(
    plan_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingPlanResponse:
    org = await resolve_request_organization(request, db, current_user)
    plan = await get_plan(db, plan_id=plan_id, user_id=current_user.id, organization_id=org.id)
    if not plan:
        raise HTTPException(status_code=404, detail="训练计划不存在或无权访问")
    return _plan_response(plan)


@router.patch("/{plan_id}/tasks/{task_id}", response_model=TrainingPlanResponse)
async def update_plan_task(
    plan_id: uuid.UUID,
    task_id: uuid.UUID,
    req: TrainingPlanTaskUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingPlanResponse:
    if req.status is None and req.scheduled_date is None:
        raise HTTPException(status_code=400, detail="至少需要更新任务状态或训练日期")
    org = await resolve_request_organization(request, db, current_user)
    week_start = await db.scalar(
        select(TrainingPlan.week_start).where(
            TrainingPlan.id == plan_id,
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.organization_id == org.id,
        )
    )
    if week_start is None:
        raise HTTPException(status_code=404, detail="训练计划不存在或无权访问")
    await db.commit()
    async with training_plan_generation_lock(current_user.id, org.id, week_start):
        plan = await get_plan(db, plan_id=plan_id, user_id=current_user.id, organization_id=org.id)
        if not plan:
            raise HTTPException(status_code=404, detail="训练计划不存在或无权访问")
        try:
            task = await update_training_task(
                db,
                plan=plan,
                task_id=task_id,
                user_id=current_user.id,
                organization_id=org.id,
                status=req.status,
                scheduled_date=req.scheduled_date,
            )
        except TrainingPlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        log_audit_event(
            db,
            event_type="training_plan.task_update",
            resource_type="training_plan_task",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=org.id,
            resource_id=str(task.id),
            request=request,
            metadata={
                "plan_id": str(plan.id),
                "status": task.status,
                "scheduled_date": task.scheduled_date.isoformat(),
                "target_dimensions": task.target_dimensions or [],
            },
        )
        record_usage(
            db,
            current_user.id,
            "training_plan_task_update",
            organization_id=org.id,
            metadata={
                "plan_id": str(plan.id),
                "task_id": str(task.id),
                "status": task.status,
                "scheduled_date": task.scheduled_date.isoformat(),
                "target_dimensions": task.target_dimensions or [],
            },
        )
        await db.commit()
        refreshed = await get_plan(db, plan_id=plan.id, user_id=current_user.id, organization_id=org.id)
        return _plan_response(refreshed or plan)


@router.post("/{plan_id}/regenerate", response_model=TrainingPlanResponse)
async def regenerate_plan(
    plan_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingPlanResponse:
    org = await resolve_request_organization(request, db, current_user)
    week_start = await db.scalar(
        select(TrainingPlan.week_start).where(
            TrainingPlan.id == plan_id,
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.organization_id == org.id,
        )
    )
    if week_start is None:
        raise HTTPException(status_code=404, detail="训练计划不存在或无权访问")
    await db.commit()
    async with training_plan_generation_lock(current_user.id, org.id, week_start):
        existing = await get_plan(db, plan_id=plan_id, user_id=current_user.id, organization_id=org.id)
        if not existing:
            raise HTTPException(status_code=404, detail="训练计划不存在或无权访问")
        try:
            plan, _ = await generate_training_plan(
                db,
                user_id=current_user.id,
                organization_id=org.id,
                source_interview_id=existing.source_interview_id,
                week_start=existing.week_start,
                force=True,
            )
        except TrainingPlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        log_audit_event(
            db,
            event_type="training_plan.regenerate",
            resource_type="training_plan",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=org.id,
            resource_id=str(plan.id),
            request=request,
            metadata={"task_count": len(plan.tasks), "completion_rate": plan.completion_rate},
        )
        record_usage(
            db,
            current_user.id,
            "training_plan_regenerate",
            organization_id=org.id,
            metadata={"plan_id": str(plan.id), "task_count": len(plan.tasks)},
        )
        await db.commit()
        return _plan_response(plan)
