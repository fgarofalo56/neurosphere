---
name: PRP-45-system-status-first-run-and-feature-settings
status: backlog
priority: P0
order: 36
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-06, NS-08, NS-09, NS-10
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-65-admin-permissions-policy-repository-and-config-store, PRP-39-identity-admin-api-and-revocation, PRP-48-authorization-and-audit-chain-hardening]
wave: W16
branch: prp-45-system-status-settings
allow_parallel: true
issues: [242]
---

# PRP-45: System status, first-run checklist and stored feature settings

## Goal
Give an operator one authenticated place that answers "what is configured, what is off and why, and what do I do next", and let them change the runtime feature settings that today are env vars plus a redeploy: copilot mode and model endpoint, evaluation judge, search provider, deployment scan, the NeuroSphere MCP server, and write-target entries. Ships a system-status API and a first-run checklist API derived from the same component registry `/readyz` uses, plus audited, ETag-guarded stored settings that the API builders and the worker evaluation role read at startup (stored value over env, restart to apply). It is for the operator standing up a deployment and for the admin console page that PRP-53 builds on it. Now, because step 1 of the 2026-11-06 re-plan (operator control plane) is still MISSING and every admin page in W17-W18 needs this API.

Out of scope: `/readyz` probe defaults and `probe_unconfigured` (#143) are PRP-58; turning stored write-target entries into registered connectors, more than one target per connector kind and profile wiring are PRP-54; the admin console pages are PRP-53 (status, checklist) and PRP-57 (models and feature settings); producers and connector credentials are PRP-41 and PRP-42; domains, budgets, price sheets and review policy are PRP-44; the schemas, the `admin-config` container and the permissions are PRP-37/PRP-65.

## Why
- No admin, settings or status router exists: `services/api/neurosphere_api/routers.py:222-251` (`REGISTERED`) has no such hook (lane-d step 1).
- The only aggregate view is public `/readyz` JSON (`services/api/neurosphere_api/health/router.py:52-62`); its composition detail entries are names only, built in `runtime/readiness.py:54-76` from `ComponentRegistry` (`runtime/status.py:35-55`). Nothing in `frontend/src` reads it (lane-d step 1, "Feature enablement + readyz first-run checklist").
- Copilot is env-only and disabled by default (`runtime/builders/copilot.py:82,107-110`, `NS_COPILOT_*`); search is `NS_SEARCH_*` (`runtime/builders/search.py:78-81`); the MCP server is `NS_MCP_*` (`mcp/server/settings.py:46-58,127-133`); scan is `NS_SCAN_ENABLED` read from `main.py:33` through `deploy/scan/bootstrap.py:54`.
- The judge is `NS_WORKER_EVAL_*` env only (`services/workers/neurosphere_workers/runtime/settings.py:117-145`), built in `factories.py:844-875` from `EvalSettings()` at `factories.py:1018`.
- Write targets are `NS_FOUNDRY_*` / `NS_APIM_*` env plus restart, one per kind (`runtime/builders/write_targets.py:10-33`; worker `runtime/settings.py:168-216`); lane-d step 3: "No UI or API to register a write target".
- Lane 4 section 5: the operator "cannot choose or change the copilot model, evaluator model, search provider, or write targets" and "cannot see a single system status screen" (`docs/validation/lane4-identity-docs-operator-setup.md:268-283`).

## Acceptance criteria
- [ ] Given a deployment-scoped admin, When `GET /api/v1/admin/system/status` is called, Then it returns every component of the composition registry with state, required flag and reason code, plus the environment probe results, and never a configuration value, host or secret (test asserts the body against a registry with failed, disabled and not_built components).
- [ ] Given a caller without the deployment-scoped admin permission (including `config.manage` in an ordinary domain only), When any `/api/v1/admin/system/*` route is called, Then it is 403 and the denial is recorded by the denial recorder.
- [ ] `GET /api/v1/admin/system/checklist` returns one item per checklist entry (optional components, ingest producers, write targets, stored-settings store reachable, auth customer binding) with state `done | todo | blocked | not_applicable`, a reason code and a docs anchor; the item ids are stable and listed in the runbook.
- [ ] `GET /api/v1/admin/system/settings` lists the six setting keys (`copilot`, `judge`, `search`, `scan`, `mcp_server`, `write_targets`) with source `stored | env | default`, stored revision, applied revision and `restart_required`.
- [ ] `PUT /api/v1/admin/system/settings/{key}` validates the body through the same settings class the builder uses, needs `If-Match` (missing is `invalid_schema`, stale is `stale_version`, the catalog convention), stores through the PRP-37/PRP-65 `admin-config` repository with an audit record, and returns the diff and the new revision.
- [ ] A stored value that names a credential (any field matching the copilot `KEY|SECRET|PASSWORD` markers) or a value in another cloud than the deployment's is refused with 422 and nothing is stored; references only (A7 vocabulary from PRP-37/PRP-65).
- [ ] Given stored `copilot`, `search`, `mcp_server` or `scan` settings, When the API starts, Then the builders use them over env (A1) and status reports source `stored`; Given the store unreachable at startup, Then builders use env and the checklist shows `stored_settings_unavailable`.
- [ ] Given a stored `judge` setting, When the evaluation worker role starts, Then `_evaluation_judge` builds from it; a Commercial endpoint in a Government deployment fails the role with the existing `evaluation_judge_*` reason, never a cross-cloud call.
- [ ] Stored `write_targets` entries are validated and listed but not registered by this PRP (PRP-54 consumes them); status says so.
- [ ] Route inventory has no undeclared route; OpenAPI drift test passes after regeneration.
- PRP exit: an operator with a deployment-scoped admin assignment can read status and checklist and change the copilot, judge, search, scan and MCP server settings through the API, restart, and see them applied, with every write audited.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | When do stored settings apply | Startup only with a restart signal; live rebuild of the builder | ASSUMPTION: A1. Startup only; status shows `restart_required` when stored revision differs from applied revision. No hot reload. |
| 2 | Precedence of stored over env | Stored wins; env wins; per-field merge | ASSUMPTION: a stored setting, when present and valid, is passed as init arguments to the existing settings class (pydantic-settings init args beat env), so env stays the bootstrap default and validation is unchanged. |
| 3 | Which permission gates the routes | `config.manage` anywhere; deployment-scoped admin | Deployment-scoped admin permission from PRP-37/PRP-65 (#114 direction): these settings act on the whole deployment. Reads and writes both need it. |
| 4 | Do settings writes go through the action executor | Executor intent; audited config write | Audited, ETag-guarded config write through the PRP-37/PRP-65 `admin-config` repository with a returned diff. They change NeuroSphere's own configuration, not an external system, so the executor is not used. ASSUMPTION, flag to the user at plan approval. |
| 5 | Store failure at startup | Fail readiness; fall back to env | ASSUMPTION: fall back to env with a checklist item `stored_settings_unavailable`; env is operator-controlled, so this cannot widen access. |
| 6 | Where the scan setting is applied | `main.py`; `deploy/scan/bootstrap.py` | `deploy/scan/bootstrap.py` reads the same cached stored snapshot; `main.py` is not a W16 Tier-1 file for this PRP. |

## Context manifest

### Files to read first
- `PRPs/reference/parallel-build-reference.md` - tiers, commands, traps, close-out.
- `services/api/neurosphere_api/runtime/status.py` - `ComponentRegistry`, `REQUIRED_COMPONENTS`, `OPTIONAL_COMPONENTS`, `is_reason_code`.
- `services/api/neurosphere_api/runtime/readiness.py` - how `/readyz` details are derived; reuse, do not duplicate.
- `services/api/neurosphere_api/runtime/compose.py:163-200` - `compose_app`; registry stored at `app.state.composition` (`STATE_ATTRIBUTE`).
- `services/api/neurosphere_api/runtime/builders/__init__.py:184-376` - `BuilderSpec`, `BuildContext.attempt/disabled`, `default_builders`.
- `services/api/neurosphere_api/runtime/builders/copilot.py:82-120` - `ENV_PREFIX`, credential-name refusal, `CopilotRuntimeSettings`.
- `services/api/neurosphere_api/runtime/builders/search.py:78-98` - `SearchSettings`.
- `services/api/neurosphere_api/mcp/server/settings.py:46-133` - `McpServerSettings`, `load_mcp_server_settings`.
- `services/api/neurosphere_api/deploy/scan/bootstrap.py:40-70`, `deploy/scan/settings.py:9` - `ScanSettings`, opt-in bootstrap.
- `services/workers/neurosphere_workers/runtime/factories.py:844-875,1017-1030` - `_evaluation_judge`, `build_evaluation`.
- `services/api/neurosphere_api/actions/customer_control.py:91-110` - customer-level check pattern.

### Interfaces consumed
- From PRP-37/PRP-65 (names in PRP-37/PRP-65's "Interfaces provided"): the system-setting schema and the first-run checklist item schema (generated Python and TS models), the audited, ETag-guarded `admin-config` Cosmos container and its repository with an in-memory twin, the deployment-scoped admin role and permission, the credential-reference vocabulary.
- From PRP-39: the `neurosphere_api.admin` package root and the `runtime/builders/admin.py` builder pattern for admin routers.
- From PRP-48 (W15, merged before W16): the deployment-scoped admin dependency under `services/api/neurosphere_api/authz/`. If it is not on `main` at session start, stop and report rather than re-implementing it.
- Existing: `ComponentRegistry` snapshot on `app.state.composition`; `run_probes`/`probes_from_env` (`health/probes.py`).

### Interfaces provided
- Routes: `GET /api/v1/admin/system/status`, `GET /api/v1/admin/system/checklist`, `GET /api/v1/admin/system/settings`, `GET|PUT /api/v1/admin/system/settings/{key}`.
- Core: `neurosphere_core.admin.runtime` (new) with the stored-settings snapshot loader (`load_stored_settings`, cached per process), per-key validators and `SETTING_KEYS`.
- Status component `admin_system` (optional) in `runtime/status.py`.
- Stored `write_targets` entries readable through the snapshot loader, for PRP-54.
- Checklist item ids, documented in `docs/runbooks/system-settings.md` (new), for PRP-53.

### Patterns to match
- Opt-in settings that are a no-op when unset: `services/api/neurosphere_api/ingest/bootstrap.py:44-63`.
- Builder status reporting: `runtime/builders/edge.py:17-27`; `BuildContext.attempt` at `runtime/builders/__init__.py:324`.
- Cloud gating that disables with a reason, never a cross-cloud fallback: `packages/core/neurosphere_core/search/azure/fallback.py:36-62`.
- Env-clearing test conftest: `services/api/tests/runtime_planes/conftest.py:8-36`.
- `If-Match` and `ETag` handling: `services/api/neurosphere_api/catalog/router.py:36-37,120,255`.

### Gotchas
- Builders do no network I/O. The stored-settings read is the single exception and happens once, before `_run_builders`, with a bounded timeout; it must not run inside a builder.
- Status bodies carry names and reason codes only, the same rule as `runtime/readiness.py:15`. Never echo a stored endpoint back in status; the settings route returns stored values only to the deployment-scoped admin.
- `CopilotCredentialConfigError` is a `BaseException` subclass (`copilot.py:89`, #131); do not catch it broadly in the settings validator, call the name check directly.
- Adding `admin_system` to `OPTIONAL_COMPONENTS` changes `/readyz` detail output; update tests that pin the component list (`services/api/tests/runtime_api/test_readiness.py`).
- `runtime/builders/write_targets.py` is in this PRP's Tier-1 grant for W16 but is not edited here; PRP-54 owns its logic change.
- `.env.example` is agent-blocked: list any new `NS_*` name in the completion note.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/admin/system/**
  - packages/core/neurosphere_core/admin/runtime/**
  - services/api/tests/admin_system_api/**
  - packages/core/tests/admin_runtime/**
  - services/workers/tests/stored_settings_worker/**
  - services/api/neurosphere_api/runtime/builders/admin_system.py
  - services/api/neurosphere_api/deploy/scan/bootstrap.py
  - docs/runbooks/system-settings.md
  - docs/runbooks/runtime-composition.md
tier1:
  - services/api/neurosphere_api/runtime/compose.py
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - services/api/neurosphere_api/runtime/builders/mcp.py
  - services/api/neurosphere_api/runtime/builders/search.py
  - services/api/neurosphere_api/runtime/builders/write_targets.py
  - services/api/neurosphere_api/runtime/status.py
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/tests/authz/test_route_inventory.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/admin/*.py
  - services/api/neurosphere_api/health/probes.py
  - services/api/neurosphere_api/main.py
  - services/api/neurosphere_api/authz/**
  - infra/**
  - frontend/**
```

## Implementation blueprint

### Item 1 - stored-settings core  [P]
- Deliverable: `neurosphere_core.admin.runtime` with `SETTING_KEYS`, one validator per key that builds the target settings class from stored fields (copilot, search, MCP server, scan in the API; judge in workers; write-target entries as a list), credential-name and cloud checks, and `load_stored_settings(repository, timeout)` returning an immutable snapshot (key to value, revision) cached per process; unreachable store returns an empty snapshot with reason `stored_settings_unavailable`.
- Owned files: `packages/core/neurosphere_core/admin/runtime/**`, `packages/core/tests/admin_runtime/**`.
- Must NOT touch: PRP-37/PRP-65 schemas and repository modules.
- Depends on: none.
- Acceptance criteria: each key round-trips; a `*_KEY`/`SECRET`/`PASSWORD` field is refused; a Commercial endpoint in a Government profile is refused; timeout yields the empty snapshot.
- Tests: `packages/core/tests/admin_runtime/test_validators.py`, `test_snapshot.py`.
- Pattern references: `runtime/builders/copilot.py:95-105`, `search/azure/fallback.py:36-62`.

### Item 2 - status and checklist API  [P]
- Deliverable: `admin/system/router.py` with status and checklist routes over `app.state.composition` and `run_probes`; checklist derivation in `admin/system/checklist.py`; deployment-scoped dependency on every route.
- Owned files: `services/api/neurosphere_api/admin/system/**`, `services/api/tests/admin_system_api/test_status*.py`, `test_checklist*.py`.
- Must NOT touch: `runtime/readiness.py`, `health/**`.
- Depends on: none.
- Acceptance criteria: criteria 1-3; body has no value outside the reason-code pattern (property test over a registry with every state).
- Tests: `services/api/tests/admin_system_api/test_status.py`, `test_checklist.py`, `test_status_authz.py`.
- Pattern references: `runtime/readiness.py:54-76`, `actions/customer_control.py:91-110`.

### Item 3 - settings API
- Deliverable: `GET/PUT` settings routes with `If-Match`, diff, audit through the PRP-37/PRP-65 repository, validation from item 1; `restart_required` from stored versus applied revision (applied revision recorded at startup by item 4).
- Owned files: `services/api/neurosphere_api/admin/system/settings_router.py` (new), `services/api/tests/admin_system_api/test_settings*.py`.
- Must NOT touch: builders.
- Depends on: item 1.
- Acceptance criteria: criteria 4-6 and 9.
- Tests: `services/api/tests/admin_system_api/test_settings.py`, `test_settings_refusals.py`.
- Pattern references: `catalog/router.py:36-37,120,255`.

### Item 4 - API builders read stored settings
- Deliverable: `compose_app` loads the snapshot once before `_run_builders` and records applied revisions; copilot, search and MCP builders pass stored fields as init arguments; scan bootstrap reads the same cached snapshot; new `runtime/builders/admin_system.py` builder installs the router state and reports `admin_system`.
- Owned files: Tier-1 `runtime/compose.py`, `runtime/builders/{copilot,mcp,search}.py`, `runtime/status.py` (append `admin_system`), `runtime/builders/admin_system.py` (new), `deploy/scan/bootstrap.py`, `services/api/tests/admin_system_api/test_builders_stored.py`.
- Must NOT touch: `main.py`, `write_targets.py` logic.
- Depends on: item 1.
- Acceptance criteria: criterion 7; with no stored settings every existing builder test passes unchanged.
- Tests: `services/api/tests/admin_system_api/test_builders_stored.py`; re-run `runtime_api`, `runtime_data`, `runtime_planes`, `runtime_routes`, `copilot_api`, `mcp_api`, `deployment`.
- Pattern references: `runtime/builders/edge.py:17-27`.

### Item 5 - worker judge reads stored settings
- Deliverable: `build_evaluation` loads the snapshot through a sync reader and passes stored judge fields into `EvalSettings`; failure keeps env.
- Owned files: Tier-1 `services/workers/neurosphere_workers/runtime/factories.py` (`build_evaluation` body only), `services/workers/tests/stored_settings_worker/**`.
- Must NOT touch: other builder bodies, `BUILDERS` order.
- Depends on: item 1.
- Acceptance criteria: criterion 8.
- Tests: `services/workers/tests/stored_settings_worker/test_judge_stored.py`; re-run `services/workers/tests/evaluation_worker`.
- Pattern references: `factories.py:844-875`.

### Item 6 - Integration and close-out
- Deliverable: Tier-2 appends (`routers.py` hook, `default_builders` entry, route inventory, `mkdocs.yml` nav), `docs/runbooks/system-settings.md` (checklist ids, setting keys, restart rule), runtime-composition runbook cross-links, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry, completion note per reference section 6.
- Owned files: Tier-2 list above, the two runbooks, this PRP file.
- Depends on: items 1-5.
- Acceptance criteria: criterion 10; validation gates green; product check recorded (settings usable without file edits; UI is PRP-53/57).
- Tests: `services/api/tests/test_openapi_drift.py`, `tests/docs/test_reference_coverage.py`, `tests/docs/test_nav_allowlist.py`.
- Pattern references: reference section 6.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/admin_runtime services/api/tests/admin_system_api services/workers/tests/stored_settings_worker services/workers/tests/evaluation_worker services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_planes services/api/tests/runtime_routes services/api/tests/copilot_api services/api/tests/mcp_api services/api/tests/deployment services/api/tests/authz services/api/tests/health services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
No data migration: stored settings are new documents in the PRP-37/PRP-65 `admin-config` container. With no stored document every builder behaves exactly as today (env). To turn a stored setting off, delete it through the API (or set it back) and restart; to revert the feature, revert the PR: builders return to env-only and the documents are ignored.

## Live and open gates
None run here. A stored copilot or judge endpoint pointing at a real model is only exercised by PRP-64's G16 judge item and a hosted copilot check, each needing `NS_LIVE_APPROVED=1`; both handed to PRP-64 and reported OPEN in the completion note.

## NOT building
- Hot reload of builders (A1), `/readyz` probe settings (#143, PRP-58), write-target registration and multiple targets per kind (PRP-54), UI pages (PRP-53, PRP-57), budgets, domains, price sheets, review policy (PRP-44), producers and connector credentials (PRP-41, PRP-42), branding.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 2, 4, 5 are assumptions to confirm at plan approval)

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
- Product check:
