---
name: PRP-134-chargeback-showback-and-success-metrics
status: backlog
priority: P2
order: 134
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-06, NS-08
depends_on: [PRP-75-find-an-agent-ui-and-recommendation-metrics, PRP-76-catalog-registration-completeness, PRP-78-copilot-graph-timeline-and-recommender-tools, PRP-115-budget-evaluation-alerts-and-enforcement, PRP-100-telemetry-tool-service-identity-and-aggregates, PRP-137-telemetry-agent-identity-resolution]
wave: W32
branch: prp-134-chargeback-success-metrics
allow_parallel: true
issues: [260]
---

# PRP-134: Chargeback, showback and product success metrics

## Goal
Show who the AI spend belongs to, and measure whether the product is being used as the original PRD promised. Part one groups the cost ledger by cost center into a showback view (what each cost center consumed, estimated and invoiced kept apart) and a chargeback view (invoiced amounts of closed periods only), always with an unallocated bucket and an allocation-coverage figure, plus a CSV and JSON export. Part two instruments four of the original PRD's success metrics from real events: recommendation acceptance rate, copilot weekly active users, copilot answer time and agent metadata completeness, each shown as a measurement with its numerator, denominator, window and source, never as a pass or fail, and with people kept pseudonymous (no per-person usage anywhere). It is for the finance partner and platform owner who ask "who spent this" and "is anyone using it", and it closes GitHub issue 260. It runs in W32 on the cost-center attribution PRP-46 shipped, the budget package PRP-115 created, and the aggregates PRP-100 and PRP-137 make complete.

Out of scope: storing or evaluating budgets (shipped PRP-44, PRP-115); the acceptance-rate mechanics and the "Find an agent" strip (PRP-72, PRP-75 own them; this PRP reads their numbers); the completeness computation (PRP-76); invoicing, general-ledger posting or any payment system; a cost-center master list (cost centers are values seen on ledger entries); per-person or per-team usage reports; a manual-search baseline study (see clarification 7); recreating `packages/core/neurosphere_core/finops/__init__.py` (PRP-115 creates it; this PRP adds only the `chargeback` subpackage).

## Why
- `cost_center` is stored but not exposed. It is a field on `Observation` (`packages/core/neurosphere_core/ledger/models.py:145`) and on `LedgerEntry` (`:212`, "Agreed cost center of the observations; None when none carries one or two disagree", folded at `ledger/fold.py:142-146`) and a filter in `LedgerFilters` (`ledger/totals.py:44-60`), but no route returns it: the finops API has only the forecast (`services/api/neurosphere_api/finops/router.py:56-75`), and `CostPoint` has no cost-center dimension (`packages/core/neurosphere_core/aggregates/models.py:226-235`). Issue 260 ("Dashboards and FinOps grouped by cost center", verified with `gh issue view 260`) says PRP-46 carried the attribution through ingest, the ledger and the filter only and left the views for later.
- The ledger entry has no agent id (`ledger/models.py:180-225`), and the aggregates cost series has no cost center, so cost by cost center and cost by agent live in different stores. The per-agent series only exists for OTLP agents once PRP-137 resolves their ids; without it an agent view would silently omit them.
- The original PRD set measurable targets (`git show 9fbf5f4c:docs/PRD.md` section 3): "Recommendation acceptance rate (operator picks suggested agent/tool) > 60%", "Weekly active copilot users / total platform users > 40%", "% of registered agents with complete metadata (owner, version, capability tags) > 95%" and "Time-to-answer: Median time for an operator to answer 'which agent/service does X' via copilot vs. manual search, 80% reduction". The v1.2 PRD did not carry the table over (gap analysis section 3: all four "NOT BUILT"; section 8 item 9 says to instrument and display them rather than claim them).
- Copilot usage cannot be derived from the conversation store: conversations are partitioned and read by owner only (`services/api/neurosphere_api/copilot/store.py:1-8,151-170`, every port method takes the `owner`) and expire by retention class, so a count across users needs its own privacy-safe record. PRP-78 lists weekly active users as a follow-up (`PRPs/backlog/PRP-78-*.md`, out-of-scope paragraph).
- People are pseudonymous by default (`docs/PRD.md:26`, "pseudonymize people by default"); a usage metric must not become a per-person activity log.

