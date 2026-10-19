---
name: prp-15-recommendations-engine
status: active
started: 2026-10-19
review: none
created: 2026-10-08
branch: prp-15-recommendations-engine
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

## Execution state

Plan approved 2026-10-19 with four deltas signed off by the operator, because the repo contradicted the blueprint:

- D1: `RecommendationCompute` (PRP-11) exposes only `co_usage_candidates` (model/provider co-usage across domains), and `TelemetryAnalytics.aggregate` cannot group by agent (`Dimension` has no agent). The fixture adapter builds its own dataset, not the sandbox output, and the PRP-14 aggregates have no agent grain. Item 1 therefore evaluates rules over a narrow `AgentSeriesSource` protocol (per agent per day: events, cost known/unknown, latency p95, errors, per-source coverage) with one implementation that reads sandbox output files (`agents.ndjson`, `telemetry.ndjson`, `cost.ndjson`; telemetry carries `canonical_agent_id`). Recorded OPEN: a production series source needs an agent dimension on the PRP-11 contract and its four adapters.
- D2: agent-pair duplicates cannot run through `RecommendationCompute` (co-usage pairs models, not agents). The sandbox defines a duplicate as shared grounding sources plus the same model deployment, which are catalog relations. Item 2 computes similarity in the worker over presented relations through the read-only `GraphQuery` (in-memory catalog loaded from sandbox output); embeddings are an optional signal hook only. Precision is measured against the manifest's `duplicate_agent_candidates`.
- D3: `neurosphere_api` depends only on `neurosphere-core`, so item 4 also owns the new `packages/core/neurosphere_core/recommendations/` (store protocol plus in-memory implementation over the generated `neurosphere_contracts` `Recommendation`, scope-filtered list/get/search). Items 1-3 emit the generated contract model. Item 4 no longer depends on items 1-3 (it tests on contract fixtures).
- D4: the UI is split out of item 4 into item 5 (`frontend/src/features/recommendations/`). A new item 6 owns the shared wiring: router registration in `services/api/neurosphere_api/routers.py`; route and nav in `frontend/src/app/main.tsx` and `frontend/src/app/workspaceNav.ts`; recommendations fixtures in `frontend/tests/mock-api/server.ts`; Playwright specs in `frontend/tests/e2e/recommendations/`; `services/api/openapi.json` regeneration; the worker pipeline `services/workers/neurosphere_workers/recommendations/pipeline.py` (runs items 1-3 over sandbox output into the store); an in-process slice in `tests/integration/recommendations/`; and evidence in `docs/evidence/G12/recommendations/` with measured detection and precision. The orchestrator created `services/workers/neurosphere_workers/recommendations/__init__.py` on the integration branch before dispatch; no item edits it.

Waves: 1 = items 1, 2, 3, 4 in parallel; 2 = item 5 (first free slot); 3 = item 6 (after 1-5).

### Wire contract (decided at approval; items 4-6 code against it)
The domain is a path segment, authorized against the server-derived `IdentityScope`; out-of-scope domain returns 403 (problem+json), policy store outage 503.

- `GET /api/v1/recommendations/domains/{domain}` (`data.read`), query `kind`, `q` (bounded text over kind and subject ids), `cursor`, `limit`: `{ "items": [Recommendation], "next_cursor": str|null }`.
- `GET /api/v1/recommendations/domains/{domain}/items/{recommendation_id:path}` (`data.read`): `{ "recommendation": Recommendation, "review": {"state": "not_routed"|"pending_review", "review_request_id": str|null}, "execution": {"executable": false, "reason": "action gates not passed"} }`.
- `POST /api/v1/recommendations/domains/{domain}/review-requests`, body `{ "recommendation_id" }` (`action.propose`): 202 `{ "review_request_id", "state": "pending_review" }` through a `ReviewRouter` protocol, in-memory stub until PRP-17.
- `POST /api/v1/recommendations/domains/{domain}/executions`: always refuses with `capability_unavailable`, reason "action gates not passed"; no executing code path.

`recommendation_id` = `{cloud}:{customer_id}:neurosphere:recommendation:{kind with _ as -}-{h}`, where `h` is the first 24 hex chars of sha256 over `generator_id|generator_version|sorted subject_ids|window.start|window.end`. Amended after item 3 to the hyphenated kind; item 1 then showed `_` is in fact allowed by the last-segment class `[a-z0-9._/=-]`, so the hyphen form is a consistency choice, not a grammar requirement. All items use it.

