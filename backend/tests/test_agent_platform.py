from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent_platform.agents import build_default_agents, build_default_skill_registry
from app.agent_platform.contracts import (
    AgentContext,
    AgentDecision,
    AgentDefinition,
    RiskLevel,
    RunBudget,
    RunStatus,
)
from app.agent_platform.harness import AgentHarness, HarnessError, InMemoryRunStore
from app.agent_platform.mcp import MCPGateway, MCPTool, ToolAuthorizationError, ToolContractError
from app.agent_platform.skills import SkillContractError, SkillDefinition, SkillRegistry


def _harness() -> AgentHarness:
    gateway = MCPGateway()
    gateway.register(
        MCPTool(
            name="resume.read",
            version="0.1.0",
            handler=lambda args: {
                "resume_text": (
                    "Backend Engineer\n"
                    "Designed an idempotent FastAPI workflow with PostgreSQL and Redis.\n"
                    "Measured retry recovery and documented rollback controls."
                )
            },
            allowed_agents=frozenset({"resume-analyst", "resume-rewriter"}),
            required_arguments=frozenset({"resume_id", "audience"}),
            output_fields=frozenset({"resume_text"}),
            risk_level=RiskLevel.MEDIUM,
        )
    )
    gateway.register(
        MCPTool(
            name="interview.questions.read",
            version="0.1.0",
            handler=lambda args: {"questions": ["Explain your retry design."]},
            allowed_agents=frozenset({"interview-coach"}),
            required_arguments=frozenset({"interview_id", "audience"}),
            output_fields=frozenset({"questions"}),
            risk_level=RiskLevel.MEDIUM,
        )
    )
    harness = AgentHarness(gateway=gateway, skills=build_default_skill_registry())
    for definition in build_default_agents():
        harness.register_agent(definition)
    return harness


