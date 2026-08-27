---
name: resume-truthful-rewrite
description: Produce an evidence-linked resume rewrite proposal for a target JD when every selected statement must remain traceable to verified resume claims; do not use it for free-form career storytelling.
---

# Resume Truthful Rewrite

Use only claims emitted by `resume-evidence-extract` and explicit requirements from the supplied JD.

- Preserve every selected claim's source hash and claim identifier.
- Rank or omit claims for relevance; never add employers, dates, metrics, titles, skills, scope, or outcomes.
- Reject claims whose text no longer matches their evidence text and SHA-256.
- Exclude contact details and other unnecessary personal identifiers.
- Return an empty proposal when no verified claim exists instead of fabricating a stronger resume.
- Treat requirement coverage as a routing signal, not proof that the rewrite is effective; effectiveness requires independent blind evaluation.
