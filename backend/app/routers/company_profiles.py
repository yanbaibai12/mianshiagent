import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CompanyInterviewProfile, User
from app.schemas import (
    CompanyInterviewProfileListResponse,
    CompanyInterviewProfileResponse,
    CompanyProfileRebuildRequest,
    CompanyProfileRebuildResponse,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user, is_admin_user, require_admin_user
from app.services.company_profiles import (
    normalize_company_name,
    normalize_position_name,
    profile_confidence,
    rebuild_all_profiles,
    visible_profile_condition,
)
from app.services.tenancy import resolve_request_organization, tenant_metadata


router = APIRouter(prefix="/api/company-profiles", tags=["company-profiles"])


def _source_ids(profile: CompanyInterviewProfile) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in profile.source_experience_ids or []:
        try:
            result.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return result


def _profile_response(
    profile: CompanyInterviewProfile,
    *,
    include_sources: bool,
) -> CompanyInterviewProfileResponse:
    return CompanyInterviewProfileResponse(
        id=profile.id,
        organization_id=profile.organization_id,
        scope=profile.scope,
        company_name=profile.company_name,
        normalized_company_name=profile.normalized_company_name,
        position_name=profile.position_name,
        normalized_position_name=profile.normalized_position_name,
        common_rounds=profile.common_rounds or [],
        frequent_questions=profile.frequent_questions or [],
        technical_topics=profile.technical_topics or [],
        difficulty_distribution=profile.difficulty_distribution or {},
        interview_count=int(profile.interview_count or 0),
        source_experience_ids=_source_ids(profile) if include_sources else None,
        profile_confidence=profile_confidence(int(profile.interview_count or 0)),
        first_observed_at=profile.first_observed_at,
        last_observed_at=profile.last_observed_at,
        generated_at=profile.generated_at,
        updated_at=profile.updated_at,
        profile_version=int(profile.profile_version or 1),
    )


@router.get("", response_model=CompanyInterviewProfileListResponse)
async def list_company_profiles(
    request: Request,
    company: str | None = Query(default=None, max_length=160),
    position: str | None = Query(default=None, max_length=200),
    round_type: str | None = Query(default=None, max_length=80),
    topic: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyInterviewProfileListResponse:
    org = await resolve_request_organization(request, db, current_user)
    conditions = [visible_profile_condition(org.id)]
    if company and company.strip():
        normalized = normalize_company_name(company)
        conditions.append(
            or_(
                CompanyInterviewProfile.normalized_company_name.ilike(f"%{normalized}%"),
                CompanyInterviewProfile.company_name.ilike(f"%{company.strip()[:160]}%"),
            )
        )
    if position and position.strip():
        normalized = normalize_position_name(position)
        conditions.append(
            or_(
                CompanyInterviewProfile.normalized_position_name.ilike(f"%{normalized}%"),
                CompanyInterviewProfile.position_name.ilike(f"%{position.strip()[:200]}%"),
            )
        )
    if round_type and round_type.strip():
        conditions.append(cast(CompanyInterviewProfile.common_rounds, String).ilike(f"%{round_type.strip()[:80]}%"))
    if topic and topic.strip():
        conditions.append(cast(CompanyInterviewProfile.technical_topics, String).ilike(f"%{topic.strip()[:80]}%"))

    total = await db.scalar(select(func.count()).select_from(CompanyInterviewProfile).where(*conditions)) or 0
    profiles = (
        await db.execute(
            select(CompanyInterviewProfile)
            .where(*conditions)
            .order_by(CompanyInterviewProfile.interview_count.desc(), CompanyInterviewProfile.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return CompanyInterviewProfileListResponse(
        items=[_profile_response(profile, include_sources=False) for profile in profiles],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post("/rebuild", response_model=CompanyProfileRebuildResponse)
async def rebuild_company_profile_index(
    req: CompanyProfileRebuildRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> CompanyProfileRebuildResponse:
    org = await resolve_request_organization(request, db, current_user)
    profiles = await rebuild_all_profiles(
        db,
        company=req.company,
        position=req.position,
        scope=req.scope,
        organization_id=org.id if req.scope == "organization" else None,
    )
    log_audit_event(
        db,
        event_type="company_profile.rebuild",
        resource_type="company_interview_profile",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        request=request,
        metadata={
            "company": normalize_company_name(req.company) if req.company else None,
            "position": normalize_position_name(req.position) if req.position else None,
            "scope": req.scope or "all",
            "rebuilt_count": len(profiles),
            **tenant_metadata(org),
        },
    )
    await db.commit()
    return CompanyProfileRebuildResponse(
        rebuilt_count=len(profiles),
        profile_ids=[profile.id for profile in profiles],
    )


@router.get("/{profile_id}", response_model=CompanyInterviewProfileResponse)
async def get_company_profile(
    profile_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyInterviewProfileResponse:
    org = await resolve_request_organization(request, db, current_user)
    profile = await db.scalar(
        select(CompanyInterviewProfile).where(
            CompanyInterviewProfile.id == profile_id,
            visible_profile_condition(org.id),
        )
    )
    if not profile:
        raise HTTPException(status_code=404, detail="公司画像不存在或无权访问")
    return _profile_response(profile, include_sources=is_admin_user(current_user))
