---
name: PRP-71-realistic-seeded-world-and-demo-profile
status: active
started: 2026-11-19
priority: P0
order: 61
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-02, NS-05, NS-09
depends_on: [PRP-70-contracts-revision-restored-scope]
wave: W20
branch: prp-71-demo-world-and-profile
allow_parallel: true
issues: []
---

# PRP-71: Realistic seeded world and the local "everything on" demo profile

Changed 2026-11-17 (owner decision D20): the demo world is for local development and CI only and is never loaded into a hosted environment; PRP-82 no longer consumes it, and a hosted deployment shows real tenant data (PRP-139).

## Goal
Make one command bring up a local stack in which every navigation entry shows believable data. Two things ship. First, a curated, deterministic demo world (a new `demo-world` sandbox profile): named, described, tagged agents with owners and capabilities; services, tools and models; data assets classified with sensitivity and EU or US residency; `reads`, `writes`, `depends_on` and `owned_by` edges; a few undeclared agents that exist only in telemetry; agent versions with changed capabilities; and one scripted incident in which a failing service degrades the agents that depend on it. Second, a local demo profile (`make demo-up`) that turns on what is merely off today, using safe local backends: producer store, MCP server, deployment scan, lifecycle in dry-run, detector recommendations, worker roles including connector roles that stay idle but configured, stored feature settings, and the copilot on the recorded model. It is for the owner and anyone judging the product by clicking, and it is the seed that PRP-74 (map topology), PRP-72/73 (recommender and graph questions) and the live-map incident view need before they can be demonstrated locally. Synthetic data only, local and CI only: the `demo-world` profile is never loaded into a hosted environment (D20), and the hosted seed driver refuses it (PRP-139). It holds the compose stack in W20.

Out of scope: the contract fields and vocabularies themselves (PRP-70); the recommender, access questions and map backend that consume the data (PRP-72, PRP-73, PRP-74); the copilot recorded-model mode in the builder, its new tools and Helm values (PRP-78 owns the mode and the demo-profile switch; the owner decided on 2026-11-16 to allow the recorded mode for the local demo only, PRP-78 clarification 6); any hosted use of the demo world (none exists: a hosted deployment shows real tenant data, PRP-139, and PRP-82 turns features on against it); a real model endpoint (operator, PRP-64); changing `NS_*` defaults in code (defaults stay off; the profile sets them).

## Why
- Seed data is anonymous: the generator names tools `"<domain> tool 0003"` and sources `"<kind> source 0001"` (`sandbox/catalog.py:138,151`), agents carry no description and no tags (`sandbox/catalog.py:159-175`), so "even where it works it does not look like a product" (`temp/audit/original-prd-gap-analysis.md` section 3). The original PRD's personas ask questions that need names, owners and data scopes: 5b "As a compliance officer, I want to query 'which agents have write access to the customer database'" and 5e "which agents touch EU customer data?". v1.2 reduced the catalog to "versioned catalog/curated relationships" without a seeded world (`docs/PRD.md:13`).
- 5d story "during an incident, every downstream agent affected by a failing service" needs a failing service with downstream agents in the data; the generator injects cost spikes, latency regressions, unused agents and duplicate pairs (`sandbox/stack/profiles.json`) but no service outage and no services at all (the generator emits no `service` entities; gap analysis 5d).
- Shadow agents (5b "Stale/undeclared agents detected via telemetry-vs-catalog reconciliation job") only exist if telemetry names agents the catalog lacks; projections write `discovered_from=telemetry` drafts (`services/workers/neurosphere_workers/projections/catalog/handler.py:19-23,275-300`) but the seed never produces any.
- Most capabilities are present but off locally: copilot `disabled` (`docker-compose.yml:148`), `NS_INGEST_PRODUCERS_FILE` instead of the store (`docker-compose.yml:163`), no MCP, scan or lifecycle setting passed through, write targets off (`docker-compose.yml:180`), and `make stack-up` needs two exported Entra ids first (`Makefile:77-78`). The real-stack route walk keeps a `KNOWN_EMPTY` list of pages the seeded stack leaves empty (`tests/integration/real_stack/test_manifest_routes.py`, mirrored by `NO_DATA` in `frontend/tests/real-stack/routes.spec.ts:308`).
- The seed path is real and idempotent already (`scripts/sandbox/sbx_seed_stack.py:1-60`: telemetry through Event Hubs and the workers, catalog entities through `CatalogRepository.create_entity`, recommendations, evaluations, intents, reports, MCP servers), so the world can ride it instead of writing raw documents.

