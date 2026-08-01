import re
from dataclasses import dataclass
from typing import Any

from app.services.quality import API_KEY_PATTERN, EMAIL_PATTERN, PHONE_PATTERN, redact_sensitive_text


INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?:忽略|无视|覆盖|绕过|忘记).{0,24}(?:之前|以上|系统|开发者|指令|规则|提示词)|"
            r"ignore.{0,24}(?:previous|above|system|developer).{0,16}(?:instruction|prompt|rule)",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(
            r"(?:泄露|输出|显示|打印|返回).{0,20}(?:系统提示词|系统指令|开发者消息|system prompt|developer message)|"
            r"reveal.{0,20}(?:system prompt|developer message|hidden instruction)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_execution",
        re.compile(
            r"(?:立即|现在|必须|请).{0,12}(?:调用|执行|运行).{0,12}(?:工具|函数|命令|shell|tool)|"
            r"(?:call|execute|run).{0,12}(?:the following|this).{0,8}(?:tool|function|command)",
            re.IGNORECASE,
        ),
    ),
    (
        "scoring_manipulation",
        re.compile(
            r"(?:修改|覆盖|忽略|绕过).{0,16}(?:评分规则|评分|分数|rubric)"
            r"(?:.{0,12}(?:给满分|评为满分|打10分|打 10 分))?|"
            r"(?:直接|必须|请).{0,8}(?:给满分|评为满分|打10分|打 10 分)|"
            r"(?:change|override|ignore).{0,16}(?:score|scoring|rubric)",
            re.IGNORECASE,
        ),
    ),
)

INTERNAL_URL_PATTERN = re.compile(
    r"https?://(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|[^\s/]+\.(?:local|internal))(?:[^\s]*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SanitizedContext:
    text: str
    risk_types: list[str]
    removed_count: int


def sanitize_untrusted_text(value: Any, *, max_chars: int = 12_000) -> SanitizedContext:
    risk_counts: dict[str, int] = {}
    raw_text = str(value or "")
    sensitive_count = sum(
        len(pattern.findall(raw_text))
        for pattern in (EMAIL_PATTERN, PHONE_PATTERN, API_KEY_PATTERN)
    )
    if sensitive_count:
        risk_counts["sensitive_data"] = sensitive_count
    text = redact_sensitive_text(raw_text)
    for risk_type, pattern in INJECTION_PATTERNS:
        match_count = len(pattern.findall(text))
        if match_count:
            risk_counts[risk_type] = risk_counts.get(risk_type, 0) + match_count

    def replace_internal_url(match: re.Match[str]) -> str:
        risk_counts["internal_url"] = risk_counts.get("internal_url", 0) + 1
        return "[internal_url_redacted]"

    text = INTERNAL_URL_PATTERN.sub(replace_internal_url, text)
    for _risk_type, pattern in INJECTION_PATTERNS:
        text = pattern.sub("[untrusted_instruction_removed]", text)

    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return SanitizedContext(
        text=text[:max_chars],
        risk_types=sorted(risk_counts),
        removed_count=sum(risk_counts.values()),
    )


def sanitize_output_text(value: Any, *, max_chars: int = 1000) -> str:
    return sanitize_untrusted_text(value, max_chars=max_chars).text


def wrap_untrusted_data(source: str, value: Any, *, max_chars: int = 12_000) -> SanitizedContext:
    sanitized = sanitize_untrusted_text(value, max_chars=max_chars)
    safe_source = re.sub(r"[^a-z0-9_\-]", "_", source.lower())[:40] or "unknown"
    return SanitizedContext(
        text=(
            f'<UNTRUSTED_DATA source="{safe_source}">\n'
            f"{sanitized.text}\n"
            "</UNTRUSTED_DATA>"
        ),
        risk_types=sanitized.risk_types,
        removed_count=sanitized.removed_count,
    )