@pytest.mark.asyncio
async def test_default_multi_agent_resume_jd_and_interview_runs_are_bounded_and_idempotent():
    harness = _harness()
    user_id = uuid.uuid4()
    resume_run = await harness.create_run(
        user_id=user_id,
        idempotency_key="resume-1",
        objective="Extract evidence",
        input={"mode": "resume", "resume_id": str(uuid.uuid4())},
        start_agent_id="supervisor",
    )
    repeated = await harness.create_run(
        user_id=user_id,
        idempotency_key="resume-1",
        objective="Extract evidence",
        input={"mode": "resume", "resume_id": resume_run.input["resume_id"]},
        start_agent_id="supervisor",
    )
    assert repeated.id == resume_run.id
    completed = await harness.execute(resume_run.id)
    assert completed.status == RunStatus.COMPLETED
    assert completed.output["agent"] == "resume-analyst"
    assert completed.output["fact_safe"] is True
    assert completed.tool_calls == 1
    assert len(completed.steps) == 3
    assert completed.checkpoint["status"] == "completed"
    assert {event["event"] for event in completed.trace} >= {
        "run.started",
        "agent.handoff",
        "tool.completed",
        "run.completed",
    }
    assert (await harness.execute(completed.id)).id == completed.id
    assert (await harness.cancel(completed.id)).status == RunStatus.COMPLETED

    with pytest.raises(HarnessError, match="different request"):
        await harness.create_run(
            user_id=user_id,
            idempotency_key="resume-1",
            objective="Different objective",
            input={"mode": "resume"},
            start_agent_id="supervisor",
        )

    with pytest.raises(HarnessError, match="different request"):
        await harness.create_run(
            user_id=user_id,
            idempotency_key="resume-1",
            objective="Extract evidence",
            input={"mode": "resume", "resume_id": resume_run.input["resume_id"]},
            start_agent_id="supervisor",
            budget=RunBudget(max_steps=10),
        )

    jd_run = await harness.create_run(
        user_id=user_id,
        idempotency_key="jd-1",
        objective="Map requirements",
        input={"mode": "jd", "jd_text": "Python FastAPI PostgreSQL Redis Docker and MCP"},
        start_agent_id="supervisor",
    )
    jd_completed = await harness.execute(jd_run.id)
    assert jd_completed.status == RunStatus.COMPLETED
    assert {"Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "MCP"}.issubset(jd_completed.output["requirements"])

    interview_run = await harness.create_run(
        user_id=user_id,
        idempotency_key="interview-1",
        objective="Critique answer",
        input={
            "mode": "interview",
            "interview_id": str(uuid.uuid4()),
            "answer": "I designed the workflow, measured the result, and documented a rollback tradeoff.",
        },
        start_agent_id="supervisor",
    )
    interview_completed = await harness.execute(interview_run.id)
    assert interview_completed.status == RunStatus.COMPLETED
    assert interview_completed.output["score"] >= 75
    assert interview_completed.output["questions"]

    rejected = await harness.create_run(
        user_id=user_id,
        idempotency_key="unsupported-1",
        objective="Unsupported route",
        input={"mode": "payments"},
        start_agent_id="supervisor",
    )
    assert (await harness.execute(rejected.id)).output["status"] == "rejected"

    rewrite_run = await harness.create_run(
        user_id=user_id,
        idempotency_key="rewrite-1",
        objective="Create an evidence-linked rewrite",
        input={
            "mode": "resume-rewrite",
            "resume_id": str(uuid.uuid4()),
            "jd_text": "FastAPI PostgreSQL Redis",
        },
        start_agent_id="supervisor",
    )
    rewrite = await harness.execute(rewrite_run.id)
    assert rewrite.status == RunStatus.COMPLETED
    assert rewrite.output["agent"] == "resume-rewriter"
    assert rewrite.output["fact_safe"] is True
    assert rewrite.output["requirement_coverage"] == 1.0
    source_lines = {
        "Backend Engineer",
        "Designed an idempotent FastAPI workflow with PostgreSQL and Redis.",
        "Measured retry recovery and documented rollback controls.",
    }
    assert {item["text"] for item in rewrite.output["rewrite_items"]}.issubset(source_lines)
    assert all(len(item["evidence_sha256"]) == 64 for item in rewrite.output["rewrite_items"])


@pytest.mark.asyncio
async def test_harness_serializes_concurrent_execution_and_honors_exact_step_budget():
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry())
    calls = 0

    async def one_step(context: AgentContext) -> AgentDecision:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return AgentDecision.complete({"ok": True})

    harness.register_agent(AgentDefinition(id="one-step", version="0.1.0", handler=one_step))
    run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="one-step",
        objective="complete exactly one step",
        input={},
        start_agent_id="one-step",
        budget=RunBudget(max_steps=1),
    )
    first, second = await asyncio.gather(harness.execute(run.id), harness.execute(run.id))

    assert first.status == second.status == RunStatus.COMPLETED
    assert len(first.steps) == 1
    assert calls == 1

    supervisor = _harness()
    bounded = await supervisor.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="step-budget",
        objective="fail before a second step",
        input={"mode": "jd", "jd_text": "Python"},
        start_agent_id="supervisor",
        budget=RunBudget(max_steps=1),
    )
    bounded_result = await supervisor.execute(bounded.id)
    assert bounded_result.status == RunStatus.FAILED
    assert "step budget exceeded" in (bounded_result.error or "")
    assert len(bounded_result.steps) == 1


