---
name: PRP-120-purview-labels-classifications-and-lineage
status: backlog
priority: P1
order: 120
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-08, NS-09
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation, PRP-73-graph-access-and-sensitivity-questions]
wave: W27
branch: prp-120-purview-labels
allow_parallel: true
issues: []
---

# PRP-120: Purview labels, classifications and lineage

## Goal
Deliver the Microsoft Purview integration the product promised and never built. A read-only connector, `connectors/reference/purview/` (kind `purview`, scaffolded `not_built` by PRP-117, run by the generic `connector_runner`), reads the customer's sensitivity labels, classifications and asset lineage through whichever documented Purview APIs the verify-first item finds, per cloud. Purview assets are matched to NeuroSphere `GroundingSource` entities by resource reference and recorded as `external_labels`; a steward-edited label mapping turns customer labels into PRP-70's `sensitivity_categories`; one precedence rule (GD-11: steward-curated value, then customer label, then NeuroSphere inference) decides the effective sensitivity that the access questions, the policy engine and "who could" use; asset-to-asset lineage between matched assets becomes inferred `depends_on` edges. Every screen that shows sensitivity says whether labels are connected, partial or not connected. It is for the compliance officer whose organisation already classifies data in Purview, and for PRP-121 (Unity Catalog uses the same label model) and PRP-119.

Out of scope: Unity Catalog and lineage push-back to Purview or Unity (PRP-121); the `ExternalLabel`, `LabelMapping` and `LineageEdgeExport` contracts (PRP-110); the runner, scaffold and coverage page (PRP-117); labelling or classifying anything inside Purview (never: NeuroSphere reads labels, it does not write them); content inspection (PRP-101 to PRP-104); the live run (PRP-136).

## Why
- Promised, never built: `docs/PRD.md:17` "Purview and Unity Catalog are optional connector integrations; do not assume universal write-back, labeling or OpenLineage support." and `docs/PRD.md:55` "Purview/Unity integrations degrade visibly when absent." Deferred in `PRPs/shipped/PRP-10-catalog-and-relationship-governance.md:34` ("Deferred. Purview and Unity Catalog are optional connectors") and `PRPs/shipped/PRP-31-missing-ui-surfaces.md:59` ("Deferred: connector work, not UI"). There is no Purview code in the tree; "Unity Catalog" appears only as the Databricks SQL catalog name (`packages/core/neurosphere_core/analytics/databricks/config.py:47`).
- A data asset knows only what NeuroSphere was told: `classification` (five values, `packages/contracts/schemas/catalog/v1/common.schema.json:68-79`), `residency_region`, `contains_personal_data`, a `resource_ref` pointer (`grounding_source.schema.json:85-98`) and PRP-70's `sensitivity_categories`. A customer that labels data in Purview has to re-type every label.
- "Degrades visibly" has no mechanism: the general signals are `ComponentState` ok/failed/disabled/not_built (`services/api/neurosphere_api/runtime/status.py:73`) and the hand-written `docs/connectors/coverage.md`.
- Owner direction 2026-11-16: the Purview and Unity Catalog integration was in the owner's original one-line product description, and every identified gap is to be planned ("the ultimate team AI governance and auditing tool"); design entry PRP-120 and decision GD-11 fix the scope and precedence.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/purview.md` has every template heading and, per signal (asset search or listing, sensitivity labels on assets, classifications on assets, asset lineage read, label and classification definitions), records the documented endpoint, the least-privilege role or permission and how it is granted, licence or plan, paging and rate limits, the asset identifier format used for matching, Commercial and Government availability, and "not found" where absent. The descriptor is `built` only with this file and lists only verified clouds.
- [ ] Given Purview assets (fixtures) whose identifiers match `resource_ref` of in-scope `GroundingSource` entities under the normalisation rules of item 1, When the runner ticks, Then each matched source's `external_labels` holds `{system: purview, label_kind, label_id, label_name, source_asset_ref, observed_at}`; `sensitivity_categories`, `classification` and every other field are untouched; an unchanged label set writes nothing; an unmatched asset creates no entity and is counted.
- [ ] Given a published `LabelMapping` for a domain (customer label id to 1-10 sensitivity categories and optionally a classification), Then `effective_sensitivity(asset)` returns categories and classification with a source per value: the asset's own declared value when present (curated, wins whole), else the union of mapped customer labels across systems, else inferred values from the inference port, else unassessed (null, never empty-as-false); unmapped labels are listed, never guessed.
- [ ] Given a steward-declared `sensitivity_categories: ["financial"]` and a Purview label mapped to `pii`, Then the effective value is `financial` with source `curated`, and the asset view shows the Purview label as "customer label, overridden by steward value"; clearing the steward value makes `pii` (source `customer_label`) effective on the next read.
- [ ] PRP-73's access questions use the effective value: "who touches PII" includes agents reading an asset that is PII only by customer label; each row carries `sensitivity_source`; each response carries `label_coverage` (`state` per system `connected|partial|not_connected`, assets matched out of in-scope assets, unmapped label count, freshness). PRP-105's `data_sensitivity_access` evaluator, which calls the same engine, needs no change.
- [ ] Verified lineage only: lineage between two matched assets becomes an `inferred` `depends_on` edge (provenance `import`, source the connector id, evidence the Purview relationship reference); edges to unmatched assets are counted; a lineage signal not verified in item 1 ships off with reason `lineage_read_unverified`.
- [ ] Label mapping routes: `GET /api/v1/catalog/labels/domains/{domain}/mappings`, `GET .../unmapped` (`data.read`, audited reads) and `PUT .../mappings/{mapping_id}` (`catalog.curate`, `If-Match`, audited mutation; a mapping to an unknown category is 422); `GET /api/v1/catalog/labels/status` (`data.read`) returns the coverage summary. Deny cases pass for no role, wrong domain, wrong customer, wrong cloud and expired assignment.
- [ ] Without the connector, credentials or consent, every screen that shows sensitivity shows a banner "Customer labels: not connected" (or "partial" with the coverage numbers) and the access API still answers from NeuroSphere values with `label_coverage.state: not_connected`; nothing reads as complete.
- [ ] Government boundary: a Government deployment calls only Purview hosts item 1 verified for Government, or refuses the config 422 `connector_cloud_unsupported`; nothing crosses clouds (recording-transport test). No token, secret or response body in logs, status documents or audit records (leak test).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated; the live Purview read recorded OPEN for PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | ASSUMPTION (GD-11, recommended default): steward-curated value (locked) over customer label over NeuroSphere inference | as design; alternative: customer label always wins | Steward value over customer label over inference, implemented as Clarification 2 describes |
| 2 | What counts as the "locked steward value" | A new contract lock field; the asset's own declared fields | ASSUMPTION (GD-49, recommended default): without a field-level lock in the contracts, GD-11's "steward-curated value (locked)" is implemented as: the asset's own declared sensitivity wins whole. Here: the contracts have no field-level lock on entities (locks exist for edges only, `common.schema.json:246`), so the asset's own non-empty `sensitivity_categories` (or `classification` other than `unknown`) is the curated value and wins whole; connectors never write those fields; a steward clears them to let labels apply. A field-level lock is a follow-up for the next contracts owner |
| 3 | Several systems disagree | Last writer; union | ASSUMPTION: union of mapped categories; classification takes the most restrictive (`restricted` > `confidential` > `internal` > `public`) |
| 4 | Inference tier | Build a classifier; port only | ASSUMPTION: no inference source exists for asset sensitivity in the tree; the resolver takes an `InferredSensitivityReader` port with an empty default, so the tier is wired and honest |
| 5 | Where mappings live | Own container; `admin_config` | `admin_config` kind `label_mapping` (PRP-110 Clarification 3) through the shipped `AdminConfigRepository`; one `ADMIN_KIND_MODELS` line here |
| 6 | Mapping change governance | Executor action; audited mutation | ASSUMPTION (GD-31, recommended default): audited mutation with `If-Match` by a domain steward (`catalog.curate`), the PRP-65 admin-config pattern; it changes NeuroSphere's interpretation, not policy, capture, enforcement or an external system. Owner may require an executor action instead |
| 7 | Matching | Name match; resource reference | Resource reference only, normalised by rules recorded in item 1 (Purview's documented asset identifier against `resource_ref`); never by display name |
| 8 | How the connector writes | Connector updates the catalog; runner binding | ASSUMPTION: the label projection is bound to kind `purview` through PRP-117's per-kind binding hook (same mechanism as PRP-118 Clarification 7): PRP-117 declares the `neurosphere.connector_bindings` entries, this PRP writes `projections/labels/binding.py` exposing `BINDING` (kind `purview`) and `UNITY_BINDING` (kind `unity_catalog`, the same projection with the Unity normalisation rule PRP-121 supplies); the connector holds no store client and nothing under `connector_runner/` is edited |
| 9 | Priority | P1; P2 | ASSUMPTION (GD-42, recommended default): PRP-120 (Purview) and PRP-121 (Unity Catalog) are P1, because the original product description named both. Here: `priority: P1` in this PRP's frontmatter |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-110-governance-contracts-b.md` "Interfaces provided", Labels and lineage - `ExternalLabel`, `LabelMapping`, `admin_kind: label_mapping`.
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` "Interfaces provided" and the shared-file rules in Gotchas.
- `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md` "Interfaces provided" - `AccessEngine`, `AccessResult`, `AccessRow`, the null-is-unassessed rule.
- `packages/core/neurosphere_core/catalog/graph/access.py` (PRP-73) - where the effective value is applied.
- `packages/contracts/schemas/catalog/v1/grounding_source.schema.json` - `resource_ref`, `contains_personal_data`, `external_labels`.
- `packages/core/neurosphere_core/admin/models.py:61-93` and `admin/store.py:142` - `AdminKindName`, `ADMIN_KIND_MODELS`, `AdminConfigRepository`.
- `packages/core/neurosphere_core/catalog/protocol.py:199-280` - `update_entity` with ETag, `put_edge`.
- `services/workers/neurosphere_workers/projections/catalog/mapping.py:172-200` - inferred edge with evidence.
- `frontend/src/features/admin/shared/areas.ts`, `frontend/src/features/admin/sources/ConnectorsPage.tsx` - admin area and page patterns.

### Interfaces consumed
- PRP-110 (W25): `ExternalLabel`, `GroundingSource.external_labels`, `LabelMapping` (`entries` of `label_kind`, `label_id`, `sensitivity_categories`, `classification`), `admin_kind` `label_mapping`.
- PRP-70 (W19): `sensitivity_category` vocabulary, `GroundingSource.sensitivity_categories`, `residency_geography`.
- PRP-73 (W20): `AccessEngine.who_accesses`, `AccessQuery`, `AccessResult`, `AccessRow`; page `frontend/src/features/catalog/access/`.
- PRP-117 (W26): descriptor, `EstateConnector`, `RunContext`, `RunResult`, the runner, `ConnectorStatusRepository` (freshness for `label_coverage`), verification template and check.
- PRP-99 (W20): `connector_kind` value `purview`.
- Shipped: `AdminConfigRepository`, `run_audited_mutation`, `audited_read`, `CatalogRepository`, curation routes (stewards can reject an inferred `depends_on`).

### Interfaces provided
- Core `neurosphere_core.catalog.labels`: `effective_sensitivity(asset, mappings, inferred=()) -> EffectiveSensitivity` {`categories` (or null), `classification`, `sources` (per value `curated|customer_label|inferred`), `overridden_labels`, `unmapped_labels`}; `LabelMappingStore` over `AdminConfigRepository`; `InferredSensitivityReader` port and `NoInference`; `LabelCoverage` {`systems` (per system `state`, `assets_matched`, `assets_in_scope`, `unmapped_labels`, `last_success`)}; `normalise_asset_ref(system, ref)`; `LabelObservationSink` port.
- `AccessRow.sensitivity_source` and `AccessResult.label_coverage` (added to PRP-73's models).
- Worker `neurosphere_workers.projections.labels`: `LabelProjection` (implements the sink for `purview` and, from PRP-121, `unity_catalog`), `bind_purview(...)`.
- Connector `neurosphere_connector_purview`: `DESCRIPTOR` (kind `purview`, mode `read`), settings `account_name`, `collections` (bounded list), `read_lineage` (bool).
- Routes under `/api/v1/catalog/labels` (alias `/catalog/labels`): `GET /status`, `GET /domains/{domain}/mappings`, `GET /domains/{domain}/unmapped`, `PUT /domains/{domain}/mappings/{mapping_id}`. Audit operations `catalog.label_status`, `catalog.label_mappings_read`, `catalog.label_mapping_replace`.
- Frontend: admin area "Customer labels" (`frontend/src/features/admin/labels/`: mapping editor, status), exported `LabelSourceBanner`; mock handlers `frontend/tests/mock-api/features/catalog-labels.ts`.

### Patterns to match
- Audited admin-config mutation with `ETag`/`If-Match`: `services/api/neurosphere_api/mcp/admin/router.py:96-198`; frontend `useEtagMutation.ts`.
- Partial-result banner and null-as-not-assessed wording: PRP-73 item 5.
- Inferred edge with evidence: `projections/catalog/mapping.py:172-200`.
- Connector package and tests: `connectors/reference/azure-billing/`.

### Gotchas
- UNVERIFIED (design U-10): "Purview has documented APIs for asset classifications, sensitivity labels and lineage, and for writing custom lineage; availability in Government." If false: read-only, or `not_built` in that cloud. The write half belongs to PRP-121; this PRP records only the read signals.
- Subagents have no Microsoft Learn tool: the orchestrator fetches item 1's pages and pastes URLs, retrieval dates and facts into the brief.
- Do not write `sensitivity_categories` or `classification` from a connector: precedence is computed at read time, so clearing a label in Purview clears it here on the next run and a steward value is never lost.
- PRP-73 treats null `sensitivity_categories` as unassessed; an empty effective set is "assessed, none" only when a source actually said so (a mapped label to no category is impossible: `LabelMapping` requires 1-10).
- Label names are customer metadata, not content, but keep them out of logs and audit records anyway (ids and counts only).
- `update_entity` needs the current ETag; on conflict re-read and retry a bounded number of times, then count `label_write_conflict`.
- Shared-file rules for the connector wave (PRP-117 Gotchas) apply.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/purview/**
  - docs/connectors/verification/purview.md
  - packages/core/neurosphere_core/catalog/labels/**
  - packages/core/neurosphere_core/catalog/graph/access.py
  - packages/core/tests/catalog_labels/**
  - services/workers/neurosphere_workers/projections/labels/**
  - services/workers/tests/projections_labels/**
  - services/api/neurosphere_api/catalog/labels/**
  - services/api/tests/catalog_labels_api/**
  - tests/security/authz/test_catalog_labels*.py
  - tests/security/labels/**
  - frontend/src/features/admin/labels/**
  - frontend/tests/mock-api/features/catalog-labels.ts
  - docs/runbooks/customer-labels.md
  - changelog.d/PRP-120-purview-labels-classifications-and-lineage.md
tier1: []
tier2_appends:
  - packages/core/neurosphere_core/admin/models.py
  - frontend/src/features/admin/shared/areas.ts
  - frontend/src/features/catalog/access/**
  - frontend/src/features/map/**
  - frontend/src/features/governance/policy/**
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - services/workers/neurosphere_workers/connector_runner/**
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - packages/core/neurosphere_core/catalog/repo/**
  - packages/core/neurosphere_core/catalog/identity/**
  - services/api/neurosphere_api/runtime/builders/**
  - connectors/reference/entra-identity/**
  - connectors/reference/unity-catalog/**
  - frontend/src/features/catalog/EntityForm.tsx
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - tests/unit/connector_conformance/**
  - docs/connectors/coverage.md
  - docs/connectors/estate-coverage.md
```
The frontend Tier-2 globs mean one banner mount line per screen that shows sensitivity (PRP-73 access page, PRP-77 map filter panel, PRP-106 policy editor), none of which another W27 PRP edits. `frontend/src/features/catalog/EntityTypeDetails.tsx` belongs to PRP-118 in W27; item 7 edits it only after PRP-118 merges.

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 [P] after it. Item 4 after 2 and 3. Item 5 after 2. Item 6 after 5. Item 7 after 6 and PRP-118's merge. Item 8 last; the security tests run inside items 4 to 6.

### Item 1 - Verify first: Purview read signals per cloud
- Deliverable: `docs/connectors/verification/purview.md` per criterion 1, the normalisation rules from Purview asset identifiers to `resource_ref` forms, the least-privilege role and how the operator grants it, Government availability, a build / do-not-build table.
- Owned files: the verification file.
- Depends on: PRP-110 and PRP-117 merged.
- Acceptance criteria: criterion 1; U-10 read half resolved or recorded OPEN.
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: PRP-122 item 1.

### Item 2 - Label model and precedence  [P]
- Deliverable: `catalog/labels/` (`precedence.py`, `mapping_store.py`, `coverage.py`, `normalise.py`, `ports.py`); `label_mapping` line in `AdminKindName` and `ADMIN_KIND_MODELS`.
- Owned files: `packages/core/neurosphere_core/catalog/labels/**`, `packages/core/tests/catalog_labels/**`, two lines in `admin/models.py`.
- Must NOT touch: `catalog/protocol.py`, contracts.
- Depends on: item 1 (normalisation).
- Acceptance criteria: criteria 3 and 4 (core part); null stays unassessed; union and most-restrictive rules; property tests over random label sets.
- Tests: `packages/core/tests/catalog_labels/test_precedence.py`, `test_mapping_store.py`, `test_normalise.py`, `test_coverage.py`; `packages/core/tests/admin`.

### Item 3 - Purview connector body  [P]
- Deliverable: readers for the verified signals over `ctx.http`, bounded paging per collection, throttling to `RunResult.reason`, `LabelObservation` and `LineageObservation` output, `supported_clouds` and `allowed_hosts` from item 1, descriptor `built`, synthetic fixtures, `conformance_factory()`.
- Owned files: `connectors/reference/purview/**`.
- Must NOT touch: other connectors, runner, SDK.
- Depends on: item 1.
- Acceptance criteria: criterion 9 (connector half); no write call exists in the package (static test).
- Tests: `connectors/reference/purview/tests/test_readers.py`, `test_no_write.py`, `test_government_hosts.py`, `test_no_secret_in_output.py`; `tests/unit/connector_conformance`.

### Item 4 - Label projection and runner binding
- Deliverable: `projections/labels/` (match by normalised reference within the worker's derived scope, write `external_labels` only when changed, remove labels absent from a complete run, `depends_on` edges for verified lineage, coverage numbers to the connector status), `binding.py` with `BINDING` (kind `purview`) and `UNITY_BINDING` (kind `unity_catalog`, built here so PRP-121 needs no worker edit; it applies the Unity rule from `catalog/labels/normalise.py` once PRP-121 adds it, and the default rule until then).
- Owned files: `services/workers/neurosphere_workers/projections/labels/**`, `services/workers/tests/projections_labels/**`.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 2 and 6; idempotent; truncated run removes nothing; ETag conflict bounded.
- Tests: `services/workers/tests/projections_labels/test_projection.py`, `test_lineage_edges.py`, `test_stale_labels.py`, `test_runner_binding.py` (uses PRP-117's test binding fixture).

### Item 5 - Effective sensitivity in the access engine and label API
- Deliverable: `access.py` applies `effective_sensitivity` in its asset predicate and fills `sensitivity_source` and `label_coverage`; `catalog/labels/` API package with the four routes, `audited_read`, audited mutation, route inventory lines.
- Owned files: `packages/core/neurosphere_core/catalog/graph/access.py`, `services/api/neurosphere_api/catalog/labels/**`, `services/api/tests/catalog_labels_api/**`, `tests/security/authz/test_catalog_labels.py`; Tier-2 lines.
- Must NOT touch: `catalog/router.py`, `runtime/builders/**`.
- Depends on: item 2.
- Acceptance criteria: criteria 5 and 7; PRP-73's suites pass with the extra fields.
- Tests: `services/api/tests/catalog_labels_api/test_mappings.py`, `test_status.py`; `packages/core/tests/catalog_labels/test_access_effective.py`; re-run `packages/core/tests/catalog_access`, `services/api/tests/catalog_access_api`, `packages/core/tests/governance_policy`.

### Item 6 - Labels admin page and banner
- Deliverable: admin area "Customer labels" with status per system, the mapping editor (observed labels on the left, categories on the right, version and `If-Match` conflict handling), unmapped list; `LabelSourceBanner`; one mount line on each screen in the Ownership note found by grepping `frontend/src` for `sensitivity`; mock handlers.
- Owned files: `frontend/src/features/admin/labels/**`, `frontend/tests/mock-api/features/catalog-labels.ts`; Tier-2 mount and area lines.
- Depends on: item 5.
- Acceptance criteria: criterion 8; axe in three themes; no wording that says data is classified "correctly" or "compliant".
- Tests: `frontend/src/features/admin/labels/labels.test.tsx`; existing access page tests.

### Item 7 - Entity page rows  [serial-after: PRP-118]
- Deliverable: grounding-source rows in `EntityTypeDetails.tsx` showing effective sensitivity with source, customer labels (and "overridden by steward value"), and the banner.
- Owned files: `frontend/src/features/catalog/EntityTypeDetails.tsx` (after PRP-118 merged and this branch rebased).
- Depends on: item 6; PRP-118 merged.
- Acceptance criteria: criterion 4 (UI part).
- Tests: `frontend/src/features/catalog/entity-type-details.test.tsx`.

### Item 8 - Integration and close-out
- Deliverable: security suite `tests/security/labels/` (leak, Government boundary, connector-off degradation); runbook `docs/runbooks/customer-labels.md` (operator grants, mapping workflow, precedence, what "partial" means); Tier-2 appends; Tier-3 regeneration after rebase; changelog fragment; completion note with the item 1 outcome.
- Owned files: `tests/security/labels/**`, the runbook, the fragment, this PRP file, Tier-3 outputs.
- Depends on: items 1 to 7.
- Acceptance criteria: criterion 9; validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/purview/tests packages/core/tests/catalog_labels packages/core/tests/catalog_access packages/core/tests/catalog packages/core/tests/admin packages/core/tests/governance_policy services/workers/tests/projections_labels services/workers/tests/connector_runner_role services/api/tests/catalog_labels_api services/api/tests/catalog_access_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/security/labels tests/unit/connector_conformance tests/unit/estate_check services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/connector_estate_check.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive: `external_labels` defaults to an empty list (PRP-110), mappings are new `admin_config` documents, lineage edges are ordinary inferred edges. Rollback: disable the `purview` config (labels stop refreshing; the banner shows the age) or delete the mappings (effective values fall back to NeuroSphere values), or revert the PR; stewards can reject imported `depends_on` edges through curation.

## Live and open gates
OPEN until run with `NS_LIVE_APPROVED=1` and operator approval: a Purview read in an approved Commercial account with the role from item 1 granted by the operator, and Government if verified. Handed to PRP-136. The session never grants Purview roles or edits collections.

## NOT building
Writing labels, classifications or lineage into Purview (push-back is PRP-121 and only where verified); parity with Microsoft Purview or any implied affiliation (design section 8 item 5); "complete" classification: the effective value is only as good as the customer's labels and NeuroSphere's declared values, and the banner says so; content scanning of assets; universal labelling or OpenLineage support (`docs/PRD.md:17`); bridging Government data to Commercial; any compliance claim.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 to 4, 6 and 8 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can a compliance officer map Purview labels and see them change the answers, without reading code):