## Acceptance criteria
- [ ] Given `python -m sandbox.generate --seed 1 --profile demo-world --cloud commercial`, Then the NDJSON layout matches the existing generator's (README table) plus `services.ndjson` and an `incident-manifest.json`; every agent has a unique readable name, a one-sentence description, at least two tags, capabilities, an environment, a version label and an owner (an `owned_by` edge to a named team); output is byte-identical for the same seed and epoch and passes the schema-validity suite.
- [ ] The world contains at least: 30 agents across 4 domains, 6 services, 12 tools, 4 model deployments, 10 data assets spanning classifications and sensitivity categories (PII, PHI, financial at least) with both EU and US residency, `reads` and `writes` edges so that at least one data asset has two writer agents and at least one EU PII asset has a reader, and 4 agents that appear only in telemetry (no catalog entity), each recorded in the manifest.
- [ ] Given the incident manifest, Then one service fails during the last hour of the seeded window (error outcomes, raised latency) and its downstream agents (via `depends_on` or `invokes`) show degraded health in the aggregates while unrelated agents do not; the manifest names the service, the downstream agent ids and the window, so tests and the later map and copilot PRPs can assert against it.
- [ ] Agent versions include at least three agents with two versions whose declared capabilities differ, so a version diff has something to show.
- [ ] Tool and service identity: tool-call and service-bound spans in the seeded telemetry carry the PRP-70 fold F1 fields (`tool.external_tool_id`, `tool.canonical_tool_id`, `tool.tool_name`, `service.external_service_id`, `service.canonical_service_id`, `mcp_server_ref`) matching the seeded Tool, Service and McpServer entities, so PRP-100's per-tool and per-service aggregates and PRP-74's map have real series; spans without a tool or service leave the fields null; the output still validates as `TelemetryEvent`.
- [ ] Given `make demo-up` with the two Entra ids exported, Then the stack builds, seeds and reports healthy; given `make demo-check`, Then every route in `frontend/src/app/route-manifest.json` either has data behind its backing API call or appears in a named, reasoned allow-list (`demo_expected_empty`), and an unexplained empty page fails the check.
- [ ] The profile turns on, and `/api/v1/admin/system/status` reports as not disabled: producer store (`NS_INGEST_PRODUCER_STORE`), MCP server, scan, lifecycle (dry-run), detector recommendations from the archive source, connector roles idle-but-configured, and the stored feature settings; each non-obvious item has one line in `docs/dev/local-setup.md` saying what is real and what is fake.
- [ ] Copilot: the profile sets a single switch (`NS_DEMO_COPILOT_MODE`, always `disabled` when this PRP ships) and the check reports copilot as `pending_prp_78` rather than silently passing. Copilot on in the local demo is NOT delivered here: PRP-78 owns the recorded mode and flips the switch (the owner allowed it for the local demo on 2026-11-16, PRP-78 clarification 6), so the profile default becomes `recorded` once PRP-78 ships.
- [ ] No secret, key, connection string or real person data enters any tracked file; the profile env file holds names and non-secret values only; the sandbox guard (`scripts/sandbox/sbx_guard.py`) still refuses non-loopback endpoints.
- [ ] Re-running `make demo-up` or `make seed-stack` creates nothing new and reports `skipped_existing`.
- PRP exit: touched suites, `sandbox/tests`, `tests/unit/sandbox_stack`, `tests/unit/demo_profile`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; a compose run of `demo-up` and `demo-check` is recorded in the completion note (or reported OPEN if Docker was unavailable).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Hand-curated or generated names | Curated JSON; name tables fed to the random generator | Curated data files under `sandbox/demo/` for entities and edges (readable, reviewable), generator code only for telemetry volume around them; the curated world is deterministic by construction. |
| 2 | New fields and vocabularies | Define here; consume PRP-70 | Consume PRP-70 (tags, capabilities, environment on agent, tool and service; `sensitivity_categories` on data assets; revision record). If a field is missing at start, stop and report; do not define contract fields in this PRP. |
| 3 | Load path | Raw document writes; real seed path | Real path: `sbx_seed_stack.py` (Event Hubs and workers for telemetry; `create_entity` for catalog). |
| 4 | Copilot in the local profile | Edit the copilot builder here; wait for PRP-78 | Confirmed by the owner 2026-11-19: the `fixture` recorded adapter exists in core (`packages/core/neurosphere_core/copilot/models/gating.py:153,179`) but `CopilotMode` has no `fixture` value and `runtime/builders/copilot.py` is PRP-78's Tier-1 file in W23. This PRP ships the switch and check; PRP-78 (item 8, decided by the owner 2026-11-16) turns it on. |
| 5 | Write targets against fakes | Build a fake ARM server; keep advisory | Confirmed by the owner 2026-11-19: decided at item 5 after reading `runtime/builders/write_targets.py` and the cloud profile: a loopback fake is built only if the ARM host can be overridden under `NS_ENV=local`; otherwise write targets stay advisory with dry-run intents seeded, and the gap is reported OPEN. |
| 6 | Lifecycle | Execute; dry-run | Dry-run only (`NS_LIFECYCLE_MODE=dry_run`); local data is synthetic but execute mode has no UI yet (PRP-83). |
| 7 | New compose profile or env passthrough | Second compose file; existing file plus env file | Existing `docker-compose.yml` with `${VAR:-default}` passthrough for names PRP-58 did not already add, plus `infra/dev/demo-profile.env` (names and non-secret values). Defaults for non-demo runs unchanged. |
| 8 | Entra requirement | Keep; add a no-Entra demo | Keep (real sign-in is the product behaviour). The CI no-Entra path (`serve_stand_in_api.py`) is untouched. |

