import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_PATH = Path(tempfile.gettempdir()) / f"mianshiagent_quality_eval_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "quality-eval-secret-key-that-is-long-enough-123456"
os.environ["DEBUG"] = "false"
os.environ["APP_ENV"] = "local"
os.environ["AUTO_CREATE_DB"] = "true"
os.environ["LLM_PROVIDER"] = "local"
os.environ["LLM_ALLOW_FALLBACK"] = "false"
os.environ["VECTOR_STORE_BACKEND"] = "keyword"
os.environ["QDRANT_SYNC_ON_STARTUP"] = "false"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["RERANK_PROVIDER"] = "none"

from app.database import async_session_maker, init_db  # noqa: E402
from app.models import Resume, User  # noqa: E402
from app.routers.resumes import _adapt_resume_to_jd  # noqa: E402
from app.services.knowledge_base import compact_json, seed_builtin_knowledge  # noqa: E402
from app.services.resume_index import reindex_resume_chunks  # noqa: E402
from app.utils.security import get_password_hash  # noqa: E402


CASES_PATH = ROOT / "quality" / "ats_eval_cases.json"
BANNED_PHRASES = ("面向该 JD", "可重点呈现", "岗位要求", "建议补充", "本地 MVP")
REQUIRED_DIMENSION_KEYS = {"score", "covered", "missing", "evidence", "risk", "suggestion"}
VISIBLE_RESUME_KEYS = ("personal", "education", "skills", "experience", "projects", "summary")


def _visible_resume_text(data: dict[str, Any]) -> str:
    visible = {key: data.get(key) for key in VISIBLE_RESUME_KEYS if data.get(key)}
    return compact_json(visible, 12000)


def _contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def _dimension(report: dict[str, Any], key: str) -> dict[str, Any]:
    for item in report.get("dimensions") or []:
        if item.get("key") == key:
            return item
    return {}


def _dimension_fields_ok(report: dict[str, Any]) -> bool:
    dimensions = report.get("dimensions") or []
    if len(dimensions) < 6:
        return False
    for dimension in dimensions:
        if not REQUIRED_DIMENSION_KEYS.issubset(set(dimension)):
            return False
        if not isinstance(dimension.get("suggestion"), str) or not dimension.get("suggestion", "").strip():
            return False
    return True


def _change_quality_ok(change_details: list[Any], expected_skills: list[str]) -> bool:
    if not change_details:
        return False
    changed = [
        item
        for item in change_details
        if isinstance(item, dict)
        and str(item.get("before") or "").strip()
        and str(item.get("after") or "").strip()
        and str(item.get("before") or "").strip() != str(item.get("after") or "").strip()
    ]
    if not changed:
        return False
    after_text = "\n".join(str(item.get("after") or "") for item in changed)
    has_expected_term = any(_contains(after_text, skill) for skill in expected_skills)
    has_action = any(marker in after_text for marker in ("负责", "完成", "使用", "设计", "实现", "参与", "接口", "检索", "任务", "数据"))
    return has_expected_term and has_action


def _evaluate_case(case: dict[str, Any], index_result: dict[str, Any], adapt_result: dict[str, Any]) -> dict[str, Any]:
    response = adapt_result["response"]
    report = adapt_result["ats_report"]
    optimized_resume = response.get("optimized_resume") if isinstance(response.get("optimized_resume"), dict) else {}
    change_details = response.get("change_details") if isinstance(response.get("change_details"), list) else []
    hard_dimension = _dimension(report, "hard_skills")
    hard_covered = set(hard_dimension.get("covered") or [])
    hard_missing = set(hard_dimension.get("missing") or [])
    visible_after = _visible_resume_text(optimized_resume)
    visible_before = _visible_resume_text(case["resume"])

    expected_skills = list(case.get("expected_skills") or [])
    missing_skills = list(case.get("missing_skills") or [])
    expected_coverage = (
        sum(1 for skill in expected_skills if skill in hard_covered) / max(1, len(expected_skills))
    )

    checks = {
        "resume_chunked": int(index_result.get("chunk_count") or 0) >= 3,
        "ats_dimensions_complete": _dimension_fields_ok(report),
        "expected_skills_covered": expected_coverage >= 0.7,
        "missing_skills_flagged": all(skill in hard_missing for skill in missing_skills),
        "evidence_non_empty": len(report.get("requirement_evidence") or []) >= 2,
        "optimized_has_real_diff": _change_quality_ok(change_details, expected_skills) and visible_after != visible_before,
        "no_banned_resume_phrase": not any(phrase in visible_after for phrase in BANNED_PHRASES),
        "no_fake_missing_skill": not any(_contains(visible_after, skill) for skill in missing_skills),
    }
    return {
        "id": case["id"],
        "role": case["role"],
        "passed": all(checks.values()),
        "checks": checks,
        "score": report.get("total_score"),
        "expected_coverage": round(expected_coverage, 3),
        "change_count": len(change_details),
        "missing_top": report.get("missing_top") or [],
    }


async def run_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    await init_db()
    results: list[dict[str, Any]] = []
    async with async_session_maker() as db:
        await seed_builtin_knowledge(db)
        await db.commit()

        for case in cases:
            user = User(
                email=f"quality-{case['id']}-{uuid.uuid4().hex}@example.com",
                password_hash=get_password_hash("password123"),
                nickname="Quality Eval",
            )
            db.add(user)
            await db.flush()
            resume = Resume(
                user_id=user.id,
                title=f"{case['role']} 评测简历",
                original_text=compact_json(case["resume"], 12000),
                parsed_data=case["resume"],
            )
            db.add(resume)
            await db.flush()
            index_result = await reindex_resume_chunks(db, resume)
            adapt_result = await _adapt_resume_to_jd(db, resume, case["jd"])
            results.append(_evaluate_case(case, index_result, adapt_result))
            await db.rollback()

    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    failed = [result for result in results if not result["passed"]]
    return {
        "case_count": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / max(1, total), 4),
        "failed_cases": failed[:10],
        "results": results,
    }


def main() -> int:
    min_pass_rate = float(os.environ.get("QUALITY_MIN_PASS_RATE", "0.9"))
    try:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        if len(cases) < 20:
            raise RuntimeError(f"Quality eval requires at least 20 cases, got {len(cases)}")
        result = asyncio.run(run_suite(cases))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["pass_rate"] >= min_pass_rate else 1
    finally:
        _DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
