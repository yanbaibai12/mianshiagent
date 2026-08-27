---
name: resume-evidence-extract
description: Extract claim-level evidence from a user resume when an Agent must reason about existing facts without inventing new employers, dates, metrics, titles, or skills.
---

# Resume Evidence Extract

Use only the resume text supplied through the authorized `resume.read` tool.

- Return each claim with its source text and source identifier.
- Preserve uncertainty; do not convert implied experience into a confirmed fact.
- Reject unsupported numbers, employers, dates, titles, and skills.
- Keep personally identifying contact data out of summaries and traces.
- If no reliable claim exists, return an empty claim list rather than guessing.
