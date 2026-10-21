# G05 - model swap compatibility: OPEN

**Status: OPEN. The live gate did not run.** The operator decided on 2026-10-20 that G05 stays
OPEN in PRP-17. Nothing in this directory is evidence that a Foundry deployment was changed.
What exists is the connector (`connectors/reference/foundry-actions/`), mock-transport tests
that drive it against a scripted ARM, and a live script that refuses without approval.

## What would close it (narrowly, for the tested target only)

`NS_LIVE_APPROVED=1 python scripts/gates/g05_foundry_swap_live.py --subscription ... --resource-group ... --account ... --location ... --deployment ... --target-model ... --target-version ...`
against an operator-chosen, non-production Commercial Azure AI Services account. The script runs
dry_run, apply, verify (observed deployment state), rollback, then verifies the restored model,
and writes a whitelisted JSON record here. Until that file exists, G05 is OPEN and production
action execution stays blocked per the register. Government is not covered: the
`foundry.deployment_write` Government capability row is disabled (G01).

## Documented operations used (Microsoft Learn, verified 2026-10-20)

| Operation | Method and path | api-version |
|---|---|---|
| Deployments - Get | `GET /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/deployments/{name}` | `2024-10-01` |
| Deployments - Create Or Update | `PUT` on the same path | `2024-10-01` |
| Models - List | `GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{location}/models` | `2024-10-01` |
| Permissions - List For Resource | `GET .../accounts/{account}/providers/Microsoft.Authorization/permissions` | `2022-04-01` |

The how-to also lists `2025-06-01` as supported for deployments; `2024-10-01` is pinned here.
Host: `management.azure.com` (Commercial). No other request shape is used.

## Known limitations

- **In-place swap, no traffic-split canary (PRP-17 D4).** The documented PUT replaces the
  deployment's model in place. There is no staged traffic split, so the connector cannot offer a
  canary. The executor's canary phase is a pluggable probe plus verify, followed by rollback on
  failure; it does not shift a fraction of traffic.
- **Etag check is not atomic (TOCTOU).** `target_version` is the deployment's ARM `etag`.
  `If-Match` on this PUT is not documented, so it is not relied on. The connector re-GETs
  immediately before the PUT and raises `stale_version` (`target_version_changed`) on a
  difference, but a change landing between that GET and the PUT is not detected.
- **Context window and tool support are not checked.** Models - List has no documented field for
  either; they are reported `unknown` (a warning), never `passed`. Checked fields: model exists
  for the account location with the same `format`, `lifecycleStatus` not `Deprecated`, inference
  deprecation date not past, deployment sku name in the model's `skus`, capability keys present
  on the current model present on the target.
- **Failed provisioning during apply.** If the PUT reaches `Failed`/`Canceled`, `apply` raises and
  returns no `ApplyResult`, so no rollback token is issued for that attempt. The executor should
  `verify` and restore from its own pre-change record.
- **Commercial availability is `unverified`** in the capability matrix
  (`foundry.deployment_write.commercial.global.any`) until this gate runs.
