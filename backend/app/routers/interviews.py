import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Interview, InterviewQuestion, JobApplication, Resume, User
from app.schemas import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    InterviewCreateRequest,
    InterviewQuestionResponse,
    InterviewReportResponse,
    InterviewResponse,
    InterviewTemplateResponse,
)
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user
from app.services.company_profiles import (
    company_profile_prompt_context,
    company_profile_snapshot,
    find_matching_company_profile,
    infer_target_from_jd,
)
from app.services.data_sanitization import redact_sensitive_text
from app.services.document_export import (
    content_disposition,
    interview_report_to_docx_bytes,
    interview_report_to_markdown,
    safe_filename,
    text_to_pdf_bytes,
)
from app.services.interview_generation_service import request_generated_questions
from app.services.interview_report_service import request_interview_report
from app.services.interview_scoring_service import request_answer_score
from app.services.interview_templates import (
    DEFAULT_INTERVIEW_TEMPLATE_ID,
    get_interview_template,
    list_interview_templates,
    template_snapshot,
)
from app.services.knowledge_base import build_rag_context, compact_json, retrieve_knowledge
from app.services.llm_client import get_llm_client
from app.services.resume_index import ensure_resume_chunks, retrieve_resume_evidence
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.services.training_profile import apply_training_signal, detect_training_dimensions
from app.services.training_profile import training_focus_context as build_training_focus_context
from app.services.usage_telemetry import record_usage
from app.utils.time import utc_now

router = APIRouter(prefix="/api/interviews", tags=["interviews"])
settings = get_settings()


@dataclass
class QuestionBatch:
    module: str
    point_id: str
    title: str
    source_section: str
    description: str
    context: str
    limit: int = 5


TECH_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("混合检索/RRF", ("混合检索", "rrf", "bm25", "倒数排序", "融合排序", "rank fusion")),
    ("RAG", ("rag", "检索增强", "知识库", "召回", "重排")),
    ("Qdrant", ("qdrant",)),
    ("BGE-M3", ("bge-m3", "bge m3", "bge")),
    ("Agent", ("agent", "智能体", "规划", "反思", "记忆")),
    ("Tool Calling", ("tool calling", "function calling", "工具调用", "函数调用")),
    ("Prompt Injection", ("prompt injection", "提示词注入", "越权提示", "提示注入")),
    ("FastAPI", ("fastapi",)),
    ("Redis", ("redis", "缓存", "队列")),
    ("PostgreSQL", ("postgresql", "postgres")),
    ("MySQL", ("mysql",)),
    ("SQL", ("sql", "索引", "事务", "慢查询")),
    ("React", ("react",)),
    ("Vue", ("vue",)),
    ("Next.js", ("next.js", "nextjs", "next")),
    ("TypeScript", ("typescript", "ts")),
    ("API", ("api", "接口", "鉴权", "限流")),
    ("数据清洗", ("数据清洗", "清洗", "etl", "pandas", "spark")),
    ("可视化", ("可视化", "报表", "看板", "仪表盘", "图表")),
    ("前端状态管理", ("状态管理", "redux", "zustand", "pinia", "状态流转")),
    ("CI/CD", ("ci/cd", "cicd", "流水线", "github actions", "gitlab ci", "jenkins")),
    ("Docker", ("docker", "镜像", "容器")),
    ("Kubernetes", ("kubernetes", "k8s")),
    ("部署运维", ("部署", "发布", "回滚", "健康检查", "故障恢复", "nginx", "linux")),
    ("异步任务", ("异步", "任务队列", "celery", "rq", "arq", "重试")),
    ("可观测性", ("日志", "监控", "链路追踪", "request_id", "metrics", "observability")),
]

SCORE_DIMENSION_KEYS = [
    "technical_accuracy",
    "project_understanding",
    "structure_clarity",
    "troubleshooting",
    "engineering_delivery",
    "reflection",
]

LEGACY_SCORE_ALIASES = {
    "technical_accuracy": ("depth", "consistency"),
    "project_understanding": ("completeness", "consistency"),
    "structure_clarity": ("logic", "conciseness"),
    "troubleshooting": ("depth",),
    "engineering_delivery": ("completeness", "depth"),
    "reflection": ("depth", "logic"),
}

SCORE_DIMENSION_LABELS = {
    "technical_accuracy": "技术准确性",
    "project_understanding": "项目理解",
    "structure_clarity": "表达结构",
    "troubleshooting": "问题定位",
    "engineering_delivery": "工程落地",
    "reflection": "复盘能力",
}

RESUME_EVIDENCE_SECTIONS = {
    "project": ["project"],
    "internship": ["experience"],
    "agent_fundamentals": ["skills", "project", "experience"],
    "system_design": ["project", "experience", "skills"],
    "behavioral": ["project", "experience"],
    "resume": None,
}

QUESTION_QUALITY_KEYWORDS = (
    "RAG",
    "RRF",
    "BM25",
    "Qdrant",
    "BGE",
    "Embedding",
    "FastAPI",
    "Redis",
    "PostgreSQL",
    "MySQL",
    "SQL",
    "React",
    "Vue",
    "Next.js",
    "TypeScript",
    "Agent",
    "Tool",
    "API",
    "Spark",
    "ETL",
    "Docker",
    "Kubernetes",
    "CI/CD",
    "接口",
    "索引",
    "切片",
    "重排",
    "检索",
    "队列",
    "重试",
    "日志",
    "监控",
    "权限",
    "联调",
    "排查",
    "指标",
    "上线",
    "验收",
    "数据清洗",
    "可视化",
    "报表",
    "看板",
    "状态管理",
    "部署",
    "流水线",
    "健康检查",
    "回滚",
)


def _fallback_point(exp: dict[str, Any]) -> dict[str, str]:
    title = exp.get("name") or exp.get("company") or exp.get("role") or "核心经历"
    description = exp.get("description") or "；".join(exp.get("highlights", [])[:3]) or str(exp)[:260]
    stable_id = uuid.uuid5(uuid.NAMESPACE_URL, title).hex[:12]
    return {"id": f"local-{stable_id}", "title": title, "description": description}


