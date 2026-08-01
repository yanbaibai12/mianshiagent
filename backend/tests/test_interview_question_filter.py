import unittest


class InterviewQuestionFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.config import get_settings
        from app.routers import interviews

        get_settings.cache_clear()
        cls.interviews = interviews

    @classmethod
    def tearDownClass(cls):
        from app.config import get_settings

        get_settings.cache_clear()

    def setUp(self):
        self.agent_batch = self.interviews.QuestionBatch(
            module="agent_fundamentals",
            point_id="agent:fundamentals",
            title="Agent 八股：核心能力",
            source_section="核心能力",
            description="围绕 Agent、RAG、工具调用、安全、评测和工程化的基础追问。",
            context="技能列表：Python、FastAPI、Redis、RAG、Agent",
            limit=5,
        )

    def test_filters_system_meta_interview_question(self):
        question = "为什么面试题不能只围绕实习经历生成？你会如何保证项目、实习和技术八股都覆盖？"

        self.assertTrue(self.interviews._is_bad_question(question, self.agent_batch))

    def test_keeps_real_engineering_question_with_how_to_guarantee(self):
        question = "如何保证接口幂等和任务重试不会重复写入？"

        self.assertFalse(self.interviews._is_bad_question(question, self.agent_batch))

    def test_filters_agent_module_design_meta_question(self):
        question = "为什么要设置 Agent 八股模块？"

        self.assertTrue(self.interviews._is_bad_question(question, self.agent_batch))

    def test_keeps_agent_skill_question(self):
        question = "Agent 工具调用失败时如何设计重试、降级和日志记录？"

        self.assertFalse(self.interviews._is_bad_question(question, self.agent_batch))

    def test_merge_drops_meta_questions_and_keeps_candidate_questions(self):
        response_items = [
            {
                "question_id": "bad-1",
                "question_text": "为什么面试题不能只围绕实习经历生成？你会如何保证项目、实习和技术八股都覆盖？",
            },
            {
                "question_id": "good-1",
                "question_text": "Agent 工具调用失败时如何设计重试、降级和日志记录？",
            },
        ]
        fallback_questions = [
            "请拆解 Agent 应用的 RAG 链路：文档清洗、切片、embedding、召回、重排分别怎么做？",
        ]

        merged = self.interviews._merge_question_items(response_items, fallback_questions, 3, batch=self.agent_batch)
        merged_text = "\n".join(item["question_text"] for item in merged)

        self.assertIn("Agent 工具调用失败", merged_text)
        for banned in ("面试题", "出题", "题库", "题型", "覆盖策略", "只围绕实习"):
            self.assertNotIn(banned, merged_text)


if __name__ == "__main__":
    unittest.main()
