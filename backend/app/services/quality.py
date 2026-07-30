import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Interview, InterviewQuestion, JobApplication, QualityAnnotation, QualityEvalCandidate, ResumeVersion, User

TARGET_TYPES = {"job", "resume_version", "interview", "interview_report", "interview_question", "ats_report"}
SENSITIVE_METADATA_KEYS = {"resume", "resume_text", "jd", "jd_text", "api_key", "phone", "email", "mobile"}
NEGATIVE_QUALITY_LABELS = {"证据不足", "表达套话", "遗漏 JD 要求", "虚构内容", "对比不清晰", "不可用", "问题较多"}
QUALITY_CANDIDATE_STATUSES = {"open", "accepted", "added_to_eval", "dismissed"}
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
API_KEY_PATTERN = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_\-]{12,}\b", re.IGNORECASE)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="target_id 必须是合法 UUID") from exc


def clean_quality_labels(labels: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        text = " ".join(str(label or "").split()).strip(" ,，;；。")
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text[:40])
    return cleaned[:12]


def redact_sensitive_text(value: str | None) -> str:
    text = str(value or "")
    text = EMAIL_PATTERN.sub("[email_redacted]", text)
    text = PHONE_PATTERN.sub("[phone_redacted]", text)
    text = API_KEY_PATTERN.sub("[key_redacted]", text)
    return text


def safe_annotation_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        key_text = str(key or "").strip()[:60]
        if not key_text or key_text.lower() in SENSITIVE_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = redact_sensitive_text(str(value))[:200] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key_text] = [redact_sensitive_text(str(item))[:80] for item in value[:12]]
    return safe


def _quality_candidate_priority(score: int, labels: list[str]) -> int:
    if score <= 1 or "虚构内容" in labels or "不可用" in labels:
        return 3
    if score <= 2 or any(label in NEGATIVE_QUALITY_LABELS for label in labels):
        return 2
    return 1


def _should_create_eval_candidate(score: int, labels: list[str]) -> bool:
    threshold = max(1, min(5, get_settings().QUALITY_EVAL_CANDIDATE_SCORE_THRESHOLD))
    return score <= threshold or any(label in NEGATIVE_QUALITY_LABELS for label in labels)


