---
name: PRP-37-contracts-revision-admin-cost-and-permissions
status: backlog
priority: P0
order: 20
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-01, NS-08, NS-09
depends_on: []
wave: W12
branch: prp-37-contracts-admin
allow_parallel: true
issues: [190, 178, 114, 195, 148]
---

# PRP-37: Contracts revision for the control plane (admin schemas, cost tags, permissions, stores)

## Goal
Ship the wire and storage layer that every operator control-plane PRP codes against, and nothing above it: a new `admin/v1` schema family (identity changes, revocation, producers, connector configs with credential references, domains, budgets, price-sheet uploads, review policy, system settings, first-run checklist), a write side for the policy store (`PolicyAdminRepository`), a versioned, ETag-guarded `admin_config` Cosmos container with an in-memory twin, two new permissions plus a core helper for deployment-scoped (customer-wide) authority, and the contract revisions that issues and shipped-PRP leftovers have queued: `CostRecord.tags` (#190, #178), the structured-query entity enum (#148 item 1), tighter `ConnectorManifest` caps and an additive-only baseline test (PRP-01 leftovers), 404/405/413/500 taxonomy codes (PRP-05 leftover) and a provenance guarantee for presented edges (#195). It is for the authors of PRP-39, 41, 42, 44, 45, 46, 48, 53 and 57, who must build against these names instead of inventing shapes. It runs first in W12 because contracts are Tier 1 and a wrong field here is refactored everywhere; that is why it is Opus with a required review.

Out of scope: every route and UI (PRP-39 identity API, PRP-40 audit search and SIEM, PRP-41 producers, PRP-42 connectors, PRP-44 domains/budgets/prices/review policy, PRP-45 system settings, PRP-53 and PRP-57 console pages); ingest reading `nscostcenter` and the ledger using tags (PRP-46); applying the deployment-scope helper to MCP admin, deploy scan and the kill switch (PRP-48, #114 behaviour half); populating edge provenance in `PresentedEdge` (PRP-43); API handlers emitting the new error codes (follow-up issue, see Item 3).

## Why
- No admin contract or store exists: `PolicyRepository` is read-only (`packages/core/neurosphere_core/auth/scope/policy.py:108-116`, "Writes belong to the (audited) admin path"), and the only writer is `scripts/sandbox/sbx_grant_operator.py:101-167` (lane-d step 1, unit A).
- `Permission.POLICY_MANAGE` and `REVOCATION_MANAGE` are declared (`permissions.py:74-75`) but have zero uses in `services/` (lane-d step 1); there is no deployment-scoped permission (#114, lane-e).
- `CostRecord` has no `tags` (schema properties end at `recorded_at`; `cost/v1/cost-record.schema.json`), so `nscostcenter` is dropped after ingest (#190, #178 duplicate, lane-f).
- `structured-query.schema.json:139-152` enumerates only the original 12 catalog entities; `grant`, `mcp_server` and `grants_access_to` cannot be queried (#148 item 1).
- `problem-details.schema.json:31` allows only 401/403/409/422/429/502/503, so 404/405/500 return a body without `code` (`PRPs/shipped/PRP-05-*.md:296`); `ConnectorManifest` caps on `scopes` and `documentation_url` are loose enough to carry a secret (`PRPs/shipped/PRP-01-*.md:303`).
- `CONTAINERS` (`packages/core/neurosphere_core/stores/containers.py:96-183`) has no container for operator configuration; every later control-plane PRP needs one.

## Acceptance criteria
- [ ] Every schema named in "Interfaces provided" exists under `packages/contracts/schemas/admin/v1/`, forbids additional properties, has valid and invalid examples, and generates Python and TypeScript bindings; `python packages/contracts/scripts/generate.py --check` passes.
- [ ] No admin schema has a field that can hold a credential value: `CredentialReference` accepts only a Key Vault secret URI (Commercial or Government suffix) or a managed-identity client id; a contract test walks every `admin/v1` schema and fails on any property named like `secret`, `key`, `password` or `token` except `secret_sha256` and the response-only `ProducerSecretIssued.secret` (A7).
- [ ] Given a `CostRecord` with `tags: {"cost_center": "cc-1001"}`, it validates; more than 16 entries, a key outside `^[a-z][a-z0-9_.-]{0,62}$`, or a value longer than 128 characters is rejected; records without `tags` still validate (#190 item 1).
- [ ] `structured-query` accepts `grant`, `mcp_server` and the `grants_access_to` relation, and `tests/contracts/validators.py` `FIELD_APPLICABILITY` has rows for them (#148 item 1).
- [ ] `error-codes.json` gains `not_found` (404), `method_not_allowed` (405), `payload_too_large` (413) and `internal_error` (500) rows; `ProblemDetails` accepts them; `neurosphere_core.errors` has exactly one class per code and `packages/core/tests/test_errors.py` passes (PRP-05 leftover).
- [ ] `ConnectorManifest` `scopes` items, `credential_ref.name` and `documentation_url` path are capped (Item 3 values); every manifest under `connectors/**` still validates (PRP-01 leftover).
- [ ] An additive-only baseline test fails when a `v1` schema removes a property, removes an enum value, adds a required property or narrows a type, compared with a committed snapshot; the one deliberate tightening (manifest caps) is listed in the test's allowlist with a reason and recorded in ADR-0004.
- [ ] A contract test asserts every catalog relation schema requires `provenance` with `common.schema.json#/$defs/provenance` (#195 provenance bullet, contract half).
- [ ] `Permission.LIFECYCLE_MANAGE` (`lifecycle.manage`, Admin) and `Permission.AUDIT_EXPORT` (`audit.export`, Security Auditor) exist; role sets are pinned by `test_roles.py` and `test_privileged_roles.py`; no role gains anything else.
- [ ] `customer_control_domain_id(cloud, customer_id)` and `permits_customer_wide(scope, permission, *, now)` live in core and return True only for an unexpired assignment on `<cloud>:<customer>:neurosphere:domain:customer-control` (#114 schema half); `actions/customer_control.py` behaviour is unchanged.
- [ ] `PolicyAdminRepository` (in-memory and Cosmos) writes `PrincipalPolicy` with an ETag precondition and bumps `PolicyHead.policy_version` in the same partition; a stale ETag raises `stale_version`; the read protocol is unchanged.
- [ ] `admin_config` is declared in `CONTAINERS`, exported to `infra/compose/cosmos-containers.json`, and `AdminConfigRepository` (in-memory and Cosmos) supports create, get, list by kind, replace with `If-Match` and retire, with a monotonic `version`; tested on the in-memory twin and, marked `integration`, on the emulator.
- [ ] PRP exit: the touched suites, `generate.py --check`, ruff, pyright and `validate_planning.py` pass; PR open with CI green including the `contracts` job; Tier-3 files regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where admin wire shapes live | contracts family; API-local models | `packages/contracts/schemas/admin/v1/` so Python, TS and the mock API share them (lane-d unit A) |
| 2 | Container name | `admin-config` (lane-d text); `admin_config` | `admin_config`: every container added since PRP-17 is snake_case (`action_intents`, `price_snapshots`, `catalog_review_queue`); partition `/customer_id` |
| 3 | Policy writes: new container or existing `policy` | new; existing | Existing `policy` container and documents (`PrincipalPolicy`, `PolicyHead`), so derivation reads what admin writes with no migration |
| 4 | Deployment-scoped admin (#114) | new role; new permission; reserved control domain | Reserved control domain already used by the kill switch (`actions/customer_control.py`); roles stay the closed set of five (PRP-06 C6/C7). Core gets the helper; PRP-48 applies it |
| 5 | Credentials in admin records | values; references | References only: Key Vault secret URI or managed identity (A7) |
| 6 | CostRecord tag shape | `cost_center` field; `tags` map | `tags` map, at most 16 entries, values 128 chars, reserved key `cost_center` with the Grant `cost_center` pattern (#190 proposal) |
| 7 | ConnectorManifest caps are a tightening inside `v1` | allow with evidence; new `v2` | ASSUMPTION: allowed because no manifest in the repo exceeds them (test proves it); recorded as the single ADR-0004 exception |
| 8 | New permission for audit export | reuse `audit.read`; `data.export`; new `audit.export` | ASSUMPTION: new `audit.export` held by Security Auditor only (lane-d unit J "data.export-style permission"; Admin never reads audit) |
| 9 | Lifecycle permission (PRP-23 needs one in the same wave) | each PRP adds its own; PRP-37 adds | PRP-37 adds `lifecycle.manage` (Admin). If PRP-23 merges first with the same member, keep one line at rebase (Tier-2 rule) |
| 10 | Typed setting bodies vs one generic body | per-kind schema; free map | Per-kind `$defs` in `system-setting.schema.json`; `AdminConfigDocument.body` is validated by kind in core (`ADMIN_KIND_MODELS`) |

## Context manifest

### Files to read first
- `packages/contracts/scripts/generate.py` - `discover_schemas` (`<area>/v<major>/*.schema.json`), staging rules, `--check`.
- `docs/adr/0004-contract-versioning.md` - `v1` additive-only rule this PRP enforces with a test.
- `packages/contracts/schemas/catalog/v1/grant.schema.json` - `cost_center` pattern; `catalog/v1/common.schema.json` `$defs` (`provenance` at :166, `etag`, `timestamp`).
- `packages/contracts/schemas/connectors/v1/connector-manifest.schema.json` - `$defs/credential_ref` (`vault_ref` pattern to reuse in `CredentialReference`).
- `packages/core/neurosphere_core/auth/scope/permissions.py` - `Permission`, role sets, `PRIVILEGED_ROLES`, `permits`.
- `packages/core/neurosphere_core/auth/scope/policy.py` - `PrincipalPolicy`, `PolicyHead`, `PolicyRepository`; `cosmos_repository.py` and `memory.py` twins.
- `services/api/neurosphere_api/actions/customer_control.py` - control domain convention (read only).
- `packages/core/neurosphere_core/stores/containers.py` and `stores/__main__.py` - registry and export writer.
- `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140` - ETag create/replace pattern with mapped errors.
- `packages/core/neurosphere_core/hitl/policy.py:37-110` and `pricing/models.py:64-160` - shapes `ReviewPolicyDocument` and `PriceSheetUpload` must map onto.
- `services/api/neurosphere_api/ingest/auth.py:34-47` - `ProducerRegistration` fields `ProducerRecord` must carry.
- `tests/contracts/validators.py:661` (`FIELD_APPLICABILITY`), `tests/contracts/test_error_taxonomy.py`, `packages/core/tests/test_errors.py`.

### Interfaces consumed
- PRP-01 contract conventions (`schema_version` `1.x.y`, `x-ns-name`, `additionalProperties: false`), PRP-05 `neurosphere_core.errors`, PRP-06 policy and revocation models, PRP-29 container registry. All shipped.

### Interfaces provided
Schemas (file under `packages/contracts/schemas/admin/v1/`; Python `neurosphere_contracts.admin.v1.<snake_file>`; TS `packages/contracts/ts/src/admin/v1/<file>.ts`):
- `common.schema.json` `$defs`: `admin_kind` (`producer`, `connector_config`, `domain`, `budget`, `price_sheet`, `review_policy`, `system_setting`), `config_version` (integer >= 1), `reason_code`, `principal_id` (canonical pseudonymous id).
- `credential-reference.schema.json` -> `CredentialReference` {`kind`: `key_vault_secret`|`managed_identity`, `secret_uri`, `managed_identity_client_id`}.
- `admin-config-document.schema.json` -> `AdminConfigDocument` {`id`, `customer_id`, `kind`, `version`, `etag`, `status` (`active`|`retired`), `updated_at`, `updated_by`, `body`}.
- Identity (PRP-39): `role-assignment-change.schema.json` -> `RoleAssignmentChange` {`op` `assign`|`remove`, `principal_id`, `assignment_id`, `role`, `domain_ids`, `expires_at`, `reason`}; `domain-membership-change.schema.json` -> `DomainMembershipChange`; `resource-grant-change.schema.json` -> `ResourceGrantChange` {`grant_id`, `resource_id`, `permissions`, `expires_at` required, `reason`}; `principal-access-summary.schema.json` -> `PrincipalAccessSummary` {principal, memberships, assignments with expiry, grants, `revocation`}; `revocation-request.schema.json` -> `RevocationRequest` {`reason`, `mode` `issued_before`|`until_lifted`}; `revocation-status.schema.json` -> `RevocationStatus`.
- Sources (PRP-41, 42): `producer-record.schema.json` -> `ProducerRecord` {`producer_id`, `customer_id`, `cloud`, `sources`, `secret_sha256`, `status` `active`|`disabled`, `rotated_at`}; `producer-secret-issued.schema.json` -> `ProducerSecretIssued` (response-only, shown once); `connector-config.schema.json` -> `ConnectorConfig` {`connector_kind` `gateway_poll`|`foundry_discovery`|`billing_export`|`otel`, `domain_ids`, `settings` (bounded scalar map), `credential` `CredentialReference`, `enabled`}.
- Platform (PRP-44, 46): `domain-definition.schema.json` -> `DomainDefinition` {`domain_id`, `display_name`, `classification`, `residency_region`, `status`, `is_control_domain`}; `budget.schema.json` -> `Budget` {`budget_id`, `domain_id`, `period`, `amount` (decimal string), `currency`, `thresholds_percent`, `tags_filter`}; `price-sheet-upload.schema.json` -> `PriceSheetUpload` (maps to `PriceSnapshot` minus `content_hash`); `review-policy-document.schema.json` -> `ReviewPolicyDocument` (kind defaults and action overrides, durations in seconds, maps to `ReviewPolicy`).
- Runtime (PRP-45): `system-setting.schema.json` -> `SystemSetting` {`setting_key` `copilot`|`judge`|`search`|`scan`|`mcp_server`|`write_target`, per-key `$defs` holding endpoints, resource ids and `CredentialReference` only}; `first-run-checklist-item.schema.json` -> `FirstRunChecklistItem` {`item_id`, `component`, `status` `complete`|`missing`|`disabled`|`not_applicable`|`error`, `reason`, `doc_path`, `required`}.
- Revised existing: `CostRecord.tags`; `StructuredQuery` entity and relation enums; `ProblemDetails` codes `not_found`, `method_not_allowed`, `payload_too_large`, `internal_error`; tighter `ConnectorManifest`.

Core (Python):
- `neurosphere_core.auth.scope.permissions`: `Permission.LIFECYCLE_MANAGE`, `Permission.AUDIT_EXPORT`, `CUSTOMER_CONTROL_SOURCE`, `CUSTOMER_CONTROL_DOMAIN_NAME`, `customer_control_domain_id()`, `permits_customer_wide()`.
- `neurosphere_core.auth.scope.policy_admin`: `PolicyAdminRepository` protocol (`get_with_etag`, `list_principals`, `put_principal_policy(policy, *, if_match)`), `InMemoryPolicyAdminRepository`, `CosmosPolicyAdminRepository`, pure `apply_role_change`, `apply_membership_change`, `apply_grant_change`, `next_policy_version`.
- `neurosphere_core.admin`: `ADMIN_CONFIG_CONTAINER = "admin_config"`, `AdminConfigRepository` protocol, `InMemoryAdminConfigRepository`, `CosmosAdminConfigRepository`, `ADMIN_KIND_MODELS` (kind -> generated model), `admin_config_chain_id(customer_id)` naming `<customer>.admin-config` for audited writes.
- Errors: `NotFoundError`, `MethodNotAllowedError`, `PayloadTooLargeError`, `InternalError` in `neurosphere_core.errors`.

### Patterns to match
- Schema file and `$id` style: `packages/contracts/schemas/cost/v1/cost-record.schema.json:1-10`.
- Container spec entry: `stores/containers.py:157-182`; ETag replace: `mcp/cosmos_store.py:110-133`; policy write and head bump: `scripts/sandbox/sbx_grant_operator.py:113-167`.
- Contract tests per family: `tests/contracts/test_grant_and_mcp_server.py`, `test_connector_manifest.py`.

### Gotchas
- `generate.py` regenerates `packages/contracts/ts/src/index.ts` and every family; items that change schemas are serial, never parallel.
- Pydantic ignores `if/then/else` (PRP-01 deviation): cross-field rules need JSON Schema tests plus a core validator.
- `StructuredQuery` is a `response_model` in `services/api/openapi.json`; the enum change regenerates it (Tier 3, at merge, not before).
- Adding error codes breaks `test_every_contract_code_has_exactly_one_class` until core error classes exist: same item.
- `PolicyHead` and `PrincipalPolicy` share partition `/customer_id`; write both in one transactional batch on Cosmos so a crash cannot leave a stale cache version.
- Never log `secret_uri`, `secret_sha256` or a tag value (CodeQL secret-name rule, #190 item 3).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - packages/core/neurosphere_core/admin/**
  - packages/core/neurosphere_core/auth/scope/policy_admin.py
  - packages/core/neurosphere_core/errors/**
  - packages/core/tests/admin/**
  - packages/core/tests/test_errors.py
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
tier1:
  - packages/contracts/schemas/**
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
  - infra/bicep/modules/cosmos.bicep
  - packages/core/neurosphere_core/auth/scope/permissions.py
tier2_appends:
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
must_not_touch:
  - services/api/**
  - services/workers/**
  - frontend/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/auth/revocation/**
```

## Implementation blueprint

Parallelization: items 1, 2, 3 are serial (shared generated output). Item 4 [P] with 1-3. Item 5 after 1. Item 6 after 2. Item 7 last.

### Item 1 - Admin schema family, identity and common
- Deliverable: `admin/v1/common`, `credential-reference`, `admin-config-document`, `role-assignment-change`, `domain-membership-change`, `resource-grant-change`, `principal-access-summary`, `revocation-request`, `revocation-status` schemas with examples; regenerated bindings; credential-field walker test.
- Owned files: `packages/contracts/schemas/admin/v1/**`, generated `packages/contracts/python/neurosphere_contracts/admin/**`, `packages/contracts/ts/src/admin/**`, `packages/contracts/ts/src/index.ts`, `tests/contracts/test_admin_identity_schemas.py` (new), `tests/contracts/test_admin_no_credential_values.py` (new).
- Must NOT touch: other schema families; core.
- Depends on: none.
- Acceptance criteria: privileged roles (`admin`, `security_auditor`) without `expires_at` rejected, matching `PolicyRoleAssignment`; `ResourceGrantChange.expires_at` required; principal ids match the canonical pseudonymous pattern, never a UPN or email.
- Tests: the two new files plus `tests/contracts/test_schemas.py`, `test_roundtrip.py`, `test_no_remote_refs.py`.
- Pattern references: `catalog/v1/grant.schema.json`, `policy.py:67-105`.

### Item 2 - Admin schema family, sources, platform and runtime
- Deliverable: `producer-record`, `producer-secret-issued`, `connector-config`, `domain-definition`, `budget`, `price-sheet-upload`, `review-policy-document`, `system-setting`, `first-run-checklist-item` schemas with examples and bindings.
- Owned files: as item 1 plus `tests/contracts/test_admin_platform_schemas.py` (new).
- Must NOT touch: core pricing, HITL or ingest modules (mapping tests read them only).
- Depends on: item 1.
- Acceptance criteria: a test converts a `PriceSheetUpload` example to `PriceSnapshot` and a `ReviewPolicyDocument` example to `ReviewPolicyRegistry` inputs without loss; `ProducerRecord` round-trips to ingest `ProducerRegistration`; `ConnectorConfig.settings` refuses nested objects and secret-like keys; Government `CredentialReference` uses `vault.usgovcloudapi.net`.
- Tests: `tests/contracts/test_admin_platform_schemas.py`.
- Pattern references: `pricing/models.py:121-160`, `hitl/policy.py:37-60`, `ingest/auth.py:34-47`.

### Item 3 - Revisions to existing contracts
- Deliverable: `CostRecord.tags`; structured-query enums and `FIELD_APPLICABILITY`; four error codes plus core error classes; manifest caps (`scopes` items max 128, `credential_ref.name` unchanged, `documentation_url` max 512 with a path segment cap); provenance assertion; additive-only baseline snapshot and test; ADR-0004 note. File a follow-up issue for API handlers to emit the new codes (owner PRP-51 or a new item) and record its number.
- Owned files: `packages/contracts/schemas/{cost,query,errors,connectors}/v1/**`, generated output, `packages/core/neurosphere_core/errors/**`, `packages/core/tests/test_errors.py`, `tests/contracts/validators.py`, `tests/contracts/test_additive_only.py` (new), `tests/contracts/fixtures/v1-baseline/**` (new), `tests/contracts/test_cost_tags.py` (new), `docs/adr/0004-contract-versioning.md`.
- Must NOT touch: ingest, ledger, catalog code; `services/api/neurosphere_api/app.py`.
- Depends on: item 2.
- Acceptance criteria: as listed in the PRP criteria for tags, enum, error codes, caps, provenance and the baseline test; `connectors/**` manifests validated in a test.
- Tests: `tests/contracts`, `packages/core/tests/test_errors.py`, `tests/unit/connector_conformance`.
- Pattern references: `tests/contracts/test_error_taxonomy.py`, `test_connector_manifest.py`.

### Item 4 - Permissions and deployment scope  [P]
- Deliverable: `LIFECYCLE_MANAGE` (Admin), `AUDIT_EXPORT` (Security Auditor), the customer-control constants and `customer_control_domain_id` / `permits_customer_wide`; docstring table updated; role pin tests updated (#148 item 5 `SHARED_ADMIN_STEWARD` reviewed).
- Owned files: `packages/core/neurosphere_core/auth/scope/permissions.py`, `auth/scope/__init__.py` exports, `packages/core/tests/auth/scope/test_roles.py`, `tests/security/authz/test_privileged_roles.py`, `packages/core/tests/admin/test_customer_wide.py` (new).
- Must NOT touch: `services/api/**` (customer_control.py keeps its constants until PRP-48 moves it).
- Depends on: none.
- Acceptance criteria: expired, cross-cloud and cross-customer assignments on the control domain return False; ordinary domains never satisfy `permits_customer_wide`; no wildcard introduced.
- Tests: the three files above.
- Pattern references: `permissions.py:146-190`, `customer_control.py`.

### Item 5 - Policy write repository
- Deliverable: `policy_admin.py` with protocol, twins and pure change functions; transactional head bump; stale ETag -> `StaleVersionError`; store failure -> `DependencyTransientError`.
- Owned files: `packages/core/neurosphere_core/auth/scope/policy_admin.py` (new), `packages/core/tests/admin/test_policy_admin.py` (new), `packages/core/tests/admin/test_policy_admin_cosmos.py` (new, `integration`).
- Must NOT touch: `policy.py`, `cosmos_repository.py`, `derivation.py` (read path unchanged).
- Depends on: item 1.
- Acceptance criteria: removing the last assignment leaves a valid document; applying a change for another customer raises; derivation over the twin sees the change after the head bump.
- Tests: the two new files.
- Pattern references: `sbx_grant_operator.py:113-167`, `cosmos_repository.py:38-90`.

### Item 6 - Admin config store
- Deliverable: `neurosphere_core/admin/` package (`models.py`, `store.py`, `cosmos_store.py`, `chains.py`), `admin_config` container spec, regenerated `infra/compose/cosmos-containers.json`.
- Owned files: `packages/core/neurosphere_core/admin/**` (new), `stores/containers.py`, `infra/compose/cosmos-containers.json`, `packages/core/tests/admin/test_config_store.py` (new), `test_config_store_cosmos.py` (new, `integration`), `packages/core/tests/stores_registry/**` only if a pin needs the new entry.
- Must NOT touch: the two Bicep modules unless the export test proves they need a change (`cosmos-data.bicep` loads the JSON).
- Depends on: item 2.
- Acceptance criteria: version increments by one per replace; `If-Match` mismatch raises `stale_version`; a body that fails its kind model is `invalid_schema`; retire keeps the document readable; the export drift test passes.
- Tests: the new files plus `packages/core/tests/stores_registry`.
- Pattern references: `stores/containers.py:157-182`, `gateway/cosmos_store.py:94-200`.

### Item 7 - Integration and close-out
- Deliverable: rebase on `main`; regenerate contracts and Tier-3 files (`services/api/openapi.json`, `docs/reference/**`, PRP status table, `PRPs/INDEX.md`); CHANGELOG entry; completion note listing every provided name for PRP-39..57 authors; follow-up issue numbers.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-6.
- Acceptance criteria: validation gates below pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run python -m neurosphere_core.stores --check
uv run pytest -q tests/contracts packages/core/tests/admin packages/core/tests/test_errors.py packages/core/tests/auth/scope packages/core/tests/stores_registry tests/security/authz/test_privileged_roles.py tests/unit/connector_conformance services/api/tests/test_openapi_drift.py
pnpm --filter ./packages/contracts/ts test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator suites (local, not CI): `docker compose up -d --wait` then `uv run pytest -q -m integration packages/core/tests/admin`.

## Migration and rollback
All schema changes are additive inside `v1` except the documented manifest cap. Stored `CostRecord`s without `tags` stay valid. The `admin_config` container is new: local emulators create it; hosted environments get it from `cosmos-data.bicep` on the next deploy (PRP-58 / operator). Nothing reads the new store until PRP-39+ ship, so revert is a plain `git revert` plus leaving an empty container.

## Live and open gates
None. Cosmos behaviour is proven on the emulator only; hosted container creation happens at the next operator deploy (PRP-58, PRP-64).

## NOT building
Routes, UI, mock handlers, worker pickup, ingest tag mapping, ledger tag queries, API error handler changes, catalog provenance population, budget alert delivery, any secret value storage.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 7 and 8 are ASSUMPTIONS for plan approval)

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

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
