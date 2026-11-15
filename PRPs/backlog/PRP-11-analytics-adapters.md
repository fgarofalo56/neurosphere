---
name: PRP-11-analytics-adapters
status: backlog
priority: P1
order: 22
review: required
created: 2026-10-08
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 2
ns: NS-01, NS-07
depends_on: []
wave: W12
branch: prp-11-round2-analytics-runtime
allow_parallel: true
absorbs: P2.1
issues: [228, 59, 60, 61, 62]
---

# PRP-11: Analytics adapters (round 2)

## Goal
Make the analytics adapters selectable and honest at runtime. Round 1 shipped the contracts, the fixture adapter and three vendor adapters tested against a SQLite stub, but nothing in the running API selects an adapter and the only real client (a Databricks Statement Execution executor) lives inside a gate script. Round 2 moves that executor into the product, adds an API runtime builder that builds the adapter named by settings and sets `app.state.analytics_adapter`, clears the review nits that accumulated as issues #60, #61 and #62, and adds a windowed quantile path so Synapse stops refusing quantiles (#59). It is for operators who pick an analytics backend at deployment and for PRP-64, which runs the live gate per adapter. It runs in W12 because it holds the API composition bodies (`runtime/compose.py`, `runtime/status.py`) for that wave.

Out of scope: live runs per adapter and the evidence under `docs/evidence/G01/analytics/` (PRP-64; the script stays refusing without `NS_LIVE_APPROVED=1`); real Fabric and Synapse executors (a TDS driver needs an ADR-0002 row and operator approval, so those two stay OPEN and selecting them reports a reason); hot aggregates and dashboards (shipped PRP-14); recommendation rules and the agent series source (PRP-15); Government Fabric host verification (needs a Learn fact or a live run, PRP-64); the `DeploymentProfile` Government region allowlist callers in copilot, workers and the UI (PRP-59, issue #212 other bullets).

## Why
- No composition path selects an adapter: `app.state.analytics_adapter` is read at `services/api/neurosphere_api/dashboards/dependencies.py:40` and set nowhere in `services/api`; `runtime/builders/` has no analytics module and `runtime/status.py` has no analytics component (lane A, PRP-11 section 1).
- The only real vendor client is `DatabricksStatementExecutor` inside `scripts/gates/g01_analytics_live.py` (class at line 393); `databricks/adapter.py:94` refuses to build without an injected executor, so the product cannot reach a warehouse.
- The live script imports its workload from the test package and a private function (`tests.integration.analytics.support`, `test_equivalence._cases`, script lines 515-520 and 718), issues setup SQL with no time budget and uses `CREATE SCHEMA IF NOT EXISTS` followed by `DROP SCHEMA ... CASCADE` (lines 730, 770). Issue #60.
- The suite's guards are weak: `tests/integration/analytics/test_profile_gating.py:179-196` never reaches its assert (`pragma: no cover`), the commercial-host test accepts any `InvalidSchemaError`, dedicated Synapse is not in the constructibility check, and `test_equivalence.py:200` accepts `None` or 0. Issue #61.
- Synapse refuses approximate quantiles in both modes (`synapse/dialect.py:65`, reason `synapse_no_approx_percentile`); `PERCENTILE_CONT` exists only as a window function that the one-aggregate-per-group renderer (`base/dialect.py:render_statement`) cannot express. Issue #59.
- `base/registry.py:_capability` turns a Government-region validation error into a generic `InvalidSchemaError`, hiding the capability reason (issue #212, analytics bullet).

## Acceptance criteria
- [ ] Given `NS_ANALYTICS_BACKEND` unset or `none`, When the API composes, Then the optional component `analytics_adapter` is `disabled`, `app.state.analytics_adapter` is absent and `/readyz` is unaffected (#212 registry bullet traced to item 3; selection gap from lane A).
- [ ] Given `NS_ENV=local` and `NS_ANALYTICS_BACKEND=fixture`, When the API composes, Then `app.state.analytics_adapter` is a `FixtureAnalytics` and `analytics_region` is set; Given any other environment with `fixture`, Then the component is `failed` with reason `analytics_fixture_not_local`.
- [ ] Given `NS_ANALYTICS_BACKEND=databricks` with a valid commercial host, warehouse id, catalog, schema and region, When the API composes with a mock transport, Then the adapter is a `DatabricksAnalytics` over the product executor and `analytics_health` runs a bounded one-row statement through it.
- [ ] Given `fabric` or `synapse`, When the API composes, Then the component is `failed` with reason `analytics_executor_unavailable` (no TDS driver is approved); no connection is attempted.
- [ ] Given a Government cloud with a Commercial Databricks host, or a backend the capability matrix disables for the region, Then the component is `failed` with the matrix reason code, never a cross-cloud fallback.
- [ ] The Databricks executor lives in `neurosphere_core.analytics.databricks.executor`, is covered by `httpx.MockTransport` tests (submit, poll, cancel on `CancelledError`, row budget breach, HTTP error carries only status or `error_code`), and `scripts/gates/g01_analytics_live.py` imports it instead of defining it (#60 item "move shared pieces").
- [ ] The live script wraps setup and teardown statements in `asyncio.timeout`, uses plain `CREATE SCHEMA` so a reused run id fails instead of dropping a pre-existing schema, and imports its request set from `neurosphere_core.analytics.fixture` (#60 bullets 1-3); the 256-parameter and INLINE-size limits stay recorded as unverified until the live run (#60 bullet 4); it still prints REFUSED and exits 2 without `NS_LIVE_APPROVED=1`.
- [ ] `tests/integration/analytics/` assertions are tightened per #61 points 1-5 (the Government registry loop reaches its assert or is removed, the host test matches the error field, dedicated Synapse is covered, narrowed scope asserts `row_count == 0`, the shim test asserts the expected shim set per adapter).
- [ ] Each #62 bullet is fixed with a test or recorded in the completion note as not reproducible or descoped, with the reason.
- [ ] Given a Synapse request with `approx_quantile`, When the adapter runs, Then it renders a windowed `PERCENTILE_CONT ... OVER (PARTITION BY ...)` statement and the equivalence suite compares it to the fixture within the documented tolerance; the dedicated and serverless refusal test is replaced by a pass test (#59).
- [ ] Given a Government region request that `DeploymentProfile` refuses, When `create_adapter` or `list_backends` is called, Then the raised error keeps the `capability_unavailable` reason (#212 analytics bullet).
- [ ] Live runs per adapter stay OPEN and are written OPEN in the completion note (handed to PRP-64).
- [ ] PRP exit: the touched suites pass, `verify-gates.ps1 -Mode full` is green and `python scripts/validate_planning.py` passes.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required | sonnet, review required (round 1 decision D6 stands; the builder selects a backend that serves telemetry) |
| 2 | What "wired" means | Dashboards read the adapter; adapter selected and health-reported | Dashboards, map and copilot read Cosmos hot aggregates and never need the adapter (`dashboards/analytics.py:3`). "Wired" here means selected from settings, set on `app.state` and health-reported through the existing `AnalyticsProbe`; no route starts reading analytics data in this PRP |
| 3 | Setting names | One file; `NS_ANALYTICS_*` env | `NS_ANALYTICS_BACKEND` (`none` default, `fixture`, `fabric`, `synapse`, `databricks`), `NS_ANALYTICS_REGION`, and for Databricks `NS_ANALYTICS_DATABRICKS_HOST`, `_WAREHOUSE_ID`, `_CATALOG`, `_SCHEMA`; cloud comes from `NS_CLOUD`. Credentials are never settings: the executor uses a managed-identity token (`DefaultAzureCredential`) |
| 4 | Fabric and Synapse real executors | Add a TDS driver now; stay OPEN | Stay OPEN (round 1 decision). Selecting them reports `analytics_executor_unavailable`; a driver needs an ADR-0002 row and operator approval and this PRP may not touch `pyproject.toml` or `uv.lock` |
| 5 | Synapse quantile tolerance | Exact only; reuse the approximate tolerance | ASSUMPTION: `PERCENTILE_CONT` is an exact continuous percentile, so it is compared with the existing documented quantile tolerance in `analytics/base/compare.py` (no new tolerance); the live check stays in PRP-64 |
| 6 | Databricks token audience in Government | Reuse the Commercial resource id; refuse | ASSUMPTION: the Entra resource id in the script (`2ff814a6-...`) is verified for Commercial only; for `NS_CLOUD=government` the builder reports `analytics_government_unverified` until a Learn fact or a live run confirms it |
| 7 | Where the shared workload lives | Test package; product module | A product module under `neurosphere_core/analytics/fixture/` so the script and the suite import one source (#60 bullet 2) |
| 8 | `integration` marker on the suite | Add it; keep it unmarked | Keep unmarked (round 1 deviation 3 stands: CI runs the default `uv run pytest -q`, which deselects `integration`); the gate command is `uv run pytest -q tests/integration/analytics` |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/analytics/base/registry.py` - `create_adapter`, `_capability`, `list_backends` (items 1, 3).
- `packages/core/neurosphere_core/analytics/databricks/adapter.py` and `config.py` - `create_adapter` needs an injected `SqlExecutor`; `DatabricksConfig` fields.
- `scripts/gates/g01_analytics_live.py:356-512` - `build_statement_body`, `DatabricksStatementExecutor`, `open_databricks_executor` (the code item 2 moves).
- `packages/core/neurosphere_core/analytics/base/enforcement.py` - `SqlExecutor`, `ExecutionLimits`, `BudgetBreach`.
- `packages/core/neurosphere_core/analytics/base/dialect.py:94-191` and `synapse/dialect.py` - `approx_quantile`, `render_statement` (item 4).
- `services/api/neurosphere_api/runtime/builders/gateway.py` - an optional-component builder with its own settings (pattern for item 3).
- `services/api/neurosphere_api/runtime/status.py:35-55` - `REQUIRED_COMPONENTS`, `OPTIONAL_COMPONENTS`.
- `services/api/neurosphere_api/dashboards/dependencies.py:35-45` and `dashboards/analytics.py` - the consumer of `app.state.analytics_*`.
- `tests/integration/analytics/{support,test_equivalence,test_profile_gating}.py` and `tests/unit/gates/test_g01_analytics_databricks.py` - what items 1 and 2 edit.
- `docs/evidence/G01/analytics/README.md` - the live run recipe (stays accurate; only the executor import path changes).

### Interfaces consumed
- `neurosphere_core.capabilities.validate.validate_profile` / `DeploymentProfile` (PRP-02, shipped): the matrix gate behind `create_adapter`.
- `BuildContext` and `BuilderSpec` (`runtime/builders/__init__.py`, PRP-29, shipped): `ctx.settings.cloud_profile`, `ctx.environ`, `ctx.attempt`, `ctx.disabled`, `ctx.on_shutdown`, `ctx.lifetime`.
- `neurosphere_core.errors` (`CapabilityUnavailableError`, `InvalidSchemaError`, `RateLimitedError`).
- `httpx` and `azure-identity` are already core dependencies (`packages/core/pyproject.toml`); no new dependency is added.

### Interfaces provided
- `neurosphere_core.analytics.databricks.executor.DatabricksStatementExecutor` and `open_databricks_executor(...)` (new); PRP-64 runs the live gate through the same class the API uses.
- Settings `NS_ANALYTICS_BACKEND`, `NS_ANALYTICS_REGION`, `NS_ANALYTICS_DATABRICKS_{HOST,WAREHOUSE_ID,CATALOG,SCHEMA}`; optional component name `analytics_adapter`; `app.state.analytics_adapter`, `analytics_region`, `analytics_health`.
- `neurosphere_core.analytics.fixture.equivalence_cases(cloud)` (new public name for the shared request set) used by the suite and the script.
- Windowed-quantile hook on the `Dialect` protocol (item 4), optional so existing dialects need no change.

### Patterns to match
- Optional builder with a settings class and reason codes: `runtime/builders/gateway.py:60-149`; test env clearing: `services/api/tests/runtime_gateway_builder/conftest.py:18-33`.
- `httpx.MockTransport` executor tests: `tests/unit/gates/test_g01_analytics_databricks.py:1-50`.
- Reason codes are `[a-z][a-z0-9_]{0,63}`, never values (`runtime/status.py` `is_reason_code`).
- Matrix-gated factory with lazy vendor modules: `base/registry.py:73-106`.

### Gotchas
- Adding a builder changes `default_builders()`; tests pin the order and the component set (`services/api/tests/runtime_api/test_readiness.py:178-215`, `runtime_gateway_builder/test_gateway_builder.py:103`, `runtime_data/data_helpers.py:79`). Grep for `default_builders` and `OPTIONAL_COMPONENTS` and update those expectations; this is the only reason a file outside the owned test directories is touched.
- `analytics_adapter` must be OPTIONAL: a deployment with no backend is valid and must stay ready.
- `base/dialect.py` is edited twice (items 1 and 4): sequence them, never parallel.
- The real executor must not log SQL text, parameter values or tokens; errors carry the HTTP status or `error_code` only (the script's rule, keep it).
- `PERCENTILE_CONT ... OVER` returns one row per input row, so the Synapse renderer must `SELECT DISTINCT` the group keys; the row-limit check (`limit + 1`) must still hold.
- A new runtime builder module must be CodeQL-clean: no PEP 695 generics in nested functions, no host substring checks without a leading dot.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/analytics/**
  - packages/core/tests/analytics/**
  - tests/integration/analytics/**
  - tests/unit/gates/test_g01_analytics_*.py
  - scripts/gates/g01_analytics_live.py
  - docs/evidence/G01/analytics/**
  - services/api/neurosphere_api/runtime/builders/analytics.py
  - services/api/tests/analytics_runtime/**
tier1:
  - services/api/neurosphere_api/runtime/compose.py
  - services/api/neurosphere_api/runtime/status.py
tier2_appends:
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/settings.py
must_not_touch:
  - pyproject.toml
  - uv.lock
  - infra/**
  - packages/contracts/**
  - docs/RESEARCH-AND-GATES.md
  - docs/adr/0002-stack-pins.md
```

## Implementation blueprint

Order: 1 then 2 then 3 (they share `databricks/`, then the builder consumes the executor); 4 after 1 (both edit `base/dialect.py`); 5 last. No item is `[P]`.

### Item 1 - Hygiene: suite, adapters, registry reason, shared workload
- Deliverable: #61 assertions tightened; #62 nits fixed or recorded; the registry keeps the `capability_unavailable` reason for refused regions (#212 analytics bullet) and passes a caller-supplied executor to the fixture factory only when it is a `SqlExecutor` (otherwise documents why not); the equivalence request set and dataset builders move into `neurosphere_core/analytics/fixture/` (`equivalence_cases`), with the suite importing them from there.
- Owned files: `packages/core/neurosphere_core/analytics/base/{registry,stub}.py`, `analytics/fabric/{config,migrations}.py`, `analytics/synapse/config.py`, `analytics/databricks/{migrations,dialect}.py`, `analytics/fixture/**`, `packages/core/tests/analytics/**`, `tests/integration/analytics/**`.
- Must NOT touch: `analytics/base/dialect.py` (item 4), `scripts/gates/**` (item 2), `services/**`.
- Depends on: none.
- Acceptance criteria: each #61 point has a test that fails on the old assertion; Fabric `apply_migrations` serialises concurrent runners (two concurrent runs insert one ledger row); a dedicated Synapse workspace named `*-ondemand` with a derived host is rejected; Databricks `_IDENT` uses `fullmatch`; the stub counter no longer depends on ANSI quoting or the recorded limitation is kept in `G12_PARITY_GAPS`; `list_backends(cloud="government", region="usdodcentral")` raises with reason `capability_unavailable`.
- Tests: `packages/core/tests/analytics/test_base_registry.py` (extend), `test_fabric_adapter.py`, `test_synapse_adapter.py`, `test_databricks_adapter.py`, `tests/integration/analytics/test_profile_gating.py`, `test_equivalence.py`.
- Pattern references: `tests/integration/analytics/support.py:90-140` (`build_adapter`), `base/registry.py:73-106`.

### Item 2 - Product Databricks executor and hardened live script
- Deliverable: `databricks/executor.py` holding `build_statement_body`, `DatabricksStatementExecutor` and `open_databricks_executor` moved from the script; `databricks/__init__.py` exports them; the script imports them, wraps setup and teardown `run_sql` in `asyncio.timeout` (cancelling the server statement), uses plain `CREATE SCHEMA`, and imports the workload from `fixture.equivalence_cases`.
- Owned files: `packages/core/neurosphere_core/analytics/databricks/{executor,__init__}.py` (new `executor.py`), `scripts/gates/g01_analytics_live.py`, `tests/unit/gates/test_g01_analytics_*.py`, `packages/core/tests/analytics/test_databricks_executor.py` (new).
- Must NOT touch: `pyproject.toml`, `uv.lock`, the script's refusal-first behaviour (`NS_LIVE_APPROVED` check stays before any import), `docs/RESEARCH-AND-GATES.md`.
- Depends on: item 1.
- Acceptance criteria: `uv run pytest -q tests/unit/gates/test_g01_analytics_refuses.py` still shows REFUSED with exit 2 and no import of project code before the check; executor tests pass on `httpx.MockTransport` with no network; a statement cancelled by the time budget posts the cancel endpoint; the module exports no token or query text in any error.
- Tests: `packages/core/tests/analytics/test_databricks_executor.py`, `tests/unit/gates/test_g01_analytics_databricks.py` (re-pointed imports), `test_g01_analytics_evidence.py`.
- Pattern references: `scripts/gates/g01_analytics_live.py:393-481`, `tests/unit/gates/test_g01_analytics_databricks.py:34-60`.

### Item 3 - API runtime builder: select and report the adapter
- Deliverable: `runtime/builders/analytics.py` with an `AnalyticsSettings` (`NS_ANALYTICS_*`), a `build(ctx)` that disables the optional component when the backend is `none`, builds the fixture adapter only under `NS_ENV=local`, builds `DatabricksAnalytics` over the product executor (token from `DefaultAzureCredential` bound to the cloud's login host, client closed with `ctx.on_shutdown`), reports `analytics_executor_unavailable` for Fabric and Synapse and `analytics_government_unverified` for Databricks under Government, sets `app.state.analytics_adapter`, `analytics_region` and an `analytics_health` callable (bounded one-row statement, no network at build time); `analytics_adapter` added to `OPTIONAL_COMPONENTS`; the builder registered last in `default_builders()`.
- Owned files: `services/api/neurosphere_api/runtime/builders/analytics.py` (new), `runtime/status.py` (append the component name), `runtime/builders/__init__.py` (append to `default_builders`), `runtime/settings.py` only if the settings class lives there (prefer the builder module), `services/api/tests/analytics_runtime/**` (new directory, no `__init__.py`, conftest clearing `NS_ANALYTICS_`), and the pinned expectations in `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py` and `runtime_data/data_helpers.py` (one-line updates).
- Must NOT touch: `dashboards/**`, `data.py`, `planes.py`, `routers.py`, other builders' bodies.
- Depends on: item 2.
- Acceptance criteria: the six builder criteria above, each a test; `/readyz` stays ready with the backend unset; a misconfigured backend makes only `analytics_adapter` failed with a reason code and no value in the status; the dashboards analytics badge reports `ok` for a healthy fake and `delayed` when the health call raises.
- Tests: `services/api/tests/analytics_runtime/test_analytics_builder.py`, `test_analytics_health.py`, plus the updated pinned tests; run with `services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/health`.
- Pattern references: `runtime/builders/gateway.py:60-149`, `dashboards/dependencies.py:35-45`.

### Item 4 - Synapse windowed quantile (#59)
- Deliverable: an optional `windowed_quantile(column_sql, q, group_sql)` hook on the `Dialect` protocol, a renderer branch in `render_statement` that emits `SELECT DISTINCT <keys>, PERCENTILE_CONT(q) WITHIN GROUP (ORDER BY col) OVER (PARTITION BY <keys>), ...` for dialects that provide it, the Synapse dialects (serverless and dedicated) providing it instead of raising, the SQLite stub shim for `PERCENTILE_CONT ... OVER`, and the equivalence suite and gating tests updated.
- Owned files: `packages/core/neurosphere_core/analytics/base/dialect.py`, `analytics/synapse/{dialect,adapter,stub_shims}.py`, `packages/core/tests/analytics/test_synapse_adapter.py`, `tests/integration/analytics/test_equivalence.py`.
- Must NOT touch: `analytics/fabric/**`, `analytics/databricks/**`, anything outside the owned list.
- Depends on: item 1.
- Acceptance criteria: a quantile request over a grouped, time-bucketed dimension returns the same rows as the fixture within tolerance on both Synapse modes; a request that also asks for a row limit still raises `rate_limited` on `limit + 1` rows; `G12_PARITY_GAPS` lists that the stub emulates the window function and that real `PERCENTILE_CONT` semantics are unproven until the live run.
- Tests: `packages/core/tests/analytics/test_synapse_adapter.py`, `tests/integration/analytics/test_equivalence.py`.
- Pattern references: `base/dialect.py:120-191`, `synapse/dialect.py:40-91`.

### Item 5 - Integration and close-out
- Deliverable: `docs/evidence/G01/analytics/README.md` updated (executor import path, new settings, what stays OPEN); Tier-2 appends confirmed; Tier-3 regeneration (`openapi.json` is not expected to change, run the drift test to confirm); completion note per reference section 6 with an "Env vars for the operator" list (`NS_ANALYTICS_*`) because `.env.example` cannot be edited by an agent; issues #60, #61, #62 closed only if every bullet is fixed or justified, #59 closed, #212 left open (other bullets belong to PRP-59).
- Owned files: `docs/evidence/G01/analytics/README.md`, this PRP's Execution state and completion note, regenerated `PRPs/PRP-MASTER-neurosphere.md` status table and `PRPs/INDEX.md`.
- Must NOT touch: `docs/RESEARCH-AND-GATES.md` (PRP-64 owns the G01 row), `.env.example`.
- Depends on: items 1-4.
- Acceptance criteria: gates below pass; live runs written OPEN per adapter.
- Tests: none new.
- Pattern references: `PRPs/reference/parallel-build-reference.md` section 6.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/analytics tests/integration/analytics tests/unit/gates services/api/tests/analytics_runtime services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/health services/api/tests/test_openapi_drift.py
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```
Live (operator only, NOT run by this PRP): `NS_LIVE_APPROVED=1 MSYS_NO_PATHCONV=1 uv run python scripts/gates/g01_analytics_live.py --adapter databricks --operator "<name>" ...` per `docs/evidence/G01/analytics/README.md`.

## Migration and rollback
No data or schema migration: the builder only reads settings and the adapter reads no store at build time. The feature is off by default (`NS_ANALYTICS_BACKEND` unset gives a `disabled` optional component), so rollback is unsetting the variable; reverting the branch removes the module and the one-line registrations. New settings are optional with safe defaults.

## Live and open gates
- G01 per adapter (Fabric, Synapse, Databricks, Commercial) and G12 stub-vs-live deltas: OPEN, need `NS_LIVE_APPROVED=1` and an operator-approved subscription; handed to PRP-64. Fabric and Synapse cannot run at all until a TDS driver has an ADR-0002 row and operator approval.
- Government analytics (Fabric, Synapse, Databricks) and the inferred Government Fabric SQL suffix `.fabric.microsoft.us`: OPEN (no Government subscription; availability is not authorization).
- The Databricks Statement Execution limits (256 parameters, INLINE size) and `PERCENTILE_CONT` semantics on real Synapse: unverified until the live run.

## NOT building
- A TDS driver or real Fabric and Synapse executors (ADR-0002 row and operator approval first).
- Any route that reads analytics data, or a change to dashboards, map or copilot to use the adapter.
- Hosted wiring of `NS_ANALYTICS_*` in Helm, Bicep or compose (PRP-58) and `.env.example` edits (operator).
- Live evidence files, `docs/RESEARCH-AND-GATES.md` rows (PRP-64).
- Cross-cloud routing of any kind.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 5 and 6 are labelled assumptions)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-11-round2-analytics-runtime | registry reason, fixture workload, #61 assertions, #62 nits (see PR) |
| 2 | merged | prp-11-round2-analytics-runtime | executor moved, script hardened |
| 3 | merged | prp-11-round2-analytics-runtime | builder + pinned test updates |
| 4 | merged | prp-11-round2-analytics-runtime | windowed quantile; stub interpolation differs from nearest-rank on small groups |
| 5 | in-progress | prp-11-round2-analytics-runtime | README done; Tier-3 regen and completion note at merge step |

## Completion note (filled at ship)
- Date, PR, merged commits:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (G01 per adapter, G12 deltas, Government):
- Env vars for the operator (`NS_ANALYTICS_*`):
- Follow-up issue numbers:
- Product check (can an operator select a backend without editing files?):

## History
- Round 1 shipped as PR #63 (merged 2026-10-18): contracts, fixture adapter, Fabric, Synapse and Databricks adapters over a SQLite stub, the equivalence and gating suite and the live-gate script. Live runs did not run; all three adapters stayed OPEN.
- The 2026-11-04 audit reopened it: no real vendor client, nothing selecting an adapter in the running app, weak suite assertions, evidence directory holding only a README.
- The 2026-11-14 lane A audit confirmed the gaps and found the wiring and executor claims still true, plus four stale commands (`python -m pytest -m integration tests/integration/analytics` collects nothing because the suite is not `integration`-marked; the correct form is `uv run pytest -q tests/integration/analytics`).
- This rewrite drops the round 1 blueprint, execution table and audit section, scopes round 2 to hygiene, the product executor, the runtime builder and the Synapse quantile, and hands every live run to PRP-64.
- The original text is in git history (`git log --follow PRPs/backlog/PRP-11-analytics-adapters.md`).
