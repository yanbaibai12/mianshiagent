import time
import re
import uuid
from dataclasses import dataclass
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Resume, Interview, InterviewQuestion, JobApplication
from app.schemas import (
    InterviewCreateRequest,
    InterviewResponse,
    InterviewQuestionResponse,
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    InterviewReportResponse,
)
from app.services.auth_service import get_current_user
from app.services.audit import log_audit_event
from app.services.business import ensure_feature_available, record_usage
from app.services.document_export import content_disposition, interview_report_to_docx_bytes, interview_report_to_markdown, safe_filename, text_to_pdf_bytes
from app.services.knowledge_base import build_rag_context, compact_json, retrieve_knowledge
from app.services.llm_client import get_llm_client
from app.services.tenancy import resolve_request_organization, tenant_metadata
from app.config import get_settings
from app.prompts import GENERATE_QUESTIONS_PROMPT, SCORE_ANSWER_PROMPT, SUMMARIZE_INTERVIEW_PROMPT
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
    ("API", ("api", "接口", "鉴权", "限流")),
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
        return f"使用 BGE-M3 做 embedding 时，为什么要确认 1024 维向量与 Qdrant collection 一致？模型切换后如何灰度重建索引？"
    if term == "Agent":
        return f"{subject}里的 Agent 决策链路是什么？任务规划、工具选择、上下文记忆、失败兜底分别由哪些模块负责？"
    if term == "Tool Calling":
        return f"如果 Agent 需要调用外部工具或 API，你怎么定义 tool schema、参数校验、权限边界和失败重试，防止工具误调用？"
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
    if term == "API":
        return f"{subject}的核心 API 怎么设计请求/响应、鉴权、错误码和幂等语义？联调时如何定位前后端字段不一致的问题？"
    if term == "异步任务":
        return f"{subject}里的异步任务如何表达 queued、running、success、failed、retrying 等状态，并向前端持续返回进度？"
    if term == "可观测性":
        return f"{subject}如何记录 request_id、耗时、错误类型、LLM fallback 和最近错误，便于线上定位生成失败或质量下降？"
    return f"围绕{subject}中的 {term}，请说明你的具体实现、方案取舍、风险和验证方式。"


