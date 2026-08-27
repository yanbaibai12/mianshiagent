"""Read-only readiness audit for the Phase 1B personal-ownership data contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Table

from app.models import Base

AUDIT_SCHEMA_VERSION = "1.0"
PHASE = "phase-1b-historical-data-contract"
RETIRED_DATA_TABLES = (
    "billing_accounts",
    "payment_orders",
    "quality_annotations",
    "quality_eval_candidates",
    "company_interview_profiles",
)


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


async def _scalar_count(session: AsyncSession, statement: Any) -> int:
    value = await session.scalar(statement)
    return int(value or 0)


async def _table_counts(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in sorted(Base.metadata.tables):
        table = _table(name)
        counts[name] = await _scalar_count(session, select(func.count()).select_from(table))
    return counts


async def _foreign_key_orphans(session: AsyncSession) -> dict[str, int]:
    findings: dict[str, int] = {}
    for table_name in sorted(Base.metadata.tables):
        table = _table(table_name)
        for foreign_key in sorted(table.foreign_keys, key=lambda item: (item.parent.name, item.target_fullname)):
            child_column = foreign_key.parent
            parent_column = foreign_key.column
            parent_source = parent_column.table
            parent_reference = parent_column
            if parent_column.table is table:
                parent_source = parent_column.table.alias(f"{table_name}_{child_column.name}_parent")
                parent_reference = parent_source.c[parent_column.name]
            parent_exists = exists(
                select(1).select_from(parent_source).where(parent_reference == child_column)
            ).correlate(table)
            count = await _scalar_count(
                session,
                select(func.count()).select_from(table).where(child_column.is_not(None), ~parent_exists),
            )
            findings[f"{table_name}.{child_column.name}->{foreign_key.target_fullname}"] = count
    return findings


async def _ownership_mapping(session: AsyncSession) -> dict[str, dict[str, int]]:
    memberships = _table("organization_members")
    findings: dict[str, dict[str, int]] = {}
    for table_name in sorted(Base.metadata.tables):
        table = _table(table_name)
        if table_name == "organization_members" or "user_id" not in table.c or "organization_id" not in table.c:
            continue
        active_membership_exists = exists(
            select(1)
            .select_from(memberships)
            .where(
                memberships.c.user_id == table.c.user_id,
                memberships.c.organization_id == table.c.organization_id,
                memberships.c.status == "active",
            )
        ).correlate(table)
        findings[table_name] = {
            "rows": await _scalar_count(session, select(func.count()).select_from(table)),
            "null_organization_id": await _scalar_count(
                session,
                select(func.count()).select_from(table).where(table.c.organization_id.is_(None)),
            ),
            "active_membership_mismatch": await _scalar_count(
                session,
                select(func.count())
                .select_from(table)
                .where(table.c.organization_id.is_not(None), ~active_membership_exists),
            ),
        }
    return findings


async def _organization_readiness(session: AsyncSession) -> dict[str, int]:
    users = _table("users")
    organizations = _table("organizations")
    memberships = _table("organization_members")

    active_org_counts = (
        select(
            memberships.c.user_id.label("user_id"),
            func.count(distinct(memberships.c.organization_id)).label("organization_count"),
        )
        .where(memberships.c.status == "active")
        .group_by(memberships.c.user_id)
        .subquery()
    )
    active_member_counts = (
        select(
            memberships.c.organization_id.label("organization_id"),
            func.count(distinct(memberships.c.user_id)).label("member_count"),
        )
        .where(memberships.c.status == "active")
        .group_by(memberships.c.organization_id)
        .subquery()
    )
    active_owner_counts = (
        select(
            memberships.c.organization_id.label("organization_id"),
            func.count(distinct(memberships.c.user_id)).label("owner_count"),
        )
        .where(memberships.c.status == "active", memberships.c.role == "owner")
        .group_by(memberships.c.organization_id)
        .subquery()
    )

    organizations_without_owner = await _scalar_count(
        session,
        select(func.count())
        .select_from(
            organizations.outerjoin(
                active_owner_counts,
                organizations.c.id == active_owner_counts.c.organization_id,
            )
        )
        .where(active_owner_counts.c.owner_count.is_(None)),
    )
    organizations_with_multiple_owners = await _scalar_count(
        session,
        select(func.count()).select_from(active_owner_counts).where(active_owner_counts.c.owner_count > 1),
    )
    return {
        "users_without_active_organization": await _scalar_count(
            session,
            select(func.count())
            .select_from(users.outerjoin(active_org_counts, users.c.id == active_org_counts.c.user_id))
            .where(active_org_counts.c.organization_count.is_(None)),
        ),
        "users_with_multiple_active_organizations": await _scalar_count(
            session,
            select(func.count()).select_from(active_org_counts).where(active_org_counts.c.organization_count > 1),
        ),
        "organizations_without_active_member": await _scalar_count(
            session,
            select(func.count())
            .select_from(
                organizations.outerjoin(
                    active_member_counts,
                    organizations.c.id == active_member_counts.c.organization_id,
                )
            )
            .where(active_member_counts.c.member_count.is_(None)),
        ),
        "organizations_with_multiple_active_members": await _scalar_count(
            session,
            select(func.count()).select_from(active_member_counts).where(active_member_counts.c.member_count > 1),
        ),
        "organizations_without_exactly_one_active_owner": (
            organizations_without_owner + organizations_with_multiple_owners
        ),
    }


async def _company_profile_readiness(session: AsyncSession) -> dict[str, int]:
    profiles = _table("company_interview_profiles")
    memberships = _table("organization_members")
    active_member_counts = (
        select(
            memberships.c.organization_id.label("organization_id"),
            func.count(distinct(memberships.c.user_id)).label("member_count"),
        )
        .where(memberships.c.status == "active")
        .group_by(memberships.c.organization_id)
        .subquery()
    )
    ambiguous = await _scalar_count(
        session,
        select(func.count())
        .select_from(
            profiles.outerjoin(
                active_member_counts,
                profiles.c.organization_id == active_member_counts.c.organization_id,
            )
        )
        .where(
            profiles.c.organization_id.is_(None)
            | active_member_counts.c.member_count.is_(None)
            | (active_member_counts.c.member_count != 1)
        ),
    )
    return {
        "rows": await _scalar_count(session, select(func.count()).select_from(profiles)),
        "ambiguous_owner_mapping": ambiguous,
    }


async def _cross_entity_owner_mismatches(session: AsyncSession) -> dict[str, int]:
    tables = {name: _table(name) for name in Base.metadata.tables}
    relation_checks = (
        ("resume_chunks.resume", "resume_chunks", "resume_id", "resumes"),
        ("resume_versions.resume", "resume_versions", "resume_id", "resumes"),
        ("resume_versions.source_task", "resume_versions", "source_task_id", "async_tasks"),
        ("resume_versions.source_job", "resume_versions", "source_job_id", "job_applications"),
        ("resume_versions.parent_version", "resume_versions", "parent_version_id", "resume_versions"),
        ("interviews.resume", "interviews", "resume_id", "resumes"),
        ("job_applications.resume", "job_applications", "resume_id", "resumes"),
        ("job_applications.current_resume_version", "job_applications", "current_resume_version_id", "resume_versions"),
        ("job_applications.interview", "job_applications", "interview_id", "interviews"),
        ("training_plans.source_interview", "training_plans", "source_interview_id", "interviews"),
        (
            "quality_eval_candidates.annotation",
            "quality_eval_candidates",
            "annotation_id",
            "quality_annotations",
        ),
    )
    findings: dict[str, int] = {}
    for check_id, child_name, reference_name, parent_name in relation_checks:
        child = tables[child_name]
        parent = tables[parent_name]
        child_reference = child.c[reference_name]
        parent_source = parent.alias(f"{parent_name}_{reference_name}") if child is parent else parent
        ownership_mismatch = child.c.user_id != parent_source.c.user_id
        if "organization_id" in child.c and "organization_id" in parent_source.c:
            ownership_mismatch = ownership_mismatch | (
                child.c.organization_id.is_not(None)
                & parent_source.c.organization_id.is_not(None)
                & (child.c.organization_id != parent_source.c.organization_id)
            )
        findings[check_id] = await _scalar_count(
            session,
            select(func.count())
            .select_from(child.join(parent_source, child_reference == parent_source.c.id))
            .where(child_reference.is_not(None), ownership_mismatch),
        )

    interviews = tables["interviews"]
    profiles = tables["company_interview_profiles"]
    findings["interviews.company_profile"] = await _scalar_count(
        session,
        select(func.count())
        .select_from(interviews.join(profiles, interviews.c.company_profile_id == profiles.c.id))
        .where(
            interviews.c.company_profile_id.is_not(None),
            interviews.c.organization_id.is_not(None),
            profiles.c.organization_id.is_not(None),
            interviews.c.organization_id != profiles.c.organization_id,
        ),
    )

    tasks = tables["training_plan_tasks"]
    plans = tables["training_plans"]
    task_relations = (
        ("training_plan_tasks.related_interview", "related_interview_id", tables["interviews"], True),
        (
            "training_plan_tasks.related_experience",
            "related_experience_id",
            tables["interview_experience_shares"],
            True,
        ),
        (
            "training_plan_tasks.related_company_profile",
            "related_company_profile_id",
            profiles,
            False,
        ),
    )
    for check_id, reference_name, related, compare_user in task_relations:
        task_reference = tasks.c[reference_name]
        ownership_mismatch = (
            plans.c.organization_id.is_not(None)
            & related.c.organization_id.is_not(None)
            & (plans.c.organization_id != related.c.organization_id)
        )
        if compare_user:
            ownership_mismatch = ownership_mismatch | (plans.c.user_id != related.c.user_id)
        findings[check_id] = await _scalar_count(
            session,
            select(func.count())
            .select_from(tasks.join(plans, tasks.c.plan_id == plans.c.id).join(related, task_reference == related.c.id))
            .where(task_reference.is_not(None), ownership_mismatch),
        )
    return findings


def _blockers(
    *,
    foreign_key_orphans: dict[str, int],
    ownership_mapping: dict[str, dict[str, int]],
    organization_readiness: dict[str, int],
    company_profile_readiness: dict[str, int],
    cross_entity_owner_mismatches: dict[str, int],
) -> list[dict[str, Any]]:
    orphan_count = sum(foreign_key_orphans.values())
    membership_mismatch_count = sum(item["active_membership_mismatch"] for item in ownership_mapping.values())
    cross_entity_mismatch_count = sum(cross_entity_owner_mismatches.values())
    candidates = [
        ("foreign-key-orphans", orphan_count, "外键孤儿记录必须在迁移前修复或分类。"),
        (
            "organization-membership-mismatches",
            membership_mismatch_count,
            "用户资产的 organization_id 必须对应同一用户的有效成员关系。",
        ),
        (
            "users-without-single-active-organization",
            organization_readiness["users_without_active_organization"]
            + organization_readiness["users_with_multiple_active_organizations"],
            "个人所有权收缩要求每个用户恰好映射一个有效组织。",
        ),
        (
            "organizations-without-single-active-member",
            organization_readiness["organizations_without_active_member"]
            + organization_readiness["organizations_with_multiple_active_members"],
            "公司画像和历史组织数据迁移前，每个组织必须能唯一映射到一个用户。",
        ),
        (
            "organizations-without-single-active-owner",
            organization_readiness["organizations_without_exactly_one_active_owner"],
            "每个历史组织必须有且仅有一个有效 owner，才能形成可审计迁移决策。",
        ),
        (
            "company-profile-owner-ambiguity",
            company_profile_readiness["ambiguous_owner_mapping"],
            "历史公司画像必须能够唯一映射到一个用户或被合规归档。",
        ),
        (
            "cross-entity-owner-mismatches",
            cross_entity_mismatch_count,
            "父子业务实体的 user_id 与 organization_id 必须保持一致。",
        ),
    ]
    return [
        {"id": blocker_id, "count": count, "description": description}
        for blocker_id, count, description in candidates
        if count
    ]


async def build_phase1b_data_contract_audit(
    session: AsyncSession,
    *,
    database_dialect: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only Phase 1B migration-readiness report."""
    table_counts = await _table_counts(session)
    foreign_key_orphans = await _foreign_key_orphans(session)
    ownership_mapping = await _ownership_mapping(session)
    organization_readiness = await _organization_readiness(session)
    company_profile_readiness = await _company_profile_readiness(session)
    cross_entity_owner_mismatches = await _cross_entity_owner_mismatches(session)
    blockers = _blockers(
        foreign_key_orphans=foreign_key_orphans,
        ownership_mapping=ownership_mapping,
        organization_readiness=organization_readiness,
        company_profile_readiness=company_profile_readiness,
        cross_entity_owner_mismatches=cross_entity_owner_mismatches,
    )
    now = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE,
        "generated_at": now.isoformat(),
        "read_only": True,
        "database_dialect": database_dialect,
        "status": "blocked" if blockers else "passed",
        "migration_readiness": "blocked" if blockers else "ready",
        "table_count": len(table_counts),
        "table_counts": table_counts,
        "retired_data_counts": {name: table_counts[name] for name in RETIRED_DATA_TABLES},
        "foreign_key_orphans": foreign_key_orphans,
        "ownership_mapping": ownership_mapping,
        "organization_readiness": organization_readiness,
        "company_profile_readiness": company_profile_readiness,
        "cross_entity_owner_mismatches": cross_entity_owner_mismatches,
        "blockers": blockers,
    }
