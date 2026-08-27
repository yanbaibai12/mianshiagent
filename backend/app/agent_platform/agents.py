from __future__ import annotations

import hashlib
import re
from typing import Any

from app.agent_platform.contracts import AgentContext, AgentDecision, AgentDefinition
from app.agent_platform.skills import SkillDefinition, SkillRegistry

KNOWN_SKILLS = ("Python", "FastAPI", "PostgreSQL", "Redis", "Docker", "RAG", "Agent", "MCP")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")


def _source_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contains_contact_data(value: str) -> bool:
    return EMAIL_PATTERN.search(value) is not None or PHONE_PATTERN.search(value) is not None


def _evidence_executor(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload["resume_text"])
    claims: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        source_text = raw_line.strip()
        if len(source_text) < 12 or _contains_contact_data(source_text):
            continue
        claims.append(
            {
                "claim_id": f"claim-{len(claims) + 1:03d}",
                "claim": source_text,
                "confidence": "direct",
                "evidence": {
                    "source": "resume_text",
                    "line_number": line_number,
                    "text": source_text,
                    "sha256": _source_hash(source_text),
                },
            }
        )
        if len(claims) == 20:
            break
    return {"claims": claims, "claim_count": len(claims), "fact_safe": bool(claims)}


def _jd_map_executor(payload: dict[str, Any]) -> dict[str, Any]:
    jd_text = str(payload["jd_text"])
    required = [skill for skill in KNOWN_SKILLS if re.search(re.escape(skill), jd_text, re.IGNORECASE)]
    return {"requirements": required, "requirement_count": len(required)}


def _rewrite_executor(payload: dict[str, Any]) -> dict[str, Any]:
    raw_claims = payload["claims"]
    jd_text = str(payload["jd_text"])
    requirements = [skill for skill in KNOWN_SKILLS if re.search(re.escape(skill), jd_text, re.IGNORECASE)]
    ranked: list[tuple[int, int, dict[str, Any], list[str]]] = []
    if isinstance(raw_claims, list):
        for index, claim in enumerate(raw_claims):
            if not isinstance(claim, dict):
                continue
            text = claim.get("claim")
            evidence = claim.get("evidence")
            if not isinstance(text, str) or not isinstance(evidence, dict):
                continue
            evidence_text = evidence.get("text")
            evidence_hash = evidence.get("sha256")
            if evidence_text != text or evidence_hash != _source_hash(text) or _contains_contact_data(text):
                continue
            matches = [item for item in requirements if re.search(re.escape(item), text, re.IGNORECASE)]
            ranked.append((len(matches), index, claim, matches))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    rewrite_items = [
        {
            "claim_id": str(claim.get("claim_id") or ""),
            "text": str(claim["claim"]),
            "evidence_sha256": str(claim["evidence"]["sha256"]),
            "matched_requirements": matches,
        }
        for _, _, claim, matches in ranked[:8]
    ]
    matched = {requirement for item in rewrite_items for requirement in item["matched_requirements"]}
    coverage = round(len(matched) / len(requirements), 4) if requirements else 0.0
    return {
        "rewrite_items": rewrite_items,
        "selected_claim_count": len(rewrite_items),
        "fact_safe": bool(rewrite_items),
        "requirement_coverage": coverage,
    }


def _critique_executor(payload: dict[str, Any]) -> dict[str, Any]:
    answer = str(payload["answer"]).strip()
    lowered = answer.lower()
    signals = {
        "context": any(word in lowered for word in ("context", "background", "goal")),
        "action": any(word in lowered for word in ("designed", "implemented", "built", "led")),
        "result": any(word in lowered for word in ("result", "improved", "reduced", "measured")),
        "reflection": any(word in lowered for word in ("learned", "tradeoff", "rollback", "next")),
    }
    score = sum(signals.values()) * 25
    missing = [name for name, present in signals.items() if not present]
    return {"score": score, "signals": signals, "missing_dimensions": missing}


