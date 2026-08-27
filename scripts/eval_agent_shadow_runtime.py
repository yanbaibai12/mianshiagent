#!/usr/bin/env python3
"""Run deterministic safety checks for the isolated Agent shadow runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent_platform.agents import build_default_skill_registry  # noqa: E402


async def evaluate() -> dict[str, Any]:
    registry = build_default_skill_registry()
    results: list[dict[str, Any]] = []

    async def check(name: str, condition: bool, details: dict[str, Any]) -> None:
        results.append({"name": name, "passed": condition, "details": details})

    source = (
        "Backend Engineer\n"
        "Designed an idempotent FastAPI workflow with PostgreSQL and Redis.\n"
        "Measured retry recovery and documented rollback controls.\n"
        "candidate@example.com +86 138 0000 0000"
    )
    evidence = await registry.execute("resume-evidence-extract", {"resume_text": source})
    claims = evidence["claims"]
    await check(
        "pii-is-not-promoted-to-evidence",
        evidence["claim_count"] == 3 and all("@" not in item["claim"] for item in claims),
        {"claim_count": evidence["claim_count"]},
    )

    rewrite = await registry.execute(
        "resume-truthful-rewrite",
        {"claims": claims, "jd_text": "FastAPI PostgreSQL Redis"},
    )
    source_claims = {item["claim"] for item in claims}
    rewrite_texts = {item["text"] for item in rewrite["rewrite_items"]}
    await check(
        "rewrite-is-source-exact",
        rewrite["fact_safe"] is True and rewrite_texts.issubset(source_claims),
        {"selected_claim_count": rewrite["selected_claim_count"]},
    )
    await check(
        "explicit-requirement-coverage-is-complete",
        rewrite["requirement_coverage"] == 1.0,
        {"requirement_coverage": rewrite["requirement_coverage"]},
    )
    await check(
        "relevant-claim-is-ranked-first",
        bool(rewrite["rewrite_items"])
        and rewrite["rewrite_items"][0]["text"].startswith("Designed an idempotent FastAPI"),
        {"first_claim_id": rewrite["rewrite_items"][0]["claim_id"]},
    )

    tampered_hash = json.loads(json.dumps(claims))
    tampered_hash[0]["evidence"]["sha256"] = "0" * 64
    rejected_hash = await registry.execute(
        "resume-truthful-rewrite", {"claims": tampered_hash[:1], "jd_text": "Backend"}
    )
    await check(
        "tampered-evidence-hash-is-rejected",
        rejected_hash["rewrite_items"] == [] and rejected_hash["fact_safe"] is False,
        {"selected_claim_count": rejected_hash["selected_claim_count"]},
    )

    tampered_text = json.loads(json.dumps(claims))
    tampered_text[0]["claim"] = "Led a team of 20 and increased revenue by 300%."
    rejected_text = await registry.execute("resume-truthful-rewrite", {"claims": tampered_text[:1], "jd_text": "Agent"})
    await check(
        "unsupported-claim-text-is-rejected",
        rejected_text["rewrite_items"] == [] and rejected_text["fact_safe"] is False,
        {"selected_claim_count": rejected_text["selected_claim_count"]},
    )

    empty = await registry.execute("resume-evidence-extract", {"resume_text": "x\nuser@example.com"})
    empty_rewrite = await registry.execute("resume-truthful-rewrite", {"claims": empty["claims"], "jd_text": "Python"})
    await check(
        "empty-evidence-does-not-trigger-invention",
        empty["claims"] == [] and empty_rewrite["rewrite_items"] == [],
        {"fact_safe": empty_rewrite["fact_safe"]},
    )

    many_source = "\n".join(f"Verified project contribution number {index}." for index in range(12))
    many_evidence = await registry.execute("resume-evidence-extract", {"resume_text": many_source})
    bounded = await registry.execute("resume-truthful-rewrite", {"claims": many_evidence["claims"], "jd_text": ""})
    await check(
        "rewrite-selection-is-bounded",
        bounded["selected_claim_count"] == 8,
        {"selected_claim_count": bounded["selected_claim_count"]},
    )

    passed = sum(1 for item in results if item["passed"])
    return {
        "schema_version": "1.0",
        "suite": "agent-shadow-fact-safety",
        "status": "passed" if passed == len(results) else "failed",
        "case_count": len(results),
        "passed_count": passed,
        "limitations": [
            "This deterministic suite verifies fact-safety invariants only.",
            "It does not prove recruiter preference, ATS lift, or human-perceived rewrite quality.",
        ],
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = asyncio.run(evaluate())
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report is not None:
        report = args.report if args.report.is_absolute() else ROOT / args.report
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
