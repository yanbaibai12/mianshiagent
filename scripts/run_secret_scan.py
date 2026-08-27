#!/usr/bin/env python3
"""Scan repository text files for high-confidence credential patterns."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 2 * 1024 * 1024
EXCLUDED_PARTS = {".git", ".venv", ".venv-codex", "node_modules", "dist", "coverage", "artifacts"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-(?!(?:test|fake|example|placeholder)(?:-|_))(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}


def _candidate_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        names = [item for item in completed.stdout.decode("utf-8", errors="ignore").split("\0") if item]
        return [ROOT / name for name in names]
    return [path for path in ROOT.rglob("*") if path.is_file()]


def _scan(path: Path) -> list[dict[str, object]] | None:
    try:
        if (
            path.is_symlink()
            or any(part in EXCLUDED_PARTS for part in path.parts)
            or path.stat().st_size > MAX_FILE_SIZE
        ):
            return None
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    findings: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if "secret-scan: allow" in line:
            continue
        for pattern_id, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(
                    {
                        "rule": pattern_id,
                        "path": path.relative_to(ROOT).as_posix(),
                        "line": line_number,
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    candidates = _candidate_files()
    findings: list[dict[str, object]] = []
    files_scanned = 0
    files_skipped = 0
    for path in candidates:
        if not path.exists():
            files_skipped += 1
            continue
        result = _scan(path)
        if result is None:
            files_skipped += 1
            continue
        files_scanned += 1
        findings.extend(result)
    payload = {
        "schema_version": "1.0",
        "status": "passed" if not findings else "failed",
        "candidate_file_count": len(candidates),
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "findings": findings,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
