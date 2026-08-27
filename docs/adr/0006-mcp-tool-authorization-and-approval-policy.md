# ADR-0006: MCP Tool authorization and approval policy

- Status: Accepted for shadow use
- Date: 2026-08-27
- Owners: Agent Platform Team, Security Owner
- Related: ADR-0004

## Context

An Agent name or prompt instruction is not an authorization boundary. Tools that read resumes or interview data can expose sensitive information if the run user, tool audience, Agent allowlist and tool-side policy are not all checked.

## Decision

Every MCP-compatible Tool invocation must pass all of the following checks:

1. the Tool exists in the registry;
2. the Tool name is in the invoking Agent's allowlist;
3. the Agent is in the Tool's `allowed_agents` set;
4. the requested audience exactly matches the Run user;
5. required arguments are present;
6. high-risk, write-capable or approval-required Tools have explicit approval;
7. output is an object and contains all declared fields;
8. timeout and failure type are recorded in the invocation audit record.

The active shadow registry contains only:

- `resume.read` for `resume-analyst` and `resume-rewriter`;
- `interview.questions.read` for `interview-coach`.

Both are read-only. A planned registry may not publish active Tool definitions. A write Tool without approval is rejected by both registry validation and runtime authorization.

## Security boundaries

- Tool output must not be copied wholesale into Trace;
- contact data is excluded by the resume evidence Skill;
- production adapters must independently enforce database ownership; audience equality alone is insufficient;
- sync handlers run in a worker thread, and Python cannot forcibly terminate the thread after timeout, so production adapters should use cancellable async I/O or process isolation.

## Consequences

The gateway provides a tested least-privilege contract. It remains MCP-compatible rather than a standards-complete network MCP Server; transport authentication and network schema negotiation are future work.
