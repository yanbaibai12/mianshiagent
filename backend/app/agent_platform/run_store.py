from __future__ import annotations

import asyncio
import copy
import math
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_platform.contracts import (
    AgentRun,
    AgentStep,
    RunBudget,
    RunStatus,
    StepStatus,
    canonical_json_object,
)
from app.models import AgentRunRecord, AgentRunStepRecord, AgentRunTraceRecord
from app.utils.time import utc_now

SessionFactory = Callable[[], AsyncSession]
TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
TERMINAL_STATUS_VALUES = {status.value for status in TERMINAL_STATUSES}
ALLOWED_SAVE_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.COMPLETED: {RunStatus.COMPLETED},
    RunStatus.FAILED: {RunStatus.FAILED},
    RunStatus.CANCELLED: {RunStatus.CANCELLED},
}


def _validate_run_progress(persisted: AgentRun, incoming: AgentRun) -> None:
    if (
        persisted.user_id != incoming.user_id
        or persisted.idempotency_key != incoming.idempotency_key
        or persisted.request_fingerprint != incoming.request_fingerprint
        or persisted.objective != incoming.objective
        or persisted.input != incoming.input
        or persisted.budget != incoming.budget
        or persisted.created_at != incoming.created_at
    ):
        raise InvalidRunTransitionError("immutable run request fields cannot be changed")
    if persisted.attempts != incoming.attempts:
        raise InvalidRunTransitionError("run attempts can only be changed by retry preparation")
    if incoming.status not in ALLOWED_SAVE_TRANSITIONS[persisted.status]:
        raise InvalidRunTransitionError(
            f"invalid run status transition: {persisted.status.value} -> {incoming.status.value}"
        )
    if incoming.tokens_used < persisted.tokens_used or incoming.tool_calls < persisted.tool_calls:
        raise InvalidRunTransitionError("run usage counters cannot decrease")
    if len(incoming.steps) < len(persisted.steps) or incoming.steps[: len(persisted.steps)] != persisted.steps:
        raise InvalidRunTransitionError("persisted step history cannot be changed")
    if len(incoming.trace) < len(persisted.trace) or incoming.trace[: len(persisted.trace)] != persisted.trace:
        raise InvalidRunTransitionError("persisted trace history cannot be changed")
    if [step.sequence for step in incoming.steps] != list(range(1, len(incoming.steps) + 1)):
        raise InvalidRunTransitionError("step sequence must be contiguous")
    if [int(item.get("sequence", 0)) for item in incoming.trace] != list(range(1, len(incoming.trace) + 1)):
        raise InvalidRunTransitionError("trace sequence must be contiguous")
    try:
        for label, value in (
            ("run input", incoming.input),
            ("run output", incoming.output),
            ("run state", incoming.state),
            ("run checkpoint", incoming.checkpoint),
        ):
            if canonical_json_object(value, label=label) != value:
                raise ValueError(f"{label} must use canonical JSON values")
        for item in incoming.trace:
            metadata = item.get("metadata") or {}
            if canonical_json_object(metadata, label="trace metadata") != metadata:
                raise ValueError("trace metadata must use canonical JSON values")
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidRunTransitionError("runtime persistence fields must be canonical JSON") from exc


class RunStoreError(RuntimeError):
    """Base error for durable Agent Run persistence."""


class RunNotFoundError(RunStoreError):
    """Raised when an Agent Run does not exist."""


class RunBusyError(RunStoreError):
    """Raised when another runtime instance owns the execution lease."""


class IdempotencyConflictError(RunStoreError):
    """Raised when an idempotency key is reused for a different request."""


class RunCancellationRequestedError(RunStoreError):
    """Raised when an executor checkpoint loses a race to a persisted cancellation."""


class InvalidRunTransitionError(RunStoreError):
    """Raised when retry or persistence lifecycle rules are violated."""


