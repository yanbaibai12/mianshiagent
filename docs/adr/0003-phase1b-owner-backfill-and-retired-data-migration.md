# ADR-0003: Phase 1B ownership backfill and retired-data migration

- Status: Proposed - blocked pending a real PostgreSQL drill
- Date: 2026-08-27
- Owners: Agent Platform Team, Data Owner, Security Owner
- Supersedes: none
- Related: ADR-0002, `PHASE1B_DATA_CONTRACT_AUDIT.md`

## Context

The product surface for payments, organization administration, operations administration and quality feedback has been retired. Persisted records and organization-scoped ownership remain. Contract migration must not infer ownership or silently delete regulated or user-originated data.

A local environment probe on August 27, 2026 found no `psql`, Docker runtime, PostgreSQL service, or configured PostgreSQL audit target. Therefore no real PostgreSQL migration rehearsal has been performed. SQLite runs and PostgreSQL SQL compilation tests are useful unit evidence, but are not PostgreSQL drill evidence.

## Decision

Use an explicit **expand -> migrate -> contract** migration. Contract changes remain prohibited until all gates below are satisfied.

### Expand

1. Add nullable `owner_user_id` to every retained user asset that currently depends on `organization_id` for ownership.
2. Add non-unique indexes concurrently where PostgreSQL supports it.
3. Introduce dual-read comparison and guarded dual-write. The legacy ownership path remains the rollback source of truth during this stage.
4. Emit counters for missing owner, conflicting owner, write divergence and legacy-only reads.
5. Do not drop columns, tables, constraints, or historical records.

### Migrate

1. Build an immutable mapping from a frozen snapshot: organization -> single active member -> single active owner.
2. Quarantine ambiguous mappings. Never choose an owner by creation time, lexical order, or “first row”.
3. Backfill in bounded batches with deterministic ordering, checkpoint rows, idempotency keys and a restart-safe high-water mark.
4. Record for each batch: snapshot id, range, selected count, updated count, unchanged count, quarantined count, checksum, duration and operator.
5. Classify retired data into retain, export, anonymize, legal-hold or delete. Payment records and raw webhook payloads require data-owner and security approval.
6. Re-run ownership, foreign-key, account-export, account-delete and cross-user isolation checks after every batch.

### Contract

A contract migration may be authored only when:

- the Phase 1B audit reports zero blockers on a production-equivalent PostgreSQL snapshot;
- row counts and canonical checksums reconcile before and after backfill;
- every retained row has exactly one valid owner;
- quarantine is empty or has an approved disposition record;
- upgrade, rollback and backup-restore drills pass on PostgreSQL;
- Release coverage is at least 85% and all required CI/security/E2E gates pass;
- Data Owner, Security Owner and Service Owner sign the evidence manifest.

## Verification

Use canonical per-table checksums over stable, non-sensitive columns. Store counts and hashes only; never copy resume text, tokens, emails, phone numbers, payment payloads or database credentials into evidence artifacts.

Required comparisons:

- source rows = backfilled + unchanged + quarantined;
- retained rows before = retained rows after;
- orphan count = 0;
- cross-user ownership mismatch count = 0;
- owner null count = 0 before NOT NULL enforcement;
- account export/delete output matches the approved personal-ownership contract.

## Rollback

During expand and migrate, stop dual-write, switch reads to the legacy path, restore the last verified checkpoint and revert only the affected batch. A contract rollback requires restoring compatible schema and data from the verified backup. Destructive rollback without a tested restore point is forbidden.

## Consequences

The migration is slower and requires explicit ownership decisions, but it is auditable, restart-safe and prevents cross-user data exposure. Harness, MCP, Skills and multi-agent runtime work may be designed, but production implementation remains gated by the Release and Phase 1B evidence requirements defined by the project plan.
