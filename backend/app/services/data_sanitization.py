from __future__ import annotations

import re
from typing import Any

SENSITIVE_METADATA_KEYS = {"resume", "resume_text", "jd", "jd_text", "api_key", "phone", "email", "mobile"}
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
API_KEY_PATTERN = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_\-]{12,}\b", re.IGNORECASE)


def clean_labels(labels: list[str] | None) -> list[str]:
    """Normalize bounded user-authored tags without preserving duplicates."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        text = " ".join(str(label or "").split()).strip(" ,，;；。")
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text[:40])
    return cleaned[:12]


def redact_sensitive_text(value: str | None) -> str:
    """Remove common contact and API credential patterns from untrusted text."""
    text = str(value or "")
    text = EMAIL_PATTERN.sub("[email_redacted]", text)
    text = PHONE_PATTERN.sub("[phone_redacted]", text)
    return API_KEY_PATTERN.sub("[key_redacted]", text)


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded metadata object with sensitive fields removed and strings redacted."""
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        key_text = str(key or "").strip()[:60]
        if not key_text or key_text.lower() in SENSITIVE_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = redact_sensitive_text(str(value))[:200] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key_text] = [redact_sensitive_text(str(item))[:80] for item in value[:12]]
    return safe
