---
name: PRP-74-live-map-topology-backend
status: active
priority: P0
order: 65
review: required
created: 2026-11-16
started: 2026-11-23
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-05
depends_on: [PRP-70-contracts-revision-restored-scope, PRP-71-realistic-seeded-world-and-demo-profile, PRP-73-graph-access-and-sensitivity-questions, PRP-100-telemetry-tool-service-identity-and-aggregates, PRP-137-telemetry-agent-identity-resolution]
wave: W22
branch: prp-74-live-map-topology-backend
allow_parallel: true
issues: []
---

# PRP-74: Live map topology backend (services and tools, facets, topology push, search, impact)

## Goal
Give the live map the server half of what the original PRD asked for in 5d. Services, tools and MCP servers become map nodes next to agents, models, sources and people. Every node carries the PRP-70 facets (environment, cloud, tags, health, error rate and count, sensitivity). When a node or edge is added, removed or changed, the existing WebSocket pushes a topology-change message so a client refetches instead of waiting for a page reload. A new search route filters and searches the whole in-scope domain on the server and returns a bounded list, and a neighbourhood route returns one node with its neighbours so a client can jump to a match without paging a cluster. A new impact route answers "what is affected if this node fails" for the map, built on the PRP-73 `dependents` engine. It is for the SRE and the architect, and for PRP-77, which draws all of it. It runs in W22 on the PRP-70 contracts and the PRP-71 demo world (the services, the incident).

Out of scope: every pixel of UI, the filter bar, jump-to-node, the impact highlight and the interaction-latency measurement (PRP-77); the dependents engine, its route and the `catalog/**` code (PRP-73; PRP-76 owns `catalog/**` in this wave, so this PRP edits nothing under `catalog/`); per-edge traffic volume (needs a new edge aggregate; follow-up, see NOT building); telemetry-derived tool and service aggregates (the telemetry envelope carries no tool or service id); the operator-hardware frame-rate and latency re-measure (PRP-66); any second graph store (Cosmos adjacency stays the engine).

## Why
- Original PRD 5d (`git show 9fbf5f4c:docs/PRD.md`): "Interactive, auto-updating graph visualization of agents, services, data assets, and their relationships, reflecting telemetry in near real time (node health, traffic volume, recent errors)". Today the map draws only agent, grounding_source, model_deployment and person (`services/api/neurosphere_api/map/service.py` `VIEWPORT_ENTITY_TYPES`); `NodeKind` has no service or tool (`map/models.py:29`); node metrics have no error field (`map/models.py:41-47`) although the subject point already holds `error_count` and `error_rate` (`packages/core/neurosphere_core/aggregates/models.py:268-285`).
- Original 5d story: "As an SRE, I want to see, during an incident, every downstream agent affected by a failing service, highlighted live." The map never calls the catalog impact route (`/catalog/lineage/impact`, `catalog/router.py:288-297`, depth <= 5); an SRE has to leave the map and read a table (gap analysis 5d).
- Original 5d acceptance: "Map updates within 5s of a graph-affecting telemetry event (push via WebSocket/SignalR)". The gateway polls aggregates every 2 s and a delta is one cluster node plus at most 50 subject nodes with `edges` always empty (`realtime/source.py:14-15`, `MAX_DELTA_SUBJECT_NODES`); the client applies deltas only to nodes it already holds (`frontend/src/features/map/mapGraph.ts:391-398`). A new agent or edge appears only after a reload. PRP-49 follow-up 2: model delta ids are `provider/model`, graph model nodes use catalog deployment ids, so model deltas are dead.
- Original 5d acceptance: "Supports filtering/search by node type, tag, environment, health status" and story "As an architect, I want to filter the map by environment (prod/staging) or cloud provider". Nodes carry no environment, cloud or tags and no filter exists on the viewport route (`map/router.py:48-68`).
- Original 5d acceptance: "Handles graphs of at least 50k nodes / 250k edges with acceptable pan/zoom performance (<200ms interaction latency)". Cut by v1.2: `docs/PRD.md` NS-05 "Aggregate into domain clusters; never download the full enterprise graph to a browser" (line 25) and the scale line "Browser target <=2k visible nodes at >=30fps on documented hardware, not 1M nodes rendered at once" (line 51). Gap analysis section 5 item 1 gives the honest restatement this PRP implements: the whole in-scope graph is searchable and filterable on the server, the viewport stays cluster-first and bounded (2000 nodes, 5000 edges, `map/dependencies.py:42-44`), and caps rise only with measured evidence. A browser holding the whole graph would also bypass per-entity authorization.
- Freshness today is proven only for metric deltas after aggregation (2.0 s); a 2000-node page took about 15 s server-side in the 2026-11-04 audit and the re-measure is OPEN (PRP-18 completion note, PRP-49 follow-up 4). The new routes need their own measured server timings.

## Acceptance criteria
- [ ] Given a domain with a service, a tool and an MCP server in the catalog, When `GET /api/v1/map/domains/{domain_id}/viewport` runs, Then they appear as nodes of kind `service`, `tool` and `mcp_server`, in their own clusters when over the node budget, and edges to and from them appear when both endpoints are in the response (orphan edges are still dropped).
- [ ] Every viewport node carries `facets` (the PRP-70 `MapNodeFacets`): `entity_type`, `environment`, `cloud`, `tags`, `lifecycle_status`, `health`, `error_rate`, `error_count`, `request_count`, `last_error_at`, `sensitivity_categories`, `residency_geography`. Unknown stays null or `unknown`, never 0; people carry facets without any real name; a cluster node carries `entity_type` null.
- [ ] Given agent telemetry with errors in the last hour, Then the agent node's `error_rate` and `error_count` equal the subject point values and `health` equals `health_for_error_rate`; a model node shows model-level values; a node with no point stays unknown.
- [ ] Given PRP-71's incident (a failing service with downstream agents), Then the service node reports `degraded` or `failing` from its own PRP-100 service subject point (measured error rate) and, only if it has no point, by the fallback dependents rule in clarification 5; the downstream agents report their own aggregate health (OTLP agents through PRP-137's resolved ids); unrelated agents stay `ok`.
- [ ] Given a connected, subscribed session and a catalog write that adds an agent, an edge or a tag change, When the next topology poll runs, Then the session receives a `topology` message (the PRP-70 `MapTopologyChange` shape: `domain_id`, `changed_at`, `change_kinds`, up to 50 `entity_ids`, `refetch`, `truncated`) within `NS_MAP_TOPOLOGY_POLL_SECONDS` (default 3, so within 5 s of the catalog change); an unchanged graph sends nothing except the existing heartbeat.
- [ ] Topology messages follow the delta rules: filtered by the session's CURRENT scope at send time, dropped with `scope_narrowed` when the domain is no longer readable, closed on revocation, counted in the existing counters, and never carry an id the session's scope cannot read. Two sessions with different scopes never share a cached snapshot (cache key is `scope_cache_key(scope, namespace="map-topology")`).
- [ ] Given `GET /api/v1/map/domains/{domain_id}/search?q=&node_type=&tag=&environment=&cloud=&health=`, Then the result is a bounded list (limit 1 to 50, default 20) of matches over the WHOLE in-scope domain scan (up to `NS_MAP_SEARCH_SCAN_PAGES` pages of 500, default 100, so 50k entities) with `truncated` and `truncation_reason` (`scan_limit`, `timeout_ms`) when the scan stopped, per-kind and per-facet counts, and each match's `node` plus its `cluster_id`; a person is only ever found by pseudonym.
- [ ] Given a filter on the viewport route (`node_type`, `tag`, `environment`, `cloud`, `health`, repeatable), Then cluster counts and pages reflect only matching entities, the response says which filters applied, and an unknown filter value is 422 `invalid_filter`.
- [ ] Given `GET /api/v1/map/domains/{domain_id}/neighborhood/{node_id}`, Then the response is a `ViewportResponse` holding that node plus its direct neighbours (both directions, node budget and edge budget clamped as the viewport route), `truncated` when over budget; a node outside the caller's scope is 404, the same body as a missing node.
- [ ] Given `POST /api/v1/map/domains/{domain_id}/impact` with `node_id` and `max_depth` 1 to 5, Then the response lists affected in-scope entities grouped by depth with the edge ids of the path, each affected node's current `health`, and `truncated` with a reason at the budget; depth 6 is 422; a person is only ever shown by pseudonym; a node the caller cannot read is 404.
- [ ] Given a caller without `data.read` on the domain, Then viewport, search, neighbourhood and impact return 403 with a denial record; every new route is in the route inventories and boots under `verify_route_permissions`.
- [ ] Model-node deltas apply: the delta source maps `model:<provider>/<model>` to every deployment id of the topology snapshot (PRP-49 follow-up 2), or sends no model node when no snapshot exists; a test asserts ids equal the viewport's model node ids.
- [ ] Server timings are recorded: viewport at 2000 nodes, search over a seeded 50k-entity domain, impact at depth 5 and one topology poll, each with hardware stated, in `docs/evidence/G07/map/server-timings.json`, plus the number of Cosmos reads per call on the emulator. No target is asserted in CI; the numbers are reported, and anything over 2 s is listed as a follow-up.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright and `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | The 50k-node criterion | Raise the caps to 50k in the browser; keep the browser bounded and make the server search the whole graph | Second. Whole-domain search and filter on the server, bounded viewport, cluster-first. Gap analysis section 5 item 1; `docs/PRD.md` lines 25 and 51 stay true. Caps (2000/5000) change only with measured evidence, in a later PRP |
| 2 | How the search scans | New index; application-side scan | Application-side scan over `CatalogRepository.list_entities` pages (PRP-73 does the same for access questions). A search index over entities is a later optimisation if the recorded timings need it |
| 3 | Where facets come from | Compute in the browser; server | Server, from the PRP-70 entity fields plus subject points. `cloud` comes from the entity's own cloud field; environment, tags and sensitivity from PRP-70 |
| 4 | Services and tools: telemetry health | Add tool and service subject aggregates; derive | ASSUMPTION: derive. The telemetry envelope has no tool or service id and the aggregates worker only rolls up `model_call` spans (`services/workers/neurosphere_workers/aggregates/mapping.py:153`), so a tool or service has no series. Changing aggregates is another PRP; file a follow-up |
| 5 | Derived health of a service or tool | `unknown` always; from dependents | UPDATED for the governance core: health of a service, tool or MCP server comes first from PRP-100's measured per-service and per-tool subject points (read through `SubjectMetricsReader`, `health_for_error_rate`), never inferred when a point exists. The rule below is only the fallback for a node with no point, and its health is labelled inferred. ASSUMPTION (fallback): a service, tool or MCP server is `failing` when at least `NS_MAP_DERIVED_FAILING_RATIO` (default 0.5) and at least 2 of its direct dependents (upstream `depends_on` and `invokes` neighbours within the scan) are `failing`, `degraded` when the same holds at the degraded threshold (default 0.34), else `unknown`. It is an inference and the runbook says so; it cannot show `ok`. If the owner wants a different rule it is one function (`derive_health`) |
| 6 | "Downstream" for impact | Edges out of the node; dependents | Dependents (things that rely on the failing node), the PRP-73 `dependents` semantics (`impact_paths(direction="upstream")`). The map route is named `impact` and the response says `direction: dependents` so it cannot be misread |
| 7 | Topology change detection | Event hub subscription; catalog change feed; poll a fingerprint | ASSUMPTION: poll a bounded fingerprint. No catalog change feed exists and `CatalogRepository` is owned by no one in this wave to extend. One scan per (scope, domain) per poll interval is shared by all sessions with the same scope key; the fingerprint is the node count, edge count and an order-independent digest of (id, entity_version or edge status and version) |
| 8 | What a topology message carries | Full nodes; ids and a refetch flag | Ids, change kinds and `refetch: true`; the client refetches the viewport (bounded). No node body in a push, so no new payload path to authorize |
| 9 | Per-edge traffic volume | Add now; follow-up | Follow-up. It needs a per-edge aggregate in the aggregates worker. The original criterion "traffic volume" is covered per node by `request_count` |
| 10 | Where the topology source lives | New builder; lazy in the gateway | Lazy: the gateway builds it on first subscribe from `app.state.catalog_repository` and `catalog_graph` and caches it on `app.state.map_topology`, so no builder, component or pinned-test change (PRP-76 adds a builder in the same wave). `NS_MAP_TOPOLOGY_ENABLED=false` turns it off |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/map/service.py` - `_Builder.scan`, `page_of_kind`, `load_subjects`, `node_for`, `build_viewport`, `VIEWPORT_ENTITY_TYPES`, `_KIND`.
- `services/api/neurosphere_api/map/models.py`, `map/router.py`, `map/dependencies.py` - wire models, `ReadScope`, limits, providers.
- `services/api/neurosphere_api/realtime/gateway.py` - `_Connection._deliver`, `_pump_loop`, `_subscribe`, `_send`; `realtime/source.py` - `DeltaPayload`, `_subject_node`; `realtime/settings.py`.
- `services/api/neurosphere_api/authz/cache_key.py:45` - `scope_cache_key`.
- `packages/core/neurosphere_core/catalog/protocol.py:141-200,276-300,412-470` - `EntityFilter`, `list_entities`, `list_edges_by_domain`, `ImpactRequest`, `GraphQuery`.
- `packages/core/neurosphere_core/aggregates/models.py:268-290` and `aggregates/subject.py` - `SubjectPoint`, `health_for_error_rate`, series keys.
- `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md` ("Interfaces provided": `MapNodeFacets`, `MapTopologyChange`, entity tags, environment) and `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md` (`AccessEngine.dependents`).
- `PRPs/shipped/PRP-18-live-map-and-session-replay.md` and `PRPs/shipped/PRP-49-per-agent-aggregates-and-map-metrics.md` completion notes (known limits).
- `services/api/tests/map/map_api_helpers.py`, `services/api/tests/realtime/rt_helpers.py` - fixtures to extend.

