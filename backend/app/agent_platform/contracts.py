from __future__ import annotations

import json
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from app.utils.time import utc_now


def canonical_json_object(value: object, *, label: str) -> dict[str, Any]:
    """Return a detached, strict-JSON object or reject an unsafe runtime value."""
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a JSON-compatible object") from exc
    if not isinstance(normalized, dict):
        raise ValueError(f"{label} must be a JSON-compatible object")
    return normalized


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RunBudget:
    max_steps: int = 12
    max_tokens: int = 12_000
    max_tool_calls: int = 8
    timeout_seconds: float = 60.0
    step_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name in ("max_steps", "max_tokens", "max_tool_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or isinstance(self.step_timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not isinstance(self.step_timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not math.isfinite(self.step_timeout_seconds)
            or self.timeout_seconds <= 0
            or self.step_timeout_seconds <= 0
        ):
            raise ValueError("timeouts must be finite and positive")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    approved: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool call name is required")
        object.__setattr__(self, "arguments", canonical_json_object(self.arguments, label="tool arguments"))


@dataclass(frozen=True)
class AgentDecision:
    kind: Literal["complete", "handoff", "tool"]
    output: dict[str, Any] = field(default_factory=dict)
    handoff_to: str | None = None
    tool_call: ToolCall | None = None
    tokens_used: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.tokens_used, bool) or not isinstance(self.tokens_used, int) or self.tokens_used < 0:
            raise ValueError("tokens_used must not be negative")
        object.__setattr__(self, "output", canonical_json_object(self.output, label="agent output"))
        if self.kind == "handoff" and not self.handoff_to:
            raise ValueError("handoff decision requires handoff_to")
        if self.kind == "tool" and self.tool_call is None:
            raise ValueError("tool decision requires tool_call")

    @classmethod
    def complete(cls, output: dict[str, Any], *, tokens_used: int = 0) -> AgentDecision:
        return cls(kind="complete", output=output, tokens_used=tokens_used)

    @classmethod
    def handoff(cls, agent_id: str, *, output: dict[str, Any] | None = None, tokens_used: int = 0) -> AgentDecision:
        return cls(kind="handoff", handoff_to=agent_id, output=output or {}, tokens_used=tokens_used)

    @classmethod
    def call_tool(
        cls, name: str, arguments: dict[str, Any], *, approved: bool = False, tokens_used: int = 0
    ) -> AgentDecision:
        return cls(
            kind="tool",
            tool_call=ToolCall(name=name, arguments=arguments, approved=approved),
            tokens_used=tokens_used,
        )


@dataclass
class AgentStep:
    id: uuid.UUID
    sequence: int
    agent_id: str
    status: StepStatus = StepStatus.RUNNING
    decision_kind: str | None = None
    tokens_used: int = 0
    error: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None


@dataclass
class AgentRun:
    id: uuid.UUID
    user_id: uuid.UUID
    idempotency_key: str
    request_fingerprint: str
    objective: str
    input: dict[str, Any]
    current_agent_id: str
    budget: RunBudget
    status: RunStatus = RunStatus.QUEUED
    tokens_used: int = 0
    tool_calls: int = 0
    attempts: int = 1
    cancel_requested: bool = False
    output: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    steps: list[AgentStep] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class AgentContext:
    run_id: uuid.UUID
    user_id: uuid.UUID
    objective: str
    input: dict[str, Any]
    state: dict[str, Any]
    previous_output: dict[str, Any]
    tool_result: dict[str, Any] | None
    execute_skill: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


AgentHandler = Callable[[AgentContext], Awaitable[AgentDecision]]


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    version: str
    handler: AgentHandler
    allowed_tools: frozenset[str] = frozenset()
    handoffs: frozenset[str] = frozenset()
