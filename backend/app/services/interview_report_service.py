import json
import time
from dataclasses import dataclass
from typing import Any

from app.prompts import SUMMARIZE_INTERVIEW_PROMPT
from app.services.interview_context_builder import build_interview_context


@dataclass(frozen=True)
class InterviewReportResult:
    response: Any
    usage_metadata: dict[str, Any]
    safety_metadata: dict[str, Any]


def _compact_answer_records(value: Any, max_chars: int = 11_500) -> Any:
    if not isinstance(value, list):
        return value
    if not value:
        return []

    per_record = max(260, max_chars // len(value))
    question_limit = max(60, int((per_record - 180) * 0.35))
    answer_limit = max(100, int((per_record - 180) * 0.65))

    def compact(question_chars: int, answer_chars: int) -> list[dict[str, Any]]:
        return [
            {
                "question": str(item.get("question") or "")[:question_chars],
                "answer": str(item.get("answer") or "")[:answer_chars],
                "scores": item.get("scores") if isinstance(item.get("scores"), dict) else {},
                "module": str(item.get("module") or "")[:40],
            }
            for item in value
            if isinstance(item, dict)
        ]

    records = compact(question_limit, answer_limit)
    while len(json.dumps(records, ensure_ascii=False, default=str)) > max_chars and (question_limit > 60 or answer_limit > 100):
        question_limit = max(60, int(question_limit * 0.8))
        answer_limit = max(100, int(answer_limit * 0.8))
        records = compact(question_limit, answer_limit)
    return records


async def request_interview_report(
    llm: Any,
    *,
    template_context: str,
    jd_context: Any,
    company_profile_context: Any,
    answers_context: Any,
    rag_context: Any,
) -> InterviewReportResult:
    context = build_interview_context(
        template_context=template_context,
        jd_context=jd_context,
        company_profile_context=company_profile_context,
        answer_context=json.dumps(_compact_answer_records(answers_context), ensure_ascii=False, default=str),
        rag_context=rag_context,
    )
    prompt = SUMMARIZE_INTERVIEW_PROMPT.format(questions_and_answers=context.text)
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages, feature="interview_report")
    return InterviewReportResult(
        response=response,
        usage_metadata=llm.build_usage_metadata(
            messages,
            response,
            feature="interview_report",
            started_at=started_at,
        ),
        safety_metadata=context.safety_metadata,
    )
