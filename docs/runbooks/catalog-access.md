# Catalog data access questions

PRP-73. Three read-only questions over the relationship catalog, on the page `/catalog/access`
("Data access", Agents navigation, shown to callers with `data.read`). They answer what the catalog
has observed, not what anyone is entitled to do.

| Question | Route | Permission |
|---|---|---|
| Who reads or writes this data asset, who touches personal or regulated data, who touches data held in a region group | `POST /api/v1/catalog/access/query` | `data.read` |
| What depends on a failing service or tool, grouped by depth | `POST /api/v1/catalog/access/dependents` | `data.read` |
| Which region groups exist for the caller's cloud | `GET /api/v1/catalog/access/region-groups` | `data.read` |

Each route is also served at the alias `/catalog/access/...` (see `api-path-aliases.md`). Customer,
cloud and domain always come from the caller's identity; a scope field in the body is ignored. An
accessor in a domain the caller cannot read is never returned or counted.

## What each question answers

- **Who writes (or reads) this asset.** Pick one or more `grounding_source` assets and a mode. Each
  row is an edge from an agent, tool or service to the asset: accessor, mode, edge status
  (asserted, inferred, curated), confidence, provenance, last observed time and evidence ids.
- **Who touches personal or regulated data.** Filter assets by sensitivity category,
  `contains_personal_data`, classification or residency region; the filters combine with AND. Same
  result shape.
- **Who touches data held in a region group.** Choose a group such as `eu` or `europe`. Same result
  shape.
- **Dependents.** Enter the canonical id of a service or tool and a depth from 1 to 5. Rows are
  grouped by depth and carry the relation path from the dependent to the node.

Results are observed access: edges the catalog holds from declaration, telemetry or steward
curation. They are not entitlements and do not say what a principal could do.

## Scan bound and the partial-result banner

The scan is bounded. The ceilings are fixed in the engine
(`packages/core/neurosphere_core/catalog/graph/access.py`); a request can lower them through the
`budget` field and can never raise them.

| Bound | Ceiling |
|---|---|
| Asset pages read (500 assets each) | 10 pages |
| Assets examined | 2000 |
| Accessor rows returned | 1000 |
| Walk depth | 5 |
| Time | 10 000 ms |
| Asset ids named in one request | 50 (more is 422 `too_many_assets`) |

When a bound stops the scan the response says `truncated` with a `truncated_reason`
(`max_assets`, `max_accessors`, `max_depth` or `timeout_ms`) and the page shows a **partial result**
banner. A partial list is missing rows that were not reached: do not read it as complete. Narrow
the question (a named asset, a domain, a stricter filter) and ask again.

## "Not assessed"

A null or empty `sensitivity_categories`, an unknown or null `classification`, a null
`residency_region` and a null `contains_personal_data` are never treated as "no". An asset with no
recorded value for the question is neither a match nor a non-match. Tick **Include assets that are
not assessed** to list those assets separately under "Not assessed". They are counted separately and
never mixed into the result rows.

## An inferred edge is evidence, not a verdict

Edges with status `inferred` come from telemetry: the catalog projection turns `data_source_refs`
on model-call events into `reads` or `writes` edges with the rule `data_source_ref`, using the same
confidence scale as other inferred edges. They are evidence that an access was observed, with a
confidence, not a finding that it was allowed or intended. A steward can reject a wrong one through
the curation routes (the edge page); a rejected edge drops out of results. Evidence ids are shown as
text for now; there is no evidence viewer link yet.

To stop new inference without a revert, set the worker setting
`NS_WORKER_CATALOG_DATA_ACCESS_EDGES=false` (default `true`) and restart the catalog projection
worker. Edges already written stay as ordinary inferred edges.

## Region groups

`eu` and `europe` are NeuroSphere's classification of Azure region locations, taken from Microsoft
Learn (the regions list), not a legal determination of where data may be held. The data lives in
`packages/core/neurosphere_core/catalog/graph/data/region_groups.yaml` with `source_url` and
`source_retrieved`. It is a point-in-time copy: re-check it against the source and refresh the file
when Microsoft adds or moves regions. The Government cloud has no groups. Naming a region that is
unknown for the caller's cloud is rejected with 422 `unknown_region`; an unknown group is 422
`unknown_region_group`.

## Audit

Each `query` and each `dependents` call writes one allowed-read audit record on the caller's domain
chain (operations `catalog.access_query` and `catalog.dependents`). The record holds the domains read
and the result count only, never asset names, ids, filter values or terms. A failure to write the
audit record does not change the response. `region-groups` returns static data and is not audited.
A denied call is recorded by the authorization layer like any other denial.

## Not covered

No entitlement ("who could") question, no export of results, no label ingestion, and no statement
that an estate, an agent or an asset meets any framework. The cost of the bounded scan on a live
Cosmos account is unmeasured and is tracked with the other catalog measurements (PRP-64).
