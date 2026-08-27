import ast
import json
import re
import time
from copy import deepcopy
from typing import Any

from app.config import Settings
from app.utils.json_extract import extract_json

COMMON_SKILLS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "Spring",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "MongoDB",
    "Docker",
    "Kubernetes",
    "Linux",
    "Git",
    "CI/CD",
    "A/B",
    "Agent",
    "RAG",
    "BM25",
    "RRF",
    "Qdrant",
    "BGE-M3",
    "Embedding",
    "Function Calling",
    "Tool Calling",
    "API",
    "任务队列",
    "异步",
    "Prompt Injection",
    "数据分析",
    "用户调研",
    "需求分析",
    "项目管理",
    "增长",
    "转化率",
    "留存",
]

DIMENSION_KEYS = [
    "technical_accuracy",
    "project_understanding",
    "structure_clarity",
    "troubleshooting",
    "engineering_delivery",
    "reflection",
]


class LLMCallError(RuntimeError):
    pass


def _message_text(messages: list[dict]) -> str:
    return "\n".join(str(message.get("content", "")) for message in messages)


def _after(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].strip()


def _between(text: str, start: str, end: str) -> str:
    value = _after(text, start)
    if end in value:
        value = value.split(end, 1)[0]
    return value.strip()


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        item = item.strip(" ，,、;；。")
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _safe_literal(value: str) -> Any:
    value = value.strip()
    try:
        return ast.literal_eval(value)
    except Exception:
        try:
            return json.loads(value)
        except Exception:
            return {}


def _first_literal_block(value: str, opener: str, closer: str) -> str:
    start = value.find(opener)
    if start < 0:
        return value

    depth = 0
    for index in range(start, len(value)):
        char = value[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return value[start:]


def _extract_skills(text: str) -> list[str]:
    found = []
    for skill in COMMON_SKILLS:
        if re.search(re.escape(skill), text, re.IGNORECASE):
            found.append(skill)

    for line in text.splitlines():
        if any(key in line for key in ("技能", "技术栈", "熟悉", "掌握")):
            parts = re.split(r"[、,，/|；;\s]+", re.sub(r"^.*?[：:]", "", line))
            found.extend(part for part in parts if 1 < len(part) <= 24)

    return _dedupe(found)[:18]


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•·]|\d+[.、)]|[（(]?\d+[）)])\s*", "", line).strip()


def _compact_lines(text: str) -> list[str]:
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = _strip_bullet(line)
        if line:
            lines.append(line)
    return lines


def _section(lines: list[str], headings: tuple[str, ...]) -> list[str]:
    stop_words = (
        "教育经历",
        "教育背景",
        "工作经历",
        "实习经历",
        "项目经历",
        "项目经验",
        "专业技能",
        "技能",
        "自我评价",
        "个人评价",
        "获奖",
        "证书",
    )
    collecting = False
    result = []
    for line in lines:
        if any(heading in line for heading in headings):
            collecting = True
            continue
        if collecting and any(word in line for word in stop_words) and not any(
            heading in line for heading in headings
        ):
            break
        if collecting:
            result.append(line)
    return result


def _first_reasonable_name(lines: list[str]) -> str:
    for line in lines[:8]:
        if any(key in line for key in ("简历", "电话", "邮箱", "求职", "应聘", "@")):
            continue
        cleaned = re.sub(r"\s+", "", line)
        if 2 <= len(cleaned) <= 12:
            return cleaned
    return ""


def _make_points(title: str, description: str, skills: list[str]) -> list[dict[str, str]]:
    candidates = skills[:2] or [title or "核心经历"]
    points = []
    for idx, candidate in enumerate(candidates, 1):
        points.append(
            {
                "id": f"p{idx}",
                "title": candidate,
                "description": description[:260] or f"围绕{candidate}的方案设计、执行过程和结果复盘。",
            }
        )
    return points


def _build_experience_item(
    lines: list[str],
    fallback_title: str,
    skills: list[str],
    is_project: bool,
) -> dict[str, Any]:
    title = next(
        (
            line
            for line in lines[:5]
            if not any(key in line for key in ("项目经历", "项目经验", "工作经历", "实习经历"))
        ),
        fallback_title,
    )
    highlights = [line for line in lines if line != title and len(line) > 6][:5]
    if not highlights and title:
        highlights = [title]
    description = "；".join(highlights[:3])
    points = _make_points(title, description, skills)

    if is_project:
        return {
            "name": title or fallback_title,
            "role": "",
            "time": "",
            "description": description,
            "tech_stack": skills[:8],
            "interview_points": points,
        }

    return {
        "company": title or fallback_title,
        "role": "",
        "time": "",
        "highlights": highlights,
        "interview_points": points,
    }


