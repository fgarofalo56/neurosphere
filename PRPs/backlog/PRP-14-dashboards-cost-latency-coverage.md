---
name: prp-14-dashboards-cost-latency-coverage
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-01, NS-07
depends_on: PRP-04, PRP-07, PRP-10
wave: W6
absorbs: P1.4 dashboards
---

# PRP-14: Dashboards for cost, latency and coverage

## Goal
Deliver the first operator-facing analytics surface: materialized 90-day hot aggregates per domain, bounded dashboard and reconciliation APIs, cost/latency/error/coverage pages, and a reconciliation (variance) view, proven end to end from sandbox data through ingest and aggregation to a Playwright-driven UI. Audience: analysts, FinOps and platform owners, who need honest numbers: unknown values show "unknown" and never 0, spend is labeled estimated or invoiced, every projection shows its price version, and the views keep working when the batch analytics backend is delayed or down. It lands in W6 because it needs the ledger and outbox (PRP-07), the app shell (PRP-04) and catalog identities (PRP-10). NS-07 is covered here only for the analytics-option side: dashboards read hot aggregates and surface which analytics adapter state (available, delayed, disabled with reason) is behind them.

> NS-01: "Cost records distinguish estimated vs invoiced spend, currency, price version/effective date, cached tokens, retries, compute/PTU/reservation allocation and license/seat costs. Avoid double counting gateway, application and billing observations. Expose reconciliation coverage and variance; do not promise all spend is observable or attributable per user."

> NS-01: "Missing fields remain null/unknown, never zero by default."

> PRD section 3 (planning targets, to be measured rather than guaranteed): "dashboard p95 <=2s on bounded 90-day aggregates". Hot aggregates remain operational if batch analytics is delayed; the UI shows lag and coverage (ARCHITECTURE section 2).

## Acceptance criteria
- [ ] Item 1: Given the analytics adapter is stopped, When the dashboards API is queried for a 90-day window, Then it still serves from hot aggregates and returns lag and coverage metadata.
- [ ] Item 2: Given the sandbox 90-day dataset, When dashboards endpoints are load-tested, Then measured p95 is recorded against the PRD planning target of 2s (a target, not a guarantee); an unknown metric returns the literal `unknown`, never 0.
- [ ] Item 3: Given a metric with null source data, When the page renders, Then the cell shows "unknown"; every cost figure carries an estimated or invoiced badge and a visible price version.
- [ ] Item 4: Given ledger records from gateway, app and billing for the same request, When the reconciliation view loads, Then variance per source is shown with a granularity label, with no double counting.
- [ ] Item 5: Playwright flow sandbox, ingest, aggregate, UI passes in CI with compose, including the analytics-down case.
- [ ] Authorization: a viewer without access to domain B never receives domain B aggregates on any dashboards or reconciliation route (403, not empty 200).
- [ ] PRP exit: `verify-gates -Mode full` and `python scripts/validate_planning.py` pass; measured latency evidence filed at `docs/evidence/G07/dashboards/`.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model and review | opus; sonnet | Sonnet, review: none (D6). Authorization defects are covered by the explicit negative criterion and PRP-06 suites |
| 2 | Source of dashboard data | analytics adapter; hot aggregates | Hot aggregates are the primary read path; analytics adapter is optional enrichment for older ranges. PRP-11 is not a dependency |
| 3 | Aggregate window and grain | free; fixed | 90-day rolling window; daily and hourly grains; grains and rollup keys documented in the worker module README |
| 4 | Unknown representation | null in JSON; literal string | API returns `{"value": null, "status": "unknown"}`; UI renders "unknown". Totals that include unknown components expose a `complete: false` flag, not a silently smaller sum |
| 5 | Estimated vs invoiced | blended; separate | Always separate series; no blended total is displayed unless both are labeled |
| 6 | Price version display | tooltip only; badge | Badge visible on every cost figure showing the price version id and effective date from the ledger |
| 7 | Performance claim wording | guarantee; target | Quote the PRD p95 <=2s as a planning target; evidence records measured numbers on the sandbox dataset; no SLA claim |
| 8 | Charts | generated Vega; fixed components | Fixed React chart components for these pages; no copilot chart plans here (PRP-19 owns Vega-Lite subset) |
| 9 | Emulator handling | assert RU or index behavior | Cosmos vNext emulator has no RU accounting or range/composite indexes, so latency evidence is "sandbox on compose, bounded feasibility", flagged G12 |
| 10 | Live items | add live gate | None. No `scripts/gates/` item; evidence is compose-based |
| 11 | Scope in cache keys | per user; hash of scope | Cache key = hash(IdentityScope) plus query shape, never a caller-supplied domain |
| 12 | Freshness label | seconds; coarse | Show aggregate watermark time and lag; billing-sourced figures show source freshness separately (not sub-10s) |

