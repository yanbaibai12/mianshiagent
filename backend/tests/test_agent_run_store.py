from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent_platform.contracts import (
    AgentContext,
    AgentDecision,
    AgentDefinition,
    RunBudget,
    RunStatus,
    StepStatus,
)
from app.agent_platform.harness import AgentHarness, HarnessError
from app.agent_platform.mcp import MCPGateway
from app.agent_platform.run_store import (
    InMemoryRunStore,
    InvalidRunTransitionError,
    PostgresRunStore,
    RunBusyError,
    RunCancellationRequestedError,
    RunStoreError,
)
from app.agent_platform.skills import SkillRegistry
from app.models import AgentRunRecord, Base, User
from app.utils.time import utc_now


async def _session_factory(tmp_path):
    database_path = tmp_path / "agent-run-store-contract.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email=f"{user_id}@example.com", password_hash="test-only"))
        await session.commit()
    return engine, factory, user_id


def _harness(store: PostgresRunStore) -> AgentHarness:
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry(), store=store)

    async def complete(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"run_id": str(context.run_id)}, tokens_used=3)

    harness.register_agent(AgentDefinition(id="persistent-agent", version="0.1.0", handler=complete))
    return harness


@pytest.mark.asyncio
async def test_sqlalchemy_contract_persists_runs_and_transactional_idempotency(tmp_path):
    """SQLite validates portability only; PostgreSQL drill evidence is tracked separately."""
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = _harness(store)
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="persistent-idempotency",
            objective="persist and recover",
            input={"mode": "contract"},
            start_agent_id="persistent-agent",
        )
        repeated = await harness.create_run(
            user_id=user_id,
            idempotency_key="persistent-idempotency",
            objective="persist and recover",
            input={"mode": "contract"},
            start_agent_id="persistent-agent",
        )
        assert repeated.id == created.id

        completed = await harness.execute(created.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.tokens_used == 3
        assert len(completed.steps) == 1
        assert [item["event"] for item in completed.trace] == ["run.started", "run.completed"]

        restarted_harness = _harness(PostgresRunStore(factory, enforce_postgresql=False))
        recovered = await restarted_harness.get_run(created.id)
        assert recovered.status == RunStatus.COMPLETED
        assert recovered.output == {"run_id": str(created.id)}
        assert recovered.checkpoint["status"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_contract_enforces_lease_and_preserves_external_cancel(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = _harness(store)
    try:
        run = await harness.create_run(
            user_id=user_id,
            idempotency_key="lease-contract",
            objective="lease",
            input={},
            start_agent_id="persistent-agent",
        )
        claimed = await store.claim(run.id, owner="worker-a", lease_seconds=60)
        with pytest.raises(RunBusyError, match="another executor"):
            await store.claim(run.id, owner="worker-b", lease_seconds=60)

        await store.request_cancel(run.id)
        claimed.status = RunStatus.RUNNING
        with pytest.raises(RunCancellationRequestedError, match="cancellation"):
            await store.save(claimed, owner="worker-a")
        claimed.status = RunStatus.CANCELLED
        claimed.cancel_requested = True
        saved = await store.save(claimed, owner="worker-a")
        assert saved.cancel_requested is True
        await store.release(run.id, owner="worker-a")

        cancelled = await harness.execute(run.id)
        assert cancelled.status == RunStatus.CANCELLED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_store_fails_closed_on_non_postgresql_backend(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory)
    harness = _harness(store)
    try:
        with pytest.raises(HarnessError, match="could not be persisted") as exc_info:
            await harness.create_run(
                user_id=user_id,
                idempotency_key="wrong-backend",
                objective="reject sqlite as production evidence",
                input={},
                start_agent_id="persistent-agent",
            )
        assert isinstance(exc_info.value.__cause__, RunStoreError)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_in_memory_harness_lease_serializes_concurrent_execution():
    calls = 0
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry())

    async def complete(context: AgentContext) -> AgentDecision:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return AgentDecision.complete({"ok": True})

    harness.register_agent(AgentDefinition(id="single-executor", version="0.1.0", handler=complete))
    run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="single-executor",
        objective="execute once",
        input={},
        start_agent_id="single-executor",
    )
    first, second = await asyncio.gather(harness.execute(run.id), harness.execute(run.id))
    assert first.status == second.status == RunStatus.COMPLETED
    assert calls == 1


@pytest.mark.asyncio
async def test_sqlalchemy_contract_allows_expired_lease_takeover_and_rejects_stale_owner(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = _harness(store)
    try:
        run = await harness.create_run(
            user_id=user_id,
            idempotency_key="lease-takeover",
            objective="take over an expired lease",
            input={},
            start_agent_id="persistent-agent",
        )
        stale = await store.claim(run.id, owner="worker-a", lease_seconds=0.01)
        await asyncio.sleep(0.03)
        current = await store.claim(run.id, owner="worker-b", lease_seconds=60)
        assert current.id == run.id
        stale.status = RunStatus.RUNNING
        with pytest.raises(RunBusyError, match="missing or expired"):
            await store.save(stale, owner="worker-a")
        await store.release(run.id, owner="worker-b")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_contract_rejects_idempotency_key_with_different_request(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    harness = _harness(PostgresRunStore(factory, enforce_postgresql=False))
    try:
        await harness.create_run(
            user_id=user_id,
            idempotency_key="fingerprint-conflict",
            objective="first request",
            input={"version": 1},
            start_agent_id="persistent-agent",
        )
        with pytest.raises(HarnessError, match="different request"):
            await harness.create_run(
                user_id=user_id,
                idempotency_key="fingerprint-conflict",
                objective="second request",
                input={"version": 2},
                start_agent_id="persistent-agent",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_run_can_be_recovered_and_retried_after_store_restart(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    failing = AgentHarness(
        gateway=MCPGateway(),
        skills=SkillRegistry(),
        store=PostgresRunStore(factory, enforce_postgresql=False),
    )

    async def fail(context: AgentContext) -> AgentDecision:
        raise RuntimeError(f"failed {context.run_id}")

    failing.register_agent(AgentDefinition(id="persistent-agent", version="0.1.0", handler=fail))
    try:
        created = await failing.create_run(
            user_id=user_id,
            idempotency_key="retry-after-restart",
            objective="persist failure and retry",
            input={},
            start_agent_id="persistent-agent",
        )
        failed = await failing.execute(created.id)
        assert failed.status == RunStatus.FAILED
        assert failed.steps[-1].status == StepStatus.FAILED

        restarted = _harness(PostgresRunStore(factory, enforce_postgresql=False))
        completed = await restarted.retry(created.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.attempts == 2
        assert [step.status for step in completed.steps] == [StepStatus.FAILED, StepStatus.COMPLETED]
        assert [item["event"] for item in completed.trace] == [
            "run.started",
            "run.failed",
            "run.started",
            "run.completed",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_is_idempotent_for_terminal_runs_and_survives_restart(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    harness = _harness(PostgresRunStore(factory, enforce_postgresql=False))
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="terminal-cancel",
            objective="terminal cancel is a no-op",
            input={},
            start_agent_id="persistent-agent",
        )
        completed = await harness.execute(created.id)
        first = await harness.cancel(completed.id)
        second = await harness.cancel(completed.id)
        recovered = await _harness(PostgresRunStore(factory, enforce_postgresql=False)).get_run(completed.id)
        assert first.status == second.status == recovered.status == RunStatus.COMPLETED
        assert first.cancel_requested is second.cancel_requested is recovered.cancel_requested is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_persisted_cancel_wins_when_requested_during_agent_decision(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    entered = asyncio.Event()
    proceed = asyncio.Event()
    harness = AgentHarness(
        gateway=MCPGateway(),
        skills=SkillRegistry(),
        store=PostgresRunStore(factory, enforce_postgresql=False),
    )

    async def delayed_complete(context: AgentContext) -> AgentDecision:
        entered.set()
        await proceed.wait()
        return AgentDecision.complete({"run_id": str(context.run_id)}, tokens_used=2)

    harness.register_agent(AgentDefinition(id="persistent-agent", version="0.1.0", handler=delayed_complete))
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="cancel-race",
            objective="cancel during decision",
            input={},
            start_agent_id="persistent-agent",
        )
        execution = asyncio.create_task(harness.execute(created.id))
        await asyncio.wait_for(entered.wait(), timeout=1)
        await harness.cancel(created.id)
        proceed.set()
        cancelled = await asyncio.wait_for(execution, timeout=1)
        assert cancelled.status == RunStatus.CANCELLED
        assert cancelled.cancel_requested is True
        assert cancelled.steps[-1].status == StepStatus.CANCELLED
        assert [item["event"] for item in cancelled.trace] == ["run.started", "run.cancelled"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_harness_converts_checkpoint_lease_loss_to_public_error():
    class LeaseLosingStore(InMemoryRunStore):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        async def save(self, run, *, owner):
            self.save_calls += 1
            if self.save_calls == 2:
                raise RunBusyError("simulated takeover")
            return await super().save(run, owner=owner)

    store = LeaseLosingStore()
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry(), store=store)

    async def complete(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"run_id": str(context.run_id)})

    harness.register_agent(AgentDefinition(id="lease-loss-agent", version="0.1.0", handler=complete))
    run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="lease-loss",
        objective="fail closed on lease loss",
        input={},
        start_agent_id="lease-loss-agent",
    )
    with pytest.raises(HarnessError, match="lease was lost"):
        await harness.execute(run.id)


@pytest.mark.asyncio
async def test_retry_preparation_persists_queued_checkpoint_and_history(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry(), store=store)

    async def fail(context: AgentContext) -> AgentDecision:
        raise RuntimeError(f"failed {context.run_id}")

    harness.register_agent(AgentDefinition(id="persistent-agent", version="0.1.0", handler=fail))
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="queued-retry-checkpoint",
            objective="persist queued retry checkpoint",
            input={},
            start_agent_id="persistent-agent",
        )
        failed = await harness.execute(created.id)
        prepared = await store.prepare_retry(failed.id)

        assert prepared.status == RunStatus.QUEUED
        assert prepared.attempts == 2
        assert prepared.checkpoint["status"] == RunStatus.QUEUED.value
        assert prepared.checkpoint["step_count"] == 1
        assert [step.status for step in prepared.steps] == [StepStatus.FAILED]
        assert [item["event"] for item in prepared.trace] == ["run.started", "run.failed"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_contract_rejects_immutable_request_mutation(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = _harness(store)
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="immutable-fields",
            objective="preserve immutable fields",
            input={"mode": "original"},
            start_agent_id="persistent-agent",
        )

        changed_objective = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_objective.objective = "mutated objective"
        with pytest.raises(InvalidRunTransitionError, match="immutable"):
            await store.save(changed_objective, owner="worker-a")

        changed_input = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_input.input["mode"] = "mutated"
        with pytest.raises(InvalidRunTransitionError, match="immutable"):
            await store.save(changed_input, owner="worker-a")

        changed_budget = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_budget.budget = RunBudget(max_steps=99)
        with pytest.raises(InvalidRunTransitionError, match="immutable"):
            await store.save(changed_budget, owner="worker-a")

        progress = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        progress.status = RunStatus.RUNNING
        progress.tokens_used = 1
        progress.trace.append({"sequence": 1, "event": "run.started", "metadata": {}, "at": utc_now()})
        progress = await store.save(progress, owner="worker-a")

        changed_attempts = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_attempts.attempts += 1
        with pytest.raises(InvalidRunTransitionError, match="retry preparation"):
            await store.save(changed_attempts, owner="worker-a")

        changed_usage = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_usage.tokens_used = 0
        with pytest.raises(InvalidRunTransitionError, match="counters"):
            await store.save(changed_usage, owner="worker-a")

        changed_history = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        changed_history.trace.clear()
        with pytest.raises(InvalidRunTransitionError, match="trace history"):
            await store.save(changed_history, owner="worker-a")

        invalid_json = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        invalid_json.state["value"] = float("nan")
        with pytest.raises(InvalidRunTransitionError, match="canonical JSON"):
            await store.save(invalid_json, owner="worker-a")

        invalid_transition = await store.claim(created.id, owner="worker-a", lease_seconds=60)
        invalid_transition.status = RunStatus.QUEUED
        with pytest.raises(InvalidRunTransitionError, match="status transition"):
            await store.save(invalid_transition, owner="worker-a")

        assert progress.tokens_used == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_rejects_invalid_owner_and_non_finite_lease():
    store = InMemoryRunStore()
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry(), store=store)

    async def complete(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"run_id": str(context.run_id)})

    harness.register_agent(AgentDefinition(id="claim-agent", version="0.1.0", handler=complete))
    run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="invalid-claim",
        objective="reject invalid claims",
        input={},
        start_agent_id="claim-agent",
    )

    with pytest.raises(RunStoreError, match="valid owner"):
        await store.claim(run.id, owner="   ", lease_seconds=60)
    with pytest.raises(RunStoreError, match="positive lease"):
        await store.claim(run.id, owner="worker", lease_seconds=float("nan"))


@pytest.mark.asyncio
async def test_terminal_checkpoint_clears_persisted_execution_lease(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    harness = _harness(PostgresRunStore(factory, enforce_postgresql=False))
    try:
        created = await harness.create_run(
            user_id=user_id,
            idempotency_key="terminal-lease-cleanup",
            objective="clear terminal lease",
            input={},
            start_agent_id="persistent-agent",
        )
        completed = await harness.execute(created.id)
        assert completed.status == RunStatus.COMPLETED

        async with factory() as session:
            owner, expires_at = (
                await session.execute(
                    select(AgentRunRecord.execution_owner, AgentRunRecord.lease_expires_at).where(
                        AgentRunRecord.id == completed.id
                    )
                )
            ).one()
        assert owner is None
        assert expires_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_in_memory_run_listing_is_owned_filtered_and_cursor_stable():
    store = InMemoryRunStore()
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry(), store=store)

    async def complete(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"ok": True})

    harness.register_agent(AgentDefinition(id="list-agent", version="0.1.0", handler=complete))
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    created = []
    for index in range(3):
        created.append(
            await harness.create_run(
                user_id=owner_id,
                idempotency_key=f"listing-{index}",
                objective=f"run {index}",
                input={"mode": "resume" if index < 2 else "jd"},
                start_agent_id="list-agent",
            )
        )
    await harness.create_run(
        user_id=other_id,
        idempotency_key="other-listing",
        objective="other run",
        input={"mode": "resume"},
        start_agent_id="list-agent",
    )
    completed = await harness.execute(created[0].id)

    remaining = sorted(created[1:], key=lambda run: (run.updated_at, run.id.int), reverse=True)
    first_page = await store.list_for_user(owner_id, limit=2)
    assert [item.id for item in first_page] == [completed.id, remaining[0].id]
    cursor = (first_page[-1].updated_at, first_page[-1].id)
    second_page = await store.list_for_user(owner_id, before=cursor, limit=2)
    assert [item.id for item in second_page] == [remaining[1].id]
    assert [item.id for item in await store.list_for_user(owner_id, status=RunStatus.COMPLETED)] == [completed.id]
    assert [item.id for item in await store.list_for_user(owner_id, current_agent_id="list-agent")] == [
        completed.id,
        remaining[0].id,
        remaining[1].id,
    ]
    assert await store.list_for_user(uuid.uuid4()) == []
    with pytest.raises(RunStoreError, match="between 1 and 101"):
        await store.list_for_user(owner_id, limit=102)


@pytest.mark.asyncio
async def test_sqlalchemy_run_listing_uses_summary_query_without_cross_user_leakage(tmp_path):
    engine, factory, user_id = await _session_factory(tmp_path)
    store = PostgresRunStore(factory, enforce_postgresql=False)
    harness = _harness(store)
    captured_statements: list[str] = []

    def capture_statement(connection, cursor, statement, parameters, context, executemany):
        captured_statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        run = await harness.create_run(
            user_id=user_id,
            idempotency_key="summary-listing",
            objective="list persisted run",
            input={"mode": "contract"},
            start_agent_id="persistent-agent",
        )
        await harness.execute(run.id)
        captured_statements.clear()
        items = await store.list_for_user(user_id, status=RunStatus.COMPLETED, limit=2)
        assert len(items) == 1
        assert items[0].id == run.id
        assert items[0].input_mode == "contract"
        assert items[0].status == RunStatus.COMPLETED
        listing_sql = captured_statements[-1]
        assert "agent_run_steps" not in listing_sql
        assert "agent_run_trace_events" not in listing_sql
        for excluded_column in (
            "output",
            "state",
            "checkpoint",
            "error",
            "budget",
            "idempotency_key",
            "request_fingerprint",
        ):
            assert f"agent_runs.{excluded_column}" not in listing_sql
        assert await store.list_for_user(uuid.uuid4()) == []
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)
        await engine.dispose()
