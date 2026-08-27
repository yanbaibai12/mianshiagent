import asyncio
import hashlib
import re
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AgentQuestionPracticeState,
    Interview,
    InterviewExperienceShare,
    Resume,
    TrainingPlan,
    TrainingPlanTask,
    TrainingProfileDimension,
)
from app.services.ai_context_security import sanitize_output_text
from app.services.company_profiles import normalize_company_name
from app.services.interview_question_bank import load_agent_question_cards
from app.services.training_profile import apply_training_signal, detect_training_dimensions
from app.utils.time import utc_now

MAX_DAILY_MINUTES = 45
TASK_TYPES = {"agent_question", "wrong_review", "mock_interview", "experience_reading", "project_review"}


@dataclass
class _GenerationLockEntry:
    lock: asyncio.Lock
    references: int = 0


_GENERATION_LOCKS: dict[tuple[str, str, date], _GenerationLockEntry] = {}
_GENERATION_LOCKS_GUARD = threading.Lock()


class TrainingPlanError(ValueError):
    pass


@asynccontextmanager
async def training_plan_generation_lock(user_id: uuid.UUID, organization_id: uuid.UUID, week_start: date):
    key = (str(user_id), str(organization_id), week_start)
    with _GENERATION_LOCKS_GUARD:
        entry = _GENERATION_LOCKS.get(key)
        if entry is None:
            entry = _GenerationLockEntry(lock=asyncio.Lock())
            _GENERATION_LOCKS[key] = entry
        entry.references += 1

    acquired = False
    try:
        await entry.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry.lock.release()
        with _GENERATION_LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and _GENERATION_LOCKS.get(key) is entry:
                _GENERATION_LOCKS.pop(key, None)


@dataclass
class TaskCandidate:
    task_type: str
    title: str
    description: str
    estimated_minutes: int
    priority: int
    dedupe_key: str
    target_dimensions: list[str] = field(default_factory=list)
    recommendation_reason: str = ""
    related_question_id: str | None = None
    related_interview_id: uuid.UUID | None = None
    related_experience_id: uuid.UUID | None = None
    related_company_profile_id: uuid.UUID | None = None
    preferred_date: date | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_week_start(value: date | None = None) -> date:
    current = value or utc_now().date()
    return current - timedelta(days=current.weekday())


def _dedupe_key(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts).lower()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{sanitize_output_text(parts[0] if parts else 'task', max_chars=30)}:{digest}"[:180]


def _safe_text(value: Any, max_chars: int) -> str:
    return sanitize_output_text(re.sub(r"\s+", " ", str(value or "")), max_chars=max_chars)


def _optional_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _profile_dimensions(rows: list[TrainingProfileDimension]) -> list[dict[str, Any]]:
    return [
        {
            "dimension_key": row.dimension_key,
            "dimension_label": row.dimension_label,
            "mastery_score": int(row.mastery_score or 0),
            "weak_count": int(row.weak_count or 0),
        }
        for row in sorted(rows, key=lambda item: (int(item.mastery_score or 60), -int(item.weak_count or 0)))[:3]
    ]


def _question_card_map() -> dict[str, dict[str, Any]]:
    try:
        return {str(card.get("id")): card for card in load_agent_question_cards()}
    except (FileNotFoundError, ValueError):
        return {}


def _project_records(resume: Resume | None) -> list[dict[str, Any]]:
    if not resume:
        return []
    data = resume.optimized_data or resume.parsed_data or {}
    projects = data.get("projects") if isinstance(data, dict) else []
    if isinstance(projects, dict):
        projects = [projects]
    return [item for item in (projects or []) if isinstance(item, dict)]


def _project_name(project: dict[str, Any], fallback: str) -> str:
    for key in ("name", "project_name", "title", "项目名", "项目名称"):
        if project.get(key):
            return _safe_text(project[key], 120)
    return _safe_text(fallback, 120)


def _project_description(project: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("description", "summary", "highlights", "interview_points", "技术栈", "描述"):
        value = project.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value[:5])
        elif value:
            values.append(str(value))
    return _safe_text(" ".join(values), 500)


