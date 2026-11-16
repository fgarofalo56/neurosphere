---
name: PRP-76-catalog-registration-completeness
status: backlog
priority: P1
order: 67
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-02
depends_on: [PRP-70-contracts-revision-restored-scope, PRP-73-graph-access-and-sensitivity-questions, PRP-108-agent-approval-gate-and-platform-control-actions, PRP-105-policy-engine-core]
wave: W24
branch: prp-76-catalog-registration-completeness
allow_parallel: true
issues: []
---

# PRP-76: Catalog registration completeness

## Goal
Make the agent catalog carry the metadata the original PRD required and let people see it change. The registration form gains owner, tags, capabilities, environment, a semver-checked version label and declared data scopes; owner and data-scope choices become audited `owned_by`, `reads` and `writes` edges through a new edge-assert route (today no route can create them by hand). Every create and update writes an immutable revision, so version history is queryable and a History tab shows the diff of declared capabilities between two versions. Agents that telemetry created but nobody registered ("shadow agents") get their own list and page, and a metadata-completeness endpoint and tile report what share of registered agents has an owner, a version label and capability tags. It is for the platform engineer who registers agents, the steward who triages undeclared ones and the platform owner who wants the completeness number. It runs in W24 on PRP-70 (fields, revision contract) and PRP-73 (shipped in W20; both edit `catalog/**`).

Out of scope: the data-access, sensitivity and blast-radius questions (PRP-73, merged first); contract and schema changes (PRP-70 is sole owner of `packages/contracts/**`); configuration findings and Azure Resource Graph shadow-AI discovery (PRP-61); agent or tool recommendation (PRP-72, PRP-75); the map badge for undeclared agents (PRP-77 may read the list route); automatic consolidation or merging of agents (never automatic); a user delete (deprecation stays the only retirement).

## Why
Original PRD (2026-10-02, `git show 9fbf5f4c:docs/PRD.md`) stories and criteria this restores:
- 5b story: "As a platform engineer, I want to register a new agent version and see its diff against the prior version's declared capabilities."
- 5b criteria: "CRUD API + UI for agent registration with required metadata schema (owner, semver, tags, data scopes)." "Full version history retained and queryable." "Stale/undeclared agents detected via telemetry-vs-catalog reconciliation job (flags "shadow agents")."
- Success metric: "% of registered agents with complete metadata (owner, version, capability tags)" with target "> 95%".

What v1.2 removed or demoted: `docs/PRD.md:14` lists the entity types (AgentVersion included) and `docs/PRD.md:17` lists "Search/CRUD/import/export, optimistic concurrency, lifecycle deprecation, ownership recertification, stale-agent reconciliation and scope-filtered lineage"; the metadata schema, version history, diff, undeclared-agent flagging and the completeness metric appear nowhere in v1.2, and the success-metrics table was not carried over.

Evidence from the current tree (re-verified in this worktree):
- The form has no owner, tags, version or scope fields (`frontend/src/features/catalog/EntityForm.tsx`, model in `entityFormModel.ts`); the agent contract has no `tags`, `capabilities` or `environment` (PRP-70 adds them); `AgentVersion.version_label` is a free string (`packages/contracts/python/neurosphere_contracts/catalog/v1/agent_version.py:69`).
- No route creates an edge: `CatalogRepository.put_edge` exists (`packages/core/neurosphere_core/catalog/protocol.py:264`) and the curation service writes edges only for stewards' decisions (`services/api/neurosphere_api/catalog/curation/service.py:354-356`), so an agent created in the UI is an isolated node.
- `update_entity` replaces in place and no history method exists on `CatalogRepository` (`catalog/protocol.py:199-340`; `CatalogService.update`, `services/api/neurosphere_api/catalog/service.py:305-339`). The only diff is form versus current before saving (`entityFormModel.ts` `diffRows`, line 215).
- Projections write `attributes.discovered_from` on draft entities (`services/workers/neurosphere_workers/projections/catalog/discovery.py:43`) and nothing in the API or frontend reads it. The inverse, stale agents, has a plan, confirm and page (`catalog/service.py:562-700`, `StaleAgentsPage.tsx`).
- Route trap: `GET /api/v1/catalog/entities/{entity_id:path}` swallows any longer path under `/entities` (`catalog/router.py:256`), so history cannot be a sub-path of an entity.

