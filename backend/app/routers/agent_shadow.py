from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_platform.contracts import AgentRun, RunBudget, RunStatus
from app.agent_platform.harness import TERMINAL_STATUSES, HarnessError
from app.agent_platform.run_store import AgentRunSummary, RunStoreError
from app.agent_platform.runtime import AgentShadowRuntime, agent_shadow_runtime
from app.config import get_settings
from app.models import User
from app.services.auth_service import get_current_user

settings = get_settings()

router = APIRouter(
    prefix="/api/agent-shadow",
    tags=["agent-shadow"],
    include_in_schema=False,
)


class AgentShadowBudgetRequest(BaseModel):
    max_steps: int = Field(default=12, ge=1, le=20)
    max_tokens: int = Field(default=12_000, ge=1, le=50_000)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    timeout_seconds: float = Field(default=60.0, gt=0, le=120)
    step_timeout_seconds: float = Field(default=15.0, gt=0, le=30)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_timeout_order(self) -> AgentShadowBudgetRequest:
        if self.step_timeout_seconds > self.timeout_seconds:
            raise ValueError("step_timeout_seconds must not exceed timeout_seconds")
        return self

    def to_runtime_budget(self) -> RunBudget:
        return RunBudget(**self.model_dump())


class AgentShadowInput(BaseModel):
    mode: Literal["resume", "resume-rewrite", "jd", "interview"]
    resume_id: uuid.UUID | None = None
    interview_id: uuid.UUID | None = None
    jd_text: str | None = Field(default=None, max_length=40_000)
    answer: str | None = Field(default=None, max_length=8_000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_mode_contract(self) -> AgentShadowInput:
        if self.mode in {"resume", "resume-rewrite"} and self.resume_id is None:
            raise ValueError("resume_id is required for resume modes")
        if self.mode in {"resume-rewrite", "jd"} and not (self.jd_text or "").strip():
            raise ValueError("jd_text is required for this mode")
        if self.mode == "interview":
            if self.interview_id is None:
                raise ValueError("interview_id is required for interview mode")
            if not (self.answer or "").strip():
                raise ValueError("answer is required for interview mode")
        return self

    def to_runtime_input(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class AgentShadowRunCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=500)
    input: AgentShadowInput
    budget: AgentShadowBudgetRequest = Field(default_factory=AgentShadowBudgetRequest)

    model_config = ConfigDict(extra="forbid")


class AgentShadowStepResponse(BaseModel):
    id: uuid.UUID
    sequence: int
    agent_id: str
    status: str
    decision_kind: str | None = None
    tokens_used: int
    error_code: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class AgentShadowTraceResponse(BaseModel):
    sequence: int
    event: str
    metadata: dict[str, Any]
    at: datetime


class AgentShadowCheckpointResponse(BaseModel):
    status: str
    current_agent_id: str
    tokens_used: int
    tool_calls: int
    step_count: int


class AgentShadowRunSummaryResponse(BaseModel):
    id: uuid.UUID
    objective: str
    input_mode: str
    current_agent_id: str
    status: str
    tokens_used: int
    tool_calls: int
    attempts: int
    cancel_requested: bool
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentShadowRunListResponse(BaseModel):
    items: list[AgentShadowRunSummaryResponse]
    next_cursor: str | None = None


class AgentShadowRunResponse(BaseModel):
    id: uuid.UUID
    objective: str
    current_agent_id: str
    status: str
    tokens_used: int
    tool_calls: int
    attempts: int
    cancel_requested: bool
    output: dict[str, Any]
    error_code: str | None = None
    steps: list[AgentShadowStepResponse]
    trace: list[AgentShadowTraceResponse]
    checkpoint: AgentShadowCheckpointResponse
    created_at: datetime
    updated_at: datetime


IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128),
]


def require_agent_shadow_enabled() -> None:
    if not settings.AGENT_SHADOW_API_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def get_runtime() -> AgentShadowRuntime:
    return agent_shadow_runtime


async def _owned_run_or_404(runtime: AgentShadowRuntime, run_id: uuid.UUID, user_id: uuid.UUID) -> AgentRun:
    try:
        run = await runtime.harness.get_run(run_id)
    except HarnessError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行不存在") from exc
    if run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行不存在")
    return run


def _public_trace_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {"agent_id", "from", "to", "tool"}
    public = {key: value for key, value in metadata.items() if key in allowed}
    if "error_type" in metadata:
        public["error_code"] = "execution_failed"
    return public