class LocalLLMClient:
    """Deterministic MVP fallback used when no external model is configured."""

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        data = await self.chat_completion_json(messages, temperature, max_tokens)
        return json.dumps(data, ensure_ascii=False)

    async def chat_completion_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        prompt = _message_text(messages)
        if "专业的简历解析助手" in prompt:
            return self._parse_resume(_after(prompt, "简历文本：") or _after(prompt, "简历文本:"))
        if "资深 HR" in prompt or "简历模板" in prompt:
            return self._optimize_resume(prompt)
        if "岗位匹配专家" in prompt:
            return self._adapt_jd(prompt)
        if "生成 5 个递进式面试小问题" in prompt:
            return self._generate_questions(prompt)
        if "面试官" in prompt and "用户回答" in prompt:
            return self._score_answer(prompt)
        if "面试辅导专家" in prompt:
            return self._summarize_interview(prompt)
        return {}

    def _parse_resume(self, resume_text: str) -> dict[str, Any]:
        lines = _compact_lines(resume_text)
        email_match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", resume_text)
        phone_match = re.search(r"(?<!\d)(?:1[3-9]\d{9}|\d{3,4}[- ]?\d{7,8})(?!\d)", resume_text)
        name_match = re.search(r"(?:姓名|Name)\s*[：:]\s*([^\s，,|]+)", resume_text, re.IGNORECASE)
        intent_match = re.search(r"(?:求职意向|应聘岗位|目标岗位)\s*[：:]\s*([^\n\r]+)", resume_text)

        skills = _extract_skills(resume_text)
        project_lines = _section(lines, ("项目经历", "项目经验", "Projects"))
        experience_lines = _section(lines, ("工作经历", "工作经验", "实习经历", "Experience"))

        if not project_lines:
            project_lines = [line for line in lines if "项目" in line][:8]
        if not experience_lines:
            experience_lines = [line for line in lines if any(key in line for key in ("实习", "负责", "参与", "开发", "运营"))][:8]

        projects = []
        if project_lines:
            projects.append(_build_experience_item(project_lines, "简历核心项目", skills, True))

        experience = []
        if experience_lines:
            experience.append(_build_experience_item(experience_lines, "核心实践经历", skills, False))

        if not projects and not experience:
            fallback_lines = lines[:8] or ["待补充简历经历"]
            projects.append(_build_experience_item(fallback_lines, "简历核心项目", skills, True))

        education = []
        for line in lines:
            if any(key in line for key in ("大学", "学院", "本科", "硕士", "博士", "大专")):
                education.append({"school": line, "major": "", "degree": "", "time": ""})
                break

        summary_lines = _section(lines, ("自我评价", "个人评价", "Summary"))
        summary = "；".join(summary_lines[:3])
        if not summary:
            summary = "具备岗位相关经历，能够围绕项目背景、个人贡献和结果进行结构化表达。"

        return {
            "personal": {
                "name": name_match.group(1) if name_match else _first_reasonable_name(lines),
                "phone": phone_match.group(0) if phone_match else "",
                "email": email_match.group(0) if email_match else "",
                "job_intent": intent_match.group(1).strip() if intent_match else "",
            },
            "education": education,
            "experience": experience,
            "projects": projects,
            "skills": skills,
            "summary": summary,
        }

    def _resume_data_from_prompt(self, prompt: str) -> dict[str, Any]:
        value = _between(prompt, "原始简历：", "要求：") or _between(prompt, "当前简历：", "请完成：")
        parsed = _safe_literal(value)
        return parsed if isinstance(parsed, dict) else {}

    def _optimize_resume(self, prompt: str) -> dict[str, Any]:
        data = deepcopy(self._resume_data_from_prompt(prompt))
        if not data:
            return {}

        for item in data.get("experience", []):
            highlights = item.get("highlights") or []
            item["highlights"] = [
                self._polish_line(line, "围绕业务目标梳理任务、行动与结果") for line in highlights
            ] or ["围绕业务目标梳理任务、行动与结果，突出个人贡献和可复盘成果。"]
            if not item.get("interview_points"):
                item["interview_points"] = _make_points(item.get("company", ""), "；".join(item["highlights"]), data.get("skills", []))

        for item in data.get("projects", []):
            description = item.get("description") or ""
            item["description"] = self._polish_line(description, "使用 STAR 结构呈现项目背景、行动和结果")
            if not item.get("interview_points"):
                item["interview_points"] = _make_points(item.get("name", ""), item["description"], data.get("skills", []))

        if not data.get("summary"):
            skills = "、".join((data.get("skills") or [])[:4])
            data["summary"] = f"具备{skills or '岗位相关'}能力，能结合项目目标拆解问题并推动落地。"

        return data

    def _polish_line(self, line: str, fallback: str) -> str:
        line = (line or "").strip()
        if not line:
            return f"{fallback}。"
        if self._looks_resume_identity_line(line):
            return self._strip_generated_resume_prefix(line)
        if any(key in line for key in ("背景", "负责", "通过", "实现", "提升", "降低")):
            return line
        return f"{fallback}：{line}"

    def _strip_generated_resume_prefix(self, line: str) -> str:
        cleaned = (line or "").strip()
        generated_prefixes = (
            "围绕业务目标梳理任务、行动与结果：",
            "使用 STAR 结构呈现项目背景、行动和结果：",
            "使用 STAR 结构呈现项目背景、个人行动和交付结果：",
            "补充实习中的任务边界、协作过程和交付结果：",
        )
        changed = True
        while changed:
            changed = False
            for prefix in generated_prefixes:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):].strip()
                    changed = True
        return cleaned

    def _looks_resume_identity_line(self, line: str) -> bool:
        cleaned = self._strip_generated_resume_prefix(line)
        if not cleaned:
            return False
        if len(cleaned) > 120:
            return False
        has_date = bool(re.search(r"(?:20\d{2}|19\d{2}|[1-9])(?:[./年-]\d{1,2})?\s*(?:[-~至]|—)\s*(?:20\d{2}|至今|现在)?(?:[./年-]\d{1,2})?", cleaned))
        has_org = bool(re.search(r"公司|有限公司|科技|集团|大学|学院|实验室|工作室|团队|部门|中心", cleaned))
        has_role = bool(re.search(r"实习生|工程师|开发|算法|后端|前端|产品|运营|测试|负责人|助理|专员", cleaned, re.IGNORECASE))
        action_markers = (
            "负责",
            "参与",
            "完成",
            "实现",
            "设计",
            "搭建",
            "优化",
            "联调",
            "排查",
            "通过",
            "使用",
            "构建",
            "对接",
            "维护",
            "提供",
            "支持",
            "交付",
            "上线",
        )
        has_action = any(marker in cleaned for marker in action_markers)
        return has_date and has_org and has_role and not has_action

    def _resume_clause_for_term(self, term: str, line: str) -> str:
        lowered = line.lower()
        if term == "Python":
            return "使用 Python 完成后端业务逻辑、接口联调和脚本化处理"
        if term == "Java":
            return "使用 Java 完成服务端模块开发、接口联调和异常处理"
        if term in {"JavaScript", "TypeScript"}:
            return f"使用 {term} 完成前端交互、接口联调和状态处理"
        if term in {"FastAPI", "API"} or "接口" in line:
            if "python" in lowered:
                return "补齐 Python 接口的参数校验、异常分支、联调记录和脚本化验收"
            if "java" in lowered:
                return "补齐 Java 服务接口的鉴权联调、异常返回、边界条件和测试验收"
            if "react" in lowered or "前端" in line:
                return "处理前端接口 loading/error、空状态、重复提交和结果对比反馈"
            if any(token in lowered for token in ("rag", "embedding", "qdrant", "agent")):
                return "补齐检索/Agent 接口的入参校验、召回异常、降级处理和质量验收"
            return "完成接口设计、参数校验、鉴权联调、异常返回和测试验收"
        if term == "Redis":
            if "验证码" in line or "邮件" in line or "celery" in lowered:
                return "使用 Redis/Celery 承担验证码缓存、邮件发送等异步任务处理"
            return "使用 Redis 处理缓存、任务状态和高频读写场景"
        if term in {"PostgreSQL", "MySQL", "SQL"}:
            return "参与数据表设计、查询优化、接口联调和数据一致性排查"
        if term == "Docker":
            return "完成 Docker 本地环境配置、服务联调和测试环境运行"
        if term == "React":
            return "实现前端表单状态、接口 loading/error 和优化结果对比展示"
        if term == "RAG":
            return "打通文档清洗、智能切片、检索召回、上下文拼接和 RAG 问答链路"
        if term in {"BM25", "RRF", "Qdrant", "BGE-M3", "Embedding"}:
            return "完成向量入库、BM25 与向量召回融合、RRF 排序和召回质量验证"
        if term in {"Agent", "Tool Calling", "Function Calling"}:
            return "设计 Agent 自主推理、工具调用、失败兜底和任务恢复链路"
        if term in {"任务队列", "异步"}:
            return "将耗时处理拆分为异步任务，补齐任务状态、重试和进度反馈"
        return f"基于 {term} 完成工程实现、联调排查和交付验证"

    def _term_appears_in_line(self, term: str, line: str) -> bool:
        lowered = line.lower()
        if re.search(re.escape(term), line, re.IGNORECASE):
            return True
        if term in {"FastAPI", "API"}:
            return any(marker in lowered for marker in ("api", "接口", "联调", "鉴权", "参数校验", "异常返回", "loading/error"))
        if term == "RAG":
            return any(marker in lowered for marker in ("rag", "检索", "召回", "切分", "embedding", "向量"))
        if term in {"BM25", "RRF", "Qdrant", "BGE-M3", "Embedding"}:
            return any(marker in lowered for marker in ("bm25", "rrf", "qdrant", "bge", "embedding", "向量", "重排"))
        if term in {"Agent", "Tool Calling", "Function Calling"}:
            return any(marker in lowered for marker in ("agent", "工具调用", "function calling", "tool calling", "react agent"))
        if term == "Redis":
            return any(marker in lowered for marker in ("redis", "缓存", "队列", "celery"))
        if term in {"任务队列", "异步"}:
            return any(marker in lowered for marker in ("异步", "任务", "队列", "重试"))
        return False

    def _line_specific_terms(self, line: str, context_terms: list[str]) -> list[str]:
        line_terms = [term for term in context_terms if self._term_appears_in_line(term, line)]
        context_hard_terms = [term for term in context_terms if term in COMMON_SKILLS or term in {"任务队列", "异步"}]
        if line_terms:
            line_hard_terms = [term for term in line_terms if term in COMMON_SKILLS or term in {"任务队列", "异步"}]
            if line_hard_terms:
                return _dedupe([*line_hard_terms, *line_terms])[:4]
            return _dedupe([*context_hard_terms[:2], *line_terms])[:4]
        return _dedupe([*context_hard_terms[:2], *context_terms[:2]])[:4]

    def _change_focus(self, line: str, terms: list[str]) -> str:
        lowered = line.lower()
        if "python" in lowered:
            return "Python 后端逻辑与接口验证"
        if "java" in lowered:
            return "Java 服务端模块与异常处理"
        if "react" in lowered or "前端" in line:
            return "前端状态流转、接口反馈与结果展示"
        if any(term in terms for term in ("RAG", "BM25", "RRF", "Qdrant", "BGE-M3", "Embedding")):
            return "检索、向量化、召回筛选与质量验证"
        if any(term in terms for term in ("Agent", "Tool Calling", "Function Calling")):
            return "Agent 规划、工具调用与失败兜底"
        if any(term in terms for term in ("Redis", "任务队列", "异步")):
            return "异步任务、状态持久化与失败重试"
        if any(term in terms for term in ("FastAPI", "API")) or "接口" in line:
            return "接口设计、联调排查与验收"
        if any(term in terms for term in ("SQL", "MySQL", "PostgreSQL")):
            return "数据库读写、索引优化与一致性排查"
        return "工程实现、交付验证与复盘"

    def _validation_clause_for_line(self, line: str, terms: list[str]) -> str:
        lowered = line.lower()
        if "python" in lowered:
            return "补充 Python 接口的参数边界、异常分支和脚本化验收记录"
        if "java" in lowered:
            return "补充 Java 模块的鉴权联调、异常返回和边界条件验证"
        if "react" in lowered or "前端" in line:
            return "补充前端 loading/error、空状态、重复提交和对比展示验收"
        if any(term in terms for term in ("RAG", "BM25", "RRF", "Qdrant", "BGE-M3", "Embedding")):
            return "补充切片、召回、筛选补全和检索质量验证"
        if any(term in terms for term in ("Agent", "Tool Calling", "Function Calling")):
            return "补充 Agent 工具编排、失败兜底和输出质量复盘"
        if any(term in terms for term in ("Redis", "任务队列", "异步")):
            return "补充任务状态、失败重试、进度反馈和服务恢复验证"
        if any(term in terms for term in ("FastAPI", "API")) or "接口" in line:
            return "补充接口参数校验、鉴权联调、异常返回和测试验收"
        if any(term in terms for term in ("SQL", "MySQL", "PostgreSQL")):
            return "补充索引设计、慢查询排查和数据一致性校验"
        return "补充实现边界、联调排查、结果验收和复盘动作"

    def _change_reason(self, section: str, subject: str, before: str, terms: list[str]) -> str:
        terms_label = "、".join(terms[:4]) if terms else "原有经历"
        focus = self._change_focus(before, terms)
        section_label = "项目" if section == "projects" else "实习"
        subject_text = subject or section_label
        return f"针对{subject_text}中已出现的{terms_label}证据，将原句侧重的{focus}补充为可核验的实现、联调、异常处理和验收表达。"

    def _rewrite_line_for_jd(self, line: str, terms: list[str], fallback: str) -> str:
        cleaned = (line or "").strip()
        if not cleaned:
            return ""
        if self._looks_resume_identity_line(cleaned):
            return self._strip_generated_resume_prefix(cleaned)
        clean_sentence = cleaned.rstrip("。；; ")
        effective_terms = self._line_specific_terms(cleaned, _dedupe([term for term in terms if term]))
        if effective_terms:
            clauses = _dedupe(
                [
                    self._resume_clause_for_term(term, cleaned)
                    for term in effective_terms[:6]
                    if term in COMMON_SKILLS or term in {"任务队列", "异步"}
                ]
            )
            if not clauses:
                clauses = [f"围绕{'、'.join(effective_terms[:4])}完成工程实现、联调排查、测试验证和结果复盘"]
            after = clean_sentence
            for clause in clauses[:3]:
                if clause and clause not in after:
                    after = f"{after}；{clause}"
            if after == clean_sentence:
                validation_clause = self._validation_clause_for_line(cleaned, effective_terms)
                if validation_clause and validation_clause not in after:
                    after = f"{after}；{validation_clause}"
            if not any(marker in after for marker in ("负责", "参与", "完成", "实现", "设计", "使用", "通过")):
                after = f"负责{after}"
            return f"{after}。"
        return self._polish_line(cleaned, fallback)

    def _adapt_jd(self, prompt: str) -> dict[str, Any]:
        jd_text = _between(prompt, "岗位 JD：", "当前简历：")
        resume_data = deepcopy(self._resume_data_from_prompt(prompt))
        resume_text = json.dumps(resume_data, ensure_ascii=False)
        keywords = self._jd_keywords(jd_text)
        matched = [kw for kw in keywords if re.search(re.escape(kw), resume_text, re.IGNORECASE)]
        coverage = len(matched) / len(keywords) if keywords else 0
        score = round(45 + coverage * 45 + min(len(matched), 5) * 2, 1)
        score = min(score, 96)
        weak_points = [kw for kw in keywords if kw not in matched][:5]
        change_details: list[dict[str, str]] = []

        if resume_data:
            project_items = resume_data.get("projects") if isinstance(resume_data.get("projects"), list) else []
            for project in project_items:
                if not isinstance(project, dict):
                    continue
                project_text = json.dumps(project, ensure_ascii=False)
                project_terms = [term for term in matched if re.search(re.escape(term), project_text, re.IGNORECASE)]
                before = str(project.get("description") or "").strip()
                if self._looks_resume_identity_line(before):
                    project["description"] = self._strip_generated_resume_prefix(before)
                    continue
                after = self._rewrite_line_for_jd(before, project_terms, "使用 STAR 结构呈现项目背景、个人行动和交付结果")
                if after and after != before:
                    project["description"] = after
                    changed_terms = self._line_specific_terms(before or project_text, project_terms)
                    project_subject = str(project.get("name") or project.get("title") or "项目经历")
                    change_details.append(
                        {
                            "section": "projects",
                            "before": before or "原项目描述未单独成句",
                            "after": after,
                            "reason": self._change_reason("projects", project_subject, before, changed_terms),
                            "evidence": before or project.get("name", ""),
                        }
                    )

            experience_items = resume_data.get("experience") if isinstance(resume_data.get("experience"), list) else []
            for experience in experience_items:
                if not isinstance(experience, dict):
                    continue
                experience_text = json.dumps(experience, ensure_ascii=False)
                experience_terms = [term for term in matched if re.search(re.escape(term), experience_text, re.IGNORECASE)]
                highlights = experience.get("highlights") if isinstance(experience.get("highlights"), list) else []
                updated_highlights = []
                for highlight in highlights:
                    before = str(highlight or "").strip()
                    if self._looks_resume_identity_line(before):
                        updated_highlights.append(self._strip_generated_resume_prefix(before))
                        continue
                    after = self._rewrite_line_for_jd(before, experience_terms, "补充实习中的任务边界、协作过程和交付结果")
                    updated_highlights.append(after or before)
                    if after and after != before:
                        changed_terms = self._line_specific_terms(before, experience_terms)
                        experience_subject = str(
                            experience.get("company")
                            or experience.get("role")
                            or experience.get("title")
                            or "实习经历"
                        )
                        change_details.append(
                            {
                                "section": "experience",
                                "before": before,
                                "after": after,
                                "reason": self._change_reason("experience", experience_subject, before, changed_terms),
                                "evidence": before,
                            }
                        )
                if updated_highlights:
                    experience["highlights"] = updated_highlights

        return {
            "jd_requirements": {
                "responsibilities": self._jd_lines(jd_text, ("负责", "参与", "建设", "推进", "设计")),
                "required_skills": [kw for kw in keywords if kw in COMMON_SKILLS],
                "bonus_skills": self._jd_lines(jd_text, ("优先", "加分", "熟悉")),
                "keywords": keywords,
            },
            "match_score": score,
            "weak_points": weak_points,
            "change_details": change_details,
            "optimized_resume": resume_data,
        }

    def _jd_keywords(self, jd_text: str) -> list[str]:
        keywords = [skill for skill in COMMON_SKILLS if re.search(re.escape(skill), jd_text, re.IGNORECASE)]
        cn_words = re.findall(r"[\u4e00-\u9fa5]{2,8}", jd_text)
        stop_words = {"岗位职责", "任职要求", "优先考虑", "相关经验", "工作经验", "以上学历", "团队合作"}
        keywords.extend(word for word in cn_words if word not in stop_words and len(word) >= 2)
        return _dedupe(keywords)[:24]

    def _jd_lines(self, jd_text: str, markers: tuple[str, ...]) -> list[str]:
        lines = [_strip_bullet(line) for line in jd_text.splitlines()]
        return [line for line in lines if line and any(marker in line for marker in markers)][:6]

    def _generate_questions(self, prompt: str) -> list[dict[str, str]]:
        title = _between(prompt, "要点：", "要点描述：") or "该经历"
        description = _between(prompt, "要点描述：", "关联经历：")
        subject = title.strip() or description[:16] or "该经历"
        lowered = prompt.lower()
        templates = [f"{subject}的业务目标、用户场景和个人交付边界是什么？请按请求链路或数据链路讲清楚。"]
        if any(term in lowered for term in ["rrf", "bm25", "混合检索", "倒数排序"]):
            templates.append(
                f"{subject}里如果用了 BM25 和向量召回，你如何用 RRF 做排序融合？为什么不能直接把两路分数相加？"
            )
        if "rag" in lowered or "检索增强" in lowered or "知识库" in lowered:
            templates.append(
                f"请拆解{subject}的 RAG 链路：清洗、切片、embedding、召回、重排、上下文拼接分别怎么做？"
            )
        if "qdrant" in lowered:
            templates.append(
                f"{subject}接入 Qdrant 时，collection 维度、payload、过滤条件和索引重建流程怎么设计？"
            )
        if "bge" in lowered:
            templates.append("使用 BGE-M3 时为什么要确认 1024 维向量与向量库 collection 一致？模型切换后怎么重建索引？")
        if "fastapi" in lowered:
            templates.append(f"{subject}中的 FastAPI 接口如何拆分路由、鉴权、参数校验和异常返回？长任务为什么不能同步等待？")
        if "redis" in lowered:
            templates.append(f"如果{subject}用 Redis 做缓存或任务队列，你如何设计 key、过期策略、幂等和失败重试？")
        if any(term in lowered for term in ["agent", "tool calling", "function calling", "工具调用"]):
            templates.append(f"{subject}里的 Agent 工具调用链路怎么设计？tool schema、权限边界和失败兜底如何处理？")
        if "prompt injection" in lowered or "提示词注入" in lowered:
            templates.append(f"如果输入中夹带 prompt injection 指令，{subject}如何隔离不可信内容并防止越权调用工具？")
        templates.extend(
            [
                f"{subject}推进过程中遇到过哪些联调、数据一致性、性能或权限问题？你如何定位根因并验证修复有效？",
                f"{subject}里有哪些方案取舍？如果让你重做一次，你会从架构、成本、稳定性或用户体验上怎么优化？",
                f"{subject}最终结果如何衡量？如果简历里没有量化数据，你会在面试中补充哪些可验证证据？",
            ]
        )
        templates = _dedupe(templates)[:5]
        return [
            {"question_id": f"local-q{idx}", "question_text": question}
            for idx, question in enumerate(templates, 1)
        ]

    def _score_answer(self, prompt: str) -> dict[str, Any]:
        question = _between(prompt, "题目：", "用户回答：")
        answer = _between(prompt, "用户回答：", "简历上下文：")
        answer_len = len(answer.strip())
        has_structure = bool(re.search(r"首先|其次|最后|背景|目标|行动|结果|因为|所以|一方面|另一方面", answer))
        has_numbers = bool(re.search(r"\d+|%|QPS|DAU|ROI", answer, re.IGNORECASE))
        has_technical_terms = bool(
            re.search(
                r"RAG|Agent|FastAPI|Redis|SQL|MySQL|PostgreSQL|Qdrant|BGE|RRF|BM25|接口|缓存|索引|重排|切片|embedding",
                answer,
                re.IGNORECASE,
            )
        )
        has_project_context = bool(re.search(r"背景|目标|职责|负责|参与|交付|上线|用户|业务|模块", answer))
        has_troubleshooting = bool(re.search(r"定位|排查|复现|日志|监控|验证|回滚|失败|异常|原因", answer))
        has_delivery = bool(re.search(r"接口|联调|测试|上线|验收|稳定|性能|成本|重试|队列|权限", answer))
        has_reflection = bool(re.search(r"复盘|取舍|指标|优化|不足|改进|下一步|风险|教训", answer))

        scores = {
            "technical_accuracy": self._clamp(4 + (2 if has_technical_terms else 0) + answer_len // 100),
            "project_understanding": self._clamp(4 + (2 if has_project_context else 0) + (1 if answer_len > 80 else 0)),
            "structure_clarity": self._clamp(4 + (3 if has_structure else 0) + answer_len // 160),
            "troubleshooting": self._clamp(4 + (3 if has_troubleshooting else 0) + (1 if has_numbers else 0)),
            "engineering_delivery": self._clamp(4 + (3 if has_delivery else 0) + (1 if has_numbers else 0)),
            "reflection": self._clamp(4 + (3 if has_reflection else 0) + (1 if has_numbers else 0)),
        }
        total = round(sum(scores.values()) / len(scores), 1)
        feedback = "优点：回答已覆盖基本内容" + ("，并体现了结构化表达" if has_structure else "")
        feedback += "。不足：建议补充具体技术链路、排查验证过程、上线验收结果和复盘指标。"

        refined = answer.strip()
        if refined:
            refined = refined[:140]
            refined = f"可按 STAR 表达：背景是{question[:24]}相关场景；我的行动是{refined}；结果需补充可验证指标、联调或排查过程，并说明复盘改进。"
        else:
            refined = "可按 STAR 表达：先说明项目背景和目标，再讲自己的关键动作、技术方案、联调排查和上线验收，最后补充结果指标与复盘改进。"

        return {
            "scores": scores,
            "total_score": total,
            "score_details": {
                key: {
                    "score": value,
                    "evidence": answer.strip()[:140],
                    "issue": "回答需要补充更具体的技术链路、项目证据、排查验证和复盘指标。",
                    "suggestion": "按背景、个人动作、技术方案、验证结果、复盘改进组织答案。",
                    "risk": "高" if value < 6 else "中" if value < 8 else "低",
                }
                for key, value in scores.items()
            },
            "feedback": feedback,
            "refined_answer": refined[:220],
        }

    def _clamp(self, value: int) -> int:
        return max(1, min(10, value))

    def _summarize_interview(self, prompt: str) -> dict[str, Any]:
        records_text = _after(prompt, "作答记录：").split("请输出", 1)[0]
        bounded_records = _between(
            prompt,
            '<UNTRUSTED_DATA source="candidate_answer">',
            "</UNTRUSTED_DATA>",
        )
        records = _safe_literal(_first_literal_block(bounded_records or records_text, "[", "]"))
        records = records if isinstance(records, list) else []
        dimension_values = {key: [] for key in DIMENSION_KEYS}
        for record in records:
            scores = record.get("scores") or {}
            for key in DIMENSION_KEYS:
                if key in scores:
                    dimension_values[key].append(float(scores[key]))

        dimension_scores = {
            key: round(sum(values) / len(values), 1) if values else 0 for key, values in dimension_values.items()
        }
        answered_count = len(records)
        avg = sum(dimension_scores.values()) / len(DIMENSION_KEYS) if answered_count else 0

        weak_points = [
            "技术回答需要更稳定地覆盖链路、边界条件和验证方式",
            "项目表达需要补充个人交付边界、联调排查过程和上线验收结果",
            "复盘部分需要补充指标、方案取舍和下一步优化动作",
        ]
        suggestions = [
            "为每段项目经历准备 1 份 STAR 版本和 1 份 60 秒精简版本，固定包含接口或模块边界",
            "整理关键指标、技术难点、联调问题、本人贡献，形成面试素材表",
            "针对低分维度复盘答案，优先补足排查过程、结果数据和方案理由",
        ]

        return {
            "total_score": round(avg * 10, 1),
            "dimension_scores": dimension_scores,
            "summary": f"本次完成 {answered_count} 道题，整体能覆盖基本问题，但答案还需要更突出技术准确性、个人贡献、工程交付证据和复盘思考。",
            "weak_points": weak_points,
            "suggestions": suggestions,
            "report_details": {
                "hire_signal": "positive" if avg >= 7.5 else "borderline" if avg >= 6 else "weak",
                "strongest_evidence": [],
                "repeated_gaps": weak_points[:2],
                "follow_up_training_plan": suggestions,
                "next_interview_questions": [
                    "请补充一个真实联调或线上排查案例，说明定位路径和验证方式。",
                    "请选择一个项目技术点，说明当时为什么这样设计以及替代方案的取舍。",
                ],
            },
        }


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.LLM_MODEL
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.max_retries = settings.LLM_MAX_RETRIES
        self.timeout = settings.LLM_TIMEOUT_SECONDS
        self.allow_fallback = settings.LLM_ALLOW_FALLBACK
        self.input_price_per_1k = settings.LLM_INPUT_PRICE_PER_1K_TOKENS_CNY
        self.output_price_per_1k = settings.LLM_OUTPUT_PRICE_PER_1K_TOKENS_CNY
        self._local_client = LocalLLMClient()
        self._use_local = self.provider == "local" or not self.api_key or self.api_key == "your-llm-api-key"

        if self._use_local:
            self._client = None
        elif self.provider == "anthropic":
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
        elif self.provider in ("openai", "moonshot", "deepseek", "custom"):
            from openai import AsyncOpenAI

            kwargs = {"api_key": self.api_key, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        else:
            raise ValueError(f"不支持的 LLM provider: {self.provider}")

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4000,
        feature: str | None = None,
    ) -> str:
        if self._use_local:
            return await self._local_client.chat_completion(messages, temperature, max_tokens)

        model = self.model_for_feature(feature)
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "anthropic":
                    return await self._call_anthropic(messages, temperature, max_tokens, model=model)
                return await self._call_openai_compatible(messages, temperature, max_tokens, model=model)
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    continue

        raise LLMCallError(f"LLM 调用失败（已重试 {self.max_retries} 次）: {last_error}")

    async def _call_anthropic(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        *,
        model: str,
    ) -> str:
        system = ""
        user_messages = messages
        if messages and messages[0]["role"] == "system":
            system = messages[0]["content"]
            user_messages = messages[1:]

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=user_messages,
        )
        return response.content[0].text

    async def _call_openai_compatible(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        *,
        model: str,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def chat_completion_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4000,
        feature: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if self._use_local:
            return await self._local_client.chat_completion_json(messages, temperature, max_tokens)

        try:
            text = await self.chat_completion(messages, temperature, max_tokens, feature=feature)
            return extract_json(text)
        except Exception as exc:
            if self.allow_fallback:
                return await self._local_client.chat_completion_json(messages, temperature, max_tokens)
            raise LLMCallError("LLM 返回结果不可用，请稍后重试或检查模型配置。") from exc

    def model_for_feature(self, feature: str | None) -> str:
        return self.settings.llm_model_for_feature(feature)

    def prompt_version_for_feature(self, feature: str | None) -> str:
        return self.settings.prompt_version_for_feature(feature)

    def build_usage_metadata(
        self,
        messages: list[dict],
        response: Any,
        *,
        feature: str,
        started_at: float | None = None,
    ) -> dict[str, Any]:
        input_text = _message_text(messages)
        output_text = json.dumps(response, ensure_ascii=False, default=str)
        input_tokens = self._estimate_tokens(input_text)
        output_tokens = self._estimate_tokens(output_text)
        estimated_cost_cny = (
            input_tokens / 1000 * self.input_price_per_1k
            + output_tokens / 1000 * self.output_price_per_1k
        )
        return {
            "llm": {
                "feature": feature,
                "provider": self.provider,
                "model": self.model_for_feature(feature),
                "default_model": self.model,
                "prompt_version": self.prompt_version_for_feature(feature),
                "source": "local" if self._use_local else "provider",
                "fallback_allowed": self.allow_fallback,
                "input_chars": len(input_text),
                "output_chars": len(output_text),
                "estimated_input_tokens": input_tokens,
                "estimated_output_tokens": output_tokens,
                "estimated_cost_cny": round(estimated_cost_cny, 6),
                "duration_ms": round((time.monotonic() - started_at) * 1000, 1) if started_at else None,
            }
        }

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)


_llm_client: LLMClient | None = None


def get_llm_client(settings: Settings) -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(settings)
    return _llm_client