def _dedupe_text(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _interview_template_config(interview: Interview | None) -> dict[str, Any]:
    if interview and isinstance(interview.template_config_snapshot, dict) and interview.template_config_snapshot.get("template_id"):
        return dict(interview.template_config_snapshot)
    template_id = getattr(interview, "interview_template_id", None) if interview else None
    return get_interview_template(template_id)


def _template_prompt_context(template: dict[str, Any]) -> str:
    focuses = "、".join(str(item) for item in (template.get("question_focus") or [])[:8])
    ratios = "、".join(f"{key}:{value}" for key, value in (template.get("module_ratios") or {}).items())
    return (
        f"本轮面试模板：{template.get('name') or '综合面'}。\n"
        f"适用场景：{template.get('scenario') or ''}\n"
        f"出题重点：{focuses}\n"
        f"模块比例参考：{ratios}\n"
        "约束：问题必须直接面向候选人，围绕简历证据、项目经历和 JD 追问；不要询问模板设置、题库设计或面试系统本身。"
    )


def _template_score_context(template: dict[str, Any]) -> str:
    dimensions = template.get("scoring_dimensions") or []
    dimension_text = "；".join(
        f"{item.get('label') or item.get('key')} 权重 {item.get('weight')}"
        for item in dimensions
        if isinstance(item, dict)
    )
    report_focus = "、".join(str(item) for item in (template.get("report_focus") or [])[:8])
    return (
        f"本轮评分模板：{template.get('name') or '综合面'}。\n"
        f"评分重点：{dimension_text}\n"
        f"报告关注点：{report_focus}\n"
        "请按本轮重点解释扣分原因，但仍保留技术准确性、项目理解、表达结构、问题定位、工程落地、复盘能力六个基础分项。"
    )


def _clone_batch_with_limit(batch: QuestionBatch, limit: int) -> QuestionBatch:
    return QuestionBatch(
        module=batch.module,
        point_id=batch.point_id,
        title=batch.title,
        source_section=batch.source_section,
        description=batch.description,
        context=batch.context,
        limit=max(1, min(int(limit), int(batch.limit or limit or 1))),
    )


def _apply_template_to_batches(batches: list[QuestionBatch], template: dict[str, Any] | None) -> list[QuestionBatch]:
    if not template:
        return batches
    module_limits = {
        str(key): int(value)
        for key, value in (template.get("module_question_limits") or {}).items()
        if int(value or 0) > 0
    }
    module_order = [str(item) for item in (template.get("module_order") or [])]
    if not module_limits or not module_order:
        return batches

    by_module: dict[str, list[QuestionBatch]] = {}
    for batch in batches:
        by_module.setdefault(batch.module, []).append(batch)

    selected: list[QuestionBatch] = []
    for module in module_order:
        remaining = module_limits.get(module, 0)
        if remaining <= 0:
            continue
        for batch in by_module.get(module, []):
            if remaining <= 0:
                break
            limit = min(batch.limit, remaining)
            selected.append(_clone_batch_with_limit(batch, limit))
            remaining -= limit

    if not selected:
        return batches

    has_resume_anchor = any(batch.module in {"project", "internship", "resume"} for batch in selected)
    if not has_resume_anchor:
        for module in ("project", "internship", "resume"):
            candidate = (by_module.get(module) or [None])[0]
            if candidate:
                selected.append(_clone_batch_with_limit(candidate, 1))
                break

    return selected


def _template_dimension_scores(template: dict[str, Any], dimension_scores: dict[str, Any] | None) -> dict[str, float]:
    base_scores = dimension_scores or {}
    result: dict[str, float] = {}
    for dimension in template.get("scoring_dimensions") or []:
        if not isinstance(dimension, dict):
            continue
        key = str(dimension.get("key") or "")
        source_keys = [str(item) for item in (dimension.get("source_score_keys") or [])]
        values = []
        for source_key in source_keys:
            try:
                values.append(float(base_scores.get(source_key)))
            except (TypeError, ValueError):
                continue
        if key and values:
            result[key] = round(sum(values) / len(values), 1)
    return result


def _template_report_details(interview: Interview, questions: list[InterviewQuestion]) -> dict[str, Any]:
    template = _interview_template_config(interview)
    module_counts: dict[str, int] = {}
    for question in questions:
        module_counts[question.module or "resume"] = module_counts.get(question.module or "resume", 0) + 1
    return {
        "interview_template": {
            "template_id": template.get("template_id") or DEFAULT_INTERVIEW_TEMPLATE_ID,
            "name": template.get("name") or "综合面",
            "scenario": template.get("scenario") or "",
            "use_training_profile": bool(template.get("use_training_profile")),
            "use_company_profile": bool(template.get("use_company_profile")),
        },
        "template_focus": template.get("report_focus") or [],
        "template_question_focus": template.get("question_focus") or [],
        "template_module_distribution": module_counts,
        "template_dimension_scores": _template_dimension_scores(template, interview.dimension_scores or {}),
        "template_scoring_dimensions": template.get("scoring_dimensions") or [],
        "next_round_suggestions": template.get("next_round_suggestions") or [],
        "company_profile": interview.company_profile_snapshot or {},
        "company_profile_match": {
            "target_company": interview.target_company,
            "target_position": interview.target_position,
            "matched": bool(interview.company_profile_snapshot),
        },
    }


def _safe_target_text(value: str | None, max_chars: int) -> str | None:
    text = redact_sensitive_text(re.sub(r"\s+", " ", str(value or ""))).strip()
    return text[:max_chars] or None


def _company_generation_trace(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    return {
        "matched_company": snapshot.get("matched_company"),
        "matched_position": snapshot.get("matched_position"),
        "profile_confidence": snapshot.get("profile_confidence"),
        "matched_rounds": [item.get("round_type") for item in (snapshot.get("matched_rounds") or [])[:6]],
        "matched_topics": [item.get("name") for item in (snapshot.get("matched_topics") or [])[:8]],
        "referenced_questions": list(snapshot.get("referenced_questions") or [])[:5],
        "source_count": snapshot.get("source_count") or 0,
    }


def _template_with_company_profile_bias(
    template: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not snapshot or snapshot.get("profile_confidence") == "low":
        return template, {}
    round_to_module = {
        "technical_first": "agent_fundamentals",
        "technical_second": "project",
        "project_deep_dive": "project",
        "system_design": "system_design",
        "hr_behavior": "behavioral",
        "manager_round": "project",
        "final_round": "behavioral",
    }
    limits = {
        str(key): int(value or 0)
        for key, value in (template.get("module_question_limits") or {}).items()
    }
    ranked_rounds = sorted(
        (snapshot.get("matched_rounds") or []),
        key=lambda item: int(item.get("source_count") or item.get("occurrence_count") or 0),
        reverse=True,
    )
    target_round = next(
        (
            item
            for item in ranked_rounds
            if round_to_module.get(str(item.get("round_type") or "")) in limits
            and limits.get(round_to_module.get(str(item.get("round_type") or "")), 0) > 0
        ),
        None,
    )
    if not target_round:
        return template, {}
    target_module = round_to_module[str(target_round.get("round_type"))]
    donor_candidates = [
        (module, count)
        for module, count in limits.items()
        if module != target_module and count > 1
    ]
    if not donor_candidates:
        return template, {}
    donor_module, _ = max(donor_candidates, key=lambda item: item[1])
    adjusted = deepcopy(template)
    adjusted_limits = dict(limits)
    adjusted_limits[target_module] += 1
    adjusted_limits[donor_module] -= 1
    adjusted["module_question_limits"] = adjusted_limits
    total = sum(adjusted_limits.values()) or 1
    adjusted["module_ratios"] = {
        module: round(count / total, 3)
        for module, count in adjusted_limits.items()
        if count > 0
    }
    bias = {
        "round_type": target_round.get("round_type"),
        "round_name": target_round.get("name"),
        "target_module": target_module,
        "donor_module": donor_module,
        "shifted_questions": 1,
    }
    return adjusted, bias


def _text_excerpt(text: Any, max_chars: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_chars]


def _resume_evidence_dicts(snippets: list[Any], batch: QuestionBatch, *, limit: int = 3) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for snippet in snippets[:limit]:
        if hasattr(snippet, "to_dict"):
            payload = snippet.to_dict()
        elif isinstance(snippet, dict):
            payload = snippet
        else:
            payload = {}
        source_section = payload.get("section_label") or payload.get("section") or batch.module
        source_title = payload.get("item_title") or payload.get("title") or batch.source_section
        source_text = payload.get("content") or payload.get("source_text") or ""
        if not source_text:
            continue
        evidence.append(
            {
                "source_section": str(source_section),
                "source_title": str(source_title),
                "source_snippet": _text_excerpt(source_text, 220),
                "matched_jd_requirement": _text_excerpt(batch.description or batch.title, 120),
                "retrieval_score": round(float(payload.get("score") or 0), 3),
                "rerank_score": round(float(payload.get("rerank_score") or 0), 3) if payload.get("rerank_score") else None,
                "retrieval_source": str(payload.get("retrieval_source") or "resume_index"),
                "chunk_id": str(payload.get("chunk_id") or ""),
            }
        )
    return evidence


def _evidence_context(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "简历证据：未检索到足够片段，只能基于当前简历结构化内容出题，不得编造。"
    lines = ["简历证据片段（只能基于这些片段出题，不得编造没有出现的经历）："]
    for index, item in enumerate(evidence, 1):
        lines.append(
            f"{index}. 来源：{item.get('source_section')} / {item.get('source_title')}；"
            f"片段：{item.get('source_snippet')}"
        )
    return "\n".join(lines)


def _question_specificity_score(question_text: str, evidence: list[dict[str, Any]]) -> int:
    text = question_text or ""
    score = 2
    if _detect_tech_terms(text):
        score += 3
    if any(keyword.lower() in text.lower() for keyword in QUESTION_QUALITY_KEYWORDS):
        score += 2
    if any(marker in text for marker in ("为什么", "如何", "怎么", "排查", "验证", "取舍", "指标", "如果")):
        score += 2
    if any((item.get("source_title") or "") and str(item.get("source_title")) in text for item in evidence):
        score += 1
    return max(1, min(10, score))


def _question_quality(question_text: str, batch: QuestionBatch, evidence: list[dict[str, Any]], duplicate_risk: float = 0.0) -> dict[str, Any]:
    specificity = _question_specificity_score(question_text, evidence)
    evidence_score = min(10, 4 + len(evidence) * 2)
    if batch.module == "agent_fundamentals":
        evidence_score = max(6, evidence_score)
    quality = round((specificity * 0.55) + (evidence_score * 0.35) + ((10 - duplicate_risk * 10) * 0.1), 1)
    difficulty = "高" if any(term in question_text for term in ("排查", "取舍", "重排", "RRF", "Prompt Injection", "幂等")) else "中"
    if specificity <= 4:
        difficulty = "低"
    return {
        "specificity_score": specificity,
        "evidence_score": evidence_score,
        "duplicate_risk": round(duplicate_risk, 2),
        "difficulty": difficulty,
        "reason": "题目绑定了具体技术点和简历证据" if evidence else "证据不足时仅保留通用但可验证的追问",
        "overall": quality,
    }


def _score_detail(
    key: str,
    score: float,
    answer: str,
    question: InterviewQuestion,
    response: dict[str, Any],
) -> dict[str, Any]:
    answer_text = answer or ""
    evidence_items = question.evidence or []
    label = SCORE_DIMENSION_LABELS.get(key, key)
    issue = "回答较完整，但还可以补充更具体的项目证据。"
    suggestion = "按背景、个人动作、技术链路、验证结果、复盘改进补全答案。"
    risk = "低"
    if score < 6:
        risk = "高"
        issue = f"{label}不足，回答缺少清晰证据或关键技术细节。"
    elif score < 8:
        risk = "中"
        issue = f"{label}基本覆盖，但缺少指标、排查过程或方案取舍。"
    if key == "technical_accuracy":
        suggestion = "补充核心概念、链路边界、失败场景和为什么选择该方案。"
    elif key == "project_understanding":
        suggestion = "补充项目背景、个人负责模块、上下游依赖和最终交付物。"
    elif key == "structure_clarity":
        suggestion = "用 STAR 或“背景-动作-结果-复盘”组织答案，减少跳跃表达。"
    elif key == "troubleshooting":
        suggestion = "补充如何复现、看哪些日志/指标、如何验证修复有效。"
    elif key == "engineering_delivery":
        suggestion = "补充接口契约、联调、测试、上线、回滚和稳定性保障。"
    elif key == "reflection":
        suggestion = "补充指标变化、方案取舍、遗留风险和下一步优化动作。"
    return {
        "label": label,
        "score": round(float(score), 1),
        "evidence": _text_excerpt(answer_text, 160) or _text_excerpt((evidence_items[0] or {}).get("source_snippet") if evidence_items else "", 160),
        "issue": issue,
        "suggestion": suggestion,
        "risk": risk,
    }


def _normalize_score_details(
    response: dict[str, Any],
    scores: dict[str, float],
    answer: str,
    question: InterviewQuestion,
) -> dict[str, Any]:
    raw_details = response.get("score_details") or response.get("dimension_details") or {}
    details: dict[str, Any] = {}
    for key, score in scores.items():
        raw = raw_details.get(key) if isinstance(raw_details, dict) else None
        if isinstance(raw, dict):
            detail = {
                "label": raw.get("label") or SCORE_DIMENSION_LABELS.get(key, key),
                "score": round(float(raw.get("score", score)), 1),
                "evidence": _text_excerpt(raw.get("evidence") or answer, 180),
                "issue": _text_excerpt(raw.get("issue") or "", 220) or _score_detail(key, score, answer, question, response)["issue"],
                "suggestion": _text_excerpt(raw.get("suggestion") or "", 220) or _score_detail(key, score, answer, question, response)["suggestion"],
                "risk": raw.get("risk") or _score_detail(key, score, answer, question, response)["risk"],
            }
        else:
            detail = _score_detail(key, score, answer, question, response)
        details[key] = detail
    return details


def _hire_signal(total_score: float) -> str:
    if total_score >= 85:
        return "strong"
    if total_score >= 75:
        return "positive"
    if total_score >= 60:
        return "borderline"
    return "weak"


def _build_report_details(interview: Interview, questions: list[InterviewQuestion]) -> dict[str, Any]:
    answered = [question for question in questions if question.user_answer]
    module_scores: dict[str, list[float]] = {}
    strongest_evidence: list[dict[str, Any]] = []
    repeated_gaps: list[str] = []
    follow_up_questions: list[str] = []
    for question in answered:
        if question.total_score is not None:
            module_scores.setdefault(question.module or "resume", []).append(float(question.total_score))
        for item in question.evidence or []:
            if len(strongest_evidence) < 5 and item.get("source_snippet"):
                strongest_evidence.append(
                    {
                        "module": question.module,
                        "source": f"{item.get('source_section')} / {item.get('source_title')}",
                        "snippet": item.get("source_snippet"),
                    }
                )
        for detail in (question.score_details or {}).values():
            if isinstance(detail, dict) and detail.get("risk") in {"中", "高"}:
                issue = str(detail.get("issue") or "").strip()
                if issue:
                    repeated_gaps.append(issue)
        if len(follow_up_questions) < 5 and question.question:
            source = question.source_section or question.point_title or "该经历"
            follow_up_questions.append(f"围绕{source}，请把刚才回答中缺失的指标、排查过程和复盘动作补充完整。")
    module_score_map = {
        module: round(sum(values) / len(values), 1)
        for module, values in module_scores.items()
        if values
    }
    total_score = float(interview.total_score or 0)
    return {
        "hire_signal": _hire_signal(total_score),
        "module_scores": module_score_map,
        "strongest_evidence": strongest_evidence[:5],
        "weakest_points": interview.weak_points or [],
        "repeated_gaps": _dedupe_text(repeated_gaps)[:5],
        "follow_up_training_plan": [
            "把每个项目整理成 60 秒版本和 3 分钟深挖版本。",
            "为 RAG、Agent、接口、Redis、数据库等技术点准备失败排查案例。",
            "为每段经历补齐指标、上线验收、联调问题和复盘改进。",
        ],
        "next_interview_questions": _dedupe_text(follow_up_questions)[:5],
    }


BAD_QUESTION_MARKERS = (
    "技术栈模块",
    "模块改成",
    "改成传统",
    "基础题型",
    "覆盖哪些题型",
    "覆盖哪些基础",
    "应该覆盖哪些",
    "应该覆盖",
    "题型设计",
    "出题模块",
    "题库模块",
)

SYSTEM_META_QUESTION_MARKERS = (
    "面试题",
    "出题",
    "题库",
    "题型",
    "生成问题",
    "有意义的问题",
    "题目质量",
    "模块题量",
    "覆盖策略",
    "候选人画像",
    "面试系统",
    "评分标准怎么设计",
    "如何设计面试",
    "如何设计题",
    "如何生成题",
    "为什么要设置 Agent 八股",
    "为什么要设置Agent八股",
    "技术八股都覆盖",
    "技术八股覆盖",
    "只围绕实习",
    "题目不重复",
    "避免无意义问题",
    "评估面试题质量",
)

QUESTION_META_CONTEXT_MARKERS = (
    "面试题",
    "出题",
    "题库",
    "题型",
    "覆盖",
    "覆盖项目",
    "覆盖实习",
    "项目、实习",
    "项目、 实习",
    "技术八股",
    "生成问题",
    "有意义",
    "题目质量",
    "评分标准",
    "模块题量",
    "覆盖策略",
    "题目不重复",
)

VALID_INTERVIEW_ANCHORS = (
    "接口",
    "联调",
    "异常",
    "排查",
    "性能",
    "优化",
    "数据一致性",
    "权限",
    "鉴权",
    "幂等",
    "任务",
    "重试",
    "上线",
    "验收",
    "复盘",
    "耗时",
    "准确率",
    "召回率",
    "TopK",
    "失败率",
    "P95",
    "日志",
    "监控",
    "测试用例",
    "工具调用",
    "降级",
    "记忆",
    "规划",
    "重排",
    "检索",
    "切片",
    "向量",
)

GENERIC_QUESTION_MARKERS = (
    "请介绍一下",
    "你做了什么",
    "遇到的最大困难",
    "最终取得了什么结果",
)


def _clean_question_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n-•·")
    cleaned = re.sub(r"^(问题|题目)\s*[:：]\s*", "", cleaned)
    if cleaned and cleaned[-1] not in {"？", "?", "。"}:
        cleaned = f"{cleaned}？"
    return cleaned


def _normalize_question_for_similarity(text: str) -> str:
    normalized = _clean_question_text(text).lower()
    normalized = re.sub(r"^结合[^，,]{1,80}[，,]", "", normalized)
    normalized = re.sub(r"^(请|你|如果|围绕|针对)", "", normalized)
    normalized = re.sub(r"[，。！？、：:；;,.!?/()\[\]（）【】\s]", "", normalized)
    for token in ("如何", "怎么", "为什么", "说明", "阐述", "一下", "具体", "请"):
        normalized = normalized.replace(token, "")
    return normalized


def _question_intent(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("排查", "定位", "失败", "重试", "异常", "恢复", "fallback", "超时")):
        return "troubleshooting"
    if any(term in lowered for term in ("取舍", "为什么", "比较", "选择", "边界", "方案")):
        return "tradeoff"
    if any(term in lowered for term in ("结果", "衡量", "指标", "验证", "topk", "提升", "评测")):
        return "metrics"
    if any(term in lowered for term in ("链路", "流程", "设计", "实现", "接口", "schema", "索引", "collection")):
        return "implementation"
    return "core"


def _question_similarity_key(text: str) -> str:
    terms = _detect_tech_terms(text)
    normalized = _normalize_question_for_similarity(text)
    if terms:
        return f"{'|'.join(terms[:3])}:{_question_intent(text)}"
    return normalized[:42]


def _contains_system_meta_question(cleaned: str) -> bool:
    compacted = re.sub(r"\s+", "", cleaned)
    if any(marker in cleaned or marker in compacted for marker in SYSTEM_META_QUESTION_MARKERS):
        return True
    if "如何保证" in cleaned and any(marker in cleaned or marker in compacted for marker in QUESTION_META_CONTEXT_MARKERS):
        return True
    if any(prefix in cleaned for prefix in ("为什么", "如何", "怎么")) and any(
        marker in cleaned or marker in compacted
        for marker in ("面试题", "出题", "题库", "题型", "覆盖", "生成问题", "题目质量", "评分标准", "模块题量")
    ):
        return True
    return False


def _question_has_valid_anchor(cleaned: str, batch: QuestionBatch | None = None) -> bool:
    if batch and batch.module in {"system_design", "behavioral"}:
        return True
    if _detect_tech_terms(cleaned):
        return True
    if any(anchor.lower() in cleaned.lower() for anchor in VALID_INTERVIEW_ANCHORS):
        return True
    if batch:
        subject_candidates = [
            batch.title.replace("项目：", "").replace("实习：", "").replace("Agent 八股：", "").strip(),
            batch.source_section.strip(),
            batch.point_id.strip(),
        ]
        for subject in subject_candidates:
            if len(subject) >= 2 and subject in cleaned:
                return True
    return False


def _is_bad_question(text: str, batch: QuestionBatch | None = None) -> bool:
    cleaned = _clean_question_text(text)
    if not cleaned:
        return True
    if len(re.sub(r"\s+", "", cleaned)) < 14:
        return True
    if _contains_system_meta_question(cleaned):
        return True
    if any(marker in cleaned for marker in BAD_QUESTION_MARKERS):
        return True
    if re.search(r"(应该|需要|如何).{0,12}(覆盖|包含).{0,12}(题型|基础题|问题)", cleaned):
        return True
    if any(marker in cleaned for marker in GENERIC_QUESTION_MARKERS) and not _detect_tech_terms(cleaned):
        return True
    if batch and batch.module != "agent_fundamentals" and "Agent 八股" in cleaned:
        return True
    if not _question_has_valid_anchor(cleaned, batch):
        return True
    return False


def _is_duplicate_question(text: str, seen_texts: list[str], seen_keys: set[str]) -> bool:
    key = _question_similarity_key(text)
    if key and key in seen_keys:
        return True
    normalized = _normalize_question_for_similarity(text)
    if not normalized:
        return True
    for seen in seen_texts:
        seen_normalized = _normalize_question_for_similarity(seen)
        if not seen_normalized:
            continue
        if normalized == seen_normalized:
            return True
        shorter, longer = sorted((normalized, seen_normalized), key=len)
        if len(shorter) >= 18 and shorter in longer:
            return True
        if SequenceMatcher(None, normalized, seen_normalized).ratio() >= 0.82:
            return True
    return False


def _safe_score(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, number))


def _normalize_score_dimensions(scores: Any) -> dict[str, float]:
    if not isinstance(scores, dict):
        return {}
    normalized: dict[str, float] = {}
    for key in SCORE_DIMENSION_KEYS:
        value = _safe_score(scores.get(key))
        if value is None:
            alias_values = [_safe_score(scores.get(alias)) for alias in LEGACY_SCORE_ALIASES.get(key, ())]
            alias_values = [item for item in alias_values if item is not None]
            value = round(sum(alias_values) / len(alias_values), 1) if alias_values else None
        if value is not None:
            normalized[key] = round(value, 1)
    return normalized


def _compact_text(value: Any, max_chars: int = 1600) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, list):
        return "；".join(_compact_text(item, 260) for item in value if item)[:max_chars]
    if isinstance(value, dict):
        fragments = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            fragments.append(f"{key}: {_compact_text(item, 360)}")
        return "；".join(fragments)[:max_chars]
    return str(value)[:max_chars]


def _normalize_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        records = [value]
    elif value:
        records = [{"description": str(value)}]
    else:
        records = []

    normalized = []
    for item in records:
        if isinstance(item, dict):
            normalized.append(item)
        elif item:
            normalized.append({"description": str(item)})
    return normalized


def _clean_label(value: Any, fallback: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip(" -:：|")
    return (label or fallback)[:90]


def _record_title(record: dict[str, Any], fallback: str, *, is_project: bool) -> str:
    if is_project:
        return _clean_label(
            record.get("name") or record.get("title") or record.get("project_name") or record.get("project"),
            fallback,
        )
    company = _clean_label(record.get("company") or record.get("name") or record.get("organization"), "")
    role = _clean_label(record.get("role") or record.get("position") or record.get("title"), "")
    if company and role:
        return _clean_label(f"{company} · {role}", fallback)
    return _clean_label(company or role or record.get("description"), fallback)


def _record_description(record: dict[str, Any]) -> str:
    fields = [
        record.get("description"),
        record.get("summary"),
        record.get("responsibilities"),
        record.get("highlights"),
        record.get("achievements"),
        record.get("tech_stack"),
        record.get("interview_points"),
    ]
    return "；".join(_compact_text(field, 700) for field in fields if field)[:1800]


def _looks_placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    placeholder_chars = sum(1 for char in text if char in {"?", "�"})
    return placeholder_chars >= max(3, len(text) // 2)


def _is_weak_record(record: dict[str, Any], *, is_project: bool) -> bool:
    title = _record_title(record, "", is_project=is_project)
    description = _record_description(record)
    return _looks_placeholder(title) or (not description and len(title) < 4)


def _resume_section_lines(resume_text: str, headings: tuple[str, ...]) -> list[str]:
    stop_headings = (
        "教育背景",
        "教育经历",
        "工作经历",
        "工作经验",
        "实习经历",
        "项目经历",
        "项目经验",
        "专业技能",
        "技能",
        "个人技能",
        "自我评价",
        "个人评价",
        "荣誉",
        "证书",
        "校园经历",
    )
    lines = [line.strip() for line in (resume_text or "").replace("\r\n", "\n").split("\n")]
    collecting = False
    result: list[str] = []
    for line in lines:
        clean_line = line.strip(" 　\t-•*")
        if not clean_line:
            continue
        if any(heading in clean_line for heading in headings):
            collecting = True
            continue
        if collecting and any(heading in clean_line for heading in stop_headings) and not any(
            heading in clean_line for heading in headings
        ):
            break
        if collecting:
            result.append(clean_line)
    return result


def _looks_record_heading(line: str) -> bool:
    if len(line) > 90:
        return False
    if re.match(r"^(负责|参与|通过|使用|实现|优化|完成|设计|搭建|维护|协助|对接|输出|沉淀)", line):
        return False
    return bool(re.search(r"(项目|系统|平台|公司|实习|工程师|负责人|\d{4}[./-]\d{1,2}|\d{4})", line))


def _records_from_raw_section(
    resume_text: str,
    headings: tuple[str, ...],
    *,
    fallback_prefix: str,
    is_project: bool,
) -> list[dict[str, Any]]:
    lines = _resume_section_lines(resume_text, headings)
    if not lines:
        return []

    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and _looks_record_heading(line):
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)

    records: list[dict[str, Any]] = []
    for index, group in enumerate(groups, 1):
        title = group[0] if group else f"{fallback_prefix} {index}"
        body = group[1:] if len(group) > 1 else group
        record = {
            "name" if is_project else "company": title,
            "description": "；".join(body)[:1400],
            "highlights": body[:5],
            "interview_points": [
                {
                    "id": f"raw-{fallback_prefix}-{index}",
                    "title": title,
                    "description": "；".join(body)[:600],
                }
            ],
        }
        if is_project:
            record["tech_stack"] = _detect_tech_terms(" ".join(group))
        records.append(record)
    return records


def _records_with_raw_fallback(
    parsed_records: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    *,
    is_project: bool,
) -> list[dict[str, Any]]:
    if not raw_records:
        return parsed_records
    if (
        not parsed_records
        or all(_is_weak_record(record, is_project=is_project) for record in parsed_records)
        or len(raw_records) >= len(parsed_records)
    ):
        return raw_records
    return parsed_records


def _detect_tech_terms(text: str) -> list[str]:
    lowered = (text or "").lower()
    found = []
    for canonical, aliases in TECH_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            found.append(canonical)
    return _dedupe_text(found)


def _extract_resume_skills(data: dict[str, Any], resume_text: str, jd_text: str | None) -> list[str]:
    candidates: list[str] = []
    raw_skills = data.get("skills") or []
    if isinstance(raw_skills, list):
        candidates.extend(str(skill) for skill in raw_skills)
    elif raw_skills:
        candidates.append(str(raw_skills))

    for project in _normalize_records(data.get("projects")):
        tech_stack = project.get("tech_stack") or project.get("skills") or []
        if isinstance(tech_stack, list):
            candidates.extend(str(skill) for skill in tech_stack)
        elif tech_stack:
            candidates.append(str(tech_stack))

    detected = _detect_tech_terms(" ".join(candidates) + " " + resume_text + " " + (jd_text or ""))
    return _dedupe_text([*candidates, *detected])[:24]


def _term_question(term: str, subject: str, module: str) -> str:
    if term == "混合检索/RRF":
        return f"{subject}里如果用了 BM25 和向量召回，你如何用 RRF 做排序融合？为什么不能直接把两路分数相加，怎么验证 TopK 质量提升？"
    if term == "RAG":
        return f"请拆解{subject}的 RAG 链路：文档清洗、切片、embedding、召回、重排、上下文拼接分别怎么做，哪一步最影响答案质量？"
    if term == "Qdrant":
        return f"{subject}接入 Qdrant 时，collection 的向量维度、payload、过滤条件和索引重建流程怎么设计？如果召回为空你会怎么排查？"
    if term == "BGE-M3":
        return "使用 BGE-M3 做 embedding 时，为什么要确认 1024 维向量与 Qdrant collection 一致？模型切换后如何灰度重建索引？"
    if term == "Agent":
        return f"{subject}里的 Agent 决策链路是什么？任务规划、工具选择、上下文记忆、失败兜底分别由哪些模块负责？"
    if term == "Tool Calling":
        return "如果 Agent 需要调用外部工具或 API，你怎么定义 tool schema、参数校验、权限边界和失败重试，防止工具误调用？"
    if term == "Prompt Injection":
        return f"遇到简历或 JD 中夹带 prompt injection 指令时，{subject}如何识别并隔离这类输入，避免模型泄露系统提示或越权调用工具？"
    if term == "FastAPI":
        return f"{subject}中的 FastAPI 接口如何拆分路由、鉴权、参数校验和异常返回？长任务接口为什么不能一直同步等待？"
    if term == "Redis":
        return f"如果{subject}用 Redis 做缓存或任务队列，你会如何设计 key、过期策略、幂等、失败重试和服务重启后的恢复？"
    if term in {"PostgreSQL", "MySQL", "SQL"}:
        return f"{subject}涉及数据库读写时，表结构、索引、事务边界和慢查询排查怎么做？请举一个你会重点优化的查询场景。"
    if term == "React":
        return f"{subject}的 React 前端如何组织状态、接口 loading/error、表单输入和结果对比展示，避免用户看到内部 JSON 字段？"
    if term in {"Vue", "Next.js", "TypeScript"}:
        return f"{subject}使用 {term} 时，页面路由、组件边界、类型约束、接口 loading/error 和异常提示怎么设计？如何验证用户不会看到内部调试字段？"
    if term == "API":
        return f"{subject}的核心 API 怎么设计请求/响应、鉴权、错误码和幂等语义？联调时如何定位前后端字段不一致的问题？"
    if term == "数据清洗":
        return f"{subject}的数据清洗链路怎么处理缺失值、重复数据、异常值和口径不一致？如何用 SQL/Pandas/Spark 校验清洗前后指标没有偏移？"
    if term == "可视化":
        return f"{subject}的报表或可视化看板如何定义指标口径、筛选维度、刷新频率和异常数据提示？如何验证分析结论可复现？"
    if term == "前端状态管理":
        return f"{subject}的前端状态管理如何拆分服务端数据、表单草稿、loading/error 和结果对比状态？如果接口失败或重复提交会怎么处理？"
    if term == "CI/CD":
        return f"{subject}的 CI/CD 流水线如何拆分构建、测试、镜像、部署、健康检查和回滚阶段？某一步失败时如何定位日志并恢复发布？"
    if term == "Docker":
        return f"{subject}的 Docker 镜像如何控制依赖层、环境变量、启动命令和健康检查？镜像构建成功但服务启动失败时怎么排查？"
    if term == "Kubernetes":
        return f"{subject}部署到 Kubernetes 时，Deployment、Service、配置、探针和滚动发布怎么设计？Pod 重启或流量异常时先看哪些指标？"
    if term == "部署运维":
        return f"{subject}的部署发布如何做环境隔离、健康检查、灰度/回滚和故障复盘？如果上线后接口 5xx 升高你会按什么顺序排查？"
    if term == "异步任务":
        return f"{subject}里的异步任务如何表达 queued、running、success、failed、retrying 等状态，并向前端持续返回进度？"
    if term == "可观测性":
        return f"{subject}如何记录 request_id、耗时、错误类型、LLM fallback 和最近错误，便于线上定位生成失败或质量下降？"
    return f"围绕{subject}中的 {term}，请说明你的具体实现、方案取舍、风险和验证方式。"


def _module_fallback_questions(batch: QuestionBatch) -> list[str]:
    subject = batch.title.replace("项目：", "").replace("实习：", "").replace("Agent 八股：", "") or "这段经历"
    source_text = f"{batch.title} {batch.description} {batch.context}"
    terms = _detect_tech_terms(source_text)
    primary_term = terms[0] if terms else "核心模块"
    questions: list[str] = []

    if batch.module == "system_design":
        questions.extend(
            [
                f"如果把{subject}扩展到多用户并发使用，你会如何拆分接口、数据表、异步任务和可观测性链路？",
                f"围绕{subject}，请画出从请求入口、权限校验、检索或计算、结果落库到前端展示的数据流，并说明关键失败点怎么兜底？",
                f"{subject}里哪些步骤适合同步处理，哪些应该放到队列或后台任务？请说明幂等、重试、超时和状态回写怎么设计。",
                f"如果{subject}的检索召回或模型调用质量下降，你会看哪些日志、指标和样本来定位问题，并怎么设计回滚方案？",
                f"{subject}在数据隔离、权限边界、成本控制和扩展性上有哪些取舍？如果业务量提升 10 倍，你会优先改哪几处？",
                f"请结合{subject}说明 API 契约、错误码、trace_id、监控告警和灰度发布怎么落地，避免线上问题无法复盘。",
            ]
        )
        return _dedupe_text(questions)[: batch.limit]

    if batch.module == "behavioral":
        questions.extend(
            [
                f"结合{subject}，请用 STAR 讲一次你推动需求或项目落地的经历：背景、你的动作、结果和复盘分别是什么？",
                f"{subject}中如果你和同学、同事或上下游对方案判断不一致，你会如何沟通、取舍并推动结论落地？",
                f"请结合{subject}说明一次你遇到压力或进度风险时的处理方式，你如何同步风险、调整优先级并复盘？",
                f"你为什么选择当前目标岗位？请结合{subject}里的经历说明你的动机、优势和需要补强的能力。",
                f"如果面试官质疑{subject}中你的个人贡献不清晰，你会如何用事实、动作和指标回答？",
                f"请复盘{subject}中一个做得不够好的点：当时为什么会这样、你学到了什么、下一次会如何避免？",
            ]
        )
        return _dedupe_text(questions)[: batch.limit]

    if batch.module == "agent_fundamentals":
        preferred_terms = [
            term for term in terms
            if term in {"Agent", "Tool Calling", "RAG", "混合检索/RRF", "Qdrant", "BGE-M3", "Prompt Injection", "可观测性"}
        ]
        if not preferred_terms:
            preferred_terms = ["Agent", "Tool Calling", "RAG", "Prompt Injection", "可观测性"]
        for term in preferred_terms:
            questions.append(_term_question(term, "Agent 应用", batch.module))
        questions.append("请比较单轮 LLM 调用、RAG 应用和 Agent 应用的边界：什么时候需要规划、工具调用和记忆，什么时候反而不应该上 Agent？")
        questions.append("如果 RAG/Agent 回答看似正确但引用了错误知识，你会如何设计离线评测集、人工复核、线上监控和回滚机制？")
        return _dedupe_text(questions)[: batch.limit]

    for term in terms[:5]:
        questions.append(_term_question(term, subject, batch.module))

    if batch.module == "project":
        questions.append(f"{subject}的业务目标、用户场景和个人交付边界是什么？请围绕 {primary_term} 的请求链路、数据链路或部署链路讲清楚。")
    elif batch.module == "internship":
        questions.append(f"{subject}中你实际负责了哪些 {primary_term} 相关模块或接口？请说明输入输出、依赖方、上线标准和验收结果。")
    else:
        questions.append(f"请围绕 {primary_term} 介绍{subject}的背景、目标、个人职责和最终交付。")

    questions.extend(
        [
            f"{subject}推进过程中遇到过哪些 {primary_term} 相关的联调、数据一致性、性能或权限问题？你如何定位根因并验证修复有效？",
            f"{subject}里围绕 {primary_term} 有哪些方案取舍？如果让你重做一次，你会从架构、成本、稳定性或用户体验上怎么优化？",
            f"{subject}最终结果如何用 {primary_term} 指标衡量？如果简历里没有量化数据，你在面试中会补充哪些可验证证据？",
        ]
    )
    return _dedupe_text(questions)[: batch.limit]


def _extract_bank_question(content: str) -> str:
    for line in (content or "").splitlines():
        text = line.strip()
        if text.startswith("题目："):
            return text.replace("题目：", "", 1).strip()
    match = re.search(r"题目[:：]\s*(.+)", content or "")
    return match.group(1).strip() if match else ""


def _compatible_bank_sections(module: str) -> set[str]:
    if module == "project":
        return {"project_deep_dive", "system_design", "troubleshooting"}
    if module == "internship":
        return {"internship_deep_dive", "system_design", "troubleshooting"}
    if module == "agent_fundamentals":
        return {"agent_fundamentals", "system_design", "troubleshooting"}
    if module == "system_design":
        return {"system_design", "troubleshooting", "project_deep_dive", "agent_fundamentals"}
    if module == "behavioral":
        return {"behavioral"}
    return {"project_deep_dive", "internship_deep_dive", "system_design", "troubleshooting", "agent_fundamentals"}


def _contextualize_bank_question(question: str, batch: QuestionBatch) -> str:
    question = question.strip()
    if not question:
        return ""
    subject = batch.title.replace("项目：", "").replace("实习：", "").replace("Agent 八股：", "") or "这段经历"
    if batch.module == "agent_fundamentals":
        return question
    if subject and subject not in question:
        return f"结合{subject}，{question}"
    return question


def _rag_question_suggestions(snippets: list[Any], batch: QuestionBatch, *, limit: int = 3) -> list[str]:
    source_text = f"{batch.title} {batch.description} {batch.context}".lower()
    compatible_sections = _compatible_bank_sections(batch.module)
    suggestions: list[str] = []
    for snippet in snippets:
        metadata = getattr(snippet, "metadata", {}) or {}
        section = str(metadata.get("section") or "")
        if section and section not in compatible_sections:
            continue
        skills = [str(item).lower() for item in metadata.get("skills") or []]
        keywords = [str(item).lower() for item in getattr(snippet, "keywords", []) or []]
        if skills or keywords:
            if not any(item and item in source_text for item in [*skills, *keywords]):
                continue
        question = _extract_bank_question(getattr(snippet, "content", ""))
        contextualized = _contextualize_bank_question(question, batch)
        if contextualized and not _is_bad_question(contextualized, batch):
            suggestions.append(_clean_question_text(contextualized))
    return _dedupe_text(suggestions)[:limit]


def _response_question_items(response: Any) -> list[dict[str, str]]:
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        items = response.get("questions", [])
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _merge_question_items(
    response_items: list[dict[str, str]],
    fallback_questions: list[str],
    limit: int,
    *,
    batch: QuestionBatch | None = None,
    seen_texts: list[str] | None = None,
    seen_keys: set[str] | None = None,
) -> list[dict[str, str]]:
    seen_texts = seen_texts if seen_texts is not None else []
    seen_keys = seen_keys if seen_keys is not None else set()
    response_texts = [
        item.get("question_text") or item.get("question") or ""
        for item in response_items
    ]
    concrete_terms = _detect_tech_terms(" ".join([*response_texts, *fallback_questions]))
    specific_response_texts = []
    for text in response_texts:
        text = _clean_question_text(text)
        if not text or _is_bad_question(text, batch):
            continue
        is_generic = any(marker in text for marker in GENERIC_QUESTION_MARKERS)
        has_term = any(term.lower() in text.lower() for term in concrete_terms)
        if not is_generic or has_term:
            specific_response_texts.append(text)

    selected: list[str] = []
    for question in [*fallback_questions, *specific_response_texts]:
        question = _clean_question_text(question)
        if _is_bad_question(question, batch):
            continue
        if _is_duplicate_question(question, [*seen_texts, *selected], seen_keys):
            continue
        selected.append(question)
        seen_texts.append(question)
        seen_keys.add(_question_similarity_key(question))
        if len(selected) >= limit:
            break

    return [{"question_id": f"q{idx}", "question_text": question} for idx, question in enumerate(selected, 1)]


def _infer_question_type(question_text: str, batch: QuestionBatch) -> str:
    if batch.module == "system_design":
        return "system_design"
    if batch.module == "behavioral":
        return "behavioral_star"
    if batch.module == "agent_fundamentals":
        return "agent_fundamentals"
    text = question_text.lower()
    if any(term in text for term in ("排查", "定位", "失败", "重试", "异常", "恢复", "fallback")):
        return "troubleshooting"
    if any(term in text for term in ("取舍", "为什么", "比较", "选择", "方案")):
        return "tradeoff"
    if any(term in text for term in ("结果", "衡量", "指标", "验证", "topk", "提升")):
        return "metrics_reflection"
    if _detect_tech_terms(question_text):
        return "technical_detail"
    if batch.module == "project":
        return "project_deep_dive"
    if batch.module == "internship":
        return "internship_deep_dive"
    return "resume_core"


def _build_question_batches(
    data: dict[str, Any],
    resume: Resume,
    jd_text: str | None,
    training_focus: str | None = None,
    template_config: dict[str, Any] | None = None,
) -> list[QuestionBatch]:
    resume_text = resume.original_text or data.get("summary") or compact_json(data, 3000)
    skills = _extract_resume_skills(data, resume_text, jd_text)
    skills_context = "技能列表：" + "、".join(skills[:18]) if skills else ""
    template_context = _template_prompt_context(template_config) if template_config else ""
    if template_context:
        skills_context = f"{skills_context}\n{template_context}" if skills_context else template_context
    batches: list[QuestionBatch] = []

    project_records = _records_with_raw_fallback(
        _normalize_records(data.get("projects")),
        _records_from_raw_section(resume_text, ("项目经历", "项目经验", "Projects"), fallback_prefix="项目", is_project=True),
        is_project=True,
    )
    for index, project in enumerate(project_records, 1):
        title = _record_title(project, f"项目 {index}", is_project=True)
        description = _record_description(project)
        context = f"{compact_json(project, 1800)}\n{skills_context}\n岗位JD：{(jd_text or '')[:1000]}"
        batches.append(
            QuestionBatch(
                module="project",
                point_id=f"project:{index}",
                title=f"项目：{title}",
                source_section=title,
                description=description or title,
                context=context,
                limit=5,
            )
        )

    experiences = _records_with_raw_fallback(
        _normalize_records(data.get("experience")),
        _records_from_raw_section(resume_text, ("实习经历", "工作经历", "工作经验", "Experience"), fallback_prefix="实习", is_project=False),
        is_project=False,
    )
    if experiences:
        titles = [_record_title(item, f"经历 {idx}", is_project=False) for idx, item in enumerate(experiences, 1)]
        description = "\n".join(f"{idx}. {title}：{_record_description(item)}" for idx, (title, item) in enumerate(zip(titles, experiences, strict=False), 1))
        internship_title = f"实习：{titles[0]}" if len(titles) == 1 else "实习：核心经历"
        batches.append(
            QuestionBatch(
                module="internship",
                point_id="internship:all",
                title=internship_title,
                source_section=internship_title.replace("实习：", ""),
                description=description[:1800],
                context=f"{compact_json(experiences, 2200)}\n{skills_context}\n岗位JD：{(jd_text or '')[:1000]}",
                limit=5,
            )
        )

    agent_terms = _detect_tech_terms(f"{resume_text} {compact_json(data, 2600)} {jd_text or ''}")
    should_add_agent_fundamentals = bool(
        {"Agent", "RAG", "Tool Calling", "Qdrant", "BGE-M3", "混合检索/RRF"}.intersection(agent_terms)
        or any(skill.lower() in {"python", "fastapi", "redis", "react"} for skill in skills)
        or training_focus
    )
    if should_add_agent_fundamentals:
        focus_note = f"\n{training_focus}" if training_focus else ""
        batches.append(
            QuestionBatch(
                module="agent_fundamentals",
                point_id="agent:fundamentals",
                title="Agent 八股：核心能力",
                source_section="核心能力",
                description=f"围绕 Agent、RAG、工具调用、安全、评测和工程化的基础追问。{focus_note}",
                context=f"{skills_context}\n简历摘要：{resume_text[:1400]}\n岗位JD：{(jd_text or '')[:1000]}{focus_note}",
                limit=5,
            )
        )

    template_modules = set((template_config or {}).get("module_question_limits") or {})
    core_subject = resume.title
    if project_records:
        core_subject = _record_title(project_records[0], resume.title, is_project=True)
    elif experiences:
        core_subject = _record_title(experiences[0], resume.title, is_project=False)

    if "system_design" in template_modules:
        batches.append(
            QuestionBatch(
                module="system_design",
                point_id="system:architecture",
                title=f"系统设计：{core_subject}",
                source_section="架构与工程化",
                description="围绕简历项目和 JD，追问架构、接口、数据流、队列、RAG 链路、可观测性、扩展性和稳定性。",
                context=f"{template_context}\n简历摘要：{resume_text[:1800]}\n{skills_context}\n岗位JD：{(jd_text or '')[:1200]}",
                limit=5,
            )
        )

    if "behavioral" in template_modules:
        batches.append(
            QuestionBatch(
                module="behavioral",
                point_id="behavioral:star",
                title=f"HR / 行为面：{core_subject}",
                source_section="STAR 表达",
                description="结合简历项目和 JD，追问动机、协作、冲突处理、压力管理、复盘能力和稳定性。",
                context=f"{template_context}\n简历摘要：{resume_text[:1800]}\n{skills_context}\n岗位JD：{(jd_text or '')[:1200]}",
                limit=5,
            )
        )

    if not batches:
        fallback_exp = {"name": resume.title, "description": resume_text[:600], "interview_points": []}
        point = _fallback_point(fallback_exp)
        batches.append(
            QuestionBatch(
                module="resume",
                point_id="resume:core",
                title=f"简历：{point['title']}",
                source_section=point["title"],
                description=point["description"],
                context=f"{resume_text[:1600]}\n岗位JD：{(jd_text or '')[:1000]}",
                limit=5,
            )
        )

    return _apply_template_to_batches(batches, template_config)




async def _get_resume(resume_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> Resume:
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.post("", response_model=InterviewResponse)
async def create_interview(
    req: InterviewCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resume = await _get_resume(req.resume_id, current_user.id, db)
    org = await resolve_request_organization(request, db, current_user)
    request_jd = (req.jd_text or "").strip()
    resume_jd = (resume.jd_text or "").strip()
    effective_jd_text = request_jd or resume_jd or None
    jd_source = "request" if request_jd else "resume_last_jd" if resume_jd else "none"
    template = get_interview_template(req.template_id)
    inferred_company, inferred_position = infer_target_from_jd(effective_jd_text)
    target_company = _safe_target_text(req.target_company, 160) or inferred_company
    target_position = _safe_target_text(req.target_position, 200) or inferred_position
    interview_organization_id = resume.organization_id or org.id
    company_profile = await find_matching_company_profile(
        db,
        organization_id=interview_organization_id,
        company=target_company,
        position=target_position,
    )
    profile_snapshot = company_profile_snapshot(company_profile)
    interview = Interview(
        user_id=current_user.id,
        organization_id=interview_organization_id,
        resume_id=resume.id,
        jd_text=effective_jd_text,
        interview_template_id=template["template_id"],
        interview_template_name=template["name"],
        template_config_snapshot=template_snapshot(template),
        target_company=target_company,
        target_position=target_position,
        company_profile_id=company_profile.id if company_profile else None,
        company_profile_snapshot=profile_snapshot,
    )
    db.add(interview)
    await db.flush()
    log_audit_event(
        db,
        event_type="interview.create",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={
            "resume_id": str(resume.id),
            "has_jd": bool(effective_jd_text),
            "jd_source": jd_source,
            "template_id": template["template_id"],
            "target_company": target_company,
            "target_position": target_position,
            "company_profile_id": str(company_profile.id) if company_profile else None,
            "profile_confidence": profile_snapshot.get("profile_confidence"),
            **tenant_metadata(org),
        },
    )
    record_usage(
        db,
        current_user.id,
        "interview_create",
        organization_id=interview.organization_id,
        metadata={
            "resume_id": str(resume.id),
            "has_jd": bool(effective_jd_text),
            "jd_source": jd_source,
            "template_id": template["template_id"],
            "company_profile_id": str(company_profile.id) if company_profile else None,
            "profile_confidence": profile_snapshot.get("profile_confidence"),
        },
    )
    await db.commit()
    await db.refresh(interview)
    return interview


@router.get("", response_model=list[InterviewResponse])
async def list_interviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.user_id == current_user.id).order_by(Interview.created_at.desc())
    )
    return result.scalars().all()


@router.get("/templates", response_model=list[InterviewTemplateResponse])
async def get_interview_templates(
    current_user: User = Depends(get_current_user),
):
    return list_interview_templates()


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    return interview


@router.delete("/{interview_id}")
async def delete_interview(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    log_audit_event(
        db,
        event_type="interview.delete",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"status": interview.status},
    )
    await db.delete(interview)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{interview_id}/generate-questions")
async def generate_questions(
    interview_id: uuid.UUID,
    request: Request,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    existing_result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    existing_questions = existing_result.scalars().all()
    if existing_questions:
        if not force:
            return {"count": len(existing_questions), "message": "题目已存在"}
        if any(question.user_answer for question in existing_questions):
            raise HTTPException(status_code=400, detail="已有作答记录，不能覆盖生成；请新建一次面试或删除未使用会话")
        for question in existing_questions:
            await db.delete(question)
        await db.flush()

    resume = await _get_resume(interview.resume_id, current_user.id, db)
    data = resume.optimized_data or resume.parsed_data or {}
    index_result = await ensure_resume_chunks(db, resume)
    if index_result.get("status") != "already_indexed":
        await db.flush()

    llm = get_llm_client(settings)
    questions = []
    llm_calls = []
    template_config = _interview_template_config(interview)
    if template_config.get("use_training_profile"):
        focus_context, focus_items = await build_training_focus_context(
            db,
            user_id=current_user.id,
            organization_id=interview.organization_id,
        )
    else:
        focus_context, focus_items = "", []
    profile_snapshot = interview.company_profile_snapshot if isinstance(interview.company_profile_snapshot, dict) else {}
    profile_context = (
        company_profile_prompt_context(profile_snapshot, str(template_config.get("template_id") or "comprehensive"))
        if template_config.get("use_company_profile")
        else ""
    )
    external_focus = "\n\n".join(item for item in (focus_context, profile_context) if item)
    generation_template, company_module_bias = _template_with_company_profile_bias(template_config, profile_snapshot)
    batches = _build_question_batches(data, resume, interview.jd_text, external_focus, generation_template)
    seen_question_texts: list[str] = []
    seen_question_keys: set[str] = set()
    generation_risk_types: set[str] = set()
    generation_filtered_count = 0

    for batch in batches:
        resume_snippets = await retrieve_resume_evidence(
            db,
            user_id=current_user.id,
            resume_id=resume.id,
            query=f"{batch.title} {batch.description} {batch.context}",
            sections=RESUME_EVIDENCE_SECTIONS.get(batch.module),
            limit=5,
        )
        question_evidence = _resume_evidence_dicts(resume_snippets, batch)
        rag_snippets = await retrieve_knowledge(
            db,
            f"{batch.title} {batch.description} {batch.context}",
            categories=["interview_rubric", "job_knowledge", "agent_interview_questions"],
            limit=5,
        )
        rag_context = build_rag_context(rag_snippets)
        generation_result = await request_generated_questions(
            llm,
            feature="question_generation",
            module=batch.module,
            point_title=batch.title,
            point_description=batch.description,
            template_context=_template_prompt_context(template_config),
            resume_context=batch.context,
            jd_context=interview.jd_text,
            training_profile_context=focus_context,
            company_profile_context=profile_context,
            evidence_context=_evidence_context(question_evidence),
            rag_context=rag_context,
        )
        generation_risk_types.update(generation_result.safety_metadata.get("risk_types") or [])
        generation_filtered_count += int(generation_result.safety_metadata.get("filtered_count") or 0)
        response = generation_result.response
        llm_calls.append(generation_result.usage_metadata["llm"])

        items = _merge_question_items(
            _response_question_items(response),
            _dedupe_text([
                *_rag_question_suggestions(rag_snippets, batch),
                *_module_fallback_questions(batch),
            ]),
            batch.limit,
            batch=batch,
            seen_texts=seen_question_texts,
            seen_keys=seen_question_keys,
        )
        for item in items[: batch.limit]:
            question_text = _clean_question_text(item.get("question_text") or item.get("question", ""))
            if not question_text:
                continue
            quality = _question_quality(question_text, batch, question_evidence)
            company_trace = _company_generation_trace(profile_snapshot)
            if company_trace:
                quality = {**quality, "company_profile": company_trace}
            if generation_result.safety_metadata.get("risk_types"):
                quality = {**quality, "context_safety": generation_result.safety_metadata}
            questions.append(
                InterviewQuestion(
                    interview_id=interview.id,
                    resume_point_id=batch.point_id,
                    point_title=batch.title,
                    module=batch.module,
                    source_section=batch.source_section,
                    question_type=_infer_question_type(question_text, batch),
                    sequence=len(questions) + 1,
                    question=question_text,
                    evidence=question_evidence,
                    question_quality=quality,
                )
            )

    db.add_all(questions)
    log_audit_event(
        db,
        event_type="interview.generate_questions",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={
            "question_count": len(questions),
            "template_id": template_config.get("template_id"),
            "company_profile_id": profile_snapshot.get("profile_id"),
            "profile_confidence": profile_snapshot.get("profile_confidence"),
            "company_module_bias": company_module_bias,
            "context_safety": {
                "risk_types": sorted(generation_risk_types),
                "filtered_count": generation_filtered_count,
            },
        },
    )
    record_usage(
        db,
        current_user.id,
        "question_generation",
        organization_id=interview.organization_id,
        metadata={
            "interview_id": str(interview.id),
            "question_count": len(questions),
            "template_id": template_config.get("template_id"),
            "template_name": template_config.get("name"),
            "resume_index": index_result,
            "training_focus": focus_items,
            "company_profile": _company_generation_trace(profile_snapshot),
            "company_module_bias": company_module_bias,
            "context_safety": {
                "risk_types": sorted(generation_risk_types),
                "filtered_count": generation_filtered_count,
            },
            "llm_calls": llm_calls,
        },
    )
    await db.commit()
    return {
        "count": len(questions),
        "message": "棰樼洰鐢熸垚鎴愬姛",
        "template": {"template_id": template_config.get("template_id"), "name": template_config.get("name")},
        "training_focus": focus_items,
        "company_profile": _company_generation_trace(profile_snapshot),
        "company_module_bias": company_module_bias,
    }


@router.get("/{interview_id}/questions", response_model=list[InterviewQuestionResponse])
async def list_questions(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion)
        .where(InterviewQuestion.interview_id == interview.id)
        .order_by(InterviewQuestion.created_at, InterviewQuestion.sequence)
    )
    return result.scalars().all()


@router.post("/{interview_id}/questions/{question_id}/answer", response_model=AnswerSubmitResponse)
async def submit_answer(
    interview_id: uuid.UUID,
    question_id: uuid.UUID,
    req: AnswerSubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion).where(
            InterviewQuestion.id == question_id,
            InterviewQuestion.interview_id == interview.id,
        )
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    resume = await _get_resume(interview.resume_id, current_user.id, db)
    resume_context = str(resume.optimized_data or resume.parsed_data)
    score_evidence = question.evidence or []
    if not score_evidence:
        resume_snippets = await retrieve_resume_evidence(
            db,
            user_id=current_user.id,
            resume_id=resume.id,
            query=f"{question.question} {req.answer}",
            sections=RESUME_EVIDENCE_SECTIONS.get(question.module or "resume"),
            limit=3,
        )
        fallback_batch = QuestionBatch(
            module=question.module or "resume",
            point_id=question.resume_point_id or "resume:core",
            title=question.point_title or question.source_section or "简历要点",
            source_section=question.source_section or "",
            description=question.question,
            context=resume_context[:1200],
            limit=3,
        )
        score_evidence = _resume_evidence_dicts(resume_snippets, fallback_batch)

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{question.question} {req.answer} {resume_context[:1500]}",
        categories=["interview_rubric", "job_knowledge", "reporting"],
        limit=5,
    )
    rag_context = build_rag_context(rag_snippets)
    template_config = _interview_template_config(interview)
    scoring_result = await request_answer_score(
        llm,
        question=question.question,
        answer=req.answer,
        template_context=_template_score_context(template_config),
        resume_context=resume_context[:4000],
        jd_context=interview.jd_text,
        company_profile_context=interview.company_profile_snapshot or {},
        evidence_context=_evidence_context(score_evidence),
        rag_context=rag_context,
    )
    score_risk_types = scoring_result.safety_metadata["risk_types"]
    score_filtered_count = scoring_result.safety_metadata["filtered_count"]
    response = scoring_result.response
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="评分结果不可用，请稍后重试")
    llm_metadata = scoring_result.usage_metadata

    scores = _normalize_score_dimensions(response.get("scores", {}))
    total = response.get("total_score", 0)
    if not total and scores:
        total = sum(scores.values()) / len(scores)

    question.user_answer = req.answer
    question.scores = scores
    if not question.evidence and score_evidence:
        question.evidence = score_evidence
    question.score_details = _normalize_score_details(response, scores, req.answer, question)
    question.total_score = float(total)
    question.feedback = response.get("feedback", "")
    question.refined_answer = response.get("refined_answer", "")
    question.answered_at = utc_now()
    dimension_keys = detect_training_dimensions(
        question.question,
        req.answer,
        question.module,
        question.source_section,
        compact_json(question.evidence or [], 800),
    )
    total_float = float(total or 0)
    if total_float < 65:
        await apply_training_signal(
            db,
            user_id=current_user.id,
            organization_id=interview.organization_id,
            dimension_keys=dimension_keys,
            signal="low_score",
            source="interview_answer",
        )
    elif total_float >= 85 and question.module == "agent_fundamentals":
        await apply_training_signal(
            db,
            user_id=current_user.id,
            organization_id=interview.organization_id,
            dimension_keys=dimension_keys,
            signal="known",
            source="interview_answer",
        )
    log_audit_event(
        db,
        event_type="interview.answer",
        resource_type="interview_question",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(question.id),
        request=request,
        metadata={
            "interview_id": str(interview.id),
            "answer_length": len(req.answer),
            "total_score": total,
            "context_safety": {"risk_types": score_risk_types, "filtered_count": score_filtered_count},
        },
    )
    record_usage(
        db,
        current_user.id,
        "answer_score",
        organization_id=interview.organization_id,
        metadata={
            "interview_id": str(interview.id),
            "question_id": str(question.id),
            "context_safety": {"risk_types": score_risk_types, "filtered_count": score_filtered_count},
            **llm_metadata,
        },
    )

    await db.commit()
    await db.refresh(question)

    return AnswerSubmitResponse.model_validate(question)


@router.post("/{interview_id}/regenerate-question")
async def regenerate_question(
    interview_id: uuid.UUID,
    request: Request,
    question_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    question_query = select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    if question_id:
        question_query = question_query.where(InterviewQuestion.id == question_id)
    else:
        question_query = question_query.where(InterviewQuestion.user_answer.is_(None)).order_by(InterviewQuestion.created_at)

    result = await db.execute(question_query)
    question = result.scalars().first()
    if not question:
        raise HTTPException(status_code=400, detail="没有可重新生成的问题")
    if question.user_answer:
        raise HTTPException(status_code=400, detail="已作答的问题不能换题，请选择未作答题目")

    resume = await _get_resume(interview.resume_id, current_user.id, db)
    resume_data = resume.optimized_data or resume.parsed_data or {}
    legacy_module = (question.resume_point_id or "resume").split(":", 1)[0]
    module = question.module or ("agent_fundamentals" if legacy_module == "agent" else legacy_module)
    source_section = (
        question.source_section
        or (question.point_title or "简历要点")
        .replace("项目：", "")
        .replace("实习：", "")
        .replace("Agent 八股：", "")
        .replace("简历：", "")
    )
    batch = QuestionBatch(
        module="agent_fundamentals" if module == "agent" else module,
        point_id=question.resume_point_id or "resume:core",
        title=question.point_title or "简历要点",
        source_section=source_section,
        description=question.question,
        context=f"{compact_json(resume_data, 2200)}\n原问题：{question.question}\n岗位JD：{(interview.jd_text or '')[:1000]}",
        limit=5,
    )
    template_config = _interview_template_config(interview)
    profile_snapshot = interview.company_profile_snapshot if isinstance(interview.company_profile_snapshot, dict) else {}
    profile_context = (
        company_profile_prompt_context(profile_snapshot, str(template_config.get("template_id") or "comprehensive"))
        if template_config.get("use_company_profile")
        else ""
    )
    if profile_context:
        batch.context = f"{batch.context}\n\n{profile_context}"

    llm = get_llm_client(settings)
    index_result = await ensure_resume_chunks(db, resume)
    if index_result.get("status") != "already_indexed":
        await db.flush()
    resume_snippets = await retrieve_resume_evidence(
        db,
        user_id=current_user.id,
        resume_id=resume.id,
        query=f"{batch.title} {batch.description} {batch.context}",
        sections=RESUME_EVIDENCE_SECTIONS.get(batch.module),
        limit=5,
    )
    question_evidence = _resume_evidence_dicts(resume_snippets, batch)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{batch.title} {batch.description} {batch.context}",
        categories=["interview_rubric", "job_knowledge", "agent_interview_questions"],
        limit=5,
    )
    regeneration_result = await request_generated_questions(
        llm,
        feature="question_regeneration",
        module=batch.module,
        point_title=batch.title,
        point_description=batch.description,
        template_context=_template_prompt_context(template_config),
        resume_context=batch.context,
        jd_context=interview.jd_text,
        company_profile_context=profile_context,
        evidence_context=_evidence_context(question_evidence),
        rag_context=build_rag_context(rag_snippets),
    )
    regenerate_risk_types = regeneration_result.safety_metadata["risk_types"]
    regenerate_filtered_count = regeneration_result.safety_metadata["filtered_count"]
    response = regeneration_result.response
    llm_metadata = regeneration_result.usage_metadata

    existing_result = await db.execute(
        select(InterviewQuestion).where(
            InterviewQuestion.interview_id == interview.id,
            InterviewQuestion.id != question.id,
        )
    )
    seen_question_texts = [item.question for item in existing_result.scalars().all() if item.question]
    seen_question_keys = {_question_similarity_key(item) for item in seen_question_texts}
    seen_question_texts.append(question.question)
    seen_question_keys.add(_question_similarity_key(question.question))

    items = _merge_question_items(
        _response_question_items(response),
        _dedupe_text([
            *_rag_question_suggestions(rag_snippets, batch),
            *_module_fallback_questions(batch),
        ]),
        batch.limit,
        batch=batch,
        seen_texts=seen_question_texts,
        seen_keys=seen_question_keys,
    )

    if items:
        replacement = next(
            (
                _clean_question_text(item.get("question_text") or item.get("question", ""))
                for item in items
                if _clean_question_text(item.get("question_text") or item.get("question", "")) != question.question
            ),
            _clean_question_text(items[0].get("question_text") or items[0].get("question", question.question)),
        )
        question.question = replacement or question.question
        question.module = batch.module
        question.source_section = batch.source_section
        question.question_type = _infer_question_type(question.question, batch)
        question.evidence = question_evidence
        quality = _question_quality(question.question, batch, question_evidence)
        company_trace = _company_generation_trace(profile_snapshot)
        question.question_quality = {**quality, "company_profile": company_trace} if company_trace else quality
        log_audit_event(
            db,
            event_type="interview.regenerate_question",
            resource_type="interview_question",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=interview.organization_id,
            resource_id=str(question.id),
            request=request,
            metadata={
                "interview_id": str(interview.id),
                "company_profile_id": profile_snapshot.get("profile_id"),
                "context_safety": {
                    "risk_types": regenerate_risk_types,
                    "filtered_count": regenerate_filtered_count,
                },
            },
        )
        record_usage(
            db,
            current_user.id,
            "question_generation",
            organization_id=interview.organization_id,
            metadata={
                "interview_id": str(interview.id),
                "question_id": str(question.id),
                "mode": "regenerate",
                "company_profile": _company_generation_trace(profile_snapshot),
                "context_safety": {
                    "risk_types": regenerate_risk_types,
                    "filtered_count": regenerate_filtered_count,
                },
                **llm_metadata,
            },
        )
        await db.commit()

    return InterviewQuestionResponse.model_validate(question)


@router.post("/{interview_id}/finish", response_model=InterviewReportResponse)
async def finish_interview(
    interview_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")

    result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    questions = result.scalars().all()

    answered = [q for q in questions if q.user_answer]
    if len(answered) < 3:
        raise HTTPException(status_code=400, detail="至少完成 3 道题才能生成报告")

    # 准备总结输入
    qa_records = []
    for q in answered:
        normalized_scores = _normalize_score_dimensions(q.scores)
        qa_records.append({
            "question": q.question,
            "answer": q.user_answer,
            "scores": normalized_scores,
            "score_details": q.score_details or {},
            "evidence": q.evidence or [],
            "module": q.module,
            "source_section": q.source_section,
            "feedback": q.feedback,
        })

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{compact_json(qa_records, 4000)} {compact_json(interview.jd_text or '', 1000)}",
        categories=["interview_rubric", "reporting", "job_knowledge"],
        limit=6,
    )
    template_config = _interview_template_config(interview)
    report_result = await request_interview_report(
        llm,
        template_context=_template_score_context(template_config),
        jd_context=interview.jd_text,
        company_profile_context=interview.company_profile_snapshot or {},
        answers_context=qa_records,
        rag_context=build_rag_context(rag_snippets),
    )
    response = report_result.response
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="面试报告结果不可用，请稍后重试")
    llm_metadata = report_result.usage_metadata

    # 计算平均分
    total_scores = {key: [] for key in SCORE_DIMENSION_KEYS}
    for q in answered:
        normalized_scores = _normalize_score_dimensions(q.scores)
        for key in total_scores:
            if key in normalized_scores:
                total_scores[key].append(normalized_scores[key])

    dimension_scores = {k: round(sum(v) / len(v), 1) if v else 0 for k, v in total_scores.items()}
    avg_total = sum(dimension_scores.values()) / len(dimension_scores) if dimension_scores else 0
    response_dimension_scores = _normalize_score_dimensions(response.get("dimension_scores", {}))
    if len(response_dimension_scores) < len(SCORE_DIMENSION_KEYS):
        response_dimension_scores = {**dimension_scores, **response_dimension_scores}

    interview.status = "completed"
    interview.total_score = float(response.get("total_score") or avg_total * 10)
    interview.dimension_scores = response_dimension_scores or dimension_scores
    interview.summary = response.get("summary", "")
    interview.weak_points = response.get("weak_points", [])
    interview.suggestions = response.get("suggestions", [])
    local_report_details = _build_report_details(interview, questions)
    template_report_details = _template_report_details(interview, questions)
    response_report_details = response.get("report_details") if isinstance(response.get("report_details"), dict) else {}
    interview.report_details = {**local_report_details, **response_report_details, **template_report_details}
    log_audit_event(
        db,
        event_type="interview.finish",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={
            "answered_count": len(answered),
            "total_score": interview.total_score,
            "template_id": template_config.get("template_id"),
            "context_safety": report_result.safety_metadata,
        },
    )
    record_usage(
        db,
        current_user.id,
        "interview_report",
        organization_id=interview.organization_id,
        metadata={
            "interview_id": str(interview.id),
            "answered_count": len(answered),
            "template_id": template_config.get("template_id"),
            "context_safety": report_result.safety_metadata,
            **llm_metadata,
        },
    )

    await db.commit()
    await db.refresh(interview)

    return InterviewReportResponse(
        id=interview.id,
        interview_template_id=interview.interview_template_id or DEFAULT_INTERVIEW_TEMPLATE_ID,
        interview_template_name=interview.interview_template_name or "综合面",
        template_config_snapshot=interview.template_config_snapshot or _interview_template_config(interview),
        target_company=interview.target_company,
        target_position=interview.target_position,
        company_profile_id=interview.company_profile_id,
        company_profile_snapshot=interview.company_profile_snapshot or {},
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
        report_details=interview.report_details,
        questions=[InterviewQuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{interview_id}/report", response_model=InterviewReportResponse)
async def get_report(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="面试会话不存在")
    if interview.status != "completed":
        raise HTTPException(status_code=400, detail="面试尚未结束，请先完成面试")

    result = await db.execute(
        select(InterviewQuestion).where(InterviewQuestion.interview_id == interview.id)
    )
    questions = result.scalars().all()

    return InterviewReportResponse(
        id=interview.id,
        interview_template_id=interview.interview_template_id or DEFAULT_INTERVIEW_TEMPLATE_ID,
        interview_template_name=interview.interview_template_name or "综合面",
        template_config_snapshot=interview.template_config_snapshot or _interview_template_config(interview),
        target_company=interview.target_company,
        target_position=interview.target_position,
        company_profile_id=interview.company_profile_id,
        company_profile_snapshot=interview.company_profile_snapshot or {},
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
        report_details=interview.report_details,
        questions=[InterviewQuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{interview_id}/report/export")
async def export_report(
    interview_id: uuid.UUID,
    request: Request,
    format: str = "md",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = await get_report(interview_id, db, current_user)
    interview = await db.scalar(select(Interview).where(Interview.id == interview_id, Interview.user_id == current_user.id))
    content = interview_report_to_markdown(report)
    normalized_format = format.lower().strip()
    if normalized_format not in {"md", "docx", "pdf"}:
        raise HTTPException(status_code=400, detail="仅支持 md、docx、pdf 导出")
    linked_job = await db.scalar(
        select(JobApplication).where(JobApplication.interview_id == interview_id, JobApplication.user_id == current_user.id)
    )
    suffix = f".{normalized_format}"
    if linked_job:
        filename_base = f"{linked_job.company}_{linked_job.title}_面试报告" if linked_job.company else f"{linked_job.title}_面试报告"
    else:
        filename_base = f"面试报告_{interview_id}"
    filename = safe_filename(filename_base, suffix)
    log_audit_event(
        db,
        event_type="interview.report_export",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id if interview else None,
        resource_id=str(interview_id),
        request=request,
        metadata={"filename": filename, "format": normalized_format},
    )
    record_usage(
        db,
        current_user.id,
        "report_export",
        organization_id=interview.organization_id if interview else None,
        metadata={"interview_id": str(interview_id)},
    )
    await db.commit()
    if normalized_format == "md":
        return {"filename": filename, "content": content}
    if normalized_format == "docx":
        return Response(
            content=interview_report_to_docx_bytes(report),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": content_disposition(filename)},
        )
    return Response(
        content=text_to_pdf_bytes(content, title="面试总结报告"),
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(filename)},
    )