### Interfaces consumed
- PRP-70 (shipped by the time this runs): `neurosphere_contracts.map.v1` `MapNodeFacets` and `MapTopologyChange`; entity fields `tags`, `environment`, `sensitivity_categories`, `residency_geography` on Agent, Tool, Service, McpServer, ModelDeployment and GroundingSource; `StructuredQuery` additions are not used here.
- PRP-71: the `demo-world` seed (services, tags, environment, the incident manifest at `incident-manifest.json`) for the integration check; unit tests build their own in-memory world.
- PRP-100 (same wave, merges first): `SubjectKind` `tool` and `service` points and canonical tool and service ids; the last item before close-out reads them for `facets_of`. PRP-137 (W19, merges earlier): resolved canonical agent ids so OTLP agents have series. If either has not merged when this PRP runs, the fallback rule applies and the criterion records OPEN.
- PRP-73: `neurosphere_core.catalog.graph.access.AccessEngine.dependents(scope, node_id, max_depth, budget) -> AccessResult` (rows grouped by depth, relation path, `truncated`; PRP-73 "Interfaces provided"; read-only import; this PRP never edits `catalog/**` or `catalog/graph/**`). The one adapter function in `map/impact.py` turns an `AccessResult` into `ImpactResponse.levels`. Fallback if PRP-73 is not merged: `GraphQuery.impact_paths(scope, ImpactRequest(direction="upstream"))`.
- Shipped: `CatalogRepository`, `GraphQuery`, `EdgesAmongQuery`, `AggregateReader` and `SubjectMetricsReader` (PRP-49), `PrincipalPseudonymizer`, `require`, `domain_from_path`, `scope_cache_key`, the realtime `Session` and revocation hooks.

