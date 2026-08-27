# ADR-0007: PostgreSQL Agent Run Store and execution lease

- Status: Accepted for Shadow Runtime implementation
- Date: 2026-08-27
- Owners: Agent Platform Team, Data Owner, Security Owner
- Supersedes: the in-memory-only persistence assumption in ADR-0004

## Context

The Shadow Harness originally stored Run, Step, Trace and Checkpoint state only in process memory. That design was suitable for deterministic contract validation but could not preserve state across process restart, enforce idempotency across instances or stop two application instances from executing the same Run.

The public Shadow API remains disabled in production. This ADR improves the internal runtime boundary; it does not approve a production Agent API.

## Decision

1. Add Alembic revision `0018` with normalized `agent_runs`, `agent_run_steps` and `agent_run_trace_events` tables.
2. Enforce a database unique constraint on `(user_id, idempotency_key)` and compare a SHA-256 request fingerprint before returning an existing Run.
3. Use an execution owner plus expiring lease for cross-instance single-executor coordination. Checkpoint writes must fail closed when the caller no longer owns an unexpired lease.
4. Preserve an externally requested cancellation during checkpoint writes instead of overwriting it with stale executor state.
5. Persist a bounded Step and Trace projection on every checkpoint. The current maximum step count keeps delete-and-reinsert synchronization bounded; a future high-volume runtime must move to append-only event persistence.
6. Select the Store with `AGENT_RUN_STORE_BACKEND=memory|postgresql`. The PostgreSQL implementation rejects non-PostgreSQL databases unless a portability test explicitly disables the backend guard.
7. Keep `AGENT_SHADOW_API_ENABLED=false` in production. Durable worker dispatch, kill/restart recovery evidence and production SLO approval remain separate gates.

## Consequences

### Positive

- Run identity and request idempotency can survive application restarts.
- Multi-instance executors have a database-enforced single-owner lease boundary.
- Step, Trace and Checkpoint inspection can be recovered from PostgreSQL.
- Staging misconfiguration fails closed through runtime checks and Release Checks.

### Risks and limitations

- The HTTP endpoint still executes synchronously; no Redis/RQ Agent worker has been connected.
- Lease recovery can resume only from the last committed checkpoint. An interrupted in-flight read Tool may be repeated after lease expiry. Write Tools remain prohibited from the current Registry and would require their own idempotency and compensation contract.
- SQLite tests prove serialization and lifecycle portability only. They are not PostgreSQL concurrency, migration, rollback or recovery evidence.
- Real PostgreSQL upgrade/downgrade/backup/restore and forced-process-termination drills are still required.

## Verification

Required automated evidence:

- Alembic has exactly one head at `0018`;
- PostgreSQL-dialect upgrade and downgrade SQL compile;
- Store restart recovery, unique idempotency, lease contention, cancellation preservation and non-PostgreSQL fail-closed tests pass;
- Release Check rejects a PostgreSQL Store paired with a non-PostgreSQL URL and rejects non-local Shadow evaluation on the memory Store.

Required external evidence before promotion:

- concurrent execution tests against a real PostgreSQL instance;
- application kill/restart after queued, running, checkpointed and cancel-requested states;
- migration upgrade, downgrade, backup and restore drill;
- p95/p99 latency, lease contention, recovery success and database growth measurements.