def _module_fallback_questions(batch: QuestionBatch) -> list[str]:
    subject = batch.title.replace("项目：", "").replace("实习：", "").replace("Agent 八股：", "") or "这段经历"
    source_text = f"{batch.title} {batch.description} {batch.context}"
    terms = _detect_tech_terms(source_text)
    questions: list[str] = []

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
        questions.append("如果模型回答看似正确但引用了错误知识，你会如何设计评测集、人工复核和线上回滚机制？")
        return _dedupe_text(questions)[: batch.limit]

    for term in terms[:5]:
        questions.append(_term_question(term, subject, batch.module))

    if batch.module == "project":
        questions.append(f"{subject}的业务目标、用户场景和个人交付边界是什么？请按请求链路或数据链路讲清楚。")
    elif batch.module == "internship":
        questions.append(f"{subject}中你实际负责了哪些模块或接口？请说明输入输出、依赖方、上线标准和验收结果。")
    else:
        questions.append(f"请介绍{subject}的背景、目标、个人职责和最终交付。")

    questions.extend(
        [
            f"{subject}推进过程中遇到过哪些联调、数据一致性、性能或权限问题？你如何定位根因并验证修复有效？",
            f"{subject}里有哪些方案取舍？如果让你重做一次，你会从架构、成本、稳定性或用户体验上怎么优化？",
            f"{subject}最终结果如何衡量？如果简历里没有量化数据，你在面试中会补充哪些可验证证据？",
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
        if contextualized:
            suggestions.append(contextualized)
    return _dedupe_text(suggestions)[:limit]


def _response_question_items(response: Any) -> list[dict[str, str]]:
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        items = response.get("questions", [])
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _merge_question_items(response_items: list[dict[str, str]], fallback_questions: list[str], limit: int) -> list[dict[str, str]]:
    response_texts = [
        item.get("question_text") or item.get("question") or ""
        for item in response_items
    ]
    generic_markers = ("请介绍一下", "具体做了哪些关键动作", "为什么选择这个方案", "遇到的最大困难", "最终取得了什么结果")
    concrete_terms = _detect_tech_terms(" ".join([*response_texts, *fallback_questions]))
    specific_response_texts = []
    for text in response_texts:
        if not text:
            continue
        is_generic = any(marker in text for marker in generic_markers)
        has_term = any(term.lower() in text.lower() for term in concrete_terms)
        if not is_generic or has_term:
            specific_response_texts.append(text)

    merged = _dedupe_text([*fallback_questions, *specific_response_texts])
    return [
        {"question_id": f"q{idx}", "question_text": question}
        for idx, question in enumerate(merged[:limit], 1)
    ]


def _infer_question_type(question_text: str, batch: QuestionBatch) -> str:
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


def _build_question_batches(data: dict[str, Any], resume: Resume, jd_text: str | None) -> list[QuestionBatch]:
    resume_text = resume.original_text or data.get("summary") or compact_json(data, 3000)
    skills = _extract_resume_skills(data, resume_text, jd_text)
    skills_context = "技能列表：" + "、".join(skills[:18]) if skills else ""
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
        description = "\n".join(f"{idx}. {title}：{_record_description(item)}" for idx, (title, item) in enumerate(zip(titles, experiences), 1))
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
    )
    if should_add_agent_fundamentals:
        batches.append(
            QuestionBatch(
                module="agent_fundamentals",
                point_id="agent:fundamentals",
                title="Agent 八股：核心能力",
                source_section="核心能力",
                description="围绕 Agent、RAG、工具调用、安全、评测和工程化的基础追问。",
                context=f"{skills_context}\n简历摘要：{resume_text[:1400]}\n岗位JD：{(jd_text or '')[:1000]}",
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

    return batches




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
    await ensure_feature_available("interview_create", db, current_user.id, settings)
    interview = Interview(
        user_id=current_user.id,
        organization_id=resume.organization_id or org.id,
        resume_id=resume.id,
        jd_text=req.jd_text,
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
        metadata={"resume_id": str(resume.id), "has_jd": bool(req.jd_text), **tenant_metadata(org)},
    )
    record_usage(db, current_user.id, "interview_create", organization_id=interview.organization_id, metadata={"resume_id": str(resume.id)})
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

    llm = get_llm_client(settings)
    questions = []
    llm_calls = []
    batches = _build_question_batches(data, resume, interview.jd_text)

    for batch in batches:
        rag_snippets = await retrieve_knowledge(
            db,
            f"{batch.title} {batch.description} {batch.context}",
            categories=["interview_rubric", "job_knowledge", "agent_interview_questions"],
            limit=5,
        )
        rag_context = build_rag_context(rag_snippets)
        prompt = GENERATE_QUESTIONS_PROMPT.format(
            point_title=batch.title,
            point_description=batch.description,
            experience_context=f"模块：{batch.module}\n{batch.context}\n\n{rag_context}",
        )
        messages = [{"role": "user", "content": prompt}]
        started_at = time.monotonic()
        response = await llm.chat_completion_json(messages)
        llm_calls.append(
            llm.build_usage_metadata(
                messages,
                response,
                feature="question_generation",
                started_at=started_at,
            )["llm"]
        )

        items = _merge_question_items(
            _response_question_items(response),
            _dedupe_text([
                *_rag_question_suggestions(rag_snippets, batch),
                *_module_fallback_questions(batch),
            ]),
            batch.limit,
        )
        for item in items[: batch.limit]:
            question_text = item.get("question_text") or item.get("question", "")
            if not question_text:
                continue
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
        metadata={"question_count": len(questions)},
    )
    record_usage(
        db,
        current_user.id,
        "question_generation",
        organization_id=interview.organization_id,
        metadata={
            "interview_id": str(interview.id),
            "question_count": len(questions),
            "llm_calls": llm_calls,
        },
    )
    await db.commit()
    return {"count": len(questions), "message": "题目生成成功"}


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

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{question.question} {req.answer} {resume_context[:1500]}",
        categories=["interview_rubric", "job_knowledge", "reporting"],
        limit=5,
    )
    rag_context = build_rag_context(rag_snippets)
    prompt = SCORE_ANSWER_PROMPT.format(
        question=question.question,
        answer=req.answer,
        resume_context=f"{resume_context[:4000]}\n\n{rag_context}",
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="评分结果不可用，请稍后重试")
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="answer_score",
        started_at=started_at,
    )

    scores = _normalize_score_dimensions(response.get("scores", {}))
    total = response.get("total_score", 0)
    if not total and scores:
        total = sum(scores.values()) / len(scores)

    question.user_answer = req.answer
    question.scores = scores
    question.total_score = float(total)
    question.feedback = response.get("feedback", "")
    question.refined_answer = response.get("refined_answer", "")
    question.answered_at = utc_now()
    log_audit_event(
        db,
        event_type="interview.answer",
        resource_type="interview_question",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(question.id),
        request=request,
        metadata={"interview_id": str(interview.id), "answer_length": len(req.answer), "total_score": total},
    )
    record_usage(
        db,
        current_user.id,
        "answer_score",
        organization_id=interview.organization_id,
        metadata={"interview_id": str(interview.id), "question_id": str(question.id), **llm_metadata},
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

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{batch.title} {batch.description} {batch.context}",
        categories=["interview_rubric", "job_knowledge", "agent_interview_questions"],
        limit=5,
    )
    prompt = GENERATE_QUESTIONS_PROMPT.format(
        point_title=batch.title,
        point_description=batch.description,
        experience_context=f"模块：{batch.module}\n{batch.context}\n\n{build_rag_context(rag_snippets)}",
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="question_regeneration",
        started_at=started_at,
    )

    items = _merge_question_items(
        _response_question_items(response),
        _dedupe_text([
            *_rag_question_suggestions(rag_snippets, batch),
            *_module_fallback_questions(batch),
        ]),
        batch.limit,
    )

    if items:
        replacement = next(
            (
                item.get("question_text") or item.get("question")
                for item in items
                if (item.get("question_text") or item.get("question")) != question.question
            ),
            items[0].get("question_text") or items[0].get("question", question.question),
        )
        question.question = replacement or question.question
        question.module = batch.module
        question.source_section = batch.source_section
        question.question_type = _infer_question_type(question.question, batch)
        log_audit_event(
            db,
            event_type="interview.regenerate_question",
            resource_type="interview_question",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            organization_id=interview.organization_id,
            resource_id=str(question.id),
            request=request,
            metadata={"interview_id": str(interview.id)},
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
            "feedback": q.feedback,
        })

    llm = get_llm_client(settings)
    rag_snippets = await retrieve_knowledge(
        db,
        f"{compact_json(qa_records, 4000)} {compact_json(interview.jd_text or '', 1000)}",
        categories=["interview_rubric", "reporting", "job_knowledge"],
        limit=6,
    )
    prompt = SUMMARIZE_INTERVIEW_PROMPT.format(
        questions_and_answers=f"{str(qa_records)}\n\n{build_rag_context(rag_snippets)}"
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="面试报告结果不可用，请稍后重试")
    llm_metadata = llm.build_usage_metadata(
        messages,
        response,
        feature="interview_report",
        started_at=started_at,
    )

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
    interview.total_score = float(response.get("total_score", avg_total * 10))
    interview.dimension_scores = response_dimension_scores or dimension_scores
    interview.summary = response.get("summary", "")
    interview.weak_points = response.get("weak_points", [])
    interview.suggestions = response.get("suggestions", [])
    log_audit_event(
        db,
        event_type="interview.finish",
        resource_type="interview",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=interview.organization_id,
        resource_id=str(interview.id),
        request=request,
        metadata={"answered_count": len(answered), "total_score": interview.total_score},
    )
    record_usage(
        db,
        current_user.id,
        "interview_report",
        organization_id=interview.organization_id,
        metadata={"interview_id": str(interview.id), "answered_count": len(answered), **llm_metadata},
    )

    await db.commit()
    await db.refresh(interview)

    return InterviewReportResponse(
        id=interview.id,
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
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
        total_score=interview.total_score,
        dimension_scores=interview.dimension_scores,
        summary=interview.summary,
        weak_points=interview.weak_points,
        suggestions=interview.suggestions,
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
    await ensure_feature_available("report_export", db, current_user.id, settings)
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