@dataclass(frozen=True)
class AgentRunSummary:
    id: uuid.UUID
    objective: str
    input_mode: str
    current_agent_id: str
    status: RunStatus
    tokens_used: int
    tool_calls: int
    attempts: int
    cancel_requested: bool
    error_code: str | None
    created_at: datetime
    updated_at: datetime


RunListCursor = tuple[datetime, uuid.UUID]


def _summary_from_run(run: AgentRun) -> AgentRunSummary:
    return AgentRunSummary(
        id=run.id,
        objective=run.objective,
        input_mode=str(run.input.get("mode") or "unknown"),
        current_agent_id=run.current_agent_id,
        status=run.status,
        tokens_used=run.tokens_used,
        tool_calls=run.tool_calls,
        attempts=run.attempts,
        cancel_requested=run.cancel_requested,
        error_code="execution_failed" if run.status == RunStatus.FAILED else None,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


class RunStore(Protocol):
    async def create(self, run: AgentRun) -> AgentRun: ...

    async def get(self, run_id: uuid.UUID) -> AgentRun: ...

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: RunStatus | None = None,
        current_agent_id: str | None = None,
        before: RunListCursor | None = None,
        limit: int = 20,
    ) -> list[AgentRunSummary]: ...

    async def request_cancel(self, run_id: uuid.UUID) -> AgentRun: ...

    async def prepare_retry(self, run_id: uuid.UUID) -> AgentRun: ...

    async def claim(self, run_id: uuid.UUID, *, owner: str, lease_seconds: float) -> AgentRun: ...

    async def save(self, run: AgentRun, *, owner: str) -> AgentRun: ...

    async def release(self, run_id: uuid.UUID, *, owner: str) -> None: ...


