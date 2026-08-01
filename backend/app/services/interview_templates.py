from copy import deepcopy
from typing import Any


DEFAULT_INTERVIEW_TEMPLATE_ID = "comprehensive"


INTERVIEW_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_id": "technical_first",
        "name": "技术一面",
        "scenario": "用于技术初筛和一面，重点验证 Agent/RAG 基础、工程实现边界和弱项画像。",
        "module_ratios": {
            "agent_fundamentals": 0.5,
            "project": 0.25,
            "internship": 0.1,
            "system_design": 0.15,
        },
        "module_question_limits": {
            "agent_fundamentals": 5,
            "project": 2,
            "internship": 1,
            "system_design": 1,
        },
        "question_count": 9,
        "module_order": ["agent_fundamentals", "project", "system_design", "internship", "resume"],
        "question_focus": ["Agent 八股", "RAG", "Tool Calling", "工程基础", "弱项追问"],
        "scoring_dimensions": [
            {"key": "technical_accuracy", "label": "技术准确性", "weight": 0.3, "source_score_keys": ["technical_accuracy"]},
            {"key": "concept_boundary", "label": "概念边界", "weight": 0.2, "source_score_keys": ["technical_accuracy", "structure_clarity"]},
            {"key": "implementation_detail", "label": "实现细节", "weight": 0.25, "source_score_keys": ["engineering_delivery", "troubleshooting"]},
            {"key": "engineering_delivery", "label": "工程落地", "weight": 0.25, "source_score_keys": ["engineering_delivery"]},
        ],
        "report_focus": ["技术概念是否准确", "弱项维度是否被补齐", "实现链路和排障证据", "下一轮项目追问风险"],
        "use_training_profile": True,
        "use_company_profile": True,
        "next_round_suggestions": ["项目深挖", "系统设计"],
    },
    {
        "template_id": "project_deep_dive",
        "name": "项目深挖",
        "scenario": "用于二面或项目专项面，重点追问简历项目、实习经历、技术细节和故障排查。",
        "module_ratios": {
            "project": 0.55,
            "internship": 0.25,
            "system_design": 0.1,
            "agent_fundamentals": 0.1,
        },
        "module_question_limits": {
            "project": 6,
            "internship": 3,
            "system_design": 1,
            "agent_fundamentals": 1,
        },
        "question_count": 11,
        "module_order": ["project", "internship", "system_design", "agent_fundamentals", "resume"],
        "question_focus": ["项目背景", "个人贡献", "技术细节", "故障排查", "结果指标"],
        "scoring_dimensions": [
            {"key": "project_understanding", "label": "项目理解", "weight": 0.3, "source_score_keys": ["project_understanding"]},
            {"key": "personal_contribution", "label": "个人贡献", "weight": 0.25, "source_score_keys": ["project_understanding", "engineering_delivery"]},
            {"key": "troubleshooting", "label": "问题定位", "weight": 0.25, "source_score_keys": ["troubleshooting"]},
            {"key": "result_metrics", "label": "结果指标", "weight": 0.2, "source_score_keys": ["reflection", "engineering_delivery"]},
        ],
        "report_focus": ["项目理解深度", "个人贡献边界", "排障过程证据", "量化结果和复盘动作"],
        "use_training_profile": False,
        "use_company_profile": True,
        "next_round_suggestions": ["系统设计", "HR / 行为面"],
    },
    {
        "template_id": "system_design",
        "name": "系统设计",
        "scenario": "用于架构面，重点验证接口、数据流、队列、RAG 链路、可观测性和扩展性。",
        "module_ratios": {
            "system_design": 0.55,
            "project": 0.2,
            "agent_fundamentals": 0.15,
            "internship": 0.1,
        },
        "module_question_limits": {
            "system_design": 6,
            "project": 2,
            "agent_fundamentals": 2,
            "internship": 1,
        },
        "question_count": 11,
        "module_order": ["system_design", "project", "agent_fundamentals", "internship", "resume"],
        "question_focus": ["架构拆解", "接口契约", "数据流", "队列与异步", "观测性", "扩展性"],
        "scoring_dimensions": [
            {"key": "architecture_clarity", "label": "架构清晰度", "weight": 0.25, "source_score_keys": ["structure_clarity", "technical_accuracy"]},
            {"key": "tradeoff", "label": "权衡能力", "weight": 0.2, "source_score_keys": ["reflection", "technical_accuracy"]},
            {"key": "scalability", "label": "扩展性", "weight": 0.2, "source_score_keys": ["engineering_delivery"]},
            {"key": "reliability", "label": "稳定性", "weight": 0.2, "source_score_keys": ["troubleshooting", "engineering_delivery"]},
            {"key": "observability", "label": "可观测性", "weight": 0.15, "source_score_keys": ["troubleshooting", "reflection"]},
        ],
        "report_focus": ["架构边界是否清楚", "关键权衡是否成立", "扩展和稳定性方案", "监控、日志和回滚预案"],
        "use_training_profile": True,
        "use_company_profile": True,
        "next_round_suggestions": ["项目深挖", "综合面"],
    },
    {
        "template_id": "hr_behavior",
        "name": "HR / 行为面",
        "scenario": "用于 HR 面或行为面，重点验证动机、协作、冲突处理、复盘和 STAR 表达。",
        "module_ratios": {
            "behavioral": 0.65,
            "project": 0.2,
            "internship": 0.15,
        },
        "module_question_limits": {
            "behavioral": 6,
            "project": 2,
            "internship": 1,
        },
        "question_count": 9,
        "module_order": ["behavioral", "project", "internship", "resume"],
        "question_focus": ["动机一致性", "协作", "冲突处理", "复盘", "STAR 表达", "稳定性"],
        "scoring_dimensions": [
            {"key": "structure_clarity", "label": "结构表达", "weight": 0.25, "source_score_keys": ["structure_clarity"]},
            {"key": "motivation_fit", "label": "动机一致性", "weight": 0.2, "source_score_keys": ["project_understanding", "reflection"]},
            {"key": "collaboration", "label": "协作", "weight": 0.2, "source_score_keys": ["project_understanding", "structure_clarity"]},
            {"key": "reflection", "label": "复盘能力", "weight": 0.25, "source_score_keys": ["reflection"]},
            {"key": "risk_awareness", "label": "风险意识", "weight": 0.1, "source_score_keys": ["troubleshooting", "engineering_delivery"]},
        ],
        "report_focus": ["STAR 表达完整度", "求职动机和岗位一致性", "协作与冲突处理", "复盘和风险意识"],
        "use_training_profile": False,
        "use_company_profile": True,
        "next_round_suggestions": ["综合面", "项目深挖"],
    },
    {
        "template_id": "comprehensive",
        "name": "综合面",
        "scenario": "用于默认模拟面试，混合项目、技术、系统设计、行为面和弱项追问。",
        "module_ratios": {
            "project": 0.3,
            "internship": 0.15,
            "agent_fundamentals": 0.25,
            "system_design": 0.15,
            "behavioral": 0.15,
        },
        "module_question_limits": {
            "project": 4,
            "internship": 2,
            "agent_fundamentals": 4,
            "system_design": 2,
            "behavioral": 2,
        },
        "question_count": 14,
        "module_order": ["project", "agent_fundamentals", "internship", "system_design", "behavioral", "resume"],
        "question_focus": ["项目", "技术基础", "系统设计", "行为表达", "弱项追问"],
        "scoring_dimensions": [
            {"key": "technical_accuracy", "label": "技术准确性", "weight": 0.2, "source_score_keys": ["technical_accuracy"]},
            {"key": "project_understanding", "label": "项目理解", "weight": 0.2, "source_score_keys": ["project_understanding"]},
            {"key": "structure_clarity", "label": "表达结构", "weight": 0.15, "source_score_keys": ["structure_clarity"]},
            {"key": "troubleshooting", "label": "问题定位", "weight": 0.15, "source_score_keys": ["troubleshooting"]},
            {"key": "engineering_delivery", "label": "工程落地", "weight": 0.15, "source_score_keys": ["engineering_delivery"]},
            {"key": "reflection", "label": "复盘能力", "weight": 0.15, "source_score_keys": ["reflection"]},
        ],
        "report_focus": ["整体面试信号", "技术与项目平衡", "弱项维度", "下一轮训练优先级"],
        "use_training_profile": True,
        "use_company_profile": True,
        "next_round_suggestions": ["技术一面", "项目深挖", "系统设计", "HR / 行为面"],
    },
]


def list_interview_templates() -> list[dict[str, Any]]:
    return deepcopy(INTERVIEW_TEMPLATES)


def get_interview_template(template_id: str | None) -> dict[str, Any]:
    normalized = (template_id or DEFAULT_INTERVIEW_TEMPLATE_ID).strip()
    for template in INTERVIEW_TEMPLATES:
        if template["template_id"] == normalized:
            return deepcopy(template)
    return deepcopy(next(template for template in INTERVIEW_TEMPLATES if template["template_id"] == DEFAULT_INTERVIEW_TEMPLATE_ID))


def template_snapshot(template: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(template)