@pytest.mark.asyncio
async def test_harness_cancellation_failure_retry_and_budget_guards():
    skills = SkillRegistry()
    gateway = MCPGateway()
    store = InMemoryRunStore()
    harness = AgentHarness(gateway=gateway, skills=skills, store=store)
    attempts = 0

    async def flaky(context: AgentContext) -> AgentDecision:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return AgentDecision.complete({"ok": True}, tokens_used=1)

    harness.register_agent(AgentDefinition(id="flaky-agent", version="0.1.0", handler=flaky))
    run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="flaky",
        objective="retry",
        input={},
        start_agent_id="flaky-agent",
    )
    assert (await harness.execute(run.id)).status == RunStatus.FAILED
    retried = await harness.retry(run.id)
    assert retried.status == RunStatus.COMPLETED
    assert retried.attempts == 2
    with pytest.raises(HarnessError, match="only failed"):
        await harness.retry(run.id)

    cancelled = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="cancel",
        objective="cancel",
        input={},
        start_agent_id="flaky-agent",
    )
    await harness.cancel(cancelled.id)
    assert (await harness.execute(cancelled.id)).status == RunStatus.CANCELLED

    async def bad_handoff(context: AgentContext) -> AgentDecision:
        return AgentDecision.handoff("unknown-agent")

    harness.register_agent(
        AgentDefinition(id="bad-handoff", version="0.1.0", handler=bad_handoff, handoffs=frozenset({"other-agent"}))
    )
    bad = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="bad-handoff",
        objective="bad",
        input={},
        start_agent_id="bad-handoff",
    )
    bad_result = await harness.execute(bad.id)
    assert bad_result.status == RunStatus.FAILED
    assert "unauthorized handoff" in (bad_result.error or "")

    async def expensive(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"ok": True}, tokens_used=10)

    harness.register_agent(AgentDefinition(id="expensive-agent", version="0.1.0", handler=expensive))
    expensive_run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="expensive",
        objective="budget",
        input={},
        start_agent_id="expensive-agent",
        budget=RunBudget(max_steps=2, max_tokens=5, max_tool_calls=1, timeout_seconds=2, step_timeout_seconds=1),
    )
    expensive_result = await harness.execute(expensive_run.id)
    assert expensive_result.status == RunStatus.FAILED
    assert "token budget" in (expensive_result.error or "")

    async def slow(context: AgentContext) -> AgentDecision:
        await asyncio.sleep(0.05)
        return AgentDecision.complete({"ok": True})

    harness.register_agent(AgentDefinition(id="slow-agent", version="0.1.0", handler=slow))
    slow_run = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="slow",
        objective="timeout",
        input={},
        start_agent_id="slow-agent",
        budget=RunBudget(max_steps=2, max_tokens=5, max_tool_calls=1, timeout_seconds=1, step_timeout_seconds=0.01),
    )
    slow_result = await harness.execute(slow_run.id)
    assert slow_result.status == RunStatus.FAILED
    assert "TimeoutError" in (slow_result.error or "")

    with pytest.raises(HarnessError, match="unknown start"):
        await harness.create_run(
            user_id=uuid.uuid4(),
            idempotency_key="unknown",
            objective="unknown",
            input={},
            start_agent_id="missing-agent",
        )
    with pytest.raises(HarnessError, match="required"):
        await harness.create_run(
            user_id=uuid.uuid4(), idempotency_key=" ", objective=" ", input={}, start_agent_id="flaky-agent"
        )
    with pytest.raises(HarnessError, match="run not found"):
        await harness.get_run(uuid.uuid4())
    with pytest.raises(HarnessError, match="duplicate agent"):
        harness.register_agent(AgentDefinition(id="flaky-agent", version="0.1.1", handler=flaky))


