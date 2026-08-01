import re
import uuid
from collections import Counter
from datetime import datetime, time
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyInterviewProfile, InterviewExperienceShare
from app.services.quality import redact_sensitive_text
from app.services.training_profile import TRAINING_DIMENSIONS
from app.utils.time import utc_now


PROFILE_VERSION = 1

COMPANY_ALIASES = {
    "alibaba": "阿里巴巴",
    "阿里": "阿里巴巴",
    "阿里集团": "阿里巴巴",
    "腾讯科技": "腾讯",
    "tencent": "腾讯",
    "bytedance": "字节跳动",
    "字节": "字节跳动",
    "meituan": "美团",
    "jd": "京东",
    "jingdong": "京东",
    "baidu": "百度",
}

POSITION_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("ai agent", "agent开发", "agent 开发", "智能体开发"), "AI Agent 开发"),
    (("后端开发", "后端工程师", "backend", "服务端开发"), "后端开发"),
    (("前端开发", "前端工程师", "frontend"), "前端开发"),
    (("算法工程师", "算法开发", "machine learning", "机器学习"), "算法工程师"),
    (("大模型", "llm"), "大模型应用开发"),
    (("产品经理", "product manager"), "产品经理"),
]

ROUND_DEFINITIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("technical_first", "技术一面", ("技术一面", "技术初面", "技术初试", "一面", "初面")),
    ("technical_second", "技术二面", ("技术二面", "二面", "复试")),
    ("project_deep_dive", "项目深挖", ("项目深挖", "项目面", "项目追问")),
    ("system_design", "系统设计", ("系统设计", "架构面", "架构设计")),
    ("hr_behavior", "HR / 行为面", ("hr面", "hr 面", "hr", "行为面", "人力面")),
    ("manager_round", "主管面", ("主管面", "leader面", "leader 面", "经理面")),
    ("final_round", "终面", ("终面", "交叉面", "综合终面")),
]

EXTRA_TOPIC_PATTERNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "system_design": ("系统设计", ("系统设计", "架构", "扩展性", "高可用", "数据流")),
    "observability": ("可观测性", ("可观测性", "链路追踪", "监控", "metrics", "日志")),
    "database": ("数据库", ("数据库", "mysql", "postgresql", "sql", "索引", "事务")),
    "cache_queue": ("缓存与队列", ("redis", "缓存", "消息队列", "kafka", "rabbitmq", "队列")),
    "deployment": ("部署与稳定性", ("docker", "kubernetes", "k8s", "发布", "回滚", "稳定性")),
}


def _compact_text(value: Any, max_chars: int) -> str:
    return redact_sensitive_text(re.sub(r"\s+", " ", str(value or ""))).strip()[:max_chars]


