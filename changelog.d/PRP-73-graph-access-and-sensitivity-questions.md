### Added
- Data access questions (PRP-73): `POST /api/v1/catalog/access/query` lists the in-scope agents
  with a `reads` or `writes` edge to named data assets, or to the assets matching a filter on
  sensitivity category, the personal-data flag, classification, residency region or region
  group. Each row carries the mode, edge status (asserted, inferred, curated), confidence,
  provenance, evidence ids and last-observed time. Rows are observed access, not entitlements.
- `POST /api/v1/catalog/access/dependents` lists the entities that depend on a failing service
  or tool, grouped by depth 1 to 5 with the relation path.
- `GET /api/v1/catalog/access/region-groups` returns the region groups for the caller's cloud.
  The groups `eu` (locations in EU member states) and `europe` (the Azure Europe geography
  list) are a point-in-time copy from Microsoft Learn in `region_groups.yaml`, empty for the
  Government cloud. They are location lists, not a legal determination.
- All three routes require `data.read`, derive scope only from the server identity and are also
  served under the `/catalog/access` alias. The query and dependents routes write one
  allowed-read audit record holding the domains read and the result count only.
- Page `/catalog/access` ("Data access") with the three questions, a dependents panel, a result
  table and a partial-result banner; a nav entry gated on `data.read`; the runbook
  `docs/runbooks/catalog-access.md`.
- The catalog projection infers `reads` and `writes` edges from telemetry `data_source_refs`
  that name a canonical `grounding_source` of the event's own cloud and customer (rule
  `data_source_ref`). Refs with unknown access, a foreign owner, a non-canonical id or another
  entity type are counted and skipped. An asset that is not in the catalog is quarantined with
  reason `asset_unresolved`; no asset entity is created. Setting
  `NS_WORKER_CATALOG_DATA_ACCESS_EDGES` (default true) turns the rule off.
- Core `neurosphere_core.catalog.graph.access` (`AccessEngine`, `AccessQuery`, `AccessResult`)
  for later map and copilot work to reuse.

### Changed
- Every access answer is bounded and says so: fixed server ceilings on assets scanned,
  accessors, depth and time that a request can only lower, and `truncated`, `truncated_reason`
  and `assets_scanned` on every response.
- An asset with no recorded sensitivity, classification, region or personal-data value is
  reported as not assessed, and only when asked for. It is never counted as a match or as a
  non-match.
- A `residency_regions` filter value that is not a known region of the caller's cloud is a 422
  `unknown_region`. A request body that carries customer, cloud or domain scope fields is
  refused with 422.
- Known limits of this release follow.
- Telemetry that names assets with a `data_asset` type segment produces no inferred edges;
  only `grounding_source` ids do.
- Evidence ids are shown as text; there is no evidence link target yet.
- Asset filtering is an application-side bounded scan. Its Cosmos request-unit cost is not
  measured, and visual baselines for the new page are not captured.
