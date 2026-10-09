---
name: prp-15-recommendations-engine
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 2
ns: NS-03
depends_on: PRP-10, PRP-11
wave: W6
absorbs: P2.3
---

# PRP-15: Recommendations engine

## Goal
Ship the evidence-backed recommendation pipeline for NS-03: bounded rules for cost spikes, latency and error degradation and unused agents; duplicate-candidate detection that only ever proposes a consolidation review; cost projections tied to versioned pricing; and an API and UI that list recommendations with evidence, owner, prerequisites and an explicit advisory status. Audience: domain stewards, analysts and FinOps, who need suggestions they can trust and audit; downstream, PRP-17 consumes the review-routing interface and PRP-16 shares the evidence conventions. It lands in W6 after the catalog (PRP-10) and analytics adapters (PRP-11) supply entities and `RecommendationCompute`. Recommendations are advisory until the action gates of PRP-17 pass; nothing here changes a target system.

> NS-03: "Each suggestion includes evidence window, coverage, uncertainty, prerequisites, projected estimate and owner; cold-start uses bounded rules rather than fabricated scores."

> NS-03: "Duplicate detection recommends consolidation review; it never automatically merges operational agents."

> NS-03: "Model swaps require capability/context/tool compatibility, quality regression tests and cost comparison, then staged rollout/canary and rollback."

## Acceptance criteria
- [ ] Item 1: Given the sandbox with seeded anomalies (spike, latency, unused), When the rules run, Then every injected anomaly in the manifest is detected; Given an agent with too little history, Then cold start emits a bounded rule result with no numeric score.
- [ ] Item 2: Given the sandbox duplicate set, When similarity runs through `RecommendationCompute`, Then precision is at least 80% on that set (a pilot-set target, not a general claim); no code path merges, deletes or edits agents.
- [ ] Item 3: Every projection carries a price version id and effective date; a projection with no resolvable price version is not emitted.
- [ ] Item 4: Given a recommendation, When a user clicks any action control, Then it routes to review and the API refuses direct execution (no executable state) until PRP-17 gates exist; UI shows "advisory".
- [ ] Each recommendation record validates against the PRP-01 `Recommendation` schema with evidence window, coverage, uncertainty, prerequisites, projected estimate and owner.
- [ ] Authorization: recommendations for domain B never appear for a caller scoped to domain A, in list, detail or search.
- [ ] PRP exit: `verify-gates -Mode full` and `python scripts/validate_planning.py` pass; measured precision and detection results filed in the completion note.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model and review | opus; sonnet | Sonnet, review: none (D6). Advisory-only status removes the highest-risk path |
| 2 | Are recommendations executable | executable now; advisory | Advisory until action gates pass. The API has no execute route; PRP-17 owns execution and G05 |
| 3 | Cold start | model-based score; bounded rules | Bounded rules only (fixed thresholds with documented windows); no fabricated scores. Output states "insufficient history" with coverage |
| 4 | Duplicate action | auto-merge; review only | Review only; never merges. Candidates link to both entities and carry similarity evidence |
| 5 | Duplicate precision target | none; 80% | At least 80% precision on the sandbox duplicate set, stated as a pilot-set target. Recall is reported, not gated |
| 6 | Embeddings | required; optional | Optional input (NS-02 "optional embeddings"). The fixture adapter path must pass without embeddings; shared-source and overlap signals are the baseline |
| 7 | Pricing sources | hardcoded; versioned snapshots | Azure Retail Prices API snapshots plus provider price sheets, each stored as an immutable versioned snapshot with id and effective date. Snapshot refresh is a separate job and needs egress approval; tests use committed fixtures only |
| 8 | Live pricing calls | include in CI; fixtures | Fixtures in CI. No live call is part of this PRP; no paid model calls |
| 9 | Compute path | in API process; worker via adapter | Analytical work runs in workers through `RecommendationCompute` (PRP-11), never on the interactive path |
| 10 | Model right-sizing | recommend swaps; candidates only | Candidates only, with explicit prerequisites (capability, context, tool compatibility, regression tests, canary); no claim of savings without a price version |
| 11 | Government | same code; gated | Same code path; adapter availability comes from the capability matrix; no data leaves its cloud |
| 12 | Emulators | rely on RU or indexes | Cosmos emulator lacks RU accounting and range/composite indexes; evidence is bounded feasibility on compose (G12) |

## Context manifest

