---
name: PRP-49-per-agent-aggregates-and-map-metrics
status: backlog
priority: P2
order: 37
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 3
ns: NS-05, NS-01
depends_on: [PRP-18-live-map-and-session-replay]
wave: W16
branch: prp-49-per-agent-aggregates
allow_parallel: true
issues: []
---

# PRP-49: Per-agent aggregates and map metrics

## Goal
Make the live map's node metrics real. Today every agent and model node on `/map` carries `null` tokens, frequency, p95 latency and `unknown` health because the hot aggregates are per domain and know nothing about agents or models. The owner decided on 2026-11-14 that per-node metrics come from a new per-agent aggregate series. This PRP adds that series end to end: contributions carry the agent and model dimension, the aggregates worker rolls them up per hour and per day into a new `subject` metric, the aggregate readers expose a bounded batch read, the viewport service fills `NodeMetrics` from it, the realtime delta source pushes changed nodes, and the map client merges a metrics-only delta without overwriting labels. Unknown stays `null` and `unknown`, never 0. It is for analysts and operators reading the map, and for PRP-64, which re-measures map performance. It runs in W16 because it needs the PRP-18 edge-batched viewport service and must not collide with PRP-45, which holds the worker composition bodies that wave.

Out of scope: the viewport edge batching, the delta pump and the replay guard (PRP-18, shipped one wave earlier); backfilling subject series for events ingested before this change (not built, see Migration); per-node metrics in the table view beyond what the shared API already returns; a per-person series (people stay pseudonymized and metric-less); the analytics adapters and the agent grain for recommendations (PRP-11 and PRP-15 use the archive); edits to worker `runtime/factories.py` builder bodies (PRP-45 owns them this wave).

## Why
- Node metrics are null by construction: `services/api/neurosphere_api/map/service.py:200` (`node_for`) fills only `context_size` for a `ModelDeployment`, and its module docstring says per-node metrics "are not available from the hot aggregates".
- Realtime deltas are one domain-level cluster node: `services/api/neurosphere_api/realtime/source.py:1-20,103-143` builds a single `DeltaNode` of kind `cluster` from the domain's latency and error series; `tokens` and `context_size` stay `None` and `edges` are empty.
- The aggregate model has no agent or model grain: `packages/core/neurosphere_core/aggregates/models.py:150-157` `EventFact` holds only `duration_ms` and `outcome`, the metric list is `Literal["cost", "latency", "errors", "coverage", "reconciliation"]` (line 43) and series are per domain; the mapping from telemetry drops everything else (`services/workers/neurosphere_workers/aggregates/mapping.py:150-167`).
- The telemetry contract already carries the dimension: `canonical_agent_id`, `provider`, `model`, `model_version`, `duration_ms`, `outcome` and `token_breakdown` (`packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:187-255`).
- The existing reader cannot serve a viewport: `AggregateReader.query` caps `max_series` at 50 (`aggregates/store.py:31`), while a viewport carries up to 2000 nodes (`map/dependencies.py:41`), so a new batch read keyed by subject is required.
- The map client would overwrite what it cannot see: `frontend/src/features/map/mapGraph.ts:221-253` merges `label`, `clusterId` and `memberCount` from every delta node into an existing node, so a metrics-only delta from the server would blank a human label unless the merge changes.