## Acceptance criteria
- [ ] Given ledger entries with cost centers `cc-100`, `cc-200` and some with none, When `GET /api/v1/finops/chargeback/domains/{domain}/cost-centers?from=&to=&currency=USD&mode=showback` runs, Then it returns one row per cost center and an `unallocated` row, each with estimated and invoiced totals kept separate, `entry_count`, `known_count`, `unresolved_count`, `unknown_count` (the `CurrencyTotal` shape), and a top-level `allocation_coverage` (share of known amount in named cost centers) that is `null`, not 0, when nothing is known.
- [ ] Given `mode=chargeback`, Then only entries whose authoritative kind is `invoiced` and whose billing period has ended are counted; estimated entries appear in a separate `pending_invoice` figure; the response states the rule in `basis`.
- [ ] Entries whose observations disagree on cost center land in `unallocated` with a count shown as `conflicting_or_missing`; a total is never presented as complete while unknown amounts exist (coverage and `complete` come from `compute_totals`).
- [ ] The export (`.../cost-centers/export?format=csv|json`, `data.export`) carries the same rows, the window, the basis, the currency, `generated_at` and a SHA-256 of the body; a CSV cell that could be read as a formula is neutralised; every export writes an audit record with ids and the hash, not the amounts.
- [ ] Scope: results include only entries of domains in the caller's scope; the customer comes from the derived scope, never a parameter; a domain the caller cannot read gives 404 shape identical to an unknown domain; a window over 366 days or a scan over the entry cap returns `truncated: true` with the cap, never a silent partial total.
- [ ] Given aggregates for agents in the domain, Then an `agents` table lists cost per agent for the window from the aggregates (not by cost center) and says so; an OTLP agent resolved by PRP-137 appears in it; an agent without any series is absent, not zero.
- [ ] Acceptance rate: `GET /api/v1/metrics/product/domains/{domain}` returns a block with `numerator` (accepts), `denominator` (accepts plus rejects), `value` (null when the denominator is 0), the window, and the source `recommendations.match_metrics`; it reads PRP-72's metrics and does not recompute them differently.
- [ ] Metadata completeness: the same response carries a block from PRP-76's completeness service with its own basis text (agents counted, fields counted); a field PRP-76 reports `unavailable` stays `unavailable`.
- [ ] Copilot weekly active users: `GET /api/v1/metrics/product/customer` (customer-level `config.manage`) returns distinct active users in the last full week or rolling 7 days, the denominator (principals holding any role in the customer's policy store, counted at read time), the ratio, and a `status`: `measured`, `insufficient_data` (fewer than `NS_METRICS_MIN_GROUP` users, default 3, in which case the count and ratio are withheld) or `unavailable` with a reason code (copilot disabled, store unreachable). The denominator's definition is printed with the number.
- [ ] Copilot answer time: the same response carries median and p95 request-to-terminal-event time per week with the sample count and outcome mix (`done`, `abstain`, `denied`, `error`), labelled "copilot answer time", and the response states that the PRD's "80% reduction versus manual search" is a comparison that is not measured here because no manual-search baseline exists (`status: not_measurable`, reason `no_baseline`).
- [ ] Privacy: no response, document, log line, audit record or export contains a principal id, a name, a conversation id or question text; the usage store holds only a week-bound digest per active user and an outcome with a latency per turn; the digest includes the week so one person cannot be followed across weeks; documents expire after 120 days; no route can list or rank users; groups smaller than `NS_METRICS_MIN_GROUP` are suppressed.
- [ ] Every block shows its `target` (the original PRD GA figure, labelled "target", not a result) and carries no pass or fail flag, colour rule or word like "healthy"; synthetic sandbox data is labelled `data_origin: synthetic` when the deployment runs the demo profile.
- [ ] Callers without the required permission (viewers on the customer route, auditors, other-domain readers, expired users) get 403 and a denial record on every new route; every route is in the inventories and boots under `verify_route_permissions`.
- [ ] The finops pages show a Chargeback tab with the mode switch, the coverage figure beside every total, the unallocated row first when it exceeds 10 percent of known amount, an export button and the by-agent table; the Product metrics page shows the four blocks with numerator, denominator, window and "how this is measured"; both pass axe in light, dark and high contrast.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` and the frontend tests pass; PR open with CI green; `services/api/openapi.json` regenerated; issue 260 can be closed.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Where grouping happens | New aggregate series by cost center; group ledger entries on read | On read from `LedgerStore.list_entries` with the existing `compute_totals`, bounded by an entry cap (`NS_CHARGEBACK_MAX_ENTRIES`, default 50 000) with `truncated`. The aggregates (PRP-49, PRP-100) are not extended in this PRP |
| 2 | Showback versus chargeback | Same data; different rule | Decided by the owner 2026-11-16 (GD-40): showback = authoritative amount of any kind, each total labelled estimated or invoiced; chargeback = invoiced and period ended only. The finance owner may want a different close rule |
| 3 | Cost centers list | Master data; seen values | Seen values on ledger entries. A cost center with no spend in the window is not listed |
| 4 | Cost by agent within a cost center | Cross-tab; two views | Decided by the owner 2026-11-16 (GD-41): two views, no cross-tab. Neither store has both keys (ledger lacks the agent, aggregates lack the cost center). A cross-tab needs a contract and ingest change and is a follow-up for the owner |
| 5 | Usage record shape | Per-turn log with user id; week-bound digest | Digest only: `sha256(customer|ISO week|principal id)` per active user per week, and one anonymous record per turn (random id, week, outcome, latency). ASSUMPTION: the principal id is the pseudonymous id the policy store already uses |
| 6 | Weekly active definition | Any API call; a copilot turn | A copilot turn started (any terminal outcome). The platform-users denominator is the count of principals with a role in the policy store (`PolicyAdminRepository.list_principals`, `auth/scope/policy_admin.py:308`); service principals are excluded when the policy document distinguishes them, else the label says "principals with a role" |
| 7 | "Time-to-answer" versus the PRD | Report latency as the metric; mark the comparison unmeasurable | Report answer time as what it is (latency of the copilot) and mark the PRD metric `not_measurable` (no baseline of manual search time exists). Cut line: this block |
| 8 | Who sees which metric | One permission; split by level | Chargeback: `data.read` per domain, export `data.export`. Product metrics: acceptance and completeness `data.read` per domain; copilot usage customer-level `config.manage` because usage is not bound to a domain |
| 9 | Where the copilot hook goes | Wrap in the engine; router hook | A `UsageSink` read from `app.state` in `copilot/router.py` at turn start and terminal event, default no-op. `[serial-after: PRP-78]`; re-check overlap with PRP-80 and PRP-116 at rebase |
| 10 | Retention of usage records | Keep; expire | 120 days (per-document TTL), the same mechanism the conversation store uses |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/ledger/models.py:114-225` and `ledger/fold.py:130-210` - entry fields, `cost_center`, allocation parts, how disagreement becomes `None`.
- `packages/core/neurosphere_core/ledger/totals.py:44-135` - `LedgerFilters`, `CurrencyTotal`, `compute_totals`, `LedgerReader`.
- `packages/core/neurosphere_core/ledger/store.py:25-45` - `list_entries(customer, window)`.
- `services/api/neurosphere_api/finops/router.py` and `finops/service.py:262-330` - route shape, scope use, `build_forecast` (imitate, do not edit).
- `packages/core/neurosphere_core/aggregates/{store,subject,models}.py` - `AggregateReader.query`, agent series keys, `CostPoint`.
- `services/api/neurosphere_api/copilot/{router,store,cosmos_store}.py` - turn lifecycle, terminal events, owner-scoped storage and TTL.
- `packages/core/neurosphere_core/auth/scope/policy_admin.py:300-400` - `list_principals`.
- `PRPs/backlog/PRP-72-agent-and-tool-recommender-backend.md`, `PRP-75-*`, `PRP-76-*` "Interfaces provided" - the metrics and completeness services.
- `PRPs/backlog/PRP-115-budget-evaluation-alerts-and-enforcement.md` - what it puts under `finops/`.
- `frontend/src/features/finops/{ForecastPage,routes,paths}.ts*` - page and nav pattern.
- `services/api/neurosphere_api/actions/customer_control.py:91` - `require_customer_control`.

### Interfaces consumed
- Shipped: `LedgerStore.list_entries`, `compute_totals`, `LedgerFilters`, `AggregateReader.query`, `require(Permission.DATA_READ, domain_from_path("domain"))`, `require_customer_control(Permission.CONFIG_MANAGE)`, `run_audited_mutation`, `audited_read`, per-document TTL pattern (`copilot/cosmos_store.py`).
- PRP-46 (shipped): cost center on ingest, ledger and `LedgerFilters`.
- PRP-72: `AgentMatcher.metrics(scope, domain, window)` over `app.state.agent_matcher` (read PRP-72's final name first; if absent the block is `unavailable`, reason `matcher_disabled`). PRP-75: no API; the UI strip stays its own.
- PRP-76: the completeness service behind `GET /api/v1/catalog/completeness`; read its function from the PRP, not by calling HTTP.
- PRP-78: the copilot router and its terminal events. PRP-115: `neurosphere_core.finops` package root exists; no import beyond the package path.
- PRP-100 and PRP-137: agent subject series keyed by canonical agent id, including OTLP agents.

### Interfaces provided
- Core `neurosphere_core.finops.chargeback` (new subpackage; does not edit `finops/__init__.py`): `CostCenterRow`, `CostCenterReport`, `build_cost_center_report(entries, mode, currency, window)`, `render_csv`, `neutralise_cell`, `UNALLOCATED`.
- Core `neurosphere_core.product_metrics` (new): `UsageStore` protocol with `InMemoryUsageStore` and `CosmosUsageStore`, `week_digest(customer, week, principal)`, `UsageSink` protocol and `StoreUsageSink`, `MeasurementBlock` model, `min_group()`.
- Container `product_usage` (partition `/customer_id`, per-document TTL).
- Routes: `/api/v1/finops/chargeback/domains/{domain}/cost-centers` (`GET`), `.../cost-centers/export` (`GET`), `/api/v1/metrics/product/domains/{domain}` (`GET`), `/api/v1/metrics/product/customer` (`GET`).
- Settings `NS_CHARGEBACK_MAX_ENTRIES` (50 000), `NS_METRICS_MIN_GROUP` (3), `NS_METRICS_USAGE_ENABLED` (default true), `NS_METRICS_USAGE_TTL_DAYS` (120). Component `product_metrics` (optional) in `runtime/status.py`; audit operations `finops.chargeback_export`, `metrics.product_read`.
- Frontend: `frontend/src/features/finops/chargeback/` and `frontend/src/features/metrics/` with mock handlers.

### Patterns to match
- Pure windowed ledger computation: `ledger/totals.py:78-115`.
- Domain-scoped finops read with derived scope: `finops/router.py:40-75`.
- Per-document TTL storage keyed by a partition value: `copilot/cosmos_store.py:3-9,73-120`.
- Min-principals suppression idea: `NS_MATCH_MIN_PRINCIPALS` in PRP-72.
- Audited read of a sensitive aggregate: `authz/read_audit.py:176-195`.

### Gotchas
- `LedgerEntry.cost_center` is `None` for both "none carried" and "observations disagree" (`fold.py:142-146`); the report cannot tell them apart and says so.
- Amounts are `Decimal` strings; never convert to float anywhere (CSV and JSON as strings).
- `list_entries` returns every entry in the window for a customer; filter by domain and cost center in memory, count what was scanned, and stop at the cap with `truncated`.
- `docs/PRD.md` has no success-metrics table; cite the original with `git show 9fbf5f4c:docs/PRD.md` and print the figure as a "target (original PRD)" only.
- The copilot router is sensitive: the hook must be exception-safe (a failing sink never fails or delays a turn) and must not read the question or answer.
- The week digest uses ISO week and year (`datetime.isocalendar`); test across a year boundary.
- Denominators drift (principals added mid-week); the response prints "as at read time".
- Unique test directories: `packages/core/tests/finops_chargeback`, `packages/core/tests/product_metrics`, `services/api/tests/finops_chargeback_api`, `services/api/tests/product_metrics_api`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/finops/chargeback/**
  - packages/core/neurosphere_core/product_metrics/**
  - packages/core/tests/finops_chargeback/**
  - packages/core/tests/product_metrics/**
  - services/api/neurosphere_api/finops/chargeback/**
  - services/api/neurosphere_api/metrics/product/**
  - services/api/neurosphere_api/runtime/builders/product_metrics.py
  - services/api/neurosphere_api/copilot/router.py
  - services/api/tests/finops_chargeback_api/**
  - services/api/tests/product_metrics_api/**
  - tests/security/authz/test_chargeback_and_metrics.py
  - tests/security/privacy/test_product_usage_privacy.py
  - frontend/src/features/finops/chargeback/**
  - frontend/src/features/finops/routes.tsx
  - frontend/src/features/metrics/**
  - frontend/tests/mock-api/features/chargeback.ts
  - frontend/tests/mock-api/features/product-metrics.ts
  - frontend/tests/e2e/chargeback/**
  - docs/runbooks/chargeback-and-product-metrics.md
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - services/api/tests/runtime_api/test_readiness.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/finops/__init__.py
  - packages/core/neurosphere_core/finops/budget_eval/**
  - packages/core/neurosphere_core/ledger/**
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/neurosphere_core/recommendations/**
  - services/api/neurosphere_api/finops/router.py
  - services/api/neurosphere_api/finops/service.py
  - services/api/neurosphere_api/finops/budgets/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/recommendations/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/runtime/builders/copilot.py
```
`services/api/neurosphere_api/copilot/router.py` is edited only by item 4, which is `[serial-after: PRP-78]` (PRP-78 added the progress event there; PRP-80 and PRP-116 may also have touched `copilot/**` by W32, so rebase first and keep the edit to the hook).

## Implementation blueprint

Parallelization: items 1 and 3 [P] share no file; item 2 needs 1; item 4 needs 3; item 5 needs 1, 3 and 4; item 6 needs 2 and 5; item 7 last before close-out.

### Item 1 - Cost-center report core  [P]
- Deliverable: `finops/chargeback/` with `report.py` (`build_cost_center_report`: filter entries by domain set and window, group by `cost_center` or `UNALLOCATED`, per currency totals through `compute_totals`, estimated and invoiced separated by `authoritative_kind`, allocation coverage, `pending_invoice`, caps and `truncated`), `modes.py` (showback and chargeback rules, period-closed test against `period_end` and an injected today), `export.py` (`render_csv`, `neutralise_cell`, body digest).
- Owned files: `packages/core/neurosphere_core/finops/chargeback/**`, `packages/core/tests/finops_chargeback/**`.
- Must NOT touch: `finops/__init__.py`, `ledger/**`.
- Depends on: PRP-115 merged (package root exists).
- Acceptance criteria: the grouping, chargeback, conflicting, coverage-null, cap and formula-neutralising criteria.
- Tests: `packages/core/tests/finops_chargeback/test_report.py`, `test_modes.py`, `test_export.py` with Hypothesis-style sum checks (sum of rows equals the unfiltered total per currency).
- Pattern references: `ledger/totals.py:78-135`.

### Item 2 - Chargeback API
- Deliverable: `finops/chargeback/{router,models,service,dependencies}.py` with the two routes, window and currency parameters, `agents` table read from `AggregateReader` (agent series in the domain for the window, cost points only), export with audit; registered through `routers.py` under its own prefix `/api/v1/finops/chargeback` (not in `finops/router.py`).
- Owned files: `services/api/neurosphere_api/finops/chargeback/**`, `services/api/tests/finops_chargeback_api/**`.
- Must NOT touch: `finops/router.py`, `finops/service.py`, `aggregates/**`.
- Depends on: item 1; PRP-100 and PRP-137 merged for the agents table.
- Acceptance criteria: scope, export, truncation and by-agent criteria; unknown domain equals unreadable domain; the customer is never a request value.
- Tests: `services/api/tests/finops_chargeback_api/test_routes.py`, `test_export_audit.py`, `test_agents_table.py`.
- Pattern references: `finops/router.py:40-75`, `finops/service.py:262-330`.

### Item 3 - Usage store and sink  [serial-after: PRP-131]
- Deliverable: `product_metrics/` with `digest.py` (`week_digest`, ISO week helper), `store.py` (`UsageStore`, in-memory twin, `distinct_users(customer, week)`, `turn_stats(customer, weeks)`), `cosmos_store.py` (TTL documents of kind `active_user` and `turn`), `sink.py` (`UsageSink`, `StoreUsageSink`, `NoopUsageSink`, exception-safe `record_turn_started`, `record_turn_finished`), `blocks.py` (`MeasurementBlock`, suppression); the container `product_usage` is declared by PRP-131 (the W32 stores owner, its item 1), not here.
- Owned files: `packages/core/neurosphere_core/product_metrics/**`, `packages/core/tests/product_metrics/**`. The stores Tier-1 files (`containers.py`, `cosmos-containers.json`, `cosmos-data.bicep`) belong to PRP-131 in W32; this item is `[serial-after: PRP-131]` because its Cosmos store test needs the declared container.
- Must NOT touch: `copilot/**`, `auth/**`.
- Depends on: none beyond shipped code.
- Acceptance criteria: the privacy criterion at the store level (no principal id in any stored document; digest changes across weeks; TTL set; one document per user per week even after many turns); a failing store never raises out of the sink; suppression below the group size; the container exists in compose and Bicep.
- Tests: `packages/core/tests/product_metrics/test_digest.py`, `test_store.py`, `test_sink_failure.py`, `test_suppression.py`, and the container-declaration comparison test.
- Pattern references: `copilot/cosmos_store.py:73-120`, `stores/containers.py:138-150`.

### Item 4 - Copilot usage hook  [serial-after: PRP-78]
- Deliverable: in `copilot/router.py`, read `app.state.copilot_usage_sink` (default none) and call `record_turn_started(principal)` when a turn is accepted and `record_turn_finished(outcome, latency_ms)` when the terminal event is emitted; no question, answer or conversation id passes to the sink; failures are logged as a reason code and swallowed.
- Owned files: `services/api/neurosphere_api/copilot/router.py` (hook lines only), `services/api/tests/product_metrics_api/test_copilot_hook.py`.
- Must NOT touch: `copilot/engine.py`, `copilot/service.py`, `copilot/store.py`.
- Depends on: item 3; PRP-78 merged.
- Acceptance criteria: with the sink absent behaviour is byte-identical (existing `services/api/tests/copilot_api` passes unchanged); each terminal event kind maps to one outcome; a sink exception does not change the HTTP result or add measurable delay (test with a slow failing sink and a timer bound).
- Tests: `services/api/tests/product_metrics_api/test_copilot_hook.py` and `services/api/tests/copilot_api`.
- Pattern references: the existing SSE emission in `copilot/router.py`.

### Item 5 - Product metrics API and composition
- Deliverable: `metrics/product/{router,service,models}.py` with the two routes; builder `runtime/builders/product_metrics.py` (`BUILDER`, optional component `product_metrics`, backend `cosmos|memory` with memory only under `NS_ENV=local`) binding `app.state.copilot_usage_sink` and the read service from the usage store, the matcher metrics, the completeness service and the policy store's principal counter; blocks for acceptance, completeness, weekly active users and answer time with the statuses of the criteria; `data_origin` from the profile.
- Owned files: `services/api/neurosphere_api/metrics/product/**`, `runtime/builders/product_metrics.py`, `services/api/tests/product_metrics_api/{test_routes,test_blocks,test_builder}.py`, the pinned-order tests (Tier-2 lines).
- Must NOT touch: `runtime/builders/data.py`, `runtime/builders/copilot.py`.
- Depends on: items 3 and 4; PRP-72 and PRP-76 merged.
- Acceptance criteria: every block criterion including `not_measurable`, `insufficient_data` and `unavailable` reason codes; a missing upstream service degrades its block only; readiness lists the component.
- Tests: the three files above plus `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`.
- Pattern references: `runtime/builders/edge.py:17-27`, PRP-127's `runtime/builders/risk.py`.

### Item 6 - Frontend
- Deliverable: Chargeback tab (mode switch, table with coverage beside totals, unallocated first when large, by-agent table, export), Product metrics page (four blocks with numerator, denominator, window, source and a "how measured" disclosure), routes appended to `finops/routes.tsx` and the app route manifest, strings file, mock handlers, Playwright and axe samples.
- Owned files: `frontend/src/features/finops/chargeback/**`, `frontend/src/features/finops/routes.tsx`, `frontend/src/features/metrics/**`, the two mock files, `frontend/tests/e2e/chargeback/**`.
- Must NOT touch: `ForecastPage.tsx`, other features.
- Depends on: items 2 and 5 (OpenAPI types).
- Acceptance criteria: the UI criterion; a banned-word test over the strings (no "healthy", "on track", "passed"); keyboard-complete; high-contrast safe (no colour-only status).
- Tests: `pnpm --filter frontend test`, `lint`, `typecheck`, the chargeback e2e.
- Pattern references: `frontend/src/features/finops/ForecastPage.tsx`, `frontend/src/features/admin/pricing/`.

### Item 7 - Authorization and privacy negative suites
- Deliverable: ABAC cases for all four routes and every denial dimension; a privacy suite that drives many turns by several users, then greps the usage store documents, API responses, logs, audit records and exports for principal ids, conversation ids and canary question text, asserts no route lists users, asserts suppression at group sizes 1 and 2, asserts week-bound digests differ across weeks, and asserts the hook adds no field to copilot responses.
- Owned files: `tests/security/authz/test_chargeback_and_metrics.py`, `tests/security/privacy/test_product_usage_privacy.py`.
- Must NOT touch: shared harness except additive helpers.
- Depends on: items 2 to 5.
- Acceptance criteria: every route has a deny case per dimension; no canary or principal id in any output.
- Tests: `tests/security/authz`, `tests/security/privacy`.
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends, runbook (modes and their rules, coverage meaning, what each metric is and is not, the privacy design, suppression, "not measurable" explanation), `openapi.json` and docs regeneration, changelog fragment `changelog.d/PRP-134-chargeback-showback-and-success-metrics.md`, completion note listing the owner follow-ups (agent by cost-center cross-tab, manual-search baseline, automatic copilot segments) and a PostgreSQL follow-up for PRP-90/91 (`product_usage`), and the comment on issue 260 for the orchestrator.
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 7.
- Acceptance criteria: gates pass; CI green.

## Cut line
If the session overruns, items 3, 4 and the answer-time and weekly-active blocks of item 5 (and their tests in item 7) move to a follow-up PRP. Items 1, 2, 6 (chargeback tab) and the acceptance-rate and completeness blocks still merge safely: they touch no copilot code and no new store. Clarification 7 already marks the time-to-answer block as the lowest-value part.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/finops_chargeback packages/core/tests/product_metrics packages/core/tests/ledger services/api/tests/finops_chargeback_api services/api/tests/product_metrics_api services/api/tests/copilot_api services/api/tests/finops services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/authz tests/security/authz tests/security/privacy services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter frontend test
pnpm --filter frontend lint
pnpm --filter frontend typecheck
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New container `product_usage`; no change to the ledger, aggregates or catalog. Rollback: `NS_METRICS_USAGE_ENABLED=false` stops recording (the hook becomes a no-op and the usage blocks report `unavailable`, reason `usage_disabled`); the chargeback routes read existing data and can be removed by reverting the PR. Leftover usage documents expire by TTL.

## Live and open gates
None run here: in-memory twins and, locally, the Cosmos emulator with synthetic data. The numbers on a real deployment depend on real usage; nothing here claims the PRD targets are met. A hosted look at the pages is part of PRP-82's signed-in smoke and PRP-136's hosted runs. No paid call.

## NOT building
A budget or invoice system; allocation rules that move cost between cost centers; an agent by cost-center cross-tab; per-person, per-team or ranking views of usage; session recording; question text analytics; a manual-search baseline or any claim of an 80 percent reduction; pass or fail scoring against the PRD targets; usage metrics for tools other than the copilot and the matcher; a metrics export to external systems.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 5, 6 and 9 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | serial-after PRP-131 (container) |
| 4 | todo | | serial-after PRP-78 |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