async def _source_interview(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    source_interview_id: uuid.UUID | None,
) -> Interview | None:
    stmt = select(Interview).where(
        Interview.user_id == user_id,
        Interview.organization_id == organization_id,
    )
    if source_interview_id:
        interview = await db.scalar(stmt.where(Interview.id == source_interview_id))
        if not interview:
            raise TrainingPlanError("来源面试不存在或不属于当前组织")
        return interview
    return await db.scalar(stmt.order_by(Interview.updated_at.desc()))


async def _visible_company_experience(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    company: str | None,
) -> InterviewExperienceShare | None:
    if not company:
        return None
    rows = (
        await db.execute(
            select(InterviewExperienceShare)
            .where(
                InterviewExperienceShare.status == "published",
                or_(
                    InterviewExperienceShare.user_id == user_id,
                    InterviewExperienceShare.visibility == "public",
                    and_(
                        InterviewExperienceShare.visibility == "organization",
                        InterviewExperienceShare.organization_id == organization_id,
                    ),
                ),
            )
            .order_by(InterviewExperienceShare.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    target = normalize_company_name(company)
    return next((row for row in rows if normalize_company_name(row.company) == target), None)


def _practice_candidates(
    states: list[AgentQuestionPracticeState],
    cards: dict[str, dict[str, Any]],
    weak_dimensions: list[str],
    week_start: date,
) -> list[TaskCandidate]:
    now = utc_now()
    result: list[TaskCandidate] = []
    ranked = sorted(
        states,
        key=lambda state: (
            0 if state.is_wrong or state.mastery_status == "unknown" else 1,
            0 if state.next_review_at and state.next_review_at <= now else 1,
            0 if state.is_favorite else 1,
            int(state.known_count or 0),
        ),
    )
    for state in ranked:
        card = cards.get(state.question_id) or {}
        question = _safe_text(card.get("question") or state.question_id, 160)
        dimensions = detect_training_dimensions(
            question,
            card.get("focus"),
            " ".join(card.get("skills") or []),
        ) or weak_dimensions[:1]
        is_wrong = bool(state.is_wrong or state.mastery_status == "unknown")
        task_type = "wrong_review" if is_wrong else "agent_question"
        priority = 100 if is_wrong else 82 if state.next_review_at and state.next_review_at <= now else 65
        preferred = state.next_review_at.date() if state.next_review_at else None
        if preferred and not week_start <= preferred <= week_start + timedelta(days=6):
            preferred = None
        result.append(
            TaskCandidate(
                task_type=task_type,
                title=f"{'错题复习' if is_wrong else '题卡练习'}：{question}",
                description="先口述核心结论，再补充实现边界、项目例子和验证方式。",
                estimated_minutes=15,
                priority=priority,
                dedupe_key=_dedupe_key(task_type, state.question_id),
                target_dimensions=dimensions,
                recommendation_reason=(
                    "该题处于错题或不会状态，需要优先复习。"
                    if is_wrong
                    else "该题已到复习时间或被收藏，适合本周巩固。"
                ),
                related_question_id=state.question_id,
                preferred_date=preferred,
            )
        )
        if len(result) >= 3:
            break

    if not any(candidate.task_type == "wrong_review" for candidate in result) and cards:
        for card in cards.values():
            dimensions = detect_training_dimensions(
                card.get("question"), card.get("focus"), " ".join(card.get("skills") or [])
            )
            if weak_dimensions and not set(dimensions).intersection(weak_dimensions):
                continue
            question_id = str(card.get("id") or "")
            result.append(
                TaskCandidate(
                    task_type="wrong_review",
                    title=f"薄弱题复习：{_safe_text(card.get('question'), 160)}",
                    description="先完成一次 2 分钟口述，再对照精简答案记录遗漏点。",
                    estimated_minutes=15,
                    priority=75,
                    dedupe_key=_dedupe_key("wrong_review", question_id),
                    target_dimensions=dimensions or weak_dimensions[:1],
                    recommendation_reason="本周没有已记录错题，使用薄弱维度题卡完成一次基线复习。",
                    related_question_id=question_id,
                )
            )
            break
    return result


def _schedule_candidates(
    candidates: list[TaskCandidate],
    *,
    week_start: date,
    existing_tasks: list[TrainingPlanTask],
) -> list[tuple[TaskCandidate, date]]:
    days = [week_start + timedelta(days=index) for index in range(7)]
    loads = {day: 0 for day in days}
    day_types: dict[date, set[str]] = {day: set() for day in days}
    for task in existing_tasks:
        if task.scheduled_date in loads and task.status != "skipped":
            loads[task.scheduled_date] += int(task.estimated_minutes or 0)
            day_types[task.scheduled_date].add(task.task_type)

    scheduled: list[tuple[TaskCandidate, date]] = []
    for candidate in sorted(candidates, key=lambda item: (-item.priority, item.task_type, item.dedupe_key)):
        possible = [day for day in days if loads[day] + candidate.estimated_minutes <= MAX_DAILY_MINUTES]
        if not possible:
            continue
        if candidate.preferred_date in possible:
            selected = candidate.preferred_date
        else:
            non_adjacent = [
                day
                for day in possible
                if candidate.task_type not in day_types[day]
                and candidate.task_type not in day_types.get(day - timedelta(days=1), set())
            ]
            selected = min(non_adjacent or possible, key=lambda day: (loads[day], day))
        loads[selected] += candidate.estimated_minutes
        day_types[selected].add(candidate.task_type)
        scheduled.append((candidate, selected))
    return scheduled


async def get_plan(
    db: AsyncSession,
    *,
    plan_id: uuid.UUID,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> TrainingPlan | None:
    return await db.scalar(
        select(TrainingPlan)
        .options(selectinload(TrainingPlan.tasks))
        .where(
            TrainingPlan.id == plan_id,
            TrainingPlan.user_id == user_id,
            TrainingPlan.organization_id == organization_id,
        )
    )


async def get_current_plan(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    week_start: date | None = None,
) -> TrainingPlan | None:
    normalized = normalize_week_start(week_start)
    return await db.scalar(
        select(TrainingPlan)
        .options(selectinload(TrainingPlan.tasks))
        .where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.organization_id == organization_id,
            TrainingPlan.week_start == normalized,
        )
    )


async def generate_training_plan(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    source_interview_id: uuid.UUID | None = None,
    week_start: date | None = None,
    force: bool = False,
) -> tuple[TrainingPlan, bool]:
    normalized_week = normalize_week_start(week_start)
    week_end = normalized_week + timedelta(days=6)
    existing = await get_current_plan(
        db,
        user_id=user_id,
        organization_id=organization_id,
        week_start=normalized_week,
    )
    if existing and not force:
        return existing, False

    interview = await _source_interview(
        db,
        user_id=user_id,
        organization_id=organization_id,
        source_interview_id=source_interview_id,
    )
    resume = None
    if interview and interview.resume_id:
        resume = await db.scalar(
            select(Resume).where(
                Resume.id == interview.resume_id,
                Resume.user_id == user_id,
                Resume.organization_id == organization_id,
            )
        )
    if not resume:
        resume = await db.scalar(
            select(Resume)
            .where(Resume.user_id == user_id, Resume.organization_id == organization_id)
            .order_by(Resume.updated_at.desc())
        )

    dimensions = (
        await db.execute(
            select(TrainingProfileDimension).where(
                TrainingProfileDimension.user_id == user_id,
                TrainingProfileDimension.organization_id == organization_id,
            )
        )
    ).scalars().all()
    weak_items = _profile_dimensions(dimensions)
    weak_keys = [item["dimension_key"] for item in weak_items]
    practice_states = (
        await db.execute(
            select(AgentQuestionPracticeState).where(
                AgentQuestionPracticeState.user_id == user_id,
                AgentQuestionPracticeState.organization_id == organization_id,
            )
        )
    ).scalars().all()
    recently_completed_keys = set(
        (
            await db.execute(
                select(TrainingPlanTask.dedupe_key)
                .join(TrainingPlan, TrainingPlan.id == TrainingPlanTask.plan_id)
                .where(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.organization_id == organization_id,
                    TrainingPlanTask.status == "completed",
                    TrainingPlanTask.completed_at >= utc_now() - timedelta(days=7),
                )
            )
        ).scalars().all()
    )

    candidates = _practice_candidates(practice_states, _question_card_map(), weak_keys, normalized_week)
    template_name = interview.interview_template_name if interview else "综合面"
    candidates.append(
        TaskCandidate(
            task_type="mock_interview",
            title=f"完成一次{_safe_text(template_name, 60)}模拟面试",
            description="按本轮模板完成至少 3 道题，重点补齐回答证据和复盘动作。",
            estimated_minutes=30,
            priority=92,
            dedupe_key=_dedupe_key("mock_interview", interview.interview_template_id if interview else "comprehensive"),
            target_dimensions=weak_keys[:3],
            recommendation_reason="保持每周至少一次完整模拟面试，验证薄弱项是否改善。",
            related_interview_id=interview.id if interview else None,
        )
    )

    projects = _project_records(resume)
    project = projects[0] if projects else {}
    project_name = _project_name(project, resume.title if resume else "核心项目")
    project_description = _project_description(project)
    repeated_gaps = []
    if interview:
        repeated_gaps = list((interview.report_details or {}).get("repeated_gaps") or interview.weak_points or [])[:3]
    candidates.append(
        TaskCandidate(
            task_type="project_review",
            title=f"项目复盘：{project_name}",
            description=_safe_text(
                project_description or "整理项目背景、个人贡献、技术取舍、故障排查、结果指标和复盘改进。",
                500,
            ),
            estimated_minutes=20,
            priority=88,
            dedupe_key=_dedupe_key("project_review", resume.id if resume else project_name),
            target_dimensions=detect_training_dimensions(project_name, project_description) or weak_keys[:2],
            recommendation_reason=_safe_text(
                f"需要重点补齐：{'；'.join(str(item) for item in repeated_gaps)}"
                if repeated_gaps
                else "项目证据是技术面和项目深挖的共同基础。",
                300,
            ),
        )
    )

    profile_snapshot = interview.company_profile_snapshot if interview and isinstance(interview.company_profile_snapshot, dict) else {}
    target_company = (profile_snapshot or {}).get("matched_company") or (interview.target_company if interview else None)
    experience = await _visible_company_experience(
        db,
        user_id=user_id,
        organization_id=organization_id,
        company=target_company,
    )
    if target_company and (experience or profile_snapshot):
        target_position = (profile_snapshot or {}).get("matched_position") or (interview.target_position if interview else None)
        candidates.append(
            TaskCandidate(
                task_type="experience_reading",
                title=f"阅读面经：{_safe_text(target_company, 100)} · {_safe_text(target_position or '目标岗位', 100)}",
                description="对照公司常见轮次和高频主题，整理 3 个可能追问及自己的回答证据。",
                estimated_minutes=10,
                priority=78,
                dedupe_key=_dedupe_key("experience_reading", experience.id if experience else profile_snapshot.get("profile_id")),
                target_dimensions=weak_keys[:2],
                recommendation_reason="目标公司存在可用面经或公司画像，可用于校准本周训练方向。",
                related_experience_id=experience.id if experience else None,
                related_company_profile_id=_optional_uuid(profile_snapshot.get("profile_id")),
            )
        )

    plan = existing
    if not existing:
        plan = TrainingPlan(
            user_id=user_id,
            organization_id=organization_id,
            week_start=normalized_week,
            week_end=week_end,
            status="active",
            created_at=utc_now(),
        )
        try:
            async with db.begin_nested():
                db.add(plan)
                await db.flush()
        except IntegrityError:
            winner = await get_current_plan(
                db,
                user_id=user_id,
                organization_id=organization_id,
                week_start=normalized_week,
            )
            if winner:
                return winner, False
            raise
    if plan is None:
        raise TrainingPlanError("训练计划生成失败")
    completed_tasks = [task for task in (existing.tasks if existing else []) if task.status == "completed"]
    completed_keys = {task.dedupe_key for task in completed_tasks}
    if existing and force:
        for task in list(existing.tasks):
            if task.status != "completed":
                await db.delete(task)
        await db.flush()

    candidates = [
        candidate
        for candidate in candidates
        if candidate.dedupe_key not in completed_keys
        and not (
            candidate.dedupe_key in recently_completed_keys
            and candidate.task_type in {"agent_question", "experience_reading"}
        )
    ]
    scheduled = _schedule_candidates(candidates, week_start=normalized_week, existing_tasks=completed_tasks)
    new_tasks: list[TrainingPlanTask] = []
    for candidate, scheduled_date in scheduled:
        task = TrainingPlanTask(
            plan_id=plan.id,
            task_type=candidate.task_type,
            title=_safe_text(candidate.title, 240),
            description=_safe_text(candidate.description, 1000),
            scheduled_date=scheduled_date,
            estimated_minutes=max(5, min(candidate.estimated_minutes, MAX_DAILY_MINUTES)),
            priority=max(1, min(candidate.priority, 100)),
            status="pending",
            related_question_id=candidate.related_question_id,
            related_interview_id=candidate.related_interview_id,
            related_experience_id=candidate.related_experience_id,
            related_company_profile_id=candidate.related_company_profile_id,
            target_dimensions=list(dict.fromkeys(candidate.target_dimensions))[:5],
            recommendation_reason=_safe_text(candidate.recommendation_reason, 500),
            dedupe_key=candidate.dedupe_key,
            task_metadata=candidate.metadata,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(task)
        new_tasks.append(task)

    all_tasks = completed_tasks + new_tasks
    plan.source_interview_id = interview.id if interview else None
    plan.week_start = normalized_week
    plan.week_end = week_end
    plan.status = "active"
    plan.plan_summary = _safe_text(
        f"本周围绕{template_name}、{project_name}"
        f"{'、' + '、'.join(item['dimension_label'] for item in weak_items) if weak_items else ''}安排训练，"
        "优先完成错题复习、项目复盘和一次完整模拟面试。",
        1000,
    )
    plan.estimated_minutes = sum(int(task.estimated_minutes or 0) for task in all_tasks if task.status != "skipped")
    plan.completion_rate = _completion_rate(all_tasks)
    plan.generation_metadata = {
        "algorithm": "deterministic_weekly_v1",
        "daily_limit_minutes": MAX_DAILY_MINUTES,
        "weak_dimensions": weak_items,
        "input_counts": {
            "practice_states": len(practice_states),
            "projects": len(projects),
            "company_profile": 1 if profile_snapshot else 0,
        },
        "target_company": _safe_text(target_company, 120) if target_company else None,
    }
    plan.updated_at = utc_now()
    await db.flush()
    refreshed = await get_plan(db, plan_id=plan.id, user_id=user_id, organization_id=organization_id)
    if not refreshed:
        raise TrainingPlanError("训练计划生成失败")
    return refreshed, True


def _completion_rate(tasks: list[TrainingPlanTask]) -> int:
    relevant = [task for task in tasks if task.status != "skipped"]
    if not relevant:
        return 0
    completed = sum(1 for task in relevant if task.status == "completed")
    return round(completed * 100 / len(relevant))


async def update_training_task(
    db: AsyncSession,
    *,
    plan: TrainingPlan,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    status: str | None,
    scheduled_date: date | None,
) -> TrainingPlanTask:
    task = next((item for item in plan.tasks if item.id == task_id), None)
    if not task:
        raise TrainingPlanError("训练任务不存在")
    if scheduled_date is not None:
        if not plan.week_start <= scheduled_date <= plan.week_end:
            raise TrainingPlanError("任务日期必须位于当前训练周")
        daily_minutes = sum(
            int(item.estimated_minutes or 0)
            for item in plan.tasks
            if item.id != task.id and item.scheduled_date == scheduled_date and item.status != "skipped"
        )
        if task.status != "skipped" and daily_minutes + int(task.estimated_minutes or 0) > MAX_DAILY_MINUTES:
            raise TrainingPlanError("调整后单日训练时间不能超过 45 分钟")
        task.scheduled_date = scheduled_date
    previous_status = task.status
    if status is not None:
        if status not in {"pending", "completed", "skipped"}:
            raise TrainingPlanError("训练任务状态无效")
        task.status = status
        task.completed_at = utc_now() if status == "completed" else None
    task.updated_at = utc_now()
    if previous_status != "completed" and task.status == "completed":
        await apply_training_signal(
            db,
            user_id=user_id,
            organization_id=organization_id,
            dimension_keys=task.target_dimensions or ["engineering"],
            signal="known",
            source="training_plan_task",
        )
    plan.completion_rate = _completion_rate(plan.tasks)
    plan.estimated_minutes = sum(
        int(item.estimated_minutes or 0) for item in plan.tasks if item.status != "skipped"
    )
    pending = [item for item in plan.tasks if item.status == "pending"]
    plan.status = "completed" if not pending and plan.tasks else "active"
    plan.updated_at = utc_now()
    await db.flush()
    return task
