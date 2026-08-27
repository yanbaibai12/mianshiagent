# ADR-0004: Agent shadow runtime and production boundary

- Status: Accepted for shadow use
- Date: 2026-08-27
- Owners: Agent Platform Team, Security Owner
- Related: ADR-0001, ADR-0003, ADR-0005, ADR-0006

## Context

The product needs Harness, Skills, MCP-compatible tools and multi-Agent orchestration, but Phase 1B has no real PostgreSQL migration/recovery evidence. Replacing the stable resume/interview path immediately would couple unproven runtime state to user data and make rollback unsafe.

## Decision

Implement an isolated **shadow runtime** under `backend/app/agent_platform`. It may expose an authenticated, feature-flagged inspection API, but it must not automatically take over any stable resume, JD or interview route.

The accepted shadow scope is:

- 5 versioned Agents: supervisor, resume analyst, resume rewriter, JD analyst and interview coach;
- 4 versioned Skills;
- 2 read-only MCP-compatible Tools backed by real Resume/Interview database reads;
- Run user, Tool audience, Agent/Tool allowlist and database `user_id` ownership authorization;
- bounded steps, tokens, tool calls, run timeout and step timeout;
- idempotency fingerprint, cancellation, retry, Checkpoint and Trace;
- one approved handoff graph;
- per-Run in-process lock to prevent duplicate concurrent execution;
- deterministic tests and registry validation;
- authenticated Shadow API at `/api/agent-shadow/runs*`, hidden from OpenAPI and disabled by default;
- production release/startup blocking when `AGENT_SHADOW_API_ENABLED=true`.

The Shadow API is an inspection and controlled-validation surface. It must return only public projections, use generic failure codes, enforce same-user Run access and never expose raw state, request fingerprints, idempotency keys, Tool results or internal exception classes.

The following are explicitly not production capabilities:

- `InMemoryRunStore` durability or multi-instance coordination;
- durable workers, restart recovery or distributed transaction/lock guarantees;
- a network MCP Server;
- a production Agent API, end-user UI or production Trace Inspector;
- automatic replacement of stable resume/interview flows;
- proof that resume rewriting improves recruiter preference.

## Consequences

The project can validate lifecycle, real read-adapter authorization and public API data-minimization contracts without putting production user flows at risk. The same isolation means restart recovery, multi-worker execution and end-user value are not yet proven.

The real read adapters deliberately return the same public failure shape for missing and cross-user resources. They are read-only and open a dedicated database session per Tool invocation. This narrows data-leak and session-lifecycle risk, but does not make the in-process MCP-compatible Gateway a network MCP implementation.

## Promotion gates

Production promotion requires:

1. PostgreSQL-backed Run Store plus multi-instance locking, transactional idempotency and a real recovery drill;
2. durable worker execution with forced-termination recovery evidence;
3. network MCP Server boundaries or a separately approved in-process production architecture;
4. authenticated, audited domain adapters for every promoted Tool, with user ownership, cancellation and downstream timeout controls;
5. feature-flagged shadow comparison, rollback and production-safe Trace inspection;
6. Agent SLO, capacity and cost evidence;
7. all Release, security, data and AI-effect gates passing;
8. independent resume-effect evidence meeting `RESUME_REWRITE_EVALUATION.md`.