async def create_eval_candidate_if_needed(db: AsyncSession, annotation: QualityAnnotation) -> QualityEvalCandidate | None:
    labels = clean_quality_labels(annotation.labels or [])
    if not _should_create_eval_candidate(annotation.score, labels):
        return None
    existing = await db.scalar(
        select(QualityEvalCandidate).where(QualityEvalCandidate.annotation_id == annotation.id)
    )
    if existing:
        return existing

    note = redact_sensitive_text(annotation.notes or "").strip()
    issue_summary = note[:500] or "用户给出了低分或负向标签，需要纳入回归评测复核。"
    candidate = QualityEvalCandidate(
        user_id=annotation.user_id,
        organization_id=annotation.organization_id,
        annotation_id=annotation.id,
        target_type=annotation.target_type,
        target_id=annotation.target_id,
        source_score=annotation.score,
        priority=_quality_candidate_priority(annotation.score, labels),
        labels=labels,
        issue_summary=issue_summary,
        status="open",
        candidate_metadata={
            "source": "quality_annotation",
            "reviewer_role": annotation.reviewer_role,
        },
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def resolve_quality_target(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    if target_type not in TARGET_TYPES:
        raise HTTPException(status_code=400, detail="不支持的标注对象")
    target_uuid = _uuid(target_id)

    if target_type in {"job", "ats_report"}:
        job = await db.scalar(select(JobApplication).where(JobApplication.id == target_uuid, JobApplication.user_id == user_id))
        if not job:
            raise HTTPException(status_code=404, detail="岗位任务不存在")
        return {"resource_type": "job", "resource_id": str(job.id), "organization_id": job.organization_id}

    if target_type == "resume_version":
        version = await db.scalar(select(ResumeVersion).where(ResumeVersion.id == target_uuid, ResumeVersion.user_id == user_id))
        if not version:
            raise HTTPException(status_code=404, detail="简历版本不存在")
        return {"resource_type": "resume_version", "resource_id": str(version.id), "organization_id": version.organization_id}

    if target_type in {"interview", "interview_report"}:
        interview = await db.scalar(select(Interview).where(Interview.id == target_uuid, Interview.user_id == user_id))
        if not interview:
            raise HTTPException(status_code=404, detail="面试不存在")
        return {"resource_type": "interview", "resource_id": str(interview.id), "organization_id": interview.organization_id}

    result = await db.execute(
        select(InterviewQuestion, Interview)
        .join(Interview, Interview.id == InterviewQuestion.interview_id)
        .where(InterviewQuestion.id == target_uuid, Interview.user_id == user_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="面试题不存在")
    question, interview = row
    return {"resource_type": "interview_question", "resource_id": str(question.id), "organization_id": interview.organization_id}


async def build_quality_summary(db: AsyncSession, *, limit: int = 20) -> dict[str, Any]:
    total = await db.scalar(select(func.count()).select_from(QualityAnnotation)) or 0
    avg_score = await db.scalar(select(func.avg(QualityAnnotation.score))) or 0
    target_rows = (
        await db.execute(
            select(QualityAnnotation.target_type, func.count(), func.avg(QualityAnnotation.score))
            .group_by(QualityAnnotation.target_type)
        )
    ).all()
    score_rows = (
        await db.execute(
            select(QualityAnnotation.score, func.count())
            .group_by(QualityAnnotation.score)
            .order_by(QualityAnnotation.score.desc())
        )
    ).all()
    recent_rows = (
        await db.execute(
            select(QualityAnnotation, User.email)
            .join(User, User.id == QualityAnnotation.user_id)
            .order_by(QualityAnnotation.created_at.desc())
            .limit(limit)
        )
    ).all()
    candidate_status_rows = (
        await db.execute(
            select(QualityEvalCandidate.status, func.count())
            .group_by(QualityEvalCandidate.status)
        )
    ).all()
    recent_candidate_rows = (
        await db.execute(
            select(QualityEvalCandidate, User.email)
            .join(User, User.id == QualityEvalCandidate.user_id)
            .order_by(QualityEvalCandidate.priority.desc(), QualityEvalCandidate.created_at.desc())
            .limit(limit)
        )
    ).all()

    label_counts: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for annotation, email in recent_rows:
        for label in annotation.labels or []:
            label_counts[str(label)] = label_counts.get(str(label), 0) + 1
        recent.append(
            {
                "id": str(annotation.id),
                "email": email,
                "target_type": annotation.target_type,
                "target_id": annotation.target_id,
                "score": annotation.score,
                "labels": annotation.labels or [],
                "notes": (annotation.notes or "")[:240],
                "status": annotation.status,
                "created_at": annotation.created_at,
            }
        )

    recent_candidates: list[dict[str, Any]] = []
    for candidate, email in recent_candidate_rows:
        recent_candidates.append(
            {
                "id": str(candidate.id),
                "email": email,
                "annotation_id": str(candidate.annotation_id) if candidate.annotation_id else None,
                "target_type": candidate.target_type,
                "target_id": candidate.target_id,
                "source_score": candidate.source_score,
                "priority": candidate.priority,
                "labels": candidate.labels or [],
                "issue_summary": (candidate.issue_summary or "")[:240],
                "status": candidate.status,
                "created_at": candidate.created_at,
            }
        )

    candidate_status_counts = {str(status): int(count) for status, count in candidate_status_rows}
    return {
        "total": int(total),
        "avg_score": round(float(avg_score or 0), 2),
        "score_distribution": {str(score): count for score, count in score_rows},
        "target_stats": [
            {"target_type": target_type, "count": count, "avg_score": round(float(avg or 0), 2)}
            for target_type, count, avg in target_rows
        ],
        "top_labels": [
            {"label": label, "count": count}
            for label, count in sorted(label_counts.items(), key=lambda item: item[1], reverse=True)[:12]
        ],
        "recent": recent,
        "eval_candidates": {
            "total": sum(candidate_status_counts.values()),
            "open": candidate_status_counts.get("open", 0),
            "accepted": candidate_status_counts.get("accepted", 0),
            "added_to_eval": candidate_status_counts.get("added_to_eval", 0),
            "dismissed": candidate_status_counts.get("dismissed", 0),
            "status_counts": candidate_status_counts,
            "recent": recent_candidates,
        },
    }


async def list_eval_candidates(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[QualityEvalCandidate]:
    stmt = select(QualityEvalCandidate).order_by(QualityEvalCandidate.priority.desc(), QualityEvalCandidate.created_at.desc())
    if status:
        if status not in QUALITY_CANDIDATE_STATUSES:
            raise HTTPException(status_code=400, detail="不支持的评测候选状态")
        stmt = stmt.where(QualityEvalCandidate.status == status)
    stmt = stmt.limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def update_eval_candidate_status(
    db: AsyncSession,
    *,
    candidate_id: uuid.UUID,
    status: str,
) -> QualityEvalCandidate:
    if status not in QUALITY_CANDIDATE_STATUSES:
        raise HTTPException(status_code=400, detail="不支持的评测候选状态")
    candidate = await db.scalar(select(QualityEvalCandidate).where(QualityEvalCandidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="评测候选不存在")
    candidate.status = status
    await db.flush()
    return candidate
