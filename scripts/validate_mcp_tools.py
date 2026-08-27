#!/usr/bin/env python3
"""Validate the versioned in-process MCP tool registry and Agent allowlists."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "mcp-tool-registry.json"
AGENT_REGISTRY = ROOT / "quality" / "agent-registry.json"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
REQUIRED_FIELDS = {
    "name",
    "version",
    "owner",
    "description",
    "risk_level",
    "read_only",
    "requires_approval",
    "allowed_agents",
    "required_arguments",
    "output_fields",
}


def _string_list(value: Any, *, pattern: re.Pattern[str], location: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not pattern.fullmatch(item):
            errors.append(f"{location}[{index}] is invalid")
        elif item in result:
            errors.append(f"{location} contains duplicate value: {item}")
        else:
            result.append(item)
    return result


def validate_registry(data: dict[str, Any], *, known_agents: set[str]) -> list[str]:
    errors: list[str] = []
    tools = data.get("tools")
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if data.get("status") not in {"planned", "active"}:
        errors.append("status must be planned or active")
    for field in ("phase", "owner"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if not isinstance(tools, list):
        errors.append("tools must be an array")
        tools = []
    if data.get("status") == "active" and not tools:
        errors.append("active registry must contain at least one tool")
    if data.get("status") == "planned" and tools:
        errors.append("planned registry must not contain active tool definitions")

    seen: set[str] = set()
    for index, tool in enumerate(tools):
        location = f"tools[{index}]"
        if not isinstance(tool, dict):
            errors.append(f"{location} must be an object")
            continue
        missing = REQUIRED_FIELDS - tool.keys()
        if missing:
            errors.append(f"{location} missing fields: {sorted(missing)}")
        name = tool.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            errors.append(f"{location}.name is invalid")
        elif name in seen:
            errors.append(f"duplicate tool name: {name}")
        else:
            seen.add(name)
        if not isinstance(tool.get("version"), str) or not SEMVER_PATTERN.fullmatch(tool["version"]):
            errors.append(f"{location}.version must be SemVer")
        for field in ("owner", "description"):
            if not isinstance(tool.get(field), str) or not tool[field].strip():
                errors.append(f"{location}.{field} must be a non-empty string")
        if tool.get("risk_level") not in {"low", "medium", "high"}:
            errors.append(f"{location}.risk_level is invalid")
        for field in ("read_only", "requires_approval"):
            if not isinstance(tool.get(field), bool):
                errors.append(f"{location}.{field} must be a boolean")
        if tool.get("read_only") is False and tool.get("requires_approval") is not True:
            errors.append(f"{location} write-capable tools must require approval")
        agents = _string_list(
            tool.get("allowed_agents"), pattern=ID_PATTERN, location=f"{location}.allowed_agents", errors=errors
        )
        if not agents:
            errors.append(f"{location}.allowed_agents must not be empty")
        for agent_id in agents:
            if agent_id not in known_agents:
                errors.append(f"{location}.allowed_agents references unknown agent: {agent_id}")
        _string_list(
            tool.get("required_arguments"),
            pattern=FIELD_PATTERN,
            location=f"{location}.required_arguments",
            errors=errors,
        )
        outputs = _string_list(
            tool.get("output_fields"), pattern=FIELD_PATTERN, location=f"{location}.output_fields", errors=errors
        )
        if not outputs:
            errors.append(f"{location}.output_fields must not be empty")
    return errors


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} root must be an object")
    return data


def main() -> int:
    try:
        data = _load(REGISTRY)
        agents_data = _load(AGENT_REGISTRY)
        known_agents = {
            item.get("id")
            for item in agents_data.get("agents", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        errors = validate_registry(data, known_agents=known_agents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [f"MCP registry cannot be read: {type(exc).__name__}: {exc}"]
        data = {}
    payload = {
        "schema_version": "1.0",
        "status": "failed" if errors else ("planned" if data.get("status") == "planned" else "passed"),
        "registry_status": data.get("status"),
        "tool_count": len(data.get("tools", [])) if isinstance(data.get("tools"), list) else 0,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