### Interfaces provided
- Routes under `/api/v1/map` (all `data.read` on the path domain): `GET /domains/{domain_id}/viewport` (new query params `node_type`, `tag`, `environment`, `cloud`, `health`), `GET /domains/{domain_id}/search`, `GET /domains/{domain_id}/neighborhood/{node_id}`, `POST /domains/{domain_id}/impact`.
- Wire models in `neurosphere_api.map.models`: `ViewportNode.facets` (optional, `MapNodeFacets`), `NodeKind` adds `service`, `tool`, `mcp_server`; `SearchResponse` {`domain_id`, `matches` (`SearchMatch` {`node`, `cluster_id`}), `counts` {`by_kind`, `by_health`, `by_environment`, `by_cloud`}, `truncated`, `truncation_reason`, `coverage`}; `ImpactRequest` {`node_id`, `max_depth` 1-5, `budget`}; `ImpactResponse` {`domain_id`, `node_id`, `direction: "dependents"`, `levels` (list of {`depth`, `nodes` (id, kind, label, domain_id, health), `edge_ids`}), `truncated`, `truncation_reason`, `coverage`}.
- Realtime message `{"type": "topology", "domain_id", "seq", ...MapTopologyChange..., "emitted_at"}` on the existing socket; subscribers need no new subscribe message.
- Settings: `NS_MAP_TOPOLOGY_ENABLED` (default true), `NS_MAP_TOPOLOGY_POLL_SECONDS` (default 3, 1 to 60), `NS_MAP_TOPOLOGY_SCAN_PAGES` (default 20), `NS_MAP_SEARCH_SCAN_PAGES` (default 100, max 200), `NS_MAP_SEARCH_TIMEOUT_MS` (default 8000), `NS_MAP_DERIVED_FAILING_RATIO`, `NS_MAP_DERIVED_DEGRADED_RATIO`.
- Core helpers for PRP-77 tests: `neurosphere_api.map.facets.facets_of(entity, point)`, `neurosphere_api.map.topology.TopologySource`.

