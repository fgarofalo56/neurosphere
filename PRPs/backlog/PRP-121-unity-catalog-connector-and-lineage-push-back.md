---
name: PRP-121-unity-catalog-connector-and-lineage-push-back
status: backlog
priority: P1
order: 121
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-02, NS-06, NS-08, NS-09
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation, PRP-120-purview-labels-classifications-and-lineage]
wave: W28
branch: prp-121-unity-catalog-lineage
allow_parallel: true
issues: []
---

# PRP-121: Unity Catalog connector and lineage push-back

## Goal
Finish the data-governance integration the PRD promised. First, a read-only Unity Catalog connector, `connectors/reference/unity-catalog/` (kind `unity_catalog`, scaffolded `not_built` by PRP-117, run by the generic `connector_runner`), reads tags, classifications and table lineage through whatever documented Databricks interface the verify-first item finds, and feeds them through PRP-120's label model: tags and classifications land in `GroundingSource.external_labels` with `system: unity_catalog`, the customer's label mapping and the GD-11 precedence decide the effective sensitivity, and lineage between matched tables becomes inferred `depends_on` edges. Second, optional push-back: NeuroSphere's own agent-to-data lineage (the `reads` and `writes` edges) can be written to Purview and/or Unity Catalog as the `lineage_push` action through the one action executor, with a dry run that shows exactly what would be written, confirmation bound to that export, approval by someone other than the requester, audit before and after, verify by reading it back, and rollback; each target is disabled unless item 1 verified an API that accepts custom lineage and lets it be read back and removed. It is for the data governance lead who wants agents to appear in the lineage their organisation already uses.

Out of scope: the Purview read connector, label mapping, precedence and banners (PRP-120); the `LineageEdgeExport` contract and the `lineage_push` manifest action (PRP-110); the runner and scaffold (PRP-117); writing labels or classifications into Purview or Unity (never); Databricks as an analytics adapter (`packages/core/neurosphere_core/analytics/databricks/`, unchanged); the live run (PRP-136).

