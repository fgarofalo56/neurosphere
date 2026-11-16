# Write targets from stored configuration (PRP-54)

The action executor changes a Foundry model deployment or an APIM gateway only through a
registered write target. This runbook covers how targets get registered, how to enable the stored
entries in each profile, what the operator must grant, and what was and was not proven.

## How targets are chosen

1. **Env path (default).** `NS_FOUNDRY_*` and `NS_APIM_*` register at most one Foundry account and
   one APIM gateway per process. Nothing set means an empty registry and a dry run reports "no
   write target".
2. **Stored path (opt-in).** With `NS_WRITE_TARGETS_FROM_STORE=true` and at least one stored
   `write_targets` entry (PRP-45, console or settings API), the stored entries define the targets
   for the process and the env path is ignored. With the switch off, or no stored entry, or the
   store unreadable (`write_targets_store_unavailable`), the env path applies. There is no hot
   reload: restart the api and the `actions` worker after changing entries.

The switch exists so a deployment never gains a write path from stored data alone. The kill
switch (`PUT /api/v1/actions/emergency-disable`) and maker-checker approval remain the runtime
gates in both paths.

### Domain key

The registry holds one connector of a kind per domain (the intent's domain id is the key).

- An APIM entry is the APIM service ARM resource id. It is matched to the gateway registration with
  that ARM id (the gateway must already be registered); the registration's domain becomes the key.
  Two gateways in two domains are both registered; an intent in domain B plans and executes
  against gateway B, never gateway A. A domain with no gateway is advisory.
- A Foundry entry is the account ARM resource id. The stored entry carries no domain and no
  region, so the account is registered without a key (it answers every domain, one account per
  deployment) and the region for the Models read comes from `NS_FOUNDRY_LOCATION`. Without it the
  entry is skipped (`foundry_config_incomplete`).
- A second enabled entry for the same connector and domain keeps the first and logs
  `write_target_duplicate_domain`.

### Skip reasons (logged, never registered as advisory)

`connector_advisory` (Government account, no `deployments/write` permission, manage disabled),
`gateway_not_registered`, `gateway_cloud_mismatch`, `foundry_config_invalid`,
`foundry_config_incomplete`, `write_target_duplicate_domain`, `write_targets_store_unavailable`.
The other entries still register.

## Enabling per profile

| Profile | Switch | Env fallback |
|---|---|---|
| Compose | `NS_WRITE_TARGETS_FROM_STORE=true` in the shell or `.env` | `NS_FOUNDRY_*`, `NS_APIM_*` passed through |
| Helm | `--set writeTargets.fromStore=true` | `writeTargets.foundry.*`, `writeTargets.apim.*` |
| Hosted demo Bicep | parameter `writeTargetsFromStore=true` | none (stored entries only) |

No profile defaults to on. New variables for `.env.example` (an agent cannot edit it):
`NS_WRITE_TARGETS_FROM_STORE`, `NS_FOUNDRY_SUBSCRIPTION_ID`, `NS_FOUNDRY_RESOURCE_GROUP`,
`NS_FOUNDRY_ACCOUNT`, `NS_FOUNDRY_LOCATION`, `NS_APIM_GATEWAY_ID`, `NS_APIM_DOMAIN_ID` (the two
`*_ENABLED` names already existed). All are names and ids; auth is the workload identity.

## Operator-owned role assignments (not granted by IaC here)

- Foundry: a Cognitive Services contributor-class role on the account for the workload identity.
- APIM: API Management Service Contributor on the service.

The connectors read their own permissions at startup; a shortfall yields the advisory connector
(`connector_advisory`) and the intents stay advisory.

## Rollback

Unset `NS_WRITE_TARGETS_FROM_STORE` and restart (env fallback or an empty registry). To stop
execution without a restart use the kill switch.

## What was and was not proven

Proven locally with fakes and the Cosmos emulator (`tests/integration/actions/test_write_targets_from_store.py`):
draft, approval by a second principal, kill-switch check, apply and read-back verify against fake
ARM seams whose state changes; self-approval, a disabled kill switch and a missing approval each
stop the apply before the connector is called. Registration from stored entries is covered by
`services/workers/tests/write_targets_worker` and `services/api/tests/write_targets_runtime`.

OPEN (needs `NS_LIVE_APPROVED=1`, an approved Limitlessdata target and the role assignments above):
any live Foundry or APIM write from a stored entry, a hosted profile with the switch on, a second
live gateway. Government stays advisory by design.
