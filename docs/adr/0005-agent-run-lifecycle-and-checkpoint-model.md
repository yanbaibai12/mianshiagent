# ADR-0005: Agent Run lifecycle, idempotency and checkpoint model

- Status: Accepted for shadow use
- Date: 2026-08-27
- Owners: Agent Platform Team
- Related: ADR-0004

## Context

Multi-Agent execution can duplicate tool calls, exceed cost budgets, lose state after failure or produce inconsistent results when the same request is retried concurrently. These behaviors require an explicit lifecycle rather than ad-hoc coroutine chaining.

## Decision

Use the following Run model:

- states: `queued`, `running`, `completed`, `failed`, `cancelled`;
- terminal Runs are immutable to `execute`; only failed Runs may use `retry`;
- idempotency is scoped by `(user_id, idempotency_key)` and a canonical request fingerprint;
- reusing a key with a different objective/input/start Agent fails closed;
- every Agent decision creates a sequenced Step with status, token use, timestamps and error type;
- every successful step and every failure writes a Checkpoint snapshot;
- Trace records lifecycle, handoff and tool completion events without resume bodies or contact data;
- step, token, tool-call, run-time and step-time budgets are enforced before additional work;
- concurrent `execute` calls for one Run are serialized by an in-process lock.

Retry resumes from the current in-memory state and checkpoint. Because current Tools are read-only, replay risk is bounded. Write-capable Tools are prohibited until persistent idempotency and compensation are implemented.

## Alternatives rejected

- Stateless retries: rejected because completed handoffs/tool reads would be lost.
- Clearing all state on retry: rejected because it hides the real replay boundary and may repeat expensive work.
- Treating every exception as retryable: rejected for production; the shadow runtime exposes retry mechanics but does not yet classify transient/permanent failures.

## Consequences

The lifecycle is deterministic and testable in one process. It is not safe for multi-instance production until locks, checkpoints and idempotency records are moved to PostgreSQL with transactional compare-and-set semantics.
