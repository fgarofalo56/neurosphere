## PRP

- PRP: `PRPs/active/PRP-NN-<name>.md`
- Work items in this PR:

## Gate evidence (paste raw output)

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Evidence paths

- `docs/evidence/...`

## Checklist

- [ ] No secrets, connection strings, PII or `.env*` in the diff
- [ ] No `|| true` or skipped tests added
- [ ] Live/paid gates either ran with operator approval (evidence linked) or are recorded as OPEN in `docs/RESEARCH-AND-GATES.md`
- [ ] No FedRAMP / ATO / parity claim added to docs or UI
- [ ] CHANGELOG `Unreleased` updated when behaviour changes