## Context manifest

### Files that matter
- `PRP.md` sections 1-3, `docs/PRD.md` NS-01 and NS-07 and section 3 (planning targets), `docs/ARCHITECTURE.md` section 2 (projections, hot aggregates, lag and coverage).
- `docs/RESEARCH-AND-GATES.md` (G07, G12), `docs/adr/0002-stack-pins.md` (React 19.3, Fluent UI 9.74, TanStack Query 5.104, Playwright 1.64).
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/cost/`, `schemas/telemetry/`, generated types in `packages/contracts/python/` and `packages/contracts/ts/`.
- Created by PRP-03: `sandbox/` generator and seed CLI (`scripts/sandbox/`).
- Created by PRP-04: `frontend/src/app/`, `frontend/src/design-system/`, `frontend/src/api/` (typed client, error mapping), `frontend/tests/`.
- Created by PRP-05: `services/api/neurosphere_api/` app factory, `neurosphere_workers/runtime/`, `neurosphere_core/observability/`.
- Created by PRP-06: `neurosphere_api/authz/` (`require(permission)`), scope derivation.
- Created by PRP-07: `neurosphere_core/ledger/`, `neurosphere_workers/projections/outbox/` (outbox with per-sink checkpoints), price version table.
- Created by PRP-10: catalog repository and canonical agent IDs used to label rows.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for aggregate documents and API responses (value/status/complete/lag fields).
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (`dashboards/`, `reconciliation/`), each endpoint behind `require(permission)`.
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; workers use the runtime base (checkpoint interface, graceful shutdown) from PRP-05.
- Error taxonomy exceptions from `neurosphere_core.errors`; pagination and budget models from `neurosphere_core.paging`.
- Tests beside packages; cross-package suites in `tests/`; `pytest.mark.integration` for compose-backed aggregate tests.
- Frontend: TS strict, `@fluentui/react-components`, Vitest + Testing Library, Playwright under `frontend/tests/e2e`; data fetching through the PRP-04 typed client and TanStack Query.

### Conventions
- ruff (line 100, py312, S rules on), pyright standard, conventional commits (`feat(dashboards): ...`), owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1` (none here).
- UI text for unknown, estimated, invoiced and price version lives in one constants module per feature so tests assert exact strings.

### Gotchas
- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-specific: aggregates are projections from the outbox with their own per-sink checkpoint; they are rebuildable. Do not read the cost ledger directly on the request path.
- PRP-specific: summing null with numbers silently coerces to 0 in many libraries (pandas, JS `+`). Aggregation code must track `complete` explicitly and tests must include a null-heavy fixture.
- PRP-specific: do not double count; the ledger holds one cost record per request across gateway, app and billing observations (PRP-07). Aggregates sum ledger records only.
- PRP-specific: the dashboards p95 number applies to bounded 90-day aggregates, not arbitrary analytics queries; every endpoint takes budgets (max series, max points) from `neurosphere_core.paging`.
- PRP-specific: the analytics adapter state shown in the UI comes from the capability matrix (PRP-02) as disabled-with-reason; do not hardcode vendor names in the UI strings.