### Patterns to match
- Bounded scan and cluster paging: `map/service.py` `scan` and `page_of_kind`; cursor encoding `_encode_cursor`.
- Route shape and `ReadScope`: `map/router.py:48-68`; no in-process cache without `scope_cache_key` (router docstring).
- Gateway deliver, send-time scope check, digest suppression and heartbeat: `realtime/gateway.py` `_deliver`.
- Per-scope TTL cache with a size cap: `realtime/source.py` `AggregateDeltaSource._cache` (but keyed by scope here).
- Route inventories: PRP-41 item 6 and `services/api/tests/authz/test_route_inventory.py`.

### Gotchas
- `from __future__ import annotations` must not appear in `map/*.py` or `realtime/*.py` (FastAPI inspects signatures).
- Contract models used as `response_model` rename `openapi.json` components; regenerate and check `services/api/tests/test_openapi_drift.py`. Wire models stay API-local; the facets and change shapes are imported from the contract package (do not copy them).
- The delta client replaces a node's whole `metrics` object (`mapGraph.ts:391-398`), and delta nodes carry `context_size: null`, so a delta blanks a known context size. Keep delta payloads metric-only and document "null in a delta means not carried"; the client merge fix is PRP-77 (listed there).
- People: facets and search results use the pseudonym everywhere; test with a person whose real name contains the query term.
- The scan reads entities page by page; 100 pages of 500 on Cosmos is real RU cost. The recorded timings and RU per call are the evidence; do not raise defaults without them.
- Two concurrent deliveries share one snapshot per scope key; evict by TTL and entry cap (1024) so a long-lived process cannot grow without bound.
- Per-replica snapshots mean two replicas can announce the same change at slightly different times; clients must treat `topology` as idempotent (refetch).
- Test package name clash: new tests live in `services/api/tests/map_topology_api/` (unique); existing `services/api/tests/map` and `realtime` suites run together with it.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/map/**
  - services/api/neurosphere_api/realtime/**
  - services/api/tests/map/**
  - services/api/tests/realtime/**
  - services/api/tests/map_topology_api/**
  - tests/security/authz/test_map_topology*.py
  - tests/load/map_topology/**
  - docs/evidence/G07/map/server-timings.json
  - docs/runbooks/live-map.md
tier1: []
tier2_appends:
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/aggregates/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/runtime/builders/**
  - services/api/neurosphere_api/routers.py
  - services/workers/**
  - frontend/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 4 then share no file (items 2 and 3 both edit `map/router.py`, so 3 follows 2). Item 5 after 2-4; item 6 last.

### Item 1 - Node kinds, facets and error fields
- Deliverable: `NodeKind` adds `service`, `tool`, `mcp_server`; `VIEWPORT_ENTITY_TYPES`, `_KIND` and cluster labels extended; `map/facets.py` with `facets_of(entity, point)` building `MapNodeFacets` (environment, cloud, tags, sensitivity from the entity; health, error fields from the subject point) and `derive_health` for service, tool and MCP server (clarification 5); `ViewportNode.facets`; `node_for` labels for the new kinds (display name, never a real person name); `map/settings.py` with the `NS_MAP_*` settings.
- Owned files: `services/api/neurosphere_api/map/{models,service,facets,settings}.py`, `services/api/tests/map/**`.
- Must NOT touch: `catalog/**`, aggregates, contracts.
- Depends on: PRP-70 shipped.
- Acceptance criteria: criteria 1 to 4 and the model-id mapping helper (`model_deployment_ids(provider, model_name)` over the scanned entities).
- Tests: `services/api/tests/map/test_service_tool_nodes.py`, `test_facets.py`, `test_derived_health.py`; existing `services/api/tests/map` unchanged otherwise.
- Pattern references: `map/service.py` `node_for`, `load_subjects`.

### Item 2 - Server-side filter, search and neighbourhood
- Deliverable: filter parameters on the viewport route applied in the scan (application-side predicates, bounded); `map/search.py` with the search function, per-kind and per-facet counts, scan cap and timeout labels; the `search` and `neighborhood` routes; 422 `invalid_filter`; domain re-check on every entity (`_in_domain`).
- Owned files: `services/api/neurosphere_api/map/{search,router,dependencies}.py` (router and dependencies edited here), `services/api/tests/map_topology_api/test_search.py`, `test_filters.py`, `test_neighborhood.py`.
- Must NOT touch: `catalog/**`.
- Depends on: item 1.
- Acceptance criteria: criteria 6 to 8, and part of 10; a search over a 5,000-entity in-memory world returns matches in kind order with counts that sum to the match total; a scan stopped by the page cap says `scan_limit`.
- Tests: the three files above, plus pseudonym test in `test_search_people.py`.
- Pattern references: `map/service.py` `scan`, `page_of_kind`; `catalog/router.py:36-37` for query bounds.

### Item 3 - Impact route
- Deliverable: `map/impact.py` with the adapter over `AccessEngine.dependents` (fallback to `GraphQuery.impact_paths`), per-level grouping, health attached from the subject points and derived rule, pseudonyms for people, budget clamp; the `impact` route in `map/router.py`.
- Owned files: `services/api/neurosphere_api/map/{impact,router}.py`, `services/api/tests/map_topology_api/test_impact.py`.
- Must NOT touch: `catalog/access/**`, `catalog/graph/**`.
- Depends on: item 2 (router) and PRP-73 shipped.
- Acceptance criteria: criterion 9; against the in-memory twin of PRP-71's incident, the impact of the failing service lists exactly the manifest's downstream agents; depth over 5 is 422; a hidden or out-of-scope node is 404.
- Tests: `services/api/tests/map_topology_api/test_impact.py`, `test_impact_scope.py`.
- Pattern references: `catalog/router.py:288-297`, PRP-73 `dependents` tests.

### Item 4 - Topology change source and push
- Deliverable: `map/topology.py` with `TopologySource` (scoped snapshot, fingerprint, diff to a `MapTopologyChange`, cache keyed by `scope_cache_key`, TTL and entry cap), gateway wiring in `realtime/gateway.py` (poll beside the delta poll, send-time scope check, `topology` message, counters), lazy construction on `app.state.map_topology`, `NS_MAP_TOPOLOGY_ENABLED`; the model delta id mapping in `realtime/source.py` using the snapshot.
- Owned files: `services/api/neurosphere_api/map/topology.py`, `services/api/neurosphere_api/realtime/{gateway,source,settings,dependencies}.py`, `services/api/tests/realtime/test_topology_push.py`, `services/api/tests/map_topology_api/test_topology_source.py`, `test_model_delta_ids.py`.
- Must NOT touch: `runtime/builders/**`, `routers.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 5, 6 (scope part) and 11; unchanged graph sends no topology message; a diff over 50 ids sets `truncated` and `refetch`; with the switch off no message is sent and existing realtime tests pass unchanged; revocation and scope narrowing behave as for deltas.
- Tests: new files above plus `services/api/tests/realtime` (all), run together with `services/api/tests/map`.
- Pattern references: `realtime/gateway.py` `_deliver`, `services/api/tests/realtime/test_scope_filter.py`, `test_pump_cadence.py`.

### Item 5 - Authorization, secrecy and scale evidence  [serial-after: PRP-100]
- Deliverable: ABAC negatives per new route (no role, viewer of another domain, expired scope, wrong customer, node in another domain); a two-scope test proving no shared snapshot; a pseudonym leak test over search, neighbourhood and impact; the timing harness in `tests/load/map_topology/` (in-memory 50k-entity world for CI-safe shape checks, emulator run documented for local) and `docs/evidence/G07/map/server-timings.json` with hardware, counts and RU per call (or "not measured: emulator unavailable" stated plainly).
- Owned files: `tests/security/authz/test_map_topology*.py`, `tests/load/map_topology/**`, `docs/evidence/G07/map/server-timings.json`.
- Must NOT touch: shared authz harness files except additive helpers.
- Depends on: items 2, 3 and 4; PRP-100 merged (same wave W22; PRP-100 merges first, so its tool and service points exist for the timing world).
- Acceptance criteria: criteria 5 (isolation), 10 and 12; no skipped case; the evidence file records numbers or says exactly what did not run.
- Tests: `tests/security/authz`, `tests/load/map_topology`.
- Pattern references: `tests/security/authz/test_api_paths.py`, `tests/load/catalog_latency/harness.py`.

### Item 6 - Integration and close-out
- Deliverable: Tier-2 inventory lines for the three new routes; `docs/runbooks/live-map.md` (new: what the map shows, derived-health rule and its limits, topology push cadence, search caps and timeouts, settings, the 50k restatement); rebase and regenerate Tier-3 (`services/api/openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`); changelog fragment under `changelog.d/`; completion note with the recorded timings and the follow-ups (per-edge traffic, tool and service aggregates, delta null-merge on the client).
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/map services/api/tests/map_topology_api services/api/tests/realtime services/api/tests/authz services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data tests/security/authz tests/load/map_topology services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, not CI): `docker compose up -d --wait`, load the PRP-71 `demo-world`, call viewport, search, impact on the failing service and watch one `topology` message arrive after a catalog write; record the timings.

## Migration and rollback
No data migration: no new container, no stored field, no contract change here (PRP-70 shipped the shapes). Existing clients ignore the new `facets` and the new node kinds only if they tolerate unknown values; the current frontend does not, so merge PRP-77 in the same release train or keep new kinds behind the filter default (see Gotchas in PRP-77). Rollback: `NS_MAP_TOPOLOGY_ENABLED=false` stops the push; revert the PR for the rest; the viewport route without the new parameters behaves as before.

## Live and open gates
Nothing here needs `NS_LIVE_APPROVED=1`. The emulator timing run is local. Real-Cosmos RU and latency for 50k-entity search, and the headed frame-rate and interaction-latency re-measure on operator hardware, are OPEN and handed to PRP-66 (G07); the hosted check follows PRP-82. Report them OPEN in the completion note.

## NOT building
Per-edge traffic volume or an edge aggregate; service and tool telemetry aggregates (PRP-100 produces them; this PRP only reads them); a search index or a second graph store; a raised 2000/5000 cap or a full-graph download; node bodies in a push; a catalog change feed; any UI (PRP-77); catalog or aggregate code changes (PRP-73, PRP-76, PRP-49 area); generated Cypher, SQL or Gremlin (a hard constraint); any claim that the map meets the 50k-node or 200 ms criterion.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4, 5 and 7 are ASSUMPTIONS for plan approval; PRP-73's `dependents` signature is unverified until it ships)

## Execution state
| Item | Status | Branch/worktree | Model | Evidence | Updated | Notes |
|---|---|---|---|---|---|---|
| 1 | merged | prp-74-item-1 | sonnet | ruff/format/pyright clean; map+realtime+openapi_drift+authz 323 passed on integration; item 52a48072, merge 45b2d92b | 2026-11-23 | node kinds, facets, derived health. MCP servers have no subject key and no dependents edge type, so they read `unknown`; `last_error_at` null (SubjectPoint has no timestamp) |
| 2 | merged | prp-74-item-2 | sonnet | ruff/format/pyright clean; map+map_topology_api+realtime+openapi_drift+authz 367 passed on integration; item fd1f3224, merge ce3d0142 | 2026-11-23 | filter, search, neighbourhood. `invalid_filter` is the `reason` on a 422 `invalid_schema` problem; `health` filter matches measured health only (review point) |
| 3 | in-progress | prp-74-item-3 | sonnet | | 2026-11-23 | impact route |
| 4 | merged | prp-74-item-4 | sonnet | ruff/format/pyright clean; same suites 384 passed on integration; item 5a7931d7, merge 3ac74fb2 (add/add on test helper resolved: item 4 helpers moved to `topology_push_helpers.py`) | 2026-11-23 | topology source and push, model delta ids mapped at deliver time from the session-scoped snapshot; with topology disabled, model delta nodes are dropped |
| 5 | todo | | sonnet | | | authz negatives, timings evidence; PRP-100 shipped |
| 6 | todo | | sonnet | | | Tier-2, runbook, Tier-3, close-out |

Plan approved 2026-11-23: waves A(1) -> B(2 || 4) -> C(3) -> D(5) -> one review pass over 1-5 -> E(6). New node kinds are returned by default (the current UI drops unknown kinds safely; PRP-77 draws them). Integration branch `prp-74-live-map-topology-backend` from main 13153e53.

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (real Cosmos cost, headed re-measure via PRP-66, hosted check):
- Env vars for the operator (`NS_MAP_*`):
- Recorded server timings (hardware stated):
- Follow-up issue numbers:
- Product check (can a client see a new agent appear and ask for impact without a reload?):
