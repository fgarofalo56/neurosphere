### Added
- Live map topology backend (PRP-74). The viewport now returns `service`, `tool` and `mcp_server`
  nodes, and every node carries `facets` (entity type, environment, cloud, tags, lifecycle,
  health, error rate and count, request count, sensitivity, residency). The viewport takes
  repeatable `node_type`, `tag`, `environment`, `cloud` and `health` filters; an unknown value is
  422 `invalid_filter`.
- `GET /api/v1/map/domains/{domain_id}/search` scans the whole in-scope domain on the server and
  returns a bounded list with per-kind, health, environment and cloud counts, and a truncation
  reason when the scan cap or time limit stopped it. `GET .../neighborhood/{node_id}` returns a
  node and its direct neighbours. `POST .../impact` lists what depends on a node, grouped by
  depth 1 to 5. All three need `data.read` on the path domain.
- The realtime socket pushes a `topology` message (changed ids, change kinds, `refetch`) when the
  catalog adds, removes or changes a node or edge in a subscribed domain. Settings:
  `NS_MAP_TOPOLOGY_ENABLED`, `NS_MAP_TOPOLOGY_POLL_SECONDS`, `NS_MAP_TOPOLOGY_SCAN_PAGES`,
  `NS_MAP_SEARCH_SCAN_PAGES`, `NS_MAP_SEARCH_TIMEOUT_MS`, `NS_MAP_DERIVED_FAILING_RATIO` and
  `NS_MAP_DERIVED_DEGRADED_RATIO`.
- Runbook `docs/runbooks/live-map.md`.

### Changed
- A service, tool or MCP server with no measured subject point gets an inferred health from its
  failing dependents, flagged `health_inferred` and never `ok`. The `health` filter matches
  measured health only.
- Model deltas on the realtime socket now carry the viewport's deployment ids; with the topology
  switch off they are dropped.
- Known limits: topology changes beyond `NS_MAP_TOPOLOGY_SCAN_PAGES` pages are not notified. The
  viewport stays bounded at 2000 nodes and 5000 edges; the map is not claimed to meet the
  50k-node or 200 ms criterion.