## Context manifest

### Files to read first
- `sandbox/README.md`, `sandbox/generate.py`, `sandbox/config.py` - output layout, profiles, epoch rules.
- `sandbox/catalog.py` and `sandbox/world.py` - how entities and relations are built today (names at `catalog.py:102,138,151,167`).
- `sandbox/traces.py` and `sandbox/costs.py` - telemetry and cost shape, anomaly injection.
- `sandbox/stack/profiles.json` - `small` and `demo` seed profiles; `load_profiles` at `scripts/sandbox/sbx_seed_stack.py:513`.
- `scripts/sandbox/sbx_seed_stack.py`, `sbx_seed_catalog.py`, `sbx_grant_operator.py`, `sbx_guard.py` - the real seed path and the loopback guard.
- `scripts/sandbox/sandbox.mk` and `Makefile:60-90` - `stack-up` ordering (grants before the app profile, #205).
- `docker-compose.yml` - env lists for `api` and `workers`, `seed` profile, mounts (`infra/dev/*.json`).
- `services/api/neurosphere_api/admin/system/stored.py` and `settings_router.py` - stored feature settings (PRP-45): keys `copilot`, `judge`, `search`, `scan`, `mcp_server`, `write_targets`.
- `services/api/neurosphere_api/mcp/server/settings.py`, `deploy/scan/settings.py`, `lifecycle/router.py` - what each switch needs.
- `docs/dev/local-setup.md` (Real stack section), `PRPs/backlog/PRP-70-*.md` if present.

### Interfaces consumed
- PRP-70 (names exactly as in its "Interfaces provided"): `tags`, `capabilities`, `environment` on `Agent` and `Tool`; `tags`, `environment` on `Service`, `McpServer`, `ModelDeployment`; `sensitivity_categories` and `residency_geography` (with `tags`, `environment`) beside `classification` on `GroundingSource`; `AgentVersion.semver`, `tags`, `capabilities`; `EntityRevision` for the seeded version history. The `service` entity type and the edge vocabulary are shipped, not PRP-70.
- PRP-45: `PUT /api/v1/admin/system/settings/{key}` semantics and the `admin_config` repository it writes through; `GET /api/v1/admin/system/status` for the check.
- PRP-41/42: producer store and connector configuration (`NS_INGEST_PRODUCER_STORE`); PRP-58: roles, store switch and compose passthrough names it added (read compose first, add only what is missing); PRP-54: stored `write_targets`; PRP-57: admin pages that need data.
- Shipped: `CatalogRepository`, `HubSeam` replay, `RecordedFixtureJudge`, `FixtureAdapter` (core).

### Interfaces provided
- Generator profile `demo-world` (flag `--profile demo-world`), files `services.ndjson` and `incident-manifest.json` {service id, downstream agent ids, window start/end, expected health transitions}; undeclared-agent list in `run-manifest.json`.
- Seed profile `demo-world` in `sandbox/stack/profiles.json`.
- `make demo-up`, `make demo-down`, `make demo-check`; `infra/dev/demo-profile.env`; env switch `NS_DEMO_COPILOT_MODE`.
- `scripts/sandbox/sbx_demo_check.py` (new) and the allow-list name `demo_expected_empty` (local and CI only; PRP-82's hosted walk no longer mirrors it and follows the PRP-139 source status instead).
- Stable demo ids and names (agents, services, data assets) that PRP-72, PRP-73, PRP-74, PRP-77, PRP-78 tests may assert against, documented in `sandbox/demo/README.md`.

### Patterns to match
- Entity builders and id scheme: `sandbox/catalog.py`, `sandbox/ids.py` (`cloud:customer:source:type:id`).
- Deterministic output and canonical NDJSON: `sandbox/output.py`; determinism test `sandbox/tests/test_determinism.py`.
- Idempotent seed with `skipped_existing`: `scripts/sandbox/sbx_seed_stack.py`; tests in `tests/unit/sandbox_stack/test_seed_stack.py`.
- Compose passthrough with defaults and a parity test: `docker-compose.yml:148-180`, `tests/unit/compose/`.
- Anomaly manifest: `sandbox/tests/test_anomaly_manifest.py`.

### Gotchas
- `make stack-up` order matters: grants-only seed before `docker compose --profile app up`, full seed after (`Makefile:68-74`); `make demo-up` must reuse it, not reorder it.
- Seeds run from the host against `127.0.0.1` only (`sbx_guard`); use `127.0.0.1`, not `localhost` (emulator IPv6 trap).
- Do not write literal 64-hex digests or credential-shaped values into fixtures (gitleaks); pseudonymous principals only, no names of real people (the existing `test_no_legacy_terms.py` and classification tests apply). Person names in the demo world are role labels ("Platform team", "Treasury analyst"), not people.
- The generator's time handling: the seed rebases the epoch so the newest event is 30 minutes before the run; the incident must be defined relative to the world's last hours so it is still "recent" after rebasing.
- Adding data changes counts that tests pin; keep `tiny`, `pilot` and `custom` profiles byte-identical (existing determinism tests must pass unchanged).
- Same-named test directories shadow each other: new tests go in `tests/unit/demo_profile` and `sandbox/tests/test_demo_world*.py`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - sandbox/demo/**
  - sandbox/generate.py
  - sandbox/config.py
  - sandbox/stack/profiles.json
  - sandbox/README.md
  - sandbox/tests/test_demo_world*.py
  - scripts/sandbox/sbx_seed_stack.py
  - scripts/sandbox/sbx_seed_catalog.py
  - scripts/sandbox/sbx_demo_check.py
  - scripts/sandbox/sbx_demo_settings.py
  - scripts/sandbox/sandbox.mk
  - infra/dev/demo-profile.env
  - infra/dev/fakes/**
  - tests/unit/demo_profile/**
  - tests/unit/sandbox_stack/test_demo_world_seed.py
  - tests/integration/real_stack/test_demo_profile.py
  - docs/dev/local-setup.md
tier1:
  - docker-compose.yml
  - Makefile
tier2_appends:
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/real-stack/routes.spec.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - services/api/neurosphere_api/map/**
  - services/api/neurosphere_api/catalog/**
  - packages/core/neurosphere_core/catalog/**
  - scripts/sandbox/sbx_guard.py
  - scripts/gates/**
  - infra/demo/**
  - infra/helm/**
  - infra/appservice/**
  - sandbox/demo/governance/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 4 [P] after item 1 (disjoint files). Item 3 after 1 and 2. Item 5 after 3 and 4. Item 6 after 5. Item 7 last.

### Item 1 - Curated demo world data
- Deliverable: `sandbox/demo/` with curated entity files (domains, teams as owners, agents with names, descriptions, tags, capabilities, environment, version labels, services, tools, models, data assets with classification, sensitivity and residency), the edge list (`owned_by`, `uses_model`, `invokes`, `reads`, `writes`, `depends_on`, `grounded_by`), two-version agents with differing capabilities, four telemetry-only agents, `sandbox/demo/build.py` writing them in the existing NDJSON layout, and `sandbox/demo/README.md` listing the stable ids and names.
- Owned files: `sandbox/demo/**` (data and `build.py`, not `incident.py`), `sandbox/tests/test_demo_world_catalog.py`.
- Must NOT touch: `sandbox/catalog.py`, `world.py`, contracts.
- Depends on: PRP-70 merged.
- Acceptance criteria: world-size, ownership and metadata criteria above; every document validates against the PRP-70 schemas; no legacy terms; names read like a business (finance, support, HR, security-operations domains).
- Tests: `sandbox/tests/test_demo_world_catalog.py` (schema validity, completeness, edge endpoints exist, writer and EU-PII criteria).
- Pattern references: `sandbox/tests/test_schema_validity.py`, `sandbox/catalog.py:90-175`.

### Item 2 - Telemetry for the demo world and the scripted incident  [P]
- Deliverable: `sandbox/demo/incident.py` (and the demo telemetry it shares with item 1's ids) emitting tool and service identity on spans per PRP-70 fold F1, producing delegation traces and cost for the curated agents (including telemetry-only agents that carry no catalog entity), a service outage window with error and latency effects on exactly the downstream agents, and `incident-manifest.json`.
- Owned files: `sandbox/demo/incident.py`, `sandbox/tests/test_demo_world_incident.py`.
- Must NOT touch: `sandbox/traces.py`, `costs.py` (call them).
- Depends on: item 1 (ids).
- Acceptance criteria: incident and shadow-agent criteria; unaffected agents keep a normal error rate; deterministic for seed and epoch; telemetry validates as `TelemetryEvent`.
- Tests: `sandbox/tests/test_demo_world_incident.py` (downstream set equals manifest, window inside the last hour, determinism).
- Pattern references: `sandbox/traces.py`, `sandbox/tests/test_anomaly_manifest.py`.

### Item 3 - Generator profile and seed wiring
- Deliverable: `--profile demo-world` in `sandbox/generate.py` and `sandbox/config.py` (existing profiles untouched); a `demo-world` entry in `sandbox/stack/profiles.json`; `sbx_seed_stack.py` and `sbx_seed_catalog.py` load services and the new fields, assign grants for the four demo personas, rebase time so the incident is recent, and stay idempotent.
- Owned files: `sandbox/generate.py`, `sandbox/config.py`, `sandbox/stack/profiles.json`, `sandbox/README.md`, `scripts/sandbox/sbx_seed_stack.py`, `scripts/sandbox/sbx_seed_catalog.py`, `tests/unit/sandbox_stack/test_demo_world_seed.py`.
- Must NOT touch: `sbx_guard.py`, `sbx_grant_operator.py` behaviour.
- Depends on: items 1 and 2.
- Acceptance criteria: idempotence criterion; `tiny`, `pilot`, `custom` output byte-identical to before; seed counts reported per category including services.
- Tests: `tests/unit/sandbox_stack/test_demo_world_seed.py`, plus `tests/unit/sandbox_stack`, `sandbox/tests` unchanged.
- Pattern references: `scripts/sandbox/sbx_seed_stack.py:513-530`, `tests/unit/sandbox_stack/test_seed_stack.py`.

### Item 4 - Demo profile: compose passthrough, env file, Makefile  [P]
- Deliverable: `infra/dev/demo-profile.env` (names and non-secret values: producer store on, worker roles including recommendations and connector roles, `NS_WORKER_REC_SOURCE=archive`, MCP resource URL and audiences placeholders that resolve locally, `NS_SCAN_ENABLED=true`, `NS_LIFECYCLE_MODE=dry_run`, `NS_DEMO_COPILOT_MODE`); `docker-compose.yml` passthrough for any of those names PRP-58 did not add; `Makefile` targets `demo-up` (stack-up ordering with `SEED_PROFILE=demo-world`), `demo-down`, `demo-check`.
- Owned files: `infra/dev/demo-profile.env`, `docker-compose.yml`, `Makefile`, `scripts/sandbox/sandbox.mk` (new variables only), `tests/unit/demo_profile/test_compose_passthrough.py`.
- Must NOT touch: `infra/demo/**`, `infra/helm/**`.
- Depends on: PRP-58 merged (read what it added first).
- Acceptance criteria: with the env file absent the compose config renders as before (golden or `docker compose config` comparison in an offline test); no name in the env file matches the secret-name markers; every name used by the profile is a name the code reads (test greps settings classes).
- Tests: `tests/unit/demo_profile/test_compose_passthrough.py`, `tests/unit/compose`.
- Pattern references: `docker-compose.yml:138-180`, `tests/unit/compose/`.

### Item 5 - Stored settings seeding and local write targets
- Deliverable: `scripts/sandbox/sbx_demo_settings.py` writing the stored feature settings (`scan`, `mcp_server`, `search`, `copilot` placeholder, `write_targets` entries) through the same `AdminConfigRepository` path the PUT route uses (audited, local guard only), called by the seed; `infra/dev/fakes/` with a loopback fake of the Foundry/APIM read endpoints only if item 5's read of `runtime/builders/write_targets.py` shows the host is overridable under `NS_ENV=local`; otherwise seeded dry-run intents and an OPEN note. Item 5b `[serial-after: PRP-78]`: set the copilot mode to the recorded adapter when PRP-78 lands (one line in `infra/dev/demo-profile.env`, the check flips from `pending_prp_78`).
- Owned files: `scripts/sandbox/sbx_demo_settings.py`, `infra/dev/fakes/**`, `tests/unit/demo_profile/test_demo_settings.py`.
- Must NOT touch: `runtime/builders/write_targets.py`, `runtime/builders/copilot.py`, worker `factories.py`.
- Depends on: items 3 and 4.
- Acceptance criteria: `GET /api/v1/admin/system/settings` lists the seeded keys with source `stored`; no credential-shaped field is stored (the PRP-45 validator refuses them; test asserts); the fake binds loopback only.
- Tests: `tests/unit/demo_profile/test_demo_settings.py` (stored shape validates through the settings classes, guard refuses non-loopback).
- Pattern references: `admin/system/stored.py`, `sbx_grant_operator.py`.

### Item 6 - Demo check and the empty-page ledger
- Deliverable: `scripts/sandbox/sbx_demo_check.py` (reads the route manifest, calls each page's backing API as the seeded operator through the dev sign-in already used by `routes.spec.ts` helpers, or the stand-in API in CI, and fails on an empty response not in `demo_expected_empty` with a reason); shrink `KNOWN_EMPTY` (the `NO_DATA` map in `routes.spec.ts` is empty today; keep it empty); `tests/integration/real_stack/test_demo_profile.py` (marker `integration`, run by the real-stack job).
- Owned files: `scripts/sandbox/sbx_demo_check.py`, `tests/integration/real_stack/test_demo_profile.py`, Tier-2 lines in `tests/integration/real_stack/test_manifest_routes.py` and `frontend/tests/real-stack/routes.spec.ts`.
- Must NOT touch: other real-stack tests, frontend sources.
- Depends on: item 5.
- Acceptance criteria: demo-check criterion; allow-list entries each carry a reason and an owning PRP; a page that regresses to empty fails.
- Tests: `tests/unit/demo_profile/test_demo_check.py` (check logic against a fake client), `tests/integration/real_stack/test_demo_profile.py`.
- Pattern references: `tests/integration/real_stack/test_manifest_routes.py`, `frontend/tests/real-stack/routes.spec.ts:50-90`.

### Item 7 - Integration and close-out
- Deliverable: `docs/dev/local-setup.md` "Demo profile" section (one command, what is real, what is fake, how to enable a real copilot endpoint, how to reset); `mkdocs.yml` line if the docs build needs it; Tier-3 regeneration if any generated file changed (none expected: no API change); changelog fragment `changelog.d/PRP-71-realistic-seeded-world-and-demo-profile.md`; completion note with env vars for the operator and the product check (does every nav entry show data after one command?).
- Owned files: `docs/dev/local-setup.md`, this PRP file, the changelog fragment.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q sandbox/tests tests/unit/sandbox_stack tests/unit/demo_profile tests/unit/compose tests/docs
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local, not CI (needs Docker and the two exported Entra ids): `make demo-up` then `make demo-check`; record the output.

## Migration and rollback
No data migration. The demo world is new generator output and seed data in a local database; `make seed-reset` or `make dev-reset` drops it. The profile is opt-in (env file and `demo-*` targets); `make stack-up` and the default compose run behave as before. Revert the PR to remove it; stored settings written locally live in the local `admin_config` container only.

## Live and open gates
None live. Everything runs on emulators and fakes. OPEN until PRP-78 ships: the copilot answering in the profile. OPEN until an operator supplies a model endpoint (PRP-64): a real copilot turn. If the local write-target fake is not possible (clarification 5), write-target apply stays advisory and is reported OPEN. A compose run that did not happen is reported OPEN, not passed.

## NOT building
New contract fields or vocabularies (PRP-70); map, recommender or graph-question backends (PRP-72, 73, 74); a hosted seed of the demo world (not built by any PRP, D20) and the hosted smoke (PRP-82); a real or paid model call; execute-mode lifecycle; production data of any kind; changing code defaults so that features are on outside the profile; the governance seed (synthetic governance agent, PII-labelled asset, policy, notification sink) under `sandbox/demo/governance/**`, which PRP-109 owns.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 4 and 5 confirmed by the owner 2026-11-19)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-71-item-1-demo-world-data | sonnet; verify PASS 2026-11-19 (ruff, format, pyright, sandbox/tests 55 passed) at 417ebe38; review APPROVED; merged 0c90a172 |
| 2 | merged | prp-71-item-2b-delegation | sonnet; two rounds (d7ab3cb7 telemetry and incident, 0e1fec4e delegation pairs and spans); verify PASS 2026-11-19 (ruff, format, pyright, sandbox/tests 72 passed); review APPROVED; merged edc4e015 |
| 3 | merged | prp-71-item-3-generator-seed-wiring | sonnet; verify PASS 2026-11-19 (ruff, format, repo-wide pyright, 221 passed, generator double run byte-identical) at 9c7c0b7e; five personas granted (fixture has five, not four); review APPROVED; merged fc2b09da |
| 4 | merged | prp-71-item-4-demo-profile | sonnet; verify PASS 2026-11-19 (ruff, format, pyright, 133 passed across demo_profile, compose, hosted_data_path, sandbox_stack, write_targets_profiles) at a4f58c79; NS_WORKER_ROLES not in profile (compose pins all); review APPROVED; merged 877d8fee |
| 5 | merged | prp-71-item-5-demo-settings | sonnet; verify PASS 2026-11-19 (ruff, format, repo-wide pyright, 231 passed) at 082d2e8f; clarification 5: no fake, ARM host not overridable, write-target apply OPEN; item 5b waits on PRP-78; review APPROVED; merged 5d3d196d |
| 6 | merged | prp-71-item-6c-live-fixes | sonnet; three rounds (bbae19df check, 3715346c az token in memory, live fixes b47c11b8 and 0541ef2d by the orchestrator); unit gates PASS 2026-11-20 (ruff, pyright, demo_profile 100 passed); review APPROVED on b47c11b8, the later banner and domain-grain incident row (0541ef2d) were not re-reviewed; live demo-check 55 of 56 routes with data, incident rows not yet verified; merged ef16475f |
| 7 | merged | prp-71-demo-world-and-profile, then prp-71-incident-model-call-errors | orchestrator; docs section and changelog fragment (1ff031f6) merged with PR #353 (4c2869a2); the recorded compose run found four more live-only defects, fixed in PR #355 (bbed2b98 incident and null tokens, 62e836cd check wait, 8168eab8 seed profile, 2bda8d16 publish throttle); review APPROVED on the PR #355 diff; clean `make demo-up` and `make demo-check` PASS 2026-11-20 |

## Completion note (filled at ship)
- Date and PR: 2026-11-20. PR #353 (squash `4c2869a2`) shipped items 1 to 7. PR #355 shipped the fixes the recorded compose run found. Review: one independent pass per item (APPROVED), and one on the whole PR #355 diff (APPROVED, no blocking findings).
- Recorded compose run (2026-11-20, emulators, synthetic data only, empty volumes): `make demo-up OPERATOR_OID=<own object id>` exit 0 in 18 minutes, 8,773 telemetry and cost events pushed, the closing catalog seed container reported every grant unchanged and nothing created. The aggregates reached the end of the incident hour about 70 minutes after the seed. `make demo-check` then exit 0: 56 of 56 routes with data; producer store, MCP server, scan, lifecycle (dry_run) and stored settings enabled; copilot `pending_prp_78`; 32 of 32 curated agents; 4 telemetry-only agents discovered as drafts; `outage_domain_error_rate` pass (3 affected domains reach 0.05, the unaffected one stays under it; an earlier run of the same generator measured finance 0.36, human-resources 0.22, support 0.10, security-operations 0.0 in the incident hour); `outage_downstream_health` not_checked. Workers healthy for over an hour with 0 role crashes. A re-run of `make seed-stack SEED_PROFILE=demo-world` created nothing (`skipped_existing` 20460 on the earlier stack).
- Deviations:
  - The incident as first shipped (PR #353) did not show in the product: it failed tool, run and request spans, and the aggregates count `model_call` spans only. PR #355 adds an abandoned `model_call` per failed call to the outage service and two retries of the service call (`INCIDENT_MAX_ATTEMPTS`). The manifest is unchanged. PRP-100 and PRP-74 authors: agent error rate and health come from `model_call` spans; the failing `tool_call` spans with service identity are there for PRP-100's tool and service points.
  - Five personas are granted, not four (the fixture has five). `NS_WORKER_ROLES` is not in the profile (compose pins all roles).
  - Fixes outside the declared ownership, each found by the live run and each with a test: `packages/core/neurosphere_core/admin/cosmos_store.py` (PR #353, stored settings with a null became unreadable), `services/workers/neurosphere_workers/recommendations/pipeline.py` (null token counts crashed the recommendations role on every tick), `scripts/sandbox/sbx_seam.py` (the publish now waits out the Event Hubs emulator throttle), `Makefile` (the closing catalog seed container takes `SEED_PROFILE`; at its default it re-granted the worker over the small world and the evaluation role failed five minutes after `demo-up`).
- Descoped items: item 5b (copilot recorded mode in the profile) waits on PRP-78.
- OPEN gates:
  - Copilot answering in the profile: OPEN until PRP-78. A real copilot turn: OPEN until an operator supplies a model endpoint (PRP-64).
  - Write-target apply against a local fake: OPEN. The management host cannot be pointed at a loopback fake, so write targets stay advisory with dry-run intents seeded.
  - Per-agent health of the five downstream agents on a REST route: NOT CHECKED. Health is computed only in the realtime WebSocket source and the map viewport answers `unknown` until PRP-74; the check verifies the incident at domain grain.
  - The window bound of the incident traces is measured, not structural: seeds 1 to 8 stay inside the seeded window (latest event 21 seconds before its end); the stack seed always uses seed 1.
- Env vars for the operator: `NS_ENTRA_TENANT_ID` and `NS_ENTRA_CLIENT_ID` exported (ids, not secrets) and `az login`; `OPERATOR_OID` on the `make demo-up` line. Optional: `NS_DEMO_COPILOT_MODE` (stays `disabled` until PRP-78), `NS_SEED_WAIT_SECONDS`, `NS_DEMO_CHECK_API_URL`, `NS_DEMO_CHECK_TOKEN_FILE`. Everything else is in `infra/dev/demo-profile.env` (names and non-secret values).
- Follow-up issue numbers: #356 (the overview's "today" tile is the current UTC day, so `/` goes empty after UTC midnight and `make demo-check` then fails that row until a reseed).
- Product check (can an operator use it without editing files): yes for the day of the seed. One command (`make demo-up OPERATOR_OID=...`) with two exported ids gives a signed-in operator data on every one of the 56 routes, including the role-gated pages, and the incident is visible in the error dashboards about 70 minutes later (the seeded data drains oldest first). Not yet: the overview page is empty from the next UTC midnight (#356), the copilot is off (PRP-78), and the map does not show which agents are failing (PRP-74).
