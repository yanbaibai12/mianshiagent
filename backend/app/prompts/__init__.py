PARSE_RESUME_PROMPT = """你是一位专业的简历解析助手。请从以下简历文本中提取结构化信息，输出 JSON。

要求：
1. 提取以下字段：
   - personal: 姓名、电话、邮箱、求职意向
   - education: 学校、专业、学历、时间（数组）
   - experience: 工作经历，每项包含公司、职位、时间、亮点（数组）、可面试要点（数组）
   - projects: 项目经历，每项包含项目名、角色、时间、描述、技术栈（数组）、可面试要点（数组）
   - skills: 技能列表（数组）
   - summary: 自我评价

2. 可面试要点指：面试官可能围绕该经历提问的具体技术点、业务难点、成果数据或决策过程。每个项目/实习至少提取 1 个可面试要点。

3. 如果某个字段在简历中没有体现，返回空数组或空字符串，不要编造。

4. 只输出 JSON，不要输出其他解释性文字。

简历文本：
{resume_text}
"""

OPTIMIZE_RESUME_PROMPT = """你是一位资深 HR 和求职顾问。请根据以下【简历模板】的规则，优化用户的简历内容。

模板规则：
{template_rules}

原始简历：
{resume_data}

要求：
1. 严格遵循模板的模块顺序和风格
2. 使用 STAR 法则描述经历
3. 尽量量化成果，如用户数、QPS、转化率、营收等
4. 突出技术深度和业务价值
5. 语言精炼，每段不超过 3 行
6. 不要虚构用户没有的经历或数据

请输出优化后的完整简历 JSON，结构与原始简历一致，字段为：personal, education, experience, projects, skills, summary。
"""

ADAPT_JD_PROMPT = """你是一位岗位匹配专家。请根据以下岗位 JD，分析简历匹配度并给出优化建议。

岗位 JD：
{jd_text}

当前简历：
{resume_data}

请完成：
1. 提取 JD 核心要求（职责、必备技能、加分项、关键词）
2. 分析简历与 JD 的匹配度，指出缺失或薄弱项
3. 针对薄弱项，定向改写相关经历，突出 JD 关键词
4. 输出匹配度评分（0-100）和优化后的简历

约束：
- 不得虚构经历、技能或数据
- 仅做表达重组和重点调整

请输出 JSON 格式：
{{
  "jd_requirements": {{"responsibilities": [], "required_skills": [], "bonus_skills": [], "keywords": []}},
  "match_score": 75,
  "weak_points": [],
  "optimized_resume": {{...}}
}}
"""

GENERATE_QUESTIONS_PROMPT = """你是一位技术/业务面试官。请基于以下简历要点，生成 5 个递进式面试小问题。

要点：{point_title}
要点描述：{point_description}
关联经历：{experience_context}

要求：
1. 5 个问题覆盖：背景、技术细节、决策原因、困难与解决、成果与反思
2. 问题必须基于简历原文，不得引入用户未提及的技能
3. 问题具体、有针对性，避免泛泛而谈
4. 输出 JSON 数组，每个元素包含 question_id（如 p1-q1）和 question_text
"""

SCORE_ANSWER_PROMPT = """你是一位资深面试官。请根据以下题目和用户回答，给出评分和精简答案。

题目：
{question}

用户回答：
{answer}

简历上下文：
{resume_context}

请从以下 5 个维度评分（1-10 分）：
1. completeness（完整性）：是否回答了问题的核心
2. logic（逻辑清晰度）：结构是否清楚
3. consistency（与简历一致性）：是否与简历描述一致
4. conciseness（表达精炼度）：是否简洁不啰嗦
5. depth（技术/业务深度）：是否有深度思考

输出 JSON：
{{
  "scores": {{"completeness": 8, "logic": 7, "consistency": 9, "conciseness": 6, "depth": 7}},
  "total_score": 7.5,
  "feedback": "优点：... 不足：...",
  "refined_answer": "100-200字的精简答案，包含STAR结构和关键词"
}}
"""

SUMMARIZE_INTERVIEW_PROMPT = """你是一位面试辅导专家。请根据以下用户的模拟面试作答记录，生成总结报告。

作答记录：
{questions_and_answers}

请输出 JSON：
{{
  "total_score": 82,
  "dimension_scores": {{"completeness": 8, "logic": 7, "consistency": 9, "conciseness": 6, "depth": 7}},
  "summary": "整体表现总结",
  "weak_points": ["薄弱点1", "薄弱点2", "薄弱点3"],
  "suggestions": ["建议1", "建议2", "建议3"]
}}

语言专业、鼓励性，但指出问题要直接。
"""
