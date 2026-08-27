# Phase 1B PostgreSQL drill runbook

Version: 1.0.0
Status: BLOCKED on August 27, 2026 - no PostgreSQL runtime or audit target is available on this workstation.
Evidence: `artifacts/data-contract/postgresql-environment-probe.json`

## 1. Purpose and non-negotiable rules

This runbook validates ownership backfill and retired-data handling on a production-equivalent PostgreSQL database. SQLite, mocked sessions, generated SQL, and PostgreSQL dialect compilation must never be reported as a successful drill.

- Use a disposable staging clone or read-only snapshot for audit.
- Never use production superuser credentials.
- Never write secrets or personal content to reports.
- Stop immediately on schema drift, blocker count greater than zero, reconciliation mismatch, unexpected lock growth or missing rollback evidence.

## 2. Roles

| Role | Responsibility |
|---|---|
| Drill lead | coordinates timeline, evidence and stop decisions |
| Database owner | snapshot, restore point, lock/replication monitoring |
| Data owner | retired-data classification and quarantine decisions |
| Security owner | credential scope, redaction and isolation review |
| Service owner | application validation and rollback switch |
| Independent reviewer | verifies commands, hashes and final decision |

No individual may both execute and independently approve the drill.

## 3. Preconditions

1. PostgreSQL major version matches production.
2. Alembic is at the expected single head.
3. Snapshot id, Git commit, migration revision and operator identities are recorded.
4. Backup restore has been tested before any write rehearsal.
5. Audit credentials have only CONNECT, schema USAGE and required SELECT grants.
6. Write rehearsal credentials are time-limited and restricted to the staging clone.
7. Release backend coverage is at least 85%.
8. Maintenance window, stop thresholds and communication channel are approved.

## 4. Read-only audit

```powershell
cd backend
.\.venv-codex\Scripts\python.exe scripts\audit_phase1b_data_contract.py `
  --database-url "postgresql+asyncpg://<readonly-user>@<staging-host>/<database>" `
  --report artifacts\data-contract\phase1b-postgresql-audit.json
```

Expected result: exit code 0, `database_dialect=postgresql`, `read_only=true`, zero blockers, and an evidence SHA-256. `--report-only` output is exploratory and cannot approve migration.

## 5. Expand rehearsal

1. Apply expand revision with `alembic upgrade <expand-revision>`.
2. Record migration duration and lock waits.
3. Verify new columns are nullable and indexed; no old contract is removed.
4. Run application smoke, account export/delete, authorization and cross-user isolation tests.
5. Verify dual-read comparison metrics and dual-write divergence are zero.

## 6. Backfill rehearsal

Use deterministic primary-key ordering. Recommended batch size starts at 1,000 and must be reduced if lock or replication thresholds are exceeded.

For every batch:

1. acquire an idempotency key for snapshot + table + range;
2. select source rows and compute a non-sensitive canonical checksum;
3. update only rows with a uniquely proven owner;
4. quarantine ambiguous rows with a reason code, never guessed ownership;
5. commit the batch and checkpoint;
6. recompute count/checksum and compare;
7. monitor lock wait, statement duration, error rate and replication lag;
8. stop on any mismatch.

## 7. Retired-data disposition

Produce an approved manifest for payment, organization, quality feedback and company-profile history. Each dataset must have one disposition: retain, user export, anonymize, legal hold or delete. Deletion requires retention-policy evidence, backup expiry rules and dual approval. Raw payment/webhook data must not be copied into general artifacts.

## 8. Contract gate

Do not apply a contract revision unless every ADR-0003 gate passes. Before NOT NULL, foreign-key or table removal, run:

- null owner count;
- orphan count;
- cross-user mismatch count;
- row-count and checksum reconciliation;
- account export/delete checks;
- authorization and tenant-isolation tests;
- backup restore and application rollback rehearsal.

## 9. Rollback drill

1. Stop migration workers and disable dual-write.
2. Switch reads to the legacy ownership path.
3. Roll back the active batch from its checkpoint or restore the verified snapshot.
4. Run audit and reconciliation again.
5. Confirm application health, isolation and account lifecycle.
6. Record recovery time and data-loss objective; any unexplained mismatch fails the drill.

## 10. Evidence manifest

Archive only sanitized evidence:

- environment and PostgreSQL version;
- snapshot id and Alembic revisions;
- Git commit and dirty-worktree hash;
- command names and exit codes;
- batch counts, checksums, timing and stop events;
- test/quality-gate report hashes;
- approvals and unresolved risks.

Current workstation result on August 27, 2026: **BLOCKED**. A real PostgreSQL target must be supplied before this runbook can produce approval evidence.
