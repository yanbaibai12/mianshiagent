#!/usr/bin/env python3
"""Validate deployment configuration against the repository runtime and safety contract."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE_PATTERN = re.compile(r"^FROM\s+python:(?P<version>\d+\.\d+)(?:[-@]|$)", re.MULTILINE)


def _read_text(path: Path, errors: list[str], label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{label} cannot be read as UTF-8: {type(exc).__name__}")
        return ""


def validate_deployment_contracts(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    pyproject_path = root / "backend" / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        runtime_version = str(pyproject["tool"]["mypy"]["python_version"])
    except (
        OSError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        errors.append(f"backend/pyproject.toml runtime version is unreadable: {type(exc).__name__}")
        runtime_version = ""

    dockerfile = _read_text(root / "backend" / "Dockerfile", errors, "backend/Dockerfile")
    image_match = PYTHON_IMAGE_PATTERN.search(dockerfile)
    if image_match is None:
        errors.append("backend/Dockerfile must use a versioned official python:<major.minor> image")
    elif runtime_version and image_match.group("version") != runtime_version:
        errors.append(
            "backend/Dockerfile Python version "
            f"{image_match.group('version')} does not match pyproject runtime {runtime_version}"
        )

    production_env = _read_text(
        root / "backend" / ".env.production.example",
        errors,
        "backend/.env.production.example",
    )
    if not re.search(r"^AGENT_SHADOW_API_ENABLED=false$", production_env, re.MULTILINE):
        errors.append("backend/.env.production.example must fail closed with AGENT_SHADOW_API_ENABLED=false")
    if not re.search(r"^AGENT_RUN_STORE_BACKEND=postgresql$", production_env, re.MULTILINE):
        errors.append("backend/.env.production.example must use AGENT_RUN_STORE_BACKEND=postgresql")
    if not re.search(r"^DATABASE_URL=postgresql\+asyncpg://", production_env, re.MULTILINE):
        errors.append("backend/.env.production.example must use a postgresql+asyncpg DATABASE_URL")

    compose = _read_text(root / "docker-compose.yml", errors, "docker-compose.yml")
    for required_fragment in (
        "postgres:16",
        "  migrate:",
        "  backend:",
        "  worker:",
        "  frontend:",
    ):
        if required_fragment not in compose:
            errors.append(f"docker-compose.yml missing required deployment fragment: {required_fragment.strip()}")
    if not re.search(r'^\s+AGENT_SHADOW_API_ENABLED:\s*["\']?false["\']?\s*$', compose, re.MULTILINE):
        errors.append("docker-compose.yml must explicitly keep AGENT_SHADOW_API_ENABLED=false")
    if not re.search(
        r'^\s+AGENT_RUN_STORE_BACKEND:\s*["\']?postgresql["\']?\s*$',
        compose,
        re.MULTILINE,
    ):
        errors.append("docker-compose.yml must explicitly use AGENT_RUN_STORE_BACKEND=postgresql")
    if not re.search(r"^\s+DATABASE_URL:\s*postgresql\+asyncpg://", compose, re.MULTILINE):
        errors.append("docker-compose.yml backend DATABASE_URL must use postgresql+asyncpg")

    gitignore = _read_text(root / ".gitignore", errors, ".gitignore")
    if not re.search(r"^/artifacts/$", gitignore, re.MULTILINE):
        errors.append(".gitignore must exclude root /artifacts/ quality evidence")
    return errors


def main() -> int:
    errors = validate_deployment_contracts()
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "failed" if errors else "passed",
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
