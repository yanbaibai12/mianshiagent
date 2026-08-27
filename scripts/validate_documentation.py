#!/usr/bin/env python3
"""Validate repository Markdown links and documentation hygiene."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")
REQUIRED_INDEX_TARGETS = {
    "AGENT_PLATFORM_DEVELOPMENT_SPEC.md",
    "QUALITY_GATE_STANDARD.md",
    "RESUME_REWRITE_EVALUATION.md",
    "AGENT_SHADOW_API.md",
    "KNOWN_ISSUES.md",
}


def _markdown_files(root: Path) -> list[Path]:
    files = [root / "README.md"]
    files.extend(sorted((root / "docs").rglob("*.md")))
    return [path for path in files if path.is_file() and not path.is_symlink()]


def _local_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    else:
        target = target.split(maxsplit=1)[0]
    if not target or target.startswith(EXTERNAL_PREFIXES):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return target or None


def validate_markdown_file(path: Path, *, root: Path) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{relative}: cannot read UTF-8 Markdown: {type(exc).__name__}"]

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line != line.rstrip():
            errors.append(f"{relative}:{line_number}: trailing whitespace")

    for raw_target in LINK_PATTERN.findall(text):
        target = _local_target(raw_target)
        if target is None:
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{relative}: link escapes repository: {raw_target}")
            continue
        if not resolved.exists():
            errors.append(f"{relative}: missing local link target: {raw_target}")
    return errors


def validate_documentation(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    files = _markdown_files(root)
    if not files:
        return ["no Markdown documentation files found"]
    for path in files:
        errors.extend(validate_markdown_file(path, root=root))

    index_path = root / "docs" / "README.md"
    try:
        index_text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"docs/README.md cannot be read: {type(exc).__name__}")
    else:
        for target in sorted(REQUIRED_INDEX_TARGETS):
            if f"({f'./{target}'})" not in index_text:
                errors.append(f"docs/README.md missing required index target: {target}")

    for archived_name in ("ENTERPRISE_ROADMAP.md", "PRODUCT_STRATEGY.md"):
        archived_path = root / "docs" / archived_name
        try:
            header = "\n".join(archived_path.read_text(encoding="utf-8").splitlines()[:8])
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"docs/{archived_name} cannot be read: {type(exc).__name__}")
            continue
        if "Archived / Superseded" not in header:
            errors.append(f"docs/{archived_name} must be explicitly marked Archived / Superseded")
    return errors


def main() -> int:
    errors = validate_documentation()
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "failed" if errors else "passed",
        "document_count": len(_markdown_files(ROOT)),
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
