---
description: Audit a paper for potentially missing direct experimental baselines
argument-hint: "[PDF path or AMiner pub_id] [review-as-of: YYYY-MM-DD]"
allowed-tools: Read, Write, Bash
---

# `/baseline-audit`

Use the `baseline-audit` Skill for `$ARGUMENTS`.

- Require exactly one local PDF or 24-character hexadecimal AMiner `pub_id`; request missing input instead of inventing paper identity.
- Follow the Skill's cutoff, credential, privacy, cost, and evidence rules. Never ask the user to paste API keys into chat.
- Keep direct comparisons separate from useful candidates that still need verification; do not turn this into a general related-work review or acceptance prediction.
