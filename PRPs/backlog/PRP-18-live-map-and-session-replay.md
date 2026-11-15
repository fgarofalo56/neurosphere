---
name: PRP-18-live-map-and-session-replay
status: backlog
priority: P2
order: 27
review: required
created: 2026-10-08
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 3
ns: NS-05
depends_on: []
wave: W13
branch: prp-18-round2-map-edge-batching
allow_parallel: true
issues: [233]
absorbs: P3.1
---

# PRP-18: Live map and session replay (round 2)

## Goal
Close the round-1 gaps that need no decision and no operator hardware: replace the per-node edge walk of the map viewport with one bulk "edges among these ids" call so a 2000-node page is usable, harden the replay read-only guard so it also catches relative imports and dynamic imports, fix the gateway pump cadence, and clear the replay, table and mock-API nits the round-1 reviewers filed. It is for analysts and auditors using `/map`, `/map/table` and `/replay/traces`, and for the reviewer who must trust that replay can never invoke an action. It runs in W13 because the viewport fix extends the PRP-10 graph package and the mock API server is a W13 Tier-1 file held by this PRP.

Out of scope: per-node metrics from a per-agent aggregate series (PRP-49); the 30 fps p5 criterion reword and the headed re-measure on operator hardware (PRP-64); reveal-people-with-audit, an `ArchiveTraceReader` index and the cross-replica revocation end-to-end test (not built, filed as issues in the close-out); catalog hardening in `catalog/**` outside `catalog/graph/` (PRP-43).

## Why
- `services/api/neurosphere_api/map/service.py:227-263` (`edges_among`) calls `GraphQuery.neighbors` once per node in chunks of 16 (`_EDGE_CHUNK`, line 56); a 2000-node page took about 15 s in memory (PRP-18 round-1 follow-up, lane-b 18-R2-A).
- `services/api/tests/replay/test_replay_readonly.py:21-30` (`_imports`) ignores `ImportFrom.level` and never inspects `importlib` or `__import__` calls, so a relative import of an executor would pass the guard.
- `services/api/neurosphere_api/realtime/gateway.py:376-381` (`_pump_loop`) sleeps `poll_interval_seconds` only, so scope refresh cadence (`effective_refresh_seconds`, `realtime/settings.py:43-51`) holds only when poll is at most half the revocation TTL; the slow-consumer close (`gateway.py:447`, reason `slow_consumer`) and close codes 1009/1011/1013 have no test.
- `frontend/src/features/map/hooks.ts:58-79` forwards every delta with no guard after a 4403 revoke, so a delta racing the close can re-add nodes that `mapGraph.ts:353` just cleared.
- `services/api/neurosphere_api/replay/assemble.py:122-127` writes the missing-parent gap detail as "parent span is outside this domain and was withheld", which tells a caller another domain has spans; `frontend/src/features/replay/TraceTree.tsx:69` keys gap badges by reason only (duplicates); `frontend/tests/mock-api/server.ts:1344` answers an unknown trace with a bare `{ error }` 404, not problem+json.