def normalize_company_name(value: str | None) -> str:
    text = _compact_text(value, 160).strip(" ,，。.;；")
    lowered = text.lower()
    if lowered in COMPANY_ALIASES:
        return COMPANY_ALIASES[lowered]
    normalized = re.sub(r"[\s·•]+", "", lowered)
    normalized = re.sub(
        r"(?:股份)?有限责任公司$|股份有限公司$|有限公司$|集团公司$|集团$|公司$|inc\.?$|ltd\.?$|corp\.?$|corporation$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    return COMPANY_ALIASES.get(normalized, normalized or lowered)


def normalize_position_name(value: str | None) -> str:
    text = _compact_text(value, 200).strip(" ,，。.;；")
    lowered = re.sub(r"\s+", " ", text.lower())
    for aliases, canonical in POSITION_ALIASES:
        if any(alias in lowered for alias in aliases):
            suffix = "实习" if "实习" in lowered or "intern" in lowered else ""
            return f"{canonical}{suffix}"
    return lowered


def normalize_rounds(value: str | None) -> list[dict[str, str]]:
    text = _compact_text(value, 300).lower()
    if not text:
        return []
    pieces = [item.strip() for item in re.split(r"[/、,，;；|\n]+", text) if item.strip()]
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for piece in pieces or [text]:
        matched = False
        for round_type, name, aliases in ROUND_DEFINITIONS:
            if any(alias in piece for alias in aliases):
                if round_type not in seen:
                    result.append({"round_type": round_type, "name": name})
                    seen.add(round_type)
                matched = True
                break
        if not matched:
            key = re.sub(r"\s+", "_", piece)[:40]
            if key and key not in seen:
                result.append({"round_type": key, "name": piece[:60]})
                seen.add(key)
    return result


def canonicalize_question(value: str | None) -> str:
    text = _compact_text(value, 300).strip(" ,，。.;；?？")
    text = re.sub(r"^(?:q\d+[:：.、]?|问题\d*[:：]?|第[一二三四五六七八九十\d]+题[:：]?)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:请你?|能否|可以)?(?:介绍一下|说一下|讲一下|谈谈|解释一下|描述一下)", "", text)
    replacements = {
        "检索增强生成": "RAG",
        "function calling": "Tool Calling",
        "函数调用": "Tool Calling",
        "工具调用": "Tool Calling",
        "提示词注入": "Prompt Injection",
        "向量数据库": "向量库",
    }
    for source, target in replacements.items():
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()[:300]


def _question_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _same_question(left: str, right: str) -> bool:
    left_key = _question_key(left)
    right_key = _question_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shorter, longer = sorted((left_key, right_key), key=len)
    if len(shorter) >= 10 and shorter in longer and len(shorter) / len(longer) >= 0.76:
        return True
    return SequenceMatcher(None, left_key, right_key).ratio() >= 0.86


def detect_technical_topics(*parts: Any) -> list[dict[str, str]]:
    text = " ".join(_compact_text(part, 12_000) for part in parts).lower()
    topics: list[dict[str, str]] = []
    for key, config in TRAINING_DIMENSIONS.items():
        if any(str(keyword).lower() in text for keyword in config.get("keywords") or []):
            topics.append({"topic_key": key, "name": str(config.get("label") or key)})
    for key, (name, keywords) in EXTRA_TOPIC_PATTERNS.items():
        if any(keyword.lower() in text for keyword in keywords):
            topics.append({"topic_key": key, "name": name})
    return list({item["topic_key"]: item for item in topics}.values())


def profile_confidence(interview_count: int) -> str:
    if interview_count >= 8:
        return "high"
    if interview_count >= 3:
        return "medium"
    return "low"


def _profile_scope(share: InterviewExperienceShare) -> tuple[str, uuid.UUID | None, str] | None:
    if share.status != "published" or not bool(share.allow_profile_usage):
        return None
    if share.visibility == "public":
        return "public", None, "public"
    if share.visibility == "organization" and share.organization_id:
        return "organization", share.organization_id, str(share.organization_id)
    return None


def _observed_at(share: InterviewExperienceShare) -> datetime:
    if share.interview_date:
        return datetime.combine(share.interview_date, time.min)
    return share.created_at or utc_now()


def _mode(values: Iterable[str], default: str = "unknown") -> str:
    counter = Counter(item for item in values if item)
    return counter.most_common(1)[0][0] if counter else default


def _aggregate_profile(shares: list[InterviewExperienceShare]) -> dict[str, Any]:
    round_counts: Counter[str] = Counter()
    round_names: dict[str, str] = {}
    topic_counts: Counter[str] = Counter()
    topic_names: dict[str, str] = {}
    difficulty_counts: Counter[str] = Counter()
    question_groups: list[dict[str, Any]] = []

    for share in shares:
        rounds = normalize_rounds(share.rounds)
        for item in rounds:
            round_counts[item["round_type"]] += 1
            round_names[item["round_type"]] = item["name"]
        difficulty_counts[share.difficulty or "unknown"] += 1
        share_topics = detect_technical_topics(
            " ".join(share.tags or []),
            " ".join(share.questions or []),
            share.process,
            share.content,
        )
        for topic in share_topics:
            topic_counts[topic["topic_key"]] += 1
            topic_names[topic["topic_key"]] = topic["name"]

        default_round = rounds[0]["round_type"] if len(rounds) == 1 else "unspecified"
        for raw_question in share.questions or []:
            sample = _compact_text(raw_question, 300)
            canonical = canonicalize_question(sample)
            if not canonical:
                continue
            question_topics = detect_technical_topics(canonical)
            match = next(
                (group for group in question_groups if _same_question(group["canonical_question"], canonical)),
                None,
            )
            if match is None:
                match = {
                    "canonical_question": canonical,
                    "sample_question": sample,
                    "occurrence_count": 0,
                    "source_ids": set(),
                    "round_types": [],
                    "topics": {},
                    "difficulties": [],
                }
                question_groups.append(match)
            match["occurrence_count"] += 1
            match["source_ids"].add(str(share.id))
            match["round_types"].append(default_round)
            match["difficulties"].append(share.difficulty or "unknown")
            for topic in question_topics:
                match["topics"][topic["topic_key"]] = topic["name"]

    frequent_questions = [
        {
            "canonical_question": group["canonical_question"],
            "sample_question": group["sample_question"],
            "occurrence_count": group["occurrence_count"],
            "round_type": _mode(group["round_types"], "unspecified"),
            "topics": list(group["topics"].values()),
            "difficulty": _mode(group["difficulties"]),
            "source_count": len(group["source_ids"]),
        }
        for group in question_groups
    ]
    frequent_questions.sort(key=lambda item: (-item["source_count"], -item["occurrence_count"], item["canonical_question"]))
    common_rounds = [
        {"round_type": key, "name": round_names[key], "occurrence_count": count, "source_count": count}
        for key, count in round_counts.most_common()
    ]
    technical_topics = [
        {"topic_key": key, "name": topic_names[key], "occurrence_count": count, "source_count": count}
        for key, count in topic_counts.most_common()
    ]
    observed = [_observed_at(share) for share in shares]
    return {
        "company_name": _mode((share.company for share in shares), shares[0].company),
        "position_name": _mode((share.position for share in shares), shares[0].position),
        "common_rounds": common_rounds,
        "frequent_questions": frequent_questions[:50],
        "technical_topics": technical_topics,
        "difficulty_distribution": dict(difficulty_counts),
        "interview_count": len(shares),
        "source_experience_ids": [str(share.id) for share in shares],
        "first_observed_at": min(observed),
        "last_observed_at": max(observed),
    }


async def _eligible_scope_shares(
    db: AsyncSession,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
) -> list[InterviewExperienceShare]:
    conditions = [
        InterviewExperienceShare.status == "published",
        InterviewExperienceShare.allow_profile_usage.is_(True),
    ]
    if scope == "public":
        conditions.append(InterviewExperienceShare.visibility == "public")
    else:
        conditions.extend(
            [
                InterviewExperienceShare.visibility == "organization",
                InterviewExperienceShare.organization_id == organization_id,
            ]
        )
    return (await db.execute(select(InterviewExperienceShare).where(*conditions))).scalars().all()


async def rebuild_profile_key(
    db: AsyncSession,
    *,
    scope: str,
    organization_id: uuid.UUID | None,
    normalized_company_name: str,
    normalized_position_name: str,
) -> CompanyInterviewProfile | None:
    scope_key = "public" if scope == "public" else str(organization_id)
    existing = await db.scalar(
        select(CompanyInterviewProfile).where(
            CompanyInterviewProfile.scope_key == scope_key,
            CompanyInterviewProfile.normalized_company_name == normalized_company_name,
            CompanyInterviewProfile.normalized_position_name == normalized_position_name,
        )
    )
    shares = [
        share
        for share in await _eligible_scope_shares(db, scope=scope, organization_id=organization_id)
        if normalize_company_name(share.company) == normalized_company_name
        and normalize_position_name(share.position) == normalized_position_name
    ]
    if not shares:
        if existing:
            await db.delete(existing)
            await db.flush()
        return None

    aggregate = _aggregate_profile(shares)
    now = utc_now()
    profile = existing or CompanyInterviewProfile(
        organization_id=organization_id,
        scope=scope,
        scope_key=scope_key,
        normalized_company_name=normalized_company_name,
        normalized_position_name=normalized_position_name,
        created_at=now,
    )
    for key, value in aggregate.items():
        setattr(profile, key, value)
    profile.organization_id = organization_id
    profile.scope = scope
    profile.scope_key = scope_key
    profile.generated_at = now
    profile.updated_at = now
    profile.profile_version = PROFILE_VERSION
    profile.profile_metadata = {
        "aggregation_method": "structured_deterministic_v1",
        "confidence": profile_confidence(len(shares)),
        "redaction_applied": True,
    }
    if not existing:
        db.add(profile)
    await db.flush()
    return profile


async def refresh_share_profile(
    db: AsyncSession,
    share: InterviewExperienceShare,
    *,
    previous_targets: list[tuple[str, uuid.UUID | None, str, str]] | None = None,
) -> list[CompanyInterviewProfile]:
    targets = list(previous_targets or [])
    scope = _profile_scope(share)
    if scope:
        targets.append((*scope[:2], normalize_company_name(share.company), normalize_position_name(share.position)))
    unique_targets = list(dict.fromkeys(targets))
    profiles: list[CompanyInterviewProfile] = []
    for target_scope, organization_id, company, position in unique_targets:
        profile = await rebuild_profile_key(
            db,
            scope=target_scope,
            organization_id=organization_id,
            normalized_company_name=company,
            normalized_position_name=position,
        )
        if profile:
            profiles.append(profile)
    return profiles


def profile_target(share: InterviewExperienceShare) -> tuple[str, uuid.UUID | None, str, str] | None:
    scope = _profile_scope(share)
    if not scope:
        return None
    return scope[0], scope[1], normalize_company_name(share.company), normalize_position_name(share.position)


async def rebuild_all_profiles(
    db: AsyncSession,
    *,
    company: str | None = None,
    position: str | None = None,
    scope: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> list[CompanyInterviewProfile]:
    company_filter = normalize_company_name(company) if company else None
    position_filter = normalize_position_name(position) if position else None
    shares = (
        await db.execute(
            select(InterviewExperienceShare).where(
                InterviewExperienceShare.status == "published",
                InterviewExperienceShare.allow_profile_usage.is_(True),
                InterviewExperienceShare.visibility.in_(["public", "organization"]),
            )
        )
    ).scalars().all()
    targets: set[tuple[str, uuid.UUID | None, str, str]] = set()
    for share in shares:
        target = profile_target(share)
        if not target:
            continue
        if scope and target[0] != scope:
            continue
        if scope == "organization" and organization_id and target[1] != organization_id:
            continue
        if company_filter and target[2] != company_filter:
            continue
        if position_filter and target[3] != position_filter:
            continue
        targets.add(target)

    existing_profiles = (await db.execute(select(CompanyInterviewProfile))).scalars().all()
    target_keys = {
        ("public" if target_scope == "public" else str(target_org_id), target_company, target_position)
        for target_scope, target_org_id, target_company, target_position in targets
    }
    for profile in existing_profiles:
        if scope and profile.scope != scope:
            continue
        if scope == "organization" and organization_id and profile.organization_id != organization_id:
            continue
        if company_filter and profile.normalized_company_name != company_filter:
            continue
        if position_filter and profile.normalized_position_name != position_filter:
            continue
        key = (profile.scope_key, profile.normalized_company_name, profile.normalized_position_name)
        if key not in target_keys:
            await db.delete(profile)
    await db.flush()

    profiles: list[CompanyInterviewProfile] = []
    for target_scope, target_org_id, target_company, target_position in sorted(targets, key=lambda item: (item[0], str(item[1]), item[2], item[3])):
        profile = await rebuild_profile_key(
            db,
            scope=target_scope,
            organization_id=target_org_id,
            normalized_company_name=target_company,
            normalized_position_name=target_position,
        )
        if profile:
            profiles.append(profile)
    return profiles


def visible_profile_condition(organization_id: uuid.UUID | None) -> Any:
    return or_(
        CompanyInterviewProfile.scope == "public",
        and_(
            CompanyInterviewProfile.scope == "organization",
            CompanyInterviewProfile.organization_id == organization_id,
        ),
    )


async def find_matching_company_profile(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    company: str | None,
    position: str | None,
) -> CompanyInterviewProfile | None:
    normalized_company = normalize_company_name(company)
    normalized_position = normalize_position_name(position)
    if not normalized_company:
        return None
    candidates = (
        await db.execute(
            select(CompanyInterviewProfile).where(
                visible_profile_condition(organization_id),
                CompanyInterviewProfile.normalized_company_name == normalized_company,
            )
        )
    ).scalars().all()
    if not candidates:
        return None

    def score(profile: CompanyInterviewProfile) -> tuple[int, int, int]:
        profile_position = profile.normalized_position_name or ""
        position_score = 0
        if normalized_position and profile_position == normalized_position:
            position_score = 3
        elif normalized_position and (normalized_position in profile_position or profile_position in normalized_position):
            position_score = 2
        elif not normalized_position:
            position_score = 1
        scope_score = 1 if profile.scope == "organization" else 0
        return position_score, int(profile.interview_count or 0), scope_score

    return max(candidates, key=score)


def infer_target_from_jd(jd_text: str | None) -> tuple[str | None, str | None]:
    text = str(jd_text or "")[:4000]
    company_match = re.search(r"(?:公司名称|目标公司|公司|company)\s*[:：]\s*([^\n，,;；]{2,80})", text, re.IGNORECASE)
    position_match = re.search(r"(?:岗位名称|目标岗位|岗位|职位|position|role)\s*[:：]\s*([^\n，,;；]{2,100})", text, re.IGNORECASE)
    return (
        _compact_text(company_match.group(1), 160) if company_match else None,
        _compact_text(position_match.group(1), 200) if position_match else None,
    )


def company_profile_snapshot(profile: CompanyInterviewProfile | None) -> dict[str, Any]:
    if not profile:
        return {}
    frequent_questions = list(profile.frequent_questions or [])[:10]
    rounds = list(profile.common_rounds or [])[:8]
    topics = list(profile.technical_topics or [])[:10]
    confidence = profile_confidence(int(profile.interview_count or 0))
    return {
        "profile_id": str(profile.id),
        "matched_company": profile.company_name,
        "matched_position": profile.position_name,
        "scope": profile.scope,
        "profile_confidence": confidence,
        "source_count": int(profile.interview_count or 0),
        "profile_version": int(profile.profile_version or PROFILE_VERSION),
        "matched_rounds": rounds,
        "matched_topics": topics,
        "frequent_questions": frequent_questions,
        "referenced_questions": [item.get("canonical_question") for item in frequent_questions if item.get("canonical_question")],
        "generated_at": profile.generated_at.isoformat() if profile.generated_at else None,
    }


def company_profile_prompt_context(snapshot: dict[str, Any] | None, template_id: str) -> str:
    if not snapshot:
        return ""
    questions = list(snapshot.get("frequent_questions") or [])
    matching_questions = [
        item for item in questions if item.get("round_type") in {template_id, "unspecified"}
    ] or questions
    question_lines = [
        f"- [{item.get('round_type') or 'unspecified'} / {item.get('difficulty') or 'unknown'}] "
        f"{item.get('canonical_question')}（{item.get('source_count') or 1} 份来源）"
        for item in matching_questions[:5]
    ]
    round_text = "、".join(
        f"{item.get('name')}({item.get('source_count') or item.get('occurrence_count')})"
        for item in list(snapshot.get("matched_rounds") or [])[:6]
    )
    topic_text = "、".join(
        f"{item.get('name')}({item.get('source_count') or item.get('occurrence_count')})"
        for item in list(snapshot.get("matched_topics") or [])[:8]
    )
    weight = {"high": "高", "medium": "中", "low": "低"}.get(str(snapshot.get("profile_confidence")), "低")
    return (
        "公司面试画像外部约束：\n"
        f"目标公司/岗位：{snapshot.get('matched_company')} / {snapshot.get('matched_position')}\n"
        f"画像置信度：{weight}（{snapshot.get('source_count') or 0} 份面经）；低样本时仅作弱参考。\n"
        f"常见轮次：{round_text or '暂无'}\n"
        f"高频主题：{topic_text or '暂无'}\n"
        f"同类高频问题：\n{chr(10).join(question_lines) if question_lines else '- 暂无结构化高频题'}\n"
        "使用规则：按当前轮次生成同类题或追问题，不要逐字复制历史问题；画像只能调整主题、难度和追问方式，"
        "不能覆盖简历项目与 JD 证据，也不能提及画像、样本、模板或题库设置。"
    )