def _encode_cursor(item: AgentRunSummary) -> str:
    updated_at = (
        item.updated_at.replace(tzinfo=UTC) if item.updated_at.tzinfo is None else item.updated_at.astimezone(UTC)
    )
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "run_id": str(item.id)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"updated_at", "run_id"}:
            raise ValueError("invalid cursor object")
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        if updated_at.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        normalized_updated_at = updated_at.astimezone(UTC).replace(tzinfo=None)
        return normalized_updated_at, uuid.UUID(str(payload["run_id"]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="分页游标无效") from exc


def _serialize_summary(item: AgentRunSummary) -> AgentShadowRunSummaryResponse:
    return AgentShadowRunSummaryResponse(
        id=item.id,
        objective=item.objective,
        input_mode=item.input_mode,
        current_agent_id=item.current_agent_id,
        status=item.status.value,
        tokens_used=item.tokens_used,
        tool_calls=item.tool_calls,
        attempts=item.attempts,
        cancel_requested=item.cancel_requested,
        error_code=item.error_code,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _serialize_run(run: AgentRun) -> AgentShadowRunResponse:
    checkpoint = {
        "status": str(run.checkpoint.get("status") or run.status.value),
        "current_agent_id": str(run.checkpoint.get("current_agent_id") or run.current_agent_id),
        "tokens_used": int(run.checkpoint.get("tokens_used") or run.tokens_used),
        "tool_calls": int(run.checkpoint.get("tool_calls") or run.tool_calls),
        "step_count": int(run.checkpoint.get("step_count") or len(run.steps)),
    }
    return AgentShadowRunResponse(
        id=run.id,
        objective=run.objective,
        current_agent_id=run.current_agent_id,
        status=run.status.value,
        tokens_used=run.tokens_used,
        tool_calls=run.tool_calls,
        attempts=run.attempts,
        cancel_requested=run.cancel_requested,
        output=dict(run.output) if run.status == RunStatus.COMPLETED else {},
        error_code="execution_failed" if run.status == RunStatus.FAILED else None,
        steps=[
            AgentShadowStepResponse(
                id=step.id,
                sequence=step.sequence,
                agent_id=step.agent_id,
                status=step.status.value,
                decision_kind=step.decision_kind,
                tokens_used=step.tokens_used,
                error_code="step_failed" if step.error else None,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in run.steps
        ],
        trace=[
            AgentShadowTraceResponse(
                sequence=int(item["sequence"]),
                event=str(item["event"]),
                metadata=_public_trace_metadata(dict(item.get("metadata") or {})),
                at=item["at"],
            )
            for item in run.trace
        ],
        checkpoint=AgentShadowCheckpointResponse(**checkpoint),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post(
    "/runs",
    response_model=AgentShadowRunResponse,
    dependencies=[Depends(require_agent_shadow_enabled)],
)
async def create_agent_shadow_run(
    payload: AgentShadowRunCreateRequest,
    idempotency_key: IdempotencyKey,
    current_user: User = Depends(get_current_user),
    runtime: AgentShadowRuntime = Depends(get_runtime),
) -> AgentShadowRunResponse:
    try:
        run = await runtime.harness.create_run(
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            objective=payload.objective,
            input=payload.input.to_runtime_input(),
            start_agent_id="supervisor",
            budget=payload.budget.to_runtime_budget(),
        )
    except HarnessError as exc:
        if "different request" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency-Key 已用于不同请求",
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无法创建运行") from exc
    completed = await runtime.harness.execute(run.id)
    return _serialize_run(completed)


@router.get(
    "/runs",
    response_model=AgentShadowRunListResponse,
    dependencies=[Depends(require_agent_shadow_enabled)],
)
async def list_agent_shadow_runs(
    run_status: RunStatus | None = Query(default=None, alias="status"),
    current_agent_id: str | None = Query(default=None, min_length=1, max_length=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    runtime: AgentShadowRuntime = Depends(get_runtime),
) -> AgentShadowRunListResponse:
    try:
        items = await runtime.harness.store.list_for_user(
            current_user.id,
            status=run_status,
            current_agent_id=current_agent_id,
            before=_decode_cursor(cursor),
            limit=limit + 1,
        )
    except RunStoreError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="运行列表暂时不可用") from exc
    has_more = len(items) > limit
    page = items[:limit]
    return AgentShadowRunListResponse(
        items=[_serialize_summary(item) for item in page],
        next_cursor=_encode_cursor(page[-1]) if has_more and page else None,
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentShadowRunResponse,
    dependencies=[Depends(require_agent_shadow_enabled)],
)
async def get_agent_shadow_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    runtime: AgentShadowRuntime = Depends(get_runtime),
) -> AgentShadowRunResponse:
    return _serialize_run(await _owned_run_or_404(runtime, run_id, current_user.id))


@router.post(
    "/runs/{run_id}/cancel",
    response_model=AgentShadowRunResponse,
    dependencies=[Depends(require_agent_shadow_enabled)],
)
async def cancel_agent_shadow_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    runtime: AgentShadowRuntime = Depends(get_runtime),
) -> AgentShadowRunResponse:
    run = await _owned_run_or_404(runtime, run_id, current_user.id)
    cancelled = await runtime.harness.cancel(run.id)
    if cancelled.status not in TERMINAL_STATUSES:
        cancelled = await runtime.harness.execute(cancelled.id)
    return _serialize_run(cancelled)


@router.post(
    "/runs/{run_id}/retry",
    response_model=AgentShadowRunResponse,
    dependencies=[Depends(require_agent_shadow_enabled)],
)
async def retry_agent_shadow_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    runtime: AgentShadowRuntime = Depends(get_runtime),
) -> AgentShadowRunResponse:
    run = await _owned_run_or_404(runtime, run_id, current_user.id)
    if run.attempts >= 3:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="运行重试次数已达上限")
    try:
        retried = await runtime.harness.retry(run.id)
    except HarnessError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前运行不可重试") from exc
    return _serialize_run(retried)
