#!/usr/bin/env python3
"""Run blocking project quality checks and emit a machine-readable evidence report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA_VERSION = "1.0"
MAX_CAPTURE_CHARS = 30_000


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _check_definitions(mode: str) -> dict[str, list[tuple[str, list[str], Path]]]:
    coverage_threshold = "85" if mode == "release" else "64"
    python = sys.executable
    npm = _npm_command()
    return {
        "backend": [
            (
                "backend.ruff",
                [python, "-m", "ruff", "check", "app", "tests", "scripts"],
                ROOT / "backend",
            ),
            (
                "backend.format",
                [
                    python,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "app/config.py",
                    "app/middleware.py",
                    "app/agent_platform",
                    "app/routers/agent_shadow.py",
                    "app/services/ai_context_security.py",
                    "app/services/data_contract_audit.py",
                    "app/services/interview_context_builder.py",
                    "app/services/interview_generation_service.py",
                    "app/services/interview_scoring_service.py",
                    "app/services/interview_templates.py",
                    "app/services/release_checks.py",
                    "app/services/usage_telemetry.py",
                    "app/utils/security.py",
                    "app/utils/time.py",
                ],
                ROOT / "backend",
            ),
            ("backend.mypy", [python, "-m", "mypy"], ROOT / "backend"),
            (
                "backend.pytest",
                [
                    python,
                    "-m",
                    "pytest",
                    "--cov=app",
                    "--cov-report=term-missing",
                    "--cov-report=json:artifacts/coverage/backend-coverage.json",
                    f"--cov-fail-under={coverage_threshold}",
                    "-q",
                ],
                ROOT / "backend",
            ),
            (
                "backend.pip_audit",
                [
                    python,
                    "-m",
                    "pip_audit",
                    "--local",
                    "--strict",
                    "--vulnerability-service",
                    "osv",
                    "--timeout",
                    "60",
                    "--progress-spinner",
                    "off",
                ],
                ROOT / "backend",
            ),
            (
                "backend.alembic_heads",
                [python, "-m", "alembic", "heads"],
                ROOT / "backend",
            ),
        ],
        "frontend": [
            ("frontend.lint", [npm, "run", "lint"], ROOT / "frontend"),
            ("frontend.unit", [npm, "run", "test:unit:coverage"], ROOT / "frontend"),
            ("frontend.typecheck", [npm, "run", "typecheck"], ROOT / "frontend"),
            ("frontend.build", [npm, "run", "build"], ROOT / "frontend"),
            ("frontend.audit", [npm, "audit", "--audit-level=high"], ROOT / "frontend"),
        ],
        "contracts": [
            (
                "contracts.static",
                [
                    python,
                    "-m",
                    "ruff",
                    "check",
                    "--config",
                    "backend/pyproject.toml",
                    "scripts",
                ],
                ROOT,
            ),
            (
                "contracts.format",
                [
                    python,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "--config",
                    "backend/pyproject.toml",
                    "scripts",
                ],
                ROOT,
            ),
            ("contracts.docs", [python, "scripts/validate_documentation.py"], ROOT),
            ("contracts.deploy", [python, "scripts/validate_deployment_contracts.py"], ROOT),
            (
                "contracts.openapi",
                [python, "scripts/validate_openapi_compatibility.py"],
                ROOT,
            ),
            (
                "contracts.agents",
                [python, "scripts/validate_agent_definitions.py"],
                ROOT,
            ),
            ("contracts.mcp", [python, "scripts/validate_mcp_tools.py"], ROOT),
            ("contracts.skills", [python, "scripts/validate_skills.py"], ROOT),
            (
                "agents.safety_eval",
                [
                    python,
                    "scripts/eval_agent_shadow_runtime.py",
                    "--report",
                    "artifacts/evaluation/agent-shadow-safety.json",
                ],
                ROOT,
            ),
            ("security.secrets", [python, "scripts/run_secret_scan.py"], ROOT),
        ],
    }


def _console_safe_text(value: str, *, encoding: str | None = None) -> str:
    """Return text that can be emitted by the active console without raising Unicode errors."""
    console_encoding = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(console_encoding, errors="replace").decode(console_encoding, errors="replace")


def _run_check(check_id: str, command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    stdout = completed.stdout[-MAX_CAPTURE_CHARS:]
    stderr = completed.stderr[-MAX_CAPTURE_CHARS:]
    print(f"[{check_id}] {'PASS' if completed.returncode == 0 else 'FAIL'} ({duration_ms} ms)")
    if completed.returncode != 0:
        if stdout:
            print(_console_safe_text(stdout))
        if stderr:
            print(
                _console_safe_text(stderr, encoding=getattr(sys.stderr, "encoding", None)),
                file=sys.stderr,
            )
    return {
        "id": check_id,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": shlex.join(command),
        "cwd": cwd.relative_to(ROOT).as_posix() or ".",
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "stdout_tail": stdout,
        "stderr_tail": stderr,
    }


def _run_git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
        capture_output=True,
        check=False,
    )


def _git_evidence() -> dict[str, Any]:
    sha_result = _run_git("rev-parse", "HEAD", text=True)
    status_result = _run_git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    diff_result = _run_git("diff", "--binary", "HEAD")
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None
    status_bytes = status_result.stdout if status_result.returncode == 0 else b""
    diff_bytes = diff_result.stdout if diff_result.returncode == 0 else b""
    fingerprint = hashlib.sha256()
    fingerprint.update(status_bytes)
    fingerprint.update(diff_bytes)

    untracked_paths: list[str] = []
    for record in status_bytes.split(b"\0"):
        if not record.startswith(b"?? "):
            continue
        relative = record[3:].decode("utf-8", errors="replace")
        untracked_paths.append(relative)
        path = ROOT / relative
        fingerprint.update(relative.encode("utf-8"))
        if path.is_file():
            try:
                fingerprint.update(path.read_bytes())
            except OSError:
                fingerprint.update(b"<unreadable>")

    return {
        "sha": sha,
        "dirty": bool(status_bytes),
        "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        "worktree_sha256": fingerprint.hexdigest(),
        "untracked_file_count": len(untracked_paths),
    }


def _write_report(payload: dict[str, Any], requested_path: str | None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = (
        Path(requested_path)
        if requested_path
        else ROOT / "artifacts" / "quality-gate" / f"{timestamp}-{payload['profile']}-{payload['mode']}.json"
    )
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["backend", "frontend", "contracts", "all"], default="all")
    parser.add_argument("--mode", choices=["ci", "release"], default="ci")
    parser.add_argument(
        "--report",
        help="Explicit JSON report path. Defaults to an immutable timestamped path.",
    )
    args = parser.parse_args()

    definitions = _check_definitions(args.mode)
    profiles = ["backend", "frontend", "contracts"] if args.profile == "all" else [args.profile]
    checks = [
        _run_check(check_id, command, cwd) for profile in profiles for check_id, command, cwd in definitions[profile]
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    git_evidence = _git_evidence()
    payload: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": ROOT.name,
        "git_sha": git_evidence["sha"],
        "git_worktree": git_evidence,
        "profile": args.profile,
        "mode": args.mode,
        "status": status,
        "policy": {
            "backend_line_coverage_minimum": 85 if args.mode == "release" else 64,
            "fail_fast": False,
            "blocking": True,
        },
        "checks": checks,
    }
    report_path = _write_report(payload, args.report)
    print(f"Quality report: {report_path}")
    print(f"Overall status: {status.upper()}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
