import unittest

from app.services.llm_client import LocalLLMClient


class LocalResumeAdaptTest(unittest.TestCase):
    def test_jd_adapt_does_not_rewrite_experience_identity_line(self):
        client = LocalLLMClient()
        identity_line = "围绕业务目标梳理任务、行动与结果：2-2026.4 江西世龙供应管理有限公司 AI开发实习生"
        resume_data = {
            "experience": [
                {
                    "company": "江西世龙供应管理有限公司",
                    "role": "AI开发实习生",
                    "time": "2026.2-2026.4",
                    "highlights": [
                        identity_line,
                        "负责用户认证模块开发，完成注册、登录、权限校验和日志追踪。",
                    ],
                    "interview_points": [
                        {"title": "技术栈", "description": "Python Java React FastAPI Redis"}
                    ],
                }
            ],
            "projects": [],
            "skills": ["Python", "Java", "React", "FastAPI", "Redis"],
        }
        prompt = f"""岗位 JD：熟悉 Python、Java、React、FastAPI、Redis，具备接口联调和优化经验。

当前简历：
{resume_data}

请完成：
"""

        result = client._adapt_jd(prompt)
        optimized_experience = result["optimized_resume"]["experience"][0]
        first_highlight = optimized_experience["highlights"][0]
        change_text = "\n".join(item.get("before", "") + item.get("after", "") for item in result["change_details"])

        self.assertEqual(first_highlight, "2-2026.4 江西世龙供应管理有限公司 AI开发实习生")
        self.assertNotIn("使用 Python", first_highlight)
        self.assertNotIn(identity_line, change_text)

    def test_jd_adapt_change_details_are_not_repeated_templates(self):
        client = LocalLLMClient()
        resume_data = {
            "experience": [
                {
                    "company": "江西世龙供应管理有限公司",
                    "role": "AI开发实习生",
                    "time": "2026.2-2026.4",
                    "highlights": [
                        "使用 Python 完成后端业务逻辑、接口联调和脚本化处理。",
                        "使用 Java 完成服务端模块开发、接口联调和异常处理。",
                        "实现 React 前端表单状态、接口 loading/error 和优化结果对比展示。",
                    ],
                }
            ],
            "projects": [
                {
                    "name": "RAG 简历优化系统",
                    "description": "RAG：掌握文档切分、Embedding、向量存储、向量检索、召回后筛选与补全。",
                    "tech_stack": ["RAG", "Embedding", "Qdrant", "Agent"],
                }
            ],
            "skills": ["Python", "Java", "React", "FastAPI", "RAG", "Embedding", "Qdrant", "Agent"],
        }
        prompt = f"""岗位 JD：熟悉 Python、Java、React、FastAPI、RAG、Embedding、Qdrant、Agent，具备接口联调、异常处理和优化经验。

当前简历：
{resume_data}

请完成：
"""

        result = client._adapt_jd(prompt)
        changes = result["change_details"]
        reasons = [item["reason"] for item in changes]
        after_text = "\n".join(item["after"] for item in changes)

        self.assertGreaterEqual(len(changes), 4)
        self.assertEqual(len(reasons), len(set(reasons)))
        self.assertLessEqual(after_text.count("完成接口设计、参数校验、鉴权联调、异常返回和测试验收"), 1)
        self.assertTrue(any("Python 后端逻辑" in reason for reason in reasons))
        self.assertTrue(any("Java 服务端模块" in reason for reason in reasons))
        self.assertTrue(any("前端状态流转" in reason for reason in reasons))
        self.assertTrue(any("检索、向量化" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