## Acceptance criteria
- [ ] Given an authorized steward, When they register an agent in `/catalog` with owner, tags, capabilities, environment, a version label and declared data scopes, Then the entity is created with the PRP-70 fields and, after the entity write succeeds, `owned_by`, `reads` and `writes` edges exist with provenance method `declared`, status `asserted` and evidence ids, each audited; a failure on one edge is reported per edge and never leaves a partial success unreported.
- [ ] Given `POST /api/v1/catalog/edge-assertions` for a relation outside `owned_by`, `reads`, `writes`, a target of the wrong entity type, an endpoint in a domain the caller cannot curate, or a body that names another customer or cloud, Then it is refused (422 or 403, with a denial record) and nothing is stored; asserting an edge that already exists is idempotent and returns it.
- [ ] Given a version label that is not semantic versioning, Then create and update return 422 with reason `invalid_version_label`; the form blocks it client-side with the same rule.
- [ ] Given any create or update of an entity, Then an immutable revision (entity id, entity version, ETag, actor pseudonym, changed-field names, the declared-field snapshot, timestamp) is stored; revisions are append-only, scope-filtered and idempotent by (entity id, version); when the revision store is down the entity write still succeeds and the response carries a reason-coded warning, the history shows a visible gap, and a counter records it.
- [ ] Given an entity written before this PRP, When history is requested, Then the current state is returned as one revision flagged `reconstructed`; no earlier version is invented.
- [ ] `GET /api/v1/catalog/versions?entity_id=` lists revisions newest first, bounded and paged; `GET /api/v1/catalog/versions/diff?entity_id=&from=&to=` returns field-level changes with added and removed capabilities, tags and data scopes called out; an entity outside the caller's scope is 404 with no leak.
- [ ] Given telemetry-created draft agents (`discovered_from = telemetry`), When `GET /api/v1/catalog/undeclared-agents` runs, Then it lists them with first and last seen (from their edges, bounded scan with the stale-agent page cap), the domain, the discovery rule and a `truncated` flag; agents a steward already registered (active) or deprecated are absent; the page offers "Register", which opens the edit form prefilled for that draft.
- [ ] `GET /api/v1/catalog/completeness` returns, for registered (active) agents in the caller's scope: totals, counts and ratios for owner, version label, capability tags and all three together; ratios are `null` (never 0 or 100) when there are no agents; a field PRP-70 does not provide is reported `unavailable` with a reason code; the explorer shows the tile with the scan bound and a partial-result note.
- [ ] Given the registration check from PRP-108 (`RegistrationCheck`) is in `enforce` mode, When an update would move an AgentVersion's `lifecycle_status` to `active`, Then the catalog service refuses it with reason `registration_blocked` unless the approval state is `approved`; in `audit` and `off` mode the update is unchanged (a test per mode).
- [ ] Every new route requires an explicit permission (`data.read` for reads, `catalog.curate` for writes), derives scope from the server identity, is in the route inventories and aliased under `/catalog/...`; reads of the new routes are audited with `audited_read`.
- [ ] The History tab on the entity page shows revisions and a two-version diff; `/catalog/undeclared` and the explorer tile pass axe in light, dark and high-contrast; no string claims an estate is complete or compliant.
- PRP exit: a steward registers an agent with an owner and data scopes in one flow, edits its capabilities, opens History and sees the capability diff, triages an undeclared agent from the list, and the explorer shows the completeness percentage.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where revisions live | Inside the catalog container; new container | New container `catalog_revisions` (customer and domain partition, like `catalog_review_queue`); this PRP is the Tier-1 stores owner in W24 (`stores/containers.py`, `infra/compose/cosmos-containers.json`, `infra/demo/modules/cosmos-data.bicep`; `infra/bicep/modules/cosmos.bicep` defines no containers, per the PRP-43 note) |
| 2 | Revision write ordering | Before the entity write; after | ASSUMPTION: after a successful entity write, idempotent by (entity id, version), so a failed entity write leaves no phantom revision; a failed revision write is a visible gap, not an error |
| 3 | History route shape | Sub-path of an entity; separate prefix with query parameters | `/api/v1/catalog/versions?entity_id=...` because `/entities/{entity_id:path}` would match any sub-path |
| 4 | Edge-assert permission | `data.read`; `catalog.curate` | `catalog.curate` on the source entity's domain, the rule the entity update uses. ASSUMPTION: asserting an edge to an entity in another domain also needs read of that entity through `get_entity` |
| 5 | "Version" in completeness | Revision count; a label field | PRP-70 puts `semver` only on `AgentVersion` (the `Agent` has no version field), so count agents with at least one linked version that has a non-null `semver` and say so in the response `basis` |
| 6 | Registered versus draft | Include drafts; active only | Active agents only; undeclared drafts are reported separately so the metric is not diluted by agents nobody registered |
| 7 | Edge-assert endpoints | Any relation; allowlist | Allowlist `owned_by` (agent, tool, service, model deployment, grounding source to an owner), `reads` and `writes` (agent to grounding source); other relations stay with import and curation |
| 8 | Undeclared source of truth | New reconciliation job; read existing drafts | Read the existing drafts the projections already create (no new job). ASSUMPTION: unresolved candidates in `catalog_quarantine` are not "agents" yet and are not listed |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/catalog/service.py:123-340,562-700` - `CatalogService` create, update, `_guarded`, stale-agent scan to imitate.
- `services/api/neurosphere_api/catalog/dependencies.py:61-66` - `get_service` builds the service per request: the revision store arrives through a new dependency.
- `services/api/neurosphere_api/catalog/curation/service.py:340-360` - audited edge writes; `curation/router.py:60-82` guards.
- `packages/core/neurosphere_core/catalog/protocol.py:199-340` - repository methods; `catalog/repo/cosmos.py` for the Cosmos pattern.
- `packages/core/neurosphere_core/catalog/review_queue_cosmos.py` and `packages/core/neurosphere_core/stores/containers.py:160-180` - the newest container and its registry row.
- `services/api/neurosphere_api/runtime/builders/gateway.py` - shared Cosmos client and override seam for a new builder; `runtime/builders/__init__.py` `default_builders`.
- `frontend/src/features/catalog/EntityForm.tsx`, `entityFormModel.ts` (`diffRows`, `buildBody`, `validate`), `CatalogEntityPage.tsx`, `StaleAgentsPage.tsx`, `CatalogExplorerPage.tsx`.
- `services/workers/neurosphere_workers/projections/catalog/discovery.py` - the draft entity shape and `discovered_from`.
- `PRPs/backlog/PRP-70-contracts-revision-restored-scope.md` - "Interfaces provided" (field names, sensitivity vocabulary, revision record).

### Interfaces consumed
- PRP-70: `tags`, `capabilities`, `environment` on `Agent` and `Tool` (`tags`, `environment` on `Service`); `AgentVersion.semver`, `tags`, `capabilities`; `EntityRevision` and `EntityRevisionDiff` (fields as listed in PRP-70, `check_revision_version_order`); `sensitivity_categories` and `residency_geography` on `GroundingSource`; `owner` and edge schemas as shipped. This PRP edits no contract.
- PRP-73 (merged in W20): new files only (`catalog/graph/access.py`, `catalog/access/**`, `routes.tsx` and `paths.ts` lines); nothing here depends on its code except `routes.tsx` and `paths.ts` co-editing.
- Shipped: `CatalogRepository.put_edge` and `list_edges_by_node`, `run_audited_mutation`, `audited_read`, `entity_access`, `RouterRegistry`, `register_with_alias`.

### Interfaces provided
- Core: `neurosphere_core.catalog.revisions` - `RevisionStore` protocol, `InMemoryRevisionStore`, `CosmosRevisionStore`, `diff_revisions`, `is_semver`; container `catalog_revisions`.
- Routes (all aliased under `/catalog/...`): `GET /api/v1/catalog/versions`, `GET /api/v1/catalog/versions/diff`, `POST /api/v1/catalog/edge-assertions`, `GET /api/v1/catalog/undeclared-agents`, `GET /api/v1/catalog/completeness`.
- API: `neurosphere_api.catalog.revisions`, `catalog.edges`, `catalog.undeclared` packages; component `catalog_revisions` (optional) in `runtime/status.py`; audit operations `catalog.edge_assert`, `catalog.versions`, `catalog.undeclared`, `catalog.completeness`.
- Frontend: routes `catalog/undeclared` and the History tab; mock handlers `frontend/tests/mock-api/features/catalog-registration.ts`. PRP-77 and PRP-78 may call the undeclared and completeness routes.
- Compatibility with PRP-73 (W20, already merged): this PRP edits the existing files PRP-73 deliberately left alone (`catalog/service.py`, `catalog/dependencies.py`, `EntityForm.tsx`, `entityFormModel.ts`, `CatalogEntityPage.tsx`, `CatalogExplorerPage.tsx`) and appends to `routes.tsx` and `paths.ts` after rebasing on PRP-73's lines. It does not edit `catalog/graph/access.py`, `catalog/access/**` or the worker mapping.

### Patterns to match
- Bounded scan with page cap and `truncated`: `catalog/service.py:562-602`.
- Audited mutation and denial records: `catalog/service.py:144-232`; edge write: `curation/service.py:340-360`.
- Cosmos container store with ETag and in-memory twin: `neurosphere_core/catalog/review_queue_cosmos.py`, `catalog/review_queue.py`.
- Optional builder component and override seam: PRP-41 `runtime/builders/edge.py` and `gateway.py`.
- Form diff and confirm dialog: `EntityForm.tsx:150-200`, `frontend/src/features/governed-change`.

### Gotchas
- The entity route swallows sub-paths; keep the new prefixes `versions`, `edge-assertions`, `undeclared-agents`, `completeness` (none starts with `entities`). The path-alias suite requires every `/api/v1/catalog` route to have its alias.
- Adding an API builder breaks tests that pin `default_builders` order and the component set: update `services/api/tests/runtime_api/test_readiness.py`, `services/api/tests/runtime_gateway_builder/test_gateway_builder.py` and `services/api/tests/runtime_data/data_helpers.py`.
- `CatalogService` has no clock-free constructor path for the new store: add an optional keyword `revisions` (default `None`) so every existing construction and test stays valid.
- Edge ids are canonical (`<cloud>:<customer>:<source>:owned_by:<slug>`); derive the slug deterministically from source and target so a repeated assertion is the same edge.
- `update` keeps server-owned fields from the stored entity (`_IMMUTABLE`); the revision snapshot must hold the declared fields after that merge, not the request body.
- The explorer page and entity form are large; keep new components in new files (`history/`, `undeclared/`) and add only wiring lines to existing ones.
- Same-named test directories shadow each other; unique names are listed below.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/catalog/revisions/**
  - packages/core/tests/catalog_revisions/**
  - services/api/neurosphere_api/catalog/revisions/**
  - services/api/neurosphere_api/catalog/edges/**
  - services/api/neurosphere_api/catalog/undeclared/**
  - services/api/neurosphere_api/catalog/service.py
  - services/api/neurosphere_api/catalog/dependencies.py
  - services/api/neurosphere_api/runtime/builders/catalog_revisions.py
  - services/api/tests/catalog_registration_api/**
  - tests/security/authz/test_catalog_registration*.py
  - frontend/src/features/catalog/history/**
  - frontend/src/features/catalog/undeclared/**
  - frontend/src/features/catalog/EntityForm.tsx
  - frontend/src/features/catalog/entityFormModel.ts
  - frontend/src/features/catalog/CatalogEntityPage.tsx
  - frontend/src/features/catalog/CatalogExplorerPage.tsx
  - frontend/src/features/catalog/routes.tsx
  - frontend/src/features/catalog/paths.ts
  - frontend/tests/mock-api/features/catalog-registration.ts
  - frontend/tests/e2e/catalog-registration/**
  - docs/runbooks/catalog-registration.md
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
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
  - packages/core/neurosphere_core/catalog/graph/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - services/api/neurosphere_api/catalog/access/**
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/**
  - frontend/src/features/catalog/access/**
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Parallelization: item 1 first. Items 3 and 4 are [P] after item 2 (separate packages). Items 5 and 6 are sequential (both edit `routes.tsx`). Item 7 after 5 and 6; item 8 last.

### Item 1 - Revision store and container
- Deliverable: `catalog/revisions/` with the revision model (from PRP-70's record), `RevisionStore` protocol (append idempotent by entity id and version, list newest first with page bound, get by version), in-memory and Cosmos stores, `diff_revisions` (field changes; set differences for tags, capabilities, data scopes), `is_semver`; the `catalog_revisions` container row in `stores/containers.py`, `infra/compose/cosmos-containers.json` and `infra/demo/modules/cosmos-data.bicep`.
- Owned files: `packages/core/neurosphere_core/catalog/revisions/**`, `packages/core/tests/catalog_revisions/**`, the three Tier-1 store files.
- Must NOT touch: `catalog/protocol.py`, `catalog/repo/**`.
- Depends on: PRP-70 and PRP-73 merged.
- Acceptance criteria: append is idempotent; list is scope-filtered and bounded; the diff is deterministic and ignores server-owned fields (`etag`, `updated_at`); the stores-registry tests pass with the new row.
- Tests: `packages/core/tests/catalog_revisions/test_store.py`, `test_diff.py`, `test_semver.py`; `packages/core/tests/stores_registry`.
- Pattern references: `neurosphere_core/catalog/review_queue_cosmos.py`.

### Item 2 - Revisions in the service, versions routes and builder
- Governance-core additions: the registration form leaves a labelled slot for the run-as identity field (PRP-118 fills it; this PRP adds no identity logic) and a slot for the approval panel (PRP-108 mounts `frontend/src/features/catalog/approval/**` into `CatalogEntityPage.tsx`); and `CatalogService` closes the direct path that sets an AgentVersion `active` without approval (PRP-108 is a dependency): when the registration check from PRP-108 is in `enforce` mode (the registration enforcement binding of PRP-105), an update that moves `lifecycle_status` to `active` calls the registration check and is refused with reason `registration_blocked` unless the approval state is `approved` (default `off`/`audit` behaviour unchanged). `catalog/service.py` stays this PRP's file.
- Deliverable: `CatalogService` takes an optional revision recorder, writes revision 1 on create and one per update after the entity write, validates the version label, and returns a reason-coded warning when the revision write fails; `get_revision_store` dependency; `revisions/router.py` with the two read routes under `audited_read`; builder `runtime/builders/catalog_revisions.py` (Cosmos on the shared client, in-memory only under `NS_ENV=local`), optional component `catalog_revisions`; `reconstructed` current revision for legacy entities.
- Owned files: `catalog/service.py`, `catalog/dependencies.py`, `catalog/revisions/**`, `runtime/builders/catalog_revisions.py`, `services/api/tests/catalog_registration_api/test_versions.py`, `test_revision_failure.py`, `test_builder.py`; updated pinned tests listed in Gotchas.
- Must NOT touch: `catalog/router.py`, `runtime/builders/data.py`.
- Depends on: item 1.
- Acceptance criteria: the revision, legacy and failure-gap criteria; the activate-without-approval path is refused under `enforce` and unchanged under `off` (a test per mode); existing `services/api/tests/catalog` and `catalog_api` suites pass unchanged except the pinned component lists.
- Tests: the three new files plus `services/api/tests/catalog`, `catalog_api`, `runtime_api`, `runtime_gateway_builder`, `runtime_data`.
- Pattern references: `catalog/service.py:144-232`; PRP-41 builder.

### Item 3 - Edge-assert route  [P]
- Deliverable: `catalog/edges/{router,service,models}.py` implementing `POST /api/v1/catalog/edge-assertions` (allowlist, type checks, scope and domain checks, deterministic id, provenance `declared`, evidence id of the form `declared:<audit correlation>`, idempotent replay), audited on the source domain's chain; `register(registry)` hook.
- Owned files: `services/api/neurosphere_api/catalog/edges/**`, `services/api/tests/catalog_registration_api/test_edge_assert.py`.
- Must NOT touch: `curation/**`, `catalog/router.py`.
- Depends on: item 2.
- Acceptance criteria: the edge criteria; evidence is append-only on repeat; a denial writes a record.
- Tests: `test_edge_assert.py`, `test_edge_assert_scope.py`.
- Pattern references: `curation/service.py:340-360`.

### Item 4 - Undeclared agents and completeness  [P]
- Deliverable: `catalog/undeclared/{router,service,models}.py` with `GET /undeclared-agents` and `GET /completeness`, both bounded scans with `truncated`, `audited_read`, aliases.
- Owned files: `services/api/neurosphere_api/catalog/undeclared/**`, `services/api/tests/catalog_registration_api/test_undeclared.py`, `test_completeness.py`.
- Must NOT touch: the worker discovery module, `catalog/service.py` (copy the scan pattern, do not import its private helpers).
- Depends on: item 2.
- Acceptance criteria: the undeclared and completeness criteria, including `null` ratio for zero agents and `unavailable` for a missing PRP-70 field.
- Tests: the two files above.
- Pattern references: `catalog/service.py:562-640`.

### Item 5 - Registration form and History tab
- Deliverable: owner picker (active `owner` entities), tag and capability inputs, environment, version label with semver check, data-scope pickers (grounding sources, read or write); after the entity save the form calls the edge-assert route per scope and reports per-edge results; `history/` with `HistoryTab`, revision list and `RevisionDiff` reusing the diff row component; wiring in `CatalogEntityPage.tsx`; mock handlers.
- Owned files: `EntityForm.tsx`, `entityFormModel.ts`, `CatalogEntityPage.tsx`, `frontend/src/features/catalog/history/**`, `frontend/tests/mock-api/features/catalog-registration.ts`.
- Must NOT touch: `frontend/src/features/catalog/access/**`, `server.ts`.
- Depends on: items 2 and 3 (response shapes).
- Acceptance criteria: form criteria and History criterion; existing `catalog-write.test.tsx` and `catalog.test.tsx` pass with only fixture additions.
- Tests: `frontend/src/features/catalog/history/history.test.tsx`, `frontend/src/features/catalog/registration.test.tsx` (new), existing catalog tests.
- Pattern references: `EntityForm.tsx`, `governed-change`.

### Item 6 - Undeclared page and completeness tile
- Deliverable: `undeclared/` with `UndeclaredAgentsPage` (table, first and last seen, "Register" opening the prefilled form), the completeness tile in `CatalogExplorerPage.tsx`, route and nav lines in `routes.tsx`, `paths.ts`.
- Owned files: `frontend/src/features/catalog/undeclared/**`, `CatalogExplorerPage.tsx`, `routes.tsx`, `paths.ts`.
- Depends on: items 4 and 5.
- Acceptance criteria: page and tile criteria; the tile shows "not enough data" for a null ratio.
- Tests: `frontend/src/features/catalog/undeclared/undeclared.test.tsx` (new).
- Pattern references: `StaleAgentsPage.tsx`.

### Item 7 - Authorization, registration and e2e
- Deliverable: ABAC negative suite for all five routes (no role, viewer, steward of another domain, wrong customer or cloud, body-supplied scope), a leak test for the versions and undeclared routes, Tier-2 registrations, Playwright specs for register-with-scopes, history diff and undeclared triage, axe in three themes, runbook.
- Owned files: `tests/security/authz/test_catalog_registration*.py`, `frontend/tests/e2e/catalog-registration/**`, `docs/runbooks/catalog-registration.md`, Tier-2 lines.
- Depends on: items 5 and 6.
- Acceptance criteria: every route has a deny case per dimension; manifest, axe and keyboard suites pass.
- Tests: `tests/security/authz`, `frontend/tests/e2e/catalog-registration/registration.spec.ts`.
- Pattern references: PRP-41 authz suite, `frontend/tests/e2e/catalog/catalog.spec.ts`.

### Item 8 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`), changelog fragment `changelog.d/PRP-76-catalog-registration-completeness.md`, completion note with the product check (can a steward register an agent with owner and scopes and read its history without raw API calls?).
- Owned files: this PRP file, the fragment, Tier-3 files.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/catalog_revisions packages/core/tests/catalog packages/core/tests/stores_registry services/api/tests/catalog_registration_api services/api/tests/catalog services/api/tests/catalog_api services/api/tests/catalog_access_api services/api/tests/read_audit_api services/api/tests/path_aliases services/api/tests/runtime_api services/api/tests/runtime_gateway_builder services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5293 NS_MOCK_API_PORT=5294 pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines: `visual:update` in the pinned Docker image, then `visual:check`.

## Migration and rollback
New container `catalog_revisions` (created by the emulator bootstrap locally and by `infra/demo/modules/cosmos-data.bicep` on the next deploy); existing entities need no migration (legacy history is a flagged `reconstructed` revision). New agent fields are optional (PRP-70). Rollback: revert the PR; the empty or populated container is left in place and inert; edges created through the assert route are ordinary `declared` edges and remain valid. To stop revision writes without a revert, leave the builder disabled (no Cosmos, no override): the service runs with no recorder and the history routes answer 503 `revisions_unconfigured`.

## Live and open gates
None run here: behaviour is proven on in-memory twins, the mock API and (locally) the Cosmos emulator. A live read of revisions in a hosted environment follows the PRP-58 and PRP-82 deploy and is operator-gated (PRP-64, `NS_LIVE_APPROVED=1`). Visual baselines are Docker-only.

## NOT building
A user delete or hard purge of revisions; revision restore or rollback of an entity; per-field approval workflows; an automatic reconciliation job or a new worker; bulk edge assertion (import already exists); the map badge for undeclared agents (PRP-77); recommendation features; any claim that metadata completeness equals quality or compliance.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 4, 5 and 8 are ASSUMPTIONS for plan approval)

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
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files or calling raw APIs?):
