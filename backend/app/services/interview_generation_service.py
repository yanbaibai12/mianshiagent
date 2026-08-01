import time
from dataclasses import dataclass
from typing import Any

from app.prompts import GENERATE_QUESTIONS_PROMPT
from app.services.interview_context_builder import build_interview_context, safe_prompt_field


@dataclass(frozen=True)
class InterviewGenerationResult:
    response: Any
    usage_metadata: dict[str, Any]
    safety_metadata: dict[str, Any]


async def request_generated_questions(
    llm: Any,
    *,
    feature: str,
    module: str,
    point_title: str,
    point_description: str,
    template_context: str,
    resume_context: Any,
    jd_context: Any,
    training_profile_context: Any = None,
    company_profile_context: Any = None,
    evidence_context: Any = None,
    rag_context: Any = None,
) -> InterviewGenerationResult:
    context = build_interview_context(
        template_context=template_context,
        resume_context=resume_context,
        jd_context=jd_context,
        training_profile_context=training_profile_context,
        company_profile_context=company_profile_context,
        evidence_context=evidence_context,
        rag_context=rag_context,
    )
    safe_title, title_safety = safe_prompt_field(point_title, "question_batch_title", max_chars=300)
    safe_description, description_safety = safe_prompt_field(
        point_description,
        "question_batch_description",
        max_chars=1200,
    )
    risk_types = sorted(
        set(context.safety_metadata.get("risk_types") or [])
        | set(title_safety.get("risk_types") or [])
        | set(description_safety.get("risk_types") or [])
    )
    filtered_count = (
        int(context.safety_metadata.get("filtered_count") or 0)
        + int(title_safety.get("removed_count") or 0)
        + int(description_safety.get("removed_count") or 0)
    )
    prompt = GENERATE_QUESTIONS_PROMPT.format(
        point_title=safe_title,
        point_description=safe_description,
        experience_context=f"模块：{module}\n{context.text}",
    )
    messages = [{"role": "user", "content": prompt}]
    started_at = time.monotonic()
    response = await llm.chat_completion_json(messages, feature=feature)
    return InterviewGenerationResult(
        response=response,
        usage_metadata=llm.build_usage_metadata(
            messages,
            response,
            feature=feature,
            started_at=started_at,
        ),
        safety_metadata={"risk_types": risk_types, "filtered_count": filtered_count},
    )
