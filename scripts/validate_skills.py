#!/usr/bin/env python3
"""Validate the Skill registry and referenced SKILL.md files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "skills-registry.json"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
REQUIRED_FIELDS = {"id", "version", "owner", "path", "description", "inputs", "outputs", "risk_level"}


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


def _validate_contract_fields(value: Any, *, location: str, is_input: bool, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return
    if not value:
        errors.append(f"{location} must contain at least one field")
        return
    seen: set[str] = set()
    required_fields = {"name", "type", "description"} | ({"required"} if is_input else set())
    for index, item in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_location} must be an object")
            continue
        missing = required_fields - set(item)
        if missing:
            errors.append(f"{item_location} missing fields: {sorted(missing)}")
        name = item.get("name")
        if not isinstance(name, str) or not FIELD_NAME_PATTERN.fullmatch(name):
            errors.append(f"{item_location}.name is invalid")
        elif name in seen:
            errors.append(f"{location} contains duplicate field: {name}")
        else:
            seen.add(name)
        for field in ("type", "description"):
            if not _is_non_empty_string(item.get(field)):
                errors.append(f"{item_location}.{field} must be a non-empty string")
        if is_input and not isinstance(item.get("required"), bool):
            errors.append(f"{item_location}.required must be a boolean")


def validate_registry(data: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    status = data.get("status")
    skills = data.get("skills")
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    for field in ("phase", "owner"):
        if not _is_non_empty_string(data.get(field)):
            errors.append(f"{field} must be a non-empty string")
    if status not in {"planned", "active"}:
        errors.append("status must be planned or active")
    if not isinstance(skills, list):
        errors.append("skills must be an array")
        skills = []
    if status == "planned" and skills:
        errors.append("planned registry must not contain definitions that look active")
    if status == "active" and not skills:
        errors.append("active registry must contain at least one Skill")

    seen: set[str] = set()
    for index, skill in enumerate(skills):
        location = f"skills[{index}]"
        if not isinstance(skill, dict):
            errors.append(f"{location} must be an object")
            continue
        missing = REQUIRED_FIELDS - set(skill)
        if missing:
            errors.append(f"{location} missing fields: {sorted(missing)}")
        skill_id = skill.get("id")
        if not isinstance(skill_id, str) or not ID_PATTERN.fullmatch(skill_id):
            errors.append(f"{location}.id is invalid")
        elif skill_id in seen:
            errors.append(f"duplicate skill id: {skill_id}")
        else:
            seen.add(skill_id)
        if not isinstance(skill.get("version"), str) or not SEMVER_PATTERN.fullmatch(skill["version"]):
            errors.append(f"{location}.version must be SemVer")
        for field in ("owner", "description"):
            if not _is_non_empty_string(skill.get(field)):
                errors.append(f"{location}.{field} must be a non-empty string")
        if skill.get("risk_level") not in {"low", "medium", "high"}:
            errors.append(f"{location}.risk_level is invalid")

        path_value = skill.get("path")
        if isinstance(path_value, str) and path_value.strip():
            skill_path = _resolve_repository_path(root, path_value)
            if skill_path is None:
                errors.append(f"{location}.path must stay within the repository")
            elif skill_path.is_symlink() or not skill_path.is_dir():
                errors.append(f"{location}.path is not an existing directory: {path_value}")
            else:
                if isinstance(skill_id, str) and skill_path.name != skill_id:
                    errors.append(f"{location}.path directory must match skill id")
                skill_file = skill_path / "SKILL.md"
                if not skill_file.is_file() or skill_file.is_symlink():
                    errors.append(f"{location} missing SKILL.md: {path_value}/SKILL.md")
                else:
                    try:
                        if not skill_file.read_text(encoding="utf-8").strip():
                            errors.append(f"{location} SKILL.md must not be empty")
                    except (OSError, UnicodeDecodeError) as exc:
                        errors.append(f"{location} SKILL.md cannot be read: {type(exc).__name__}")
        else:
            errors.append(f"{location}.path must be a non-empty string")

        _validate_contract_fields(skill.get("inputs"), location=f"{location}.inputs", is_input=True, errors=errors)
        _validate_contract_fields(skill.get("outputs"), location=f"{location}.outputs", is_input=False, errors=errors)
    return errors


def _load_registry() -> tuple[dict[str, Any], list[str]]:
    if not REGISTRY.exists():
        return {}, ["skills registry is missing"]
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"skills registry cannot be read: {type(exc).__name__}"]
    if not isinstance(data, dict):
        return {}, ["skills registry root must be an object"]
    return data, []


def main() -> int:
    data, errors = _load_registry()
    errors.extend(validate_registry(data))
    status = data.get("status")
    skills = data.get("skills")
    skill_count = len(skills) if isinstance(skills, list) else 0
    payload = {
        "schema_version": "1.0",
        "status": "failed" if errors else ("planned" if status == "planned" else "passed"),
        "registry_status": status,
        "skill_count": skill_count,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