### Files that matter
- `PRP.md` sections 1-3, `docs/PRD.md` NS-03 (plus NS-02 for optional embeddings), `docs/ARCHITECTURE.md` section 2 (recommendations fed by analytics, catalog and evaluation) and section 6 (RecommendationCompute).
- `docs/RESEARCH-AND-GATES.md` (G01, G04, G05, G12), `docs/adr/0002-stack-pins.md`, `docs/adr/0007-analytics-adapter-contract.md` (created by PRP-02).
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/recommendations/` (`Recommendation`), `schemas/cost/`, generated Python and TS types.
- Created by PRP-03: `sandbox/` generator with anomaly manifest (spike, latency, unused, duplicates).
- Created by PRP-05: worker runtime base, `neurosphere_core/errors`, `paging`.
- Created by PRP-06: `neurosphere_api/authz/`.
- Created by PRP-07: `neurosphere_core/ledger/` with price version table and cost records.
- Created by PRP-10: `neurosphere_core/catalog/repo/`, `catalog/graph/` (entities, shared-source relations).
- Created by PRP-11: `neurosphere_core/analytics/base/` (`RecommendationCompute`) and `analytics/fixture/`.
- Created by PRP-14 (if merged first): hot aggregates; this PRP must not depend on them.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for rule configs, evidence windows and projection records.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (`recommendations/`), endpoints behind `require(permission)`.
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; analytical access only through `RecommendationCompute`.
- Error taxonomy exceptions from `neurosphere_core.errors` (`capability_unavailable`, `rate_limited` on budget exceed).
- Tests beside packages and cross-package suites in `tests/`; `pytest.mark.integration` for compose-backed runs.
- Frontend: TS strict, `@fluentui/react-components`, Vitest + Testing Library, Playwright under `frontend/tests/e2e`; data via PRP-04 typed client.

### Conventions
- ruff (line 100, py312, S rules on), pyright standard, conventional commits (`feat(recommendations): ...`), owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1` (none here).
- Rules are data-driven (versioned config documents with thresholds and windows) so a recommendation can cite the rule id and version that produced it.

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
- PRP-specific: a recommendation's cost estimate is a projection from versioned pricing; show it as an estimate with the price version, never as realized savings. No percentage savings claim without evidence.
- PRP-specific: locked or curated catalog relations influence presented lineage; duplicate similarity must read presented relations and must not write to the catalog.
- PRP-specific: unused-agent rules must distinguish "no events observed" from "no coverage" (a source with missing telemetry is unknown, not unused).
- PRP-specific: price sheets from providers may be PDF or portal-only; ingest only machine-readable official sources and record the retrieval date; do not scrape.
- PRP-specific: `neurosphere_core/pricing/` is owned by item 3 only; PRP-07 owns the ledger's price version table, so pricing code must read it through the ledger interface, not edit it.

### External references
- Azure Retail Prices API (public pricing endpoint, query by service/SKU/region/currency), https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices, not observed during planning: record the retrieval date and any Government cloud applicability in the snapshot metadata at implementation time.
- Cosmos hierarchical partition keys (Python SDK 4.6 or later; new containers only), https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys, observed 2026-10-08.
- Cosmos DB vNext emulator limits, https://learn.microsoft.com/azure/cosmos-db/emulator-linux, observed 2026-10-08.
- Foundry models in Azure Government (model availability affects right-sizing candidates), https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-gov, observed 2026-10-08 (dated 2026-09-01).
- PRD NS-03 planning text in `docs/PRD.md` (repo document, v1.1).

## Implementation blueprint

### Item 1 — rules-engine  [P]
- Deliverable: rule evaluator and versioned rule configs for cost spike, latency degradation, error degradation and unused agent, each emitting evidence window, coverage, uncertainty and owner reference; cold-start path emits bounded rule output with no score.
- Owned files (may edit): `services/workers/neurosphere_workers/recommendations/rules/`.
- Must NOT touch: `services/workers/neurosphere_workers/recommendations/duplicates/` (item 2), `.../projection/` (item 3), `packages/core/neurosphere_core/pricing/` (item 3), `neurosphere_core/analytics/` (PRP-11), `sandbox/` (PRP-03), root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - All anomalies in the sandbox manifest (spike, latency, unused) are detected, with zero false positives on the clean control set.
  - Agent with history below the minimum window yields `cold_start` output with null score and a stated rule threshold.
  - Missing telemetry is reported as `unknown` coverage, never as zero usage.
- Pattern references: worker runtime base; Pydantic strict rule configs; `RecommendationCompute` for aggregate reads.
- Tests to write: `services/workers/neurosphere_workers/recommendations/rules/tests/test_sandbox_anomalies.py`, `test_cold_start_no_score.py`, `test_unknown_not_unused.py`.

### Item 2 — duplicate-candidates  [P]
- Deliverable: similarity job over shared sources, overlapping tools and (optionally) embeddings via `RecommendationCompute`, producing consolidation-review candidates with evidence; no mutation path.
- Owned files (may edit): `services/workers/neurosphere_workers/recommendations/duplicates/`.
- Must NOT touch: `.../recommendations/rules/` (item 1), `.../recommendations/projection/` (item 3), `neurosphere_core/catalog/` (PRP-10, read through interfaces only), `sandbox/`.
- Depends on: none.
- Acceptance criteria:
  - At least 80% precision on the sandbox duplicate set (pilot-set target); recall reported alongside.
  - Static test proves the module imports no catalog write API and calls no update, merge or delete method.
  - Candidate cites both canonical IDs, similarity signals and evidence IDs; low-confidence candidates route to review, not to a recommendation of action.
