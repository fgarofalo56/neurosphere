# Incident response plan

Pre-release project: no deployed instance exists yet, so this plan covers the
repository, build pipeline and, once deployed, a customer-hosted instance.
This document makes **no FedRAMP, ATO or compliance claim**; control narratives
and ATO evidence are owned by PRP-23.

## Severity levels

| Level | Meaning | Examples | Target response |
|---|---|---|---|
| SEV1 | Confirmed compromise or data exposure | Real credential pushed, cross-tenant or cross-cloud data exposure, unauthorized action executed | Immediately; operator paged |
| SEV2 | Probable exposure, contained | Credential in a local commit only, High CVE reachable in a deployed image | Same working day |
| SEV3 | Weakness without exposure | Failing scan on a branch, expired secret warning, hook bypassed with no leak | Next working days |

## Roles

- **Incident lead:** the operator (repo owner) unless delegated.
- **Responder:** whoever detects it; starts containment within their permissions.
- **Communications:** the incident lead; customers or tenants are informed by the
  operator, not by an agent.
- Agents must not push, deploy or change shared resources during an incident
  without operator approval.

## Detection sources

- `secret-scan` CI (`.github/workflows/secret-scan.yml`): gitleaks full history,
  tracked credential-shaped files, PII pattern scan; weekly re-scan.
- Local hooks `.githooks/pre-commit` and `.githooks/pre-push`.
- CodeQL, `pip-audit`, `pnpm audit` in CI (see `SECURITY.md`).
- NeuroSphere audit store (PRP-06): append-only before/after/denied-action
  records, exportable to a SIEM.
- Azure Monitor and Key Vault diagnostics, once deployed.
- Reports through the channel in `SECURITY.md`.

## Flow

1. **Contain.** Revoke or rotate the credential, disable the identity, revoke a
   token, disable the affected connector or feature. For credentials follow
   [credential-leak-response.md](credential-leak-response.md): **rotate the
   credential first, then clean history.** Fail closed rather than open.
2. **Eradicate.** Remove the root cause (code, configuration, dependency, access),
   confirm no persistence (new role assignments, extra credentials, tampered
   catalog or action state).
3. **Recover.** Restore service with new credentials from Key Vault references,
   verify by behaviour ([secret-rotation.md](secret-rotation.md)), and re-run
   the relevant gates. Report anything not run as OPEN.
4. **Lessons learned.** Within five working days: timeline, root cause, what
   detection worked or missed, follow-up issues with owners. No secret values.

## Evidence preservation

- Audit records are append-only; never edit or delete them. Export copies and
  record hashes/identifiers.
- Preserve CI run logs, commit ids, alert ids and provider log extracts.
- Keep evidence in access-controlled storage; redact before sharing externally.
  Do not paste credentials or personal data into the incident record.

## Communication

- Internal: incident lead decides on notification; keep a timestamped log.
- External (customers, tenants, providers): operator-approved wording only.
- Never claim compliance or authorization status in incident communications.

## Related

- [credential-leak-response.md](credential-leak-response.md)
- [secret-rotation.md](secret-rotation.md)
- [pre-push-checklist.md](pre-push-checklist.md)