@pytest.mark.asyncio
async def test_mcp_gateway_enforces_audience_allowlist_approval_contract_and_timeout():
    gateway = MCPGateway()
    agent = AgentDefinition(
        id="tool-agent",
        version="0.1.0",
        handler=lambda context: asyncio.sleep(0),  # type: ignore[arg-type]
        allowed_tools=frozenset({"profile.write", "profile.read", "slow.read", "invalid.output"}),
    )
    gateway.register(
        MCPTool(
            name="profile.read",
            version="0.1.0",
            handler=lambda args: {"profile": {"id": args["profile_id"]}},
            allowed_agents=frozenset({"tool-agent"}),
            required_arguments=frozenset({"profile_id"}),
            output_fields=frozenset({"profile"}),
        )
    )
    with pytest.raises(ToolAuthorizationError, match="audience"):
        await gateway.invoke(
            agent=agent,
            tool_name="profile.read",
            arguments={"profile_id": "1"},
            user_id="user-1",
            audience="user-2",
        )
    unauthorized_agent = AgentDefinition(
        id="other-agent", version="0.1.0", handler=agent.handler, allowed_tools=frozenset({"profile.read"})
    )
    with pytest.raises(ToolAuthorizationError, match="allowlisted"):
        await gateway.invoke(
            agent=unauthorized_agent,
            tool_name="profile.read",
            arguments={"profile_id": "1"},
            user_id="user-1",
            audience="user-1",
        )
    with pytest.raises(ToolContractError, match="missing tool arguments"):
        await gateway.invoke(
            agent=agent,
            tool_name="profile.read",
            arguments={},
            user_id="user-1",
            audience="user-1",
        )
    result = await gateway.invoke(
        agent=agent,
        tool_name="profile.read",
        arguments={"profile_id": "1"},
        user_id="user-1",
        audience="user-1",
    )
    assert result["profile"]["id"] == "1"

    gateway.register(
        MCPTool(
            name="profile.write",
            version="0.1.0",
            handler=lambda args: {"updated": True},
            allowed_agents=frozenset({"tool-agent"}),
            output_fields=frozenset({"updated"}),
            risk_level=RiskLevel.HIGH,
            read_only=False,
            requires_approval=True,
        )
    )
    with pytest.raises(ToolAuthorizationError, match="requires approval"):
        await gateway.invoke(
            agent=agent,
            tool_name="profile.write",
            arguments={},
            user_id="user-1",
            audience="user-1",
        )
    assert (
        await gateway.invoke(
            agent=agent,
            tool_name="profile.write",
            arguments={},
            user_id="user-1",
            audience="user-1",
            approved=True,
        )
    )["updated"]

    async def slow_tool(arguments):
        await asyncio.sleep(0.05)
        return {"value": 1}

    gateway.register(
        MCPTool(
            name="slow.read",
            version="0.1.0",
            handler=slow_tool,
            allowed_agents=frozenset({"tool-agent"}),
            output_fields=frozenset({"value"}),
            timeout_seconds=0.01,
        )
    )
    with pytest.raises(TimeoutError):
        await gateway.invoke(
            agent=agent,
            tool_name="slow.read",
            arguments={},
            user_id="user-1",
            audience="user-1",
        )
    assert gateway.invocations[-1].status == "failed"
    assert gateway.invocations[-1].error_type == "TimeoutError"
    with pytest.raises(ToolContractError, match="duplicate tool"):
        gateway.register(gateway.get("profile.read"))
    with pytest.raises(ToolContractError, match="positive"):
        gateway.register(
            MCPTool(
                name="invalid.timeout",
                version="0.1.0",
                handler=lambda args: {},
                allowed_agents=frozenset({"tool-agent"}),
                timeout_seconds=0,
            )
        )
    with pytest.raises(ToolContractError, match="finite"):
        gateway.register(
            MCPTool(
                name="invalid.nan-timeout",
                version="0.1.0",
                handler=lambda args: {},
                allowed_agents=frozenset({"tool-agent"}),
                timeout_seconds=float("nan"),
            )
        )
    gateway.register(
        MCPTool(
            name="invalid.output",
            version="0.1.0",
            handler=lambda args: {"value": float("nan")},
            allowed_agents=frozenset({"tool-agent"}),
            output_fields=frozenset({"value"}),
        )
    )
    with pytest.raises(ToolContractError, match="JSON-compatible"):
        await gateway.invoke(
            agent=agent,
            tool_name="invalid.output",
            arguments={},
            user_id="user-1",
            audience="user-1",
        )
    with pytest.raises(ToolContractError, match="unknown tool"):
        gateway.get("missing.tool")