- Pattern references: `RecommendationCompute` fixture adapter; catalog `GraphQuery` read-only use.
- Tests to write: `services/workers/neurosphere_workers/recommendations/duplicates/tests/test_precision_sandbox.py`, `test_no_merge_paths.py`, `test_scope_filtering.py`.

### Item 3 — cost-projection  [P]
- Deliverable: versioned pricing store (immutable snapshots from Azure Retail Prices API data and provider price sheets, with id, source, retrieval date, effective date, currency) and projection logic for right-sizing candidates and cost comparisons.
- Owned files (may edit): `services/workers/neurosphere_workers/recommendations/projection/`, `packages/core/neurosphere_core/pricing/`.
- Must NOT touch: `packages/core/neurosphere_core/ledger/` (PRP-07), `.../recommendations/rules/` (item 1), `.../recommendations/duplicates/` (item 2), `infra/`, `.env.example`.
- Depends on: none.
- Acceptance criteria:
  - Every projection includes `price_version_id` and effective date; projection without a resolvable version is rejected (`invalid_schema`).
  - Snapshots are immutable and content-hashed; a new snapshot never overwrites an old one.
  - Right-sizing candidates list prerequisites (capability, context, tool compatibility, regression tests, canary) and state "estimate", with uncertainty range.
- Pattern references: Pydantic strict models; ledger price version table read via interface.
- Tests to write: `packages/core/neurosphere_core/pricing/tests/test_snapshot_immutability.py`, `.../test_version_resolution.py`, `services/workers/neurosphere_workers/recommendations/projection/tests/test_projection_cites_version.py` (fixture snapshots only, no network).

### Item 4 — recommendations-api-ui
- Deliverable: list and detail endpoints with filters and pagination, evidence panel, owner, prerequisites, advisory status, and a "route to review" action that calls the PRP-17 interface (stubbed until PRP-17 merges); frontend list and detail pages.
- Owned files (may edit): `services/api/neurosphere_api/recommendations/`, `frontend/src/features/recommendations/`.
- Must NOT touch: `services/api/neurosphere_api/actions/`, `.../hitl/` (PRP-17), `frontend/src/features/review/` and `frontend/src/features/actions/` (PRP-17), `frontend/src/api/`, `frontend/src/design-system/`, items 1-3 paths.
- Depends on: items 1, 2, 3.
- Acceptance criteria:
  - No route or UI control executes a change; a request attempting execution returns `capability_unavailable` with reason "action gates not passed".
  - Detail shows evidence window, coverage, uncertainty, prerequisites, projected estimate with price version, and owner; unknown fields render "unknown".
  - Cross-domain list or detail request returns 403; axe clean; keyboard operable.
- Pattern references: router per module; `require(permission)`; PRP-04 typed client; Fluent UI v9.
- Tests to write: `services/api/neurosphere_api/recommendations/tests/test_no_execute_route.py`, `test_scope_denial.py`, `test_detail_contract.py`, `frontend/src/features/recommendations/__tests__/detail.test.tsx`, `advisory-badge.test.tsx`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
- `docker compose up -d --wait` then `python -m pytest -m integration services/workers/neurosphere_workers/recommendations services/api/neurosphere_api/recommendations -q`
- `python -m pytest packages/core/neurosphere_core/pricing -q`
- `pnpm --filter frontend test`
- `make seed` to load the sandbox anomaly manifest before detection tests.
- No live script: this PRP has no operator-approved gate. A live pricing refresh, if ever wanted, is a separate item that would be **operator-approved, requires NS_LIVE_APPROVED=1**.

## Live and open gates
- G05 (model swap compatibility): untouched; this PRP only lists right-sizing candidates with prerequisites. Execution evidence is PRP-17.
- G04 (provider/API/license coverage): price sheet ingestion records source coverage per provider; gaps stay OPEN until PRP-09 evidence exists.
- G01 (service/feature/region/SKU matrix): projections depend on region and SKU availability from the matrix; unverified Government rows produce no projection.
- G12 (emulator parity): detection and precision results come from emulators on compose; record that RU and index behavior are not reproduced.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Action execution, approvals, maker-checker and review queue (PRP-17); only the routing interface call.
- Evaluation, judge calibration and quality trends (PRP-16).
- Dashboards (PRP-14) and live map overlays (PRP-18).
- Copilot recommendation explanations (PRP-19).
- Automatic merge or consolidation of agents, ever.
- Forecast models or FinOps forecasting (PRP-21).
- Agent/tool selection as a recommendation capability (NS-03 calls it optional and secondary).
- Any claim of realized savings.

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
