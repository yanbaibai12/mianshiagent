import json
import hashlib
import hmac
import os
import time
import tempfile
import unittest
import uuid
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
os.environ["PAYMENT_WEBHOOK_SECRET"] = "unit-test-webhook-secret"
os.environ["BACKUP_ENABLED"] = "true"
os.environ["BACKUP_DIR"] = str(_BACKUP_DIR)
os.environ["VECTOR_STORE_BACKEND"] = "keyword"
os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["RERANK_PROVIDER"] = "none"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


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
通过 RAG 知识库增强面试评分标准，提升问题针对性。

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
        for key in ["resumes", "interviews", "usage_records", "audit_logs"]:
            self.assertIn(key, exported)
        self.assertEqual(len(exported["resumes"]), 1)
        self.assertTrue(any(record["feature"] == "resume_upload" for record in exported["usage_records"]))
        self.assertIn("organizations", exported)
        self.assertIn("payment_orders", exported)

        forbidden = self.client.get("/api/audit/admin/logs", headers=headers)
        self.assertEqual(forbidden.status_code, 403)

        admin_headers = self.auth_headers("admin@example.com")
        audit_logs = self.assert_ok(self.client.get("/api/audit/admin/logs", headers=admin_headers, params={"limit": 200}))["logs"]
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

    def test_organizations_payment_webhook_and_operations(self):
        owner_email = f"owner-{uuid.uuid4().hex}@example.com"
        member_email = f"member-{uuid.uuid4().hex}@example.com"
        owner_headers = self.auth_headers(owner_email)
        member_headers = self.auth_headers(member_email)
        admin_headers = self.auth_headers("admin@example.com")

        orgs = self.assert_ok(self.client.get("/api/organizations", headers=owner_headers))["organizations"]
        self.assertGreaterEqual(len(orgs), 1)

        org = self.assert_ok(
            self.client.post("/api/organizations", headers=owner_headers, json={"name": "校招训练团队"})
        )
        self.assertEqual(org["role"], "owner")

        invited = self.assert_ok(
            self.client.post(
                f"/api/organizations/{org['id']}/members",
                headers=owner_headers,
                json={"email": member_email, "role": "member"},
            )
        )
        self.assertEqual(invited["email"], member_email)
        self.assertEqual(invited["role"], "member")

        forbidden = self.client.post(
            f"/api/organizations/{org['id']}/members",
            headers=member_headers,
            json={"email": owner_email, "role": "admin"},
        )
        self.assertEqual(forbidden.status_code, 403)

        checkout = self.assert_ok(
            self.client.post("/api/payments/checkout", headers=owner_headers, json={"plan": "pro", "billing_cycle": "monthly"})
        )
        self.assertEqual(checkout["plan"], "pro")
        self.assertIn(checkout["status"], {"pending", "pending_manual"})

        payload = {
            "order_id": checkout["order_id"],
            "status": "paid",
            "provider_order_id": f"gateway-{uuid.uuid4().hex}",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(b"unit-test-webhook-secret", raw, hashlib.sha256).hexdigest()
        webhook = self.assert_ok(
            self.client.post(
                "/api/payments/webhook",
                content=raw,
                headers={"content-type": "application/json", "x-payment-signature": signature},
            )
        )
        self.assertEqual(webhook["plan"], "pro")

        entitlements = self.assert_ok(self.client.get("/api/business/entitlements", headers=owner_headers))
        self.assertEqual(entitlements["plan"]["current"], "pro")

        status_payload = self.assert_ok(self.client.get("/api/system/status", headers=owner_headers))
        self.assertIn("operations", status_payload)
        self.assertTrue(status_payload["operations"]["backup"]["enabled"])
        self.assertIn("metrics", status_payload["operations"])

        backup = self.assert_ok(self.client.post("/api/system/admin/backup", headers=admin_headers))
        self.assertTrue(backup["filename"].endswith(".db"))
        self.assertGreater(backup["size_bytes"], 0)

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

        versions = self.assert_ok(self.client.get(f"/api/resumes/{resume['id']}/versions", headers=headers))
        self.assertGreaterEqual(len(versions), 2)
        delivery = self.assert_ok(self.client.post(f"/api/resumes/{resume['id']}/versions/delivery", headers=headers))
        self.assertEqual(delivery["version_type"], "delivery")
        exported_resume = self.client.get(f"/api/resumes/{resume['id']}/export", headers=headers, params={"variant": "delivery"})
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

        interview = self.assert_ok(
            self.client.post(
                "/api/interviews",
                headers=headers,
                json={"resume_id": resume["id"]},
            )
        )

        generated = self.assert_ok(
            self.client.post(f"/api/interviews/{interview['id']}/generate-questions", headers=headers)
        )
        self.assertGreaterEqual(generated["count"], 5)

        questions = self.assert_ok(
            self.client.get(f"/api/interviews/{interview['id']}/questions", headers=headers)
        )
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
        self.assertIn("agent_fundamentals", question_types)
        self.assertRegex(question_text, r"RAG|FastAPI|Redis|PostgreSQL|Agent|Qdrant|BGE-M3")
        self.assertNotIn("面向该 JD", question_text)

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

        report = self.assert_ok(
            self.client.post(f"/api/interviews/{interview['id']}/finish", headers=headers)
        )
        self.assertGreater(report["total_score"], 0)

        exported = self.assert_ok(
            self.client.get(f"/api/interviews/{interview['id']}/report/export", headers=headers)
        )
        self.assertTrue(exported["filename"].endswith(".md"))
        self.assertIn("面试总结报告", exported["content"])
        exported_docx = self.client.get(f"/api/interviews/{interview['id']}/report/export", headers=headers, params={"format": "docx"})
        self.assertEqual(exported_docx.status_code, 200, exported_docx.text)
        self.assertGreater(len(exported_docx.content), 1000)
        exported_pdf = self.client.get(f"/api/interviews/{interview['id']}/report/export", headers=headers, params={"format": "pdf"})
        self.assertEqual(exported_pdf.status_code, 200, exported_pdf.text)
        self.assertGreater(len(exported_pdf.content), 500)

        deleted = self.assert_ok(
            self.client.delete(f"/api/interviews/{interview['id']}", headers=headers)
        )
        self.assertEqual(deleted["message"], "删除成功")
        missing = self.client.get(f"/api/interviews/{interview['id']}", headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_admin_usage_and_manual_grant(self):
        user_email = f"candidate-{uuid.uuid4().hex}@example.com"
        user_headers = self.auth_headers(user_email)
        admin_headers = self.auth_headers("admin@example.com")

        forbidden = self.client.get("/api/business/admin/usage-summary", headers=user_headers)
        self.assertEqual(forbidden.status_code, 403)

        summary = self.assert_ok(
            self.client.get("/api/business/admin/usage-summary", headers=admin_headers)
        )
        self.assertIn("totals", summary)

        grant = self.assert_ok(
            self.client.post(
                "/api/business/admin/grant-plan",
                headers=admin_headers,
                json={"email": user_email, "plan": "pro", "days": 30, "notes": "unit test"},
            )
        )
        self.assertEqual(grant["plan"], "pro")

        entitlements = self.assert_ok(
            self.client.get("/api/business/entitlements", headers=user_headers)
        )
        self.assertEqual(entitlements["plan"]["current"], "pro")

        enterprise = self.assert_ok(
            self.client.post(
                "/api/business/admin/grant-plan",
                headers=admin_headers,
                json={"email": user_email, "plan": "enterprise", "notes": "institution trial"},
            )
        )
        self.assertEqual(enterprise["plan"], "enterprise")
        self.assertIsNone(enterprise["expires_at"])


if __name__ == "__main__":
    unittest.main()
