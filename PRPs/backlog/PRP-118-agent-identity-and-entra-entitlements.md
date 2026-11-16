---
name: PRP-118-agent-identity-and-entra-entitlements
status: backlog
priority: P1
order: 118
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-02, NS-08, NS-09
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation, PRP-76-catalog-registration-completeness]
wave: W27
branch: prp-118-agent-identity-entitlements
allow_parallel: true
issues: []
---

# PRP-118: Agent identity and Entra entitlements

## Goal
Model what each agent CAN do, not only what it did. Every agent, agent version, tool, service or MCP server can carry a `runs_as` edge to a `workload_identity` entity (app registration, service principal, managed identity, and an Entra Agent ID only if verification finds a documented API), declared by the owner at registration or discovered where Foundry or ARM documents it. A read-only connector, `connectors/reference/entra-identity/` (kind `entra_identity`, scaffolded `not_built` by PRP-117 and run by the generic `connector_runner`), collects for those identities only: the identity object, its app role assignments and delegated permission grants, and Azure role assignments at the scopes the operator authorizes, through documented, admin-consented directory and resource-management APIs. Observations become `entitled_to` edges carrying `Entitlement` fragments onto data assets, services, model deployments and MCP servers. Every identity says how much of its entitlements were collected, so nothing downstream reads "no edges" as "no access". It is for the security lead who must answer "what is this agent allowed to touch", and for PRP-119 (over-privilege and "who could"), PRP-126 (shadow AI) and the policy rule `identity_entitlement`.

Out of scope: over-privilege findings, the "who could" query and the `identity_entitlement` evaluator (PRP-119); the contracts (`WorkloadIdentity`, `RunsAs`, `EntitledTo`, `Entitlement`, all PRP-110); the runner, scaffold, verification template and coverage page (PRP-117); sign-in logs and consent grants for shadow-AI discovery (PRP-126); Purview and Unity labels (PRP-120, PRP-121); data-plane permissions inside data services (SQL grants, storage ACLs, search keys, SharePoint item permissions), which are out of reach (design section 8 item 8); the live run (PRP-136).

## Why
- No run-as identity exists anywhere: `Agent`, `AgentVersion`, `Tool` and `Service` have none; the closest shapes are `Grant.principal` (`packages/contracts/schemas/catalog/v1/grant.schema.json:64-97`, an Entra `object_id` a gateway matches) and `Owner.owner_kind: service_principal` (`packages/contracts/schemas/catalog/v1/owner.schema.json:70`). The core entity union stops at 14 types (`packages/core/neurosphere_core/catalog/protocol.py:70-117`).
- No directory read in product code: the only Microsoft Graph calls are in an operator gate script (`scripts/gates/p29_entra_local.py:55-56,144-161`); Azure Resource Graph is used by the deploy scan only, inside a consent-bound in-memory call (`services/api/neurosphere_api/deploy/scan/graph.py:18-50`).
- PRP-73 answers "who did" from observed `reads` and `writes` edges; nothing can answer "who could", which needs entitlements (design G-c).
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool", every identified gap planned; the governance-core design (`temp/audit/governance-core-design.md` PRP-118 entry, sections 8 and 9) scopes this PRP and its degradation ("declared identities only, entitlements not collected, stated on the page").
- `docs/PRD.md` NS-08 heading "Identity, security and compliance alignment" and NS-09: "Publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent."

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/entra-identity.md` has every heading of PRP-117's template and, per signal (service principal and application object, managed identity, app role assignments, delegated permission grants, directory role membership, Azure role assignments, Entra Agent ID, run-as discovery from Foundry and from ARM resource identity), records: documentation URL and retrieval date, documented endpoint, the exact least-privilege permission or role and its admin-consent requirement, licence if any, paging and rate limits, Commercial and Government availability, fields used, and "not found" where the documentation has no such signal. `scripts/connector_estate_check.py` passes and the descriptor moves to `built` only with this file.
- [ ] Given an agent version registered with a declared run-as identity (kind, client id or resource id), When the owner saves it through `POST /api/v1/catalog/identity/domains/{domain}/run-as`, Then a `workload_identity` entity (`discovery: declared`) and a `runs_as` edge (`status: asserted`) exist, the write is audited, and re-submitting the same identity reuses the entity (deterministic canonical id from cloud, customer and client id or resource id; never from a display name).
- [ ] Given a configured `entra_identity` connector and fakes of the verified APIs, When the runner ticks, Then for each in-scope `workload_identity` the connector reads only that identity's objects and assignments (no tenant-wide enumeration of users or groups), and the projection writes `entitled_to` edges with `Entitlement` (`grant_kind`, `role_or_permission`, `scope_ref`, `plane`, `access`, `source`, `first_observed`, `last_observed`); an assignment whose target matches no catalog entity is counted under `unmatched_targets`, never creates an entity.
- [ ] Each identity carries `attributes.entitlement_collection` (`collected`, `partial`, `not_collected`, `failed`), `attributes.entitlement_collected_at` and `attributes.entitlement_planes`; an identity never reached is `not_collected`, never "no entitlements"; an entitlement not seen in a later complete run gets `valid_to` set, while a truncated or failed run changes nothing.
- [ ] Role to access mapping (`read`, `write`, `admin`; plane `control` or `data`) comes from a data file with source URL and retrieval date; a role or permission not in the file maps to `access: admin` with reason `unmapped_role` (conservative), never to `read`.
- [ ] Discovered run-as: only where item 1 verified a documented field (for example a resource's managed identity in ARM), a `runs_as` edge with `status: inferred` and provenance `import` is proposed for the catalog entity whose `resource_ref` equals that resource; a steward can reject it through the existing curation routes; a declared edge is never overwritten.
- [ ] Without consent or credentials the connector records reason `identity_consent_missing` or `connector_credential_unavailable`, the identity panel says "entitlements not collected" with the reason, and declared identities still show; no token, secret, assertion or response body appears in logs, status documents or audit records (leak test).
- [ ] Government boundary: a Government deployment calls only the hosts item 1 verified for Government, or, if none, refuses the config 422 `connector_cloud_unsupported`; no request leaves for a Commercial host and nothing is copied across clouds (test with a recording transport).
- [ ] `GET /api/v1/catalog/identity/domains/{domain}/subjects/{entity_id}` returns the subject's run-as identities, their entitlements and collection state, needs `data.read`, writes an `audited_read` record (operation `catalog.identity_read`, domains and count only), hides out-of-scope targets entirely; the run-as route needs `catalog.curate`; deny cases pass for no role, wrong domain, wrong customer, wrong cloud and expired assignment.
- [ ] The registration form for the form types that can be a `runs_as` source (`agent`, `tool`, `mcp_server`; `entityFormModel.ts:8` `FORM_TYPES`, `model_deployment` is not a run-as source) offers an optional "Runs as" field, and agent versions and services get a "Declare run-as identity" action on the identity panel; the entity page shows an identity panel with entitlements, plane, access, source, last observed and the collection state; axe passes in three themes.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated; the live Graph and ARM read recorded OPEN for PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Which identities are collected | Whole tenant; only run-as identities | Only identities referenced by a `runs_as` edge in scope (design PRP-118 entry: "collects for those identities"). Least data, least permission |
| 2 | Permissions NeuroSphere's identity requests | Broad directory read; least privilege | Least privilege as intent: read-only, application permissions sufficient for the signals in Clarification 1, written exactly from documentation in item 1; admin consent is an operator step in the runbook, never automated |
| 3 | Credential | Client secret in settings; reference | Credentials only as PRP-42 references (`managed_identity` preferred, `key_vault_secret` otherwise); never a value in settings, logs or audit |
| 4 | Entra Agent ID | Model now; verify first | Verify first (U-9). `identity_kind: entra_agent_id` is used only if item 1 finds a documented API in the target cloud; otherwise "not modelled" in the verification file |
| 5 | Unknown roles | Ignore; read; admin | ASSUMPTION (GD-33, recommended default): an unmapped role or permission is `admin` with reason `unmapped_role` so "who could" over-reports rather than under-reports |
| 6 | Where collection state lives | New container; entity attributes | ASSUMPTION: scalar `attributes` on `WorkloadIdentity` (`entitlement_collection`, `entitlement_collected_at`, `entitlement_planes`); no container (no stores owner in W27) |
| 7 | How the connector gets its identity list and writes its output | Connector reads the catalog; runner binding | ASSUMPTION: the identity projection supplies an `IdentityTargetSource` and an `IdentityObservationSink` through PRP-117's per-kind binding hook (entry point group `neurosphere.connector_bindings`, kind `entra_identity`, already declared by PRP-117 and pointing at `neurosphere_workers.projections.identity.binding:BINDING`, which this PRP writes); nothing under `connector_runner/` is edited |
| 8 | Run-as route | Extend `catalog/router.py`; own package | Own package `catalog/identity/` (PRP-76 owns `catalog/router.py` and `catalog/service.py` in W24; nothing here edits them). If PRP-76's `POST /catalog/edge-assertions` accepts `runs_as`, the route reuses its service function |
| 9 | Entitlement write semantics | Create-only; update | Edges are upserted by the projection (they change); entities follow create-only discovery (`foundry_discovery/poller.py`), so a steward's identity is never overwritten |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-110-governance-contracts-b.md` "Interfaces provided", Identity section - every name used here.
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` "Interfaces provided" and Gotchas "Shared-file rules for the connector wave" - binding on this PRP.
- `docs/connectors/verification/_TEMPLATE.md` (PRP-117) - headings item 1 must fill.
- `packages/core/neurosphere_core/catalog/protocol.py:70-140,199-280` - literals, entity and edge unions, `create_entity`, `update_entity`, `put_edge`.
- `packages/core/neurosphere_core/catalog/repo/documents.py:59,135` - `ENTITY_MODELS` is derived from the union.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:112-290` - create-only discovery, `_ensure`, worker scope.
- `services/workers/neurosphere_workers/connector_config/resolve.py:111-130` and `keyvault.py` - credential reference resolution.
- `packages/core/neurosphere_core/cloud/profile.py:21-92` - per-cloud hosts (no directory host there; item 1 records it).
- `services/api/neurosphere_api/authz/read_audit.py:176-195` - `audited_read`.
- `frontend/src/features/catalog/EntityForm.tsx`, `entityFormModel.ts:8-12`, `EntityTypeDetails.tsx:126` - form types and per-type rows.

