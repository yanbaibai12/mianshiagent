import time
from dataclasses import dataclass
from typing import Any

from app.prompts import SCORE_ANSWER_PROMPT
from app.services.interview_context_builder import build_interview_context, safe_prompt_field


@dataclass(frozen=True)
class InterviewScoringResult:
    response: Any
    usage_metadata: dict[str, Any]
    safety_metadata: dict[str, Any]


async def request_answer_score(
    llm: Any,
    *,
    question: str,
    answer: str,
    template_context: str,
    resume_context: Any,
    jd_context: Any,
    company_profile_context: Any = None,
    evidence_context: Any = None,
    rag_context: Any = None,
) -> InterviewScoringResult:
    context = build_interview_context(
        template_context=template_context,
        resume_context=resume_context,
        jd_context=jd_context,
        company_profile_context=company_profile_context,
        evidence_context=evidence_context,
        rag_context=rag_context,
    )
    safe_question, question_safety = safe_prompt_field(question, "interview_question", max_chars=2000)
    safe_answer, answer_safety = safe_prompt_field(answer, "candidate_answer", max_chars=8000)
    risk_types = sorted(
        set(context.safety_metadata.get("risk_types") or [])
        | set(question_safety.get("risk_types") or [])
        | set(answer_safety.get("risk_types") or [])
    )
    filtered_count = (
        int(context.safety_metadata.get("filtered_count") or 0)
        + int(question_safety.get("removed_count") or 0)
        + int(answer_safety.get("removed_count") or 0)
    )
    prompt = SCORE_ANSWER_PROMPT.format(
        question=safe_question,
        answer=safe_answer,
        resume_context=context.text,
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages, feature="answer_score")
    return InterviewScoringResult(
        response=response,
        usage_metadata=llm.build_usage_metadata(
            messages,
            response,
            feature="answer_score",
            started_at=started_at,
        ),
        safety_metadata={"risk_types": risk_types, "filtered_count": filtered_count},
    )