## Why
- Promised, never built: `docs/PRD.md:17` "Purview and Unity Catalog are optional connector integrations; do not assume universal write-back, labeling or OpenLineage support." and `docs/PRD.md:55` "Purview/Unity integrations degrade visibly when absent." "Unity Catalog" exists in code only as the analytics SQL catalog name (`packages/core/neurosphere_core/analytics/databricks/config.py:47`).
- Deferred twice: `PRPs/shipped/PRP-10-catalog-and-relationship-governance.md:34` ("no write-back assumed") and `PRPs/shipped/PRP-31-missing-ui-surfaces.md:59`.
- The executor refuses to pretend: a kind with no registered write connector is advisory and "nothing is changed anywhere to stand in for the change" (`packages/core/neurosphere_core/actions/targets.py:1-7`); `ACTION_CONNECTORS` has no lineage kind (`targets.py:59-72`). Unknown kinds require approval by default (`services/api/neurosphere_api/actions/settings.py:57-59`).
- NeuroSphere already holds agent-to-data lineage as catalog `reads`/`writes` edges (PRP-73 infers them from telemetry); the customer's catalog cannot see which agents touch which tables.
- Owner direction 2026-11-16: Purview and Unity Catalog were in the owner's original one-line product description; every identified gap is to be planned; design entry PRP-121 and section 8 item 11 ("only where a verified API accepts custom lineage").

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/unity-catalog.md` (every template heading) records, per signal (table and column tags, classifications, table lineage read; external or custom lineage create, read-back and delete), the documented endpoint or system table, least-privilege privilege for read and, separately, for write, authentication method with the workload identity, rate limits, the table identifier format, Azure Commercial and Government availability, and "not found" where absent; a "Lineage write" section appended to `docs/connectors/verification/purview.md` records the same for Purview custom lineage. `scripts/connector_estate_check.py` passes.
- [ ] Given Unity tables (fixtures) whose identifiers match `resource_ref` of in-scope grounding sources under the normalisation rule added to PRP-120's `normalise_asset_ref`, When the runner ticks, Then their tags and classifications appear as `external_labels` with `system: unity_catalog` through PRP-120's projection, the effective sensitivity follows PRP-120's precedence and mappings, and verified table lineage between matched tables becomes `inferred` `depends_on` edges; unmatched tables are counted; any table-lineage query is a fixed constant with a column allowlist (no generated SQL).
- [ ] Given in-scope `reads`/`writes` edges from agents to grounding sources that have an external reference for the target system, When a user with `action.propose` calls `POST /api/v1/catalog/lineage-export/domains/{domain}/drafts` for `purview` or `unity_catalog`, Then a `lineage_push` intent is drafted whose diff is a `LineageEdgeExport` (at most 500 edges, deterministic `export_id`, evidence ids), only `asserted` and `curated` edges by default, hidden edges never; the preview route shows the same edges before drafting.
- [ ] Executor path: the intent requires approval, the requester cannot approve it, the confirmation hash binds the exact export digest, the executor rechecks permission before apply, writes audit before and after, applies, verifies by reading back from the target that exactly the exported edges exist, and rolls back (removes what it wrote) when verify fails; a dry run lists every object it would create, by name, with nothing written.
- [ ] Disabled unless verified: for a target where item 1 did not verify create, read-back and delete, no write connector is registered, the intent stays advisory with "no supported write connector", and the labels page says "push-back not available for <system>: <reason>"; `NS_LINEAGE_PUSH_ENABLED` defaults to false.
- [ ] Government: a Government deployment pushes only to targets in its own cloud on hosts verified for Government, otherwise the target is not registered; no lineage, label or id crosses clouds (recording-transport test). No token, secret or response body in logs, audit, status documents or intent views (leak test).
- [ ] Authorization: preview needs `data.read` (audited read `catalog.lineage_export_preview`), drafting needs `action.propose` in the domain; deny cases pass for no role, wrong domain, wrong customer, wrong cloud and expired assignment; body-supplied scope ignored.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated; the live Unity read and any live push recorded OPEN for PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | ASSUMPTION (GD-11, recommended default): steward-curated value (locked) over customer label over NeuroSphere inference | as PRP-120 | Applied to Unity tags by PRP-120's resolver unchanged |
| 2 | When push-back is enabled per target | When create works; when create, read-back and delete are all verified | ASSUMPTION (GD-35, recommended default): all three verified; without read-back there is no verify and without delete there is no rollback, so the executor contract cannot be honoured |
| 3 | Which edges are exported | All presented edges; asserted and curated only | ASSUMPTION: `asserted` and `curated` by default; `inferred` only with the per-draft flag `include_inferred`, shown in the dry run as inferred |
| 4 | One kind, two targets | Two kinds; one kind with a target override | One kind `lineage_push` (PRP-110); `ACTION_CONNECTORS["lineage_push"]` names the Unity connector and `TARGET_KIND_CONNECTORS` routes target entity type `purview_lineage` to the Purview connector (ASSUMPTION: target entity types `unity_lineage`, `purview_lineage`, used by no other kind) |
| 5 | Credentials | Stored secret; workload identity | Workload identity as every write target today (`runtime/builders/write_targets.py` docstring); a PRP-42 credential reference only if item 1 shows the API needs one; never a value in settings or logs |
| 6 | Least privilege | One broad role; separate read and write | Separate: the read connector's identity never holds the write privilege; exact privileges written from documentation in item 1; granting them is an operator step |
| 7 | Self-approval (GD-20: who approves each governance action kind) | Default review policy; pinned | Pinned: `lineage_push` is added to PRP-108's `PINNED_NO_SELF_APPROVAL` with one line |
| 8 | Priority | P1; P2 | ASSUMPTION (GD-42, recommended default): PRP-120 (Purview) and PRP-121 (Unity Catalog) are P1, because the original product description named both. Here: `priority: P1` in this PRP's frontmatter |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-120-purview-labels-classifications-and-lineage.md` "Interfaces provided" - label projection, `normalise_asset_ref`, banners, labels page.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` - `LineageEdgeExport`, `lineage_push`.
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` "Interfaces provided" and the shared-file rules.
- `PRPs/backlog/PRP-108-agent-approval-gate-and-platform-control-actions.md` "Interfaces provided" - `PINNED_NO_SELF_APPROVAL`, how a target is registered.
- `packages/core/neurosphere_core/actions/targets.py` - `ACTION_CONNECTORS`, `TARGET_KIND_CONNECTORS`, `connector_names_for` (`:119`).
- `connectors/sdk-python/neurosphere_connector/write/write_protocol.py:23-55` - `WriteConnector` (`dry_run`, `apply`, `verify`, `rollback`).
- `services/api/neurosphere_api/runtime/builders/write_targets.py` (docstring) and `services/workers/neurosphere_workers/runtime/factories.py:1813` (`register_write_targets`) - where targets are registered.
- `services/workers/neurosphere_workers/actions/apim.py` - a worker-side write-target builder to imitate.
- `services/api/neurosphere_api/catalog/grant_publish.py` - drafting an intent from a domain route through `ActionApi.draft` (`actions/service.py:120`).
- `packages/core/neurosphere_core/analytics/databricks/config.py:40-52` - existing Databricks host and identity settings shape (pattern only).

### Interfaces consumed
- PRP-120 (W27): `LabelProjection` (accepts `system: unity_catalog`), `normalise_asset_ref`, `LabelSourceBanner`, labels admin page, `docs/connectors/verification/purview.md`.
- PRP-110 (W25): `LineageEdgeExport` (1-500 edges of `source_id`, `target_id`, `relation_type` reads or writes, `external_target_ref`, `evidence_ids`), manifest action `lineage_push`, `ExternalLabel` system `unity_catalog`.
- PRP-117 (W26): descriptor, `EstateConnector`, `RunContext`, `RunResult`, the per-kind binding hook (kind `unity_catalog` is bound by PRP-120's `UNITY_BINDING`), verification template.
- PRP-108 (W23): `PINNED_NO_SELF_APPROVAL`, approval UI for intents.
- PRP-73 (W20): `reads`/`writes` edges with evidence; `rules.present_edge`.
- PRP-99 (W20): `connector_kind` value `unity_catalog`.
- Shipped: `ActionApi.draft`, executor (kill switch, lease, permission recheck, dry run, audit, apply, verify, rollback: `services/workers/neurosphere_workers/actions/executor.py`), `WriteTargetRegistry`, `audited_read`.

### Interfaces provided
- Connector `neurosphere_connector_unity_catalog`: `DESCRIPTOR` (kind `unity_catalog`, mode `read`), settings `workspace_host`, `catalogs` (bounded list), `read_lineage` (bool); `UnityLineagePushConnector` (manifest name `unity-catalog-lineage-push`, action `lineage_push`).
- `neurosphere_connector_purview.lineage_push.PurviewLineagePushConnector` (manifest name `purview-lineage-push`).
- Core `neurosphere_core.catalog.lineage_export`: `build_export(scope, domain_id, target_system, *, include_inferred, budget) -> LineageEdgeExport`, `export_digest`, `export_diff`/`parse_export_diff`, `compare_read_back(export, observed) -> ReadBackResult`, target entity types `unity_lineage`, `purview_lineage`.
- `targets.py`: `UNITY_LINEAGE_CONNECTOR`, `PURVIEW_LINEAGE_CONNECTOR`, the `lineage_push` row and the `purview_lineage` override.
- Worker `neurosphere_workers.actions.lineage_push.build_lineage_push_targets(settings, ...)`; settings `NS_LINEAGE_PUSH_ENABLED` (false), `NS_LINEAGE_PUSH_PURVIEW_ACCOUNT`, `NS_LINEAGE_PUSH_UNITY_WORKSPACE_HOST`.
- Routes under `/api/v1/catalog/lineage-export` (alias `/catalog/lineage-export`): `GET /domains/{domain}/preview?target_system=`, `POST /domains/{domain}/drafts`. Audit operations `catalog.lineage_export_preview`, `catalog.lineage_export_draft`.
- Frontend: "Propose lineage push" panel on PRP-120's labels page (`frontend/src/features/admin/labels/LineagePushPanel.tsx`).

### Patterns to match
- Write connector with dry run, verify by read-back and rollback: `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/{connector,planner,applier}.py`.
- Worker write-target builder and advisory fallback: `services/workers/neurosphere_workers/actions/apim.py:165-232` (`build_apim_gateway_connector`, `build_http_apim_gateway_connector`).
- Drafting an intent from a domain route: `services/api/neurosphere_api/catalog/grant_publish.py`.
- Fixed query constant with column allowlist: `services/api/neurosphere_api/deploy/scan/graph.py:40-46` (`SCAN_QUERY`).

### Gotchas
- UNVERIFIED (design U-10): "Purview has documented APIs for asset classifications, sensitivity labels and lineage, and for writing custom lineage; availability in Government." If false: read-only, or `not_built` in that cloud.
- UNVERIFIED (design U-11): "Databricks Unity Catalog exposes tags, classifications and table lineage through documented APIs or system tables, and accepts external lineage." If false: tags only; no push-back.
- Subagents have no Microsoft Learn tool: the orchestrator fetches the Microsoft and Databricks documentation for item 1 and pastes URLs, retrieval dates and facts into the brief.
- A pushed object must be identifiable as NeuroSphere's so read-back and rollback touch only what NeuroSphere wrote (a deterministic name or qualifier from `export_id`, as item 1 finds the API allows); never delete or edit lineage NeuroSphere did not create.
- `TARGET_KIND_CONNECTORS` overrides apply to every kind for that target type; use the two new target types for nothing else.
- Write targets are registered in a STARTUP hook in the API and in `register_write_targets` in the worker (Tier-1 bodies); this PRP's item 6 is serial-after a grant.
- A Databricks workspace host is customer-specific: `allowed_hosts` uses DNS-label suffix matching from item 1, never substring.
- Shared-file rules for the connector wave (PRP-117 Gotchas) apply; this PRP edits PRP-120's `purview/` package only to add `lineage_push.py` and its tests (W28 has no other owner of it).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/unity-catalog/**
  - connectors/reference/purview/neurosphere_connector_purview/lineage_push.py
  - connectors/reference/purview/tests/test_lineage_push*.py
  - docs/connectors/verification/unity-catalog.md
  - docs/connectors/verification/purview.md
  - packages/core/neurosphere_core/catalog/lineage_export/**
  - packages/core/neurosphere_core/catalog/labels/normalise.py
  - packages/core/tests/catalog_lineage_export/**
  - packages/core/neurosphere_core/actions/targets.py
  - services/workers/neurosphere_workers/actions/lineage_push.py
  - services/workers/tests/lineage_push_target/**
  - services/api/neurosphere_api/catalog/lineage_export/**
  - services/api/tests/catalog_lineage_export_api/**
  - tests/security/authz/test_catalog_lineage_export*.py
  - tests/security/lineage_push/**
  - frontend/src/features/admin/labels/LineagePushPanel.tsx
  - frontend/src/features/admin/labels/lineage-push.test.tsx
  - frontend/tests/mock-api/features/catalog-lineage-export.ts
  - docs/runbooks/lineage-push-back.md
  - changelog.d/PRP-121-unity-catalog-connector-and-lineage-push-back.md
tier1: []
tier2_appends:
  - packages/core/neurosphere_core/admin/platform/review_policy.py
  - frontend/src/features/admin/labels/**
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - mkdocs.yml
must_not_touch:
  - services/workers/neurosphere_workers/connector_runner/**
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/labels/precedence.py
  - packages/core/neurosphere_core/catalog/graph/access.py
  - services/workers/neurosphere_workers/actions/executor.py
  - services/api/neurosphere_api/actions/settings.py
  - connectors/reference/entra-identity/**
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - tests/unit/connector_conformance/**
  - docs/connectors/coverage.md
  - docs/connectors/estate-coverage.md
```
Item 6 additionally edits `services/api/neurosphere_api/runtime/builders/write_targets.py` and the `register_write_targets` body in `services/workers/neurosphere_workers/runtime/factories.py`, both Tier-1, only after the orchestrator grants them for W28 (no other W28 PRP edits them) or after a wave owner merges. The `frontend/src/features/admin/labels/**` line is one mount line for `LineagePushPanel` in PRP-120's page.

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 [P] after it. Item 4 after 3. Item 5 after 4. Item 6 after 5 and the grant. Item 7 after 5 (and 6 when granted). Item 8 last. Items 3 to 7 are the push-back half (Cut line).

### Item 1 - Verify first: Unity read, Unity and Purview lineage write
- Deliverable: `docs/connectors/verification/unity-catalog.md` and the "Lineage write" section of `purview.md` per criterion 1; the Unity normalisation rule; a build / do-not-build table per signal and per target, including create, read-back and delete separately.
- Owned files: the two verification files.
- Depends on: PRP-110, PRP-117, PRP-120 merged.
- Acceptance criteria: criterion 1; U-10 write half and U-11 resolved or recorded OPEN.
- Tests: `python scripts/connector_estate_check.py`.

### Item 2 - Unity Catalog read connector  [P]
- Deliverable: readers for verified signals over `ctx.http`, bounded per catalog, throttling to `RunResult.reason`, label and lineage observations in PRP-120's observation types, descriptor `built` with verified clouds and suffix hosts, fixtures, `conformance_factory()`; the Unity rule in `normalise.py`; no binding code: PRP-117 declares the `unity_catalog` entry and PRP-120 writes `UNITY_BINDING`, which calls the Unity rule in `normalise.py`.
- Owned files: `connectors/reference/unity-catalog/**`, `packages/core/neurosphere_core/catalog/labels/normalise.py`.
- Depends on: item 1.
- Acceptance criteria: criterion 2; criterion 6 (read half); no write call in the read package path (static test).
- Tests: `connectors/reference/unity-catalog/tests/test_readers.py`, `test_fixed_query.py`, `test_government_hosts.py`, `test_no_secret_in_output.py`; `packages/core/tests/catalog_labels`; `tests/unit/connector_conformance`.

### Item 3 - Lineage export core  [P]
- Deliverable: `catalog/lineage_export/` (`build.py`, `diff.py`, `read_back.py`): bounded export from presented `reads`/`writes` edges with external references, deterministic `export_id` and digest, diff and parser, read-back comparison.
- Owned files: `packages/core/neurosphere_core/catalog/lineage_export/**`, `packages/core/tests/catalog_lineage_export/**`.
- Depends on: item 1 (identifier formats).
- Acceptance criteria: criterion 3 (core part); hidden edges excluded; inferred only on request; out-of-scope edges never exported.
- Tests: `test_build.py`, `test_digest_stable.py`, `test_read_back.py`, `test_scope.py`.

### Item 4 - Write connectors for verified targets
- Deliverable: `UnityLineagePushConnector` and `PurviewLineagePushConnector` implementing `WriteConnector` (dry run lists every object to create; apply; verify via `compare_read_back`; rollback removes only NeuroSphere-created objects); each built only where item 1 verified create, read-back and delete, otherwise the manifest is advisory.
- Owned files: `connectors/reference/unity-catalog/**` (push module), `connectors/reference/purview/neurosphere_connector_purview/lineage_push.py`, its tests.
- Depends on: item 3.
- Acceptance criteria: criteria 4 and 5 (connector part).
- Tests: `connectors/reference/unity-catalog/tests/test_lineage_push.py`, `connectors/reference/purview/tests/test_lineage_push.py` (fake transports: apply, verify mismatch triggers rollback, delete scoped to own objects).
- Pattern references: `apim-gateway` `planner.py`, `applier.py`.

### Item 5 - Executor mapping, worker builder, draft routes and panel
- Deliverable: `targets.py` constants, row and override; `PINNED_NO_SELF_APPROVAL` line; `services/workers/neurosphere_workers/actions/lineage_push.py` (`build_lineage_push_targets`, settings, advisory when disabled or unverified); `catalog/lineage_export/` API package (preview, drafts via `ActionApi.draft`); `LineagePushPanel` on the labels page; mock handlers; route inventory lines.
- Owned files: `targets.py`, `actions/lineage_push.py`, `services/workers/tests/lineage_push_target/**`, `services/api/neurosphere_api/catalog/lineage_export/**`, `services/api/tests/catalog_lineage_export_api/**`, the panel and its test, mock file; Tier-2 lines.
- Must NOT touch: `executor.py`, `actions/settings.py`, Tier-1 builders.
- Depends on: item 4.
- Acceptance criteria: criteria 3, 4 (draft and approval part), 5 and 7.
- Tests: `services/api/tests/catalog_lineage_export_api/test_preview.py`, `test_draft.py`; `services/workers/tests/lineage_push_target/test_builder.py`; `packages/core/tests/actions` (targets table tests); `frontend/src/features/admin/labels/lineage-push.test.tsx`.

### Item 6 - Write-target registration  [serial-after: W28 Tier-1 grant for `runtime/builders/write_targets.py` and `register_write_targets`]
- Deliverable: one call of `build_lineage_push_targets` in `register_write_targets` (worker) and the matching registration in the API STARTUP hook, so dry runs in the API plan against the same connectors the worker applies.
- Owned files: those two Tier-1 locations, only once granted.
- Depends on: item 5.
- Acceptance criteria: criterion 4 end to end in `services/api/tests/write_targets_runtime` and the worker executor suite.
- Tests: `services/api/tests/write_targets_runtime`, `services/workers/tests/lineage_push_target/test_executor_flow.py`.

### Item 7 - Security suite
- Deliverable: approval required and self-approval refused; confirmation bound to the export digest (a changed edge set invalidates it); permission recheck at apply; audit records before and after with ids only; Government boundary; leak test; authorization negatives for both routes.
- Owned files: `tests/security/lineage_push/**`, `tests/security/authz/test_catalog_lineage_export.py`.
- Depends on: item 5 (item 6 for the end-to-end cases).
- Acceptance criteria: criteria 4, 6, 7.

### Item 8 - Integration and close-out
- Deliverable: runbook `docs/runbooks/lineage-push-back.md` (separate read and write privileges, operator grant steps, enabling per target, what verify and rollback do, what is never touched); Tier-2 appends; Tier-3 regeneration after rebase; changelog fragment; completion note with the item 1 outcome per target.
- Owned files: the runbook, the fragment, this PRP file, Tier-3 outputs.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
Push-back is the cut. If the session overruns, item 1 has found no target that accepts custom lineage with read-back and delete, or the Tier-1 grant is withheld, then items 1, 2 and 8 merge safely on their own: Unity labels and lineage are read and mapped, and the labels page says "push-back not available" with the reason. Items 3 to 7 move to a follow-up PRP; item 6 alone may follow later, in which case `lineage_push` intents stay advisory (no registered connector) and nothing is written anywhere.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/unity-catalog/tests connectors/reference/purview/tests packages/core/tests/catalog_lineage_export packages/core/tests/catalog_labels packages/core/tests/actions services/workers/tests/lineage_push_target services/workers/tests/connector_runner_role services/api/tests/catalog_lineage_export_api services/api/tests/write_targets_runtime services/api/tests/actions_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/security/lineage_push tests/unit/connector_conformance tests/unit/estate_check services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/connector_estate_check.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive: new connector, new action kind row, new settings defaulting off. Rollback: leave `NS_LINEAGE_PUSH_ENABLED` false (no target registered; intents advisory), disable the `unity_catalog` config, or revert the PR. Lineage already pushed is removed by the executor's rollback of that intent while verify fails, or by an operator-approved follow-up intent; NeuroSphere never removes objects it did not create.

## Live and open gates
OPEN until run with `NS_LIVE_APPROVED=1` and operator approval: a Unity Catalog read in an approved Commercial workspace with the read privilege granted by the operator; a push, read-back and rollback against an approved Purview account and/or Unity workspace, only for targets item 1 verified, with the write privilege granted separately by the operator; Government only if verified. Handed to PRP-136. Pushing lineage writes into a shared enterprise catalog: the session never runs it without that approval.

## NOT building
Lineage push-back everywhere: only where a verified API accepts custom lineage with read-back and delete (design section 8 item 11; `docs/PRD.md:17`). Writing labels, tags or classifications to Purview or Unity. Universal OpenLineage support. Automatic or scheduled pushes (every push is an approved intent). Parity with Purview or Databricks features. Generated SQL against Databricks. Bridging Government data to Commercial. Any compliance claim.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 to 4 are ASSUMPTIONS for plan approval; item 6 needs a Tier-1 grant)

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
- Product check (can a governance lead propose, approve and verify a lineage push without reading code; is the "not available" state visible where it applies):
