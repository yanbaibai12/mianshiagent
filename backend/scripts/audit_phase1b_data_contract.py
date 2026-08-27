#!/usr/bin/env python3
"""Run the non-destructive Phase 1B historical data-contract readiness audit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base
from app.services.data_contract_audit import build_phase1b_data_contract_audit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = BACKEND_ROOT / "artifacts" / "data-contract"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Phase 1B ownership and historical-data migration readiness without mutating the database."
    )
    parser.add_argument("--database-url", help="Override DATABASE_URL for this audit only.")
    parser.add_argument("--report", type=Path, help="JSON evidence path. Defaults to a timestamped backend artifact.")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Return success even when migration blockers are found. Schema/read failures still fail closed.",
    )
    return parser.parse_args()


def _default_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORT_DIR / f"phase1b-data-contract-audit-{timestamp}.json"


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_database_url(message: str, database_url: str) -> str:
    """Remove raw and SQLAlchemy-rendered database URLs from failure evidence."""
    candidates = {database_url}
    try:
        parsed = make_url(database_url)
        candidates.add(parsed.render_as_string(hide_password=False))
        candidates.add(parsed.render_as_string(hide_password=True))
    except Exception:
        pass

    sanitized = message
    for candidate in sorted((item for item in candidates if item), key=len, reverse=True):
        sanitized = sanitized.replace(candidate, "<redacted-database-url>")
    return sanitized


async def _database_table_names(connection: AsyncConnection) -> set[str]:
    return set(await connection.run_sync(lambda sync_connection: inspect(sync_connection).get_table_names()))


async def _run(database_url: str) -> dict[str, Any]:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as connection:
            actual_tables = await _database_table_names(connection)
        expected_tables = set(Base.metadata.tables)
        missing_tables = sorted(expected_tables - actual_tables)
        if missing_tables:
            raise RuntimeError(
                "Database schema is missing expected tables: "
                + ", ".join(missing_tables)
                + ". Run Alembic upgrade and verify the target database before Phase 1B auditing."
            )

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            report = await build_phase1b_data_contract_audit(
                session,
                database_dialect=engine.dialect.name,
            )
        report["expected_table_count"] = len(expected_tables)
        report["unexpected_tables"] = sorted(actual_tables - expected_tables - {"alembic_version"})
        report["evidence_sha256"] = _canonical_hash(report)
        return report
    finally:
        await engine.dispose()


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def _main() -> int:
    args = _arguments()
    database_url = args.database_url or get_settings().DATABASE_URL
    report_path = args.report or _default_report_path()
    try:
        payload = await _run(database_url)
    except Exception as exc:
        failure = {
            "schema_version": "1.0",
            "phase": "phase-1b-historical-data-contract",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "status": "failed",
            "migration_readiness": "unknown",
            "error_type": type(exc).__name__,
            "error": _redact_database_url(str(exc), database_url),
        }
        failure["evidence_sha256"] = _canonical_hash(failure)
        _write_report(report_path, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        print(f"Audit report: {report_path.resolve()}", file=sys.stderr)
        return 2

    _write_report(report_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Audit report: {report_path.resolve()}")
    if payload["status"] == "blocked" and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