@pytest.mark.asyncio
async def test_skill_registry_contracts_support_sync_and_async_executors():
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            id="sync-skill",
            version="0.1.0",
            required_inputs=frozenset({"value"}),
            output_fields=frozenset({"result"}),
            executor=lambda payload: {"result": payload["value"]},
        )
    )

    async def async_executor(payload):
        return {"result": payload["value"] * 2}

    registry.register(
        SkillDefinition(
            id="async-skill",
            version="0.1.0",
            required_inputs=frozenset({"value"}),
            output_fields=frozenset({"result"}),
            executor=async_executor,
        )
    )
    assert (await registry.execute("sync-skill", {"value": 2}))["result"] == 2
    assert (await registry.execute("async-skill", {"value": 2}))["result"] == 4
    with pytest.raises(SkillContractError, match="duplicate skill"):
        registry.register(registry.get("sync-skill"))
    with pytest.raises(SkillContractError, match="unknown skill"):
        registry.get("missing-skill")
    with pytest.raises(SkillContractError, match="missing skill inputs"):
        await registry.execute("sync-skill", {})

    registry.register(
        SkillDefinition(
            id="bad-output",
            version="0.1.0",
            required_inputs=frozenset(),
            output_fields=frozenset({"result"}),
            executor=lambda payload: {},
        )
    )
    with pytest.raises(SkillContractError, match="missing skill outputs"):
        await registry.execute("bad-output", {})
    registry.register(
        SkillDefinition(
            id="not-object",
            version="0.1.0",
            required_inputs=frozenset(),
            output_fields=frozenset(),
            executor=lambda payload: [],  # type: ignore[return-value]
        )
    )
    with pytest.raises(SkillContractError, match="must be a JSON-compatible object"):
        await registry.execute("not-object", {})
    registry.register(
        SkillDefinition(
            id="non-json-output",
            version="0.1.0",
            required_inputs=frozenset(),
            output_fields=frozenset({"result"}),
            executor=lambda payload: {"result": float("nan")},
        )
    )
    with pytest.raises(SkillContractError, match="JSON-compatible"):
        await registry.execute("non-json-output", {})
    with pytest.raises(SkillContractError, match="JSON-compatible"):
        await registry.execute("sync-skill", {"value": uuid.uuid4()})


def test_contract_value_guards():
    with pytest.raises(ValueError, match="max_steps"):
        RunBudget(max_steps=0)
    with pytest.raises(ValueError, match="max_steps"):
        RunBudget(max_steps=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timeouts"):
        RunBudget(timeout_seconds=0)
    with pytest.raises(ValueError, match="finite"):
        RunBudget(timeout_seconds=float("nan"))
    with pytest.raises(ValueError, match="tokens_used"):
        AgentDecision.complete({}, tokens_used=-1)
    with pytest.raises(ValueError, match="tokens_used"):
        AgentDecision.complete({}, tokens_used=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="JSON-compatible"):
        AgentDecision.complete({"value": float("nan")})
    with pytest.raises(ValueError, match="JSON-compatible"):
        AgentDecision.call_tool("profile.read", {"value": uuid.uuid4()})
    with pytest.raises(ValueError, match="handoff_to"):
        AgentDecision(kind="handoff")
    with pytest.raises(ValueError, match="tool_call"):
        AgentDecision(kind="tool")


@pytest.mark.asyncio
async def test_create_run_enforces_request_length_and_json_contracts():
    harness = AgentHarness(gateway=MCPGateway(), skills=SkillRegistry())

    async def complete(context: AgentContext) -> AgentDecision:
        return AgentDecision.complete({"run_id": str(context.run_id)})

    harness.register_agent(AgentDefinition(id="contract-agent", version="0.1.0", handler=complete))
    accepted = await harness.create_run(
        user_id=uuid.uuid4(),
        idempotency_key="k" * 128,
        objective="o" * 500,
        input={"nested": (1, 2)},
        start_agent_id="contract-agent",
    )
    assert accepted.idempotency_key == "k" * 128
    assert accepted.objective == "o" * 500
    assert accepted.input == {"nested": [1, 2]}

    with pytest.raises(HarnessError, match="128"):
        await harness.create_run(
            user_id=uuid.uuid4(),
            idempotency_key="k" * 129,
            objective="valid",
            input={},
            start_agent_id="contract-agent",
        )
    with pytest.raises(HarnessError, match="500"):
        await harness.create_run(
            user_id=uuid.uuid4(),
            idempotency_key="valid",
            objective="o" * 501,
            input={},
            start_agent_id="contract-agent",
        )
    with pytest.raises(HarnessError, match="JSON-compatible"):
        await harness.create_run(
            user_id=uuid.uuid4(),
            idempotency_key="non-json-value",
            objective="reject non-json values",
            input={"value": uuid.uuid4()},
            start_agent_id="contract-agent",
        )
    with pytest.raises(HarnessError, match="JSON-compatible"):
        await harness.create_run(
            user_id=uuid.uuid4(),
            idempotency_key="nan-value",
            objective="reject non-finite values",
            input={"value": float("nan")},
            start_agent_id="contract-agent",
        )
