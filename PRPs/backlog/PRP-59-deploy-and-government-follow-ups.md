---
name: PRP-59-deploy-and-government-follow-ups
status: backlog
priority: P3
order: 43
review: none
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-07, NS-08
depends_on: []
wave: W17
branch: prp-59-deploy-gov-followups
allow_parallel: true
issues: [249, 36, 38, 212, 213, 214, 133]
---

# PRP-59: Deploy and Government follow-ups

## Goal
Close seven small, independent hardening items that the PRP-08 and PRP-20 reviews left open on the deployment path and the Government profile, so later deploy work (PRP-55 real apply) builds on a plan route that cannot be fed a forged scan, an uninstall script that knows every resource type the Bicep modules create, one Government region rule applied everywhere, and live-gate scripts that always leave evidence. It is for operators who plan, deploy and tear down a customer-hosted instance, and for the maintainers of the Government gates. It is `review: none` because every item is small and test-covered; the plan-route change is the one behaviour change and is pinned by tests.

Out of scope: the real deploy apply path, durable plan approvals and the ARM provisioner (PRP-55); the analytics registry reason for a DoD request (#212 analytics bullet, PRP-11 owns `analytics/**`); Bicep module changes and the egress and CI hardening (PRP-52); the what-if noise allow-list for G02 (#213 item 3, needs a Government subscription, operator, PRP-64); running G02, G01 or the live uninstall (PRP-64); the PRP-48 role-gated deployment dependency on the plan and scan routes (kept as merged in W15); Snyk-UI ignores, which only the operator can set (reported OPEN).

## Why
- `POST /api/v1/deploy/plan` accepts a full `ScanResponse` in the request body as a "validated fallback" (`services/api/neurosphere_api/deploy/plan/router.py:54-63`, `plan/models.py:107-110`), so a `config.manage` caller can plan against a forged discovery result; the server-issued `scan_id` path exists and is preferred but not required (#36). The UI still sends the whole scan (`frontend/src/features/deploy/PlanStep.tsx:146`).
- `infra/scripts/uninstall.py:43-52` hard-codes eight ARM types; the Bicep tree declares more top-level types (`Microsoft.Web/sites`, `serverfarms`, `Network/privateEndpoints`, `networkSecurityGroups`, `virtualNetworks`, `privateDnsZones`, `Consumption/budgets`), so uninstalling an App Service deployment would be refused for those resources with "no known api-version" (#38).
- `ScanRequest.consent.consented_by` is a client-supplied free string (`deploy/scan/models.py:36-40`) used only as a non-empty check (`scan/service.py:50-58`); the audit record never names the authenticated principal (#133 bullet; PRP-31 Clarification 8, PRP-29 Clarification 20).
- The Government region allowlist is enforced in `DeploymentProfile` (`packages/core/neurosphere_core/capabilities/validate.py:82-121`), but copilot gating builds the profile without a guard (`packages/core/neurosphere_core/copilot/models/gating.py:97-107`), `ui_adapters/capabilities.py:40` still treats `usdod` as Government, and the mock regex does the same (`frontend/tests/mock-api/features/deploy.ts:32`) (#212).
- In `_g02_profile_common._run` a `KeyboardInterrupt` during `profile.deploy` tears down and re-raises with no evidence file (`scripts/gates/_g02_profile_common.py:430-457`); `_delete_group` trusts a plan that is the empty default after an early failure (`:508-530`); the AKS cleanup has a broad `except Exception` (`scripts/gates/g02_profile_aks.py:175`) (#213 items 1, 2, 4).
- `confine_evidence_dir` is duplicated byte for byte in `g01_analytics_live.py:140` and `g01_deploy_smoke.py:103` and there is no `.snyk` file, so Snyk Code keeps resurfacing the path-traversal lows (#214).

## Acceptance criteria
- [ ] Given a plan request with a body `scan`, when posted, then it is refused with 422 `invalid_schema` reason `scan_body_not_accepted` before any planning; given `scan_id` of a scan this caller ran, planning works as today; given another caller's `scan_id`, 403 as today (#36).
- [ ] The deploy UI plans from the stored scan: `PlanStep` sends `scan_id` from the scan response and never the scan body; when the scan response has no `scan_id` (store not configured) the UI shows the existing "scan unavailable" error state instead of posting (#36 follow-through).
- [ ] The mock API refuses a body `scan` the same way and echoes `scan_id` flows in tests and e2e (#36).
- [ ] Every top-level `provider/type` declared as `resource ... '<Type>@<version>'` under `infra/bicep/**`, `infra/demo/**` and `infra/appservice/**` has an entry in `_API_VERSIONS` or is listed in an explicit `NOT_DELETED_DIRECTLY` allow-list (child and extension types such as `roleAssignments`, `diagnosticSettings`, `sqlDatabases`) with a one-line reason; a new Bicep type with neither fails the test naming it (#38).
- [ ] Each `_API_VERSIONS` value is not older than the newest version the Bicep tree uses for that type, or a test comment records why; `api_version_for` still refuses an unknown type (#38).
- [ ] Given a scan request, when it succeeds, then the consent audit record carries the authenticated principal pseudonym as `consented_by` and the hash of the client text as `attestation`; the raw client string is not stored; the request model and UI keep accepting `consented_by` as the attestation reference (#133).
- [ ] Given a copilot region `usdod*`, empty, or malformed, `_evaluate` returns a disabled `AdapterAvailability` with reason `capability_unavailable` instead of raising `ValidationError` (#212 copilot).
- [ ] `ui_adapters/capabilities.py` derives Government regions from `GOVERNMENT_DEPLOYABLE_REGIONS`; a `usdod*` region is not Government there; the mock `GOV_REGION` matches only the three deployable regions (#212 display and mock).
- [ ] A worker test shows `fabric_unavailable_reason(GOVERNMENT, "usdodeast")` returns `invalid_region` (#212 workers).
- [ ] The known-host list in `tests/unit/government_profile/test_sovereign_hosts.py` is derived from `CloudProfile` and `sovereign-profile.yaml`, and a host in the manifest that no suffix covers fails with the host name (#212 `GOV_SUFFIX`).
- [ ] A `KeyboardInterrupt` raised inside `profile.deploy` still tears down, writes an evidence file with `result: FAIL` and `interrupted: true`, then re-raises (#213 item 1).
- [ ] Before the group delete, `_delete_group` re-lists the group's resources and refuses to delete when any resource lacks this run's tag, recording the refusal in `teardown` (#213 item 2).
- [ ] The AKS cleanup catches the recoverable tuple only; any other exception propagates after the evidence write (#213 item 4).
- [ ] `confine_evidence_dir` lives once in `scripts/gates/_evidence_paths.py` and both G01 scripts import it; the existing path-confinement tests pass unchanged; `--help` and docs state that analytics evidence is confined to `docs/evidence/G01/analytics` (#214).
- [ ] `snyk_code_scan` over the touched Python shows no new findings; the remaining path-traversal lows are justified in `docs/security/snyk-justifications.md` naming `confine_evidence_dir`, with a `.snyk` ignore added only if Snyk Code supports one for the finding (UNVERIFIED), else reported as an operator Snyk-UI action (#214).
- [ ] PRP exit: targeted suites, `ruff`, `pyright`, frontend lint/typecheck/test, `verify-gates.ps1 -Mode full` pass; live runs reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Plan route body scan | Refuse outside local; require a signature; always refuse | Always refuse. A signature adds key management for no caller; the stored `scan_id` path already exists. `PlanRequest.scan` stays as an internal field for `build_plan` (set by the route from the store), so planner unit tests are unchanged |
| 2 | `consented_by` server-side | New model field; stamp into audit only | ASSUMPTION: stamp into the audit record (principal pseudonym) and keep the request field as the client attestation reference, hashed. No response-model change, no UI change |
| 3 | Uninstall table derivation | Generate from Bicep at runtime; keep explicit table plus a coverage test | Explicit table plus a coverage test: the script must stay a plain stdlib script that refuses unknown types, never guesses |
| 4 | DoD regions | Treat as Government display; refuse everywhere | Refuse everywhere (matches `DeploymentProfile`); DoD is a separate unbuilt profile |
| 5 | Snyk justification mechanism | `.snyk` file; Snyk UI; both | ASSUMPTION: `.snyk` only if the scan output gives a finding id it accepts; otherwise a documented justification plus an operator UI ignore. The implementer runs `snyk_code_scan` and decides on evidence |
| 6 | G01 helper dedupe | Leave duplicates; shared module | Shared module (the issue marks it optional; it removes the second finding source) |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/deploy/plan/{router,models}.py` and `deploy/scan/{service,models,router}.py`.
- `frontend/src/features/deploy/{PlanStep.tsx,ScanStep.tsx,types.ts,deploy.test.tsx}` and `frontend/tests/mock-api/features/deploy.ts`.
- `infra/scripts/uninstall.py:30-70` and `tests/unit/infra/test_uninstall_rg_guard.py`.
- `packages/core/neurosphere_core/copilot/models/gating.py:80-130` and `capabilities/validate.py:75-125`.
- `services/api/neurosphere_api/ui_adapters/capabilities.py:35-80`.
- `services/workers/neurosphere_workers/actions/deploy.py:377-395`.
- `scripts/gates/_g02_profile_common.py:413-560`, `scripts/gates/g02_profile_aks.py:150-190`, `tests/unit/gates/test_g02_profile_paths.py`.
- `scripts/gates/g01_analytics_live.py:130-160`, `scripts/gates/g01_deploy_smoke.py:95-120`, `tests/unit/gates/test_g01_path_confinement.py`.
- `tests/unit/government_profile/test_sovereign_hosts.py:25-80`.

### Interfaces consumed
- `ScanService.stored_scan(scope, scan_id)` and `ScanResponse.scan_id` (PRP-08, shipped).
- `DeploymentProfile`, `validate_profile`, `GOVERNMENT_DEPLOYABLE_REGIONS` (PRP-20, shipped).
- PRP-48 (W15) already swaps the plan and scan route permission for the deployment-scoped dependency and may add audit calls; keep every change it made in `deploy/plan/router.py` and `deploy/scan/router.py`.
- PRP-55 (W18) builds apply on top of this plan route; it assumes `scan_id` only.

### Interfaces provided
- Plan route contract: body `scan` refused (`scan_body_not_accepted`); `scan_id` required for planning from a scan.
- `scripts/gates/_evidence_paths.py` (`confine_evidence_dir`) for later gate scripts.
- `NOT_DELETED_DIRECTLY` allow-list in `infra/scripts/uninstall.py` and the Bicep coverage test.
- Evidence field `interrupted` in G02 profile evidence.

### Patterns to match
- Typed refusal with a stable reason: `deploy/plan/router.py:54-63` (`scan_not_found`).
- Pure region reason function: `actions/deploy.py:377-395`.
- Gate evidence scrubbing and writing: `_g02_profile_common.py:476-487`.
- Bicep text parsing in a unit test: `tests/unit/infra/test_helm_render.py` style (no tool needed, plain regex over `.bicep`).

### Gotchas
- `PlanRequest` is `extra="forbid"` and part of `openapi.json`; do not remove `scan` from the model, refuse it in the route, and regenerate `openapi.json` only if descriptions change.
- Existing tests build `PlanRequest(scan=...)` for `build_plan` directly (`services/api/tests/deployment/test_plan.py`, `tests/integration/deploy/test_scan_to_plan.py`); those stay valid. Tests that POST a body scan to the route must move to `scan_id`.
- The Bicep scan must ignore commented lines and `existing` references; child types (three or more segments after the provider) are covered by their parent.
- A mock `consent` body uses `consented_by` (`deploy.ts:35`); keep accepting it.
- `usdod*` is still valid for the capability matrix rows labelled `region: "*"` in the Commercial/Government split only as display; after the change a `usdod*` region matches no Government wildcard row, which is intended.
- `scripts/gates/g01_*.py` belong to PRP-11 in W12; this PRP edits only the helper import and removes the duplicate.
- Gate scripts are live-only: unit tests use fakes; do not run `az` or any live command.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/deploy/plan/**
  - services/api/neurosphere_api/deploy/scan/models.py
  - services/api/neurosphere_api/deploy/scan/service.py
  - services/api/tests/deployment/test_plan_body_scan_refused.py
  - services/api/tests/deployment/test_consent_stamp.py
  - services/api/tests/deployment/test_plan.py
  - services/api/tests/deployment/test_audit_and_scan_id.py
  - tests/integration/deploy/**
  - frontend/src/features/deploy/PlanStep.tsx
  - frontend/src/features/deploy/types.ts
  - frontend/src/features/deploy/deploy.test.tsx
  - frontend/tests/mock-api/features/deploy.ts
  - infra/scripts/uninstall.py
  - tests/unit/infra/test_uninstall_api_versions.py
  - packages/core/neurosphere_core/copilot/models/gating.py
  - packages/core/tests/copilot/test_gating_government_regions.py
  - services/api/neurosphere_api/ui_adapters/capabilities.py
  - services/api/tests/ui_adapters_api/test_capabilities.py
  - services/workers/tests/action_executor/test_deploy_dod_region.py
  - tests/unit/government_profile/**
  - scripts/gates/_g02_profile_common.py
  - scripts/gates/g02_profile_aks.py
  - scripts/gates/_evidence_paths.py
  - scripts/gates/g01_analytics_live.py
  - scripts/gates/g01_deploy_smoke.py
  - tests/unit/gates/test_g02_teardown_hardening.py
  - tests/unit/gates/test_g01_path_confinement.py
  - docs/security/snyk-justifications.md
  - .snyk
tier1: []
tier2_appends: []
must_not_touch:
  - services/api/neurosphere_api/deploy/scan/router.py
  - services/api/neurosphere_api/deploy/apply/**
  - packages/core/neurosphere_core/analytics/**
  - services/workers/neurosphere_workers/actions/deploy.py
  - infra/bicep/**
  - infra/demo/**
  - infra/appservice/**
  - packages/contracts/**
```

## Implementation blueprint
Parallelization map: Items 1, 2, 3, 5, 6 are independent [P] (disjoint files); Item 4 waits for Item 1 (shared mock file). Item 1 and Item 2 both live under `deploy/` but touch different files (`plan/**` versus `scan/{models,service}.py`); keep them in separate worktrees and merge in order 2 then 1 if the scan service signature moves. `openapi.json` and `docs/reference/**` are regenerated in Item 7 only.

### Item 1 - Plan route refuses a body scan  [P]
- Deliverable: `_resolve_scan` refuses `body.scan` with `scan_body_not_accepted`; `PlanStep` posts `scan_id`; mock handler mirrors; tests moved from body scan to `scan_id`.
- Owned files: `deploy/plan/router.py`, `deploy/plan/models.py` (description text only), `services/api/tests/deployment/{test_plan_body_scan_refused,test_plan,test_audit_and_scan_id}.py`, `tests/integration/deploy/**`, `frontend/src/features/deploy/{PlanStep,types}.ts*`, `frontend/src/features/deploy/deploy.test.tsx`, `frontend/tests/mock-api/features/deploy.ts`.
- Must NOT touch: `deploy/scan/router.py`, `build_plan` logic in `planner.py`, PRP-48's permission dependency lines.
- Depends on: none.
- Acceptance criteria: criteria 1 to 3.
- Tests: `uv run pytest -q services/api/tests/deployment tests/integration/deploy`; `pnpm --filter @neurosphere/frontend test -- deploy`; `pnpm --filter @neurosphere/frontend test:e2e -- deploy`.
- Pattern references: `plan/router.py:54-70`, `plan/models.py:98-112`.

### Item 2 - Server-side consent stamping  [P]
- Deliverable: `ScanService.scan_for` records the authenticated principal pseudonym as `consented_by` and the opaque hash of the client attestation in the consent audit state; `ConsentRecord` field description updated to "attestation reference".
- Owned files: `deploy/scan/{service,models}.py`, `services/api/tests/deployment/test_consent_stamp.py`.
- Must NOT touch: `deploy/scan/router.py`, `deploy/scan/audit.py`.
- Depends on: none.
- Acceptance criteria: criterion 6; the consent audit state never contains the raw attestation (grep test over the recorded audit draft).
- Tests: `uv run pytest -q services/api/tests/deployment`.
- Pattern references: `scan/service.py:78-112`, `scope.to_contract().principal.principal_pseudonym` as used in `recommendations/review_hitl.py:44-52`.

### Item 3 - Uninstall API-version coverage  [P]
- Deliverable: entries for the missing top-level types (versions taken from the Bicep tree), `NOT_DELETED_DIRECTLY`, and a Bicep-scanning coverage test.
- Owned files: `infra/scripts/uninstall.py`, `tests/unit/infra/test_uninstall_api_versions.py` (new).
- Must NOT touch: any `.bicep` file, `tests/unit/infra/test_uninstall_rg_guard.py`.
- Depends on: none.
- Acceptance criteria: criteria 4 and 5; the unknown-type refusal test in `test_uninstall_rg_guard.py` still passes.
- Tests: `uv run pytest -q tests/unit/infra/test_uninstall_api_versions.py tests/unit/infra/test_uninstall_rg_guard.py`.
- Pattern references: `uninstall.py:43-66`.

### Item 4 - Government region allowlist alignment
- Deliverable: guarded profile build in copilot gating; capabilities adapter and mock derive from `GOVERNMENT_DEPLOYABLE_REGIONS`; DoD worker test; `KNOWN_GOV_SUFFIXES` derived from the profile and manifest.
- Owned files: `packages/core/neurosphere_core/copilot/models/gating.py`, `packages/core/tests/copilot/test_gating_government_regions.py`, `ui_adapters/capabilities.py`, `services/api/tests/ui_adapters_api/test_capabilities.py`, `frontend/tests/mock-api/features/deploy.ts` (the `GOV_REGION` line; Item 1 owns the rest of the file, so land Item 1 first), `services/workers/tests/action_executor/test_deploy_dod_region.py`, `tests/unit/government_profile/test_sovereign_hosts.py`.
- Must NOT touch: `analytics/**`, `services/workers/neurosphere_workers/actions/deploy.py`.
- Depends on: Item 1 for the shared mock file (order, not logic).
- Acceptance criteria: criteria 7 to 10.
- Tests: `uv run pytest -q packages/core/tests/copilot services/api/tests/ui_adapters_api services/workers/tests/action_executor tests/unit/government_profile`.
- Pattern references: `validate.py:112-125`, `actions/deploy.py:377-394`.

### Item 5 - G02 teardown hardening  [P]
- Deliverable: interrupt during deploy writes evidence then re-raises; pre-delete re-list and tag check; narrowed AKS cleanup exception.
- Owned files: `scripts/gates/_g02_profile_common.py`, `scripts/gates/g02_profile_aks.py`, `tests/unit/gates/test_g02_teardown_hardening.py` (new, fake `Runner`).
- Must NOT touch: anything that runs `az`; live behaviour stays gated by `NS_LIVE_APPROVED`.
- Depends on: none.
- Acceptance criteria: criteria 11 to 13; existing `test_g02_profile_paths.py` and `test_g02_profile_refuses.py` stay green.
- Tests: `uv run pytest -q tests/unit/gates`.
- Pattern references: `_g02_profile_common.py:508-545`.

### Item 6 - Shared evidence-path helper and Snyk justification  [P]
- Deliverable: `_evidence_paths.confine_evidence_dir`; G01 scripts import it; help text states the confinement; `snyk_code_scan` run on the touched files; `docs/security/snyk-justifications.md`; `.snyk` only when supported.
- Owned files: `scripts/gates/_evidence_paths.py` (new), `g01_analytics_live.py`, `g01_deploy_smoke.py`, `tests/unit/gates/test_g01_path_confinement.py`, `docs/security/snyk-justifications.md` (new), `.snyk` (new, conditional).
- Must NOT touch: other gate scripts.
- Depends on: none.
- Acceptance criteria: criteria 14 and 15.
- Tests: `uv run pytest -q tests/unit/gates`.
- Pattern references: `g01_analytics_live.py:140-150`.

### Item 7 - Integration and close-out
- Deliverable: regenerate `services/api/openapi.json` and `docs/reference/**` if the plan or scan model descriptions changed; `python scripts/prp_status.py --write`; cross-test grep for `PlanRequest(`, `scan=`, `confine_evidence_dir`, `_API_VERSIONS` over `tests/`, `services/*/tests`, `frontend/`; CHANGELOG entry; comment on #36, #38, #133, #212, #213, #214 and close those fully fixed (#213 item 3 and Snyk UI items stay open or are split).
- Owned files: this PRP file; generated Tier 3 files.
- Depends on: Items 1 to 6.
- Acceptance criteria: reference section 6 satisfied.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/deployment services/api/tests/ui_adapters_api services/workers/tests/action_executor packages/core/tests/copilot tests/integration/deploy tests/unit/infra tests/unit/government_profile tests/unit/gates services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e -- deploy
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data or schema migration. Behaviour change: clients that posted a body `scan` to the plan route (only the shipped UI and mocks did) must use `scan_id`; the UI change ships in the same PR. Rollback: revert the PR. Uninstall gains entries only; the unknown-type refusal is unchanged.

## Live and open gates
G02 profile runs, G01 live runs and the live uninstall need `NS_LIVE_APPROVED=1` and operator approval; none runs here and all are reported OPEN (PRP-64). #213 item 3 (what-if noise list) needs a Government subscription and stays open. A Snyk-UI ignore, if the `.snyk` file cannot express it, is an operator action.

## NOT building
Real apply or durable approvals (PRP-55); signature scheme for scan bodies; analytics registry reason change (PRP-11); Bicep edits; DoD profile; the what-if allow-list.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided or labelled ASSUMPTION

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-59-deploy-gov-followups | done in this branch |
| 2 | merged | prp-59-deploy-gov-followups | done in this branch |
| 3 | merged | prp-59-deploy-gov-followups | done in this branch |
| 4 | merged | prp-59-deploy-gov-followups | done after item 1 |
| 5 | merged | prp-59-deploy-gov-followups | done in this branch |
| 6 | merged | prp-59-deploy-gov-followups | done in this branch |
| 7 | todo | | merge step: Tier 3 regeneration, changelog fragment, close-out |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint:
- Descoped items:
- OPEN gates (G02 live, G01 live, live uninstall, #213 item 3, Snyk UI ignore):
- Env vars for the operator (none):
- Follow-up issue numbers:
- Issue state (#36, #38, #133, #212, #213, #214):
