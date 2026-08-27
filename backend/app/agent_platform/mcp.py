from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent_platform.contracts import AgentDefinition, RiskLevel, canonical_json_object

ToolHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class ToolAuthorizationError(PermissionError):
    """Raised when a tool invocation violates the MCP authorization policy."""


class ToolContractError(ValueError):
    """Raised when a tool request or response violates its contract."""


@dataclass(frozen=True)
class MCPTool:
    name: str
    version: str
    handler: ToolHandler
    allowed_agents: frozenset[str]
    required_arguments: frozenset[str] = frozenset()
    output_fields: frozenset[str] = frozenset()
    risk_level: RiskLevel = RiskLevel.LOW
    read_only: bool = True
    requires_approval: bool = False
    timeout_seconds: float = 10.0


@dataclass
class MCPInvocation:
    tool_name: str
    agent_id: str
    user_id: str
    status: str
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPGateway:
    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}
        self.invocations: list[MCPInvocation] = []

    def register(self, tool: MCPTool) -> None:
        if tool.name in self._tools:
            raise ToolContractError(f"duplicate tool: {tool.name}")
        if (
            isinstance(tool.timeout_seconds, bool)
            or not isinstance(tool.timeout_seconds, (int, float))
            or not math.isfinite(tool.timeout_seconds)
            or tool.timeout_seconds <= 0
        ):
            raise ToolContractError("tool timeout must be finite and positive")
        self._tools[tool.name] = tool

    def get(self, name: str) -> MCPTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolContractError(f"unknown tool: {name}") from exc

    async def invoke(
        self,
        *,
        agent: AgentDefinition,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str,
        audience: str,
        approved: bool = False,
    ) -> dict[str, Any]:
        tool = self.get(tool_name)
        try:
            normalized_arguments = canonical_json_object(arguments, label="tool arguments")
        except ValueError as exc:
            raise ToolContractError(str(exc)) from exc
        record = MCPInvocation(tool_name=tool_name, agent_id=agent.id, user_id=user_id, status="started")
        self.invocations.append(record)
        try:
            if audience != user_id:
                raise ToolAuthorizationError("tool audience does not match run user")
            if tool_name not in agent.allowed_tools or agent.id not in tool.allowed_agents:
                raise ToolAuthorizationError("tool is not allowlisted for this agent")
            if (tool.requires_approval or tool.risk_level == RiskLevel.HIGH or not tool.read_only) and not approved:
                raise ToolAuthorizationError("tool invocation requires approval")
            missing = tool.required_arguments - normalized_arguments.keys()
            if missing:
                raise ToolContractError(f"missing tool arguments: {sorted(missing)}")
            if inspect.iscoroutinefunction(tool.handler):
                result = await asyncio.wait_for(tool.handler(normalized_arguments), timeout=tool.timeout_seconds)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(tool.handler, normalized_arguments), timeout=tool.timeout_seconds
                )
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=tool.timeout_seconds)
            try:
                result = canonical_json_object(result, label="tool output")
            except ValueError as exc:
                raise ToolContractError(str(exc)) from exc
            missing_output = tool.output_fields - result.keys()
            if missing_output:
                raise ToolContractError(f"missing tool outputs: {sorted(missing_output)}")
            record.status = "completed"
            record.metadata = {"read_only": tool.read_only, "risk_level": tool.risk_level.value}
            return result
        except Exception as exc:
            record.status = "failed"
            record.error_type = type(exc).__name__
            raise
