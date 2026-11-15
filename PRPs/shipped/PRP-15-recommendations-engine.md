---
name: PRP-15-recommendations-engine
status: shipped
shipped: 2026-11-15
pr: 281
priority: P1
order: 25
review: required
created: 2026-10-08
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 2
ns: NS-03
depends_on: []
wave: W13
branch: prp-15-round2-production-series
allow_parallel: true
absorbs: P2.3
issues: [231, 133]
---

# PRP-15: Recommendations engine (round 2)

## Goal
Feed the shipped recommendations pipeline with real telemetry and raise its measured quality. Round 1 shipped bounded rules, duplicate detection, cost projection, the API, the UI and a worker role, but every record comes from sandbox NDJSON files. Round 2 adds a production `AgentSeriesSource` that reads the redacted archive (telemetry and cost documents) behind a new `NS_WORKER_REC_SOURCE=archive|sandbox` switch (default `sandbox`), runs duplicate detection over the live catalog when the source is `archive`, recalibrates duplicate thresholds and the pilot-density latency policy on held-out seeds, and closes the two recommendation bullets of #133 (the `HitlReviewRouter` race and duplicate recommendation ids across partitions). It is for stewards and FinOps who need recommendations about their own agents, and for PRP-58, which turns the role on in hosted environments. It runs in W13 because it holds the worker `build_recommendations` body.

Out of scope: enabling the recommendations role in Bicep, App Service and Helm and a real-stack run (PRP-58, lane A unit U2); the evaluation half of #133 (`evaluation_id` duplicates across partitions, PRP-16 territory, left on the issue); the `RecommendationStore` SharedKey coupling in the API composition (#131, PRP-51); gateway token pricing (#148, PRP-46); an agent dimension on the PRP-11 analytics contract or on the hot aggregates (PRP-14; the owner chose the archive for this series, assumption A4); any execution path (PRP-17).

## Why
- The only `AgentSeriesSource` implementation is `SandboxSeriesSource` (`services/workers/neurosphere_workers/recommendations/rules/sandbox_source.py:98`); `rules/series.py:4-5` records the production source as OPEN, and `recommendations/pipeline.py:233-260` reads `agents.ndjson`, `relations.ndjson`, `telemetry.ndjson` and `cost.ndjson` from one directory for rules, duplicates and usage.
- The worker raises `recommendations_data_dir_missing` unless `NS_WORKER_REC_DATA_DIR` is set (`runtime/factories.py:757-762`); `infra/demo/main.bicep:259-260` does not run the role because the hosted image has no such directory.
- Neither rules nor duplicates call `RecommendationCompute`: `TelemetryAnalytics` cannot group by agent (`Dimension` in `analytics/base/models.py:64-72` has no agent) and duplicates read presented relations through `GraphQuery` over an in-memory sandbox catalog (`pipeline.py:100-133`). The round 1 text claiming otherwise is removed here.
- The ledger carries no agent id (`ledger/models.py:123-153` `Observation`, `:174-209` `LedgerEntry`), so per-agent cost can only come from the archive's cost documents; telemetry carries `canonical_agent_id` (contract `telemetry_event.py:187`) and the archive keeps day-partitioned blobs `{customer}/{domain}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz` (`archive/serialize.py:35-54`).
- Quality is below the round 1 targets: duplicate precision 0.75 on held-out seed 5 against the 80% target, pilot-density latency detection 0/5, 3/5 and 3/5 with 1, 2 and 4 false alarms (`docs/evidence/G12/recommendations/README.md`, reproduced by `tests/integration/recommendations/measure_detection.py`); duplicate thresholds (`duplicates/config.py:62-64`) were tuned on the measured seeds.
- #133 bullets 1 and 2 are still true: `HitlReviewRouter.route` serialises only inside one process (`services/api/neurosphere_api/recommendations/review_hitl.py:54-79`, its docstring admits two processes can open two items) and `CosmosRecommendationStore.put` upserts then deletes copies in other partitions (`packages/core/neurosphere_core/recommendations/cosmos_store.py:125-142`), so two concurrent puts into different partitions can both survive or delete each other.

