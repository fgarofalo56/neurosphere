# PRP-139 evidence: hosted environment shows the tenant it runs in

Gate "hosted real tenant" is **OPEN**. PRP-139 built and unit-tested the scripts, templates and
console pieces; it ran nothing against Azure. The operator steps are in
`docs/deploy/hosted-real-tenant.md`. This directory holds no evidence file yet.

Real evidence files are added only by operator runs (`NS_LIVE_APPROVED=1`, owner approval of each
role assignment, point-to-site VPN) and hold counts, states and reason codes only: no subscription
id, tenant id, host, resource id, object id or token.

| # | Gate row | What PASS needs | Commands that produce the evidence | Status |
|---|---|---|---|---|
| 1 | Foundry | At least one real agent or model deployment from an owner-named project is visible in the catalog UI | `hosted_real_tenant.py verify` (writes `<date>-verify.json`); the console connection at `/admin/sources/connectors` | OPEN |
| 2 | API Management gateway | At least one registered real gateway with `poll_status` ok and gateway traffic on a dashboard (needs a gateway with LLM logs sent to a workspace) | `hosted_real_tenant.py verify` | OPEN |
| 3 | Cost and billing | Invoiced spend of a closed month from the owner's export in the reconciliation view (needs an existing export and a closed month) | `hosted_real_tenant.py verify` | OPEN |
| 4 | Azure Monitor and Application Insights AI call telemetry | Owned by the follow-up PRP; not available in this release | none here | OPEN |
| 5 | Synthetic records | Purge evidence with deleted counts, and `verify` showing zero records of the synthetic customer and source | `hosted_purge_synthetic.py plan` and `apply` (`<date>-purge-plan.json`, `<date>-purge.json`), then `hosted_real_tenant.py verify` | OPEN |
| 6 | Access | The access evidence lists exactly the approved assignments, each at single-resource scope | `hosted_real_tenant.py access-plan` and `access-apply` (`<date>-access.json`) | OPEN |

## Role assignments the access gate (row 6) expects

Each is at single-resource scope. Role definition ids were verified against Microsoft Learn on
2026-11-21.

| Identity | Role | Role definition id | Scope |
|---|---|---|---|
| Workers | Foundry User | `53ca6127-db72-4b80-b1b0-d745d6d5456d` | each named Foundry account |
| Workers | Storage Blob Data Reader | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | the export storage account |
| Workers | Log Analytics Data Reader | `3b03c2da-16b3-4a49-8834-0f8130efdd3b` | the gateway's workspace |
| API | API Management Service Reader Role | `71522526-b88f-4d52-b57f-d31fc3546d0d` | the API Management service |

A Monitoring Reader row is printed by `access-plan` marked UNVERIFIED and cannot be applied. If
gateway registration is denied on diagnostic settings with Service Reader alone, record that row as
OPEN and do not assign a broader role without the owner's approval.

The gate is PASS only when all six rows have evidence from one environment after the cut-over. A
source that was not connected is OPEN, never PASS. The G04 connector gate
(`docs/connectors/coverage.md`) stays OPEN and is not replaced by this gate.
