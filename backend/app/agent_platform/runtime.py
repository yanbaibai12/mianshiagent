from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_platform.agents import build_default_agents, build_default_skill_registry
from app.agent_platform.contracts import RiskLevel
from app.agent_platform.harness import AgentHarness
from app.agent_platform.mcp import MCPGateway, MCPTool
from app.agent_platform.run_store import PostgresRunStore, RunStore
from app.config import get_settings
from app.database import async_session_maker
from app.models import Interview, InterviewQuestion, Resume

SessionFactory = Callable[[], AsyncSession]


class DomainResourceAccessError(LookupError):
    """Raised without disclosing whether a cross-tenant resource exists."""


@dataclass(frozen=True)
class AgentShadowRuntime:
    """Process-local shadow runtime. It is not a durable production runtime."""

    harness: AgentHarness


def _parse_resource_id(arguments: dict[str, object], field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(arguments[field]))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainResourceAccessError("resource is unavailable") from exc


def _parse_audience(arguments: dict[str, object]) -> uuid.UUID:
    try:
        return uuid.UUID(str(arguments["audience"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainResourceAccessError("resource is unavailable") from exc


def _resume_reader(session_factory: SessionFactory) -> Callable[[dict[str, object]], Awaitable[dict[str, object]]]:
    async def read_resume(arguments: dict[str, object]) -> dict[str, object]:
        resume_id = _parse_resource_id(arguments, "resume_id")
        user_id = _parse_audience(arguments)
        async with session_factory() as session:
            resume_text = await session.scalar(
                select(Resume.original_text).where(Resume.id == resume_id, Resume.user_id == user_id)
            )
        if resume_text is None:
            raise DomainResourceAccessError("resource is unavailable")
        return {"resume_text": str(resume_text)}

    return read_resume


def _interview_question_reader(
    session_factory: SessionFactory,
) -> Callable[[dict[str, object]], Awaitable[dict[str, object]]]:
    async def read_interview_questions(arguments: dict[str, object]) -> dict[str, object]:
        interview_id = _parse_resource_id(arguments, "interview_id")
        user_id = _parse_audience(arguments)
        async with session_factory() as session:
            owned_interview_id = await session.scalar(
                select(Interview.id).where(Interview.id == interview_id, Interview.user_id == user_id)
            )
            if owned_interview_id is None:
                raise DomainResourceAccessError("resource is unavailable")
            result = await session.execute(
                select(InterviewQuestion.question)
                .where(InterviewQuestion.interview_id == interview_id)
                .order_by(InterviewQuestion.sequence.asc(), InterviewQuestion.id.asc())
            )
            questions = [str(question) for question in result.scalars().all()]
        return {"questions": questions}

    return read_interview_questions


def build_agent_shadow_runtime(
    *,
    session_factory: SessionFactory = async_session_maker,
    store: RunStore | None = None,
) -> AgentShadowRuntime:
    """Build the authenticated shadow runtime with database-backed read adapters."""
    effective_store = store
    if effective_store is None and get_settings().AGENT_RUN_STORE_BACKEND == "postgresql":
        effective_store = PostgresRunStore(session_factory)
    gateway = MCPGateway()
    gateway.register(
        MCPTool(
            name="resume.read",
            version="0.2.0",
            handler=_resume_reader(session_factory),
            allowed_agents=frozenset({"resume-analyst", "resume-rewriter"}),
            required_arguments=frozenset({"resume_id", "audience"}),
            output_fields=frozenset({"resume_text"}),
            risk_level=RiskLevel.MEDIUM,
            read_only=True,
            timeout_seconds=10.0,
        )
    )
    gateway.register(
        MCPTool(
            name="interview.questions.read",
            version="0.2.0",
            handler=_interview_question_reader(session_factory),
            allowed_agents=frozenset({"interview-coach"}),
            required_arguments=frozenset({"interview_id", "audience"}),
            output_fields=frozenset({"questions"}),
            risk_level=RiskLevel.MEDIUM,
            read_only=True,
            timeout_seconds=10.0,
        )
    )
    harness = AgentHarness(gateway=gateway, skills=build_default_skill_registry(), store=effective_store)
    for definition in build_default_agents():
        harness.register_agent(definition)
    return AgentShadowRuntime(harness=harness)


agent_shadow_runtime = build_agent_shadow_runtime()
