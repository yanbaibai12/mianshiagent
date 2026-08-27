import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AgentQuestionPracticeState, InterviewExperienceShare, User
from app.schemas import (
    AgentQuestionBankItemResponse,
    AgentQuestionBankListResponse,
    AgentQuestionPracticeStateResponse,
    AgentQuestionPracticeUpdateRequest,
    InterviewExperienceCreateRequest,
    InterviewExperienceListResponse,
    InterviewExperienceResponse,
    InterviewExperienceUpdateRequest,
    TrainingProfileDimensionResponse,
    TrainingProfileResponse,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.company_profiles import profile_target, refresh_share_profile
from app.services.data_sanitization import clean_labels, redact_sensitive_text
from app.services.interview_question_bank import (
    filter_agent_question_cards,
    load_agent_question_cards,
    question_bank_filter_options,
)
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.services.training_profile import (
    apply_training_signal,
    detect_training_dimensions,
    ensure_training_profile,
    weakest_dimensions,
)
from app.utils.time import utc_now

router = APIRouter(prefix="/api/community", tags=["community"])


def _practice_state_response(state: AgentQuestionPracticeState) -> AgentQuestionPracticeStateResponse:
    return AgentQuestionPracticeStateResponse(
        question_id=state.question_id,
        mastery_status=state.mastery_status,
        is_favorite=bool(state.is_favorite),
        is_wrong=bool(state.is_wrong),
        review_count=int(state.review_count or 0),
        known_count=int(state.known_count or 0),
        wrong_count=int(state.wrong_count or 0),
        next_review_at=state.next_review_at,
        last_practiced_at=state.last_practiced_at,
        updated_at=state.updated_at or state.created_at or utc_now(),
    )


def _dimension_response(dimension) -> TrainingProfileDimensionResponse:
    return TrainingProfileDimensionResponse(
        dimension_key=dimension.dimension_key,
        dimension_label=dimension.dimension_label,
        mastery_score=int(dimension.mastery_score or 0),
        exposure_count=int(dimension.exposure_count or 0),
        known_count=int(dimension.known_count or 0),
        weak_count=int(dimension.weak_count or 0),
        low_score_count=int(dimension.low_score_count or 0),
        last_signal=dimension.last_signal,
        last_source=dimension.last_source,
        last_practiced_at=dimension.last_practiced_at,
        updated_at=dimension.updated_at,
    )


def _question_card_response(
    card: dict[str, Any],
    practice_state: AgentQuestionPracticeState | None = None,
) -> AgentQuestionBankItemResponse:
    answer_points = [str(item) for item in card.get("answer_points") or []]
    return AgentQuestionBankItemResponse(
        id=str(card.get("id") or ""),
        section=str(card.get("section") or ""),
        difficulty=str(card.get("difficulty") or ""),
        roles=[str(item) for item in card.get("roles") or []],
        skills=[str(item) for item in card.get("skills") or []],
        question=str(card.get("question") or ""),
        concise_answer=_concise_answer(card, answer_points),
        deep_dive_answer=None,
        focus=str(card.get("focus") or ""),
        scenario=str(card.get("scenario") or ""),
        answer_points=answer_points,
        followups=[str(item) for item in card.get("followups") or []],
        scoring=[str(item) for item in card.get("scoring") or []],
        red_flags=[str(item) for item in card.get("red_flags") or []],
        keywords=[str(item) for item in card.get("keywords") or []],
        tags=[str(item) for item in card.get("tags") or []],
        source_title=str(card.get("source_title") or ""),
        source_version=str(card.get("source_version") or ""),
        practice_state=_practice_state_response(practice_state) if practice_state else None,
    )


def _concise_answer(card: dict[str, Any], answer_points: list[str]) -> str:
    points = [
        " ".join(point.split()).strip(" ,，;；。")
        for point in answer_points
        if str(point or "").strip()
    ][:4]
    if points:
        return f"核心回答：{'；'.join(points)}。"
    focus = " ".join(str(card.get("focus") or "").split()).strip(" ,，;；。")
    if focus:
        return f"核心回答：围绕{focus}展开，先说明原理，再结合项目场景、实现细节和验证结果回答。"
    return "核心回答：先给出结论，再补充项目场景、实现步骤、指标验证和风险边界。"


async def _practice_state_map(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    question_ids: list[str] | None = None,
) -> dict[str, AgentQuestionPracticeState]:
    stmt = select(AgentQuestionPracticeState).where(AgentQuestionPracticeState.user_id == user_id)
    if question_ids is not None:
        stmt = stmt.where(AgentQuestionPracticeState.question_id.in_(question_ids or [""]))
    rows = (await db.execute(stmt)).scalars().all()
    return {state.question_id: state for state in rows}


def _filter_cards_by_practice(
    cards: list[dict[str, Any]],
    states: dict[str, AgentQuestionPracticeState],
    practice_filter: str | None,
) -> list[dict[str, Any]]:
    if not practice_filter:
        return cards
    now = utc_now()
    filtered: list[dict[str, Any]] = []
    for card in cards:
        question_id = str(card.get("id") or "")
        state = states.get(question_id)
        if practice_filter == "favorite" and state and state.is_favorite:
            filtered.append(card)
        elif practice_filter == "wrong" and state and (state.is_wrong or state.mastery_status == "unknown"):
            filtered.append(card)
        elif practice_filter == "due" and state and state.next_review_at and state.next_review_at <= now:
            filtered.append(card)
        elif practice_filter == "unseen" and not state:
            filtered.append(card)
    return filtered


def _question_card_by_id(question_id: str) -> dict[str, Any] | None:
    cards = load_agent_question_cards()
    for card in cards:
        if card.get("id") == question_id:
            return card
    return None


async def _get_or_create_practice_state(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    question_id: str,
) -> AgentQuestionPracticeState:
    state = await db.scalar(
        select(AgentQuestionPracticeState).where(
            AgentQuestionPracticeState.user_id == user_id,
            AgentQuestionPracticeState.question_id == question_id,
        )
    )
    if state:
        if organization_id and not state.organization_id:
            state.organization_id = organization_id
        return state
    state = AgentQuestionPracticeState(
        user_id=user_id,
        organization_id=organization_id,
        question_id=question_id,
        mastery_status="unseen",
        is_favorite=False,
        is_wrong=False,
        review_count=0,
        known_count=0,
        wrong_count=0,
        practice_metadata={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(state)
    await db.flush()
    return state


def _next_review_for_status(status: str) -> Any:
    now = utc_now()
    if status == "known":
        return now + timedelta(days=7)
    if status == "review":
        return now + timedelta(days=2)
    if status == "unknown":
        return now + timedelta(days=1)
    return None


def _clean_question_items(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = redact_sensitive_text(" ".join(str(value or "").split()).strip(" ,，;；。"))[:300]
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result[:20]


def _clean_optional_text(value: str | None, max_chars: int) -> str | None:
    text = redact_sensitive_text(str(value or "")).strip()
    return text[:max_chars] or None


def _clean_required_text(value: str, max_chars: int, field_name: str) -> str:
    text = redact_sensitive_text(str(value or "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return text[:max_chars]


def _author_label(share: InterviewExperienceShare, *, email: str, nickname: str | None, current_user_id: uuid.UUID) -> str:
    if share.user_id == current_user_id:
        return "我（匿名展示）" if share.is_anonymous else (nickname or email.split("@", 1)[0])
    if share.is_anonymous:
        return "匿名同学"
    return nickname or email.split("@", 1)[0]


def _experience_response(
    share: InterviewExperienceShare,
    *,
    email: str,
    nickname: str | None,
    current_user_id: uuid.UUID,
) -> InterviewExperienceResponse:
    return InterviewExperienceResponse(
        id=share.id,
        organization_id=share.organization_id,
        company=share.company,
        position=share.position,
        city=share.city,
        interview_date=share.interview_date,
        rounds=share.rounds,
        difficulty=share.difficulty,
        result=share.result,
        tags=share.tags or [],
        questions=share.questions or [],
        process=share.process,
        content=share.content,
        visibility=share.visibility,
        is_anonymous=share.is_anonymous,
        allow_profile_usage=bool(share.allow_profile_usage),
        status=share.status,
        view_count=share.view_count or 0,
        like_count=share.like_count or 0,
        author_label=_author_label(share, email=email, nickname=nickname, current_user_id=current_user_id),
        can_edit=share.user_id == current_user_id,
        created_at=share.created_at,
        updated_at=share.updated_at,
    )


def _visible_conditions(user: User, organization_id: uuid.UUID | None) -> list[Any]:
    published = InterviewExperienceShare.status == "published"
    return [
        or_(
            InterviewExperienceShare.user_id == user.id,
            and_(published, InterviewExperienceShare.visibility == "public"),
            and_(
                published,
                InterviewExperienceShare.visibility == "organization",
                InterviewExperienceShare.organization_id == organization_id,
            ),
        )
    ]


def _experience_filter_conditions(
    *,
    user: User,
    organization_id: uuid.UUID | None,
    q: str | None,
    company: str | None,
    tag: str | None,
    difficulty: str | None,
    result: str | None,
) -> list[Any]:
    conditions = _visible_conditions(user, organization_id)
    if q and q.strip():
        keyword = f"%{q.strip()[:120]}%"
        conditions.append(
            or_(
                InterviewExperienceShare.company.ilike(keyword),
                InterviewExperienceShare.position.ilike(keyword),
                InterviewExperienceShare.rounds.ilike(keyword),
                InterviewExperienceShare.process.ilike(keyword),
                InterviewExperienceShare.content.ilike(keyword),
                cast(InterviewExperienceShare.tags, String).ilike(keyword),
                cast(InterviewExperienceShare.questions, String).ilike(keyword),
            )
        )
    if company and company.strip():
        conditions.append(InterviewExperienceShare.company.ilike(f"%{company.strip()[:120]}%"))
    if tag and tag.strip():
        conditions.append(cast(InterviewExperienceShare.tags, String).ilike(f"%{tag.strip()[:40]}%"))
    if difficulty:
        conditions.append(InterviewExperienceShare.difficulty == difficulty)
    if result:
        conditions.append(InterviewExperienceShare.result == result)
    return conditions


@router.get("/agent-questions", response_model=AgentQuestionBankListResponse)
async def list_agent_questions(
    q: str | None = Query(default=None, max_length=200),
    section: str | None = Query(default=None, max_length=80),
    difficulty: str | None = Query(default=None, max_length=40),
    role: str | None = Query(default=None, max_length=80),
    skill: str | None = Query(default=None, max_length=80),
    practice_filter: str | None = Query(default=None, pattern=r"^(favorite|wrong|due|unseen)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentQuestionBankListResponse:
    try:
        cards = load_agent_question_cards()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent 八股题库文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filtered = filter_agent_question_cards(
        cards,
        query=q,
        section=section,
        difficulty=difficulty,
        role=role,
        skill=skill,
    )
    all_state_map = await _practice_state_map(db, user_id=current_user.id)
    filtered = _filter_cards_by_practice(filtered, all_state_map, practice_filter)
    sliced = filtered[offset : offset + limit]
    state_map = {
        question_id: state
        for question_id, state in all_state_map.items()
        if question_id in {str(card.get("id") or "") for card in sliced}
    }
    return AgentQuestionBankListResponse(
        items=[_question_card_response(card, state_map.get(str(card.get("id") or ""))) for card in sliced],
        total=len(filtered),
        limit=limit,
        offset=offset,
        filters=question_bank_filter_options(cards),
    )


@router.get("/agent-questions/{question_id}", response_model=AgentQuestionBankItemResponse)
async def get_agent_question(
    question_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentQuestionBankItemResponse:
    try:
        cards = load_agent_question_cards()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent 八股题库文件不存在") from exc
    state = await db.scalar(
        select(AgentQuestionPracticeState).where(
            AgentQuestionPracticeState.user_id == current_user.id,
            AgentQuestionPracticeState.question_id == question_id,
        )
    )
    for card in cards:
        if card.get("id") == question_id:
            return _question_card_response(card, state)
    raise HTTPException(status_code=404, detail="题卡不存在")


@router.put("/agent-questions/{question_id}/practice", response_model=AgentQuestionPracticeStateResponse)
async def update_agent_question_practice(
    question_id: str,
    req: AgentQuestionPracticeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentQuestionPracticeStateResponse:
    try:
        card = _question_card_by_id(question_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent 八股题库文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not card:
        raise HTTPException(status_code=404, detail="题卡不存在")

    org = await resolve_request_organization(request, db, current_user)
    state = await _get_or_create_practice_state(
        db,
        user_id=current_user.id,
        organization_id=org.id,
        question_id=question_id,
    )
    now = utc_now()
    signal: str | None = None
    previous_wrong = bool(state.is_wrong)
    if req.mastery_status is not None:
        state.mastery_status = req.mastery_status
        state.last_practiced_at = now
        state.review_count = int(state.review_count or 0) + 1
        if req.mastery_status == "known":
            state.known_count = int(state.known_count or 0) + 1
            state.is_wrong = False if req.is_wrong is None else req.is_wrong
            signal = "known"
        elif req.mastery_status == "unknown":
            state.wrong_count = int(state.wrong_count or 0) + 1
            state.is_wrong = True
            signal = "weak"
        elif req.mastery_status == "review":
            signal = "weak"
        if req.next_review_at is None:
            state.next_review_at = _next_review_for_status(req.mastery_status)
    if req.is_favorite is not None:
        state.is_favorite = req.is_favorite
    if req.is_wrong is not None:
        state.is_wrong = req.is_wrong
        if req.is_wrong and not previous_wrong:
            state.wrong_count = int(state.wrong_count or 0) + 1
            state.mastery_status = "unknown" if state.mastery_status == "unseen" else state.mastery_status
            signal = signal or "weak"
    if req.next_review_at is not None:
        state.next_review_at = req.next_review_at
    state.updated_at = now

    dimension_keys = detect_training_dimensions(
        card.get("question"),
        card.get("focus"),
        card.get("scenario"),
        " ".join(card.get("skills") or []),
        " ".join(card.get("keywords") or []),
    )
    if signal:
        await apply_training_signal(
            db,
            user_id=current_user.id,
            organization_id=org.id,
            dimension_keys=dimension_keys,
            signal=signal,
            source="agent_question_practice",
        )
    log_audit_event(
        db,
        event_type="community.agent_question_practice_update",
        resource_type="agent_question",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=question_id,
        request=request,
        metadata={
            "mastery_status": state.mastery_status,
            "is_favorite": state.is_favorite,
            "is_wrong": state.is_wrong,
            "dimension_keys": dimension_keys,
        },
    )
    await db.commit()
    await db.refresh(state)
    return _practice_state_response(state)


@router.get("/training-profile", response_model=TrainingProfileResponse)
async def get_training_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrainingProfileResponse:
    org = await resolve_request_organization(request, db, current_user)
    dimensions = await ensure_training_profile(db, user_id=current_user.id, organization_id=org.id)
    states = (await db.execute(select(AgentQuestionPracticeState).where(AgentQuestionPracticeState.user_id == current_user.id))).scalars().all()
    now = utc_now()
    stats = {
        "practice_count": len(states),
        "favorite_count": sum(1 for state in states if state.is_favorite),
        "wrong_count": sum(1 for state in states if state.is_wrong or state.mastery_status == "unknown"),
        "due_count": sum(1 for state in states if state.next_review_at and state.next_review_at <= now),
    }
    await db.commit()
    return TrainingProfileResponse(
        dimensions=[_dimension_response(item) for item in dimensions],
        weakest_dimensions=[_dimension_response(item) for item in weakest_dimensions(dimensions)],
        stats=stats,
    )


@router.get("/experiences", response_model=InterviewExperienceListResponse)
async def list_experiences(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    company: str | None = Query(default=None, max_length=120),
    tag: str | None = Query(default=None, max_length=40),
    difficulty: str | None = Query(default=None, pattern=r"^(easy|medium|hard|unknown)$"),
    result: str | None = Query(default=None, pattern=r"^(offer|passed|failed|pending|unknown)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewExperienceListResponse:
    org = await resolve_request_organization(request, db, current_user)
    conditions = _experience_filter_conditions(
        user=current_user,
        organization_id=org.id,
        q=q,
        company=company,
        tag=tag,
        difficulty=difficulty,
        result=result,
    )
    total = await db.scalar(select(func.count()).select_from(InterviewExperienceShare).where(*conditions)) or 0
    rows = (
        await db.execute(
            select(InterviewExperienceShare, User.email, User.nickname)
            .join(User, User.id == InterviewExperienceShare.user_id)
            .where(*conditions)
            .order_by(InterviewExperienceShare.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return InterviewExperienceListResponse(
        items=[
            _experience_response(share, email=email, nickname=nickname, current_user_id=current_user.id)
            for share, email, nickname in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/experiences", response_model=InterviewExperienceResponse)
async def create_experience(
    req: InterviewExperienceCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewExperienceResponse:
    org = await resolve_request_organization(request, db, current_user)
    share = InterviewExperienceShare(
        user_id=current_user.id,
        organization_id=org.id,
        company=_clean_required_text(req.company, 160, "公司"),
        position=_clean_required_text(req.position, 200, "岗位"),
        city=_clean_optional_text(req.city, 80),
        interview_date=req.interview_date,
        rounds=_clean_optional_text(req.rounds, 200) or "",
        difficulty=req.difficulty,
        result=req.result,
        tags=clean_labels(req.tags),
        questions=_clean_question_items(req.questions),
        process=_clean_optional_text(req.process, 4000),
        content=_clean_required_text(req.content, 12000, "面经正文"),
        visibility=req.visibility,
        is_anonymous=req.is_anonymous,
        allow_profile_usage=req.allow_profile_usage,
        status="published",
        view_count=0,
        like_count=0,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(share)
    await db.flush()
    await refresh_share_profile(db, share)
    log_audit_event(
        db,
        event_type="community.experience_create",
        resource_type="interview_experience_share",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=org.id,
        resource_id=str(share.id),
        request=request,
        metadata={
            "company": share.company,
            "position": share.position,
            "visibility": share.visibility,
            "allow_profile_usage": share.allow_profile_usage,
            **tenant_metadata(org),
        },
    )
    await db.commit()
    await db.refresh(share)
    return _experience_response(share, email=current_user.email, nickname=current_user.nickname, current_user_id=current_user.id)


@router.get("/experiences/{experience_id}", response_model=InterviewExperienceResponse)
async def get_experience(
    experience_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewExperienceResponse:
    org = await resolve_request_organization(request, db, current_user)
    conditions = [
        InterviewExperienceShare.id == experience_id,
        *_visible_conditions(current_user, org.id),
    ]
    row = (
        await db.execute(
            select(InterviewExperienceShare, User.email, User.nickname)
            .join(User, User.id == InterviewExperienceShare.user_id)
            .where(*conditions)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="面经不存在或无权访问")
    share, email, nickname = row
    share.view_count = (share.view_count or 0) + 1
    share.updated_at = utc_now()
    await db.commit()
    await db.refresh(share)
    return _experience_response(share, email=email, nickname=nickname, current_user_id=current_user.id)


@router.put("/experiences/{experience_id}", response_model=InterviewExperienceResponse)
async def update_experience(
    experience_id: uuid.UUID,
    req: InterviewExperienceUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewExperienceResponse:
    share = await db.scalar(
        select(InterviewExperienceShare).where(
            InterviewExperienceShare.id == experience_id,
            InterviewExperienceShare.user_id == current_user.id,
        )
    )
    if not share:
        raise HTTPException(status_code=404, detail="面经不存在或无权编辑")
    previous_target = profile_target(share)
    if req.company is not None:
        share.company = _clean_required_text(req.company, 160, "公司")
    if req.position is not None:
        share.position = _clean_required_text(req.position, 200, "岗位")
    if req.city is not None:
        share.city = _clean_optional_text(req.city, 80)
    if req.interview_date is not None:
        share.interview_date = req.interview_date
    if req.rounds is not None:
        share.rounds = _clean_optional_text(req.rounds, 200) or ""
    if req.difficulty is not None:
        share.difficulty = req.difficulty
    if req.result is not None:
        share.result = req.result
    if req.tags is not None:
        share.tags = clean_labels(req.tags)
    if req.questions is not None:
        share.questions = _clean_question_items(req.questions)
    if req.process is not None:
        share.process = _clean_optional_text(req.process, 4000)
    if req.content is not None:
        share.content = _clean_required_text(req.content, 12000, "面经正文")
    if req.visibility is not None:
        share.visibility = req.visibility
    if req.is_anonymous is not None:
        share.is_anonymous = req.is_anonymous
    if req.allow_profile_usage is not None:
        share.allow_profile_usage = req.allow_profile_usage
    share.updated_at = utc_now()
    await db.flush()
    await refresh_share_profile(db, share, previous_targets=[previous_target] if previous_target else None)
    log_audit_event(
        db,
        event_type="community.experience_update",
        resource_type="interview_experience_share",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=share.organization_id,
        resource_id=str(share.id),
        request=request,
    )
    await db.commit()
    await db.refresh(share)
    return _experience_response(share, email=current_user.email, nickname=current_user.nickname, current_user_id=current_user.id)


@router.post("/experiences/{experience_id}/like", response_model=InterviewExperienceResponse)
async def like_experience(
    experience_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewExperienceResponse:
    org = await resolve_request_organization(request, db, current_user)
    row = (
        await db.execute(
            select(InterviewExperienceShare, User.email, User.nickname)
            .join(User, User.id == InterviewExperienceShare.user_id)
            .where(InterviewExperienceShare.id == experience_id, *_visible_conditions(current_user, org.id))
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="面经不存在或无权访问")
    share, email, nickname = row
    share.like_count = (share.like_count or 0) + 1
    share.updated_at = utc_now()
    log_audit_event(
        db,
        event_type="community.experience_like",
        resource_type="interview_experience_share",
        actor_user_id=current_user.id,
        target_user_id=share.user_id,
        organization_id=share.organization_id,
        resource_id=str(share.id),
        request=request,
    )
    await db.commit()
    await db.refresh(share)
    return _experience_response(share, email=email, nickname=nickname, current_user_id=current_user.id)


@router.delete("/experiences/{experience_id}")
async def delete_experience(
    experience_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    share = await db.scalar(
        select(InterviewExperienceShare).where(
            InterviewExperienceShare.id == experience_id,
            InterviewExperienceShare.user_id == current_user.id,
        )
    )
    if not share:
        raise HTTPException(status_code=404, detail="面经不存在或无权删除")
    previous_target = profile_target(share)
    log_audit_event(
        db,
        event_type="community.experience_delete",
        resource_type="interview_experience_share",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=share.organization_id,
        resource_id=str(share.id),
        request=request,
    )
    await db.delete(share)
    await db.flush()
    await refresh_share_profile(db, share, previous_targets=[previous_target] if previous_target else None)
    await db.commit()
    return {"message": "删除成功"}
