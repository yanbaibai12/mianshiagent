#!/usr/bin/env python3
"""Validate the versioned Agent registry without claiming planned Agents are implemented."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "agent-registry.json"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
ENTRYPOINT_PATTERN = re.compile(
    r"^(?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.py):(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)$"
)
TOOL_REF_PATTERN = re.compile(r"^[a-z][a-z0-9._:/-]{1,127}$")
REQUIRED_FIELDS = {
    "id",
    "version",
    "owner",
    "description",
    "entrypoint",
    "allowed_tools",
    "max_steps",
    "max_tokens",
    "handoffs",
}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_repository_path(root: Path, relative_path: str) -> Path | None:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _entrypoint_error(value: Any, root: Path) -> str | None:
    if not isinstance(value, str):
        return "must be a string in repository/path.py:symbol format"
    match = ENTRYPOINT_PATTERN.fullmatch(value)
    if match is None:
        return "must use repository/path.py:symbol format"
    file_path = _resolve_repository_path(root, match.group("path"))
    if file_path is None:
        return "must stay within the repository"
    if not file_path.is_file() or file_path.is_symlink():
        return f"file does not exist: {match.group('path')}"
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return f"file cannot be parsed: {type(exc).__name__}"
    symbol = match.group("symbol")
    defined_symbols = {
        node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if symbol not in defined_symbols:
        return f"callable symbol is not defined at module scope: {symbol}"
    return None


def _validate_string_list(
    value: Any,
    *,
    location: str,
    pattern: re.Pattern[str],
    errors: list[str],
) -> None:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not pattern.fullmatch(item):
            errors.append(f"{location}[{index}] is invalid")
        elif item in seen:
            errors.append(f"{location} contains duplicate value: {item}")
        else:
            seen.add(item)


def validate_registry(data: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    status = data.get("status")
    agents = data.get("agents")
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    for field in ("phase", "owner"):
        if not _is_non_empty_string(data.get(field)):
            errors.append(f"{field} must be a non-empty string")
    if status not in {"planned", "active"}:
        errors.append("status must be planned or active")
    if not isinstance(agents, list):
        errors.append("agents must be an array")
        agents = []
    if status == "planned" and agents:
        errors.append("planned registry must not contain definitions that look active")
    if status == "active" and not agents:
        errors.append("active registry must contain at least one Agent")

    known_agent_ids = {
        agent.get("id")
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("id"), str) and ID_PATTERN.fullmatch(agent["id"])
    }
    seen: set[str] = set()
    for index, agent in enumerate(agents):
        location = f"agents[{index}]"
        if not isinstance(agent, dict):
            errors.append(f"{location} must be an object")
            continue
        missing = REQUIRED_FIELDS - set(agent)
        if missing:
            errors.append(f"{location} missing fields: {sorted(missing)}")
        agent_id = agent.get("id")
        if not isinstance(agent_id, str) or not ID_PATTERN.fullmatch(agent_id):
            errors.append(f"{location}.id is invalid")
        elif agent_id in seen:
            errors.append(f"duplicate agent id: {agent_id}")
        else:
            seen.add(agent_id)
        if not isinstance(agent.get("version"), str) or not SEMVER_PATTERN.fullmatch(agent["version"]):
            errors.append(f"{location}.version must be SemVer")
        for field in ("owner", "description"):
            if not _is_non_empty_string(agent.get(field)):
                errors.append(f"{location}.{field} must be a non-empty string")
        entrypoint_error = _entrypoint_error(agent.get("entrypoint"), root)
        if entrypoint_error:
            errors.append(f"{location}.entrypoint {entrypoint_error}")
        for field in ("max_steps", "max_tokens"):
            value = agent.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"{location}.{field} must be a positive integer")
        _validate_string_list(
            agent.get("allowed_tools"),
            location=f"{location}.allowed_tools",
            pattern=TOOL_REF_PATTERN,
            errors=errors,
        )
        _validate_string_list(
            agent.get("handoffs"),
            location=f"{location}.handoffs",
            pattern=ID_PATTERN,
            errors=errors,
        )
        handoffs = agent.get("handoffs")
        if isinstance(handoffs, list):
            for handoff_index, handoff in enumerate(handoffs):
                if not isinstance(handoff, str) or not ID_PATTERN.fullmatch(handoff):
                    continue
                handoff_location = f"{location}.handoffs[{handoff_index}]"
                if handoff == agent_id:
                    errors.append(f"{handoff_location} must not reference the same agent")
                elif handoff not in known_agent_ids:
                    errors.append(f"{handoff_location} references unknown agent: {handoff}")
    return errors


def _load_registry() -> tuple[dict[str, Any], list[str]]:
    if not REGISTRY.exists():
        return {}, ["agent registry is missing"]
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"agent registry cannot be read: {type(exc).__name__}"]
    if not isinstance(data, dict):
        return {}, ["agent registry root must be an object"]
    return data, []


def main() -> int:
    data, errors = _load_registry()
    errors.extend(validate_registry(data))
    status = data.get("status")
    agents = data.get("agents")
    agent_count = len(agents) if isinstance(agents, list) else 0
    payload = {
        "schema_version": "1.0",
        "status": "failed" if errors else ("planned" if status == "planned" else "passed"),
        "registry_status": status,
        "agent_count": agent_count,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
