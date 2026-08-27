from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.services.data_contract_audit import build_phase1b_data_contract_audit
from scripts.audit_phase1b_data_contract import _canonical_hash, _redact_database_url, _run


class Phase1BDataContractAuditTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database_path = Path(tempfile.gettempdir()) / f"phase1b_audit_{uuid.uuid4().hex}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.database_path.as_posix()}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.database_path.unlink(missing_ok=True)

    async def _insert(self, table_name: str, **values) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(Base.metadata.tables[table_name].insert().values(**values))

    async def _audit(self):
        async with self.session_factory() as session:
            return await build_phase1b_data_contract_audit(
                session,
                database_dialect="sqlite",
                generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
            )

    async def test_clean_personal_ownership_data_is_ready(self) -> None:
        user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        annotation_id = uuid.uuid4()
        await self._insert(
            "users",
            id=user_id,
            email="owner@example.com",
            password_hash="hash",
        )
        await self._insert(
            "organizations",
            id=organization_id,
            name="Owner Personal",
            slug="owner-personal",
            plan="free",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role="owner",
            status="active",
        )
        await self._insert(
            "resumes",
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=organization_id,
            title="Resume",
        )
        await self._insert(
            "billing_accounts",
            user_id=user_id,
            organization_id=organization_id,
            plan="free",
            status="active",
            source="system",
        )
        await self._insert(
            "payment_orders",
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=organization_id,
            provider="manual",
            plan="free",
            billing_cycle="monthly",
            amount_cny=0,
            currency="CNY",
            status="closed",
        )
        await self._insert(
            "quality_annotations",
            id=annotation_id,
            user_id=user_id,
            organization_id=organization_id,
            target_type="resume",
            target_id="resume-1",
            score=5,
            reviewer_role="user",
            status="archived",
        )
        await self._insert(
            "quality_eval_candidates",
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=organization_id,
            annotation_id=annotation_id,
            target_type="resume",
            target_id="resume-1",
            source_score=5,
            priority=1,
            status="archived",
        )
        await self._insert(
            "company_interview_profiles",
            id=uuid.uuid4(),
            organization_id=organization_id,
            scope="organization",
            scope_key=str(organization_id),
            company_name="Example",
            normalized_company_name="example",
            position_name="Engineer",
            normalized_position_name="engineer",
            interview_count=1,
            profile_version=1,
        )

        report = await self._audit()

        self.assertEqual(report["generated_at"], "2026-08-27T00:00:00+00:00")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["migration_readiness"], "ready")
        self.assertEqual(report["table_count"], 29)
        self.assertEqual(report["retired_data_counts"]["payment_orders"], 1)
        self.assertEqual(report["retired_data_counts"]["quality_annotations"], 1)
        self.assertEqual(report["blockers"], [])
        self.assertTrue(all(count == 0 for count in report["foreign_key_orphans"].values()))

    async def test_orphans_and_membership_mismatches_block_migration(self) -> None:
        owner_id = uuid.uuid4()
        mismatched_user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        await self._insert("users", id=owner_id, email="owner@example.com", password_hash="hash")
        await self._insert("users", id=mismatched_user_id, email="other@example.com", password_hash="hash")
        await self._insert(
            "organizations",
            id=organization_id,
            name="Owner Personal",
            slug="owner-personal",
            plan="free",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=owner_id,
            role="owner",
            status="active",
        )
        await self._insert(
            "resumes",
            id=uuid.uuid4(),
            user_id=mismatched_user_id,
            organization_id=organization_id,
            title="Cross user resume",
        )
        await self._insert(
            "payment_orders",
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            organization_id=organization_id,
            provider="manual",
            plan="free",
            billing_cycle="monthly",
            amount_cny=0,
            currency="CNY",
            status="closed",
        )

        report = await self._audit()
        blocker_ids = {item["id"] for item in report["blockers"]}

        self.assertEqual(report["status"], "blocked")
        self.assertGreater(report["ownership_mapping"]["resumes"]["active_membership_mismatch"], 0)
        self.assertGreater(report["foreign_key_orphans"]["payment_orders.user_id->users.id"], 0)
        self.assertIn("foreign-key-orphans", blocker_ids)
        self.assertIn("organization-membership-mismatches", blocker_ids)
        self.assertIn("users-without-single-active-organization", blocker_ids)

    async def test_shared_organization_and_ambiguous_profile_block_personal_contract(self) -> None:
        first_user_id = uuid.uuid4()
        second_user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        for user_id, email in (
            (first_user_id, "first@example.com"),
            (second_user_id, "second@example.com"),
        ):
            await self._insert("users", id=user_id, email=email, password_hash="hash")
        await self._insert(
            "organizations",
            id=organization_id,
            name="Shared",
            slug="shared",
            plan="free",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=first_user_id,
            role="owner",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=second_user_id,
            role="member",
            status="active",
        )
        await self._insert(
            "company_interview_profiles",
            id=uuid.uuid4(),
            organization_id=organization_id,
            scope="organization",
            scope_key=str(organization_id),
            company_name="Shared Company",
            normalized_company_name="shared-company",
            position_name="Engineer",
            normalized_position_name="engineer",
            interview_count=2,
            profile_version=1,
        )

        report = await self._audit()
        blocker_ids = {item["id"] for item in report["blockers"]}

        self.assertEqual(report["organization_readiness"]["organizations_with_multiple_active_members"], 1)
        self.assertEqual(report["company_profile_readiness"]["ambiguous_owner_mapping"], 1)
        self.assertIn("organizations-without-single-active-member", blocker_ids)
        self.assertIn("company-profile-owner-ambiguity", blocker_ids)

    async def test_parent_child_owner_mismatch_is_detected(self) -> None:
        owner_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        resume_id = uuid.uuid4()
        for user_id, email in ((owner_id, "owner@example.com"), (other_user_id, "other@example.com")):
            await self._insert("users", id=user_id, email=email, password_hash="hash")
        await self._insert(
            "organizations",
            id=organization_id,
            name="Personal",
            slug="personal",
            plan="free",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=owner_id,
            role="owner",
            status="active",
        )
        await self._insert(
            "resumes",
            id=resume_id,
            user_id=owner_id,
            organization_id=organization_id,
            title="Owner resume",
        )
        await self._insert(
            "resume_chunks",
            id=uuid.uuid4(),
            resume_id=resume_id,
            user_id=other_user_id,
            organization_id=organization_id,
            section="project",
            item_title="Mismatch",
            chunk_index=1,
            content="content",
            source_hash="hash",
            embedding_status="pending",
        )

        report = await self._audit()

        self.assertEqual(report["cross_entity_owner_mismatches"]["resume_chunks.resume"], 1)
        self.assertTrue(any(item["id"] == "cross-entity-owner-mismatches" for item in report["blockers"]))

    async def test_self_referencing_foreign_key_distinguishes_valid_parent_from_orphan(self) -> None:
        user_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        resume_id = uuid.uuid4()
        parent_version_id = uuid.uuid4()
        await self._insert("users", id=user_id, email="version-owner@example.com", password_hash="hash")
        await self._insert(
            "organizations",
            id=organization_id,
            name="Version Owner",
            slug="version-owner",
            plan="free",
            status="active",
        )
        await self._insert(
            "organization_members",
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role="owner",
            status="active",
        )
        await self._insert(
            "resumes",
            id=resume_id,
            user_id=user_id,
            organization_id=organization_id,
            title="Versioned resume",
        )
        await self._insert(
            "resume_versions",
            id=parent_version_id,
            resume_id=resume_id,
            user_id=user_id,
            organization_id=organization_id,
            version_number=1,
            version_type="original",
            title="Parent",
            data={},
        )
        await self._insert(
            "resume_versions",
            id=uuid.uuid4(),
            resume_id=resume_id,
            user_id=user_id,
            organization_id=organization_id,
            version_number=2,
            version_type="rewrite",
            title="Valid child",
            data={},
            parent_version_id=parent_version_id,
        )
        await self._insert(
            "resume_versions",
            id=uuid.uuid4(),
            resume_id=resume_id,
            user_id=user_id,
            organization_id=organization_id,
            version_number=3,
            version_type="rewrite",
            title="Orphan child",
            data={},
            parent_version_id=uuid.uuid4(),
        )

        report = await self._audit()

        self.assertEqual(
            report["foreign_key_orphans"]["resume_versions.parent_version_id->resume_versions.id"],
            1,
        )
        self.assertEqual(report["cross_entity_owner_mismatches"]["resume_versions.parent_version"], 0)

    async def test_cli_runner_adds_schema_inventory_and_verifiable_evidence_hash(self) -> None:
        report = await _run(f"sqlite+aiosqlite:///{self.database_path.as_posix()}")

        evidence_hash = report.pop("evidence_sha256")
        self.assertEqual(report["expected_table_count"], 29)
        self.assertEqual(report["unexpected_tables"], [])
        self.assertEqual(evidence_hash, _canonical_hash(report))

    async def test_all_audit_queries_compile_for_postgresql(self) -> None:
        class CompilingSession:
            async def scalar(self, statement):
                statement.compile(dialect=postgresql.dialect())
                return 0

        report = await build_phase1b_data_contract_audit(
            cast(AsyncSession, CompilingSession()),
            database_dialect="postgresql",
            generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        )

        self.assertEqual(report["database_dialect"], "postgresql")
        self.assertEqual(report["status"], "passed")

    def test_cli_failure_evidence_redacts_database_url(self) -> None:
        database_url = "postgresql+asyncpg://audit_user:secret@db.example.test/app?ssl=require"
        rendered_url = "postgresql+asyncpg://audit_user:***@db.example.test/app?ssl=require"
        message = f"Could not connect to {database_url}; normalized as {rendered_url}"

        sanitized = _redact_database_url(message, database_url)

        self.assertNotIn(database_url, sanitized)
        self.assertNotIn(rendered_url, sanitized)
        self.assertNotIn("secret", sanitized)
        self.assertEqual(sanitized.count("<redacted-database-url>"), 2)

    async def test_cli_runner_fails_closed_when_schema_is_incomplete(self) -> None:
        incomplete_path = Path(tempfile.gettempdir()) / f"phase1b_incomplete_{uuid.uuid4().hex}.db"
        try:
            with self.assertRaisesRegex(RuntimeError, "missing expected tables"):
                await _run(f"sqlite+aiosqlite:///{incomplete_path.as_posix()}")
        finally:
            incomplete_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
