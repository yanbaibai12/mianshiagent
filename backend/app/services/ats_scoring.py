import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume
from app.services.rerank_service import rerank_status
from app.services.resume_index import HARD_SKILL_TERMS, retrieve_resume_evidence

SOFT_SKILL_TERMS = [
    "沟通",
    "协作",
    "推进",
    "复盘",
    "学习",
    "责任心",
    "团队",
    "表达",
    "抗压",
    "主动",
    "问题拆解",
    "需求分析",
    "结果交付",
]

PROJECT_EVIDENCE_TERMS = [
    "项目",
    "实习",
    "接口",
    "优化",
    "联调",
    "排查",
    "上线",
    "交付",
    "架构",
    "性能",
    "日志",
    "监控",
    "测试",
    "任务队列",
    "RAG",
    "Agent",
]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip(" ，,、;；。")
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _contains(text: str, term: str) -> bool:
    if re.search(r"[a-zA-Z0-9]", term):
        pattern = rf"(?<![a-zA-Z0-9+#./-]){re.escape(term)}(?![a-zA-Z0-9+#./-])"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return bool(re.search(re.escape(term), text, re.IGNORECASE))


def _extract_lines(jd_text: str, markers: tuple[str, ...], limit: int = 8) -> list[str]:
    lines = []
    for line in jd_text.replace("\r\n", "\n").split("\n"):
        cleaned = re.sub(r"^\s*(?:[-*•·]|\d+[.、)]|[（(]?\d+[）)])\s*", "", line).strip()
        if cleaned and any(marker in cleaned for marker in markers):
            lines.append(cleaned[:180])
    return _dedupe(lines)[:limit]


def extract_jd_requirements(jd_text: str) -> dict[str, Any]:
    hard_skills = [term for term in HARD_SKILL_TERMS if _contains(jd_text, term)]
    soft_skills = [term for term in SOFT_SKILL_TERMS if _contains(jd_text, term)]
    project_terms = [term for term in PROJECT_EVIDENCE_TERMS if _contains(jd_text, term)]
    responsibilities = _extract_lines(jd_text, ("负责", "参与", "建设", "设计", "开发", "优化", "落地", "实现", "维护", "推进"))
    bonus = _extract_lines(jd_text, ("优先", "加分", "熟悉", "了解"))
    education = _extract_lines(jd_text, ("本科", "硕士", "学历", "计算机", "软件工程", "年经验", "经验"))

    keywords = _dedupe(
        [
            *hard_skills,
            *soft_skills,
            *project_terms,
            *re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}|[\u4e00-\u9fa5]{2,8}", jd_text),
        ]
    )[:40]
    return {
        "responsibilities": responsibilities,
        "required_skills": hard_skills,
        "soft_skills": soft_skills,
        "project_terms": project_terms,
        "bonus_skills": bonus,
        "education_or_experience": education,
        "keywords": keywords,
    }


def _resume_text(resume: Resume) -> str:
    parts = [resume.original_text or ""]
    if isinstance(resume.parsed_data, dict):
        parts.append(str(resume.parsed_data))
    return "\n".join(parts)


def _resume_has_section(resume: Resume, section: str) -> bool:
    data = resume.parsed_data if isinstance(resume.parsed_data, dict) else {}
    value = data.get(section)
    return bool(value)


def _evidence_payload(requirement: str, snippets: list) -> list[dict[str, Any]]:
    payload = []
    for snippet in snippets[:3]:
        payload.append(
            {
                "requirement": requirement,
                "section": snippet.section,
                "section_label": snippet.to_dict().get("section_label"),
                "item_title": snippet.item_title,
                "excerpt": snippet.content[:260],
                "score": round(snippet.score, 3),
                "source": snippet.retrieval_source,
            }
        )
    return payload


def _suggestion_for(name: str, missing: list[str], risk: list[str]) -> str:
    if missing:
        return f"优先检查原简历是否已有 {missing[0]} 相关事实；如果有，把动作、技术细节和结果补到项目或实习条目中。"
    if risk:
        return f"当前{name}存在表达风险，建议补充可验证证据，避免只写能力标签。"
    return "该维度已有证据支撑，下一步可补充量化指标和方案取舍，让表达更有说服力。"


def _dimension(
    key: str,
    name: str,
    score: float,
    covered: list[str],
    missing: list[str],
    evidence: list[dict[str, Any]],
    risk: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "score": round(max(0, min(100, score)), 1),
        "covered": _dedupe(covered),
        "missing": _dedupe(missing),
        "evidence": evidence[:8],
        "risk": _dedupe(risk),
        "suggestion": _suggestion_for(name, missing, risk),
    }


