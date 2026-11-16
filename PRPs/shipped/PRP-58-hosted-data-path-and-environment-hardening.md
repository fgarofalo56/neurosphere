---
name: PRP-58-hosted-data-path-and-environment-hardening
status: shipped
shipped: 2026-11-16
pr: 312
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
issues: [252, 220]
---

# PRP-58: Hosted data path

## Goal
Make the hosted and customer profiles run the real data path that PRP-41, 42, 44 and 15 built. Concretely: the connector roles (`gateway_poll`, `foundry_discovery`, `billing_export`) and the recommendations role are switchable in the hosted Bicep, the App Service profile and the Helm chart, with the managed-identity role assignments they need; the ingest edge reads producers from the admin store in every profile; the hosted evaluation pilot parameters are in the hosted parameter list; and a G04 live gate script exists for Azure Monitor, Foundry discovery and billing export (#220). It ships IaC, scripts and offline tests only: the live deploy and the G04 run are OPEN and handed to PRP-64. It is for the operator whose hosted stack today answers 503 on ingest and runs no connector or recommendations role (lane-d step 2). This PRP was split on 2026-11-14: the `/readyz` probe settings (#143), the hosted-script and template review fixes (#136) and the live-run follow-ups of #144 moved to PRP-67 (W20, depends on this PRP).

Out of scope: the producer, connector and platform APIs themselves (PRP-41, 42, 44); the Key Vault secret reader and connector settings pickup (PRP-42); write-target profile wiring (PRP-54); `/readyz` probe settings in every profile, the App Service `publicNetworkAccess` fix, smoke and teardown hardening, register backend delete, budget `startDate` validation and the `scripts/sandbox/**` bullets of #136 (PRP-67); an OTel collector deployment (compose profile only); CI deploy workflow (PRP-63); the live deploy and the G04 run (PRP-64); every operator-only bullet of #144 (PRP-66); the PRP-52 hardening of `infra/bicep/modules/**` and Dockerfiles.

## Why
- Hosted ingest is dead: `infra/demo` and `infra/appservice` never set a producers source, so every ingest route is 503 (lane-d step 1 and 2); PRP-41 adds the store switch `NS_INGEST_PRODUCER_STORE`, which no profile sets yet.
- No profile runs a connector role: hosted `NS_WORKER_ROLES` is `ingestion,projections,aggregates,actions,hitl_timers,lifecycle,evaluation` (`infra/demo/main.bicep:273`), Helm `workers.roles` is empty (`infra/helm/values.yaml:150`), and neither wires the managed-identity roles the roles need (#220: Foundry project read, `Storage Blob Data Reader` on the export container, Key Vault Secrets User for the producer secret).
- Recommendations are not hosted: the role needs `NS_WORKER_REC_DATA_DIR` sandbox files the hosted image lacks (`infra/demo/main.bicep:258-261`); PRP-15 adds `NS_WORKER_REC_SOURCE=archive` and names this PRP as the one that turns it on.
- The hosted evaluation pilot parameters (`evaluationPilotDomainId`, `evaluationPilotSubjectId`, `evaluationPilotDatasetIds`) are PRP-16 leftovers not in the hosted parameter list (`scripts/gates/_hosted_demo_common.py` `GENERATED_PARAMS`).
- No G04 evidence exists and no gate script exists for it (`docs/evidence/G04/` absent; lane-d gate register, #220).

## Acceptance criteria
- [x] `infra/demo/main.bicep` gains `connectorRoles` (subset of the three connector role names, default empty), `recommendationsEnabled` (default false), `foundryAccountIds` (array, default empty), `billingExportStorageAccountId` (default empty); `NS_WORKER_ROLES` is composed from the base list plus these, `NS_INGEST_PRODUCER_STORE=true` and `NS_WORKER_CONNECTOR_CONFIG_SOURCE=auto` are set on the right sites, `NS_API_BASE_URL` points the workers at `apiUpstream`, and `NS_WORKER_REC_SOURCE=archive` is set when recommendations are on; `az bicep build` passes and defaults leave the deployed settings unchanged except the two store switches.
- [x] A new module `infra/demo/modules/connector-rbac.bicep` assigns, to the workers identity only: `Storage Blob Data Reader` on `billingExportStorageAccountId`, and the Foundry reader role (`Azure AI User`; role definition id verified against Microsoft Learn at session start) on each `foundryAccountIds` entry, at those scopes and nothing wider; the vault role already exists (`keyvault-rbac.bicep`); a template test asserts no subscription-scope or resource-group-scope assignment is created for these.
- [x] The Helm chart documents and renders the same switches for the workers (`workers.roles` list helper, `workers.recommendations.source`, ingest store switch, API base URL) and the App Service profile exposes them as parameters; all three profiles pass a parity test that every new `NS_*` name appears in compose, Helm and Bicep; no profile defaults a connector role on.
- [x] `GENERATED_PARAMS` in `scripts/gates/_hosted_demo_common.py` lists every new `infra/demo/main.bicep` parameter (including the hosted evaluation pilot params `evaluationPilotDomainId`, `evaluationPilotSubjectId`, `evaluationPilotDatasetIds`, PRP-16 leftover) and the existing check against the template passes; `plan` accepts the matching CLI flags.
- [x] `scripts/gates/g04_connectors_live.py` refuses without `NS_LIVE_APPROVED=1` before any import of Azure code, requires a budget cap and per-connector `--approve-step`, runs the contract kit read paths for `azure-monitor`, `foundry-discovery` and `billing-export` only against an operator-named Commercial target, writes scrubbed evidence under `docs/evidence/G04/`, and exits `2` refused, `3` open, `0` only after a real run; offline tests cover refusal, argument handling, scrubbing and the Government refusal. No live run happens in this PRP.
- [x] `docs/deploy/hosted-demo.md` describes the new parameters, the connector onboarding order (deploy, grant yourself admin, create producer, put its secret in Key Vault, create connector config) and marks every live step OPEN.
- PRP exit: touched suites, `az bicep build` for both templates, `helm template` tests, ruff, pyright, `validate_planning.py` pass; PR open with CI green including `helm`; live items written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where connector and ingest enablement lives | Env per connector in IaC; stored config | Stored config is the source (PRP-42); IaC only enables roles, identities, the store switches and the API base URL (lane-d unit G, "enabled through unit C") |
| 2 | Hosted recommendations | Role on in all hosted; opt-in | Opt-in `recommendationsEnabled` (default false) with `NS_WORKER_REC_SOURCE=archive` (A4); the seeder still feeds a demo that leaves it off |
| 3 | Foundry reader role | Reader on resource group; per-account | Per account (`foundryAccountIds`), least privilege; accounts may live in another subscription, so the module is deployed at each account's scope |
| 4 | Compose change | None; parity only | `docker-compose.yml` only passes the new env names through, defaults off, for the parity test (Tier-1 for the wave) |
| 5 | Split of the original PRP-58 | Keep one PRP; split | Split on 2026-11-14 (owner, second pass): the probe, review-debt and live-run follow-up work is PRP-67, which depends on this PRP so the Bicep and script edits are sequenced, never parallel |
| 6 | Order of edits to `_hosted_demo_common.py` and `hosted_demo.py` | Here and PRP-67 in parallel; sequential | Sequential: this PRP edits only the parameter list and plan flags (W18); PRP-67 edits the smoke, register and teardown code (W20) after this one merges |

## Context manifest

### Files to read first
- `infra/demo/main.bicep:225-330,384-440` - settings vars, two-pass App Service, probe vars, RBAC modules.
- `infra/appservice/main.bicep:60-285` - `*AppSettings` merge and parameters; add the data-path parameters beside them.
- `infra/demo/modules/{keyvault-rbac,cosmos-rbac}.bicep` - RBAC module shape to copy.
- `infra/helm/values.yaml:40-175`, `infra/helm/templates/deployment.yaml:44-205`, `infra/helm/ci/values-ci.yaml`.
- `scripts/gates/_hosted_demo_common.py:40-80` (`GENERATED_PARAMS`) and `scripts/gates/hosted_demo.py` plan flags.
- `scripts/gates/g16_judge_live.py` (refusal-first structure) and `g17_apim_observe_live.py` (budget, approvals, evidence).
- `docs/deploy/hosted-demo.md`, `tests/unit/hosted_demo/test_demo_composition.py`, `tests/unit/infra/test_helm_render.py`.
- PRPs 41, 42, 15 "Interfaces provided" (env names).

### Interfaces consumed
- PRP-41: `NS_INGEST_PRODUCER_STORE`, `NS_INGEST_PRODUCER_REFRESH_SECONDS`; PRP-42: `NS_WORKER_CONNECTOR_CONFIG_SOURCE`, worker roles read stored connector config and need Key Vault Secrets User plus the identity roles of this PRP; PRP-44: nothing new in infra; PRP-15: `NS_WORKER_REC_SOURCE`, `NS_WORKER_REC_LOOKBACK_DAYS`; PRP-54: `NS_WRITE_TARGETS_FROM_STORE` (already wired there; this PRP must not duplicate it).
- Shipped: worker roles `foundry_discovery`, `billing_export`, `gateway_poll` (`services/workers/neurosphere_workers/runtime/roles.py:19-31`), `keyVaultRbac` and `cosmosRbac` modules, the D9 parameter list, the connector contract kit (`connectors/sdk-python`).

### Interfaces provided
- Bicep parameters on `infra/demo/main.bicep`: `connectorRoles`, `recommendationsEnabled`, `foundryAccountIds`, `billingExportStorageAccountId`; module `connector-rbac.bicep`.
- Helm values `workers.recommendations.source`, `ingest.producerStore`, `workers.apiBaseUrl`; App Service parameters for the same switches.
- `scripts/gates/g04_connectors_live.py` with evidence under `docs/evidence/G04/` (written only by an operator run); `docs/connectors/coverage.md` row text for PRP-64.
- CLI flags on `hosted_demo.py plan`/`deploy`: `--connector-roles`, `--foundry-account-ids`, `--billing-export-storage-account-id`, `--recommendations`, `--evaluation-pilot-*`.
- For PRP-67: the settled `NS_*` and parameter names, so it adds the `NS_PROBE_*` plumbing beside them without renaming anything.

### Patterns to match
- Conditional settings object: `evaluationPilotSettings` (`infra/demo/main.bicep:262-269`); conditional env array `infra/appservice/main.bicep:146`.
- RBAC module and its dependsOn: `main.bicep:384-428`.
- Refusal-first live script: `scripts/gates/g16_judge_live.py:1-98`; tests `tests/unit/gates/test_g05_live_refuses.py`.
- Helm optional env block: `infra/helm/templates/deployment.yaml:94-142`.

### Gotchas
- Changing `infra/appservice/main.bicep` or `infra/demo/main.bicep` moves goldens: `tests/unit/hosted_demo/core_main_resources.golden.json` and `appservice_default_profile.json`; regenerate deliberately and review the diff.
- D9: every `infra/demo/main.bicep` parameter must be in `_hosted_demo_common.py` `GENERATED_PARAMS`; the hosted-demo tests check it. Parameters only a human sets still need an entry or an explicit exclusion in that list.
- The two-pass App Service declaration repeats settings: add every new setting to the second pass var, and keep the bootstrap pass unchanged so ordering is unchanged.
- Never use a hard-coded host suffix; derive from `environment().suffixes` or module outputs.
- Role assignments to resources in another subscription need their own deployment scope; deploy the module per account id with `scope: resourceGroup(...)`, or document the one-line operator `az role assignment create` where the deploying principal lacks rights.
- `.env.example` is agent-blocked; `docker-compose.yml` is shared across worktrees (this PRP holds the stack for W18; no compose run is needed here).
- New test directories need unique names: `tests/unit/hosted_data_path`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - infra/demo/**
  - infra/appservice/**
  - scripts/gates/hosted_demo.py
  - scripts/gates/_hosted_demo_common.py
  - scripts/gates/g04_connectors_live.py
  - tests/unit/hosted_data_path/**
  - tests/unit/hosted_demo/**
  - tests/unit/gates/test_g04_connectors_live.py
  - tests/unit/gates/test_hosted_demo_flow.py
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
  - scripts/gates/_hosted_demo_smoke.py
  - scripts/gates/hosted_demo_seed.py
  - services/workers/neurosphere_workers/**
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/admin/**
  - services/api/neurosphere_api/health/**
  - packages/contracts/**
  - .github/workflows/**
  - docs/evidence/**
  - tests/unit/infra/**
```
`docs/deploy/hosted-demo.md` is edited here (item 1, parameters and onboarding section) and again by PRP-67 (W20, other sections); the waves are sequential, so it is listed in neither `owns` block.

## Implementation blueprint

Parallelization: items 1 and 4 [P] (hosted Bicep and the G04 script share no file). Item 2 after 1 (Helm and App Service mirror the Bicep names). Item 3 after 2 for the parity test. Item 5 last.

### Item 1 - Hosted data path in the demo Bicep  [P]
- Deliverable: new parameters and composed settings in `infra/demo/main.bicep` (roles, ingest store switch, config source, API base URL, recommendations source), `modules/connector-rbac.bicep`, outputs, the matching `GENERATED_PARAMS` entries (including the evaluation pilot params) and CLI flags in the hosted scripts, and the parameters and onboarding section of `docs/deploy/hosted-demo.md`.
- Owned files: `infra/demo/**`, `scripts/gates/_hosted_demo_common.py` (parameter list only), `scripts/gates/hosted_demo.py` (flags and plan wiring only), `tests/unit/hosted_demo/**`, `tests/unit/hosted_data_path/test_demo_data_path.py`, `docs/deploy/hosted-demo.md`.
- Must NOT touch: `infra/bicep/modules/**`, `infra/appservice/main.bicep` beyond item 2, the smoke and teardown code of the hosted scripts (PRP-67).
- Depends on: PRPs 41, 42, 15 merged.
- Acceptance criteria: criteria 1, 2, 4 and 6; with defaults the plan output differs from before only by the two store switches; the role module creates only the scoped assignments.
- Tests: `tests/unit/hosted_demo`, `tests/unit/hosted_data_path`, `tests/unit/gates/test_hosted_demo_flow.py` (az-dependent tests follow the existing skip rules; CI has `az`).
- Pattern references: `main.bicep:262-306,384-428`, `modules/keyvault-rbac.bicep`.

### Item 2 - App Service and Helm switches
- Deliverable: App Service parameters for roles and the same switches; Helm values and template for worker roles, recommendations source, ingest store switch, API base URL, with the CI values updated; goldens regenerated.
- Owned files: `infra/appservice/**`, `infra/helm/**`, `tests/unit/hosted_data_path/test_helm_data_path.py`, `tests/unit/hosted_data_path/test_appservice_profile.py`.
- Must NOT touch: `infra/helm/templates/networkpolicy.yaml` semantics (PRP-52), `infra/bicep/modules/**`, `NS_PROBE_*` and `publicNetworkAccess` (PRP-67).
- Depends on: item 1.
- Acceptance criteria: criterion 3 (App Service and Helm halves); `helm template` with defaults is unchanged except documented additions.
- Tests: `tests/unit/hosted_data_path`, `tests/unit/hosted_demo`, `tests/unit/infra` (read only, must still pass).
- Pattern references: `deployment.yaml:94-142`, `infra/appservice/main.bicep:146,153`.

### Item 3 - Compose parity and profile parity test
- Deliverable: `docker-compose.yml` passes the new names through (defaults off); a parity test that every new `NS_*` name appears in compose, Helm and Bicep and none matches the secret-name pattern.
- Owned files: `docker-compose.yml`, `tests/unit/hosted_data_path/test_profile_parity.py`.
- Must NOT touch: compose service topology, ports, healthchecks.
- Depends on: item 2.
- Acceptance criteria: criterion 3 parity half; `docker compose config` still parses (unit test through the existing compose-parse helper if present, else a YAML load).
- Tests: `tests/unit/hosted_data_path`, `tests/integration/compose`.
- Pattern references: `docker-compose.yml:160-170`.

### Item 4 - G04 live gate script  [P]
- Deliverable: `scripts/gates/g04_connectors_live.py` and offline tests; a section in `docs/connectors/coverage.md` stating what a run proves and that it is OPEN.
- Owned files: `scripts/gates/g04_connectors_live.py`, `tests/unit/gates/test_g04_connectors_live.py`, `docs/connectors/coverage.md`.
- Must NOT touch: `docs/evidence/**` (an operator run writes there), connector source.
- Depends on: none.
- Acceptance criteria: criterion 5; refusal is the first statement of `main` (module imports `os` and `sys` only at top level); evidence is scrubbed of subscription, tenant and resource names; Government is refused for billing and Foundry per the connectors' own gates.
- Tests: `tests/unit/gates/test_g04_connectors_live.py`, `tests/unit/gates/test_g05_live_refuses.py` (pattern).
- Pattern references: `g16_judge_live.py`, `g17_apim_observe_live.py` budget and approval handling.

### Item 5 - Integration and close-out
- Deliverable: rebase, `mkdocs.yml` nav if a page was added, changelog entry per reference section 6, regenerate Tier-3 files (status table, `PRPs/INDEX.md`, `docs/reference/**` if touched), completion note with "Env vars for the operator", and the operator checklist for PRP-64 (hosted redeploy with these parameters, G04 run, hosted ingest smoke with a created producer).
- Owned files: this PRP file, Tier-3 files per reference section 2, `docs/deploy/hosted-demo.md`.
- Depends on: items 1-4.
- Acceptance criteria: validation gates pass; CI green; #220 commented with the exact open bullets.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/hosted_data_path tests/unit/hosted_demo tests/unit/gates tests/unit/infra tests/integration/compose
az bicep build --file infra/demo/main.bicep --stdout > /dev/null
az bicep build --file infra/appservice/main.bicep --stdout > /dev/null
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No `docker compose up` is needed; no Azure resource is created.

## Migration and rollback
Template changes are parameter-gated and default to the current deployment, except the two store switches (inert until PRP-41 and PRP-42 are deployed). Rollback: revert the PR; the next `plan` shows the diff.

## Live and open gates
OPEN and handed to PRP-64 (each needs `NS_LIVE_APPROVED=1` and per-step operator approval; spend is pre-authorized but each run logs a cap and a spend row): the hosted redeploy with these parameters; the G04 run for Azure Monitor, Foundry discovery and billing export against Limitlessdata; hosted ingest smoke with a created producer. A Cost Management export and a Foundry project are operator-created prerequisites, listed in the runbook.

## NOT building
A deploy workflow (PRP-63); connector or producer logic; Key Vault secret creation; an OTel collector deployment; Government hosted profile changes beyond the shared parameters; `/readyz` probe settings, review-debt fixes and sandbox script fixes (PRP-67); AMPLS for Log Analytics; changes to `infra/bicep/modules/**`; any live Azure call.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (the `Azure AI User` role id must be verified against Learn at session start)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-58-hosted-data-path | demo Bicep, connector-rbac module, GENERATED_PARAMS, plan flags, runbook section 8 |
| 2 | merged | prp-58-hosted-data-path | App Service params, Helm values+template; goldens unchanged (defaults inert) |
| 3 | merged | prp-58-hosted-data-path | compose pass-through, parity test; compose stack not run |
| 4 | merged | prp-58-hosted-data-path | G04 script + offline tests; live run OPEN |
| 5 | merged | prp-58-hosted-data-path | close-out: Tier-3 regeneration, completion note, changelog fragment |

## Completion note (filled at ship)
- Date and PR: 2026-11-16, PR #312.
- Deviations: none from the blueprint. No `[serial-after]` item existed. `az bicep build` could not be run locally (a copy of the template in temp/ broke its relative module paths), so the Bicep was read by hand and the CI `bicep` and `helm` jobs are the build check. No `openapi.json` or `docs/reference/**` change (no API or SDK change).
- Descoped items: none. `/readyz` probe settings, hosted-script review fixes and live-run follow-ups stay in PRP-67 and PRP-66 as planned.
- OPEN gates: hosted redeploy with these parameters; the G04 live run (Azure Monitor, Foundry discovery, billing export) against Limitlessdata; hosted ingest smoke with a created producer. All handed to PRP-64 and need `NS_LIVE_APPROVED=1`. `docs/evidence/G04/` stays absent until an operator run.
- Env vars for the operator: new pass-through names in compose, Helm and Bicep (all default inert): `NS_INGEST_PRODUCER_STORE`, `NS_WORKER_REC_SOURCE`, `NS_WORKER_CONNECTOR_CONFIG_SOURCE`, `NS_API_BASE_URL`; `NS_WORKER_ROLES` is now composed from `connectorRoles`. `.env.example` is not edited (agent-blocked). Hosted parameters: `connectorRoles`, `recommendationsEnabled`, `foundryAccountIds`, `billingExportStorageAccountId`, `evaluationPilotDomainId`, `evaluationPilotSubjectId`, `evaluationPilotDatasetIds`. The G04 script needs `NS_LIVE_APPROVED=1`, a budget cap and per-connector `--approve-step`.
- Follow-up issues: reviewer follow-ups, not yet filed. (1) `infra/demo/main.bicep` `connectorRoles` has no `@allowed`; the CLI validates role names but a direct `az deployment` call could pass any name, so add `@allowed` on the array items or a template-level check. (2) `g04_connectors_live.py`: `--operator` is not covered by GUID or URL scrubbing (its regex already rejects emails) and `--billing-basis` is written unscrubbed (harmless enum). (3) PRP-64 should confirm a connector role with no stored config idles and does not crash-loop (roles start through `NS_WORKER_ROLES`; PRP-42 stored config decides what they poll). #220 stays open for the G04 run.
- Product check (can an operator use it without editing files): partly. Producers and connector config are created through the admin API (PRP-41, 42); enabling the roles in a hosted environment still needs a redeploy with the new parameters, which is OPEN (PRP-64).
