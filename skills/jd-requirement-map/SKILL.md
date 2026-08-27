---
name: jd-requirement-map
description: Map explicit requirements from a job description into a structured capability list for resume comparison or interview planning; do not infer requirements that are not stated.
---

# JD Requirement Map

Extract only requirements present in the supplied JD.

- Separate explicit required capabilities from optional or preferred capabilities when the source distinguishes them.
- Preserve the original wording as evidence for every normalized requirement.
- Do not treat company marketing language as a candidate requirement.
- Return an empty list when the JD has no supported requirement signal.