async def build_ats_report(db: AsyncSession, resume: Resume, jd_text: str) -> dict[str, Any]:
    requirements = extract_jd_requirements(jd_text)
    resume_text = _resume_text(resume)

    requirement_evidence: list[dict[str, Any]] = []
    hard_covered: list[str] = []
    hard_missing: list[str] = []
    soft_covered: list[str] = []
    soft_missing: list[str] = []
    keyword_covered: list[str] = []
    keyword_missing: list[str] = []
    project_evidence: list[dict[str, Any]] = []

    async def collect(term: str, sections: list[str] | None = None) -> list:
        snippets = await retrieve_resume_evidence(
            db,
            user_id=resume.user_id,
            resume_id=resume.id,
            query=term,
            sections=sections,
            limit=3,
        )
        return snippets

    for skill in requirements["required_skills"]:
        snippets = await collect(skill)
        evidence = _evidence_payload(skill, snippets)
        if snippets or _contains(resume_text, skill):
            hard_covered.append(skill)
            requirement_evidence.extend(evidence)
        else:
            hard_missing.append(skill)

    for skill in requirements["soft_skills"]:
        snippets = await collect(skill)
        evidence = _evidence_payload(skill, snippets)
        if snippets or _contains(resume_text, skill):
            soft_covered.append(skill)
            requirement_evidence.extend(evidence)
        else:
            soft_missing.append(skill)

    project_query_terms = _dedupe([*requirements["project_terms"], *requirements["required_skills"]])[:12]
    for term in project_query_terms:
        snippets = await collect(term, sections=["project", "experience"])
        evidence = _evidence_payload(term, snippets)
        if evidence:
            project_evidence.extend(evidence)

    for keyword in requirements["keywords"][:24]:
        if _contains(resume_text, keyword):
            keyword_covered.append(keyword)
        else:
            snippets = await collect(keyword)
            if snippets:
                keyword_covered.append(keyword)
                requirement_evidence.extend(_evidence_payload(keyword, snippets[:1]))
            else:
                keyword_missing.append(keyword)

    hard_total = max(1, len(requirements["required_skills"]))
    soft_total = max(1, len(requirements["soft_skills"]))
    keyword_total = max(1, len(requirements["keywords"][:24]))
    project_score = min(100, 45 + len(project_evidence) * 9)

    format_risk = []
    if not _resume_has_section(resume, "projects"):
        format_risk.append("缺少项目经历模块")
    if not _resume_has_section(resume, "experience"):
        format_risk.append("缺少实习/工作经历模块")
    if not _resume_has_section(resume, "skills"):
        format_risk.append("缺少技术栈模块")
    if not _resume_has_section(resume, "education"):
        format_risk.append("缺少教育经历模块")

    education_risk = []
    if requirements["education_or_experience"] and not _resume_has_section(resume, "education"):
        education_risk.append("JD 提到学历/经验要求，但简历教育或经验信息不足")
    if re.search(r"\d+\s*年", jd_text) and not _resume_has_section(resume, "experience"):
        education_risk.append("JD 提到年限要求，但简历缺少可证明的工作/实习时长")

    dimensions = [
        _dimension(
            "hard_skills",
            "硬技能匹配",
            len(hard_covered) / hard_total * 100 if requirements["required_skills"] else 72,
            hard_covered,
            hard_missing,
            [item for item in requirement_evidence if item["requirement"] in hard_covered],
            ["硬技能缺口会直接影响 ATS 初筛"] if hard_missing else [],
        ),
        _dimension(
            "soft_skills",
            "软技能匹配",
            len(soft_covered) / soft_total * 100 if requirements["soft_skills"] else 70,
            soft_covered,
            soft_missing,
            [item for item in requirement_evidence if item["requirement"] in soft_covered],
            ["软技能只有标签，缺少情景证据"] if soft_missing and soft_covered else [],
        ),
        _dimension(
            "project_evidence",
            "项目证据强度",
            project_score if project_query_terms else 68,
            _dedupe([item["requirement"] for item in project_evidence]),
            [term for term in project_query_terms if term not in {item["requirement"] for item in project_evidence}],
            project_evidence,
            ["JD 技术点需要落到项目或实习事实，不能只放在技能列表"] if project_query_terms and not project_evidence else [],
        ),
        _dimension(
            "keyword_coverage",
            "关键词覆盖",
            len(keyword_covered) / keyword_total * 100,
            keyword_covered[:16],
            keyword_missing[:16],
            requirement_evidence[:8],
            ["关键词缺口较多，可能影响 ATS 召回"] if len(keyword_missing) > len(keyword_covered) else [],
        ),
        _dimension(
            "education_experience_risk",
            "学历/年限风险",
            100 - len(education_risk) * 28,
            requirements["education_or_experience"][:6],
            [],
            [],
            education_risk,
        ),
        _dimension(
            "format_risk",
            "格式风险",
            100 - len(format_risk) * 18,
            ["结构化模块完整"] if not format_risk else [],
            format_risk,
            [],
            format_risk,
        ),
    ]

    weights = {
        "hard_skills": 0.24,
        "soft_skills": 0.10,
        "project_evidence": 0.24,
        "keyword_coverage": 0.20,
        "education_experience_risk": 0.10,
        "format_risk": 0.12,
    }
    total_score = round(sum(item["score"] * weights[item["key"]] for item in dimensions), 1)
    missing_top = _dedupe([*hard_missing, *keyword_missing])[:8]

    advice = []
    if total_score >= 85:
        advice.append("可以投递；建议把命中的项目证据前置，并补充 1-2 个量化结果。")
    elif total_score >= 70:
        advice.append("可以尝试投递；建议先补齐硬技能证据和项目结果，再生成投递版。")
    else:
        advice.append("暂不建议直接投递；需要先补齐 JD 核心技能或更换匹配度更高的岗位。")
    if missing_top:
        advice.append(f"优先处理缺口：{'、'.join(missing_top[:5])}。")

    return {
        "total_score": total_score,
        "jd_requirements": requirements,
        "dimensions": dimensions,
        "requirement_evidence": requirement_evidence[:18],
        "missing_top": missing_top,
        "delivery_advice": advice,
        "pipeline": {
            "retrieval": "resume_keyword + resume_vector",
            "fusion": "rrf",
            "rerank": rerank_status(),
            "scope": "user_id + resume_id",
        },
    }
