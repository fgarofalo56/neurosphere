Prepare the current work for shipping. Do not push.

1. Run the full gates and show the raw output:
   `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full`
2. If anything fails, fix it and re-run. Never weaken a test or add `|| true`.
3. Review `git diff` for secrets, PII, `.env*`, and claims of FedRAMP/ATO/parity.
4. Stage only the files that belong to this work item and commit with a
   conventional-commit message. Reference the PRP id and work item.
5. STOP. Report the commit hash and the gate output. Pushing, opening a PR and
   any deployment require explicit operator approval (CLAUDE.md hard constraints).
