import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OrganizationMember, User
from app.schemas import (
    OrganizationCreateRequest,
    OrganizationMemberInviteRequest,
    OrganizationMemberResponse,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.tenancy import (
    create_organization,
    list_user_organizations,
    require_membership,
    require_org_admin_role,
    tenant_metadata,
)

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("")
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"organizations": await list_user_organizations(db, current_user)}


@router.post("")
async def create_org(
    req: OrganizationCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org = await create_organization(db, owner=current_user, name=req.name)
    log_audit_event(
        db,
        event_type="organization.create",
        resource_type="organization",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=str(org.id),
        request=request,
        metadata=tenant_metadata(org),
    )
    await db.commit()
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "plan": org.plan,
        "status": org.status,
        "role": "owner",
        "created_at": org.created_at,
    }


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
async def list_members(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_membership(db, organization_id, current_user)
    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.created_at.asc())
    )
    return [
        OrganizationMemberResponse(
            id=member.id,
            user_id=user.id,
            email=user.email,
            nickname=user.nickname,
            role=member.role,
            status=member.status,
            created_at=member.created_at,
        )
        for member, user in result.all()
    ]


@router.post("/{organization_id}/members", response_model=OrganizationMemberResponse)
async def invite_member(
    organization_id: uuid.UUID,
    req: OrganizationMemberInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    membership = await require_membership(db, organization_id, current_user)
    require_org_admin_role(membership)

    result = await db.execute(select(User).where(User.email == req.email.strip().lower()))
    target = result.scalar_one_or_none()
    if not target:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="用户不存在，请先让对方注册")

    existing = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == target.id,
        )
    )
    if existing:
        existing.role = req.role
        existing.status = "active"
        member = existing
    else:
        member = OrganizationMember(
            organization_id=organization_id,
            user_id=target.id,
            role=req.role,
            status="active",
        )
        db.add(member)
        await db.flush()

    log_audit_event(
        db,
        event_type="organization.member_upsert",
        resource_type="organization_member",
        actor_user_id=current_user.id,
        target_user_id=target.id,
        organization_id=organization_id,
        resource_id=str(member.id),
        request=request,
        metadata={"role": member.role, "target_email": target.email},
    )
    await db.commit()
    return OrganizationMemberResponse(
        id=member.id,
        user_id=target.id,
        email=target.email,
        nickname=target.nickname,
        role=member.role,
        status=member.status,
        created_at=member.created_at,
    )