class InMemoryRunStore:
    """Deterministic test/local store with the same lease semantics as PostgreSQL."""

    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, AgentRun] = {}
        self._idempotency: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
        self._leases: dict[uuid.UUID, tuple[str, datetime]] = {}
        self._lock = asyncio.Lock()

    async def create(self, run: AgentRun) -> AgentRun:
        async with self._lock:
            key = (run.user_id, run.idempotency_key)
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                existing = self._runs[existing_id]
                if existing.request_fingerprint != run.request_fingerprint:
                    raise IdempotencyConflictError("idempotency key was reused with a different request")
                return copy.deepcopy(existing)
            self._runs[run.id] = copy.deepcopy(run)
            self._idempotency[key] = run.id
            return copy.deepcopy(run)

    async def get(self, run_id: uuid.UUID) -> AgentRun:
        async with self._lock:
            try:
                return copy.deepcopy(self._runs[run_id])
            except KeyError as exc:
                raise RunNotFoundError("run not found") from exc

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: RunStatus | None = None,
        current_agent_id: str | None = None,
        before: RunListCursor | None = None,
        limit: int = 20,
    ) -> list[AgentRunSummary]:
        if limit < 1 or limit > 101:
            raise RunStoreError("list limit must be between 1 and 101")
        async with self._lock:
            runs = [
                run
                for run in self._runs.values()
                if run.user_id == user_id
                and (status is None or run.status == status)
                and (current_agent_id is None or run.current_agent_id == current_agent_id)
                and (
                    before is None
                    or run.updated_at < before[0]
                    or (run.updated_at == before[0] and run.id.int < before[1].int)
                )
            ]
            runs.sort(key=lambda run: (run.updated_at, run.id.int), reverse=True)
            return [_summary_from_run(run) for run in runs[:limit]]

    async def request_cancel(self, run_id: uuid.UUID) -> AgentRun:
        async with self._lock:
            try:
                run = self._runs[run_id]
            except KeyError as exc:
                raise RunNotFoundError("run not found") from exc
            if run.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                run.cancel_requested = True
                run.updated_at = utc_now()
            return copy.deepcopy(run)

    async def prepare_retry(self, run_id: uuid.UUID) -> AgentRun:
        async with self._lock:
            try:
                run = self._runs[run_id]
            except KeyError as exc:
                raise RunNotFoundError("run not found") from exc
            if run.status != RunStatus.FAILED:
                raise InvalidRunTransitionError("only failed runs can be retried")
            run.status = RunStatus.QUEUED
            run.error = None
            run.cancel_requested = False
            run.attempts += 1
            run.updated_at = utc_now()
            run.checkpoint = {
                **run.checkpoint,
                "status": RunStatus.QUEUED.value,
                "current_agent_id": run.current_agent_id,
                "tokens_used": run.tokens_used,
                "tool_calls": run.tool_calls,
                "step_count": len(run.steps),
                "state": copy.deepcopy(run.state),
            }
            return copy.deepcopy(run)

    async def claim(self, run_id: uuid.UUID, *, owner: str, lease_seconds: float) -> AgentRun:
        if not owner.strip() or len(owner) > 120 or not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise RunStoreError("claim requires a valid owner and positive lease")
        async with self._lock:
            try:
                run = self._runs[run_id]
            except KeyError as exc:
                raise RunNotFoundError("run not found") from exc
            if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return copy.deepcopy(run)
            now = utc_now()
            lease = self._leases.get(run_id)
            if lease is not None and lease[0] != owner and lease[1] > now:
                raise RunBusyError("run is already owned by another executor")
            self._leases[run_id] = (owner, now + timedelta(seconds=lease_seconds))
            return copy.deepcopy(run)

    async def save(self, run: AgentRun, *, owner: str) -> AgentRun:
        async with self._lock:
            lease = self._leases.get(run.id)
            if lease is None or lease[0] != owner or lease[1] <= utc_now():
                raise RunBusyError("run execution lease is missing or expired")
            persisted = self._runs.get(run.id)
            if persisted is None:
                raise RunNotFoundError("run not found")
            _validate_run_progress(persisted, run)
            if persisted.cancel_requested and run.status != RunStatus.CANCELLED:
                raise RunCancellationRequestedError("run cancellation was requested")
            if persisted.status in TERMINAL_STATUSES and run.status != persisted.status:
                raise InvalidRunTransitionError("terminal run status cannot be changed")
            saved = copy.deepcopy(run)
            saved.cancel_requested = saved.cancel_requested or persisted.cancel_requested
            saved.updated_at = utc_now()
            self._runs[run.id] = saved
            if saved.status in TERMINAL_STATUSES:
                self._leases.pop(run.id, None)
            else:
                self._leases[run.id] = (
                    owner,
                    saved.updated_at + timedelta(seconds=max(run.budget.timeout_seconds + 30.0, 60.0)),
                )
            return copy.deepcopy(saved)

    async def release(self, run_id: uuid.UUID, *, owner: str) -> None:
        async with self._lock:
            lease = self._leases.get(run_id)
            if lease is not None and lease[0] == owner:
                self._leases.pop(run_id, None)


