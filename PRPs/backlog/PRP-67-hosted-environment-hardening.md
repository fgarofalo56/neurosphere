---
name: PRP-67-hosted-environment-hardening
status: backlog
priority: P2
order: 55
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-10, NS-01
depends_on: [PRP-58-hosted-data-path-and-environment-hardening]
wave: W20
branch: prp-67-hosted-hardening
allow_parallel: true
issues: [266, 136, 143, 144]
---

# PRP-67: Hosted environment hardening

## Goal
Close the agent-doable hardening backlog of the hosted environment that PRP-32 left open: `/readyz` stops probing localhost outside local and every profile (App Service, Helm) carries its probe settings (#143); the App Service template, budget module, hosted smoke, teardown and ownership register get the review fixes of #136 and the code follow-ups of #144; and the hosted sandbox scripts stop leaking raw tracebacks and tighten their credential guard (the `scripts/sandbox/` bullets of #136 that no earlier PRP owned). It ships templates, scripts and offline tests only; every live step stays OPEN. It is for the operator who today sees a 503 `/readyz` on a customer profile with no explanation, a teardown that refuses on the Defender-for-Storage system topic, and hosted seed scripts that crash with Azure stack traces. It is split out of the original PRP-58 and runs in W20 after PRP-58 has merged, beside PRP-69 (MCP client code only, no shared file). In W20 it is the Tier-1 owner of `infra/demo/**`, `infra/appservice/main.bicep` and `infra/helm/**`.

Out of scope: the hosted data path, connector roles, identities and the G04 script (PRP-58); sandbox seed and grant scripts' behaviour other than the error-handling and guard bullets below (PRP-38 owns them in W12); the CI deploy workflow (PRP-63); the live deploy and every operator-only bullet of #144 and #136 (App Service logs missing in Log Analytics, viewer-only 403 test user, S6 `seed-access` rerun, copilot `approved_endpoint` row and `NS_COPILOT_MODEL_FEATURE`/`NS_COPILOT_SKU` confirmation, drift confirmation, Defender cost note, Entra redirect and Foundry role leftover check: PRP-66, with the live proof of the Defender-topic teardown); the PRP-52 hardening of `infra/bicep/modules/**`.

## Why
- `/readyz` probes default to localhost: `services/api/neurosphere_api/health/probes.py:28-30` falls back to `localhost:8081`, `:5672`, `:10000` and `probes_from_env` (`probes.py:105-120`) reads `NS_PROBE_*` with those defaults; only `infra/demo/main.bicep:302-306` sets them, so App Service and Helm deployments sit at 503 (#143, found live in PRP-32 S9). `ReasonCode` has no `probe_unconfigured` (`probes.py:26`).
- `publicNetworkAccess` compiles to null for `Enabled` (`infra/appservice/main.bicep:182,219,254`), so a redeploy cannot reset a site someone set to `Disabled` (#136).
- The smoke `/readyz` check passes on any non-200 (`scripts/gates/_hosted_demo_smoke.py:307-314`) while nginx answers 200 on `/readyz/` through the SPA fallback; the az-error scrub removes ids, URLs and GUIDs but not resource-group, site or tenant names (#136, #144).
- `RefusedError` is caught at `scripts/gates/hosted_demo.py:1975-1977`, prints to stderr and returns 2 without writing evidence; teardown refuses while the Defender-for-Storage system topic exists (`hosted_demo.py:1738-1775` ours/not-ours split; `foreign_live_ids`), and `RegisterBook.remove` drops local rows only (`scripts/gates/_hosted_demo_common.py:338-344`; the Cosmos mirror is upsert-only) (#136, #144).
- Verified open in the sandbox scripts (the lane-F triage marked them UNVERIFIED): `scripts/sandbox/sbx_grant_operator.py` `_main_hosted` (`:243-309`) catches only `GuardError` and `(ValueError, KeyError)`, so Azure, httpx and OS errors surface as tracebacks; `fetch_pseudonym_secret` (`:183-213`) calls `response.json()` unguarded, so a non-JSON 200 raises `ValueError` that the grant path misreports as "invalid role, profile or identifier" and the seed path (`scripts/sandbox/sbx_seed_stack.py:1623-1627`, catches only `AzureError, HTTPError, OSError`) does not catch at all; the hosted seed prints `FAILED: {type}: {exc}` (`sbx_seed_stack.py:1635`); `CREDENTIAL_ENV_NAMES` (`scripts/sandbox/sbx_guard.py:115-122`) lacks the Entra client-secret variable.
- Dropped as already resolved: the `NS_UI_HEALTH_OUT_DIR` knob of #136 (no occurrence in code, templates or scripts; only a historical evidence note names the nginx path) and "does the CI job have `az`" (`.github/workflows/ci.yml:40-49`: `az` is preinstalled and the tests fail rather than skip, #100).

## Acceptance criteria
- [ ] Given `NS_ENV` is not `local` and a `NS_PROBE_*` variable is unset, When `/readyz` runs, Then that probe reports reason `probe_unconfigured` and no connection to localhost is attempted; given `NS_ENV=local` the emulator defaults apply as today (`services/api/tests/health` passes unchanged) (#143 bullet 3).
- [ ] Helm values `probes.{cosmosUrl,eventHubsHostPort,blobHostPort}` and App Service parameters of the same meaning render `NS_PROBE_*`; with the CI values every rendered probe value is a non-empty non-localhost host, or the chart fails with a clear message when `probes.required=true`; a test asserts no rendered `NS_PROBE_*` contains `localhost` (#143 bullets 1 and 2 and the closing test requirement).
- [ ] App Service profile: `publicNetworkAccess` emits `'Enabled'` explicitly so a redeploy resets a `Disabled` site; `*AppSettings` precedence is documented as last wins; the `dailyQuotaGb` 1 GB floor and the public Log Analytics endpoints are recorded as accepted exceptions in `docs/deploy/hosted-demo.md` (#136).
- [ ] The budget `startDate` is validated as `yyyy-MM-01T00:00:00Z` in `plan` (refused with a clear message, nothing changed) and documented (#136).
- [ ] Smoke: the `/readyz-not-proxied` check asserts exactly 404 (`/readyz/` hitting the SPA fallback must not pass), `HealthCheckStatus` has a bounded retry, an unauthenticated POST to the ingest edge answers 401 (not 503), and the az-error scrub keeps no resource-group, site or tenant name (allowlist) (#136, #144).
- [ ] `RefusedError` runs write an evidence file recording the refused attempt and no secret; exit code stays 2 and nothing was changed (#136).
- [ ] Teardown: a platform-managed child (Defender for Storage Event Grid system topic whose source is the demo storage account) is classified `platform_managed`, never deleted by the script, in a dry run or otherwise, and never treated as "not ours"; teardown proceeds to delete the storage account and reports the child as left to the platform; unknown foreign resources still refuse. `RegisterBook.remove` also deletes the Cosmos backend rows (`remove_rows`), tolerant of not-found (#144).
- [ ] `sbx_grant_operator` hosted mode: Azure, httpx and OS errors end as a one-line `REFUSED` or `FAILED` message with the exception type only and a non-zero exit, never a traceback; no secret value appears in output (#136 hosted-seeding bullet 1).
- [ ] `fetch_pseudonym_secret` turns a non-JSON or non-object 200 into a `GuardError`; both the grant and the seed path end with `REFUSED`, not a misleading "invalid role" message and not a traceback (#136 bullet 2).
- [ ] `sbx_seed_stack` hosted `FAILED:` lines print only the exception type (#136 bullet 3); `AZURE_CLIENT_SECRET` joins `CREDENTIAL_ENV_NAMES` so the hosted path refuses when it is set, with a test (#136 bullet 4; see clarification 5).
- [ ] `docs/deploy/hosted-demo.md` records the probe parameters, the `platform_managed` teardown behaviour and the accepted exceptions; every live step is marked OPEN.
- PRP exit: touched suites, `az bicep build` for both templates, `helm template` tests, ruff, pyright, `validate_planning.py` pass; PR open with CI green including `helm`; live items written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Refuse emulator probe defaults outside local | Keep silent defaults; fail with `probe_unconfigured` | Fail with `probe_unconfigured` (#143 bullet 3): a missing setting must be obvious; local behaviour unchanged |
| 2 | Defender-for-Storage topic at teardown | Delete it; delete parent and leave it; refuse | Never delete security tooling: classify it `platform_managed`, delete the storage account and leave cleanup to the platform. ASSUMPTION: the platform removes the system topic with its source resource; the live proof is operator-owned (PRP-66) |
| 3 | Sandbox bullets of #136 | Leave for PRP-38; take here | Take here, all of them (owner, second pass 2026-11-14): no earlier PRP owned them; PRP-38 (W12) has merged before this PRP runs, so `scripts/sandbox/**` is free |
| 4 | Verification of the UNVERIFIED #136 bullets | Trust the triage; verify | Verified against the tree on 2026-11-14 (see Why); the `NS_UI_HEALTH_OUT_DIR` bullet is dropped; the rest are open and become criteria 8 to 10. Re-verify each at session start and drop any a merged PRP already fixed, saying so in the completion note |
| 5 | `AZURE_CLIENT_SECRET` in the credential guard | Add; leave | ASSUMPTION: add (the issue asks to consider it and hosted access is Entra-only by the guard's own comment); if an operator workflow relies on a service-principal secret in the environment, the test documents the refusal message and the operator uses `az login` instead |
| 6 | #136 bullets that are not code | Build; record | Recorded, not built: brittle golden name matching (no concrete target named), a user-assigned identity for workers (design option), Log Analytics private link (accepted exception) |
| 7 | Entra redirect and Foundry role leftover check from the #144 teardown bullet | Build into teardown; operator checklist | ASSUMPTION: operator checklist (PRP-66); it needs live Entra and Foundry reads |
| 8 | Shared files with PRP-58 | Parallel edits; sequence | Sequenced: PRP-58 (W18) edits the parameter list and plan flags of `_hosted_demo_common.py` and `hosted_demo.py`; this PRP edits their smoke, register, budget and teardown code after it has merged |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/health/probes.py` and `health/router.py:12-60` - reason codes, `probes_from_env`.
- `infra/appservice/main.bicep:60-285` - `*AppSettings` merge, `publicNetworkAccess`, parameters.
- `infra/demo/main.bicep:296-306` and `infra/demo/modules/budget.bicep` - probe vars from module outputs, `startDate`.
- `infra/helm/values.yaml:40-175`, `infra/helm/templates/deployment.yaml:44-205`, `infra/helm/ci/values-ci.yaml`.
- `scripts/gates/_hosted_demo_common.py:296-370` (`RegisterBook`, `plan_removal` use), `scripts/gates/_hosted_demo_smoke.py:230-330`.
- `scripts/gates/hosted_demo.py:690-770,1738-1800,1960-1990` - ours/not-ours split, teardown, the `RefusedError` handler.
- `scripts/sandbox/sbx_grant_operator.py:183-312`, `scripts/sandbox/sbx_seed_stack.py:1600-1660`, `scripts/sandbox/sbx_guard.py:105-125,185-195`.
- `tests/unit/hosted_sandbox_guard/test_seed_stack_hosted.py`, `tests/unit/sandbox_stack/test_grant_operator.py`, `tests/unit/infra/test_helm_render.py`.
- `temp/audit/lane-f-issues-136-220.md` - the triage this PRP re-verified.

### Interfaces consumed
- PRP-58: the settled `NS_*` and parameter names in `infra/demo/main.bicep`, the Helm values and App Service parameters it added, and `GENERATED_PARAMS`; this PRP adds `NS_PROBE_*` plumbing beside them and renames nothing.
- PRP-41: the ingest edge store switch (the smoke ingest-401 check needs a deployment where producers come from the store, otherwise the edge answers 503 by design).
- Shipped: `HostedSmoke`, `RegisterBook`, `plan_removal`, `foreign_live_ids`, `remove_rows` on the register backend (verify the name at session start), `GuardError`, `hosted_pseudonym_env`.

### Interfaces provided
- Probe reason code `probe_unconfigured`; Helm values `probes.*` and `probes.required`; App Service parameters `probeCosmosUrl`, `probeEventHubsHostPort`, `probeBlobHostPort`.
- Resource classification `platform_managed` in the hosted teardown evidence.
- Refusal evidence file written by `hosted_demo.py` on `RefusedError`.
- For PRP-64 and PRP-66: the list of operator-only bullets of #136 and #144 left open (see Live and open gates).

### Patterns to match
- Probe settings from module outputs, cloud-agnostic: `infra/demo/main.bicep:296-306`.
- Probe construction and reason classification: `probes.py:105-120`.
- Conditional env array: `infra/appservice/main.bicep:146`; Helm optional env block `infra/helm/templates/deployment.yaml:94-142`.
- Smoke check with injectable transport: `_hosted_demo_smoke.py:299-312` and `tests/unit/gates/test_hosted_demo_smoke.py`.
- Hosted sandbox error wrapping: `sbx_seed_stack.py:1623-1636` (the `REFUSED` and `FAILED` shapes to copy for the grant script).

### Gotchas
- Changing `infra/appservice/main.bicep` or `infra/demo/main.bicep` moves goldens: `tests/unit/hosted_demo/core_main_resources.golden.json` and `appservice_default_profile.json`; regenerate deliberately and review the diff. PRP-58 changed them already; rebase first.
- `ReasonCode` is a closed Literal in `health/probes.py`; extending it needs the health tests that pin the set (`services/api/tests/health`).
- Never use a hard-coded host suffix; derive from `environment().suffixes` or module outputs.
- A Defender-managed child is security tooling: the script must never issue a delete for it, in a dry run or otherwise; a test proves no delete is issued for a `systemTopics` resource.
- Evidence and error output must stay scrubbed: no subscription id, tenant, resource-group or site name and no secret value; print exception types, not messages, in the sandbox scripts.
- `scripts/sandbox/` tests live in `tests/unit/sandbox_stack` and `tests/unit/hosted_sandbox_guard`; add new test files rather than reshaping existing ones.
- `.env.example` is agent-blocked; new test directories need unique names: `tests/unit/hosted_hardening`, `services/api/tests/health_probe_config`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/health/probes.py
  - services/api/tests/health_probe_config/**
  - tests/unit/hosted_hardening/**
  - scripts/sandbox/**
  - scripts/gates/hosted_demo.py
  - scripts/gates/_hosted_demo_common.py
  - scripts/gates/_hosted_demo_smoke.py
  - tests/unit/gates/test_hosted_demo_smoke.py
  - tests/unit/gates/test_hosted_demo_teardown.py
  - tests/unit/sandbox_stack/test_grant_operator.py
  - tests/unit/hosted_sandbox_guard/**
  - docs/deploy/hosted-demo.md
tier1:
  - infra/demo/**
  - infra/appservice/main.bicep
  - infra/helm/**
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - infra/bicep/modules/**
  - services/api/neurosphere_api/health/router.py
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/admin/**
  - services/workers/neurosphere_workers/**
  - scripts/gates/g04_connectors_live.py
  - packages/contracts/**
  - packages/core/**
  - .github/workflows/**
  - docs/evidence/**
  - tests/unit/infra/**
```
`scripts/gates/hosted_demo.py` and `scripts/gates/_hosted_demo_common.py` are also edited by PRP-58 (W18, parameter list and plan flags); `docs/deploy/hosted-demo.md` by PRP-58 (parameters section). The waves are sequential (this PRP depends on PRP-58), so there is no parallel edit; keep to the code named in each item.

## Implementation blueprint

Parallelization: items 1, 4 and 5 [P] (probe code, hosted gate scripts and sandbox scripts share no file). Item 2 after 1 (the Helm and App Service probe plumbing renders the setting item 1 enforces). Item 3 after 2 (same `infra/appservice/main.bicep`). Item 6 last.

### Item 1 - Probe defaults (#143)  [P]
- Deliverable: `probes_from_env` takes the environment and returns `probe_unconfigured` probes outside local when a setting is missing; `ReasonCode` gains the code; no localhost fallback outside `NS_ENV=local`.
- Owned files: `services/api/neurosphere_api/health/probes.py`, `services/api/tests/health_probe_config/**`.
- Must NOT touch: `health/router.py`.
- Depends on: none.
- Acceptance criteria: criterion 1; `/readyz` body carries only the enumerated reason; existing `services/api/tests/health` and `tests/integration/health` pass unchanged.
- Tests: `services/api/tests/health_probe_config`, `services/api/tests/health`, `tests/integration/health`.
- Pattern references: `probes.py:105-120`.

### Item 2 - Probe settings in the App Service and Helm profiles (#143)
- Deliverable: App Service parameters `probeCosmosUrl`, `probeEventHubsHostPort`, `probeBlobHostPort` rendered as `NS_PROBE_*` on the API; Helm values `probes.*` and `probes.required` with a clear failure when required and empty; CI values updated; a render test that no `NS_PROBE_*` value contains `localhost`; goldens regenerated. Hosts are derived from deployed resources or operator values, never hard-coded suffixes.
- Owned files: `infra/appservice/main.bicep`, `infra/helm/values.yaml`, `infra/helm/templates/deployment.yaml`, `infra/helm/ci/values-ci.yaml`, `tests/unit/hosted_hardening/test_helm_probes.py`, `tests/unit/hosted_hardening/test_appservice_probes.py`.
- Must NOT touch: `infra/helm/templates/networkpolicy.yaml` semantics (PRP-52), the settings PRP-58 added.
- Depends on: item 1; PRP-58 merged.
- Acceptance criteria: criterion 2; `helm template` with defaults is unchanged except the documented probe additions.
- Tests: `tests/unit/hosted_hardening`, `tests/unit/hosted_demo`, `tests/unit/infra` (read only, must still pass).
- Pattern references: `infra/demo/main.bicep:296-306`, `deployment.yaml:94-142`, `infra/appservice/main.bicep:146`.

### Item 3 - App Service review debt and accepted exceptions (#136)
- Deliverable: `publicNetworkAccess` emitted as `'Enabled'` explicitly at the three sites; "last wins" documented beside the `*AppSettings` merge; accepted-exceptions section in `docs/deploy/hosted-demo.md` (`dailyQuotaGb` floor, public Log Analytics endpoints, the two-pass identity flip recorded as a known restart); goldens regenerated.
- Owned files: `infra/appservice/main.bicep` (the three `publicNetworkAccess` lines and comments only), `docs/deploy/hosted-demo.md` (accepted exceptions section), `tests/unit/hosted_hardening/test_appservice_public_access.py`.
- Must NOT touch: `infra/demo/modules/**` behaviour, `infra/bicep/modules/**`.
- Depends on: item 2.
- Acceptance criteria: criterion 3; `az bicep build` passes; a test shows the compiled template carries `Enabled` for all three sites.
- Tests: `tests/unit/hosted_hardening`, `tests/unit/hosted_demo`.
- Pattern references: `infra/appservice/main.bicep:182,219,254`; `infra/demo/main.bicep:196-207` (existing `dailyQuotaGb` comment).

### Item 4 - Hosted gate script hardening (#136, #144)  [P]
- Deliverable: smoke checks (exact 404, bounded `HealthCheckStatus` retry, ingest-401 check, scrub allowlist); budget `startDate` validation in `plan`; evidence on `RefusedError`; `platform_managed` classification and teardown path; `RegisterBook` backend row delete; docs notes in the hosted-demo runbook.
- Owned files: `scripts/gates/_hosted_demo_smoke.py`, `scripts/gates/_hosted_demo_common.py` (smoke, register and classification code only), `scripts/gates/hosted_demo.py` (plan validation, teardown and refusal paths only), `tests/unit/gates/test_hosted_demo_smoke.py`, `tests/unit/gates/test_hosted_demo_teardown.py`, `tests/unit/hosted_hardening/test_hosted_scripts.py`, `docs/deploy/hosted-demo.md` (teardown and smoke sections; edit after item 3 within the session).
- Must NOT touch: `hosted_demo_seed.py` behaviour, `GENERATED_PARAMS` and plan flags (PRP-58), `scripts/sandbox/**` (item 5).
- Depends on: PRP-58 merged.
- Acceptance criteria: criteria 4 to 7 and the teardown and smoke part of 11; a test proves no delete call is ever issued for a `systemTopics` resource; foreign unknown resources still refuse.
- Tests: `tests/unit/gates` (hosted_demo files), `tests/unit/hosted_demo`, `tests/unit/hosted_hardening`.
- Pattern references: `hosted_demo.py:690-730,1738-1800`, `_hosted_demo_common.py:296-370`.

### Item 5 - Hosted sandbox scripts (#136)  [P]
- Deliverable: error wrapping in `sbx_grant_operator._main_hosted`; `fetch_pseudonym_secret` raising `GuardError` for non-JSON or non-object bodies; type-only `FAILED:` in the hosted seed; `AZURE_CLIENT_SECRET` in `CREDENTIAL_ENV_NAMES`; tests for each. Re-verify every bullet in the code first and drop any already fixed.
- Owned files: `scripts/sandbox/sbx_grant_operator.py`, `scripts/sandbox/sbx_seed_stack.py` (hosted `_main_hosted` path only), `scripts/sandbox/sbx_guard.py` (`CREDENTIAL_ENV_NAMES` only), `tests/unit/sandbox_stack/test_grant_operator.py`, `tests/unit/hosted_sandbox_guard/**`.
- Must NOT touch: the local (non-hosted) seed and grant paths, seed catalog content, the pseudonym derivation.
- Depends on: none.
- Acceptance criteria: criteria 8 to 10; the existing hosted and local sandbox tests pass unchanged except where a criterion changes a message; no secret value in any test output.
- Tests: `tests/unit/sandbox_stack`, `tests/unit/hosted_sandbox_guard`.
- Pattern references: `sbx_seed_stack.py:1615-1636`, `sbx_grant_operator.py:257-261`.

### Item 6 - Integration and close-out
- Deliverable: rebase on main (PRP-58 and PRP-38 merged), `mkdocs.yml` nav only if a page was added, changelog entry per reference section 6 (keep the `TODO(operator)` migration-id note at `CHANGELOG.md:368` listed unless the operator supplied ids), regenerate Tier-3 files (status table, `PRPs/INDEX.md`, `docs/reference/**` if touched), completion note with the bullets dropped as already fixed, and the operator checklist for PRP-64 and PRP-66 (viewer 403 user, App Service logs, S6 rerun, copilot row and `NS_COPILOT_*` confirm, drift check, Defender-topic teardown proof, Defender cost note, Entra redirect and Foundry role leftover check).
- Owned files: this PRP file, Tier-3 files per reference section 2, `docs/deploy/hosted-demo.md`.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green; #143 closeable; #136 and #144 commented with the exact open bullets.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/health_probe_config services/api/tests/health tests/unit/hosted_hardening tests/unit/hosted_demo tests/unit/gates tests/unit/infra tests/unit/sandbox_stack tests/unit/hosted_sandbox_guard tests/integration/health
az bicep build --file infra/demo/main.bicep --stdout > /dev/null
az bicep build --file infra/appservice/main.bicep --stdout > /dev/null
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No `docker compose up` is needed; no Azure resource is created.

## Migration and rollback
Template changes are inert or corrective: the explicit `'Enabled'` public access means a redeploy now resets a manually disabled site (the intended fix), and `probe_unconfigured` is a behaviour change outside local: a deployment that never set `NS_PROBE_*` stays not-ready with a clear reason, as it already was with a silent failure. Rollback: revert the PR; the next `plan` shows the diff. The `AZURE_CLIENT_SECRET` refusal is reverted by removing one name from the guard tuple.

## Live and open gates
OPEN, handed to PRP-66 (operator checks; each needs `NS_LIVE_APPROVED=1` and per-step operator approval): the hosted redeploy with the probe and public-access changes, the Defender-topic teardown proof, App Service logs in Log Analytics, viewer-only 403 test user, S6 `seed-access` rerun, copilot approved-endpoint row and `NS_COPILOT_MODEL_FEATURE` / `NS_COPILOT_SKU` confirmation, drift confirmation, Defender cost note, Entra redirect and Foundry role leftover check. Nothing in this PRP calls Azure.

## NOT building
The hosted data path and G04 (PRP-58); a user-assigned identity for the workers; AMPLS for Log Analytics; brittle-golden refactoring without a named target; deletion of Defender or any security tooling; changes to the local sandbox seed and grant paths; a deploy workflow (PRP-63); changes to `infra/bicep/modules/**`; any live Azure call.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 5 and 7 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
