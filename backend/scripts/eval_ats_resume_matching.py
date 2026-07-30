import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_PATH = Path(tempfile.gettempdir()) / f"mianshiagent_ats_eval_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "ats-eval-secret-key-that-is-long-enough-123456"
os.environ["DEBUG"] = "false"
os.environ["APP_ENV"] = "local"
os.environ["VECTOR_STORE_BACKEND"] = "keyword"
os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["RERANK_PROVIDER"] = "none"

from app.database import async_session_maker, init_db  # noqa: E402
from app.models import Resume, User  # noqa: E402
from app.services.ats_scoring import build_ats_report  # noqa: E402
from app.services.resume_index import reindex_resume_chunks  # noqa: E402
from app.utils.security import get_password_hash  # noqa: E402


SAMPLE_RESUME = {
    "personal": {"name": "张三", "email": "zhangsan@example.com", "phone": "13800138000", "job_intent": "后端开发工程师"},
    "education": [{"school": "某某大学", "major": "计算机科学与技术", "degree": "本科", "time": "2022-2026"}],
    "skills": ["Python", "FastAPI", "Redis", "PostgreSQL", "Docker", "Git", "RAG", "Qdrant"],
    "projects": [
        {
            "name": "面试简历 Agent",
            "role": "后端负责人",
            "time": "2026.01-2026.06",
            "description": "负责 FastAPI 接口、RAG 知识库、Qdrant 向量检索、报告导出和任务状态追踪。",
            "tech_stack": ["Python", "FastAPI", "PostgreSQL", "Redis", "Qdrant", "RAG"],
            "interview_points": [
                {"title": "混合检索", "description": "使用向量召回与关键词召回融合，按 RRF 思路合并证据。"}
            ],
        }
    ],
    "experience": [
        {
            "company": "某科技公司",
            "role": "后端实习生",
            "time": "2025.07-2025.10",
            "highlights": ["参与用户系统开发，负责登录注册、权限校验、接口联调和日志追踪。"],
            "interview_points": [{"title": "接口联调", "description": "排查登录接口参数、权限和异常返回问题。"}],
        }
    ],
    "summary": "具备 Python 后端、RAG 应用和接口联调经验。",
}

SAMPLE_JD = "岗位要求：熟悉 Python、FastAPI、Redis、PostgreSQL；有 RAG 或 Agent 项目经验；具备接口设计、联调排查、优化和结果交付能力。"


async def run_eval() -> dict:
    await init_db()
    async with async_session_maker() as db:
        user = User(
            email=f"ats-eval-{uuid.uuid4().hex}@example.com",
            password_hash=get_password_hash("password123"),
            nickname="ATS Eval",
        )
        db.add(user)
        await db.flush()
        resume = Resume(
            user_id=user.id,
            title="ATS 评测简历",
            original_text=json.dumps(SAMPLE_RESUME, ensure_ascii=False),
            parsed_data=SAMPLE_RESUME,
        )
        db.add(resume)
        await db.flush()
        index_result = await reindex_resume_chunks(db, resume)
        report = await build_ats_report(db, resume, SAMPLE_JD)
        await db.rollback()

    dimensions = report.get("dimensions") or []
    evidence = report.get("requirement_evidence") or []
    hard_dimension = next((item for item in dimensions if item.get("key") == "hard_skills"), {})
    checks = {
        "chunked_resume": index_result.get("chunk_count", 0) >= 4,
        "has_dimensions": len(dimensions) >= 6,
        "has_resume_evidence": len(evidence) >= 2,
        "hard_skill_score_reasonable": hard_dimension.get("score", 0) >= 70,
        "no_banned_phrase": "面向该 JD" not in json.dumps(report, ensure_ascii=False),
    }
    return {
        "passed": sum(1 for value in checks.values() if value),
        "total": len(checks),
        "pass_rate": round(sum(1 for value in checks.values() if value) / len(checks), 4),
        "checks": checks,
        "index": index_result,
        "ats_score": report.get("total_score"),
        "dimension_count": len(dimensions),
        "evidence_count": len(evidence),
    }


def main() -> int:
    try:
        result = asyncio.run(run_eval())
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["pass_rate"] >= 0.9 else 1
    finally:
        _DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