### External references
- NS-01 and PRD section 3 targets in `docs/PRD.md` (repo document, v1.1).
- Cosmos DB vNext emulator limits, https://learn.microsoft.com/azure/cosmos-db/emulator-linux, observed 2026-10-08.
- Cosmos hierarchical partition keys (Python SDK 4.6 or later; new containers only), https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys, observed 2026-10-08.
- Cosmos change feed modes (all-versions-and-deletes still preview; use outbox), https://learn.microsoft.com/azure/cosmos-db/change-feed-modes, observed 2026-10-08.
- Fluent UI React v9, https://www.npmjs.com/package/@fluentui/react-components, version 9.74 observed 2026-10-08 in ADR-0002.
- TanStack Query 5.104 and Playwright 1.64, versions per `docs/adr/0002-stack-pins.md`, observed 2026-10-08.

## Implementation blueprint

### Item 1 — hot-aggregates-worker  [P]
- Deliverable: worker materializing 90-day rollups (cost estimated, cost invoiced, latency percentiles, error rate, coverage) per domain from the outbox, with lag and coverage metadata and an explicit `complete` flag.
- Owned files (may edit): `services/workers/neurosphere_workers/aggregates/`.
- Must NOT touch: `services/workers/neurosphere_workers/projections/outbox/` (PRP-07), `services/api/neurosphere_api/dashboards/`, `neurosphere_core/ledger/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Given the analytics adapter is down, aggregates continue to update and be readable.
  - Replaying the same outbox batch twice yields identical aggregates (idempotent).
  - Null inputs never become 0; documents carry `complete` and `watermark`.
- Pattern references: worker runtime base (PRP-05), per-sink checkpoint (PRP-07).
- Tests to write: `services/workers/neurosphere_workers/aggregates/tests/test_rollups.py`, `test_nulls_not_zero.py`, and integration `test_aggregates_idempotent.py` (same directory, marker `integration`).

### Item 2 — dashboards-api
- Deliverable: bounded endpoints for cost, latency, error and coverage with scope, pagination and budgets; response model with value/status/complete/lag/price_version.
- Owned files (may edit): `services/api/neurosphere_api/dashboards/`.
- Must NOT touch: `services/api/neurosphere_api/reconciliation/` (item 4), `services/workers/neurosphere_workers/aggregates/` (item 1), `neurosphere_api/authz/`, root `pyproject.toml`.
- Depends on: item 1.
- Acceptance criteria:
  - Unknown metric returns `status: "unknown"` with null value, never 0 (property test over nullable fixtures).
  - Cross-domain request returns 403; policy store outage returns 503.
  - Endpoint handlers expose per-request timing so item 5 can record p95 on the sandbox 90-day dataset and compare it to the 2s planning target.
- Pattern references: router per module, `require(permission)`, paging/budget models.
- Tests to write: `services/api/neurosphere_api/dashboards/tests/test_unknown_not_zero.py`, `test_scope_denial.py`, `test_budgets.py`.

### Item 3 — dashboards-ui  [P]
- Deliverable: cost, latency and coverage pages; estimated vs invoiced badges; price version badge; lag indicator; analytics adapter state chip (available, delayed, disabled with reason).
- Owned files (may edit): `frontend/src/features/dashboards/`.
- Must NOT touch: `frontend/src/features/reconciliation/` (item 4), `frontend/src/design-system/`, `frontend/src/api/`, `frontend/src/app/` (PRP-04), `frontend/package.json`.
- Depends on: none (codes against the PRP-01 generated TS types and a mock API).
- Acceptance criteria:
  - Null metric renders exactly "unknown" (test asserts string); zero renders "0" only when the API says value 0.
  - Every cost figure has an estimated or invoiced badge and the price version visible without hover.
  - Pages keyboard navigable; axe clean on all three routes.
- Pattern references: Fluent UI v9 components, TanStack Query, PRP-04 typed client and error mapping.
- Tests to write: `frontend/src/features/dashboards/__tests__/unknown.test.tsx`, `badges.test.tsx`, `lag-indicator.test.tsx`.

### Item 4 — reconciliation-view  [P]
- Deliverable: coverage and variance view from the PRP-07 ledger: per-source variance, granularity label, coverage percent with explicit unknown remainder.
- Owned files (may edit): `frontend/src/features/reconciliation/`, `services/api/neurosphere_api/reconciliation/`.
- Must NOT touch: `frontend/src/features/dashboards/` (item 3), `services/api/neurosphere_api/dashboards/` (item 2), `neurosphere_core/ledger/` (PRP-07), `frontend/src/api/`.
- Depends on: none.
- Acceptance criteria:
  - Variance per source is displayed with a granularity label (for example vendor-level or request-level, as reported by the source); no claim that all spend is observable.
  - A source with no data shows "unknown" coverage, not 0 percent.
  - API enforces scope; reconciliation endpoint returns 403 across domains.
- Pattern references: router per module; Fluent UI table; PRP-07 ledger models (estimated vs invoiced).
- Tests to write: `services/api/neurosphere_api/reconciliation/tests/test_variance.py`, `test_scope_denial.py`, `frontend/src/features/reconciliation/__tests__/variance-view.test.tsx`.

### Item 5 — vertical-slice-e2e
- Deliverable: Playwright test driving sandbox seed, ingest, aggregation and UI, including the analytics-down scenario, runnable in CI against compose.
- Owned files (may edit): `tests/e2e/dashboards/`, `docs/evidence/G07/dashboards/` (measured p95 JSON and a short markdown note, labelled "sandbox on compose, emulators").
- Must NOT touch: `frontend/playwright.config.ts` (PRP-04), `docker-compose.yml`, `scripts/sandbox/` (PRP-03), items 1-4 paths.
- Depends on: items 1, 2, 3, 4.
- Acceptance criteria:
  - Passes headless in CI with `docker compose --profile app up -d --wait`.
  - Asserts "unknown" cell, estimated and invoiced badges, price version, lag indicator, and analytics-down continuity.
  - Records timings used for the latency evidence file.
- Pattern references: Playwright under `frontend/tests/e2e` conventions from PRP-04 (config reused, not edited).
- Tests to write: `tests/e2e/dashboards/dashboards.spec.ts`, `tests/e2e/dashboards/analytics-down.spec.ts`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
- `docker compose --profile app up -d --wait` then `python -m pytest -m integration services/workers/neurosphere_workers/aggregates services/api/neurosphere_api/dashboards services/api/neurosphere_api/reconciliation -q`
- `pnpm --filter frontend test` and `pnpm --filter frontend exec playwright test tests/e2e/dashboards`
- `make seed` (idempotent sandbox load from PRP-03) before the e2e run.
- No live script: this PRP has no operator-approved gate.

## Live and open gates
- G07 (workload/SLO/DR): sandbox latency numbers narrow the dashboard planning target only; sized-profile and cost evidence stay OPEN (PRP-21).
- G12 (emulator parity): measurements come from Cosmos and Event Hubs emulators on compose; record that RU, indexing and Entra behavior are not reproduced.
- G04 (provider/API coverage): the reconciliation view reports coverage gaps but does not close G04 (PRP-09 owns connector evidence).
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Live ecosystem map and session replay (PRP-18).
- Copilot-generated charts, saved dashboards and the Vega-Lite subset renderer (PRP-19).
- Quality and evaluation dashboards (PRP-16) and recommendations list (PRP-15).
- Analytics adapters (PRP-11); this PRP reads hot aggregates and reports adapter state.
- Cost forecasting and FinOps projections (PRP-21), price snapshots (PRP-15).
- Export to SIEM or enterprise analytics; per-user spend attribution claims.
- Any guarantee or SLA for the 2s target.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Open gates recorded (ids and where):
- Follow-ups:
