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

from app.config import get_settings  # noqa: E402
from app.database import async_session_maker, init_db  # noqa: E402
from app.models import InterviewQuestion, Resume, User  # noqa: E402
from app.prompts import SCORE_ANSWER_PROMPT  # noqa: E402
from app.routers.interviews import (  # noqa: E402
    _build_question_batches,
    _detect_tech_terms,
    _is_bad_question,
    _merge_question_items,
    _module_fallback_questions,
    _normalize_score_details,
    _question_quality,
    _resume_evidence_dicts,
)
from app.routers.resumes import _adapt_resume_to_jd  # noqa: E402
from app.services.knowledge_base import compact_json, seed_builtin_knowledge  # noqa: E402
from app.services.llm_client import get_llm_client  # noqa: E402
from app.services.resume_index import (
    reindex_resume_chunks,  # noqa: E402
    retrieve_resume_evidence,  # noqa: E402
)
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


def _should_expect_agent(case: dict[str, Any]) -> bool:
    text = f"{case.get('role', '')} {case.get('jd', '')} {compact_json(case.get('resume') or {}, 8000)}"
    return any(term in text.lower() for term in ("agent", "rag", "qdrant", "bge", "tool calling", "function calling"))


async def _evaluate_interview_quality(db: Any, resume: Resume, case: dict[str, Any]) -> dict[str, Any]:
    data = resume.optimized_data or resume.parsed_data or {}
    batches = _build_question_batches(data, resume, case["jd"])
    modules = {batch.module for batch in batches}
    generated_questions: list[dict[str, Any]] = []
    evidence_count = 0
    seen_keys: set[str] = set()
    seen_texts: list[str] = []
    duplicate_count = 0

    for batch in batches:
        snippets = await retrieve_resume_evidence(
            db,
            user_id=resume.user_id,
            resume_id=resume.id,
            query=f"{batch.title} {batch.description} {batch.context}",
            sections={"project": ["project"], "internship": ["experience"], "agent_fundamentals": ["skills", "project", "experience"]}.get(batch.module),
            limit=5,
        )
        evidence = _resume_evidence_dicts(snippets, batch)
        if evidence:
            evidence_count += 1
        selected_items = _merge_question_items(
            [],
            _module_fallback_questions(batch),
            batch.limit,
            batch=batch,
            seen_texts=seen_texts,
            seen_keys=seen_keys,
        )
        for item in selected_items:
            question = item.get("question_text") or item.get("question") or ""
            duplicate_count += max(0, seen_texts.count(question) - 1)
            generated_questions.append(
                {
                    "module": batch.module,
                    "question": question,
                    "evidence": evidence,
                    "quality": _question_quality(question, batch, evidence),
                    "bad": _is_bad_question(question, batch),
                    "tech_terms": _detect_tech_terms(question),
                }
            )

    question_count = len(generated_questions)
    evidence_rate = evidence_count / max(1, len(batches))
    specific_rate = sum(1 for item in generated_questions if item["tech_terms"] or item["quality"].get("specificity_score", 0) >= 6) / max(1, question_count)
    bad_count = sum(1 for item in generated_questions if item["bad"])

    score_details_ok = False
    if generated_questions:
        sample_question = generated_questions[0]["question"]
        sample_answer = (
            "我会先说明项目背景和个人负责边界，再拆解接口、检索、Redis 队列和 Qdrant 证据链路。"
            "排查时先看日志和任务状态，再验证召回、重排和最终报告质量，并用指标复盘优化效果。"
        )
        llm = get_llm_client(get_settings())
        response = await llm.chat_completion_json(
            [
                {
                    "role": "user",
                    "content": SCORE_ANSWER_PROMPT.format(
                        question=sample_question,
                        answer=sample_answer,
                        resume_context=compact_json(data, 4000),
                    ),
                }
            ],
            feature="answer_score",
        )
        if isinstance(response, dict):
            fake_question = InterviewQuestion(
                interview_id=None,
                sequence=1,
                question=sample_question,
                evidence=generated_questions[0]["evidence"],
            )
            scores = response.get("scores") or {}
            details = _normalize_score_details(response, scores, sample_answer, fake_question)
            score_details_ok = bool(details) and all(
                isinstance(item, dict) and item.get("issue") and item.get("suggestion")
                for item in details.values()
            )

    return {
        "modules": sorted(modules),
        "question_count": question_count,
        "evidence_rate": round(evidence_rate, 3),
        "specific_rate": round(specific_rate, 3),
        "duplicate_count": duplicate_count,
        "bad_count": bad_count,
        "checks": {
            "interview_covers_project": "project" in modules,
            "interview_covers_internship": "internship" in modules,
            "interview_covers_agent_when_expected": (not _should_expect_agent(case)) or "agent_fundamentals" in modules,
            "interview_questions_specific": specific_rate >= 0.7,
            "interview_no_duplicates": duplicate_count == 0,
            "interview_no_bad_questions": bad_count == 0,
            "interview_evidence_coverage": evidence_rate >= 0.8,
            "answer_score_explained": score_details_ok,
        },
    }


def _evaluate_case(case: dict[str, Any], index_result: dict[str, Any], adapt_result: dict[str, Any], interview_result: dict[str, Any]) -> dict[str, Any]:
    response = adapt_result["response"]
    report = adapt_result["ats_report"]
    optimized_resume = response.get("optimized_resume") if isinstance(response.get("optimized_resume"), dict) else {}
    change_details = response.get("change_details") if isinstance(response.get("change_details"), list) else []
    hard_dimension = _dimension(report, "hard_skills")
    hard_covered = set(hard_dimension.get("covered") or [])
    hard_missing = set(hard_dimension.get("missing") or [])
    missing_top = set(report.get("missing_top") or [])
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
        "missing_skills_flagged": all(skill in hard_missing or skill in missing_top for skill in missing_skills),
        "evidence_non_empty": len(report.get("requirement_evidence") or []) >= 2,
        "optimized_has_real_diff": _change_quality_ok(change_details, expected_skills) and visible_after != visible_before,
        "no_banned_resume_phrase": not any(phrase in visible_after for phrase in BANNED_PHRASES),
        "no_fake_missing_skill": not any(_contains(visible_after, skill) for skill in missing_skills),
        **(interview_result.get("checks") or {}),
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
        "interview": {
            "modules": interview_result.get("modules") or [],
            "question_count": interview_result.get("question_count", 0),
            "evidence_rate": interview_result.get("evidence_rate", 0),
            "specific_rate": interview_result.get("specific_rate", 0),
            "duplicate_count": interview_result.get("duplicate_count", 0),
            "bad_count": interview_result.get("bad_count", 0),
        },
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
            response = adapt_result.get("response") if isinstance(adapt_result.get("response"), dict) else {}
            optimized_resume = response.get("optimized_resume") if isinstance(response.get("optimized_resume"), dict) else None
            if optimized_resume:
                resume.optimized_data = optimized_resume
            interview_result = await _evaluate_interview_quality(db, resume, case)
            results.append(_evaluate_case(case, index_result, adapt_result, interview_result))
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
    min_pass_rate = float(os.environ.get("QUALITY_MIN_PASS_RATE", "0.95"))
    try:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        if len(cases) < 40:
            raise RuntimeError(f"Quality eval requires at least 40 cases, got {len(cases)}")
        result = asyncio.run(run_suite(cases))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["pass_rate"] >= min_pass_rate else 1
    finally:
        _DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