class PostgresRunStore:
    """PostgreSQL-backed Run Store with transactional idempotency and execution leases.

    Tests may set ``enforce_postgresql=False`` to validate serialization and lifecycle
    portability on SQLite. Such tests are not PostgreSQL production evidence.
    """

    def __init__(self, session_factory: SessionFactory, *, enforce_postgresql: bool = True) -> None:
        self._session_factory = session_factory
        self._enforce_postgresql = enforce_postgresql

    async def _assert_backend(self, session: AsyncSession) -> None:
        if not self._enforce_postgresql:
            return
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            raise RunStoreError("PostgresRunStore requires a PostgreSQL database")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._session_factory() as session:
                await self._assert_backend(session)
                yield session
        except RunStoreError:
            raise
        except SQLAlchemyError as exc:
            raise RunStoreError("agent run database operation failed") from exc

    async def _get_record(self, session: AsyncSession, run_id: uuid.UUID) -> AgentRunRecord:
        result = await session.execute(
            select(AgentRunRecord)
            .options(selectinload(AgentRunRecord.steps), selectinload(AgentRunRecord.trace_events))
            .where(AgentRunRecord.id == run_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise RunNotFoundError("run not found")
        return record

    async def create(self, run: AgentRun) -> AgentRun:
        async with self._session() as session:
            session.add(self._record_from_domain(run))
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                result = await session.execute(
                    select(AgentRunRecord).where(
                        AgentRunRecord.user_id == run.user_id,
                        AgentRunRecord.idempotency_key == run.idempotency_key,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                if existing.request_fingerprint != run.request_fingerprint:
                    raise IdempotencyConflictError("idempotency key was reused with a different request") from exc
                return await self.get(existing.id)
        return await self.get(run.id)

    async def get(self, run_id: uuid.UUID) -> AgentRun:
        async with self._session() as session:
            return self._domain_from_record(await self._get_record(session, run_id))

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: RunStatus | None = None,
        current_agent_id: str | None = None,
        before: RunListCursor | None = None,
        limit: int = 20,
    ) -> list[AgentRunSummary]:
        if limit < 1 or limit > 101:
            raise RunStoreError("list limit must be between 1 and 101")
        async with self._session() as session:
            statement = select(
                AgentRunRecord.id,
                AgentRunRecord.objective,
                AgentRunRecord.input_payload,
                AgentRunRecord.current_agent_id,
                AgentRunRecord.status,
                AgentRunRecord.tokens_used,
                AgentRunRecord.tool_calls,
                AgentRunRecord.attempts,
                AgentRunRecord.cancel_requested,
                AgentRunRecord.created_at,
                AgentRunRecord.updated_at,
            ).where(AgentRunRecord.user_id == user_id)
            if status is not None:
                statement = statement.where(AgentRunRecord.status == status.value)
            if current_agent_id is not None:
                statement = statement.where(AgentRunRecord.current_agent_id == current_agent_id)
            if before is not None:
                statement = statement.where(
                    or_(
                        AgentRunRecord.updated_at < before[0],
                        and_(AgentRunRecord.updated_at == before[0], AgentRunRecord.id < before[1]),
                    )
                )
            result = await session.execute(
                statement.order_by(AgentRunRecord.updated_at.desc(), AgentRunRecord.id.desc()).limit(limit)
            )
            return [self._summary_from_mapping(record) for record in result.mappings().all()]

    async def request_cancel(self, run_id: uuid.UUID) -> AgentRun:
        async with self._session() as session:
            record = await session.scalar(select(AgentRunRecord).where(AgentRunRecord.id == run_id).with_for_update())
            if record is None:
                raise RunNotFoundError("run not found")
            if record.status not in TERMINAL_STATUS_VALUES:
                record.cancel_requested = True
                record.updated_at = utc_now()
            await session.commit()
        return await self.get(run_id)

    async def prepare_retry(self, run_id: uuid.UUID) -> AgentRun:
        async with self._session() as session:
            record = await session.scalar(select(AgentRunRecord).where(AgentRunRecord.id == run_id).with_for_update())
            if record is None:
                raise RunNotFoundError("run not found")
            if record.status != RunStatus.FAILED.value:
                raise InvalidRunTransitionError("only failed runs can be retried")
            record.status = RunStatus.QUEUED.value
            record.error = None
            record.cancel_requested = False
            record.attempts += 1
            record.execution_owner = None
            record.lease_expires_at = None
            record.updated_at = utc_now()
            record.checkpoint = {
                **dict(record.checkpoint or {}),
                "status": RunStatus.QUEUED.value,
                "current_agent_id": record.current_agent_id,
                "tokens_used": record.tokens_used,
                "tool_calls": record.tool_calls,
                "step_count": int(dict(record.checkpoint or {}).get("step_count", 0)),
                "state": copy.deepcopy(dict(record.state_payload or {})),
            }
            await session.commit()
        return await self.get(run_id)

    async def claim(self, run_id: uuid.UUID, *, owner: str, lease_seconds: float) -> AgentRun:
        if not owner.strip() or len(owner) > 120 or not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise RunStoreError("claim requires a valid owner and positive lease")
        now = utc_now()
        expires_at = now + timedelta(seconds=lease_seconds)
        async with self._session() as session:
            result = await session.execute(
                update(AgentRunRecord)
                .where(
                    AgentRunRecord.id == run_id,
                    AgentRunRecord.status.not_in(TERMINAL_STATUS_VALUES),
                    or_(
                        AgentRunRecord.execution_owner == owner,
                        AgentRunRecord.execution_owner.is_(None),
                        AgentRunRecord.lease_expires_at.is_(None),
                        AgentRunRecord.lease_expires_at <= now,
                    ),
                )
                .values(execution_owner=owner, lease_expires_at=expires_at, updated_at=now)
                .returning(AgentRunRecord.id)
            )
            claimed_id = result.scalar_one_or_none()
            await session.commit()
        if claimed_id is not None:
            return await self.get(run_id)
        current = await self.get(run_id)
        if current.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return current
        raise RunBusyError("run is already owned by another executor")

    async def save(self, run: AgentRun, *, owner: str) -> AgentRun:
        async with self._session() as session:
            record = await session.scalar(
                select(AgentRunRecord)
                .options(selectinload(AgentRunRecord.steps), selectinload(AgentRunRecord.trace_events))
                .where(AgentRunRecord.id == run.id)
                .with_for_update()
            )
            if record is None:
                raise RunNotFoundError("run not found")
            now = utc_now()
            if record.execution_owner != owner or record.lease_expires_at is None or record.lease_expires_at <= now:
                raise RunBusyError("run execution lease is missing or expired")
            _validate_run_progress(self._domain_from_record(record), run)
            if record.cancel_requested and run.status != RunStatus.CANCELLED:
                raise RunCancellationRequestedError("run cancellation was requested")
            if record.status in TERMINAL_STATUS_VALUES and run.status.value != record.status:
                raise InvalidRunTransitionError("terminal run status cannot be changed")
            cancel_requested = bool(record.cancel_requested or run.cancel_requested)
            self._apply_domain(record, run)
            record.cancel_requested = cancel_requested
            record.updated_at = now
            if run.status in TERMINAL_STATUSES:
                record.execution_owner = None
                record.lease_expires_at = None
            else:
                record.lease_expires_at = now + timedelta(seconds=max(run.budget.timeout_seconds + 30.0, 60.0))
            await session.execute(delete(AgentRunStepRecord).where(AgentRunStepRecord.run_id == run.id))
            await session.execute(delete(AgentRunTraceRecord).where(AgentRunTraceRecord.run_id == run.id))
            session.add_all(self._step_records(run))
            session.add_all(self._trace_records(run))
            await session.commit()
        return await self.get(run.id)

    async def release(self, run_id: uuid.UUID, *, owner: str) -> None:
        async with self._session() as session:
            await session.execute(
                update(AgentRunRecord)
                .where(AgentRunRecord.id == run_id, AgentRunRecord.execution_owner == owner)
                .values(execution_owner=None, lease_expires_at=None, updated_at=utc_now())
            )
            await session.commit()

    @staticmethod
    def _summary_from_mapping(record: Mapping[str, Any]) -> AgentRunSummary:
        record_status = RunStatus(str(record["status"]))
        return AgentRunSummary(
            id=record["id"],
            objective=str(record["objective"]),
            input_mode=str((record["input_payload"] or {}).get("mode") or "unknown"),
            current_agent_id=str(record["current_agent_id"]),
            status=record_status,
            tokens_used=int(record["tokens_used"]),
            tool_calls=int(record["tool_calls"]),
            attempts=int(record["attempts"]),
            cancel_requested=bool(record["cancel_requested"]),
            error_code="execution_failed" if record_status == RunStatus.FAILED else None,
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    @staticmethod
    def _record_from_domain(run: AgentRun) -> AgentRunRecord:
        record = AgentRunRecord(id=run.id, user_id=run.user_id, idempotency_key=run.idempotency_key)
        PostgresRunStore._apply_domain(record, run)
        record.steps = PostgresRunStore._step_records(run)
        record.trace_events = PostgresRunStore._trace_records(run)
        return record

    @staticmethod
    def _apply_domain(record: AgentRunRecord, run: AgentRun) -> None:
        record.request_fingerprint = run.request_fingerprint
        record.objective = run.objective
        record.input_payload = copy.deepcopy(run.input)
        record.current_agent_id = run.current_agent_id
        record.budget = {
            "max_steps": run.budget.max_steps,
            "max_tokens": run.budget.max_tokens,
            "max_tool_calls": run.budget.max_tool_calls,
            "timeout_seconds": run.budget.timeout_seconds,
            "step_timeout_seconds": run.budget.step_timeout_seconds,
        }
        record.status = run.status.value
        record.tokens_used = run.tokens_used
        record.tool_calls = run.tool_calls
        record.attempts = run.attempts
        record.cancel_requested = run.cancel_requested
        record.output_payload = copy.deepcopy(run.output)
        record.state_payload = copy.deepcopy(run.state)
        record.checkpoint = copy.deepcopy(run.checkpoint)
        record.error = run.error
        record.created_at = run.created_at
        record.updated_at = run.updated_at

    @staticmethod
    def _step_records(run: AgentRun) -> list[AgentRunStepRecord]:
        return [
            AgentRunStepRecord(
                id=step.id,
                run_id=run.id,
                sequence=step.sequence,
                agent_id=step.agent_id,
                status=step.status.value,
                decision_kind=step.decision_kind,
                tokens_used=step.tokens_used,
                error=step.error,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in run.steps
        ]

    @staticmethod
    def _trace_records(run: AgentRun) -> list[AgentRunTraceRecord]:
        return [
            AgentRunTraceRecord(
                run_id=run.id,
                sequence=int(item["sequence"]),
                event=str(item["event"]),
                event_metadata=copy.deepcopy(dict(item.get("metadata") or {})),
                created_at=item["at"],
            )
            for item in run.trace
        ]

    @staticmethod
    def _domain_from_record(record: AgentRunRecord) -> AgentRun:
        budget_payload = dict(record.budget or {})
        budget = RunBudget(
            max_steps=int(budget_payload.get("max_steps", 12)),
            max_tokens=int(budget_payload.get("max_tokens", 12_000)),
            max_tool_calls=int(budget_payload.get("max_tool_calls", 8)),
            timeout_seconds=float(budget_payload.get("timeout_seconds", 60.0)),
            step_timeout_seconds=float(budget_payload.get("step_timeout_seconds", 15.0)),
        )
        steps = [
            AgentStep(
                id=step.id,
                sequence=step.sequence,
                agent_id=step.agent_id,
                status=StepStatus(step.status),
                decision_kind=step.decision_kind,
                tokens_used=step.tokens_used,
                error=step.error,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in sorted(record.steps, key=lambda item: (item.sequence, str(item.id)))
        ]
        trace = [
            {
                "sequence": event.sequence,
                "event": event.event,
                "metadata": dict(event.event_metadata or {}),
                "at": event.created_at,
            }
            for event in sorted(record.trace_events, key=lambda item: (item.sequence, item.id))
        ]
        return AgentRun(
            id=record.id,
            user_id=record.user_id,
            idempotency_key=record.idempotency_key,
            request_fingerprint=record.request_fingerprint,
            objective=record.objective,
            input=dict(record.input_payload or {}),
            current_agent_id=record.current_agent_id,
            budget=budget,
            status=RunStatus(record.status),
            tokens_used=record.tokens_used,
            tool_calls=record.tool_calls,
            attempts=record.attempts,
            cancel_requested=record.cancel_requested,
            output=dict(record.output_payload or {}),
            state=dict(record.state_payload or {}),
            checkpoint=dict(record.checkpoint or {}),
            error=record.error,
            steps=steps,
            trace=trace,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