`Recommendation` is the PRP-01 schema document verbatim (`packages/contracts/schemas/recommendations/v1/recommendation.schema.json`).

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 | merged | worktree-agent-a3a33fb34fe9eb576 | sonnet | ac73f1d; orchestrator re-run on branch: ruff + format clean, pyright 0 errors, rules 45 passed, no production `sandbox` import (test-only `sys.path` setup); detection on a 40-agent, 7-day, ~20 traces/agent-day set: cost_spike 3/3, latency 3/3, unused 3/3 on seeds 3 and 11, zero false positives on non-anomaly agents (cost-spike agents also trip latency, a real effect, allowed); decisions: latency uses daily p50 by default (p95 on a handful of requests was too noisy, controls hit 9x; `percentile` configurable), score = breach_days / recent_days with `rule_bound`, source coverage from the canonical id source segment, uncovered source -> `unknown_coverage`, no record; limits: pilot profile (~2 traces/agent-day) latency recall 2/5 plus one unlabelled zero-event sub-agent flagged unused, and seed 7 misses one latency anomaly at ratio 1.97 vs threshold 2.0 (data density, recorded); merge 32db480, recommendations workers 72 passed post-merge | 2026-10-19 |
| 2 | merged | worktree-agent-a68d7d8fcfed09859 | sonnet | 0abe7d0; orchestrator re-run on branch: ruff + format clean, pyright 0 errors, duplicates 29 passed (54 s), no mutation calls or `view="raw"` outside tests; measured on custom sandbox (400 agents, 8 domains, 3 days, 8 duplicate pairs) seed 7: 9 predicted, 8 TP, precision 0.889, recall 1.000, 27 pairs to `review_candidates`; seeds 1-3 precision 1.0, recall 1.0. CAVEAT: thresholds (`min_similarity` 0.9, `review_floor` 0.7) were tuned on these same seeds, so this is a pilot-set fit, not held-out evidence; decisions: confidence-weighted Jaccard over presented `grounded_by`/`uses_model`/`invokes`/`owned_by` plus `agent_kind` and an optional embedding provider, trace-inferred edges at 0.25 of confidence, same domain is a gate; agents listed via a narrow `AgentLister` (GraphQuery has no list op); model deployments homed in another domain are `unobserved` under a single-domain scope (coverage partial, wider upper bound); merge 41dd240, recommendations workers 101 passed post-merge | 2026-10-19 |
| 3 | merged | worktree-agent-a2f115cb4eb7c644b | sonnet | d1eadaa; orchestrator re-run on branch: ruff + format clean, pyright 0 errors, pricing + projection 47 passed, no network imports, fixtures labelled synthetic; decisions: identical re-put is an idempotent no-op, conflicting re-put raises `SnapshotConflictError`; right-sizing records are `method: rule`, `insufficient_evidence`, no score (nothing measures candidate quality); candidate priced from the same snapshot as the current model, else `invalid_schema` `price_unresolved`; Retail Prices snapshots apply to commercial only (Learn, verified 2026-10-19); deviation: id kind segment uses hyphens (contract amended); merge 6e1f468, ruff clean, 47 passed post-merge | 2026-10-19 |
| 4 | merged | worktree-agent-a18e73fa86390fd69 | sonnet | cbb4d5e; orchestrator re-run on branch: ruff + format clean, pyright 0 errors, recommendations 48 passed, services/api 507 passed (a reconciliation scope test failed once in the agent's first run and passed on every re-run, flaky, cause not established); scope audit: router uses `require(permission, domain_from_path)`, store `_visible` checks customer, cloud, allowed domain and record domain == path domain; deviations: executions refusal is 409 `capability_unavailable` with `detail` "action gates not passed" and `reason` `action_gates_not_passed` (ProblemDetails requires snake_case reason) and requires `action.propose`; missing recommendation is a plain 404; extra body `domain_id`/`customer_id` ignored; `q` is a case-insensitive substring capped at 128 chars; app.state `recommendation_store`, `review_router` (503 when absent); OPEN: Cosmos store, real PRP-17 ReviewRouter; merge 814cfe2, services/api + core 538 passed post-merge | 2026-10-19 |
| 5 | merged | worktree-agent-acbc0c06c6b9c3991 | sonnet | ade8182; orchestrator re-run on branch: eslint + tsc clean, vitest 191 passed (25 new), build ok; `Recommendation` type from `@neurosphere/contracts`, POST via the existing `createMutationHook`/`client.post` (no `frontend/src/api/` edit); domain and id from UI search params `?domain_id=`/`&recommendation_id=` (same convention as dashboards; the API call carries the domain as a path segment only); exports `recommendationRoutes` (`recommendations`, `recommendations/detail`) and `recommendationNavItems()` (`/recommendations`); merge 4846678 plus orchestrator fix 6192074 (filter submit relabelled "Apply filters": a bare "Apply" beside advisory recommendations read as applying one); post-merge lint + tsc clean, vitest 191 passed, build ok | 2026-10-19 |
| 6 | in-progress | (worktree) | sonnet | dispatched after items 1-5 merged | 2026-10-19 |

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Open gates recorded (ids and where):
- Follow-ups:
