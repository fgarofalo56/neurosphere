# Live map: topology, search and impact

This runbook covers the server side of the live map (PRP-74): which nodes it shows, how a node's
health is chosen, the topology push, the search, neighbourhood and impact routes, and the
`NS_MAP_*` settings. It describes the API, not the page that draws it (PRP-77).

Status: the figures below are code defaults and caps, not measured performance. Server timings
are recorded separately (see "Server timings"). Nothing here claims the map meets the original
50k-node or 200 ms interaction criterion.

## Routes

All routes sit under `/api/v1/map/domains/{domain_id}` and need `data.read` on the path domain.
A caller without it gets 403 and a denial record. A node that is missing, outside the caller's
scope, in another domain or not a map entity is the same 404 (`node_not_found`) on the
neighbourhood and impact routes, so the response never says which.

| Route | Purpose |
|---|---|
| `GET /viewport` | Clusters, nodes and edges for one domain, bounded; takes filters |
| `GET /search` | Whole-domain search and filter, bounded list with counts |
| `GET /neighborhood/{node_id}` | One node plus its direct neighbours, both directions |
| `POST /impact` | What depends on a node, grouped by depth |

## What the map shows

Node kinds: `person`, `agent`, `sub_agent`, `model`, `source`, `service`, `tool`, `mcp_server`
and `cluster`. Services, tools and MCP servers are returned by default and get their own clusters
when the domain is over the node budget. An edge is returned only when both endpoints are in the
response; an edge with a missing endpoint is dropped.

Every node carries `facets`: entity type, environment, cloud, tags, lifecycle status, health,
error rate, error count, request count, last error time, sensitivity categories and residency
geography. An unknown value is null (or `unknown` for health), never 0. A cluster node has a null
entity type and everything else unknown. A person node shows a pseudonym as its id and label and
carries no real name. `last_error_at` is currently always null because a subject point has no
timestamp for it.

### How health is chosen

1. **Measured.** If the node has a subject point (agents, models, and services and tools that
   PRP-100 telemetry identifies), health comes from the point's error rate, and the error rate,
   error count and request count are the point's values. A measured point is never overridden.
2. **Inferred fallback.** Only a `service`, `tool` or `mcp_server` with no subject point gets this.
   Health is inferred from its direct dependents: the sources of its incoming `depends_on` and
   `invokes` edges, counted from the edges present in the same response (viewport page,
   neighbourhood or impact result), using each dependent's measured health. The node is:
   - `failing` when at least 2 dependents are failing and the failing share is at least
     `NS_MAP_DERIVED_FAILING_RATIO` (default 0.5);
   - otherwise `degraded` when at least 2 dependents are degraded or failing and that share is at
     least `NS_MAP_DERIVED_DEGRADED_RATIO` (default 0.34);
   - otherwise `unknown`.
   Fewer than 2 dependents is always `unknown`.
3. **Unknown.** Everything else.

An inferred value sets `health_inferred: true` on the node (and on an impact node). The rule can
return only `failing`, `degraded` or `unknown`, never `ok`: a lack of failing dependents is not
evidence that the node is healthy. Treat an inferred value as a hint to look, not as a reading.

MCP servers always read `unknown`: they have no subject key, and the catalog has no edge type
that makes something a dependent of an MCP server, so there is nothing to measure or infer from.

### Known limit: the health filter

The `health` filter on the viewport and search routes, and the health counts in a search
response, match measured health only. A node displayed as inferred-failing is not matched by
`health=failing`. Search `counts.by_health` likewise counts it as unknown.

## Filters

The viewport and search routes take repeatable `node_type`, `tag`, `environment`, `cloud` and
`health` parameters (at most 10 values each). Cluster counts and pages then reflect only matching
entities, and the response echoes the applied filters in `filters_applied` (null when none).
A value outside the allowed set, or too long, is 422 with reason `invalid_filter`. The
neighbourhood route takes no filters.

## Topology push

A client that is subscribed to a domain on the realtime WebSocket receives a `topology` message
when a node or edge it can read is added, removed or changed. No extra subscribe message is
needed.

- **Cadence.** The gateway checks at most once per `NS_MAP_TOPOLOGY_POLL_SECONDS` (default 3)
  per session and domain. A catalog change therefore reaches a connected client within about the
  poll interval plus the snapshot cache time (half the interval).
- **Baseline.** The first poll after subscribing records a snapshot and sends nothing. Only later
  differences are announced. An unchanged graph sends nothing except the usual heartbeat.
- **Shape.** `{"type": "topology", "seq", "domain_id", "changed_at", "change_kinds",
  "entity_ids", "refetch", "truncated", "emitted_at"}`. `change_kinds` is a subset of
  `node_added`, `node_removed`, `node_updated`, `edge_added`, `edge_removed`, `edge_updated`.
  `refetch` is always true: the message carries ids only, never a node body, so the client
  refetches the viewport.
- **Truncation.** At most 50 ids are listed. When more changed, `truncated` is true; refetch
  anyway. Person ids are never listed (the client only knows the pseudonym), although a person
  change still counts toward the change kinds.
- **Scope.** Each snapshot is taken with the session's own scope and cached under
  `scope_cache_key(scope, namespace="map-topology")` plus the domain, so two scopes never share
  one. A message follows the delta rules: the session's current scope is checked at send time, a
  domain it can no longer read is dropped with `scope_narrowed`, and a revoked session is closed.
  Sent messages are counted in the existing realtime counters.
- **Replicas.** Snapshots are per replica, so two replicas can announce the same change at
  slightly different times. A client must treat `topology` as idempotent: refetch, do not apply.
- **Scan cap.** A snapshot reads up to `NS_MAP_TOPOLOGY_SCAN_PAGES` pages of 500 entities
  (default 20, so 10,000 entities), then the edges under the same cap. A change beyond the cap is
  not notified, and nothing says so. This is a known limit. A failed snapshot is logged and
  retried on the next pump tick with no backoff.
- **Model deltas.** Model metric deltas use the same snapshot to map `provider/model` to the
  deployment ids the viewport shows. With `NS_MAP_TOPOLOGY_ENABLED=false`, or when no snapshot can
  be read, model nodes are dropped from deltas, since an id is never guessed.

## Search

`GET /search?q=&node_type=&tag=&environment=&cloud=&health=&limit=` scans the whole in-scope
domain on the server, not the viewport.

- The scan reads pages of 500 entities, up to `NS_MAP_SEARCH_SCAN_PAGES` pages (default 100, so
  50,000 entities) and within `NS_MAP_SEARCH_TIMEOUT_MS` (default 8000). When either stops it,
  `truncated` is true, `truncation_reason` is `scan_limit` or `timeout_ms`, and `coverage` is
  partial. Matches and counts then cover only what was scanned.
- `limit` is 1 to 50 (default 20), and `q` is at most 128 characters. Text matching is
  case-insensitive on the node's public label and id. Matches come back in node-kind order, then
  label, then id.
- `counts` (`by_kind`, `by_health`, `by_environment`, `by_cloud`) cover every match scanned, not
  only the returned page. Each match carries its node and `cluster_id`.
- A person is found only by pseudonym; a query for a real name returns nothing. Every entity is
  re-checked against the customer and domain.
- All matches of a request are held in memory before sorting, so a very broad query on a large
  domain is the heaviest call here.

## Neighbourhood and impact

**Neighbourhood.** `GET /neighborhood/{node_id}` returns a `ViewportResponse` with the node and
its direct neighbours in both directions. `node_budget` and `edge_budget` are clamped to the
server ceilings as on the viewport, and `truncated` is set when the result is over budget.

**Impact.** `POST /impact` with `node_id`, `max_depth` (1 to 5, default 3) and an optional
`budget` answers "what is affected if this node fails". The response has `direction:
"dependents"`: it lists entities that rely on the node, not what the node uses. It is built on the
PRP-73 dependents engine.

- `levels` is a list of `{depth, nodes, edge_ids}`. A node reachable at several depths is listed
  once, at the shallowest. Each node carries its health, with `health_inferred` where the
  fallback applied. People appear only as pseudonyms.
- `max_depth` above 5 is 422. A budget can only lower the server ceilings (1000 accessors, 10 s).
  When a ceiling is hit, `truncated` is true with a reason (`node_budget`, `scan_limit` or
  `timeout_ms`). Reaching the requested depth is not a truncation.
- Every dependent is re-read under the caller's scope and kept only if it is in the path domain.
  The node itself is read first, so an unreadable node is a 404 and not an empty answer.

## The 50k-node requirement

The original product text asked for graphs of at least 50k nodes and 250k edges at under 200 ms
interaction latency. The v1.2 scope restates it, and this PRP implements the restatement:

- The whole in-scope domain is searchable and filterable on the server (search, up to 50,000
  entities per request, with the caps above).
- The viewport stays cluster-first and bounded at 2000 nodes and 5000 edges. A browser never
  downloads the whole graph, which would sidestep the per-entity authorization checks.
- Raising either cap needs measured evidence and a later PRP.

This PRP does not claim the map meets the 50k-node or 200 ms criterion.

## Using the map: filters, search and incident view (PRP-77)

The client is `frontend/src/features/map/` (canvas) and `frontend/src/features/map-table/` (the
accessible table). Both read the same state from the URL, so a filtered or searched view can be
shared and survives a reload; the back button restores the previous filter.

- **Filter bar** (`map-filter-bar`): node type, environment, cloud, health and a tag. Option lists
  and their counts come from the search route's `counts` for the domain (one unfiltered
  `q=&limit=1` call). A tag must match the catalog tag pattern `^[a-z0-9][a-z0-9._-]{0,62}$`; an
  invalid tag is refused in the field and never sent. The UI sends one value per filter (the
  server accepts up to 10). "N filters applied, clear all" resets them. A filter change refetches
  the viewport and every open cluster with the same parameters.
- **Search** (`map-search`, results `map-search-result`): at least 2 characters, debounced, the
  previous request aborted on each keystroke, result count announced politely. Each row shows kind,
  environment and health as text; a person shows the pseudonym label only. Choosing a result on
  screen selects and centres it; one off screen is fetched with the neighbourhood route and merged
  under the 2000-node client cap (the farthest unselected leaf nodes of the previous view are
  dropped first; dropped and skipped counts are shown as text). In the table, a loaded row is
  focused; a row in a closed cluster is expanded and focused; a row not on a loaded page is reported
  as text ("Use Load more" or "not in the table with the current filters").
- **Incident view**: "Show impact" (`show-impact`) in the node panel, or `i` with a node selected
  (ignored while typing). It calls the impact route with depth 2 (control 1 to 5), rings every
  dependent node and thickens its edges while dimming the rest, and lists the dependents by depth
  with their health as text (`impact-list`, heading "Depends on this node"). Dependents not on
  screen have a "show on map" action. While it is on, a live delta that turns the node or a
  dependent `failing`, or a topology push, recomputes after 2 s (once per burst) and the polite
  status (`impact-status`) says how many dependents are affected. If the selected node itself turns
  `failing`, the view starts by itself; any other node that turns failing raises a banner
  (`impact-banner`) instead, so the map never moves under the user. The table has the same toggle
  (`I` on a focused row) with a depth column.
- **Topology push**: a `topology` message with `refetch: true` triggers one refetch per burst
  (400 ms quiet, 2 s maximum wait) of the top level and every open cluster, with the active
  filters. Camera, selection and node positions are kept. Removed nodes disappear on the next
  reload (issue #406).
- **Live metrics**: a delta that leaves a metric null keeps the last known value; model nodes now
  update live because delta ids match viewport ids.
- **Node kinds**: service (pentagon), tool (cross) and MCP server (octagon) have their own shape
  and text label in the legend; an unknown kind from a newer server is drawn as a generic node
  with its raw kind name.

## Interaction-latency evidence

`frontend/tests/e2e/map-latency.spec.ts` renders the 2000-node, 4000-edge fixture with the same
fake realtime gateway as `map-perf.spec.ts` and measures, 30 samples each by default, the time from
the real input event to the second `requestAnimationFrame` after it (taken in the page with
`performance.now()`, so no Playwright round-trip is counted) for pan, wheel zoom, node hover, node
click and the "Show impact" highlight (until the first impact row is painted).

| Variable | Effect |
|---|---|
| `NS_MAP_PERF_HEADED=1` | Headed Chromium on the real GPU (the only product evidence) |
| `NS_MAP_LATENCY_WRITE_EVIDENCE=1` | Writes `docs/evidence/G07/map/interaction-latency.json`; otherwise the result goes to `temp/map-latency/` |
| `NS_MAP_LATENCY_ENFORCE=1` | Fails the test unless every p95 is at most 200 ms |
| `NS_MAP_LATENCY_SAMPLES` | More samples (minimum 30) |
| `NS_MAP_LATENCY_NODE_INPUT` | `pointer` (real GPU picking) or `emit` (real input, then the sigma node event raised from the page). Headless defaults to `emit`; the pointer mode does not yet hit nodes on the perf fixture (#406) |
| `NS_MAP_LATENCY_RUN=1` | Runs the spec in CI (skipped there by default: 11 to 26 minutes headless) |

Re-measure on operator hardware (PRP-66), on a quiet machine. Until the harness picking in #406 is
fixed, also set `NS_MAP_LATENCY_NODE_INPUT=emit` (the committed 2026-11-24 run did); otherwise the
headed default `pointer` collects no click samples and the run fails:

```bash
cd frontend && NS_MAP_PERF_HEADED=1 NS_MAP_LATENCY_WRITE_EVIDENCE=1 NS_MAP_LATENCY_ENFORCE=1 NS_E2E_APP_PORT=5299 NS_MOCK_API_PORT=5300 pnpm exec playwright test map-latency
```

The file records `mode` (headed or headless), `browser` (name, version, `webgl_renderer`), `host`
(OS, CPU model, logical cores, RAM, Node), `scene` (node and edge counts), per interaction
`samples`, `p50_ms`, `p95_ms`, `max_ms`, `meets_target` and, where nodes were not picked by the
pointer, `node_targeting`, plus `target_p95_ms` (200), overall `meets_target`, `enforced` and a
plain-language `note`. A number is valid only for the hardware in the file and only for the 2000
node view; it is never a 50k-node result.

## Settings

All are read once at startup and range-checked; an invalid value fails startup. Unknown `NS_MAP_*`
names are rejected.

| Variable | Default | Range | Effect |
|---|---|---|---|
| `NS_MAP_TOPOLOGY_ENABLED` | `true` | true or false | Turns the topology push off. Also drops model delta nodes |
| `NS_MAP_TOPOLOGY_POLL_SECONDS` | `3.0` | 1 to 60 | Topology check interval per session and domain |
| `NS_MAP_TOPOLOGY_SCAN_PAGES` | `20` | 1 to 200 | Pages of 500 per snapshot scan (entities, then edges) |
| `NS_MAP_SEARCH_SCAN_PAGES` | `100` | 1 to 200 | Pages of 500 per search |
| `NS_MAP_SEARCH_TIMEOUT_MS` | `8000` | 100 to 60000 | Search deadline |
| `NS_MAP_DERIVED_FAILING_RATIO` | `0.5` | above 0, up to 1 | Failing share of dependents for the inferred `failing` |
| `NS_MAP_DERIVED_DEGRADED_RATIO` | `0.34` | above 0, up to 1 | Degraded-or-worse share for the inferred `degraded` |

The scan reads real request units on Cosmos (100 pages of 500 per search). Do not raise the
defaults without the recorded timings.

## Server timings

Measured server timings for the viewport at 2000 nodes, search over a seeded 50k-entity world,
impact at depth 5 and one topology poll, with the hardware stated, are in
`docs/evidence/G07/map/server-timings.json`. Read the file for the numbers and for what did not
run. No target is asserted in CI.

## Rollback

No data migration: there is no new container and no stored field. Set
`NS_MAP_TOPOLOGY_ENABLED=false` to stop the push (the viewport, search and impact keep working).
For the rest, revert the PR. The viewport route called without the new parameters behaves as it
did before, but its nodes now include the new kinds and `facets`; a client that rejects unknown
node kinds must be updated first (PRP-77 draws them).

## Open gates

These did not run and are reported open:

- Real-Cosmos request-unit cost and latency for a 50k-entity search (only the emulator or an
  in-memory world was used).
- The headed frame-rate and interaction-latency re-measure on operator hardware (PRP-66).
- The hosted-environment check (PRP-82).

Other known limits: topology notices stop at the scan cap; the inferred health rule only sees
dependents present in the same response; per-edge traffic volume is not built (request count is
per node); a metric delta carries `context_size: null`, meaning "not carried", and the client
keeps the last known value (PRP-77). Client follow-ups from PRP-77 are in issue #406.
