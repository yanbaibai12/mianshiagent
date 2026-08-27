import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

_DB_PATH = Path(tempfile.gettempdir()) / f"interview_agent_test_{uuid.uuid4().hex}.db"
_BACKUP_DIR = Path(tempfile.gettempdir()) / f"interview_agent_backups_{uuid.uuid4().hex}"
_DB_PATH.unlink(missing_ok=True)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-123456"
os.environ["DEBUG"] = "false"
os.environ["APP_ENV"] = "local"
os.environ["AUTO_CREATE_DB"] = "true"
os.environ["LLM_PROVIDER"] = "local"
os.environ["LLM_ALLOW_FALLBACK"] = "false"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["BACKUP_ENABLED"] = "true"
os.environ["BACKUP_DIR"] = str(_BACKUP_DIR)
os.environ["VECTOR_STORE_BACKEND"] = "keyword"
os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["RERANK_PROVIDER"] = "none"
os.environ["RATE_LIMIT_AUTH_REQUESTS"] = "1000"
os.environ["RATE_LIMIT_API_REQUESTS"] = "5000"
os.environ["AGENT_SHADOW_API_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

settings = get_settings()
from app.main import app  # noqa: E402
from app.services.company_profiles import (  # noqa: E402
    canonicalize_question,
    normalize_company_name,
    normalize_position_name,
    normalize_rounds,
)

SAMPLE_RESUME = """姓名：张三
邮箱：zhangsan@example.com
电话：13800138000
求职意向：后端开发工程师

教育背景
某某大学 计算机科学与技术 本科 2022-2026

专业技能
Python、FastAPI、PostgreSQL、Redis、Docker、React

项目经历
面试简历 Agent 项目 后端负责人 2026.01-2026.06
负责 FastAPI 接口设计、认证鉴权、简历解析、模拟面试题生成和报告导出。
通过 RAG 知识库增强面试评分标准，使用 Qdrant 存储 BGE-M3 向量，并用 BM25 与向量召回的 RRF 排序融合提升问题针对性。

实习经历
某科技公司 后端实习生
参与用户系统开发，负责登录注册、权限校验和日志追踪。
"""


class MainFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        _DB_PATH.unlink(missing_ok=True)
        if _BACKUP_DIR.exists():
            for item in _BACKUP_DIR.glob("*"):
                item.unlink(missing_ok=True)
            _BACKUP_DIR.rmdir()

    def assert_ok(self, response, expected_status=200):
        self.assertEqual(response.status_code, expected_status, response.text)
        return response.json()

    def auth_headers(self, email: str | None = None):
        email = email or f"smoke-{uuid.uuid4().hex}@example.com"
        register = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "nickname": "Smoke"},
        )
        self.assertIn(register.status_code, {200, 400}, register.text)
        login = self.assert_ok(
            self.client.post(
                "/api/auth/login",
                json={"email": email, "password": "password123"},
            )
        )
        return {"Authorization": f"Bearer {login['access_token']}"}

    def test_account_export_delete_and_admin_audit(self):
        user_email = f"privacy-{uuid.uuid4().hex}@example.com"
        headers = self.auth_headers(user_email)

        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=headers,
                json={"title": "账号治理测试", "text": SAMPLE_RESUME},
            )
        )
        self.assertIn("id", resume)

        exported = self.assert_ok(self.client.get("/api/account/export", headers=headers))
        self.assertEqual(exported["user"]["email"], user_email)
        for key in [
            "resumes",
            "interviews",
            "usage_records",
            "audit_logs",
            "quality_annotations",
            "quality_eval_candidates",
        ]:
            self.assertIn(key, exported)
        self.assertEqual(len(exported["resumes"]), 1)
        self.assertTrue(any(record["feature"] == "resume_upload" for record in exported["usage_records"]))
        self.assertIn("organizations", exported)
        self.assertIn("payment_orders", exported)

        forbidden = self.client.get("/api/audit/admin/logs", headers=headers)
        self.assertEqual(forbidden.status_code, 403)

        admin_headers = self.auth_headers("admin@example.com")
        audit_logs = self.assert_ok(
            self.client.get("/api/audit/admin/logs", headers=admin_headers, params={"limit": 200})
        )["logs"]
        event_types = {record["event_type"] for record in audit_logs}
        self.assertIn("auth.login", event_types)
        self.assertIn("resume.upload", event_types)
        self.assertIn("account.export", event_types)

        deleted = self.assert_ok(self.client.delete("/api/account/delete", headers=headers))
        self.assertEqual(deleted["message"], "账号及关联数据已删除")

        missing_user = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(missing_user.status_code, 401)

        post_delete_logs = self.assert_ok(
            self.client.get("/api/audit/admin/logs", headers=admin_headers, params={"limit": 300})
        )["logs"]
        delete_events = [record for record in post_delete_logs if record["event_type"] == "account.delete"]
        self.assertGreaterEqual(len(delete_events), 1)
        self.assertIn("anonymized_user", delete_events[0]["metadata"])
        self.assertNotIn(user_email, json.dumps(post_delete_logs, ensure_ascii=False))

    def test_retired_product_apis_are_unavailable_and_operations_remain_available(self):
        owner_headers = self.auth_headers(f"owner-{uuid.uuid4().hex}@example.com")
        member_headers = self.auth_headers(f"member-{uuid.uuid4().hex}@example.com")
        admin_headers = self.auth_headers("admin@example.com")

        retired_operations = [
            ("GET", "/api/business/admin/usage-summary"),
            ("GET", "/api/business/entitlements"),
            ("POST", "/api/business/admin/grant-plan"),
            ("POST", "/api/business/upgrade-request"),
            ("GET", "/api/company-profiles"),
            ("GET", "/api/company-profiles/00000000-0000-0000-0000-000000000000"),
            ("POST", "/api/company-profiles/rebuild"),
            ("GET", "/api/organizations"),
            ("POST", "/api/organizations"),
            ("GET", "/api/organizations/00000000-0000-0000-0000-000000000000/members"),
            ("POST", "/api/organizations/00000000-0000-0000-0000-000000000000/members"),
            ("GET", "/api/payments/orders"),
            ("POST", "/api/payments/checkout"),
            ("POST", "/api/payments/webhook"),
            ("GET", "/api/quality/annotations"),
            ("POST", "/api/quality/annotations"),
            ("GET", "/api/quality/admin/summary"),
            ("GET", "/api/quality/admin/eval-candidates"),
            ("POST", "/api/quality/admin/eval-candidates/00000000-0000-0000-0000-000000000000/status"),
        ]
        for method, path in retired_operations:
            with self.subTest(operation=f"{method} {path}"):
                response = self.client.request(method, path, headers=owner_headers, json={})
                self.assertEqual(response.status_code, 404, response.text)

        openapi = self.assert_ok(self.client.get("/openapi.json"))
        retired_prefixes = (
            "/api/business",
            "/api/company-profiles",
            "/api/organizations",
            "/api/payments",
            "/api/quality",
        )
        self.assertFalse(
            any(path.startswith(retired_prefixes) for path in openapi["paths"]),
            "Retired product APIs must not remain discoverable in OpenAPI",
        )
        retired_tags = {"business", "company-profiles", "organizations", "payments", "quality"}
        active_tags = {
            tag
            for operation in openapi["paths"].values()
            for item in operation.values()
            for tag in item.get("tags", [])
        }
        self.assertTrue(retired_tags.isdisjoint(active_tags))
        self.assertEqual(self.assert_ok(self.client.get("/health")), {"status": "ok"})

        status_payload = self.assert_ok(self.client.get("/api/system/status", headers=owner_headers))
        self.assertIn("operations", status_payload)
        self.assertTrue(status_payload["operations"]["backup"]["enabled"])
        self.assertIn("metrics", status_payload["operations"])
        self.assertIn("alerting", status_payload["operations"])
        self.assertIn("alerts", status_payload)
        self.assertIn("task_queue_backend", {item["key"] for item in status_payload["release"]["checks"]})
        self.assertIn("qdrant_external", {item["key"] for item in status_payload["release"]["checks"]})
        self.assertIn("alert_webhook", {item["key"] for item in status_payload["release"]["checks"]})

        alerts = self.assert_ok(self.client.get("/api/system/alerts", headers=admin_headers))
        self.assertIn("health", alerts)
        self.assertIn("alerts", alerts)
        notify = self.assert_ok(
            self.client.post(
                "/api/system/admin/alerts/notify",
                headers=admin_headers,
                json={"include_warnings": True},
            )
        )
        self.assertFalse(notify["configured"])
        self.assertEqual(notify["sent_count"], 0)
        self.assertEqual(notify.get("reason"), "alert_webhook_not_configured")

        backup = self.assert_ok(self.client.post("/api/system/admin/backup", headers=admin_headers))
        self.assertTrue(backup["filename"].endswith(".db"))
        self.assertGreater(backup["size_bytes"], 0)

        forbidden_import = self.client.post(
            "/api/knowledge/admin/import-interview-bank",
            headers=member_headers,
            json={"skip_vector": True},
        )
        self.assertEqual(forbidden_import.status_code, 403)

        imported_bank = self.assert_ok(
            self.client.post(
                "/api/knowledge/admin/import-interview-bank",
                headers=admin_headers,
                json={"skip_vector": True},
            )
        )
        self.assertEqual(imported_bank["questions"], 100)
        self.assertGreaterEqual(imported_bank["chunks"], 100)
        self.assertEqual(imported_bank["duplicates_removed"], 0)

        knowledge_stats = self.assert_ok(self.client.get("/api/knowledge/stats", headers=admin_headers))
        self.assertIn("agent_interview_questions", knowledge_stats["categories"])

        recall = self.assert_ok(
            self.client.post(
                "/api/knowledge/search",
                headers=admin_headers,
                json={
                    "query": "RRF 倒数排序 召回失败 项目混合检索",
                    "categories": ["agent_interview_questions"],
                    "limit": 3,
                },
            )
        )
        self.assertGreaterEqual(len(recall["results"]), 1)
        recall_text = json.dumps(recall["results"], ensure_ascii=False)
        self.assertRegex(recall_text, r"RRF|混合检索|召回")
        self.assertIn("metadata", recall["results"][0])

    def test_community_question_bank_and_experience_shares(self):
        headers = self.auth_headers()

        bank = self.assert_ok(
            self.client.get(
                "/api/community/agent-questions",
                headers=headers,
                params={"q": "RRF", "limit": 5},
            )
        )
        self.assertGreaterEqual(bank["total"], 1)
        self.assertGreaterEqual(len(bank["items"]), 1)
        self.assertIn("concise_answer", bank["items"][0])
        self.assertIn("核心回答", bank["items"][0]["concise_answer"])
        self.assertIn("answer_points", bank["items"][0])
        self.assertIn("followups", bank["items"][0])
        self.assertIn("skills", bank["filters"])

        card = self.assert_ok(
            self.client.get(f"/api/community/agent-questions/{bank['items'][0]['id']}", headers=headers)
        )
        self.assertEqual(card["id"], bank["items"][0]["id"])
        self.assertRegex(json.dumps(card, ensure_ascii=False), r"RRF|召回|RAG")
        self.assertIsNone(card["practice_state"])

        profile = self.assert_ok(self.client.get("/api/community/training-profile", headers=headers))
        self.assertEqual(len(profile["dimensions"]), 5)
        self.assertIn("rag", {item["dimension_key"] for item in profile["dimensions"]})

        unknown_state = self.assert_ok(
            self.client.put(
                f"/api/community/agent-questions/{card['id']}/practice",
                headers=headers,
                json={"mastery_status": "unknown"},
            )
        )
        self.assertEqual(unknown_state["mastery_status"], "unknown")
        self.assertTrue(unknown_state["is_wrong"])
        self.assertGreaterEqual(unknown_state["wrong_count"], 1)
        self.assertIsNotNone(unknown_state["next_review_at"])

        wrong_book = self.assert_ok(
            self.client.get(
                "/api/community/agent-questions",
                headers=headers,
                params={"practice_filter": "wrong", "limit": 10},
            )
        )
        self.assertIn(card["id"], {item["id"] for item in wrong_book["items"]})

        favorite_state = self.assert_ok(
            self.client.put(
                f"/api/community/agent-questions/{card['id']}/practice",
                headers=headers,
                json={"is_favorite": True},
            )
        )
        self.assertTrue(favorite_state["is_favorite"])
        favorite_list = self.assert_ok(
            self.client.get(
                "/api/community/agent-questions",
                headers=headers,
                params={"practice_filter": "favorite", "limit": 10},
            )
        )
        self.assertIn(card["id"], {item["id"] for item in favorite_list["items"]})

        known_state = self.assert_ok(
            self.client.put(
                f"/api/community/agent-questions/{card['id']}/practice",
                headers=headers,
                json={"mastery_status": "known"},
            )
        )
        self.assertEqual(known_state["mastery_status"], "known")
        self.assertFalse(known_state["is_wrong"])
        self.assertGreaterEqual(known_state["known_count"], 1)

        profile_after = self.assert_ok(self.client.get("/api/community/training-profile", headers=headers))
        rag_profile = next(item for item in profile_after["dimensions"] if item["dimension_key"] == "rag")
        self.assertGreaterEqual(rag_profile["exposure_count"], 2)
        self.assertGreaterEqual(profile_after["stats"]["practice_count"], 1)

        created = self.assert_ok(
            self.client.post(
                "/api/community/experiences",
                headers=headers,
                json={
                    "company": "示例科技",
                    "position": "AI Agent 应用开发实习生",
                    "city": "上海",
                    "interview_date": "2026-07-20",
                    "rounds": "一面 / 二面 / HR 面",
                    "difficulty": "hard",
                    "result": "offer",
                    "tags": ["RAG", "Agent", "RAG"],
                    "questions": [
                        "如果用户问 RRF 倒数排序，但召回结果偏离，你会怎么排查？",
                        "联系我 13800138000 / test@example.com 不应原样保存。",
                    ],
                    "process": "一面技术深挖，二面项目复盘，HR 面确认到岗时间。",
                    "content": "重点追问 RAG、RRF、工具调用失败降级。联系方式 test@example.com，手机号 13800138000，key sk-test-secret-1234567890。",
                    "visibility": "public",
                    "is_anonymous": True,
                },
            )
        )
        self.assertEqual(created["company"], "示例科技")
        self.assertEqual(created["result"], "offer")
        self.assertEqual(created["tags"], ["RAG", "Agent"])
        self.assertIn("[email_redacted]", created["content"])
        self.assertIn("[phone_redacted]", created["content"])
        self.assertIn("[key_redacted]", created["content"])
        self.assertIn("[phone_redacted]", " ".join(created["questions"]))
        self.assertEqual(created["author_label"], "我（匿名展示）")

        listed = self.assert_ok(
            self.client.get(
                "/api/community/experiences",
                headers=headers,
                params={"q": "RRF", "result": "offer"},
            )
        )
        self.assertGreaterEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["id"], created["id"])

        detail = self.assert_ok(self.client.get(f"/api/community/experiences/{created['id']}", headers=headers))
        self.assertEqual(detail["view_count"], created["view_count"] + 1)
        liked = self.assert_ok(self.client.post(f"/api/community/experiences/{created['id']}/like", headers=headers))
        self.assertEqual(liked["like_count"], detail["like_count"] + 1)

        exported = self.assert_ok(self.client.get("/api/account/export", headers=headers))
        self.assertTrue(any(item["id"] == created["id"] for item in exported["interview_experience_shares"]))
        self.assertTrue(any(item["question_id"] == card["id"] for item in exported["agent_question_practice_states"]))
        self.assertTrue(any(item["dimension_key"] == "rag" for item in exported["training_profile_dimensions"]))

        deleted = self.assert_ok(self.client.delete(f"/api/community/experiences/{created['id']}", headers=headers))
        self.assertEqual(deleted["message"], "删除成功")
        missing = self.client.get(f"/api/community/experiences/{created['id']}", headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_interview_round_templates(self):
        headers = self.auth_headers()

        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=headers,
                json={"title": "多轮模板测试简历", "text": SAMPLE_RESUME},
            )
        )

        templates = self.assert_ok(self.client.get("/api/interviews/templates", headers=headers))
        self.assertEqual(len(templates), 5)
        template_ids = {template["template_id"] for template in templates}
        self.assertEqual(
            template_ids,
            {"technical_first", "project_deep_dive", "system_design", "hr_behavior", "comprehensive"},
        )

        default_interview = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={"resume_id": resume["id"]},
            )
        )
        self.assertEqual(default_interview["interview_template_id"], "comprehensive")
        self.assertEqual(default_interview["interview_template_name"], "综合面")
        self.assertEqual(default_interview["template_config_snapshot"]["template_id"], "comprehensive")

        bank = self.assert_ok(
            self.client.get(
                "/api/community/agent-questions",
                headers=headers,
                params={"q": "RAG", "limit": 1},
            )
        )
        self.assertGreaterEqual(len(bank["items"]), 1)
        self.assert_ok(
            self.client.put(
                f"/api/community/agent-questions/{bank['items'][0]['id']}/practice",
                headers=headers,
                json={"mastery_status": "unknown"},
            )
        )

        technical = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={"resume_id": resume["id"], "template_id": "technical_first"},
            )
        )
        self.assertEqual(technical["interview_template_id"], "technical_first")
        technical_generated = self.assert_ok(
            self.client.post(f"/api/interviews/{technical['id']}/generate-questions", headers=headers)
        )
        self.assertEqual(technical_generated["template"]["template_id"], "technical_first")
        self.assertGreaterEqual(len(technical_generated["training_focus"]), 1)
        technical_questions = self.assert_ok(
            self.client.get(f"/api/interviews/{technical['id']}/questions", headers=headers)
        )
        technical_modules = [question["module"] for question in technical_questions]
        self.assertIn("agent_fundamentals", technical_modules)
        self.assertGreaterEqual(
            technical_modules.count("agent_fundamentals"),
            technical_modules.count("project"),
        )

        hr = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={"resume_id": resume["id"], "template_id": "hr_behavior"},
            )
        )
        hr_generated = self.assert_ok(
            self.client.post(f"/api/interviews/{hr['id']}/generate-questions", headers=headers)
        )
        self.assertEqual(hr_generated["template"]["template_id"], "hr_behavior")
        self.assertEqual(hr_generated["training_focus"], [])
        hr_questions = self.assert_ok(self.client.get(f"/api/interviews/{hr['id']}/questions", headers=headers))
        hr_modules = [question["module"] for question in hr_questions]
        self.assertIn("behavioral", hr_modules)
        self.assertNotEqual(set(hr_modules), {"agent_fundamentals"})
        self.assertGreater(hr_modules.count("behavioral"), hr_modules.count("agent_fundamentals"))
        self.assertNotEqual(technical_modules, hr_modules)

    def test_historical_company_profile_snapshot_feeds_interview_generation(self):
        owner_headers = self.auth_headers()
        other_headers = self.auth_headers()
        company_base = f"画像测试{uuid.uuid4().hex[:8]}科技"

        self.assertEqual(normalize_company_name(f"{company_base}有限公司"), normalize_company_name(company_base))
        self.assertEqual(normalize_position_name("AI Agent 开发工程师"), normalize_position_name("智能体开发工程师"))
        self.assertEqual(normalize_rounds("技术初面 / 系统设计 / HR 面")[0]["round_type"], "technical_first")
        self.assertEqual(canonicalize_question("请说一下检索增强生成的召回率如何评估？"), "RAG的召回率如何评估")

        eligible_shares = [
            {
                "company": f"{company_base}有限公司",
                "position": "AI Agent 开发工程师",
                "rounds": "技术初面 / 系统设计",
                "difficulty": "hard",
                "result": "passed",
                "tags": ["RAG", "工程化"],
                "questions": ["请说一下检索增强生成的召回率如何评估？"],
                "content": "重点考察 RAG 召回、重排、可观测性和上线后的质量评测。",
                "visibility": "public",
                "is_anonymous": True,
                "allow_profile_usage": True,
            },
            {
                "company": company_base,
                "position": "智能体开发工程师",
                "rounds": "系统设计 / HR 面",
                "difficulty": "medium",
                "result": "offer",
                "tags": ["RAG", "Tool Calling"],
                "questions": ["RAG 的召回率应该如何评估？"],
                "content": "讨论检索指标、工具调用参数校验和失败降级。",
                "visibility": "public",
                "is_anonymous": True,
                "allow_profile_usage": True,
            },
            {
                "company": company_base,
                "position": "AI Agent 开发工程师",
                "rounds": "系统设计",
                "difficulty": "hard",
                "result": "passed",
                "tags": ["系统设计", "工程化"],
                "questions": ["如何设计可观测、可扩展的 Agent 检索与工具调用链路？"],
                "content": "系统设计轮重点讨论数据流、降级、监控、容量和稳定性。",
                "visibility": "public",
                "is_anonymous": True,
                "allow_profile_usage": True,
            },
        ]
        for payload in eligible_shares:
            created = self.assert_ok(
                self.client.post("/api/community/experiences", headers=owner_headers, json=payload)
            )
            self.assertTrue(created["allow_profile_usage"])

        excluded_shares = [
            {
                "company": company_base,
                "position": "AI Agent 开发工程师",
                "rounds": "项目深挖",
                "difficulty": "hard",
                "result": "unknown",
                "tags": ["private-only-marker"],
                "questions": ["private-only-marker secret@example.com"],
                "content": "private-only-marker 13800138000",
                "visibility": "private",
                "is_anonymous": False,
                "allow_profile_usage": True,
            },
            {
                "company": company_base,
                "position": "AI Agent 开发工程师",
                "rounds": "项目深挖",
                "difficulty": "medium",
                "result": "passed",
                "tags": ["opt-out-only-marker"],
                "questions": ["opt-out-only-marker"],
                "content": "opt-out-only-marker secret@example.com 13800138000",
                "visibility": "public",
                "is_anonymous": True,
                "allow_profile_usage": False,
            },
        ]
        for payload in excluded_shares:
            self.assert_ok(self.client.post("/api/community/experiences", headers=other_headers, json=payload))

        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=owner_headers,
                json={"title": "公司画像面试简历", "text": SAMPLE_RESUME},
            )
        )
        interview = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=owner_headers,
                json={
                    "resume_id": resume["id"],
                    "template_id": "technical_first",
                    "target_company": company_base,
                    "target_position": "AI Agent 开发工程师",
                },
            )
        )
        self.assertIsNotNone(interview["company_profile_id"])
        self.assertEqual(interview["company_profile_snapshot"]["source_count"], 3)
        snapshot_json = json.dumps(interview["company_profile_snapshot"], ensure_ascii=False)
        for excluded_value in (
            "private-only-marker",
            "opt-out-only-marker",
            "secret@example.com",
            "13800138000",
        ):
            self.assertNotIn(excluded_value, snapshot_json)

        generated = self.assert_ok(
            self.client.post(f"/api/interviews/{interview['id']}/generate-questions", headers=owner_headers)
        )
        self.assertEqual(generated["company_profile"]["source_count"], 3)
        self.assertEqual(generated["company_module_bias"]["target_module"], "system_design")
        generated_questions = self.assert_ok(
            self.client.get(f"/api/interviews/{interview['id']}/questions", headers=owner_headers)
        )
        self.assertTrue(any(question["question_quality"].get("company_profile") for question in generated_questions))
        self.assertGreaterEqual(sum(question["module"] == "system_design" for question in generated_questions), 2)

        fallback = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=owner_headers,
                json={
                    "resume_id": resume["id"],
                    "target_company": f"不存在公司{uuid.uuid4().hex[:6]}",
                    "target_position": "后端开发",
                },
            )
        )
        self.assertIsNone(fallback["company_profile_id"])
        self.assertEqual(fallback["company_profile_snapshot"], {})

    def test_resume_to_report_flow(self):
        headers = self.auth_headers()

        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=headers,
                json={"title": "后端校招版", "text": SAMPLE_RESUME},
            )
        )
        self.assertIn("parsed_data", resume)

        chunks = self.assert_ok(self.client.get(f"/api/resumes/{resume['id']}/chunks", headers=headers))
        self.assertGreaterEqual(len(chunks), 3)
        sections = {chunk["section"] for chunk in chunks}
        self.assertIn("project", sections)
        self.assertIn("experience", sections)
        self.assertIn("skills", sections)

        admin_headers = self.auth_headers("admin@example.com")
        reindex_all = self.assert_ok(
            self.client.post(
                "/api/system/admin/reindex-resumes",
                headers=admin_headers,
                json={"only_missing": False, "limit": 20},
            )
        )
        self.assertIn(reindex_all["status"], {"success", "partial_failed"})
        self.assertGreaterEqual(reindex_all["processed_count"], 1)
        self.assertGreaterEqual(reindex_all["chunk_count"], 3)

        evidence = self.assert_ok(
            self.client.post(
                f"/api/resumes/{resume['id']}/retrieve-evidence",
                headers=headers,
                json={"jd_text": "FastAPI Redis RAG Qdrant 接口优化"},
            )
        )
        self.assertIn("results", evidence)
        self.assertGreaterEqual(len(evidence["results"]), 1)
        self.assertEqual(evidence["pipeline"]["fusion"], "rrf")

        templates = self.assert_ok(self.client.get("/api/templates", headers=headers))
        self.assertGreaterEqual(len(templates), 1)

        optimized = self.assert_ok(
            self.client.post(
                f"/api/resumes/{resume['id']}/optimize",
                headers=headers,
                json={"template_id": templates[0]["id"]},
            )
        )
        self.assertEqual(optimized["template_id"], templates[0]["id"])

        adapted_task_payload = self.assert_ok(
            self.client.post(
                f"/api/resumes/{resume['id']}/adapt-jd",
                headers=headers,
                json={"jd_text": "岗位要求：熟悉 Python、FastAPI、Redis、PostgreSQL，具备接口设计经验。"},
            ),
            expected_status=202,
        )
        adapted_task_id = adapted_task_payload["task"]["id"]
        adapted_task = adapted_task_payload["task"]
        for _ in range(10):
            adapted_task = self.assert_ok(self.client.get(f"/api/tasks/{adapted_task_id}", headers=headers))
            if adapted_task["status"] in {"success", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        self.assertEqual(adapted_task["status"], "success", adapted_task)
        adapted_resume = self.assert_ok(self.client.get(f"/api/resumes/{resume['id']}", headers=headers))
        adapted = adapted_resume["optimized_data"]
        self.assertIn("ats_report", adapted)
        self.assertGreater(adapted["ats_report"]["total_score"], 0)
        self.assertGreaterEqual(len(adapted["ats_report"]["dimensions"]), 6)
        self.assertIn("resume_evidence", adapted)
        self.assertNotIn("面向该 JD", json.dumps(adapted, ensure_ascii=False))
        self.assertNotIn("jd_alignment", adapted)
        self.assertGreaterEqual(len(adapted.get("change_details") or []), 1)
        changed_text = json.dumps(adapted.get("change_details") or [], ensure_ascii=False)
        self.assertRegex(changed_text, r"负责|参与|完成|实现|使用|联调|交付|验证")
        self.assertRegex(changed_text, r"FastAPI|Redis|PostgreSQL|接口")
        self.assertNotRegex(changed_text, r"建议|进一步明确|可重点呈现|面向该 JD|岗位要求|本地 MVP|应该覆盖|基础题型")

        versions = self.assert_ok(self.client.get(f"/api/resumes/{resume['id']}/versions", headers=headers))
        self.assertGreaterEqual(len(versions), 2)
        delivery = self.assert_ok(self.client.post(f"/api/resumes/{resume['id']}/versions/delivery", headers=headers))
        self.assertEqual(delivery["version_type"], "delivery")
        exported_resume = self.client.get(
            f"/api/resumes/{resume['id']}/export", headers=headers, params={"variant": "delivery"}
        )
        self.assertEqual(exported_resume.status_code, 200, exported_resume.text)
        self.assertGreater(len(exported_resume.content), 1000)

        task_payload = self.assert_ok(
            self.client.post(
                f"/api/resumes/{resume['id']}/adapt-jd-task",
                headers=headers,
                json={"jd_text": "岗位要求：Python FastAPI Redis RAG Agent 接口优化"},
            )
        )
        task_id = task_payload["task"]["id"]
        task = task_payload["task"]
        for _ in range(10):
            task = self.assert_ok(self.client.get(f"/api/tasks/{task_id}", headers=headers))
            if task["status"] in {"success", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        self.assertEqual(task["status"], "success", task)

        job = self.assert_ok(
            self.client.post(
                "/api/jobs",
                headers=headers,
                json={
                    "title": "Agent 应用开发实习生",
                    "company": "示例科技",
                    "jd_text": "岗位要求：熟悉 Python、FastAPI、Redis、RAG、Agent，具备接口联调和优化经验。",
                    "resume_id": resume["id"],
                },
            )
        )
        preflight_job = self.assert_ok(self.client.post(f"/api/jobs/{job['id']}/preflight", headers=headers))
        self.assertGreater(preflight_job["match_score"], 0)
        review = (preflight_job["ats_report"] or {}).get("application_review") or {}
        self.assertIn(review.get("decision"), {"apply_now", "revise_before_apply", "low_priority", "not_recommended"})
        self.assertIn("actions_before_apply", review)
        self.assertIn("reviewer_checks", review)
        self.assertNotIn("jd_text", json.dumps(review, ensure_ascii=False))

        job_task_payload = self.assert_ok(self.client.post(f"/api/jobs/{job['id']}/adapt-resume-task", headers=headers))
        job_task_id = job_task_payload["task"]["id"]
        job_task = job_task_payload["task"]
        for _ in range(10):
            job_task = self.assert_ok(self.client.get(f"/api/tasks/{job_task_id}", headers=headers))
            if job_task["status"] in {"success", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        self.assertEqual(job_task["status"], "success", job_task)
        job_after = self.assert_ok(self.client.get(f"/api/jobs/{job['id']}", headers=headers))
        self.assertEqual(job_after["status"], "optimized")
        self.assertIsNotNone(job_after["current_resume_version_id"])
        optimized_review = (job_after["ats_report"] or {}).get("application_review") or {}
        self.assertIn(
            optimized_review.get("decision"), {"apply_now", "revise_before_apply", "low_priority", "not_recommended"}
        )
        self.assertGreaterEqual(len(optimized_review.get("reviewer_checks") or []), 3)

        interview = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={"resume_id": resume["id"]},
            )
        )
        self.assertIn("Python", interview.get("jd_text") or "")
        self.assertIn("Redis", interview.get("jd_text") or "")

        generated = self.assert_ok(
            self.client.post(f"/api/interviews/{interview['id']}/generate-questions", headers=headers)
        )
        self.assertGreaterEqual(generated["count"], 5)

        questions = self.assert_ok(self.client.get(f"/api/interviews/{interview['id']}/questions", headers=headers))
        self.assertGreaterEqual(len(questions), 3)
        point_titles = [question.get("point_title") or "" for question in questions]
        modules = {question.get("module") for question in questions}
        question_types = {question.get("question_type") for question in questions}
        question_text = "\n".join(question.get("question") or "" for question in questions)
        self.assertTrue(any(title.startswith("项目：") for title in point_titles), point_titles)
        self.assertTrue(any(title.startswith("实习：") for title in point_titles), point_titles)
        self.assertTrue(any(title.startswith("Agent 八股：") for title in point_titles), point_titles)
        self.assertIn("project", modules)
        self.assertIn("internship", modules)
        self.assertIn("agent_fundamentals", modules)
        self.assertTrue(all(question.get("source_section") is not None for question in questions))
        self.assertTrue(all(question.get("question_quality") for question in questions))
        self.assertTrue(any(question.get("evidence") for question in questions))
        evidence_text = json.dumps([question.get("evidence") for question in questions], ensure_ascii=False)
        self.assertRegex(evidence_text, r"source_section|source_title|source_snippet")
        self.assertIn("agent_fundamentals", question_types)
        self.assertRegex(question_text, r"RAG|FastAPI|Redis|PostgreSQL|Agent|Qdrant|BGE-M3")
        self.assertRegex(question_text, r"RRF|混合检索|BM25")
        self.assertNotIn("面向该 JD", question_text)
        self.assertEqual(len({question.get("question") for question in questions}), len(questions))
        self.assertNotRegex(question_text, r"技术栈模块|模块改成|改成传统|基础题型|应该覆盖哪些|覆盖哪些题型|题库模块")

        regenerated = self.assert_ok(
            self.client.post(
                f"/api/interviews/{interview['id']}/regenerate-question",
                headers=headers,
                params={"question_id": questions[0]["id"]},
            )
        )
        self.assertEqual(regenerated["id"], questions[0]["id"])

        answer_text = (
            "背景是项目需要完成简历解析到面试复盘的闭环。"
            "我负责接口设计、数据建模和 RAG 检索接入，"
            "通过结构化数据生成问题并保存评分结果，后续补充真实模型评测和成本监控。"
        )
        for question in questions[:3]:
            scored = self.assert_ok(
                self.client.post(
                    f"/api/interviews/{interview['id']}/questions/{question['id']}/answer",
                    headers=headers,
                    json={"answer": answer_text},
                )
            )
            self.assertIsNotNone(scored["total_score"])
            self.assertIn("technical_accuracy", scored["scores"])
            self.assertIn("engineering_delivery", scored["scores"])
            self.assertIn("reflection", scored["scores"])
            self.assertIn("technical_accuracy", scored["score_details"])
            self.assertIn("issue", scored["score_details"]["technical_accuracy"])
            self.assertIn("suggestion", scored["score_details"]["technical_accuracy"])

        report = self.assert_ok(self.client.post(f"/api/interviews/{interview['id']}/finish", headers=headers))
        self.assertGreater(report["total_score"], 0)
        self.assertIn("technical_accuracy", report["dimension_scores"])
        self.assertIn("troubleshooting", report["dimension_scores"])
        self.assertIn("engineering_delivery", report["dimension_scores"])
        self.assertIn(report["report_details"]["hire_signal"], {"strong", "positive", "borderline", "weak"})
        self.assertIn("module_scores", report["report_details"])
        self.assertIn("follow_up_training_plan", report["report_details"])

        exported = self.assert_ok(self.client.get(f"/api/interviews/{interview['id']}/report/export", headers=headers))
        self.assertTrue(exported["filename"].endswith(".md"))
        self.assertIn("面试总结报告", exported["content"])
        exported_docx = self.client.get(
            f"/api/interviews/{interview['id']}/report/export", headers=headers, params={"format": "docx"}
        )
        self.assertEqual(exported_docx.status_code, 200, exported_docx.text)
        self.assertGreater(len(exported_docx.content), 1000)
        exported_pdf = self.client.get(
            f"/api/interviews/{interview['id']}/report/export", headers=headers, params={"format": "pdf"}
        )
        self.assertEqual(exported_pdf.status_code, 200, exported_pdf.text)
        self.assertGreater(len(exported_pdf.content), 500)

        deleted = self.assert_ok(self.client.delete(f"/api/interviews/{interview['id']}", headers=headers))
        self.assertEqual(deleted["message"], "删除成功")
        missing = self.client.get(f"/api/interviews/{interview['id']}", headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_agent_shadow_api_enforces_real_resource_ownership_idempotency_and_redaction(self):
        from app.routers import agent_shadow as agent_shadow_router

        registry_path = Path(__file__).resolve().parents[2] / "quality" / "mcp-tool-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(registry["status"], "active")
        for item in registry["tools"]:
            tool = agent_shadow_router.agent_shadow_runtime.harness.gateway.get(item["name"])
            self.assertEqual(tool.version, item["version"])
            self.assertEqual(tool.allowed_agents, frozenset(item["allowed_agents"]))
            self.assertEqual(tool.required_arguments, frozenset(item["required_arguments"]))
            self.assertEqual(tool.output_fields, frozenset(item["output_fields"]))
            self.assertEqual(tool.risk_level.value, item["risk_level"])
            self.assertIs(tool.read_only, item["read_only"])
            self.assertIs(tool.requires_approval, item["requires_approval"])

        owner_headers = self.auth_headers()
        other_headers = self.auth_headers()
        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=owner_headers,
                json={"title": "Shadow Runtime Resume", "text": SAMPLE_RESUME},
            )
        )
        payload = {
            "objective": "基于真实证据生成岗位定向改写建议",
            "input": {
                "mode": "resume-rewrite",
                "resume_id": resume["id"],
                "jd_text": "需要 Python、FastAPI、PostgreSQL、Redis、Docker 和 Agent 工程经验",
            },
        }
        headers = {**owner_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"}
        created = self.assert_ok(self.client.post("/api/agent-shadow/runs", headers=headers, json=payload))
        self.assertEqual(created["status"], "completed")
        self.assertEqual(created["output"]["agent"], "resume-rewriter")
        self.assertTrue(created["output"]["fact_safe"])
        self.assertGreater(created["output"]["evidence_claim_count"], 0)
        self.assertNotIn("state", created["checkpoint"])
        self.assertNotIn("last_tool_result", json.dumps(created, ensure_ascii=False))
        self.assertNotIn("request_fingerprint", created)
        self.assertNotIn("idempotency_key", created)

        repeated = self.assert_ok(self.client.post("/api/agent-shadow/runs", headers=headers, json=payload))
        self.assertEqual(repeated["id"], created["id"])
        self.assertEqual(len(repeated["steps"]), len(created["steps"]))

        changed_budget = {**payload, "budget": {"max_steps": 10}}
        conflict = self.client.post("/api/agent-shadow/runs", headers=headers, json=changed_budget)
        self.assertEqual(conflict.status_code, 409, conflict.text)

        owned = self.assert_ok(self.client.get(f"/api/agent-shadow/runs/{created['id']}", headers=owner_headers))
        self.assertEqual(owned["id"], created["id"])
        self.assertEqual(
            self.client.get(f"/api/agent-shadow/runs/{created['id']}", headers=other_headers).status_code,
            404,
        )
        cancelled_terminal = self.assert_ok(
            self.client.post(f"/api/agent-shadow/runs/{created['id']}/cancel", headers=owner_headers)
        )
        self.assertEqual(cancelled_terminal["status"], "completed")
        self.assertEqual(
            self.client.post(f"/api/agent-shadow/runs/{created['id']}/retry", headers=owner_headers).status_code,
            409,
        )

        denied_payload = {
            "objective": "读取不属于当前用户的简历",
            "input": {"mode": "resume", "resume_id": resume["id"]},
        }
        denied_headers = {**other_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"}
        denied = self.assert_ok(self.client.post("/api/agent-shadow/runs", headers=denied_headers, json=denied_payload))
        missing_headers = {**other_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"}
        missing = self.assert_ok(
            self.client.post(
                "/api/agent-shadow/runs",
                headers=missing_headers,
                json={
                    "objective": denied_payload["objective"],
                    "input": {"mode": "resume", "resume_id": str(uuid.uuid4())},
                },
            )
        )
        for response in (denied, missing):
            self.assertEqual(response["status"], "failed")
            self.assertEqual(response["error_code"], "execution_failed")
            self.assertEqual(response["output"], {})
            self.assertNotIn("DomainResourceAccessError", json.dumps(response, ensure_ascii=False))
        self.assertEqual(
            (denied["status"], denied["error_code"], denied["output"]),
            (missing["status"], missing["error_code"], missing["output"]),
        )

        first_retry = self.assert_ok(
            self.client.post(f"/api/agent-shadow/runs/{denied['id']}/retry", headers=other_headers)
        )
        second_retry = self.assert_ok(
            self.client.post(f"/api/agent-shadow/runs/{denied['id']}/retry", headers=other_headers)
        )
        self.assertEqual(first_retry["attempts"], 2)
        self.assertEqual(second_retry["attempts"], 3)
        self.assertEqual(
            self.client.post(f"/api/agent-shadow/runs/{denied['id']}/retry", headers=other_headers).status_code,
            409,
        )

        interview = self.assert_ok(
            self.client.post("/api/interviews", headers=owner_headers, json={"resume_id": resume["id"]})
        )
        self.assert_ok(self.client.post(f"/api/interviews/{interview['id']}/generate-questions", headers=owner_headers))
        interview_shadow = self.assert_ok(
            self.client.post(
                "/api/agent-shadow/runs",
                headers={**owner_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"},
                json={
                    "objective": "根据当前面试题评估回答结构",
                    "input": {
                        "mode": "interview",
                        "interview_id": interview["id"],
                        "answer": "I designed the workflow, measured the result, and documented the rollback tradeoff.",
                    },
                },
            )
        )
        self.assertEqual(interview_shadow["status"], "completed")
        self.assertEqual(interview_shadow["output"]["agent"], "interview-coach")
        self.assertGreater(len(interview_shadow["output"]["questions"]), 0)

        invalid = self.client.post(
            "/api/agent-shadow/runs",
            headers={**owner_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"},
            json={"objective": "invalid", "input": {"mode": "resume"}},
        )
        self.assertEqual(invalid.status_code, 422)
        openapi = self.assert_ok(self.client.get("/openapi.json"))
        self.assertNotIn("/api/agent-shadow/runs", openapi["paths"])

        original_enabled = agent_shadow_router.settings.AGENT_SHADOW_API_ENABLED
        try:
            agent_shadow_router.settings.AGENT_SHADOW_API_ENABLED = False
            disabled = self.client.post(
                "/api/agent-shadow/runs",
                headers={**owner_headers, "Idempotency-Key": f"shadow-{uuid.uuid4().hex}"},
                json=payload,
            )
            self.assertEqual(disabled.status_code, 404)
        finally:
            agent_shadow_router.settings.AGENT_SHADOW_API_ENABLED = original_enabled

    def test_core_resume_flow_has_no_commercial_entitlement_dependency(self):
        headers = self.auth_headers(f"core-flow-{uuid.uuid4().hex}@example.com")
        response = self.client.post(
            "/api/resumes/upload",
            headers=headers,
            json={"title": "核心简历流程", "text": SAMPLE_RESUME},
        )

        resume = self.assert_ok(response)
        self.assertIn("id", resume)
        self.assertIn("parsed_data", resume)
        self.assertEqual(self.client.get("/api/business/entitlements", headers=headers).status_code, 404)

    def test_training_plan_closed_loop_and_tenant_isolation(self):
        headers = self.auth_headers()
        other_headers = self.auth_headers()
        company = f"训练计划{uuid.uuid4().hex[:8]}科技"

        bank = self.assert_ok(
            self.client.get(
                "/api/community/agent-questions",
                headers=headers,
                params={"q": "RAG", "limit": 1},
            )
        )
        question_id = bank["items"][0]["id"]
        self.assert_ok(
            self.client.put(
                f"/api/community/agent-questions/{question_id}/practice",
                headers=headers,
                json={"mastery_status": "unknown", "is_favorite": True},
            )
        )
        self.assert_ok(
            self.client.post(
                "/api/community/experiences",
                headers=headers,
                json={
                    "company": company,
                    "position": "AI Agent 开发工程师",
                    "rounds": "技术一面 / 项目深挖",
                    "difficulty": "medium",
                    "result": "passed",
                    "tags": ["RAG", "工程化"],
                    "questions": ["如何评估 RAG 召回率并定位噪声来源？"],
                    "content": "技术一面关注 RAG 检索质量，项目轮关注个人贡献与故障复盘。",
                    "visibility": "public",
                    "is_anonymous": True,
                    "allow_profile_usage": True,
                },
            )
        )
        resume = self.assert_ok(
            self.client.post(
                "/api/resumes/upload",
                headers=headers,
                json={"title": "训练计划测试简历", "text": SAMPLE_RESUME},
            )
        )
        interview = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={
                    "resume_id": resume["id"],
                    "template_id": "technical_first",
                    "target_company": company,
                    "target_position": "AI Agent 开发工程师",
                },
            )
        )
        self.assertEqual(interview["status"], "ongoing")

        plan = self.assert_ok(
            self.client.post(
                "/api/training-plans/generate",
                headers=headers,
                json={"source_interview_id": interview["id"]},
            )
        )
        self.assertEqual(
            date.fromisoformat(plan["week_end"]) - date.fromisoformat(plan["week_start"]),
            timedelta(days=6),
        )
        task_types = {task["task_type"] for task in plan["tasks"]}
        self.assertTrue({"wrong_review", "mock_interview", "project_review", "experience_reading"}.issubset(task_types))
        daily_minutes = {}
        for task in plan["tasks"]:
            if task["status"] != "skipped":
                daily_minutes[task["scheduled_date"]] = (
                    daily_minutes.get(task["scheduled_date"], 0) + task["estimated_minutes"]
                )
        self.assertTrue(daily_minutes)
        self.assertLessEqual(max(daily_minutes.values()), 45)

        repeated = self.assert_ok(
            self.client.post(
                "/api/training-plans/generate",
                headers=headers,
                json={"source_interview_id": interview["id"]},
            )
        )
        self.assertEqual(repeated["id"], plan["id"])

        forbidden = self.client.get(f"/api/training-plans/{plan['id']}", headers=other_headers)
        self.assertEqual(forbidden.status_code, 404, forbidden.text)

        wrong_task = next(task for task in plan["tasks"] if task["task_type"] == "wrong_review")
        completed = self.assert_ok(
            self.client.patch(
                f"/api/training-plans/{plan['id']}/tasks/{wrong_task['id']}",
                headers=headers,
                json={"status": "completed"},
            )
        )
        self.assertGreater(completed["completion_rate"], 0)
        completed_task = next(task for task in completed["tasks"] if task["id"] == wrong_task["id"])
        self.assertEqual(completed_task["status"], "completed")

        profile = self.assert_ok(self.client.get("/api/community/training-profile", headers=headers))
        self.assertTrue(any(item["known_count"] > 0 for item in profile["dimensions"]))

        outside_week = (date.fromisoformat(plan["week_end"]) + timedelta(days=1)).isoformat()
        invalid_move = self.client.patch(
            f"/api/training-plans/{plan['id']}/tasks/{wrong_task['id']}",
            headers=headers,
            json={"scheduled_date": outside_week},
        )
        self.assertEqual(invalid_move.status_code, 400, invalid_move.text)

        regenerated = self.assert_ok(self.client.post(f"/api/training-plans/{plan['id']}/regenerate", headers=headers))
        preserved = next(task for task in regenerated["tasks"] if task["id"] == wrong_task["id"])
        self.assertEqual(preserved["status"], "completed")
        serialized = json.dumps(regenerated, ensure_ascii=False)
        for secret in ("13800138000", "zhangsan@example.com", "sk-test-secret"):
            self.assertNotIn(secret, serialized)

    def test_training_plan_concurrent_generation_is_idempotent(self):
        headers = self.auth_headers()
        request_count = 4
        barrier = threading.Barrier(request_count)

        def generate():
            barrier.wait(timeout=10)
            return self.client.post(
                "/api/training-plans/generate",
                headers=headers,
                json={},
            )

        with ThreadPoolExecutor(max_workers=request_count) as executor:
            responses = list(executor.map(lambda _index: generate(), range(request_count)))

        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
        payloads = [response.json() for response in responses]
        self.assertEqual(len({payload["id"] for payload in payloads}), 1)
        self.assertTrue(all(payload["tasks"] for payload in payloads))

        current = self.assert_ok(self.client.get("/api/training-plans/current", headers=headers))
        self.assertEqual(current["id"], payloads[0]["id"])
        exported = self.assert_ok(self.client.get("/api/account/export", headers=headers))
        self.assertEqual(len(exported["training_plans"]), 1)
        generation_usage = [
            record for record in exported["usage_records"] if record["feature"] == "training_plan_generate"
        ]
        self.assertEqual(len(generation_usage), 1)


if __name__ == "__main__":
    unittest.main()
