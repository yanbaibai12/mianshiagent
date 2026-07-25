import re
import uuid
from typing import Literal

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, OrganizationMember, User

OrgRole = Literal["owner", "admin", "member"]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "org"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    index = 1
    while await db.scalar(select(Organization.id).where(Organization.slug == candidate)):
        index += 1
        candidate = f"{slug}-{index}"
    return candidate


async def create_organization(
    db: AsyncSession,
    *,
    owner: User,
    name: str,
    role: OrgRole = "owner",
) -> Organization:
    org = Organization(name=name.strip()[:120], slug=await _unique_slug(db, name), plan="free", status="active")
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role=role, status="active"))
    await db.flush()
    return org


async def ensure_personal_organization(db: AsyncSession, user: User) -> Organization:
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
        .order_by(OrganizationMember.created_at.asc())
    )
    org = result.scalars().first()
    if org:
        return org

    display = user.nickname or user.email.split("@", 1)[0]
    return await create_organization(db, owner=user, name=f"{display} 的组织")


async def list_user_organizations(db: AsyncSession, user: User) -> list[dict]:
    await ensure_personal_organization(db, user)
    result = await db.execute(
        select(Organization, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user.id, OrganizationMember.status == "active")
        .order_by(Organization.created_at.asc())
    )
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "plan": org.plan,
            "status": org.status,
            "role": member.role,
            "created_at": org.created_at,
        }
        for org, member in result.all()
    ]


async def get_membership(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationMember | None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def require_membership(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user: User,
) -> OrganizationMember:
    membership = await get_membership(db, organization_id, user.id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该组织")
    return membership


def require_org_admin_role(membership: OrganizationMember) -> None:
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要组织管理员权限")


async def resolve_request_organization(request: Request, db: AsyncSession, user: User) -> Organization:
    raw_org_id = request.headers.get("x-organization-id")
    if raw_org_id:
        try:
            organization_id = uuid.UUID(raw_org_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="X-Organization-Id 格式无效") from exc
        await require_membership(db, organization_id, user)
        org = await db.get(Organization, organization_id)
        if not org or org.status != "active":
            raise HTTPException(status_code=404, detail="组织不存在")
        return org

    return await ensure_personal_organization(db, user)


def tenant_metadata(org: Organization | None) -> dict:
    return {} if not org else {"organization_id": str(org.id), "organization_slug": org.slug}