## Acceptance criteria
- [ ] Given a catalog of 2000 in-scope nodes and 4000 edges, When the viewport service builds a page, Then edges come from one bulk call (call count asserted, not per node) and the in-memory page completes in under 3 s (test with a recorded wall time; the threshold is ASSUMPTION A-1 below).
- [ ] The bulk call returns exactly the edge set the per-node walk returned for the same ids (parity test over locks, overrides, hidden edges and an out-of-scope other endpoint), never includes an edge with an endpoint outside the caller's scope, and reports truncation when an edge or time budget is hit.
- [ ] `RepositoryGraphQuery` still satisfies `GraphQuery`; a graph that lacks the bulk method falls back to the per-node walk (test with a stub graph).
- [ ] `test_replay_readonly.py` fails on a fixture module that uses `from . import actions_x`, `from .. import executor`, `importlib.import_module("neurosphere_api.actions")` or `__import__("neurosphere_core.actions")` (negative-fixture tests), and still passes on the real replay package.
- [ ] The gateway pump sleeps `min(poll_interval_seconds, effective refresh)`; tests cover the slow-consumer close (code 4429 reason `slow_consumer`) and close codes 1009, 1011 and 1013.
- [ ] After a 4403 revoke the map client ignores later deltas and the graph stays empty (vitest).
- [ ] Replay gap detail for a withheld parent is generic ("parent span is not available in this trace") and the foreign-domain reason is not distinguishable from an absent parent (test); gap badges have unique keys; the map-table `Load more` does not steal focus after the user tabbed away, and a stale `activeKey` leaves a tabbable row (vitest plus Playwright spec).
- [ ] The mock API answers an unknown replay trace with `application/problem+json` (status 404, code `not_found`).
- [ ] The Playwright command in the gates uses the correct cwd-relative spec paths.
- [ ] PRP exit: the touched pytest and vitest suites pass, `verify-gates.ps1 -Mode full` is green, the PRP-18 close-out lists the follow-up issues filed for the deferred items.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Where the bulk call lives | Add to the `GraphQuery` protocol; new optional protocol in `catalog/graph/` | New runtime-checkable `EdgesAmongQuery` protocol and `RepositoryGraphQuery.edges_among` inside `catalog/graph/` only. `catalog/protocol.py` belongs to PRP-43, so the base `GraphQuery` is not changed; the map service falls back when the method is absent |
| 2 | Per-node metrics | Compute from ledger; per-agent aggregate series | Owner decision 2026-11-14: per-agent aggregate series, PRP-49. Not here |
| 3 | fps criterion and perf re-measure | Reword now; wait for hardware | PRP-64 (operator hardware); round-1 evidence in `docs/evidence/G07/map/fps-run{1,2,3}.json` stands |
| 4 | Deferred items | Build now; file issues | Reveal-people-with-audit, `ArchiveTraceReader` index and cross-replica revocation e2e are filed as issues at close-out, not built |
| 5 | Model and review | sonnet/none; sonnet/required | sonnet, review required (round 1 decision D6 stands: a replay import guard and scope-bearing graph code) |
| 6 | ASSUMPTION A-1 | n/a | ASSUMPTION: the 3 s in-memory bound for a 2000-node page is a regression guard chosen here (round 1 measured about 15 s); the real figure is recorded in the test output and evidence, not promised |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/map/service.py` - `_Builder.edges_among`, `_neighbors`, `node_for` (lines 227-263, 200-216).
- `packages/core/neurosphere_core/catalog/graph/query.py` - `RepositoryGraphQuery._walk`, `_expand`, `_in_scope` (presented-edge rules: locks, overrides, hidden edges).
- `packages/core/neurosphere_core/catalog/protocol.py:446-470` - the `GraphQuery` protocol (read only; PRP-43 owns it).
- `packages/core/tests/catalog/graph_helpers.py` and `test_graph_budgets.py` - fixtures for scope and budgets.
- `services/api/neurosphere_api/realtime/gateway.py:376-460` and `realtime/settings.py:20-51` - pump loop, slow consumer, refresh.
- `services/api/tests/replay/test_replay_readonly.py` and `replay/assemble.py:100-185` - guard and gap text.
- `frontend/src/features/map/{hooks.ts,realtime.ts,mapGraph.ts}` - delta path and revoke.
- `frontend/src/features/map-table/MapGrid.tsx:215-300` - pending focus and `loadMore`.
- `frontend/tests/mock-api/server.ts:1323-1350` - `mapReplayHandler` (W13 Tier-1, owned here).
- `docs/evidence/G07/map/README.md` - evidence format for any re-measure note.

### Interfaces consumed
- `CatalogRepository.list_edges_by_node`, `get_entity`, `list_overrides_for_edges` (PRP-10, shipped).
- `AggregateReader.status` coverage and lag (PRP-14, shipped); not changed.
- `RevocationHookRegistry.register_push_registry("websocket", ...)` wired in `runtime/builders/data.py:437-448` (not edited).

### Interfaces provided
- `neurosphere_core.catalog.graph.EdgesAmongQuery` (runtime-checkable protocol) and `RepositoryGraphQuery.edges_among(scope, node_ids, budget, view="presented") -> GraphResult`; PRP-49 and PRP-43 build against it unchanged.
- Mock API: problem+json 404 for replay; no other contract change; `openapi.json` is not expected to change.

### Patterns to match
- Bounded, scope-first traversal: `catalog/graph/query.py:304-360` (`_expand`).
- Negative-fixture style tests for an AST guard: `services/api/tests/replay/test_replay_readonly.py:34-60`.
- problem+json in the mock: `frontend/tests/mock-api/server.ts:54-60` (`problem`) and `:417` use.
- Fake clock and sleeper in gateway tests: `services/api/tests/realtime/rt_helpers.py`.

### Gotchas
- Same-named test directories shadow each other: the new core test goes in `packages/core/tests/catalog/test_graph_edges_among.py` (a new file in the existing `catalog` test package, importing `graph_helpers` as `test_indexer.py` does); the API test goes in the existing `services/api/tests/map/`.
- `map-table` must import only `paths.ts` from `map` (round-1 fix `5a0622c`); do not re-import the `map` index from `map-table`.
- The map e2e specs are not in this PRP's `frontend/src` globs; the three map specs under `frontend/tests/e2e/` are listed in Owned files because items need them. PRP-47 owns the rest of `frontend/tests/**` in W15.
- Headless fps is SwiftShader; never record a headless number as a hardware result.
- `pnpm` runs inside `frontend/`, so Playwright spec paths are `tests/e2e/...`, not `frontend/tests/e2e/...`; `MSYS_NO_PATHCONV` breaks the pnpm shim.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - services/api/neurosphere_api/map/**
  - services/api/neurosphere_api/realtime/**
  - services/api/neurosphere_api/replay/**
  - packages/core/neurosphere_core/catalog/graph/**
  - packages/core/tests/catalog/test_graph_edges_among.py
  - services/api/tests/map/**
  - services/api/tests/realtime/**
  - services/api/tests/replay/**
  - frontend/src/features/map/**
  - frontend/src/features/map-table/**
  - frontend/src/features/replay/**
  - frontend/tests/e2e/map-table-keyboard.spec.ts
  - frontend/tests/e2e/map-reduced-motion.spec.ts
  - frontend/tests/e2e/map-perf.spec.ts
  - tests/load/map_freshness/**
tier1:
  - frontend/tests/mock-api/server.ts
tier2_appends: []
must_not_touch:
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - packages/core/neurosphere_core/catalog/repo/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/routers.py
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
  - frontend/package.json
```

## Implementation blueprint

Items 1, 2 and 3 are independent [P] (disjoint files). Item 4 waits for 1 (the viewport service calls the new method). Item 5 is the close-out.

### Item 1 - Bulk edges-among in the graph package  [P]
- Deliverable: new `packages/core/neurosphere_core/catalog/graph/bulk.py` with a runtime-checkable `EdgesAmongQuery` protocol and the request budget type; `RepositoryGraphQuery.edges_among` in `query.py` that reads the edges of all given ids with a shared scope cache (each node read once), applies the same presented-view rules as `_expand`, keeps only edges whose both endpoints are in the id set and in scope, bounds by `Budget` (edges, timeout) and reports `truncated`/`truncated_reason`; export from `graph/__init__.py`.
- Owned files: `packages/core/neurosphere_core/catalog/graph/**`, `packages/core/tests/catalog/test_graph_edges_among.py`.
- Must NOT touch: `catalog/protocol.py`, `catalog/repo/**`, `catalog/graph/latest.py` semantics.
- Depends on: none.
- Acceptance criteria: parity with per-node `neighbors` over the same ids (locks, overrides, hidden edges, out-of-scope other endpoint); raw view still refused for non-auditors; budget truncation flagged; no unbounded read.
- Tests: `packages/core/tests/catalog/test_graph_edges_among.py`.
- Pattern references: `query.py:233-360`, `packages/core/tests/catalog/test_graph_scope.py`.

### Item 2 - Replay guard hardening and replay nits  [P]
- Deliverable: `_imports()` in `test_replay_readonly.py` resolves `ImportFrom.level` against the package and flags `importlib.import_module`, `importlib.__import__` and `__import__` calls; negative fixtures written to `tmp_path` prove each form is caught; generic missing-parent gap text in `assemble.py`; frontend unique gap-badge keys in `TraceTree.tsx`.
- Owned files: `services/api/neurosphere_api/replay/**`, `services/api/tests/replay/**`, `frontend/src/features/replay/**`.
- Must NOT touch: `services/api/neurosphere_api/actions/**`, `connectors/**`, `frontend/tests/mock-api/server.ts`.
- Depends on: none.
- Acceptance criteria: the five forbidden forms fail the guard; real package passes; a withheld parent and an absent parent yield identical gap detail; replay vitest green.
- Tests: `services/api/tests/replay/test_replay_readonly.py`, `services/api/tests/replay/test_replay_labels.py`, `frontend/src/features/replay/replay.test.tsx`.
- Pattern references: `replay/assemble.py:117-148`, `TraceTree.tsx:60-75`.

### Item 3 - Gateway pump cadence and tests  [P]
- Deliverable: `_pump_loop` sleeps `min(poll_interval_seconds, effective refresh seconds)`; docstring says "TTL plus one interval" for cross-replica revocation; tests for the slow-consumer close and for close codes 1009, 1011, 1013; vetted WebSocket error reasons contain no token text (assertion on `Sec-WebSocket-Protocol` value).
- Owned files: `services/api/neurosphere_api/realtime/**`, `services/api/tests/realtime/**`.
- Must NOT touch: `neurosphere_core/auth/revocation/**`, `aggregates/**`, `runtime/builders/data.py`.
- Depends on: none.
- Acceptance criteria: with poll 10 s and TTL 4 s the refresh still fires at 2 s (fake sleeper); slow consumer closes with `rate_limited`/4429 and reason `slow_consumer`; the three close codes are asserted.
- Tests: `services/api/tests/realtime/test_budgets.py`, `services/api/tests/realtime/test_disconnect_lifecycle.py`, `services/api/tests/realtime/test_pump_cadence.py` (new).
- Pattern references: `realtime/gateway.py:376-460`, `rt_helpers.py`.

### Item 4 - Map service uses the bulk call; frontend and mock nits
- Deliverable: `_Builder.edges_among` calls `edges_among` when the graph supports `EdgesAmongQuery`, else the existing walk; a 2000-node perf test; map `onDelta` guard after revoke; map-table focus fixes (`loadMore` does not move focus if focus left the grid; a stale `activeKey` falls back to the first row) with e2e additions for ArrowRight/Left, End, 401 and 503; mock API replay 404 as problem+json (new `notFoundProblem` helper beside `problem`, status 404, `application/problem+json`); fix the Playwright paths in the PRP gates.
- Owned files: `services/api/neurosphere_api/map/**`, `services/api/tests/map/**`, `frontend/src/features/map/**`, `frontend/src/features/map-table/**`, the three `frontend/tests/e2e/map-*.spec.ts` files, `frontend/tests/mock-api/server.ts`, `tests/load/map_freshness/**`.
- Must NOT touch: `map/service.py` metrics logic (`node_for`, PRP-49), `aggregates/**`, `frontend/package.json`.
- Depends on: item 1.
- Acceptance criteria: one bulk call per viewport page (spy), fallback path covered, edge budget flag unchanged, the page under the A-1 bound; vitest and Playwright specs pass on the mock API.
- Tests: `services/api/tests/map/test_node_budget.py`, `services/api/tests/map/test_edge_batching.py` (new), `frontend/src/features/map/map.test.tsx`, `frontend/src/features/map-table/map-table.test.tsx`, `frontend/tests/e2e/map-table-keyboard.spec.ts`.
- Pattern references: `map/service.py:227-263`, `MapGrid.tsx:215-300`, `server.ts:54-60`.

### Item 5 - Integration and close-out
- Deliverable: regenerate Tier 3 files (only if models changed: `uv run python -m neurosphere_api.openapi_export`; not expected), tick the round-1 acceptance boxes that the code confirms, fill the completion note, file issues for the three deferred items (reveal-people-with-audit, `ArchiveTraceReader` index, cross-replica revocation e2e), `python scripts/prp_status.py --write`, CHANGELOG entry per reference section 6.
- Owned files: this PRP file only.
- Must NOT touch: any item 1-4 source except to fix an integration defect (record the deviation).
- Depends on: items 1-4.
- Acceptance criteria: completion note filled; issues numbered in it.

## Validation gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/catalog services/api/tests/map services/api/tests/realtime services/api/tests/replay services/api/tests/test_openapi_drift.py tests/load/map_freshness
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend test
cd frontend && pnpm exec playwright test tests/e2e/map-table-keyboard.spec.ts tests/e2e/map-reduced-motion.spec.ts
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

Use unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` for Playwright in this worktree.

## Migration and rollback
No data or schema migration: the bulk call is additive and read-only. Rollback is a revert of the PRP branch; the map service falls back to the per-node walk if `edges_among` is removed from the graph, so a partial revert is safe.

## Live and open gates
- G07 map evidence stays OPEN: the fps p5 criterion reword and the enforced headed re-measure are handed to PRP-64 (`NS_LIVE_APPROVED=1` is not needed, operator hardware is).
- The optional live freshness run (`NS_LIVE_APPROVED=1`) is not run here.
- No paid call; nothing in this PRP needs one.

## NOT building
- Per-node metrics and per-agent aggregates (PRP-49).
- Reveal-people-with-audit, `ArchiveTraceReader` index, cross-replica revocation e2e (issues only).
- Renderer optimisation for the p5 tail (PRP-64 decides after re-measure).
- Any change to `catalog/protocol.py`, repositories, contracts or `openapi.json` shapes.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 6 is a labelled assumption)

## Execution state

| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 | merged | prp-18-round2-map-edge-batching | EdgesAmongQuery + RepositoryGraphQuery.edges_among, 7 tests |
| 2 | merged | prp-18-round2-map-edge-batching | guard + generic gap text + unique badge keys |
| 3 | merged | prp-18-round2-map-edge-batching | pump cadence + slow consumer, 1011, token-text tests |
| 4 | todo | | |
| 5 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (G07 map fps and live freshness):
- Env vars for the operator (none expected):
- Follow-up issue numbers (reveal-people-with-audit, archive index, revocation e2e):
- Product check (can an operator use the map and replay without editing files?):

## History
- Round 1 (PR #85, merged 2026-10-21, merge `3d14d00`) shipped the WebSocket gateway, viewport API, sigma renderer, accessible table, replay viewer, freshness test and wiring (items 1-7).
- The 2026-11-04 audit reopened it: per-node metrics null, a 2000-node page about 15 s, 30 fps p5 not met with opt-in enforcement, replay never run on real storage, import guard gaps.
- The 2026-11-14 re-audit (lane-b unit 18-R2-A) found the real-stack data-plane test now covers replay on Azurite (`tests/integration/real_stack/test_data_plane.py:257-275`), so that gap is mostly closed, and four references were stale (Playwright path, composition now in `runtime/builders/data.py`, PRP-30 frontend refold, status labels).
- This rewrite removed the round-1 blueprint, the wire-contract and execution-state narrative, the pre-PRP-35 composition caveats and the audit section; per-node metrics moved to PRP-49 and the perf re-measure to PRP-64.
- The original text is in git history (`git log --follow PRPs/backlog/PRP-18-live-map-and-session-replay.md`).