## Acceptance criteria
- [ ] Given a telemetry `model_call` event with `canonical_agent_id`, `provider`, `model`, `duration_ms`, `outcome` and `token_breakdown`, When the aggregates worker applies it, Then the stored contribution carries those fields and the bucket rollup writes `subject` documents for the series `agent:<id>` and `model:<provider>/<model>` at the hour and day grains.
- [ ] Given events with a missing agent id, duration, outcome or tokens, Then the subject point keeps those as unknown (`None`, `complete=False`), counts them in `missing_count` or `unknown_outcome_count`, and never turns them into 0 (null-not-zero test beside `test_nulls_not_zero.py`).
- [ ] Given the same contribution applied twice, or a bucket rebuilt from the same contributions, Then the subject documents are equal and a one-event rebuild writes only the changed documents (counted-writes test on the fake container).
- [ ] Given a bucket with more distinct subjects than the per-bucket cap, Then the documents kept are deterministic (sorted by series key), the overflow is logged by count only, and no reader returns a partial point as complete.
- [ ] Given a viewport request for a domain with agent and model entities and subject points in the last two hour buckets, When the map service builds nodes, Then each agent and model node carries `frequency`, `latency_p95_ms`, `tokens` and `health` from its latest point, and a node with no point or an unknown value keeps `null` and `unknown` (never 0).
- [ ] Given the subject read fails or times out, When the viewport is built, Then nodes keep unknown metrics, `coverage.state` is `partial` and the response is still 200; given a caller scoped away from the domain, Then the request is refused before any subject read (scope test).
- [ ] Given a person node, a cluster node or an entity with no subject mapping, Then its metrics stay unknown and no subject read is issued for it.
- [ ] Given hourly points for several agents of one domain, When the realtime source polls, Then the delta carries the domain cluster node plus at most `MAX_DELTA_SUBJECT_NODES` agent and model nodes (those with the newest points), with unknown values `None`; the cache TTL and digest behaviour are unchanged.
- [ ] Given a delta node whose id already exists in the map graph, When the client applies it, Then only `metrics` change (label, cluster and member count are kept); a delta node of kind agent, sub_agent, model or source whose id is not in the graph is ignored; the existing domain cluster upsert still works (vitest).
- [ ] The dashboards, reconciliation, federation and copilot-evidence readers that already use `AggregateReader` still pass unchanged (cross-suite run).
- [ ] `services/api/openapi.json` does not change (drift test green); `PRP-18`'s edge batching call is not reintroduced.
- [ ] Map performance on operator hardware with real subject data is written OPEN and handed to PRP-64.
- [ ] PRP exit: the touched pytest and vitest suites pass, `verify-gates.ps1 -Mode full` is green, `python scripts/validate_planning.py` passes.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Source of per-node metrics | Compute from ledger or archive on request; per-agent aggregate series | Owner decision 2026-11-14: a new per-agent aggregate series in the aggregates worker |
| 2 | Metric shape | New series keys under existing metrics; a new metric | A new metric `subject` (new document model `SubjectPoint`, series keys `agent:<canonical id>` and `model:<provider>/<model>`), so existing `latency` and `errors` series keep exactly their keys and the 50-series ceiling readers are untouched |
| 3 | Read path | Raise `max_series`; a batch read | A separate runtime-checkable reader protocol `SubjectMetricsReader` with `latest_subject_points(customer, domain, kind, keys, window)` chunked at 100 keys per Cosmos query; `AggregateReader` is not changed. The map service uses it only when the reader implements it |
| 4 | Frequency | Events; requests | `frequency` is the number of `model_call` spans in the latest hour bucket (the only span kind contributions count); `tokens` is input plus output of events whose count is known, `None` when none is known; `latency_p95_ms` from known durations only |
| 5 | Health | New thresholds; reuse | Same thresholds and meaning as the realtime source (degraded at 0.05, failing at 0.25 error rate); defined once as constants beside `SubjectPoint` and pinned equal to the `RealtimeSettings` defaults by a test; unknown error rate gives `unknown` |
| 6 | Model matching | Deployment id; provider and model labels | ASSUMPTION: telemetry carries provider and model labels, not deployment ids, so a `ModelDeployment` node matches by `(provider, model_name)` compared case-insensitively; every deployment of one model shows the model's metrics, and this is documented as model-level, not deployment-level |
| 7 | Agent matching | Canonical id | `Agent` entity id equals telemetry `canonical_agent_id` (the sandbox generator and the PRP-15 rules already join on it) |
| 8 | Series growth | Unbounded; capped | ASSUMPTION: at most 5000 subject series per (customer, domain, grain, bucket) (`MAX_SUBJECT_SERIES_PER_BUCKET`), kept in sorted key order; the figure is a guard chosen here, not a measurement, and real document growth is OPEN (G07, G12) |
| 9 | Absent point | Zero; unknown | Unknown (`null`): no point in the last two hour buckets means "not observed", not "idle" |
| 10 | Realtime node labels | Server resolves labels from the catalog; client keeps labels | Client keeps labels on merge (item 5); the server's delta node label is the last segment of the canonical id and is only used if the id is new, which the client now ignores for non-cluster kinds |
| 11 | Historic data | Backfill; none | No backfill: contributions stored before this change lack the dimension, so their subject values stay unknown until they age out of the window |
| 12 | Model and review | sonnet/none; sonnet/required | sonnet, review required (scope-sensitive read path and a change to every aggregate rebuild) |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/aggregates/models.py` - `EventFact`, `Metric`, `AggregateDoc`, `aggregate_doc_id`, `UNASSIGNED_DOMAIN`.
- `packages/core/neurosphere_core/aggregates/store.py` and `cosmos.py` - `AggregateReader`, `select_series`, `replace_bucket`, the Cosmos queries (single partition per customer).
- `services/workers/neurosphere_workers/aggregates/{mapping,rollups,handler}.py` - `contribution_from_event`, `rollup_bucket`, the rebuild-per-bucket handler.
- `services/api/neurosphere_api/map/service.py` - `_Builder.node_for`, `build_viewport`, `coverage` (as changed by PRP-18; re-read before editing).
- `services/api/neurosphere_api/realtime/source.py` and `realtime/settings.py:18-45` - `AggregateDeltaSource`, health thresholds, poll interval.
- `services/api/neurosphere_api/map/dependencies.py` - `get_aggregate_reader`, `ViewportLimits`.
- `services/api/tests/map/map_api_helpers.py` and `services/api/tests/realtime/rt_helpers.py` - harnesses to extend.
- `services/workers/neurosphere_workers/aggregates/tests/{support,test_nulls_not_zero,test_aggregates_idempotent}.py` - fixtures and idempotency pattern.
- `frontend/src/features/map/mapGraph.ts:210-385` and `frontend/src/features/map/map.test.tsx:540-560` - `upsertNodes`, `applyDelta` and an existing delta test.
- `packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:150-260` - the event fields used.

### Interfaces consumed
- PRP-18 (shipped one wave earlier): the edge-batched `build_viewport` in `map/service.py` and the unchanged `GraphQuery`; `EdgesAmongQuery` is not used here.
- PRP-14 aggregates (shipped): `AggregateStore`, `Contribution`, `rollup_bucket`, `AggregateProjection`; the worker role `aggregates` is built by `factories.py` and is not edited.
- `AggregateReader.status` for lag and coverage; `IdentityScope` and `data.read` checks in the map router (unchanged).

### Interfaces provided
- `neurosphere_core.aggregates.SubjectPoint`, `subject_series_key(kind, ...)`, `SubjectMetricsReader`, `health_for_error_rate(...)`, constants `MAX_SUBJECT_SERIES_PER_BUCKET`, `HEALTH_DEGRADED_ERROR_RATE`, `HEALTH_FAILING_ERROR_RATE` (new `aggregates/subject.py`).
- Metric name `subject` in `Metric` and in the Cosmos aggregate documents (`c.metric = 'subject'`); additive optional fields on `EventFact`: `agent_id`, `provider`, `model`, `input_tokens`, `output_tokens`.
- `MAX_DELTA_SUBJECT_NODES` in `realtime/source.py`; the client merge rule for delta nodes (PRP-64 and later map work build against it).

### Patterns to match
- Pure rollup helpers with explicit null handling: `rollups.py:44-57` (`known_sum`, `percentile`) and the `_latency_and_errors` structure at `rollups.py:156-185`.
- Deterministic ids and idempotent rebuild: `models.py:aggregate_doc_id`, `handler.py` module docstring.
- Optional-capability check on a reader: `map/dependencies.py:get_aggregate_reader` plus an `isinstance` against a runtime-checkable protocol.
- Null-not-zero tests: `aggregates/tests/test_nulls_not_zero.py`.
- Fake Cosmos container for store tests: `packages/core/tests/recommendations_cosmos/{cosmos_fake,fake_container}.py`.

### Gotchas
- Rebuild amplification: the handler rebuilds a bucket from all its contributions on every applied event and `replace_bucket` upserts every document; with thousands of subject documents that multiplies writes. Item 1 makes `replace_bucket` skip unchanged documents; the RU cost on a real account is unmeasured (G07, G12).
- `EventFact` and `Contribution` use `extra="forbid"`: only add optional fields with defaults so stored contributions keep validating; do not rename existing ones.
- `AggregateDoc` is a discriminated union on `metric`; adding `SubjectPoint` means every `AGGREGATE_ADAPTER.validate_python` caller now accepts it. Search the repo for exhaustive `match doc.metric` or `isinstance` ladders and run dashboards, reconciliation, federation and copilot-evidence suites together.
- Only `model_call` spans are contributions (`mapping.py:150-153`); an `agent_run` parent span is not counted, so `frequency` means model calls.
- `canonical_agent_id` can be absent on an event: such events add to no agent series (they still add to the domain series).
- The viewport must keep the "edge only if both endpoints are nodes" rule from PRP-18; this PRP changes node metrics only.
- Do not edit worker `runtime/factories.py` builder bodies (PRP-45 owns them in W16); the aggregates builder already constructs `AggregateProjection`, which is all that is needed.
- A frontend change here follows PRP-18's frontend work (W13): rebase and re-read `mapGraph.ts` and `hooks.ts` first.
- Tests using `next(iter(set))` flake on hash seed; sort before choosing.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/tests/aggregates_subjects/**
  - services/workers/neurosphere_workers/aggregates/**
  - services/api/neurosphere_api/map/service.py
  - services/api/neurosphere_api/realtime/source.py
  - services/api/tests/map/test_node_metrics.py
  - services/api/tests/realtime/test_subject_deltas.py
  - frontend/src/features/map/mapGraph.ts
  - frontend/src/features/map/mapGraphDelta.test.ts
tier1: []
tier2_appends: []
must_not_touch:
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/runtime/builders/**
  - services/api/neurosphere_api/routers.py
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/**
  - pyproject.toml
  - uv.lock
  - frontend/package.json
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Order: 1, then 2 and 3 and 4 in parallel (they share no file once item 1 has merged), item 5 independent of the backend items, item 6 last. Items 3 and 4 both read the new reader protocol: they only import it.

### Item 1 - Subject series model, reader protocol and store support
- Deliverable: `aggregates/subject.py` with `SubjectPoint` (metric `subject`, fields `subject_kind` agent or model, `subject_key`, `event_count`, `missing_duration_count`, `unknown_outcome_count`, `error_count`, `error_rate`, `p50_ms`, `p95_ms`, `input_tokens`, `output_tokens`, `tokens_known_count`), `subject_series_key`, `SubjectMetricsReader`, health helper and constants; `Metric` and `AggregateDoc` extended; additive `EventFact` fields; `InMemoryAggregateStore` and `CosmosAggregateStore` implement `latest_subject_points` (bounded keys, window, newest point per key, truncation flag) and `replace_bucket` skips unchanged documents; exports in `aggregates/__init__.py`.
- Owned files: `packages/core/neurosphere_core/aggregates/{models,store,cosmos,subject,__init__}.py`, `packages/core/tests/aggregates_subjects/**` (new directory with `__init__.py`).
- Must NOT touch: `catalog/**`, `ledger/**`, the existing `latency` and `errors` document shapes.
- Depends on: none.
- Acceptance criteria: round trip of a `SubjectPoint` through `AGGREGATE_ADAPTER`; `latest_subject_points` returns only the caller's customer and domain, at most 100 keys per Cosmos query and at most the requested key count, newest bucket wins; old stored contributions without the new fields still validate; unchanged-document skip proven by a write counter.
- Tests: `packages/core/tests/aggregates_subjects/test_subject_models.py`, `test_subject_reader_inmemory.py`, `test_subject_reader_cosmos.py` (fake container), `test_replace_bucket_skips_unchanged.py`.
- Pattern references: `aggregates/models.py:216-300`, `aggregates/cosmos.py:60-95`, `recommendations_cosmos/cosmos_fake.py`.

### Item 2 - Worker mapping and rollup
- Deliverable: `contribution_from_event` copies the agent, provider, model and token counts into `EventFact`; `rollup_bucket` adds `_subjects` producing `SubjectPoint` documents per agent and per model with null discipline, the per-bucket cap and sorted order; the handler path is unchanged.
- Owned files: `services/workers/neurosphere_workers/aggregates/{mapping,rollups}.py`, `services/workers/neurosphere_workers/aggregates/tests/test_subject_mapping.py` and `test_subject_rollups.py` (new).
- Must NOT touch: `handler.py` behaviour, `runtime/factories.py`, `sources.py`.
- Depends on: item 1.
- Acceptance criteria: the first four acceptance criteria above; existing `test_rollups.py`, `test_aggregates_idempotent.py` and `test_nulls_not_zero.py` pass unchanged.
- Tests: the new files plus the existing aggregates test directory in one run.
- Pattern references: `rollups.py:156-185`, `mapping.py:150-167`, `aggregates/tests/support.py`.

### Item 3 - Map service node metrics
- Deliverable: `build_viewport` collects the agent and model entities of the response, asks the reader (when it implements `SubjectMetricsReader`) for their latest points in the last two hour buckets in one bounded call, and `node_for` fills `NodeMetrics` (`frequency`, `latency_p95_ms`, `tokens`, `health`); read failures degrade to unknown metrics and `partial` coverage; `context_size` behaviour is kept.
- Owned files: `services/api/neurosphere_api/map/service.py`, `services/api/tests/map/test_node_metrics.py` (new).
- Must NOT touch: `map/router.py`, `map/models.py`, `map/dependencies.py`, `GraphQuery` and the edge path from PRP-18.
- Depends on: item 1.
- Acceptance criteria: the node-metrics, failure-degrades, scope and person/cluster criteria above; viewport response schema unchanged (drift test); a 2000-node page issues at most 20 subject queries.
- Tests: `services/api/tests/map/test_node_metrics.py`, existing `test_node_budget.py` and `test_scope_and_pseudonyms.py` unchanged.
- Pattern references: `map/service.py:200-216,299-402`, `tests/map/map_api_helpers.py`.

### Item 4 - Realtime delta source
- Deliverable: `AggregateDeltaSource.poll` also reads the newest subject points of the domain (bounded) and emits up to `MAX_DELTA_SUBJECT_NODES` agent and model `DeltaNode`s with metrics, keeping the domain cluster node, the cache and the digest rules; coverage logic unchanged.
- Owned files: `services/api/neurosphere_api/realtime/source.py`, `services/api/tests/realtime/test_subject_deltas.py` (new).
- Must NOT touch: `realtime/gateway.py`, `settings.py`, `registry.py`, `router.py`, `runtime/builders/data.py` (the constructor already receives the reader).
- Depends on: item 1.
- Acceptance criteria: the delta criterion above; a reader without `SubjectMetricsReader` yields the unchanged one-node delta; per-session scope checks in the gateway tests still pass.
- Tests: `services/api/tests/realtime/test_subject_deltas.py` plus the existing realtime directory.
- Pattern references: `realtime/source.py:103-170`, `tests/realtime/rt_helpers.py`.

### Item 5 - Client merge of metrics-only deltas
- Deliverable: `MapGraph.applyDelta` merges only `metrics` into an existing non-cluster node, ignores unknown agent, sub_agent, model and source ids, and keeps upserting the domain cluster node as before.
- Owned files: `frontend/src/features/map/mapGraph.ts`, `frontend/src/features/map/mapGraphDelta.test.ts` (new).
- Must NOT touch: `hooks.ts`, `realtime.ts`, `MapPage.tsx` (PRP-18 W13 files), `frontend/tests/mock-api/server.ts`, visual baselines.
- Depends on: none (semantic pair of item 4).
- Acceptance criteria: the client criterion above; existing `map.test.tsx` cases still pass.
- Tests: `pnpm --filter @neurosphere/frontend test -- mapGraphDelta`.
- Pattern references: `mapGraph.ts:221-256,378-384`, `map.test.tsx:540-560`.

### Item 6 - Integration and close-out
- Deliverable: cross-suite run (dashboards, reconciliation, federation, copilot evidence, map, realtime), Tier-3 regeneration (`openapi.json` drift check, `docs/reference` if the generator reports a change, `python scripts/prp_status.py --write`, index build), completion note with the OPEN items, and a note for PRP-64 that map perf needs a re-measure with subject data.
- Owned files: this PRP file, regenerated `PRPs/PRP-MASTER-neurosphere.md` status table and `PRPs/INDEX.md`.
- Must NOT touch: `docs/RESEARCH-AND-GATES.md`, evidence under `docs/evidence/G07/**` (PRP-64).
- Depends on: items 1-5.
- Acceptance criteria: gates below pass; OPEN gates recorded.
- Tests: none new.
- Pattern references: `PRPs/reference/parallel-build-reference.md` section 6.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/aggregates_subjects services/workers/neurosphere_workers/aggregates services/api/tests/map services/api/tests/realtime services/api/neurosphere_api/dashboards services/api/neurosphere_api/reconciliation services/api/tests/federation_api services/workers/tests/federation_worker services/api/tests/copilot_api tests/integration/map tests/load/map_freshness services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```
`tests/integration/map` and `tests/load/map_freshness` need the compose emulators (`docker compose up -d --wait`, `127.0.0.1`, one compose session at a time); if they are skipped, say so in the completion note.

## Migration and rollback
Additive only. `EventFact` gains optional fields and the aggregate container gains documents with `metric = 'subject'`; no container or index change and no data migration. Contributions stored before the change have no dimension, so their subject values stay unknown until they leave the 90-day (day) and 14-day (hour) windows; no backfill is built. Rollback: revert the branch; leftover `subject` documents are ignored by every existing reader (they filter by metric) and are removed by the normal prune when they age out. The map keeps working with unknown metrics if the subject read is absent or fails, so no flag is needed.

## Live and open gates
- Real Cosmos behaviour of the new documents (RU per rebuild, `IN` query cost, 429s) and document growth at hosted scale: OPEN (G07, G12); the emulator has no RU accounting.
- Map frame rate and viewport latency with real subject data on operator hardware: OPEN, handed to PRP-64 (lane B unit 18-R2-C).
- Hosted verification that agent and model nodes show live metrics: OPEN until PRP-58 has the hosted data path running; requires an operator-approved deployment.

## NOT building
- A subject series for people, domains or tools; per-deployment (rather than per-model) metrics.
- Backfill of past events, a ledger-based or archive-based on-request metric computation, or a query-text analytics path.
- New map routes, wire-contract changes or `openapi.json` changes.
- Edits to `GraphQuery`, the catalog or the edge batching (PRP-18, PRP-43).
- Changes to worker composition or role settings (PRP-45).
- Alerting on node health.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 6, 8 and 10 are labelled assumptions)

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
- Date, PR, merged commits:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (real Cosmos cost and growth, map perf re-measure, hosted check):
- Env vars for the operator (none expected):
- Follow-up issue numbers:
- Product check (does a node on `/map` show live metrics without editing files?):
