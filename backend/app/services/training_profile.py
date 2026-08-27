import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrainingProfileDimension
from app.utils.time import utc_now

TRAINING_DIMENSIONS: dict[str, dict[str, Any]] = {
    "rag": {
        "label": "RAG",
        "keywords": ("rag", "检索", "召回", "重排", "embedding", "向量", "chunk", "切片", "rrf", "bm25", "qdrant", "bge"),
    },
    "tool_calling": {
        "label": "Tool Calling",
        "keywords": ("tool calling", "function calling", "工具调用", "函数调用", "工具", "schema", "参数", "重试", "降级"),
    },
    "agent_memory": {
        "label": "Agent Memory",
        "keywords": ("memory", "记忆", "短期记忆", "长期记忆", "会话", "上下文", "规划", "反思", "agent"),
    },
    "prompt_injection": {
        "label": "Prompt Injection",
        "keywords": ("prompt injection", "提示词注入", "提示注入", "越权", "安全", "防护", "注入", "越狱"),
    },
    "engineering": {
        "label": "工程化",
        "keywords": ("工程化", "监控", "日志", "评测", "上线", "回滚", "接口", "队列", "缓存", "权限", "ci/cd", "docker", "fastapi"),
    },
}


def clamp_mastery(value: int) -> int:
    return max(0, min(100, int(value)))


def detect_training_dimensions(*parts: Any) -> list[str]:
    text = re.sub(r"\s+", " ", " ".join(str(part or "") for part in parts)).lower()
    hits: list[str] = []
    for key, config in TRAINING_DIMENSIONS.items():
        if any(keyword.lower() in text for keyword in config["keywords"]):
            hits.append(key)
    if not hits and any(term in text for term in ("agent", "智能体", "大模型", "llm")):
        hits.append("engineering")
    return hits


async def get_or_create_profile_dimension(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    dimension_key: str,
    organization_id: uuid.UUID | None = None,
) -> TrainingProfileDimension:
    if dimension_key not in TRAINING_DIMENSIONS:
        dimension_key = "engineering"
    dimension = await db.scalar(
        select(TrainingProfileDimension).where(
            TrainingProfileDimension.user_id == user_id,
            TrainingProfileDimension.dimension_key == dimension_key,
        )
    )
    if dimension:
        if organization_id and not dimension.organization_id:
            dimension.organization_id = organization_id
        return dimension
    config = TRAINING_DIMENSIONS[dimension_key]
    dimension = TrainingProfileDimension(
        user_id=user_id,
        organization_id=organization_id,
        dimension_key=dimension_key,
        dimension_label=config["label"],
        mastery_score=60,
        exposure_count=0,
        known_count=0,
        weak_count=0,
        low_score_count=0,
        profile_metadata={"keywords": list(config["keywords"])[:12]},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(dimension)
    await db.flush()
    return dimension


async def ensure_training_profile(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> list[TrainingProfileDimension]:
    dimensions = [
        await get_or_create_profile_dimension(
            db,
            user_id=user_id,
            organization_id=organization_id,
            dimension_key=dimension_key,
        )
        for dimension_key in TRAINING_DIMENSIONS
    ]
    return dimensions


async def apply_training_signal(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    dimension_keys: list[str] | None = None,
    signal: str,
    source: str,
) -> list[TrainingProfileDimension]:
    keys = [key for key in dict.fromkeys(dimension_keys or []) if key in TRAINING_DIMENSIONS]
    if not keys:
        keys = ["engineering"]
    now = utc_now()
    updated: list[TrainingProfileDimension] = []
    for key in keys:
        dimension = await get_or_create_profile_dimension(
            db,
            user_id=user_id,
            organization_id=organization_id,
            dimension_key=key,
        )
        dimension.exposure_count = int(dimension.exposure_count or 0) + 1
        if signal == "known":
            dimension.known_count = int(dimension.known_count or 0) + 1
            dimension.mastery_score = clamp_mastery(int(dimension.mastery_score or 60) + 8)
        elif signal == "low_score":
            dimension.low_score_count = int(dimension.low_score_count or 0) + 1
            dimension.weak_count = int(dimension.weak_count or 0) + 1
            dimension.mastery_score = clamp_mastery(int(dimension.mastery_score or 60) - 12)
        else:
            dimension.weak_count = int(dimension.weak_count or 0) + 1
            dimension.mastery_score = clamp_mastery(int(dimension.mastery_score or 60) - 10)
        dimension.last_signal = signal
        dimension.last_source = source
        dimension.last_practiced_at = now
        dimension.updated_at = now
        updated.append(dimension)
    await db.flush()
    return updated


def weakest_dimensions(dimensions: list[TrainingProfileDimension], *, limit: int = 3) -> list[TrainingProfileDimension]:
    return sorted(
        dimensions,
        key=lambda item: (int(item.mastery_score or 60), -int(item.weak_count or 0), item.dimension_key),
    )[:limit]


async def training_focus_context(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    limit: int = 3,
) -> tuple[str, list[dict[str, Any]]]:
    dimensions = await ensure_training_profile(db, user_id=user_id, organization_id=organization_id)
    weak = [
        dimension
        for dimension in weakest_dimensions(dimensions, limit=limit)
        if int(dimension.mastery_score or 60) <= 68 or int(dimension.weak_count or 0) > 0
    ]
    if not weak:
        return "", []
    focus_items = []
    lines = ["用户弱项记忆（下一次 Agent 八股题优先覆盖，但仍需结合简历项目和 JD）："]
    for dimension in weak:
        config = TRAINING_DIMENSIONS.get(dimension.dimension_key, {})
        keywords = "、".join(str(item) for item in (config.get("keywords") or [])[:6])
        item = {
            "dimension_key": dimension.dimension_key,
            "dimension_label": dimension.dimension_label,
            "mastery_score": int(dimension.mastery_score or 0),
            "weak_count": int(dimension.weak_count or 0),
            "keywords": keywords,
        }
        focus_items.append(item)
        lines.append(
            f"- {dimension.dimension_label}：掌握度 {item['mastery_score']}/100，"
            f"薄弱记录 {item['weak_count']} 次；建议追问关键词：{keywords}"
        )
    return "\n".join(lines), focus_items
