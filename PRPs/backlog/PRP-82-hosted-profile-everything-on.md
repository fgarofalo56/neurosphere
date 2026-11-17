---
name: PRP-82-hosted-profile-everything-on
status: backlog
priority: P0
order: 72
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-01, NS-05, NS-06, NS-09
depends_on: [PRP-58-hosted-data-path-and-environment-hardening, PRP-63-delivery-pipeline-to-hosted, PRP-67-hosted-environment-hardening, PRP-60-search-indexing-hardening, PRP-139-hosted-environment-real-tenant-data]
wave: W21
branch: prp-82-hosted-everything-on
allow_parallel: true
issues: []
---

# PRP-82: Hosted Azure profile with everything on, against real tenant data, and checked

Changed 2026-11-17 (owner decision D20): the hosted profile no longer loads the PRP-71 demo world; it turns features on against the real tenant data that PRP-139 connects, and the demo world is used only locally and in CI.

## Goal
Give the hosted environment (`https://nsdemo-web.azurewebsites.net`) an `everything-on` profile: the infrastructure parameters and role lists that switch on the producer store, the recommendations and connector roles, Azure AI Search, the MCP server, deployment scan and lifecycle dry-run, and the copilot on an approved Foundry endpoint, all on top of the real-tenant mode of PRP-139 (`dataMode = 'real-tenant'`, the deployment's own customer id, sources connected by an administrator); no synthetic data is loaded into a hosted environment; and a signed-in browser smoke that walks every navigation entry and fails on an error, a "not configured" state, an unexplained 4xx/5xx, or an empty page whose source PRP-139 reports as connected. It is deployed through the delivery pipeline of PRP-63 and proven by evidence checked into a fixed layout. It is for the owner, who judges the product by what they can click in the deployed app and found the hosted site serving the 2026-10-26 build with none of the PRP-36..57 admin work. This PRP ships parameters, the smoke, the evidence layout, an offline evidence validator, offline tests and the exact operator commands. Anything that deploys, signs in or spends is an operator-approved live step and is reported OPEN until it runs; this PRP does not run it.

Out of scope: the data-path parameters themselves and the producer store switch (PRP-58, already merged); the delivery workflow and its infrastructure smoke (PRP-63, `scripts/gates/hosted_smoke.py`); probe defaults and teardown (PRP-67); search indexing fixes (PRP-60); the demo world (PRP-71, local and CI only, never loaded into a hosted environment); the real-tenant mode, the source connections, the purge of the old synthetic data and the page empty states (PRP-139); new copilot tools (PRP-78, PRP-80) and the live copilot groundedness run (PRP-64); any real-Azure throughput number (PRP-84, PRP-66); creating or modifying Foundry accounts the project does not own.

## Why
- The owner's complaint is concrete: the hosted app is the 2026-10-28 hand deployment (hosted-demo runbook, `docs/deploy/hosted-demo.md` section 3), ingest answers 503 because no hosted profile sets a producer source (`infra/demo/main.bicep` has no ingest setting; lane-d step 1), the worker role list excludes `recommendations`, connectors and `foundry_discovery` (`infra/demo/main.bicep:280`: `ingestion,projections,aggregates,actions,hitl_timers,lifecycle,evaluation`), copilot is `disabled` (`infra/demo/main.bicep:73`) and search is the in-process fixture (`:87-92`).
- Original PRD success metrics are judged on a live system: section 3 "Time-to-answer: median time for an operator to answer 'which agent/service does X' via copilot vs. manual search, 80% reduction" and "Copilot adoption: weekly active copilot users > 40%", and 5e "Conversational interface using retrieval-augmented generation". v1.2 kept the copilot but set it off by default and left it unobserved against a real model: the live copilot turn is OPEN (PRP-19 completion note; gap analysis 5e "Ever run against a real model: NO").
- The existing hosted browser spec checks the shell, domain switcher, overview tiles, map and copilot only (`frontend/tests/hosted/hosted-smoke.spec.ts`, hosted-demo S9); 56 routes exist in `frontend/src/app/route-manifest.json`. Nothing fails when an admin page, review queue or recommendations page is empty, which is exactly how the stale site went unnoticed.
- The delivery pipeline (PRP-63) smokes infrastructure unauthenticated by design (`scripts/gates/_hosted_demo_smoke.py` checks `/`, `/config.json`, a 401, site state, health metric); an Entra sign-in with MFA cannot run in CI, so the product-level smoke is operator-attended and must leave checkable evidence.
- Cosmos and the other data planes are private in the DMLZ landing zone, so any operator data-plane step and the signed-in walk need the operator on the P2S VPN (memory: live-run gotchas; hosted-demo S7).
- The owner decided on 2026-11-17 (D20, `docs/DECISIONS-LOG.md:18`) that a hosted deployment shows the tenant it is deployed to and starts empty; the synthetic world loaded on 2026-10-28 is removed by PRP-139, and this profile must not put a demo world back.

## Acceptance criteria
- [ ] Given the Bicep templates, When `infra/demo/main.bicep` is built with `hostedProfile = 'everything-on'`, Then the API and worker app settings include the producer store switch, the extended worker role list, the archive recommendations source, `NS_SEARCH_PROVIDER=azure` with the existing search service name, `NS_MCP_*` for the deployed host, `NS_SCAN_ENABLED=true`, `NS_LIFECYCLE_MODE=dry_run`, and `NS_COPILOT_MODE` from a parameter; Given `hostedProfile = 'baseline'` (the default), Then the rendered settings are identical to today's golden (`tests/unit/hosted_demo/core_main_resources.golden.json` unchanged except documented additions).
- [ ] Given `hostedProfile = 'everything-on'` with an empty `copilotEndpoint`, Then the template build fails with a clear message (no silent `disabled`); no parameter, output or setting value holds a key, secret or connection string (the PRP-58 parity test and a new name-pattern test pass).
- [ ] Given the App Service profile (`infra/appservice/main.bicep`), Then it exposes the same `hostedProfile` parameter and renders the same setting names as the demo template (parity test).
- [ ] Given `hostedProfile = 'everything-on'`, When the template is built with `dataMode = 'demo'` or the customer id `synthco`, Then the build or the plan step refuses with a clear message: the profile exists only on the real-tenant mode of PRP-139. Given the hosted seed driver, Then this PRP adds no profile to it and the offline test proves `hosted_demo_seed.py` still refuses a real-tenant registration (the PRP-139 rule) before any import of a network client.
- [ ] Given a signed-in session, When `hosted-nav-walk.spec.ts` runs, Then it opens every link in the rendered primary navigation plus every manifest route without a required id (detail routes are reached through their list), and fails any page that shows a "not configured" or "not available in this deployment" message, an error boundary, an API 4xx/5xx not named in the page's allowed answers, or an `empty-state` marker on a page whose source the PRP-139 source status reports as `connected`; an empty state is allowed only when it is the PRP-139 source-aware one and the source is recorded `not_connected` or OPEN in the evidence, and each allowed empty or denied answer carries a reason and an owning PRP.
- [ ] Given `frontend/tests/hosted/nav-expectations.ts`, When a route is added to `route-manifest.json` without an expectation, Then an offline test fails (`tests/unit/hosted_profile/test_nav_expectations.py`), so a new nav entry cannot escape the walk.
- [ ] Given an evidence directory under `docs/evidence/hosted/<date>-<image-tag>/`, When `scripts/gates/hosted_profile_evidence.py` validates it, Then it requires the plan hash and image tag, the per-source status counts (`sources.json`, from the PRP-139 verify step; a `seed.json` in the directory is a failure), the nav-walk result (`nav-walk.json`, pass count equal to route count, zero failures), a copilot turn record (or an explicit `copilot: open` with reason), a served-build check, and rejects any file containing a token, key, subscription id, host name or resource id (counts and names only).
- [ ] Served-build check: the walk records the build identifier the frontend serves and the evidence validator fails when it differs from the image tag that was deployed, so a stale site (the 2026-10-26 build) cannot pass.
- [ ] `docs/deploy/hosted-everything-on.md` lists the exact operator commands in order (VPN, plan, approval, deploy through the pipeline with `dataMode = 'real-tenant'`, the PRP-139 source verify, sign-in, walk, teardown or keep; no seed step), the spend-row and approval wording, and how to point the copilot at an approved Foundry deployment; it states that nothing here was run by the PRP.
- PRP exit: touched suites, ruff, pyright, `validate_planning.py` pass; PR open with CI green. The live items are listed OPEN in the completion note with the commands; no live claim is made.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How the profile is expressed | New templates; one parameter on the existing templates | One parameter `hostedProfile` (`baseline` default, `everything-on`) on `infra/demo/main.bicep` and `infra/appservice/main.bicep`, so existing deployments do not change. |
| 2 | Who deploys | This PRP; the pipeline | The pipeline (PRP-63 `deploy-hosted.yml`, plan then approval then apply) with operator approval; this PRP edits no workflow. |
| 3 | Data in the hosted environment | Seed the PRP-71 demo world; real tenant data only | Decided by the owner 2026-11-17 (D20): real tenant data only, connected by PRP-139. Nothing is seeded into a hosted environment; the demo world is local and CI only. Pages with no connected source show the PRP-139 empty states and the walk records them with the source's OPEN reason. |
| 4 | Where the signed-in walk runs | CI; operator-attended | Operator-attended (Entra MFA). It reuses `playwright.hosted.config.ts`, the saved storage state and the `sessionStorage` replay (hosted-demo S9). Not in CI. |
| 5 | Model endpoint | Create a Foundry deployment here; use an approved one | An approved existing Foundry deployment supplied as `copilotEndpoint` and `copilotDeployment` by the operator (spend pre-authorized for NeuroSphere, a cap and spend row still logged). Never touch Foundry accounts the project does not own. The hosted profile never uses the `recorded` copilot mode (local demo only, PRP-78) and needs a real approved model endpoint. |
| 6 | Search | Keep fixture; Azure AI Search | Azure AI Search on an existing service named by `searchService`, after PRP-60 (index key and `text` fixes). ASSUMPTION: if the operator has no search service, the profile may set `searchProvider = 'fixture'` and the walk records search as `fixture` in evidence (not hidden). |
| 7 | Build identifier | Add a version route; read the existing config | ASSUMPTION: the frontend `config.json` or an asset hash already identifies the build; item 3 reads what exists and, if nothing does, records the image tag from the App Service `linuxFxVersion` through the PRP-63 smoke outputs. No API change in this PRP. |
| 8 | Write targets, deploy apply | Switch on | Stay off (`NS_WRITE_TARGETS_FROM_STORE=false`, apply 503) unless the operator names an approved target; the walk allows them as "advisory" pages with a reason. |

## Context manifest

### Files to read first
- `infra/demo/main.bicep` and `infra/demo/main.bicepparam` - parameters, app settings blocks (`:62-117,249-306`), worker roles (`:280`).
- `infra/appservice/main.bicep` and `main.bicepparam` - the App Service twin.
- `scripts/gates/_hosted_demo_common.py` - `GENERATED_PARAMS`; `scripts/gates/hosted_demo.py` - commands (plan, deploy, grant, seed-access, smoke, teardown) and `NS_LIVE_APPROVED` check (`:1997`).
- `scripts/gates/hosted_demo_seed.py` - the seed driver, read only: after PRP-139 it refuses a real-tenant registration and needs `--demo-environment`; this PRP does not edit it.
- `PRPs/backlog/PRP-139-hosted-environment-real-tenant-data.md` (or its shipped copy) - `dataMode`, `customerId`, the source status API and the verify evidence this profile builds on.
- `scripts/gates/_hosted_demo_smoke.py` and PRP-63's `scripts/gates/hosted_smoke.py` - the unauthenticated smoke; do not edit.
- `frontend/tests/hosted/hosted-smoke.spec.ts`, `global-setup.ts`, `frontend/playwright.hosted.config.ts` - the signed-in pattern and session replay.
- `frontend/tests/real-stack/routes.spec.ts` - the entry table (`Entry`, `Expected`, `via`) to imitate; `frontend/src/app/route-manifest.json`, `workspaceNav.ts`.
- `frontend/src/design-system/components/states.tsx:51` - the empty-state marker.
- `docs/deploy/hosted-demo.md` (S3-S9) and PRP-58, PRP-63, PRP-67 ownership blocks (read only).
- `frontend/src/features/source-status/**` (PRP-139) - the source-aware empty state the walk must tell apart from a broken page.

### Interfaces consumed
- PRP-58: hosted parameters for roles, producer store switch, config source, API base URL, recommendations source, `connector-rbac` module, `GENERATED_PARAMS` handling; PRP-63: `deploy-hosted.yml` (plan, apply, release) and `hosted_smoke.py`; PRP-67: probe settings, `publicNetworkAccess` handling, teardown and sandbox guard; PRP-60: working Azure search key and index; PRP-60/58 are treated as merged.
- PRP-139: Bicep `dataMode` and `customerId`, `NS_HOSTED_DATA_MODE`, `GET /api/v1/sources/status`, the source-aware empty states, `hosted_real_tenant.py verify` and its evidence under `docs/evidence/PRP-139/`. PRP-71 is not a dependency: its demo world is local and CI only and is never loaded here.
- PRP-45: system status for the post-deploy check; PRP-57 admin pages in the nav.

### Interfaces provided
- Bicep parameter `hostedProfile` (`baseline | everything-on`) on both templates; setting names unchanged, values only.
- `frontend/tests/hosted/hosted-nav-walk.spec.ts`, `nav-expectations.ts`; result file `nav-walk.json` {route, status, rows_seen, allowed_reason}.
- `scripts/gates/hosted_profile_evidence.py` (new) - offline validator of an evidence directory; layout `docs/evidence/hosted/<yyyy-mm-dd>-<image-tag>/{plan.json, sources.json, nav-walk.json, copilot.json, build.json, README.md}`.
- `docs/deploy/hosted-everything-on.md` - operator commands. PRP-64 and PRP-66 consume the layout when they re-run it.

### Patterns to match
- App settings blocks and `union()` merge: `infra/demo/main.bicep:249-306` (note the PRP-32 trap that `union()` hides schema errors; build with `az bicep build` in the test).
- Offline Bicep tests with golden files: `tests/unit/hosted_demo/test_demo_composition.py`, `core_main_resources.golden.json`, `appservice_default_profile.json`.
- Entry table and allowed-answer style: `frontend/tests/real-stack/routes.spec.ts:20-60`.
- Counts-only evidence writer: `scripts/gates/hosted_demo_seed.py:86-104`.
- Gate script refusal order (approval first, exit 2): `scripts/gates/hosted_demo.py:1997-2010`.

### Gotchas
- `docs/deploy/hosted-demo.md` is edited by PRP-58 and PRP-67; this PRP writes a new file instead and links to it from nowhere else except a `mkdocs.yml` line.
- `hosted_demo.py`, `_hosted_demo_common.py` and `_hosted_demo_smoke.py` belong to PRP-67 and `hosted_smoke.py` to PRP-63: this PRP adds a parameter name to the plan only through `main.bicepparam` and the bicep files; if `GENERATED_PARAMS` needs the new name, write a `[serial-after: PRP-67]` item (item 1b) rather than editing the script in parallel.
- The evidence files must hold names and counts only: no subscription id, tenant id, host, resource id, token or object id. The validator greps for GUIDs and `https://` hosts.
- MSAL's cache is in `sessionStorage`; storage state alone does not carry the sign-in (hosted-demo S9). Everything under `temp/hosted-demo/` holds tokens and is never committed.
- Cosmos is private in the landing zone: any operator data-plane step and any API-level check need the P2S VPN; DNS must resolve through the vault suffix (memory: live-run gotchas). Key Vault purge protection blocks a redeploy of the same name.
- The Foundry account for the copilot is operator-supplied; do not create deployments on shared accounts (memory: G05 gotchas, "don't touch others' Foundry accounts"). Commercial rows only; no Government.
- Hosted run gates need `NS_LIVE_APPROVED=1` and are reported OPEN when they did not run.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - infra/demo/main.bicepparam
  - infra/appservice/main.bicepparam
  - scripts/gates/hosted_profile_evidence.py
  - frontend/tests/hosted/**
  - tests/unit/hosted_profile/**
  - docs/deploy/hosted-everything-on.md
  - docs/evidence/hosted/**
tier1:
  - infra/demo/main.bicep
  - infra/appservice/main.bicep
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - infra/bicep/modules/**
  - infra/helm/**
  - scripts/gates/hosted_demo.py
  - scripts/gates/_hosted_demo_common.py
  - scripts/gates/_hosted_demo_smoke.py
  - scripts/gates/hosted_smoke.py
  - scripts/gates/hosted_demo_seed.py
  - scripts/gates/hosted_purge_synthetic.py
  - scripts/gates/hosted_real_tenant.py
  - .github/workflows/**
  - docs/deploy/hosted-demo.md
  - docs/deploy/delivery.md
  - packages/contracts/**
  - packages/core/**
  - services/**
  - sandbox/**
  - scripts/sandbox/**
```

## Implementation blueprint

Parallelization: items 1, 3 and 4 [P] after reading (Bicep, the browser walk and the evidence validator share no file). Item 2 after item 1 (it tests the profile guard). Item 5 after 1-4. Item 6 last.

### Item 1 - Hosted profile parameters in Bicep  [P]
- Deliverable: `hostedProfile` parameter and a variable table in `infra/demo/main.bicep` that selects, for `everything-on`, the extended worker roles (adds `recommendations`, the connector roles and `foundry_discovery`), `NS_INGEST_PRODUCER_STORE`, `NS_WORKER_REC_SOURCE=archive`, `NS_SEARCH_PROVIDER=azure` plus `NS_SEARCH_SERVICE`, `NS_MCP_RESOURCE_SERVER_URL` and audiences from the deployed host, `NS_SCAN_ENABLED`, `NS_LIFECYCLE_MODE=dry_run`, copilot mode; a template-level assertion that `everything-on` requires a non-empty `copilotEndpoint`; the same parameter and names in `infra/appservice/main.bicep`; placeholders in both `.bicepparam` files. Use the setting names PRP-58 introduced; read them first and add only what is missing. 1b `[serial-after: PRP-67]`: if the hosted scripts' `GENERATED_PARAMS` must list `hostedProfile`, add it after PRP-67 has merged and rebase.
- Owned files: `infra/demo/main.bicep`, `infra/demo/main.bicepparam`, `infra/appservice/main.bicep`, `infra/appservice/main.bicepparam`, `tests/unit/hosted_profile/test_profile_params.py`, `tests/unit/hosted_profile/test_profile_parity.py`.
- Must NOT touch: `infra/bicep/modules/**`, `infra/helm/**`, `hosted_demo.py`.
- Depends on: PRP-58, PRP-60, PRP-67, PRP-139 merged (the profile composes with `dataMode` and `customerId`; it does not redefine them).
- Acceptance criteria: the first three criteria above; the baseline render equals the existing golden.
- Tests: `tests/unit/hosted_profile`, `tests/unit/hosted_demo`, `tests/unit/infra` (read only, must still pass); `az bicep build` runs where `az` exists (CI has it) and skips otherwise per the existing rules.
- Pattern references: `infra/demo/main.bicep:249-306`, `tests/unit/hosted_demo/test_demo_composition.py`.

### Item 2 - Real-tenant guard for the profile (no hosted seed)
- Deliverable: offline tests that pin the D20 rule for this profile: `everything-on` is refused with `dataMode = 'demo'` or the customer id `synthco`; the hosted seed driver gains no profile and still refuses a real-tenant registration; the evidence layout takes `sources.json` (copied from the PRP-139 verify output, counts and states only) and rejects a `seed.json`. No script is edited here.
- Owned files: `tests/unit/hosted_profile/test_real_tenant_guard.py`, `tests/unit/hosted_profile/test_no_hosted_seed.py`.
- Must NOT touch: `scripts/gates/hosted_demo_seed.py`, `scripts/gates/hosted_purge_synthetic.py`, `scripts/gates/hosted_real_tenant.py` (PRP-139), `scripts/sandbox/**` (PRP-67 and PRP-71 own it).
- Depends on: item 1; PRP-139 merged.
- Acceptance criteria: the profile-guard criterion; the tests fail if a later change adds a seed profile for hosted or lets the profile render with the synthetic customer id.
- Tests: the two files (parser and template checks with fakes; no network).
- Pattern references: `tests/unit/gates/test_hosted_demo_seed_refuses.py`, `scripts/gates/hosted_demo_seed.py:105-123`.

### Item 3 - Signed-in navigation walk  [P]
- Deliverable: `hosted-nav-walk.spec.ts` that restores the session (as the existing spec does), reads the rendered navigation, visits each entry and each manifest route (detail routes through their list), records `nav-walk.json`, and applies the failure rules; `nav-expectations.ts` keyed by route with `rows` test id or `allowed` reason and owner PRP, where an empty page is allowed only as the PRP-139 source-aware empty state for a source the walk reads as `not_connected` from `GET /api/v1/sources/status`; a build identifier probe recorded to `build.json`; the copilot turn recorded to `copilot.json` (asks one catalog question, records answered or the typed disabled reason, never the answer text beyond a length and citation count).
- Owned files: `frontend/tests/hosted/hosted-nav-walk.spec.ts`, `frontend/tests/hosted/nav-expectations.ts`, `frontend/tests/hosted/nav-walk-support.ts`, `tests/unit/hosted_profile/test_nav_expectations.py`.
- Must NOT touch: `playwright.hosted.config.ts` semantics (add nothing unless the new spec is not matched), `frontend/src/**`, the existing `hosted-smoke.spec.ts` assertions.
- Depends on: none at build time (uses the manifest); data expectations follow the PRP-139 source status, not a seeded world.
- Acceptance criteria: the walk and expectations criteria; listing the spec offline (`--list`) shows it wired; the offline test fails when a manifest route lacks an expectation and when an allowed entry lacks a reason or owner.
- Tests: `tests/unit/hosted_profile/test_nav_expectations.py`; `pnpm --filter @neurosphere/frontend exec playwright test -c playwright.hosted.config.ts --list`; frontend lint and typecheck.
- Pattern references: `frontend/tests/real-stack/routes.spec.ts`, `frontend/tests/hosted/hosted-smoke.spec.ts:20-60`.

### Item 4 - Evidence layout and offline validator  [P]
- Deliverable: `hosted_profile_evidence.py` validating the directory layout and contents (criteria above), including the served-build versus image-tag comparison and the redaction scan; `docs/evidence/hosted/README.md` describing the layout and that real directories are added only by operator runs.
- Owned files: `scripts/gates/hosted_profile_evidence.py`, `docs/evidence/hosted/README.md`, `tests/unit/hosted_profile/test_evidence_validator.py`.
- Must NOT touch: other `docs/evidence/**`.
- Depends on: none.
- Acceptance criteria: the evidence and served-build criteria; a directory with a GUID, an `https://` host, or `nav-walk.json` with a failure fails; a complete synthetic fixture passes.
- Tests: `tests/unit/hosted_profile/test_evidence_validator.py` (fixtures built in the test, no committed secrets-shaped values).
- Pattern references: `scripts/gates/_evidence_paths.py`, `tests/unit/evidence_register/`.

### Item 5 - Operator runbook and live command list
- Deliverable: `docs/deploy/hosted-everything-on.md`: prerequisites (VPN, Entra user assignment, approved Foundry deployment, spend row, search service), the ordered commands (`hosted_demo.py plan`/`deploy` with `hostedProfile=everything-on` through the PRP-63 workflow, `--data-mode real-tenant`, `grant-model-access`, `hosted_real_tenant.py verify` from PRP-139, sign-in and storage-state capture, the walk; no seed and no `seed-access` step), the evidence validator call, troubleshooting (503 ingest, empty page with a connected source, stale build), what is real tenant data and what is a fixture, and a section stating which steps were not run.
- Owned files: `docs/deploy/hosted-everything-on.md`, `tests/unit/hosted_profile/test_runbook_commands.py`.
- Must NOT touch: `docs/deploy/hosted-demo.md`.
- Depends on: items 1-4.
- Acceptance criteria: the runbook criterion; every command in the runbook parses against the real CLI (`--help` or parser import) in an offline test; no placeholder looks like a real id.
- Tests: `tests/unit/hosted_profile/test_runbook_commands.py`, `tests/docs`.
- Pattern references: `tests/unit/hosted_demo/test_runbook_commands.py`.

### Item 6 - Integration and close-out
- Deliverable: `mkdocs.yml` nav line; changelog fragment `changelog.d/PRP-82-hosted-profile-everything-on.md`; completion note listing every live step OPEN with its command, env vars for the operator (`hostedProfile`, `copilotEndpoint`, `copilotDeployment`, `searchService`, `NS_LIVE_APPROVED`), and the product check (can the owner open the deployed app and click every nav entry with data once the operator has run the steps?).
- Owned files: `mkdocs.yml` (one line), this PRP file, the changelog fragment.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/hosted_profile tests/unit/hosted_demo tests/unit/gates tests/unit/infra tests/unit/hosted_data_path tests/docs
pnpm --filter @neurosphere/frontend exec playwright test -c playwright.hosted.config.ts --list
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. `hostedProfile` defaults to `baseline`, so an existing deployment redeploys unchanged. Switching to `everything-on` changes only app settings and role lists (restart); roll back by redeploying with `baseline` (the Bicep what-if shows the setting diff first). This PRP writes no data to a hosted environment; real records arrive only through the sources PRP-139 connects. Revert the PR to remove the parameter, walk and validator.

## Live and open gates
All of these need `NS_LIVE_APPROVED=1`, operator approval, the P2S VPN and, for the model, an approved Foundry deployment; none ran in this PRP and each is OPEN until recorded under `docs/evidence/hosted/`: deploy with `everything-on` on the real-tenant mode through the delivery pipeline; the signed-in nav walk against real tenant data (the per-source rows are the PRP-139 live gate and stay OPEN there until run) (Entra MFA); one live copilot turn and one real catalog question (the first live turn is also tracked by PRP-64); Azure AI Search against the real index (PRP-60 follow-through); a served-build check against the deployed tag. Throughput on the hosted ingest edge is PRP-84 and PRP-66.

## NOT building
New workflows or edits to the delivery pipeline (PRP-63); a CI browser run of the signed-in walk; changes to the infrastructure smoke; Government or multi-cloud hosted profiles (PRP-85 and later); a new Foundry account or deployment; a demo world or any synthetic seed in a hosted environment (D20); connecting sources or purging the old synthetic data (PRP-139); captured prompt or response content (capture stays off); write-target or deploy-apply enablement; fixes to pages found empty (each is filed against the PRP that owns the page); the governance-core features (interaction capture, policy engine, notifications, approval gate): "everything on" means every feature that exists when this PRP runs, those do not exist yet, and PRP-109 owns turning them on in the hosted profile.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 6 and 7 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | 1b serial-after PRP-67 |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Scope note: "everything on" here excludes the governance-core features that did not exist at this PRP's wave (capture, policy, notifications, approval); PRP-109 turns them on in hosted.
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