## Acceptance criteria
- [x] Given `NS_WORKER_REC_SOURCE=archive`, When the role starts, Then it needs no `NS_WORKER_REC_DATA_DIR`; Given `sandbox` (the default) or unset, Then behaviour and the existing `recommendations_data_dir_missing` and `recommendations_data_dir_invalid` errors are unchanged (`services/workers/tests/worker_roles/test_builders.py` still passes).
- [x] Given archive blobs of telemetry and cost documents for a cloud, customer and domains, When `ArchiveSeriesSource` loads a window, Then each in-scope agent in the live catalog gets one `AgentDay` per day with events, requests, errors, p50 and p95 latency, cost and `covered` computed with the same rules as `SandboxSeriesSource` (same fixtures give equal series: parity test).
- [x] Given a day on which no event from any agent of a source was archived, Then the day is `covered=False` and rules report unknown coverage, never zero usage; Given the archive listing hit its bound (`ArchiveReader.truncated`), Then the affected window is marked unknown and the run records `archive_truncated` instead of emitting `unused_agent`.
- [x] Given a blob for another customer, another cloud or a domain outside the scope, When the source loads, Then it is never read into a series (cross-customer leak test); a malformed blob is skipped and counted, never fatal.
- [x] Given `archive`, When the pipeline runs, Then agents, owners and duplicate candidates come from the live `CatalogRepository` through the read-only `GraphQuery` and `AgentLister`, token usage for right-sizing comes from archive cost documents (deduped by `dedupe_key`), and nothing is written to the catalog.
- [x] AMENDED to measured numbers (lane A alternative): held-out dense seeds 5, 13, 17 give duplicate precision 0.75, 0.60, 1.0 (recall 1.0); no score threshold separates the false pairs from true pairs on other seeds, and tuning on held-out seeds was refused; reason and numbers in the evidence README.
- [x] AMENDED to measured numbers: pilot density held-out seeds 5, 13, 17 detect 3, 2, 4 of 5 latency regressions with 4, 1, 0 false alarms and no silent miss (the assumption target of 3 of 5 and at most 1 false alarm holds on seed 17 only). Dense held-out seed 13 has one silent latency miss (OPEN).
- [x] Given two `HitlReviewRouter.route` calls for one recommendation racing in two router instances over one store, Then exactly one review item exists and both calls return its id (#133 bullet 1), via a deterministic item id and a create-only write.
- [x] Given two concurrent `CosmosRecommendationStore.put` calls with the same `recommendation_id` in different domain partitions, Then exactly one copy remains after both finish (#133 bullet 2), and the in-memory store follows the same rule.
- [x] No route, UI control or worker path executes a change; the executions refusal stays 409 `capability_unavailable` (unchanged round 1 behaviour).
- [ ] The hosted enablement and the real-stack run are written OPEN and handed to PRP-58.
- [ ] PRP exit: the touched suites pass, `verify-gates.ps1 -Mode full` is green, `python scripts/validate_planning.py` passes, the measured numbers are in `docs/evidence/G12/recommendations/README.md`.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required | sonnet, review required: the PRP changes what the worker reads from customer telemetry and a concurrency-sensitive write path |
| 2 | Production series source | Agent dimension on analytics adapters; per-agent hot aggregates; archive reader | Assumption A4 (owner direction): read the archive behind `NS_WORKER_REC_SOURCE=archive|sandbox`, default `sandbox`; no contract change, worker-only. A per-agent aggregate series now exists as PRP-49 for the map and is not used here |
| 3 | Where per-agent cost comes from | Ledger; archive cost documents | Archive cost documents (the ledger has no agent id, verified in `ledger/models.py`); the ledger is not read |
| 4 | Duplicates in archive mode | Keep the sandbox catalog; live catalog | Live `CatalogRepository` read-only through `RepositoryGraphQuery`; the sandbox path keeps `load_sandbox_catalog` |
| 5 | Archive window | Fixed; derived | ASSUMPTION: the last `RuleSet` lookback (max of the rule `lookback_days`) complete UTC days ending today, overridable by `NS_WORKER_REC_LOOKBACK_DAYS` |
| 6 | Archive listing is bounded | Index the archive now; flag truncation | Flag truncation as unknown coverage (honest, no new index); sizing on a real account stays OPEN (#133 archive-reader bullet, G07) |
| 7 | Deterministic review item id | Conditional create in the router; deterministic id | Deterministic UUIDv5 over `(customer, domain, recommendation id)` passed to `HitlService.open_item` through a new optional `item_id` argument; the store's create-only write turns a lost race into `StaleVersionError`, which the router resolves by reading the winner. This edits `packages/core/neurosphere_core/hitl/service.py` (one keyword argument), outside the ownership list in the assignment; flagged for the orchestrator |
| 8 | Duplicate ids across partitions | Transactions; deterministic winner | Cosmos has no cross-partition transaction: after the upsert, if copies exist, the copy in the lexicographically smallest `[customer, domain]` partition wins and every other writer deletes its own copy, never another's; ASSUMPTION: a record never legitimately moves domains |
| 9 | Held-out seeds | Reuse tuned seeds; new seeds | Tuning seeds 1, 2, 3, 7 (as measured in round 1); held-out seeds 5, 13, 17 chosen here and never used for tuning; the lists live in `measure_detection.py` |
| 10 | Pilot latency targets | None; fixed targets | ASSUMPTION in the criteria above; amend to measured numbers if unreachable without losing dense-profile detection (3/3) |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/recommendations/rules/series.py` - `AgentDay`, `AgentSeries`, the sync `AgentSeriesSource` protocol.
- `services/workers/neurosphere_workers/recommendations/rules/sandbox_source.py` - bucketing, dedupe, coverage rules the archive source must match.
- `services/workers/neurosphere_workers/recommendations/pipeline.py:233-330` and `load_sandbox_catalog`, `summarize_usage` - what `run_pipeline` reads from the directory.
- `services/workers/neurosphere_workers/runtime/archive_reader.py` - `ArchiveReader.names/read`, `truncated`, blob naming.
- `services/workers/neurosphere_workers/runtime/factories.py:311-325, 757-790` - `_archive_container`, `build_recommendations`; `runtime/settings.py:104-115` `RecommendationSettings`.
- `services/workers/neurosphere_workers/recommendations/duplicates/{config,detector,models}.py` - thresholds, `AgentLister`, the read-only guarantee.
- `tests/integration/recommendations/measure_detection.py` and `docs/evidence/G12/recommendations/README.md` - the measurement harness and recorded numbers.
- `services/api/neurosphere_api/recommendations/review_hitl.py` and `packages/core/neurosphere_core/hitl/{service.py,store.py}` - `open_item`, create-only `create`, `StaleVersionError`.
- `packages/core/neurosphere_core/recommendations/{cosmos_store.py,store.py}` - `put` and the in-memory parity.
- `services/workers/tests/worker_roles/test_builders.py` - existing role-config tests that must keep passing.

### Interfaces consumed
- `ArchiveReader` and the archive blob format (PRP-07 and PRP-29, shipped); `TelemetryEvent` and `CostRecord` contract models (PRP-01).
- `CatalogRepository.list_entities` and `RepositoryGraphQuery` (PRP-10, shipped), `CosmosCatalogRepository` (already built in `factories.py:438`).
- `HitlService.open_item` and `ReviewItem` (PRP-17, shipped).
- `PriceSnapshotStore` and `run_pipeline` signature (round 1, shipped).

### Interfaces provided
- `ArchiveSeriesSource.load(...)` (async classmethod returning a snapshot that satisfies the sync `AgentSeriesSource`), `archive_source.py` (new).
- Settings `NS_WORKER_REC_SOURCE` (`sandbox` default, `archive`) and `NS_WORKER_REC_LOOKBACK_DAYS`; PRP-58 sets them in hosted profiles.
- `run_pipeline` keeps its signature for the sandbox path and gains a sibling entry for archive inputs (item 2); PRP-58 and PRP-61 build against the stored `Recommendation` records only.
- `HitlService.open_item(..., item_id=None)` optional argument (additive).

### Patterns to match
- Bucketing, dedupe by `event_id` and `dedupe_key`, coverage by (source, day): `rules/sandbox_source.py:136-200`.
- Role builder with archive container and Cosmos: `runtime/factories.py:425-465` (aggregates builder) and `757-790`.
- Create-only write plus conflict mapping: `hitl_cosmos/store.py:181-190`.
- Held-out vs tuning separation in measurement scripts: `tests/integration/recommendations/measure_detection.py:68-100`.

### Gotchas
- `AgentSeriesSource.series` is synchronous but archive reads are async: load everything first (bounded) and serve the snapshot; never block the event loop.
- Archive documents are already redacted and pseudonymized; the source reads no payload bodies and logs no document content, only counts.
- `ArchiveReader.names` returns doc id to blob name for the whole customer (bounded by `max_blobs`, default 20000); filter by the day segments of the blob name before downloading.
- Round 1 measurements are UNVERIFIED in this session (not re-run); the first step of item 3 is to rerun `measure_detection.py` on the current tree.
- `services/api/openapi.json` is not expected to change; if a response model is touched, expect the component-rename trap and regenerate once.
- Tests using `next(iter(set))` flake on hash seed; sort before choosing (a round 1 duplicates test broke this way).
- `factories.py` `build_recommendations` is a Tier-1 body owned by this PRP in W13 only; do not edit other builders.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/recommendations/**
  - services/workers/neurosphere_workers/recommendations/**
  - services/api/neurosphere_api/recommendations/**
  - tests/integration/recommendations/**
  - docs/evidence/G12/recommendations/**
  - packages/core/tests/recommendations_cosmos/**
  - packages/core/neurosphere_core/hitl/service.py
tier1:
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/workers/neurosphere_workers/runtime/settings.py
must_not_touch:
  - packages/core/neurosphere_core/analytics/**
  - packages/core/neurosphere_core/aggregates/**
  - packages/contracts/**
  - infra/**
  - docker-compose.yml
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Order: 1 and 3 are `[P]` (no shared file); 2 after 1; 4 independent of the rest but sequenced after 2 only because both run the touched suites together; 5 last.

### Item 1 - Archive series source  [P]
- Deliverable: `rules/archive_source.py` with `ArchiveSeriesSource.load(reader, *, scope, agents, window)` reading archive blobs of the window (telemetry and cost messages), validating with the contract models, deduping, tracking truncation and skip counts, and exposing `series(...)` and `observed_window()` like the sandbox source; shared helpers factored without changing `SandboxSeriesSource` behaviour; export in `rules/__init__.py`.
- Owned files: `services/workers/neurosphere_workers/recommendations/rules/{archive_source,__init__}.py`, `rules/tests/test_archive_source*.py` (new).
- Must NOT touch: `rules/config.py`, `rules/evaluator.py` (item 3), `runtime/**`, `pipeline.py` (item 2).
- Depends on: none.
- Acceptance criteria: parity with `SandboxSeriesSource` on a fixture written to an in-memory fake container, uncovered day, truncation flag, cross-customer, cross-cloud, out-of-scope domain and malformed-blob tests from the criteria above.
- Tests: `rules/tests/test_archive_source_parity.py`, `test_archive_source_scope.py`, `test_archive_source_coverage.py` (fake container implementing `BlobReadable`).
- Pattern references: `rules/sandbox_source.py:98-200`, `runtime/archive_reader.py:55-130`, `rules/tests/support.py`.

### Item 2 - Pipeline inputs, settings and role wiring
- Deliverable: a pipeline entry that takes a prepared series source, a live catalog (`GraphQuery` plus `AgentLister`) and usage summaries from archive cost documents, reusing the sandbox path unchanged; `RecommendationSettings.source` and `lookback_days`; `build_recommendations` branching on the source (archive container via `_archive_container`, Cosmos catalog repository, no data-dir requirement for `archive`).
- Owned files: `recommendations/pipeline.py`, `services/workers/neurosphere_workers/runtime/factories.py` (`build_recommendations` body only), `runtime/settings.py` (new fields only), `recommendations/tests/test_pipeline_archive.py` (new), `services/workers/tests/worker_roles/test_builders.py` (new cases appended; existing ones unchanged).
- Must NOT touch: other builders in `factories.py`, `rules/**` (items 1 and 3), `duplicates/**` internals.
- Depends on: item 1.
- Acceptance criteria: the first two and fifth criteria above; an archive-mode run over fakes stores the same record kinds as the sandbox run on equivalent data; `archive` with a truncated listing stores no `unused_agent` and reports `archive_truncated` in `PipelineSummary`.
- Tests: `recommendations/tests/test_pipeline_archive.py`, `services/workers/tests/worker_roles/test_builders.py`, `tests/integration/recommendations/test_vertical_slice.py` (still green).
- Pattern references: `pipeline.py:233-330`, `factories.py:425-465`.

### Item 3 - Held-out recalibration  [P]
- Deliverable: rerun the harness first; tune duplicate thresholds and the latency noise policy on tuning seeds only, measure on held-out seeds, record both lists and the numbers; amend a target only with the measured numbers and the reason.
- Owned files: `recommendations/duplicates/{config,detector}.py`, `rules/{config,evaluator}.py`, `tests/integration/recommendations/measure_detection.py`, `docs/evidence/G12/recommendations/README.md`, tests beside the edited modules.
- Must NOT touch: `rules/archive_source.py`, `rules/__init__.py` (item 1), `sandbox/**` (PRP-03).
- Depends on: none.
- Acceptance criteria: the duplicate-precision and pilot-latency criteria above; the dense-profile results stay 3/3 on cost spike, latency and unused with zero unlabelled false positives; every number in the README is reproducible with `uv run python tests/integration/recommendations/measure_detection.py`.
- Tests: `rules/tests/test_latency_pooled.py`, `duplicates/tests/test_precision_sandbox.py` (extended with held-out seeds), `tests/integration/recommendations/test_vertical_slice.py`.
- Pattern references: `measure_detection.py:101-185`, `duplicates/config.py:55-95`.

### Item 4 - Review race and cross-partition duplicates (#133)
- Deliverable: `HitlService.open_item(item_id=...)`; `HitlReviewRouter` derives the id, treats `StaleVersionError` `review_item_exists` as "someone else won" and returns the existing item; `CosmosRecommendationStore.put` and the in-memory store apply the smallest-partition-wins rule from Clarification 8.
- Owned files: `services/api/neurosphere_api/recommendations/review_hitl.py`, `packages/core/neurosphere_core/hitl/service.py`, `packages/core/neurosphere_core/recommendations/{cosmos_store,store}.py`, `packages/core/tests/recommendations_cosmos/**`, `services/api/neurosphere_api/recommendations/tests/**`.
- Must NOT touch: other `hitl/` modules, the HITL Cosmos store, `neurosphere_api/actions/**`.
- Depends on: none (sequenced last among code items to run suites together).
- Acceptance criteria: the two #133 criteria above using two router instances over one in-memory HITL store and two store instances over one fake Cosmos container; existing idempotency tests unchanged.
- Tests: `packages/core/tests/recommendations_cosmos/test_recommendation_conformance.py` (extend), `test_cross_partition_put.py` (new), `packages/core/tests/hitl/test_open_item_id.py` (new), `services/api/neurosphere_api/recommendations/tests/test_review_race.py` (new); the existing `services/api/tests/runtime_planes/test_review_hitl.py` must keep passing and is read-only here.
- Pattern references: `hitl_cosmos/store.py:181-190`, `cosmos_store.py:125-142`.

### Item 5 - Integration and close-out
- Deliverable: Tier-3 regeneration (`python scripts/prp_status.py --write`, the index build, `openapi.json` drift check), the evidence README final, completion note with "Env vars for the operator" (`NS_WORKER_REC_SOURCE`, `NS_WORKER_REC_LOOKBACK_DAYS`), #133 left open with a comment listing the evaluation half and the archive-reader sizing bullet; follow-up issue for the archive listing index if sizing demands it.
- Owned files: this PRP file, `docs/evidence/G12/recommendations/**`, regenerated `PRPs/PRP-MASTER-neurosphere.md` status table and `PRPs/INDEX.md`.
- Must NOT touch: `docs/RESEARCH-AND-GATES.md` rows other than via PRP-64.
- Depends on: items 1-4.
- Acceptance criteria: gates below pass; hosted enablement written OPEN.
- Tests: none new.
- Pattern references: `PRPs/reference/parallel-build-reference.md` section 6.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/workers/neurosphere_workers/recommendations services/api/neurosphere_api/recommendations packages/core/neurosphere_core/pricing packages/core/neurosphere_core/recommendations packages/core/tests/recommendations_cosmos packages/core/tests/hitl services/workers/tests/worker_roles services/api/tests/runtime_planes/test_review_hitl.py tests/integration/recommendations services/api/tests/test_openapi_drift.py
uv run python tests/integration/recommendations/measure_detection.py
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```
Frontend (only if a UI file is touched, none expected): `pnpm --filter @neurosphere/frontend test`. There is no `make seed`; the sandbox seed is `scripts/sandbox/sbx_cli.py seed --data-dir`.

## Migration and rollback
No schema change and no new container. `NS_WORKER_REC_SOURCE` defaults to `sandbox`, so existing compose and hosted behaviour is unchanged until an operator sets `archive`; rollback is unsetting it. The deterministic review item id applies to items opened after the change; items opened earlier keep random ids and the router still finds them by `subject_ref` (existing lookup stays as the read path). The partition rule cleans duplicate recommendation copies only when a later `put` runs; no backfill.

## Live and open gates
- Hosted enablement of the recommendations role and a real-stack run against Cosmos and the real archive: OPEN, operator approval and a deploy needed; handed to PRP-58.
- Archive listing sizing on a real storage account and RU cost of the recommendation store: OPEN (G07, G12).
- G04 price-sheet coverage and G01 Government projections: unchanged and OPEN; Government pricing stays unavailable.
- No live script exists for this PRP; no paid call is made.

## NOT building
- Execution, approvals or any change to a target system (PRP-17); the 409 executions refusal stays.
- An agent dimension on the analytics adapters or the hot aggregates, and any use of `RecommendationCompute` for agent rules.
- Hosted infrastructure for the role (PRP-58), pricing refresh, evaluation changes (PRP-16), the `evaluation_id` half of #133.
- An `ArchiveTraceReader` or archive index.
- Any claim of realized savings.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 5, 8 and 10 are labelled assumptions)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-15-round2-production-series | ArchiveSeriesSource + SeriesAccumulator shared with sandbox; parity, scope, coverage tests |
| 2 | merged | prp-15-round2-production-series | run_pipeline_archive, NS_WORKER_REC_SOURCE and NS_WORKER_REC_LOOKBACK_DAYS, build_recommendations branch; compose-only checks not run |
| 3 | merged | prp-15-round2-production-series | no threshold change; held-out seeds 5,13,17 measured, targets amended to measured numbers (README); dup precision 0.75, 0.60, 1.0; pilot latency 3, 2, 4 of 5, FA 4, 1, 0 |
| 4 | merged | prp-15-round2-production-series | deterministic UUIDv5 review item id via HitlService.open_item(item_id) (outside Ownership listing in assignment, allowed by PRP Ownership); smallest-partition-wins put in Cosmos and in-memory stores; winner also deletes larger copies (deviation from Clarification 8 text, needed to converge) |
| 5 | merged | prp-15-round2-production-series | Tier-3 regeneration, completion note, changelog fragment, reviewer follow-ups |

## Completion note (filled at ship)
- Date, PR, merged commits: 2026-11-15, PR #281 (squash merge of branch `prp-15-round2-production-series`).
- Deviations from the blueprint and why: item 4 also deletes the larger-partition copies after a `put` (needed so two concurrent puts converge on one copy; differs from the text of Clarification 8). `HitlService.open_item(item_id=...)` lives in `packages/core/neurosphere_core/hitl/service.py`, which the PRP Ownership allows. Item 3 changed no threshold: held-out seeds 5, 13 and 17 were measured and the two targets amended to the measured numbers, as the blueprint permits. No `[serial-after]` item exists in this PRP.
- Descoped items: none. Reviewer follow-ups done in the close-out commit: store docs now state the silent-discard rule (`recommendations/store.py` module docstring); `test_duplicate_detection_never_searches` pins that `run_pipeline_archive` never searches; a comment in `archive_source.py` explains why `add_cost` returning True for lower-priority duplicates is harmless (`summarize_usage_docs` dedupes by `dedupe_key`).
- Measured results (tuning seeds, held-out seeds, dense and pilot density): see `docs/evidence/G12/recommendations/README.md`. Duplicate precision on held-out dense seeds 5, 13, 17 is 0.75, 0.60, 1.0 (recall 1.0). Pilot density latency regressions detected 3, 2, 4 of 5 with 4, 1, 0 false alarms; dense held-out seed 13 has one silent latency miss (OPEN).
- OPEN gates (hosted enablement, archive sizing, G04, G01 Government): hosted enablement of the role and a real-stack run against Cosmos and the real archive (PRP-58); archive listing sizing and RU cost (G07, G12); G04 price sheet coverage; G01 Government projections; compose-only checks of the archive path were not run in this session; the dense seed 13 silent latency miss.
- Env vars for the operator (`NS_WORKER_REC_SOURCE`, `NS_WORKER_REC_LOOKBACK_DAYS`): `NS_WORKER_REC_SOURCE` (`sandbox` default, or `archive`; `archive` needs no `NS_WORKER_REC_DATA_DIR`) and `NS_WORKER_REC_LOOKBACK_DAYS` (complete UTC days of archive window). `.env.example` was not edited; the operator adds both.
- Follow-up issue numbers: #133 stays open (evaluation_id half in PRP-16, archive reader sizing bullet); tracking issue #231 closed by this PR. Store note: a later `put` of an id that already exists in a smaller `[customer, domain]` partition is silently discarded (documented in the store docstring).
- Product check (can an operator see recommendations about their own agents without editing files?): not yet in a hosted environment. With `NS_WORKER_REC_SOURCE=archive` the role reads the live catalog and the archive, but enabling it in the hosted deployment is PRP-58 and OPEN.

## History
- Round 1 shipped as PR #79 (merged 2026-10-19; seven items including the fix-forward latency rule): rules engine, duplicate candidates, cost projection, recommendations API and UI, the worker role over sandbox files, `HitlReviewRouter` and `CosmosRecommendationStore` wiring afterwards (PRP-29).
- The 2026-11-04 audit reopened it: sandbox-only input, empty hosted page, detection quality below target (duplicate precision 0.75 held-out, pilot latency 0/5 on seed 3), frontend e2e on the mock API only.
- The 2026-11-14 lane A audit found the `run_pipeline` hosting claim stale (`factories.py:757`), the `RecommendationCompute` claims false (rules and duplicates never call it), `make seed` nonexistent, a wrong `pnpm --filter frontend` and a non-compose `-m integration` command.
- This rewrite removes the round 1 blueprint, wire-contract notes, execution table and audit section, keeps the shipped behaviour as context only, and scopes round 2 to the archive series source, held-out recalibration and the two #133 bullets. Hosted enablement moved to PRP-58.
- The original text is in git history (`git log --follow PRPs/backlog/PRP-15-recommendations-engine.md`).
