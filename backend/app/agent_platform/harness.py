from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
import weakref
from dataclasses import asdict
from typing import Any

from app.agent_platform.contracts import (
    AgentContext,
    AgentDefinition,
    AgentRun,
    AgentStep,
    RunBudget,
    RunStatus,
    StepStatus,
)
from app.agent_platform.mcp import MCPGateway
from app.agent_platform.run_store import (
    IdempotencyConflictError,
    InMemoryRunStore,
    InvalidRunTransitionError,
    RunBusyError,
    RunCancellationRequestedError,
    RunNotFoundError,
    RunStore,
    RunStoreError,
)
from app.agent_platform.skills import SkillRegistry
from app.utils.time import utc_now

TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


class HarnessError(RuntimeError):
    """Raised when a run violates Harness lifecycle or policy rules."""


class HarnessPersistenceError(HarnessError):
    """Raised when durable Run state cannot be read or checkpointed safely."""


class AgentHarness:
    def __init__(self, *, gateway: MCPGateway, skills: SkillRegistry, store: RunStore | None = None) -> None:
        self.gateway = gateway
        self.skills = skills
        self.store = store or InMemoryRunStore()
        self._agents: dict[str, AgentDefinition] = {}
        self._run_locks: weakref.WeakValueDictionary[uuid.UUID, asyncio.Lock] = weakref.WeakValueDictionary()

    def register_agent(self, definition: AgentDefinition) -> None:
        if definition.id in self._agents:
            raise HarnessError(f"duplicate agent: {definition.id}")
        self._agents[definition.id] = definition

    async def create_run(
        self,
        *,
        user_id: uuid.UUID,
        idempotency_key: str,
        objective: str,
        input: dict[str, Any],
        start_agent_id: str,
        budget: RunBudget | None = None,
    ) -> AgentRun:
        if start_agent_id not in self._agents:
            raise HarnessError(f"unknown start agent: {start_agent_id}")
        normalized_key = idempotency_key.strip()
        normalized_objective = objective.strip()
        if not normalized_key or not normalized_objective:
            raise HarnessError("idempotency key and objective are required")
        if len(normalized_key) > 128:
            raise HarnessError("idempotency key must not exceed 128 characters")
        if len(normalized_objective) > 500:
            raise HarnessError("objective must not exceed 500 characters")
        effective_budget = budget or RunBudget()
        try:
            canonical_input = json.loads(json.dumps(input, ensure_ascii=False, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise HarnessError("run input must be a JSON-compatible object") from exc
        if not isinstance(canonical_input, dict):
            raise HarnessError("run input must be a JSON-compatible object")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "objective": normalized_objective,
                    "input": canonical_input,
                    "start_agent_id": start_agent_id,
                    "budget": asdict(effective_budget),
                },
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        run = AgentRun(
            id=uuid.uuid4(),
            user_id=user_id,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
            objective=normalized_objective,
            input=canonical_input,
            current_agent_id=start_agent_id,
            budget=effective_budget,
        )
        try:
            return await self.store.create(run)
        except IdempotencyConflictError as exc:
            raise HarnessError(str(exc)) from exc
        except RunStoreError as exc:
            raise HarnessError("run could not be persisted") from exc

    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        try:
            return await self.store.get(run_id)
        except RunNotFoundError as exc:
            raise HarnessError("run not found") from exc
        except RunStoreError as exc:
            raise HarnessPersistenceError("run could not be loaded") from exc

    async def cancel(self, run_id: uuid.UUID) -> AgentRun:
        try:
            return await self.store.request_cancel(run_id)
        except RunNotFoundError as exc:
            raise HarnessError("run not found") from exc
        except RunStoreError as exc:
            raise HarnessError("run cancellation could not be persisted") from exc

    async def retry(self, run_id: uuid.UUID) -> AgentRun:
        try:
            await self.store.prepare_retry(run_id)
        except InvalidRunTransitionError as exc:
            raise HarnessError(str(exc)) from exc
        except RunNotFoundError as exc:
            raise HarnessError("run not found") from exc
        except RunStoreError as exc:
            raise HarnessError("run retry could not be persisted") from exc
        return await self.execute(run_id)

    async def execute(self, run_id: uuid.UUID) -> AgentRun:
        lock = self._run_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            return await self._execute_with_lease(run_id)

    async def _execute_with_lease(self, run_id: uuid.UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        owner = f"harness:{uuid.uuid4()}"
        lease_seconds = max(run.budget.timeout_seconds + run.budget.step_timeout_seconds + 30.0, 60.0)
        try:
            run = await self.store.claim(run_id, owner=owner, lease_seconds=lease_seconds)
        except RunBusyError as exc:
            raise HarnessError("run is already executing") from exc
        except RunStoreError as exc:
            raise HarnessPersistenceError("run execution lease could not be acquired") from exc
        if run.status in TERMINAL_STATUSES:
            return run
        try:
            return await self._execute_claimed(run, owner=owner)
        finally:
            try:
                await self.store.release(run_id, owner=owner)
            except RunStoreError:
                # The lease expires automatically. A release failure must not hide the run result.
                pass

    async def _execute_claimed(self, run: AgentRun, *, owner: str) -> AgentRun:
        started = time.monotonic()
        run.status = RunStatus.RUNNING
        self._trace(run, "run.started", {"attempt": run.attempts})
        self._checkpoint(run)
        try:
            run = await self._save_owned(run, owner=owner)
            while run.status == RunStatus.RUNNING:
                latest = await self.get_run(run.id)
                run.cancel_requested = run.cancel_requested or latest.cancel_requested
                self._enforce_budget(run, started)
                if run.cancel_requested:
                    raise RunCancellationRequestedError("run cancellation was requested")
                agent = self._agents.get(run.current_agent_id)
                if agent is None:
                    raise HarnessError(f"unknown current agent: {run.current_agent_id}")
                step = AgentStep(id=uuid.uuid4(), sequence=len(run.steps) + 1, agent_id=agent.id)
                run.steps.append(step)
                context = AgentContext(
                    run_id=run.id,
                    user_id=run.user_id,
                    objective=run.objective,
                    input=dict(run.input),
                    state=dict(run.state),
                    previous_output=dict(run.output),
                    tool_result=run.state.get("last_tool_result"),
                    execute_skill=self.skills.execute,
                )
                try:
                    decision = await asyncio.wait_for(agent.handler(context), timeout=run.budget.step_timeout_seconds)
                    step.decision_kind = decision.kind
                    step.tokens_used = decision.tokens_used
                    run.tokens_used += decision.tokens_used
                    latest = await self.get_run(run.id)
                    run.cancel_requested = run.cancel_requested or latest.cancel_requested
                    if run.cancel_requested:
                        raise RunCancellationRequestedError("run cancellation was requested")
                    if run.tokens_used > run.budget.max_tokens:
                        raise HarnessError("token budget exceeded")
                    if time.monotonic() - started > run.budget.timeout_seconds:
                        raise HarnessError("run timeout exceeded")
                    if decision.kind == "complete":
                        run.output = dict(decision.output)
                        run.status = RunStatus.COMPLETED
                        self._trace(run, "run.completed", {"agent_id": agent.id})
                    elif decision.kind == "handoff":
                        target = decision.handoff_to or ""
                        if target not in agent.handoffs or target not in self._agents:
                            raise HarnessError(f"unauthorized handoff: {agent.id} -> {target}")
                        run.output.update(decision.output)
                        run.current_agent_id = target
                        run.state.pop("last_tool_result", None)
                        self._trace(run, "agent.handoff", {"from": agent.id, "to": target})
                    else:
                        call = decision.tool_call
                        if call is None:
                            raise HarnessError("tool decision is missing call data")
                        if run.tool_calls >= run.budget.max_tool_calls:
                            raise HarnessError("tool call budget exceeded")
                        tool_result = await self.gateway.invoke(
                            agent=agent,
                            tool_name=call.name,
                            arguments=call.arguments,
                            user_id=str(run.user_id),
                            audience=str(call.arguments.get("audience") or run.user_id),
                            approved=call.approved,
                        )
                        run.tool_calls += 1
                        run.state["last_tool_result"] = tool_result
                        self._trace(run, "tool.completed", {"agent_id": agent.id, "tool": call.name})
                    step.status = StepStatus.COMPLETED
                    step.finished_at = utc_now()
                    self._checkpoint(run)
                    run = await self._save_owned(run, owner=owner)
                except (RunBusyError, RunCancellationRequestedError, HarnessPersistenceError):
                    raise
                except Exception as exc:
                    step.status = StepStatus.FAILED
                    step.error = type(exc).__name__
                    step.finished_at = utc_now()
                    raise
        except RunCancellationRequestedError:
            return await self._persist_cancellation(run, owner=owner)
        except RunBusyError as exc:
            raise HarnessError("run execution lease was lost") from exc
        except HarnessPersistenceError:
            raise
        except Exception as exc:
            return await self._persist_failure(run, owner=owner, error=exc)
        return run

    async def _persist_cancellation(self, run: AgentRun, *, owner: str) -> AgentRun:
        if run.steps and run.steps[-1].status == StepStatus.RUNNING:
            run.steps[-1].status = StepStatus.CANCELLED
            run.steps[-1].finished_at = utc_now()
        if run.trace and run.trace[-1]["event"] in {"run.completed", "run.failed"}:
            run.trace.pop()
        run.status = RunStatus.CANCELLED
        run.cancel_requested = True
        run.error = None
        if not run.trace or run.trace[-1]["event"] != "run.cancelled":
            self._trace(run, "run.cancelled", {})
        self._checkpoint(run)
        try:
            return await self._save_owned(run, owner=owner)
        except RunBusyError as exc:
            raise HarnessError("run execution lease was lost while persisting cancellation") from exc

    async def _persist_failure(self, run: AgentRun, *, owner: str, error: Exception) -> AgentRun:
        run.status = RunStatus.FAILED
        run.error = f"{type(error).__name__}: {error}"
        self._trace(run, "run.failed", {"error_type": type(error).__name__})
        self._checkpoint(run)
        try:
            return await self._save_owned(run, owner=owner)
        except RunCancellationRequestedError:
            return await self._persist_cancellation(run, owner=owner)
        except RunBusyError as exc:
            raise HarnessError("run execution lease was lost while persisting failure") from exc

    async def _save_owned(self, run: AgentRun, *, owner: str) -> AgentRun:
        run.updated_at = utc_now()
        try:
            return await self.store.save(run, owner=owner)
        except (RunBusyError, RunCancellationRequestedError):
            raise
        except RunStoreError as exc:
            raise HarnessPersistenceError("run checkpoint could not be persisted") from exc

    @staticmethod
    def _enforce_budget(run: AgentRun, started: float) -> None:
        if len(run.steps) >= run.budget.max_steps:
            raise HarnessError("step budget exceeded")
        if run.tokens_used > run.budget.max_tokens:
            raise HarnessError("token budget exceeded")
        if time.monotonic() - started > run.budget.timeout_seconds:
            raise HarnessError("run timeout exceeded")

    @staticmethod
    def _trace(run: AgentRun, event: str, metadata: dict[str, Any]) -> None:
        run.trace.append({"sequence": len(run.trace) + 1, "event": event, "metadata": metadata, "at": utc_now()})

    @staticmethod
    def _checkpoint(run: AgentRun) -> None:
        run.checkpoint = {
            "status": run.status.value,
            "current_agent_id": run.current_agent_id,
            "tokens_used": run.tokens_used,
            "tool_calls": run.tool_calls,
            "step_count": len(run.steps),
            "state": dict(run.state),
        }
