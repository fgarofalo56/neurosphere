---
description: Review the current changes for bugs, security, and style
---

Review the uncommitted changes (`git diff`) in this repository. Check for:

- Correctness bugs and edge cases.
- Security issues (injection, unsafe input handling, secret leakage).
- Consistency with the surrounding code and the conventions in `CLAUDE.md`.
- Missing tests for new behavior.

Report findings grouped by severity (Critical / Warning / Suggestion) with
`file:line` references and concrete fixes. Be specific and skeptical.