### Interfaces consumed
- PRP-110 (W25): `WorkloadIdentity` (`identity_kind`, `client_id`, `resource_id`, `discovery`, `source_connector_id`, `attributes`), `RunsAs`, `EntitledTo` with 1-32 `Entitlement`, core literals `workload_identity`, `runs_as`, `entitled_to`, `IdentityEntitlementParams` (for PRP-119).
- PRP-117 (W26): `ConnectorDescriptor`, `EstateConnector`, `RunContext` (`http` egress-guarded, `credentials`, `clock`, `since`), `RunResult`, `InventorySink`, the verification template and `scripts/connector_estate_check.py`, discovered conformance.
- PRP-99 (W20): `connector_kind` value `entra_identity`.
- PRP-76 (W24): registration form layout, `POST /api/v1/catalog/edge-assertions`, revision history (identity writes appear there).
- PRP-42 (shipped): `CredentialReference` kinds `key_vault_secret`, `managed_identity`.
- Shipped: `CatalogRepository`, `rules.present_edge` and curation routes, `audited_read`, `Permission.DATA_READ`, `Permission.CATALOG_CURATE`.

### Interfaces provided
- Core `neurosphere_core.catalog.identity`: `workload_identity_id(cloud, customer, *, client_id=None, resource_id=None)`, `IdentityObservation`, `EntitlementObservation`, `to_entitlement(obs, role_map) -> Entitlement`, `RoleAccessMap` loaded from `catalog/identity/data/role_access.yaml` (source URL, retrieval date), `CollectionState` literal, `IdentityTargetSource` and `IdentityObservationSink` ports, `identity_view(scope, entity_id) -> SubjectIdentityView` (identities, entitlements, collection state, `unmatched_targets` count).
- Catalog unions: `CatalogEntity` gains `WorkloadIdentity`; `CatalogEdge` gains `RunsAsRelation`, `EntitledToRelation` (generated names from PRP-110).
- Worker `neurosphere_workers.projections.identity`: `IdentityProjection` (implements both ports), `bind_entra_identity(...)`.
- Connector `neurosphere_connector_entra_identity`: `DESCRIPTOR` (kind `entra_identity`, mode `read`), settings `tenant_id`, `arm_scopes` (bounded list of subscription or resource-group ids), `include_directory_roles` (bool).
- Routes: `POST /api/v1/catalog/identity/domains/{domain}/run-as` (`catalog.curate`), `GET /api/v1/catalog/identity/domains/{domain}/subjects/{entity_id}` (`data.read`, audited); alias under `/catalog/identity`.
- Audit operations `catalog.identity_declare`, `catalog.identity_read`.
- Frontend `frontend/src/features/catalog/identity/` (`RunAsField`, `IdentityPanel`); mock handlers `frontend/tests/mock-api/features/catalog-identity.ts`.

### Patterns to match
- Create-only discovery with collision counting: `foundry_discovery/poller.py:168-290`.
- Edge candidate and evidence shape: `services/workers/neurosphere_workers/projections/catalog/mapping.py:172-200`.
- Bounded ARM reads with fixed API version and cloud host: `services/api/neurosphere_api/deploy/scan/graph.py:18-50`.
- Router with alias and read audit: PRP-73's `catalog/access/router.py` (W20) or `services/api/neurosphere_api/catalog/router.py:263-298`.
- Connector package layout and tests: `connectors/reference/azure-billing/`.

### Gotchas
- UNVERIFIED (design U-7): "Microsoft Graph exposes app registrations, service principals, app role assignments, delegated permission grants, sign-in logs and consent grants to an admin-consented application, in both clouds." If false: declared identities only; entitlements "not collected".
- UNVERIFIED (design U-8): "Azure role assignments are listable through ARM or Resource Graph at authorized scopes." If false: entitlements limited to directory permissions.
- UNVERIFIED (design U-9): "Entra Agent ID exists as a documented identity type with an API." If false: not modelled.
- Subagents have no Microsoft Learn tool (memory): the orchestrator fetches the documentation for item 1 and pastes URLs, retrieval dates and the exact facts into the brief; nothing is written from memory.
- `ConnectorConfig.settings` refuses names matching `secret|passw|pwd|token|key|...` (PRP-117 Gotchas): use `tenant_id`, `arm_scopes`.
- A role assignment's scope may be a management group, subscription or resource group above the asset. The projection applies it to each in-scope catalog entity whose `resource_ref` equals or lies under that scope (bounded; `scope_expansion_truncated` when the bound hits) and keeps the original scope in `Entitlement.scope_ref`; it never lists Azure resources that are not catalog entities. Resource-id comparison is by normalised path segments, never substring.
- `client_id` is an identifier, not a credential, but object ids and client ids of real tenants must not appear in fixtures: use obviously synthetic GUIDs.
- Graph or ARM throttling responses are recorded as `rate_limited` with backoff (PRP-117 runner); never retry in a tight loop.
- Adding the two relations to `CatalogEdge` can break tests that count unions; grep `packages/core/tests` and `services/api/tests/catalog*` for the union sizes.
- Shared-file rules for the connector wave (PRP-117 Gotchas) apply: no edit to `pyproject.toml`, `uv.lock`, Dockerfiles, licences, conformance tests, coverage files, contracts or another connector's directory.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/entra-identity/**
  - docs/connectors/verification/entra-identity.md
  - packages/core/neurosphere_core/catalog/identity/**
  - packages/core/neurosphere_core/catalog/protocol.py
  - packages/core/tests/catalog_identity/**
  - services/workers/neurosphere_workers/projections/identity/**
  - services/workers/tests/projections_identity/**
  - services/api/neurosphere_api/catalog/identity/**
  - services/api/tests/catalog_identity_api/**
  - tests/security/authz/test_catalog_identity*.py
  - tests/security/identity_collection/**
  - frontend/src/features/catalog/identity/**
  - frontend/src/features/catalog/EntityForm.tsx
  - frontend/src/features/catalog/entityFormModel.ts
  - frontend/src/features/catalog/EntityTypeDetails.tsx
  - frontend/tests/mock-api/features/catalog-identity.ts
  - docs/runbooks/agent-identity.md
  - changelog.d/PRP-118-agent-identity-and-entra-entitlements.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - services/workers/neurosphere_workers/connector_runner/**
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/repo/**
  - packages/core/neurosphere_core/catalog/graph/access.py
  - packages/core/neurosphere_core/catalog/labels/**
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/catalog/service.py
  - services/api/neurosphere_api/runtime/builders/**
  - connectors/reference/purview/**
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - tests/unit/connector_conformance/**
  - docs/connectors/coverage.md
  - docs/connectors/estate-coverage.md
```
`protocol.py` is edited only to append the three union members. No file under `connector_runner/` is edited: the binding is `projections/identity/binding.py`, reached through PRP-117's `neurosphere.connector_bindings` entry (Clarification 7). PRP-120 (same wave) mounts its grounding-source rows in `EntityTypeDetails.tsx` only after this PRP merges (its serial-after item).

## Implementation blueprint

Parallelization: item 1 first (it decides what is built). Items 2 and 3 [P] after it. Item 4 after 2 and 3. Items 5 and 6 after 4. Item 7 after 5 and 6. Item 8 last.

### Item 1 - Verify first: directory, resource-management and run-as signals
- Deliverable: `docs/connectors/verification/entra-identity.md` from the template, one row per signal in acceptance criterion 1, a "build / do not build" table, the least-privilege permission set as written in the documentation, the admin-consent step, Government availability, and the fallback per absent signal; `role_access.yaml` source rows for the built-in roles the mapping covers.
- Owned files: the verification file, `packages/core/neurosphere_core/catalog/identity/data/role_access.yaml`.
- Must NOT touch: code.
- Depends on: PRP-110 and PRP-117 merged.
- Acceptance criteria: criterion 1; every later item builds only "build" rows; U-7, U-8, U-9 resolved or recorded OPEN.
- Tests: `python scripts/connector_estate_check.py` (descriptor still `not_built` until item 3).
- Pattern references: PRP-122 item 1.

### Item 2 - Core identity model and catalog unions  [P]
- Deliverable: `catalog/identity/` (`ids.py`, `observations.py`, `role_map.py`, `view.py`, `ports.py`); union appends in `protocol.py`; in-memory repository round trip of `WorkloadIdentity`, `RunsAs`, `EntitledTo`.
- Owned files: `packages/core/neurosphere_core/catalog/identity/**`, `protocol.py` (unions), `packages/core/tests/catalog_identity/**`.
- Must NOT touch: `catalog/repo/**`, contracts.
- Depends on: item 1 (role file).
- Acceptance criteria: criteria 2 (id part) and 5; unmapped role is `admin`; ids never derived from display names.
- Tests: `packages/core/tests/catalog_identity/test_ids.py`, `test_role_map.py`, `test_repository_roundtrip.py`, `test_view.py`; re-run `packages/core/tests/catalog`.
- Pattern references: `catalog/repo/documents.py:59`, `catalog/rules.py`.

### Item 3 - Connector body  [P]
- Deliverable: `neurosphere_connector_entra_identity/` readers for the verified signals over `ctx.http`, bounded paging (per-identity and per-run caps), throttling to `RunResult.reason`, mapping to `IdentityObservation`/`EntitlementObservation`, `supported_clouds` and `allowed_hosts` from item 1, descriptor `built`; recorded synthetic fixtures under `tests/fixtures/`; `conformance_factory()` with fakes.
- Owned files: `connectors/reference/entra-identity/**`.
- Must NOT touch: other connectors, runner, SDK.
- Depends on: item 1.
- Acceptance criteria: criteria 3 (connector half), 7 and 8; requests only for identities from the target source; no tenant-wide user or group enumeration (asserted on the recording transport).
- Tests: `connectors/reference/entra-identity/tests/test_readers.py`, `test_paging_and_throttle.py`, `test_no_secret_in_output.py`, `test_government_hosts.py`; `tests/unit/connector_conformance`.
- Pattern references: `connectors/reference/azure-billing/`, `deploy/scan/graph.py:18-50`.

### Item 4 - Identity projection and runner binding
- Deliverable: `projections/identity/` implementing `IdentityTargetSource` (run-as identities in the worker's derived scope, bounded) and `IdentityObservationSink` (upsert `entitled_to` edges, set `valid_to` on entitlements absent from a complete run, write collection attributes, create discovered identities create-only, count `unmatched_targets`); discovered run-as edges per criterion 6; `binding.py` exposing `BINDING` for kind `entra_identity` (PRP-117's hook).
- Owned files: `services/workers/neurosphere_workers/projections/identity/**`, `services/workers/tests/projections_identity/**`.
- Must NOT touch: `projections/catalog/**`, `foundry_discovery/**`.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 3, 4 and 6; idempotent on replay; truncated run changes nothing.
- Tests: `services/workers/tests/projections_identity/test_projection.py`, `test_stale_entitlements.py`, `test_discovered_run_as.py`, `test_runner_binding.py` (uses PRP-117's test binding fixture).
- Pattern references: `foundry_discovery/poller.py:269` (`_ensure`), `projections/catalog/mapping.py:172-200`.

### Item 5 - API routes
- Deliverable: `catalog/identity/{__init__,router,models,deps}.py` with the two routes, `audited_read`, server-derived scope, deterministic identity id, `register(registry)` with alias; route inventory lines.
- Owned files: `services/api/neurosphere_api/catalog/identity/**`, `services/api/tests/catalog_identity_api/**`; Tier-2 lines.
- Must NOT touch: `catalog/router.py`, `catalog/service.py`, `runtime/builders/**`.
- Depends on: item 4.
- Acceptance criteria: criterion 9 (API part); body-supplied customer, cloud or domain ignored.
- Tests: `services/api/tests/catalog_identity_api/test_run_as.py`, `test_subject_view.py`, `test_read_audit.py`; `services/api/tests/authz`, `services/api/tests/runtime_routes`.
- Pattern references: PRP-73 `catalog/access/router.py`; `catalog/router.py:263-298`.

### Item 6 - Registration field and identity panel
- Deliverable: `RunAsField` in `EntityForm.tsx` for `agent`, `tool` and `mcp_server` (optional; kind, client id or resource id), submitted to the run-as route after the entity save; `IdentityPanel` mounted from `EntityTypeDetails.tsx` for agent, agent version, tool, service and MCP server, with the collection-state banner; mock handlers.
- Owned files: `frontend/src/features/catalog/identity/**`, `EntityForm.tsx`, `entityFormModel.ts`, `EntityTypeDetails.tsx`, `frontend/tests/mock-api/features/catalog-identity.ts`.
- Must NOT touch: `CatalogEntityPage.tsx`, `server.ts`.
- Depends on: item 5 (shapes).
- Acceptance criteria: criterion 10; "not collected" and "partial" are plain words, never an empty table.
- Tests: `frontend/src/features/catalog/identity/identity.test.tsx`, existing `catalog-write.test.tsx`, `entity-type-details.test.tsx`.
- Pattern references: `EntityTypeDetails.tsx:31-125` (`GrantRows`, `McpRows`).

### Item 7 - Security suite
- Deliverable: authorization negatives for both routes; leak test over logs, status documents, audit records and stored edges (no token, secret, assertion, response body); Government boundary test; consent-missing degradation test.
- Owned files: `tests/security/authz/test_catalog_identity.py`, `tests/security/identity_collection/**`.
- Depends on: items 4 and 5.
- Acceptance criteria: criteria 7, 8, 9.
- Tests: `tests/security/authz`, `tests/security/identity_collection`.
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends, runbook `docs/runbooks/agent-identity.md` (least-privilege permissions from item 1, the operator admin-consent step, credential reference setup, what "not collected" and "partial" mean, data-plane limits), Tier-3 regeneration after rebase (`openapi.json`, `docs/reference/**`, `estate-coverage.md`, `prp_status.py --write`, `PRPs/INDEX.md`, `prp_execution_plan.py --write`), changelog fragment, completion note with the item 1 outcome per signal.
- Owned files: the runbook, the fragment, this PRP file, Tier-2 lines, Tier-3 outputs.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/entra-identity/tests packages/core/tests/catalog_identity packages/core/tests/catalog services/workers/tests/projections_identity services/workers/tests/projections services/workers/tests/connector_runner_role services/api/tests/catalog_identity_api services/api/tests/catalog services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/security/identity_collection tests/unit/connector_conformance tests/unit/estate_check services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/connector_estate_check.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive: new entities and edges in the existing catalog container, no change to existing documents. Rollback: disable the `entra_identity` config (the runner stops collecting; edges keep their last `last_observed` and age out of "current" views), or revert the PR. Declared identities and edges stay as ordinary catalog data that stewards can deprecate or reject. Revoking NeuroSphere's admin consent is the operator's off switch for the directory reads.

## Live and open gates
OPEN until run with `NS_LIVE_APPROVED=1` and operator approval: a Graph and ARM read in an approved Commercial tenant with admin consent granted by the operator, and the same in Government if item 1 verified it. Handed to PRP-136 (`docs/evidence/governance/**`). No paid call is involved, but the consent and the tenant are shared enterprise resources: never grant consent or create role assignments from a session.

## NOT building
Complete entitlements: data-plane permissions inside each data service (SQL grants, storage ACLs, search index keys, SharePoint item permissions) are mostly out of reach; "who could" is always shown with its collection coverage (design section 8 item 8). Entra Agent ID unless verified (item 9). Tenant-wide directory inventory, user or group enumeration, sign-in logs and consent grants (PRP-126). Over-privilege findings and the policy evaluator (PRP-119). Any write to Entra or Azure (consent, role assignment, revocation): remediation is a customer action in their identity provider. No bridging of Government data to Commercial. No compliance or authorization claim.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 5, 6 and 7 are ASSUMPTIONS for plan approval; row 7 depends on PRP-117's merged runner)

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
- Product check (can a security lead see what an agent may access, and how complete that view is, without reading code):