def build_default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            id="resume-evidence-extract",
            version="0.2.0",
            required_inputs=frozenset({"resume_text"}),
            output_fields=frozenset({"claims", "claim_count", "fact_safe"}),
            executor=_evidence_executor,
        )
    )
    registry.register(
        SkillDefinition(
            id="resume-truthful-rewrite",
            version="0.1.0",
            required_inputs=frozenset({"claims", "jd_text"}),
            output_fields=frozenset({"rewrite_items", "selected_claim_count", "fact_safe", "requirement_coverage"}),
            executor=_rewrite_executor,
        )
    )
    registry.register(
        SkillDefinition(
            id="jd-requirement-map",
            version="0.1.0",
            required_inputs=frozenset({"jd_text"}),
            output_fields=frozenset({"requirements", "requirement_count"}),
            executor=_jd_map_executor,
        )
    )
    registry.register(
        SkillDefinition(
            id="interview-answer-critique",
            version="0.1.0",
            required_inputs=frozenset({"answer"}),
            output_fields=frozenset({"score", "signals", "missing_dimensions"}),
            executor=_critique_executor,
        )
    )
    return registry


async def supervisor_agent(context: AgentContext) -> AgentDecision:
    mode = str(context.input.get("mode") or "").strip().lower()
    routes = {
        "resume": "resume-analyst",
        "resume-rewrite": "resume-rewriter",
        "jd": "jd-analyst",
        "interview": "interview-coach",
    }
    target = routes.get(mode)
    if target is None:
        return AgentDecision.complete(
            {"status": "rejected", "reason": "unsupported mode", "supported_modes": sorted(routes)},
            tokens_used=16,
        )
    return AgentDecision.handoff(target, output={"route": target}, tokens_used=24)


async def resume_analyst_agent(context: AgentContext) -> AgentDecision:
    if context.tool_result is None:
        resume_id = str(context.input.get("resume_id") or "")
        return AgentDecision.call_tool(
            "resume.read",
            {"resume_id": resume_id, "audience": str(context.user_id)},
            tokens_used=32,
        )
    result = await context.execute_skill(
        "resume-evidence-extract", {"resume_text": context.tool_result.get("resume_text", "")}
    )
    return AgentDecision.complete({"agent": "resume-analyst", **result}, tokens_used=64)


async def resume_rewriter_agent(context: AgentContext) -> AgentDecision:
    if context.tool_result is None:
        return AgentDecision.call_tool(
            "resume.read",
            {"resume_id": str(context.input.get("resume_id") or ""), "audience": str(context.user_id)},
            tokens_used=32,
        )
    evidence = await context.execute_skill(
        "resume-evidence-extract", {"resume_text": context.tool_result.get("resume_text", "")}
    )
    rewrite = await context.execute_skill(
        "resume-truthful-rewrite",
        {"claims": evidence["claims"], "jd_text": context.input.get("jd_text", "")},
    )
    return AgentDecision.complete(
        {"agent": "resume-rewriter", "evidence_claim_count": evidence["claim_count"], **rewrite},
        tokens_used=96,
    )


async def jd_analyst_agent(context: AgentContext) -> AgentDecision:
    result = await context.execute_skill("jd-requirement-map", {"jd_text": context.input.get("jd_text", "")})
    return AgentDecision.complete({"agent": "jd-analyst", **result}, tokens_used=48)


async def interview_coach_agent(context: AgentContext) -> AgentDecision:
    if context.tool_result is None:
        return AgentDecision.call_tool(
            "interview.questions.read",
            {"interview_id": str(context.input.get("interview_id") or ""), "audience": str(context.user_id)},
            tokens_used=32,
        )
    critique = await context.execute_skill("interview-answer-critique", {"answer": context.input.get("answer", "")})
    return AgentDecision.complete(
        {"agent": "interview-coach", "questions": context.tool_result.get("questions", []), **critique},
        tokens_used=64,
    )


def build_default_agents() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            id="supervisor",
            version="0.2.0",
            handler=supervisor_agent,
            handoffs=frozenset({"resume-analyst", "resume-rewriter", "jd-analyst", "interview-coach"}),
        ),
        AgentDefinition(
            id="resume-analyst",
            version="0.2.0",
            handler=resume_analyst_agent,
            allowed_tools=frozenset({"resume.read"}),
        ),
        AgentDefinition(
            id="resume-rewriter",
            version="0.1.0",
            handler=resume_rewriter_agent,
            allowed_tools=frozenset({"resume.read"}),
        ),
        AgentDefinition(id="jd-analyst", version="0.1.0", handler=jd_analyst_agent),
        AgentDefinition(
            id="interview-coach",
            version="0.1.0",
            handler=interview_coach_agent,
            allowed_tools=frozenset({"interview.questions.read"}),
        ),
    ]
