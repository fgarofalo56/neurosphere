---
name: PRP-73-graph-access-and-sensitivity-questions
status: active
started: 2026-11-20
priority: P0
order: 63
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-02, NS-05, NS-08
depends_on: [PRP-70-contracts-revision-restored-scope]
wave: W20
branch: prp-73-graph-access-questions
allow_parallel: true
issues: []
---

# PRP-73: Graph access and sensitivity questions

## Goal
Answer the three graph questions the original PRD promised, as bounded structured API routes and one page a compliance officer can use: which agents read or write a named data asset ("write access to the customer database"), which agents touch data that is personal, regulated (PII, PHI, CUI) or held in the EU, and which agents are affected when a service or tool fails (blast radius, with a depth control). Every answer is scope-filtered, carries the edge status, confidence, provenance and evidence ids, labels truncation, and writes an allowed-read audit record. It also starts producing the `reads` and `writes` edges the questions depend on, by projecting them from the `data_source_refs` that telemetry events already carry, so the answer is not limited to hand-declared edges. It is for the compliance officer, the SRE and PRP-78 (the copilot graph tool builds on the same core engine). It runs in W20 on the contracts shipped by PRP-70 (sensitivity vocabulary, tags, environment).

Out of scope: the registration form, owner and data-scope pickers and the edge-assert route (PRP-76); version history and the undeclared-agent list (PRP-76); the live map, its filters and the impact highlight on the map (PRP-74 backend, PRP-77 frontend; PRP-74 should call the `dependents` function provided here instead of writing its own walk); the copilot `graph_query` tool (PRP-78); classification-aware (attribute-based) read rules, which the original acceptance criteria never required; any generated Cypher, SQL or Gremlin (a hard constraint).

## Why
Original PRD (2026-10-02, `git show 9fbf5f4c:docs/PRD.md`) stories and criteria this restores:
- 5b: "As a compliance officer, I want to query "which agents have write access to the customer database.""
- 5e: "As an operations lead, I want to ask "which agents touch EU customer data?" and get a grounded answer with citations to graph nodes."
- 5d: "As an SRE, I want to see, during an incident, every downstream agent affected by a failing service, highlighted live."
- 5g: "As a compliance officer, I want an audit trail of every data access and agent-to-data-asset relationship." The persona "Dana" "needs to prove data lineage, access boundaries, and audit trails across agents touching regulated data (PII, PHI, CUI)."

What v1.2 removed or demoted: `docs/PRD.md:17` reduces NS-02 lineage to "scope-filtered lineage" and nothing in v1.2 names PII, PHI, CUI, EU data, write access or blast radius (grep of `docs/PRD.md` and `PRP.md` finds none); `PRP.md:12` states the catalog "is not a native arbitrary graph query engine" and `docs/PRD.md:30` bans "generated JavaScript or unrestricted SQL/Cypher/KQL". Those two rules stay; the questions do not need a query engine.

Evidence from the current tree (re-verified in this worktree):
- The API can only answer by hand: `POST /api/v1/catalog/lineage/neighbors` and `/lineage/impact` (`services/api/neurosphere_api/catalog/router.py:275-298`) take one node id; no route filters assets by `classification`, `residency_region` or `contains_personal_data` (`EntityFilter`, `packages/core/neurosphere_core/catalog/protocol.py:141-148`, offers only entity type, domain and lifecycle). The entity page shows a mixed neighbour table with no relation filter (gap analysis 5b; `frontend/src/features/catalog/CatalogEntityPage.tsx:171-219`).
- The data exists on the asset: `grounding_source` carries `classification`, `residency_region` and `contains_personal_data` (`packages/contracts/python/neurosphere_contracts/catalog/v1/grounding_source.py`), but no PII, PHI or CUI vocabulary (PRP-70 adds `sensitivity_categories`).
- `reads` and `writes` edges are never inferred: the projection maps only `uses_model` and `invokes` (`services/workers/neurosphere_workers/projections/catalog/mapping.py:172-200`), although the telemetry envelope carries `data_source_refs[].ref` and `access` of `read | write | unknown` (`packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:83-97`). Only `tool_call_candidates` reads the field, and only for tool refs.
- Blast radius is a fixed-depth table on the entity page and is not on any API shaped for "affected agents grouped by distance"; `RepositoryGraphQuery.impact_paths` (`catalog/graph/query.py:147-155`) supports `upstream` (edges pointing at the node, that is, its dependents) within the ceilings depth <= 5, 5000 nodes, 20000 edges.
- Allowed reads are audited on five operations only (`services/api/neurosphere_api/authz/read_audit.py:1-27`); the lineage routes have none.

## Acceptance criteria
- [ ] Given an asset id that the caller may read, When `POST /api/v1/catalog/access/query` names it with `modes: ["write"]`, Then the response lists every in-scope agent with a `writes` edge to it, each with `mode`, edge `status` (asserted, inferred, curated), `confidence`, `provenance` method and source, `evidence_ids`, `last_observed`; a hidden (rejected) edge is omitted; an agent outside the caller's scope never appears, not even as a count.
- [ ] Given assets with `contains_personal_data: true` or a PRP-70 sensitivity category (pii, phi or cui) in several domains, When the query names `filters.sensitivity_categories` or `contains_personal_data`, Then only in-scope assets matching are scanned and their accessors returned; an asset with a null (unassessed) value is never treated as false: it is reported under `unassessed_assets` with a count when the caller asks for `include_unassessed`.
- [ ] Given assets with `residency_region` values, When the query names `filters.region_group: "eu"` or explicit `residency_regions`, Then matching assets and their accessors are returned; the `eu` group is data (a file with source URL and retrieval date), empty for the Government cloud, and an unknown group or region is a 422 with a reason code.
- [ ] Given a failing service or tool, When `POST /api/v1/catalog/access/dependents` names it with `max_depth` 1 to 5, Then affected in-scope entities are returned grouped by depth with the relation path; the walk stops at the budget and the response says `truncated` with the reason; depth above 5 is a 422.
- [ ] Every response carries `truncated`, `truncated_reason` (`max_assets`, `max_accessors`, `max_depth`, `timeout_ms`) and `assets_scanned`; a result is never presented as complete when a bound stopped the scan; the server ceilings are fixed and a request can only lower them.
- [ ] Given telemetry events whose `data_source_refs` hold a canonical `grounding_source` id of the event's own cloud and customer with `access` `read` or `write`, When the catalog projection runs, Then an `inferred` `reads` or `writes` edge candidate exists agent to asset with trace evidence ids and confidence from the existing rule scale; `unknown` access, a foreign cloud or customer, a non-canonical ref and a ref of another entity type create no edge and are counted, never raised.
- [ ] Each of the three routes requires `data.read`, derives scope only from the server identity, ignores any customer, cloud or domain in the body, and appends one allowed-read audit record through `audited_read` (domains read and result count; never asset names, filter values or terms); an audit-store failure is logged and counted and never blocks the read (PRP-48 decision 3).
- [ ] Page `/catalog/access` offers the three canned questions and a free pick of asset, shows the result table with status, confidence and evidence links, shows a partial-result banner when truncated, has loading, empty, error and forbidden states, passes axe in light, dark and high-contrast, and uses no wording that says an estate is compliant.
- [ ] Every new route is in the route inventories and boots under the startup route check; the `/catalog/access` alias prefix passes the path-alias suite.
- PRP exit: a compliance officer opens `/catalog/access`, picks "who writes to this data asset", and sees the writers with evidence; picks "who touches PII" and "who touches EU data" and sees the same shape; an SRE enters a failing service and sees dependents by depth; each read left an audit record.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How to filter assets by classification, residency, personal data | Add Cosmos filter fields and backfill existing documents; filter application-side over a bounded scan | ASSUMPTION: application-side over a bounded, scope-filtered scan of `grounding_source` entities (`list_entities` by entity type, at most `MAX_ASSET_PAGES` pages). The backend `Field` allowlist (`catalog/repo/backend.py:21-36`) and stored `filters` would need a data backfill; defer that to a measured need and report the scan bound in every response |
| 2 | Route shape | Extend `/lineage/*`; new `/access/*` family | New family under `/api/v1/catalog/access` (with the `/catalog/access` alias like every catalog route) so the existing lineage contracts and `openapi.json` components do not change |
| 3 | Models | Contracts schema; API-local Pydantic | API-local models in `catalog/access/models.py`; PRP-70 is sole owner of `packages/contracts/**` in W19 and PRP-78 builds on the core engine, not on a schema |
| 4 | Sensitivity vocabulary | Reuse `classification`; PRP-70 list | Consume PRP-70's `sensitivity_categories` (pii, phi, cui, financial and so on; exact names from PRP-70 "Interfaces provided"); `classification` stays a separate filter |
| 5 | Who may ask | `data.read`; a new permission | `data.read` (the lineage routes' permission). The question names sensitive categories, not their content. ASSUMPTION: no new permission |
| 6 | Audit record content | Record the filter values; domains and count only | Domains read and result count only (the `audited_read` contract); the operation name is `catalog.access_query` or `catalog.dependents`. Filter values are not recorded, as with search terms |
| 7 | Telemetry-inferred edges | Only declared edges; infer from `data_source_refs` | Infer. Whether the normaliser keeps `data_source_refs` through to the projection input is UNVERIFIED (gap analysis section 6): item 2 first reads `LoadedEvent` and the ingest normaliser; if the field is dropped, the item reports it and the inference half is descoped to a follow-up with declared edges still answering |
| 8 | EU region list | Hard-code; data file | Data file with a source URL and retrieval date. Subagents have no Microsoft Learn tool: the orchestrator reads the Azure geographies page and pastes the Europe region names into the brief; the list is never written from memory |
| 9 | "Downstream" semantics | Edges out of the node; things that depend on the node | Dependents: entities whose edges lead to the failing node, that is `impact_paths(direction="upstream")`. The route is named `dependents` so the direction cannot be misread |
| 10 | Label precedence and "who could" | decide now; leave open | Precedence the engine and the filters must honour once customer labels arrive (PRP-120): a steward-curated value is locked and wins, then a customer label mapped to a sensitivity category, then inference from telemetry or declared fields. Today only the curated and inferred layers exist; the engine reads an effective value through one function so a label layer slots in without a route change. Responses are phrased as "who did" (observed edges); PRP-119 adds "who could" beside them under `catalog/access/could/**`, which this PRP does not create |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/catalog/graph/query.py` - `RepositoryGraphQuery._walk`, `impact_paths`, scope cache, truncation reasons; the new engine reuses its scope rule.
- `packages/core/neurosphere_core/catalog/protocol.py:141-160,199-340,347-470` - `EntityFilter`, `EdgeFilter`, `CatalogRepository.list_entities`, `list_edges_by_node`, `PresentedEdge`, `GraphResult`, `ImpactRequest`.
- `packages/core/neurosphere_core/catalog/rules.py` - `present_edge` (locks, overrides, hidden) to present edges the way lineage does.
- `services/api/neurosphere_api/catalog/router.py:108-140,263-300,365-376` - budget clamp, `ReadScope`, lineage routes, `register`.
- `services/api/neurosphere_api/catalog/curation/router.py:172-173` and `services/api/neurosphere_api/routers.py:100-110,282-283` - how a sibling router registers with an alias and a hook.
- `services/api/neurosphere_api/authz/read_audit.py` - `audited_read`, `ReadAudit.allowed`.
- `services/workers/neurosphere_workers/projections/catalog/mapping.py:100-200` and `handler.py` (around the `tool_call_candidates` call) - candidate construction and the owned-id check.
- `packages/contracts/python/neurosphere_contracts/catalog/v1/grounding_source.py` and `telemetry/v1/telemetry_event.py:83-97` - the fields consumed.
- `frontend/src/features/catalog/explorerHooks.ts:47-50`, `CatalogEntityPage.tsx:171-219`, `routes.tsx`, `paths.ts` - existing neighbour and impact hooks and route registration.
- `services/api/tests/read_audit_api/conftest.py` - fixture for audit-record assertions.

### Interfaces consumed
- PRP-70 (contracts): `sensitivity_categories` on `grounding_source` with its vocabulary; `tags`, `capabilities`, `environment` on agent, tool and service (shown in result rows only). Names are taken from PRP-70 "Interfaces provided" at execution; this PRP does not write contracts.
- Shipped: `CatalogRepository`, `GraphQuery` and `get_graph`, `get_repository` providers (PRP-10, `catalog/dependencies.py`); `audited_read` (PRP-48); `RouterRegistry` and `register_with_alias`; the projection candidate and edge-write path (PRP-10, PRP-43 quarantine); `Permission.DATA_READ`.

### Interfaces provided
- Core: `neurosphere_core.catalog.graph.access` - `AccessQuery`, `AccessResult`, `AccessRow`, `AccessEngine` with `who_accesses(scope, query: AccessQuery) -> AccessResult` and `dependents(scope, node_id, max_depth, budget) -> AccessResult` (rows grouped by depth with the relation path, `truncated` and a reason), constants `MAX_ASSET_PAGES`, `MAX_ACCESSORS`; `region_groups` loader over `catalog/graph/data/region_groups.yaml`. PRP-74 and PRP-78 import these; they never re-implement the walk.
- Routes (all `data.read`, all with the `/catalog/access` alias): `POST /api/v1/catalog/access/query`, `POST /api/v1/catalog/access/dependents`, `GET /api/v1/catalog/access/region-groups` (names and member regions only).
- Audit operations `catalog.access_query`, `catalog.dependents`; component name none (no builder change).
- Worker: `data_access_candidates(loaded)` in `projections/catalog/mapping.py`, rule name `data_source_ref`.
- Frontend route `catalog/access` (`CATALOG_ACCESS_ROUTE`) and mock handlers `frontend/tests/mock-api/features/catalog-access.ts`.
- Compatibility with PRP-76 (W24, edits `catalog/**` after this merges): this PRP touches only new files under `catalog/graph/access.py`, `catalog/graph/data/**`, `catalog/access/**` and one hook line in `routers.py`; it does not edit `catalog/router.py`, `catalog/service.py`, `catalog/protocol.py`, `catalog/repo/**`, `EntityForm.tsx`, `entityFormModel.ts` or `StaleAgentsPage.tsx`, which PRP-76 edits. The two shared frontend files are `routes.tsx` and `paths.ts` (this PRP appends one route; PRP-76 appends its own after rebase).

### Patterns to match
- Router with alias and read audit: `catalog/router.py:117,263-273`; registration: `catalog/curation/router.py:172-173`.
- Bounded scan with page cap and truncation flag: `catalog/service.py:562-602` (`_stale_candidates`, `MAX_SCAN_PAGES`).
- Scope rule (an id the repository does not return for this scope never surfaces): `catalog/graph/query.py` `_walk`/`edges_among`.
- Candidate builders: `mapping.py:172-200`; worker tests: `services/workers/tests/projections/test_catalog_projection.py`.
- Frontend page and mock pairing: `frontend/src/features/catalog/StaleAgentsPage.tsx`, `frontend/tests/mock-api/features/catalog.ts`.

### Gotchas
- `EntityFilter` is `extra="forbid"`; do not add fields to it here (PRP-76 owns `protocol.py` edits in W24). Filter inside `access.py`.
- Stored documents were written before PRP-70: a null `sensitivity_categories` means unassessed, not none. Never turn null into false (the contract says `contains_personal_data` is "null when not assessed").
- `list_edges_by_node` filters on the edge's own domain; whether the other endpoint is in scope is a graph-level rule, so fetch each accessor through `get_entity(scope, id)` and drop what it does not return.
- The telemetry example uses a `data_asset` type segment (`telemetry-event.full-model-call.json`) while the catalog id pattern for assets is `grounding_source`; only `grounding_source` ids create edges. If the ingest side should map `data_asset`, report it, do not alias it here.
- The access query scans entities of one type; a customer with more assets than the bound gets a truncated, labelled answer, not a silent subset.
- Same-named test directories shadow each other: new tests use the unique names below.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/catalog/graph/access.py
  - packages/core/neurosphere_core/catalog/graph/region_groups.py
  - packages/core/neurosphere_core/catalog/graph/data/**
  - packages/core/tests/catalog_access/**
  - services/api/neurosphere_api/catalog/access/**
  - services/api/tests/catalog_access_api/**
  - services/workers/neurosphere_workers/projections/catalog/mapping.py
  - services/workers/neurosphere_workers/projections/catalog/handler.py
  - services/workers/tests/projections_data_access/**
  - tests/security/authz/test_catalog_access*.py
  - frontend/src/features/catalog/access/**
  - frontend/src/features/catalog/routes.tsx
  - frontend/src/features/catalog/paths.ts
  - frontend/tests/mock-api/features/catalog-access.ts
  - frontend/tests/e2e/catalog-access/**
  - docs/runbooks/catalog-access.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - packages/core/neurosphere_core/catalog/repo/**
  - packages/core/neurosphere_core/catalog/graph/query.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/catalog/service.py
  - services/api/neurosphere_api/runtime/builders/**
  - services/api/neurosphere_api/authz/read_audit.py
  - frontend/src/features/catalog/EntityForm.tsx
  - frontend/src/features/catalog/entityFormModel.ts
  - frontend/tests/mock-api/server.ts
  - services/api/neurosphere_api/catalog/access/could/**
  - frontend/src/features/catalog/access/could/**
```

## Implementation blueprint

Parallelization: items 1 and 2 are [P] (core engine and worker mapping share no file). Item 3 needs 1. Item 4 needs 3. Item 5 needs the models from item 3. Item 6 needs 5; item 7 last.

### Item 1 - Access engine and region groups in core  [P]
- Deliverable: `access.py` with `AccessQuery` (asset ids at most 50, filters for classification, sensitivity categories, `contains_personal_data`, residency regions or group, domain ids, modes read and write, `include_unassessed`, budget), `AccessResult`, `AccessEngine.who_accesses` (bounded scan of `grounding_source` entities, application-side predicates, `list_edges_by_node` direction in for `reads` and `writes`, accessors re-fetched through `get_entity`, edges presented through `rules.present_edge`) and `AccessEngine.dependents` (wraps `GraphQuery.impact_paths(direction="upstream")`, groups by depth, adds the relation path). `region_groups.py` plus `data/region_groups.yaml` (`eu` for Commercial; empty for Government; `source_url`, `source_retrieved`).
- Owned files: `packages/core/neurosphere_core/catalog/graph/{access,region_groups}.py`, `catalog/graph/data/**`, `packages/core/tests/catalog_access/**`.
- Must NOT touch: `protocol.py`, `repo/**`, `graph/query.py`.
- Depends on: PRP-70 merged.
- Acceptance criteria: criteria 1 to 5; null never counted as false; hidden edges omitted; out-of-scope accessors never returned or counted; ceilings fixed and only lowerable; the unknown group raises a typed error with a reason code.
- Tests: `packages/core/tests/catalog_access/test_who_accesses.py`, `test_sensitivity_filters.py`, `test_dependents.py`, `test_truncation.py`, `test_region_groups.py` (use the in-memory repository, a two-domain world).
- Pattern references: `catalog/service.py:562-602`, `catalog/graph/query.py` scope handling.

### Item 2 - Telemetry-inferred reads and writes  [P]
- Deliverable: first confirm in the ingest normaliser and `LoadedEvent` that `data_source_refs` reaches the projection input and report the result; then `data_access_candidates(loaded)` in `mapping.py` (for each ref with `access` read or write and a canonical `grounding_source` id owned by the event's cloud and customer, an `EdgeCandidate` `reads` or `writes` agent to asset, rule `data_source_ref`, existing confidence scale, evidence ids as for the other rules) and its call in `handler.py` beside `tool_call_candidates`; a counter for skipped refs by reason (`unknown_access`, `foreign_owner`, `not_canonical`, `wrong_type`).
- Owned files: `services/workers/neurosphere_workers/projections/catalog/{mapping,handler}.py`, `services/workers/tests/projections_data_access/**`.
- Must NOT touch: `discovery.py`, `quarantine*.py`, ingest code.
- Depends on: none.
- Acceptance criteria: criterion 6; the same event projected twice yields one edge (idempotent); unresolved assets follow the existing quarantine path rather than being created implicitly (no entity creation for assets); existing projection tests pass unchanged.
- Tests: `services/workers/tests/projections_data_access/test_data_access_candidates.py`, `test_handler_edges.py`; re-run `services/workers/tests/projections`.
- Pattern references: `mapping.py:172-200`, `services/workers/tests/projections/catalog_support.py`.

### Item 3 - API routes with read audit
- Deliverable: `catalog/access/{__init__,router,models,deps}.py` with the three routes in "Interfaces provided", `audited_read(Permission.DATA_READ, "catalog.access_query")` and `"catalog.dependents"`, budget clamp reusing `clamp_budget`, 422 reason codes for unknown group, region, depth and asset count; `register(registry)` using `register_with_alias`.
- Owned files: `services/api/neurosphere_api/catalog/access/**`, `services/api/tests/catalog_access_api/**`.
- Must NOT touch: `catalog/router.py`, `catalog/service.py`, `runtime/builders/**`.
- Depends on: item 1.
- Acceptance criteria: criteria 7 and 9 (API part); body-supplied customer, cloud or domain ignored; the audit record holds domains and count only (asserted by reading the stored record); audit failure does not change the response.
- Tests: `services/api/tests/catalog_access_api/test_access_routes.py`, `test_dependents_route.py`, `test_read_audit.py`, `test_budget_clamp.py`.
- Pattern references: `catalog/router.py:263-298`, `services/api/tests/read_audit_api/test_search_reads.py`.

### Item 4 - Authorization negative suite
- Deliverable: cases for every route: no role, viewer in another domain, wrong customer, wrong cloud, expired assignment, body-supplied scope fields; denial records asserted; a two-domain world proving an accessor in an unreadable domain never leaks through counts, `visited_*` fields or error text.
- Owned files: `tests/security/authz/test_catalog_access.py`, `tests/security/authz/test_catalog_access_leak.py`.
- Must NOT touch: the shared harness (`world.py`, `cases.py`) except additive helpers.
- Depends on: item 3.
- Acceptance criteria: every route has a deny case per dimension, none skipped.
- Tests: `tests/security/authz`.
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 5 - Data access page and mock handlers
- Deliverable: `frontend/src/features/catalog/access/` with `AccessPage`, three canned-question panels, an asset picker over `GET /catalog/entities?entity_type=grounding_source`, a dependents panel with a depth control (1 to 5), a result table with status pill, confidence, evidence links and the partial-result banner, hooks, types, strings; `catalog-access.ts` mock handlers (including a truncated and a forbidden fixture); one route line in `routes.tsx` and `paths.ts`.
- Owned files: `frontend/src/features/catalog/access/**`, `routes.tsx`, `paths.ts`, `frontend/tests/mock-api/features/catalog-access.ts`.
- Must NOT touch: `EntityForm.tsx`, `entityFormModel.ts`, `server.ts`.
- Depends on: item 3 (response shapes).
- Acceptance criteria: criterion 8; strings pass the PRP-56 no-claim scan pattern (no "compliant" or "certified" about the estate); a null sensitivity renders as "not assessed".
- Tests: `frontend/src/features/catalog/access/access.test.tsx`, `frontend/tests/mock-api/features/catalog-access.test.ts` (new).
- Pattern references: `StaleAgentsPage.tsx`, `explorerHooks.ts`.

### Item 6 - Registration, e2e and accessibility
- Deliverable: Tier-2 lines (appRoutes, manifest, nav entry with `data.read`, route samples, real-stack rows, `manifest_calls.py`, route inventories), Playwright spec for the three questions, axe in three themes, runbook `docs/runbooks/catalog-access.md` stating the scan bound, what "not assessed" means and that an inferred edge is evidence, not a verdict.
- Owned files: `frontend/tests/e2e/catalog-access/**`, `docs/runbooks/catalog-access.md`, Tier-2 lines.
- Depends on: items 3 and 5.
- Acceptance criteria: criteria 8 and 9; manifest, axe and keyboard suites pass.
- Tests: `frontend/tests/e2e/catalog-access/access.spec.ts`; `uv run pytest -q services/api/tests/runtime_routes services/api/tests/authz services/api/tests/path_aliases`.
- Pattern references: `frontend/tests/e2e/catalog/catalog.spec.ts`.

### Item 7 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`), changelog fragment `changelog.d/PRP-73-graph-access-and-sensitivity-questions.md`, completion note including the item 2 finding on `data_source_refs` and the product check (can a compliance officer ask the three questions without raw API calls?).
- Owned files: this PRP file, the fragment, Tier-3 files per reference section 2.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/catalog_access packages/core/tests/catalog services/api/tests/catalog_access_api services/api/tests/catalog services/api/tests/read_audit_api services/api/tests/path_aliases services/api/tests/runtime_routes services/api/tests/authz tests/security/authz services/workers/tests/projections services/workers/tests/projections_data_access services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5291 NS_MOCK_API_PORT=5292 pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines for the new page: `visual:update` in the pinned Docker image, then `visual:check`.

## Migration and rollback
No data migration: the routes read existing documents; inferred `reads` and `writes` edges are ordinary `inferred` edges that stewards can reject through the existing curation routes, and they are written only for assets that already exist. Rollback: revert the PR; edges already written stay as inferred catalog edges (reject through curation, or leave). To stop new inference without a revert, the worker rule is behind `NS_WORKER_CATALOG_DATA_ACCESS_EDGES` (default true; ASSUMPTION, a worker settings field, Tier 2 new fields only). The routes carry no state.

## Live and open gates
None run here: behaviour is proven on in-memory twins and the mock API. Cosmos RU cost of the bounded asset scan is unmeasured and is handed to PRP-64 with the other catalog measurements (live Cosmos, `NS_LIVE_APPROVED=1`). Visual baselines are Docker-only.

## NOT building
The "who could" (entitlement) question and `catalog/access/could/**` (reserved for PRP-119); label ingestion (PRP-120); Cosmos-side filter fields and a backfill; attribute-based (classification-aware) read rules; owner and data-scope pickers (PRP-76); map impact highlight (PRP-74, PRP-77); the copilot tool (PRP-78); embeddings or any model call; a Cypher, Gremlin or SQL surface; export of access results (a later `data.export` decision); any statement that an estate is compliant.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 5, 7 and the rollback setting are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-73-item-1-access-engine | sonnet; 9d121429, merge b1efd7e5; review APPROVE; post-merge 225 passed (core catalog + workers projections), pyright 0 errors; 2026-11-20. Follow-ups: dependents truncation reason codes, ScanBound.max_assets null for dependents, unknown_region only rejects malformed tokens (AC3 partial), union of group+regions documented, mid-path scope test |
| 2 | merged | prp-73-item-2-data-access-edges | sonnet; 5d3c4c0b, merge 15e53c5e; review APPROVE; post-merge 41 passed, pyright 0 errors; 2026-11-20. Follow-ups: unresolved-asset warn threshold, stats not exported as metric, data_asset vs grounding_source ingest mapping, 2 extra handler tests |
| 3 | in-progress | prp-73-item-3-access-routes | sonnet; dispatched 2026-11-20 |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files or calling raw APIs?):
