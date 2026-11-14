---
name: PRP-58-hosted-data-path-and-environment-hardening
status: backlog
priority: P1
order: 46
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-03, NS-10
depends_on: [PRP-41-producer-registry, PRP-42-connector-configuration-and-credential-references, PRP-44-platform-configuration, PRP-15-recommendations-engine, PRP-54-write-targets-from-configuration]
wave: W18
branch: prp-58-hosted-data-path
allow_parallel: true
issues: [252, 136, 143, 144, 220]
---

# PRP-58: Hosted data path and environment hardening

## Goal
Make the hosted and customer profiles run the real data path that PRP-41, 42, 44 and 15 built, and close the agent-doable hardening backlog of the hosted environment. Concretely: the connector roles (`gateway_poll`, `foundry_discovery`, `billing_export`) and the recommendations role are switchable in the hosted Bicep, the App Service profile and the Helm chart, with the managed-identity role assignments they need; the ingest edge reads producers from the admin store in every profile; `/readyz` stops probing localhost outside local (#143); the hosted demo scripts get the review fixes of #136 and the teardown, register and smoke follow-ups of #144; and a G04 live gate script exists for Azure Monitor, Foundry discovery and billing export (#220). It ships IaC, scripts and offline tests only: the live deploy, the G04 run and every operator check are OPEN and handed to PRP-64. It is for the operator whose hosted stack today answers 503 on ingest and runs no connector or recommendations role (lane-d step 2).

Out of scope: the producer, connector and platform APIs themselves (PRP-41, 42, 44); the Key Vault secret reader and connector settings pickup (PRP-42); write-target profile wiring (PRP-54); sandbox seed and grant scripts including the hosted-seeding bullets of #136 (`scripts/sandbox/**`, PRP-38 owns it; file them as an issue if still wanted); an OTel collector deployment (compose profile only); CI deploy workflow (PRP-63); the live deploy, G04 run, viewer 403 test user, App Service logs in Log Analytics and every other operator-only bullet of #144 and #136 (PRP-64); the PRP-52 hardening of `infra/bicep/modules/**` and Dockerfiles.

## Why
- Hosted ingest is dead: `infra/demo` and `infra/appservice` never set a producers source, so every ingest route is 503 (lane-d step 1 and 2); PRP-41 adds the store switch `NS_INGEST_PRODUCER_STORE`, which no profile sets yet.
- No profile runs a connector role: hosted `NS_WORKER_ROLES` is `ingestion,projections,aggregates,actions,hitl_timers,lifecycle,evaluation` (`infra/demo/main.bicep:273`), Helm `workers.roles` is empty (`infra/helm/values.yaml:150`), and neither wires the managed-identity roles the roles need (#220: Foundry project read, `Storage Blob Data Reader` on the export container, Key Vault Secrets User for the producer secret).
- Recommendations are not hosted: the role needs `NS_WORKER_REC_DATA_DIR` sandbox files the hosted image lacks (`infra/demo/main.bicep:258-261`); PRP-15 adds `NS_WORKER_REC_SOURCE=archive` and names this PRP as the one that turns it on.
- `/readyz` probes default to localhost: `health/probes.py:28-30` falls back to `localhost:8081`, `:5672`, `:10000`; only `infra/demo/main.bicep:302-306` sets `NS_PROBE_*`, so App Service and Helm deployments sit at 503 (#143, found live in PRP-32 S9).
- Review debt in the hosted scripts and templates: `publicNetworkAccess` compiles to null for `Enabled` (`infra/appservice/main.bicep:182,219,254`), the smoke `/readyz` check accepts any non-200 (`scripts/gates/_hosted_demo_smoke.py:307-314`), the budget `startDate` is unvalidated (`infra/demo/modules/budget.bicep:12`), `RegisterBook.remove` is local only (`scripts/gates/_hosted_demo_common.py:338-344`), and teardown refuses on the Defender-for-Storage system topic (#136, #144).
- No G04 evidence exists and no gate script exists for it (`docs/evidence/G04/` absent; lane-d gate register, #220).

## Acceptance criteria
- [ ] Given `NS_ENV` is not `local` and a `NS_PROBE_*` variable is unset, When `/readyz` runs, Then that probe reports reason `probe_unconfigured` and no connection to localhost is attempted; given `NS_ENV=local` the emulator defaults apply as today (`services/api/tests/health` passes unchanged).
- [ ] Helm values `probes.{cosmosUrl,eventHubsHostPort,blobHostPort}` and App Service parameters of the same meaning render `NS_PROBE_*`; with the CI values every rendered probe value is a non-empty non-localhost host or the chart fails with a clear message when `probes.required=true`; a test asserts no rendered `NS_PROBE_*` contains `localhost` (#143 bullets 1 to 3).
- [ ] `infra/demo/main.bicep` gains `connectorRoles` (subset of the three connector role names, default empty), `recommendationsEnabled` (default false), `foundryAccountIds` (array, default empty), `billingExportStorageAccountId` (default empty); `NS_WORKER_ROLES` is composed from the base list plus these, `NS_INGEST_PRODUCER_STORE=true` and `NS_WORKER_CONNECTOR_CONFIG_SOURCE=auto` are set on the right sites, `NS_API_BASE_URL` points the workers at `apiUpstream`, and `NS_WORKER_REC_SOURCE=archive` is set when recommendations are on; `az bicep build` passes and defaults leave the deployed settings unchanged except the two store switches.
- [ ] A new module `infra/demo/modules/connector-rbac.bicep` assigns, to the workers identity only: `Storage Blob Data Reader` on `billingExportStorageAccountId`, and the Foundry reader role (`Azure AI User`; role definition id verified against Microsoft Learn at session start) on each `foundryAccountIds` entry, at those scopes and nothing wider; the vault role already exists (`keyvault-rbac.bicep`); a template test asserts no subscription-scope or resource-group-scope assignment is created for these.
- [ ] The Helm chart documents and renders the same switches for the workers (`workers.roles` list helper, `workers.recommendations.source`, ingest store switch, API base URL) and the App Service profile exposes them as parameters; all three profiles pass a parity test that every new `NS_*` name appears in compose, Helm and Bicep; no profile defaults a connector role on.
- [ ] `GENERATED_PARAMS` in `scripts/gates/_hosted_demo_common.py` lists every new `infra/demo/main.bicep` parameter (including the hosted evaluation pilot params `evaluationPilotDomainId`, `evaluationPilotSubjectId`, `evaluationPilotDatasetIds`, PRP-16 leftover) and the existing check against the template passes; `plan` accepts the matching CLI flags.
- [ ] Smoke: the `/readyz-not-proxied` check asserts exactly 404 (`/readyz/` hits the SPA fallback and must not pass), `HealthCheckStatus` has a bounded retry, an unauthenticated POST to the ingest edge must answer 401 (not 503), and the az-error scrub keeps no resource-group, site or tenant name (allowlist, #144); `RefusedError` runs write an evidence file with the refused attempt and no secret (#136).
- [ ] Teardown: a platform-managed child (Defender for Storage Event Grid system topic whose source is the demo storage account) is classified `platform_managed`, never deleted by the script and never treated as "not ours"; teardown proceeds to delete the storage account and reports the child as left to the platform; unknown foreign resources still refuse. `RegisterBook.remove` also deletes the Cosmos backend rows (`remove_rows`), tolerant of not-found (#144).
- [ ] App Service profile: `publicNetworkAccess` emits `'Enabled'` explicitly so a redeploy resets a `Disabled` site; `*AppSettings` precedence is documented as last wins; the budget `startDate` is validated as `yyyy-MM-01T00:00:00Z` in `plan` and documented; the `dailyQuotaGb` 1 GB floor and the public Log Analytics endpoints are recorded as accepted exceptions in `docs/deploy/hosted-demo.md` (#136).
- [ ] `scripts/gates/g04_connectors_live.py` refuses without `NS_LIVE_APPROVED=1` before any import of Azure code, requires a budget cap and per-connector `--approve-step`, runs the contract kit read paths for `azure-monitor`, `foundry-discovery` and `billing-export` only against an operator-named Commercial target, writes scrubbed evidence under `docs/evidence/G04/`, and exits `2` refused, `3` open, `0` only after a real run; offline tests cover refusal, argument handling, scrubbing and the Government refusal. No live run happens in this PRP.
- [ ] `docs/deploy/hosted-demo.md` describes the new parameters, the connector onboarding order (deploy, grant yourself admin, create producer, put its secret in Key Vault, create connector config) and marks every live step OPEN.
- PRP exit: touched suites, `az bicep build` for both templates, `helm template` tests, ruff, pyright, `validate_planning.py` pass; PR open with CI green including `helm`; live items written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where connector and ingest enablement lives | Env per connector in IaC; stored config | Stored config is the source (PRP-42); IaC only enables roles, identities, the store switches and the API base URL (lane-d unit G, "enabled through unit C") |
| 2 | Refuse emulator probe defaults outside local | Keep silent defaults; fail with `probe_unconfigured` | Fail with `probe_unconfigured` (#143 bullet 3): a missing setting must be obvious; local behaviour unchanged |
| 3 | Defender-for-Storage topic at teardown | Delete it; delete parent and leave it; refuse | Never delete security tooling: classify it `platform_managed`, delete the storage account and leave cleanup to the platform. ASSUMPTION: the platform removes the system topic with its source resource; the live proof is operator-owned (PRP-64) |
| 4 | Hosted recommendations | Role on in all hosted; opt-in | Opt-in `recommendationsEnabled` (default false) with `NS_WORKER_REC_SOURCE=archive` (A4); the seeder still feeds a demo that leaves it off |
| 5 | Foundry reader role | Reader on resource group; per-account | Per account (`foundryAccountIds`), least privilege; accounts may live in another subscription, so the module is deployed at each account's scope |
| 6 | Sandbox hosted-seeding bullets of #136 | Fix here; leave | Leave: `scripts/sandbox/**` is PRP-38's; reported as unassigned |
| 7 | Compose change | None; parity only | `docker-compose.yml` only passes the new env names through, defaults off, for the parity test (Tier-1 for the wave) |

## Context manifest

### Files to read first
- `infra/demo/main.bicep:225-330,384-440` - settings vars, two-pass App Service, probe vars, RBAC modules.
- `infra/appservice/main.bicep:60-285` - `*AppSettings` merge, `publicNetworkAccess`, outputs (`apiHostName`).
- `infra/demo/modules/{keyvault-rbac,cosmos-rbac,budget}.bicep` - RBAC module shape to copy.
- `infra/helm/values.yaml:40-175`, `infra/helm/templates/deployment.yaml:44-205`, `infra/helm/ci/values-ci.yaml`.
- `services/api/neurosphere_api/health/probes.py` and `health/router.py:12-60`.
- `scripts/gates/_hosted_demo_common.py:40-80,296-370`, `_hosted_demo_smoke.py:230-330`, `hosted_demo.py:690-770,1738-1800`.
- `scripts/gates/g16_judge_live.py` (refusal-first structure) and `g17_apim_observe_live.py` (budget, approvals, evidence).
- `docs/deploy/hosted-demo.md`, `tests/unit/hosted_demo/test_demo_composition.py`, `tests/unit/infra/test_helm_render.py`.
- PRPs 41, 42, 15 "Interfaces provided" (env names).

### Interfaces consumed
- PRP-41: `NS_INGEST_PRODUCER_STORE`, `NS_INGEST_PRODUCER_REFRESH_SECONDS`; PRP-42: `NS_WORKER_CONNECTOR_CONFIG_SOURCE`, worker roles read stored connector config and need Key Vault Secrets User plus the identity roles of this PRP; PRP-44: nothing new in infra; PRP-15: `NS_WORKER_REC_SOURCE`, `NS_WORKER_REC_LOOKBACK_DAYS`; PRP-54: `NS_WRITE_TARGETS_FROM_STORE` (already wired there; this PRP must not duplicate it).
- Shipped: worker roles `foundry_discovery`, `billing_export`, `gateway_poll` (`services/workers/neurosphere_workers/runtime/roles.py:19-31`), `keyVaultRbac` and `cosmosRbac` modules, the D9 parameter list, `HostedSmoke`, `RegisterBook`, the connector contract kit (`connectors/sdk-python`).

### Interfaces provided
- Bicep parameters on `infra/demo/main.bicep`: `connectorRoles`, `recommendationsEnabled`, `foundryAccountIds`, `billingExportStorageAccountId`; module `connector-rbac.bicep`.
- Helm values `probes.*`, `workers.recommendations.source`, `ingest.producerStore`, `workers.apiBaseUrl`; App Service parameters `probeCosmosUrl`, `probeEventHubsHostPort`, `probeBlobHostPort`.
- Probe reason code `probe_unconfigured`.
- `scripts/gates/g04_connectors_live.py` with evidence under `docs/evidence/G04/` (written only by an operator run); `docs/connectors/coverage.md` row text for PRP-64.
- CLI flags on `hosted_demo.py plan`/`deploy`: `--connector-roles`, `--foundry-account-ids`, `--billing-export-storage-account-id`, `--recommendations`, `--evaluation-pilot-*`.

### Patterns to match
- Probe settings from module outputs, cloud-agnostic: `infra/demo/main.bicep:296-306`.
- Conditional settings object: `evaluationPilotSettings` (`main.bicep:262-269`); conditional env array `infra/appservice/main.bicep:146`.
- RBAC module and its dependsOn: `main.bicep:384-428`.
- Refusal-first live script: `scripts/gates/g16_judge_live.py:1-98`; tests `tests/unit/gates/test_g05_live_refuses.py`.
- Smoke check with injectable transport: `_hosted_demo_smoke.py:299-312` and `tests/unit/gates/test_hosted_demo_smoke.py`.

### Gotchas
- Changing `infra/appservice/main.bicep` or `infra/demo/main.bicep` moves goldens: `tests/unit/hosted_demo/core_main_resources.golden.json` and `appservice_default_profile.json`; regenerate deliberately and review the diff.
- D9: every `infra/demo/main.bicep` parameter must be in `_hosted_demo_common.py` `GENERATED_PARAMS`; the hosted-demo tests check it. Parameters only a human sets still need an entry or an explicit exclusion in that list.
- The two-pass App Service declaration repeats settings: add every new setting to the second pass var, and keep the bootstrap pass unchanged so ordering is unchanged.
- `ReasonCode` is a closed Literal in `health/probes.py`; extending it needs the health tests that pin the set (`services/api/tests/health`).
- Never use a hard-coded host suffix; derive from `environment().suffixes` or module outputs.
- Role assignments to resources in another subscription need their own deployment scope; deploy the module per account id with `scope: resourceGroup(...)`, or document the one-line operator `az role assignment create` where the deploying principal lacks rights.
- A Defender-managed child is security tooling: the script must never issue a delete for it, in a dry run or otherwise.
- `.env.example` is agent-blocked; `docker-compose.yml` is shared across worktrees (this PRP holds the stack for W18; no compose run is needed here).
- New test directories need unique names: `tests/unit/hosted_data_path`, `services/api/tests/health_probe_config`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - infra/demo/**
  - infra/appservice/**
  - scripts/gates/hosted_demo.py
  - scripts/gates/hosted_demo_seed.py
  - scripts/gates/_hosted_demo_common.py
  - scripts/gates/_hosted_demo_smoke.py
  - scripts/gates/g04_connectors_live.py
  - services/api/neurosphere_api/health/probes.py
  - services/api/tests/health_probe_config/**
  - tests/unit/hosted_data_path/**
  - tests/unit/hosted_demo/**
  - tests/unit/gates/test_g04_connectors_live.py
  - tests/unit/gates/test_hosted_demo_smoke.py
  - tests/unit/gates/test_hosted_demo_teardown.py
  - tests/unit/gates/test_hosted_demo_flow.py
  - docs/deploy/hosted-demo.md
  - docs/connectors/coverage.md
tier1:
  - infra/demo/main.bicep
  - infra/appservice/main.bicep
  - infra/helm/**
  - docker-compose.yml
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - infra/bicep/modules/**
  - scripts/sandbox/**
  - services/workers/neurosphere_workers/**
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/admin/**
  - services/api/neurosphere_api/health/router.py
  - packages/contracts/**
  - .github/workflows/**
  - docs/evidence/**
  - tests/unit/infra/**
```

## Implementation blueprint

Parallelization: items 1, 2 and 5 [P] (probes, hosted data path in Bicep, hosted script hardening share no file). Item 3 after 2 (Helm and App Service mirror the Bicep names). Item 4 after 3 for the parity test. Item 6 [P] with 5 after the script constants exist. Item 7 last.

### Item 1 - Probe defaults (#143)  [P]
- Deliverable: `probes_from_env` takes the environment and returns `probe_unconfigured` probes outside local when a setting is missing; `ReasonCode` gains the code; no localhost fallback outside `NS_ENV=local`.
- Owned files: `services/api/neurosphere_api/health/probes.py`, `services/api/tests/health_probe_config/**`.
- Must NOT touch: `health/router.py`.
- Depends on: none.
- Acceptance criteria: criterion 1; `/readyz` body carries only the enumerated reason; existing `services/api/tests/health` and `tests/integration/health` pass unchanged.
- Tests: `services/api/tests/health_probe_config`, `services/api/tests/health`, `tests/integration/health`.
- Pattern references: `probes.py:105-120`.

### Item 2 - Hosted data path in the demo Bicep  [P]
- Deliverable: new parameters and composed settings in `infra/demo/main.bicep` (roles, ingest store switch, config source, API base URL, recommendations source), `modules/connector-rbac.bicep`, outputs, and the matching `GENERATED_PARAMS` entries and CLI flags in the hosted scripts.
- Owned files: `infra/demo/**`, `scripts/gates/_hosted_demo_common.py` (parameter list only), `scripts/gates/hosted_demo.py` (flags and plan wiring only), `tests/unit/hosted_demo/**`, `tests/unit/hosted_data_path/test_demo_data_path.py`.
- Must NOT touch: `infra/bicep/modules/**`, `infra/appservice/main.bicep` beyond item 3.
- Depends on: PRPs 41, 42, 15 merged.
- Acceptance criteria: criteria 3, 4 and 6; with defaults the plan output differs from before only by the two store switches; the role module creates only the scoped assignments.
- Tests: `tests/unit/hosted_demo`, `tests/unit/hosted_data_path`, `tests/unit/gates/test_hosted_demo_flow.py` (az-dependent tests follow the existing skip rules; CI has `az`).
- Pattern references: `main.bicep:262-306,384-428`, `modules/keyvault-rbac.bicep`.

### Item 3 - App Service and Helm profiles
- Deliverable: App Service parameters for probes, roles and the same switches, explicit `'Enabled'` for `publicNetworkAccess`, "last wins" documented; Helm values and template for probes, worker roles, recommendations source, ingest store switch, API base URL, with `probes.required` and the CI values updated; goldens regenerated.
- Owned files: `infra/appservice/**`, `infra/helm/**`, `tests/unit/hosted_data_path/test_helm_data_path.py`, `tests/unit/hosted_data_path/test_appservice_profile.py`.
- Must NOT touch: `infra/helm/templates/networkpolicy.yaml` semantics (PRP-52), `infra/bicep/modules/**`.
- Depends on: item 2.
- Acceptance criteria: criteria 2, 5 (App Service and Helm halves) and 9 (public access); `helm template` with defaults is unchanged except documented additions.
- Tests: `tests/unit/hosted_data_path`, `tests/unit/hosted_demo`, `tests/unit/infra` (read only, must still pass).
- Pattern references: `deployment.yaml:94-142`, `infra/appservice/main.bicep:146,153`.

### Item 4 - Compose parity and profile parity test
- Deliverable: `docker-compose.yml` passes the new names through (defaults off); a parity test that every new `NS_*` name appears in compose, Helm and Bicep and none matches the secret-name pattern.
- Owned files: `docker-compose.yml`, `tests/unit/hosted_data_path/test_profile_parity.py`.
- Must NOT touch: compose service topology, ports, healthchecks.
- Depends on: item 3.
- Acceptance criteria: criterion 5 parity half; `docker compose config` still parses (unit test through the existing compose-parse helper if present, else a YAML load).
- Tests: `tests/unit/hosted_data_path`, `tests/integration/compose`.
- Pattern references: `docker-compose.yml:160-170`.

### Item 5 - Hosted script hardening (#136, #144 agent-doable)  [P]
- Deliverable: smoke checks (exact 404, bounded `HealthCheckStatus` retry, ingest-401 check, scrub allowlist), evidence on `RefusedError`, budget `startDate` validation, `platform_managed` classification and teardown path, `RegisterBook` backend row delete, doc notes.
- Owned files: `scripts/gates/_hosted_demo_smoke.py`, `scripts/gates/_hosted_demo_common.py` (smoke, register and classification code only), `scripts/gates/hosted_demo.py` (teardown and refusal paths only), `tests/unit/gates/test_hosted_demo_{smoke,teardown,flow}.py`, `docs/deploy/hosted-demo.md`.
- Must NOT touch: `scripts/sandbox/**`, `hosted_demo_seed.py` behaviour.
- Depends on: none (serialize `_hosted_demo_common.py` and `hosted_demo.py` edits after item 2 within one session).
- Acceptance criteria: criteria 7, 8 and the budget half of 9; a test proves no delete call is ever issued for a `systemTopics` resource; foreign unknown resources still refuse.
- Tests: `tests/unit/gates` (hosted_demo files), `tests/unit/hosted_demo`.
- Pattern references: `hosted_demo.py:690-730`, `_hosted_demo_common.py:296-370`.

### Item 6 - G04 live gate script  [P]
- Deliverable: `scripts/gates/g04_connectors_live.py` and offline tests; a section in `docs/connectors/coverage.md` stating what a run proves and that it is OPEN.
- Owned files: `scripts/gates/g04_connectors_live.py`, `tests/unit/gates/test_g04_connectors_live.py`, `docs/connectors/coverage.md`.
- Must NOT touch: `docs/evidence/**` (an operator run writes there), connector source.
- Depends on: none.
- Acceptance criteria: criterion 10; refusal is the first statement of `main` (module imports `os` and `sys` only at top level); evidence is scrubbed of subscription, tenant and resource names; Government is refused for billing and Foundry per the connectors' own gates.
- Tests: `tests/unit/gates/test_g04_connectors_live.py`, `tests/unit/gates/test_g05_live_refuses.py` (pattern).
- Pattern references: `g16_judge_live.py`, `g17_apim_observe_live.py` budget and approval handling.

### Item 7 - Integration and close-out
- Deliverable: rebase, `mkdocs.yml` nav if a page was added, CHANGELOG entry (also resolve the `TODO(operator)` note only if the operator supplied ids, else keep it listed), regenerate Tier-3 files (status table, `PRPs/INDEX.md`, `docs/reference/**` if touched), completion note with "Env vars for the operator", the operator checklist for PRP-64 (hosted redeploy, G04 run, viewer 403 user, App Service logs, S6 rerun, drift check) and the unassigned #136 sandbox bullets.
- Owned files: this PRP file, Tier-3 files per reference section 2, `docs/deploy/hosted-demo.md`.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green; #143 closeable, #220 and #144 and #136 commented with exact open bullets.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/health_probe_config services/api/tests/health tests/unit/hosted_data_path tests/unit/hosted_demo tests/unit/gates tests/unit/infra tests/integration/health tests/integration/compose
az bicep build --file infra/demo/main.bicep --stdout > /dev/null
az bicep build --file infra/appservice/main.bicep --stdout > /dev/null
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No `docker compose up` is needed; no Azure resource is created.

## Migration and rollback
Template changes are parameter-gated and default to the current deployment, except the explicit `'Enabled'` public access (a redeploy now resets a manually disabled site, the intended fix) and the two store switches (inert until PRP-41 and PRP-42 are deployed). Rollback: revert the PR; the next `plan` shows the diff. `probe_unconfigured` is a behaviour change outside local: a deployment that never set `NS_PROBE_*` stays not-ready with a clear reason, as it already was with a silent failure.

## Live and open gates
OPEN and handed to PRP-64 (each needs `NS_LIVE_APPROVED=1` and per-step operator approval; spend is pre-authorized but each run logs a cap and a spend row): the hosted redeploy with these parameters; the G04 run for Azure Monitor, Foundry discovery and billing export against Limitlessdata; hosted ingest smoke with a created producer; the Defender-topic teardown proof; App Service logs in Log Analytics; viewer 403 test user; S6 `seed-access` rerun; copilot approved-endpoint row; drift confirm; Defender cost note (#144, #136). A Cost Management export and a Foundry project are operator-created prerequisites, listed in the runbook.

## NOT building
A deploy workflow (PRP-63); connector or producer logic; Key Vault secret creation; an OTel collector deployment; Government hosted profile changes beyond the shared parameters; `scripts/sandbox/**` fixes; AMPLS for Log Analytics; changes to `infra/bicep/modules/**`; any live Azure call.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 3 is an ASSUMPTION for plan approval; the `Azure AI User` role id must be verified against Learn at session start)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
