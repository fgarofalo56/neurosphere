---
name: PRP-37-contracts-revision-admin-cost-and-permissions
status: shipped
shipped: 2026-11-15
pr: 273
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
wave: W11
branch: prp-37-contracts-admin
allow_parallel: true
issues: [226, 190, 114, 195, 148]
---

# PRP-37: Contracts revision for the control plane (admin schemas, cost tags, query enum, error taxonomy)

## Goal
Ship the wire layer that every operator control-plane PRP codes against, and nothing above it: a new `admin/v1` schema family (identity changes, revocation, producers, connector configs with credential references, domains, budgets, price-sheet uploads, review policy, system settings, first-run checklist) and the contract revisions that issues and shipped-PRP leftovers have queued: `CostRecord.tags` (#190, #178), the structured-query entity enum (#148 item 1), tighter `ConnectorManifest` caps and an additive-only baseline test (PRP-01 leftovers), 404/405/413/500 taxonomy codes with their core error classes (PRP-05 leftover) and a provenance guarantee for presented edges (#195). It is for the authors of PRP-39, 41, 42, 44, 45, 46, 53 and 57, who must build against these names instead of inventing shapes, and for PRP-65, which builds the permissions and stores on top of these schemas. It runs in W11 (beside PRP-36, docs only, and PRP-68, changelog and CI planning job) because contracts are Tier 1 and a wrong field here is refactored everywhere; it is the only owner of `packages/contracts/**`, which is why it is Opus with a required review.

Out of scope: the permission additions (`lifecycle.manage`, `audit.export`), the deployment-scope helper, the policy write repository and the `admin_config` container and store (PRP-65, W12); every route and UI (PRP-39 identity API, PRP-40 audit search and SIEM, PRP-41 producers, PRP-42 connectors, PRP-44 domains/budgets/prices/review policy, PRP-45 system settings, PRP-53 and PRP-57 console pages); ingest reading `nscostcenter` and the ledger using tags (PRP-46); populating edge provenance in `PresentedEdge` (PRP-43); API handlers emitting the new error codes (follow-up issue, see Item 3).

## Why
- No admin contract exists: there is no `packages/contracts/schemas/admin/` family, so PRP-39+ would each invent request and document shapes (lane-d step 1, unit A).
- `CostRecord` has no `tags` (schema properties end at `recorded_at`; `cost/v1/cost-record.schema.json`), so `nscostcenter` is dropped after ingest (#190, #178 duplicate, lane-f).
- `structured-query.schema.json:139-152` enumerates only the original 12 catalog entities; `grant`, `mcp_server` and `grants_access_to` cannot be queried (#148 item 1).
- `problem-details.schema.json:31` allows only 401/403/409/422/429/502/503, so 404/405/500 return a body without `code` (`PRPs/shipped/PRP-05-*.md:296`); `ConnectorManifest` caps on `scopes` and `documentation_url` are loose enough to carry a secret (`PRPs/shipped/PRP-01-*.md:303`).

## Acceptance criteria
- [ ] Every schema named in "Interfaces provided" exists under `packages/contracts/schemas/admin/v1/`, forbids additional properties, has valid and invalid examples, and generates Python and TypeScript bindings; `python packages/contracts/scripts/generate.py --check` passes.
- [ ] No admin schema has a field that can hold a credential value: `CredentialReference` accepts only a Key Vault secret URI (Commercial or Government suffix) or a managed-identity client id; a contract test walks every `admin/v1` schema and fails on any property named like `secret`, `key`, `password` or `token` except `secret_sha256` and the response-only `ProducerSecretIssued.secret` (A7).
- [ ] Given a `CostRecord` with `tags: {"cost_center": "cc-1001"}`, it validates; more than 16 entries, a key outside `^[a-z][a-z0-9_.-]{0,62}$`, or a value longer than 128 characters is rejected; records without `tags` still validate (#190 item 1).
- [ ] `structured-query` accepts `grant`, `mcp_server` and the `grants_access_to` relation, and `tests/contracts/validators.py` `FIELD_APPLICABILITY` has rows for them (#148 item 1).
- [ ] `error-codes.json` gains `not_found` (404), `method_not_allowed` (405), `payload_too_large` (413) and `internal_error` (500) rows; `ProblemDetails` accepts them; `neurosphere_core.errors` has exactly one class per code and `packages/core/tests/test_errors.py` passes (PRP-05 leftover).
- [ ] `ConnectorManifest` `scopes` items, `credential_ref.name` and `documentation_url` path are capped (Item 3 values); every manifest under `connectors/**` still validates (PRP-01 leftover).
- [ ] An additive-only baseline test fails when a `v1` schema removes a property, removes an enum value, adds a required property or narrows a type, compared with a committed snapshot; the one deliberate tightening (manifest caps) is listed in the test's allowlist with a reason and recorded in ADR-0004.
- [ ] A contract test asserts every catalog relation schema requires `provenance` with `common.schema.json#/$defs/provenance` (#195 provenance bullet, contract half).
- [ ] PRP exit: the touched suites, `generate.py --check`, ruff, pyright and `validate_planning.py` pass; PR open with CI green including the `contracts` job; Tier-3 files regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where admin wire shapes live | contracts family; API-local models | `packages/contracts/schemas/admin/v1/` so Python, TS and the mock API share them (lane-d unit A) |
| 5 | Credentials in admin records | values; references | References only: Key Vault secret URI or managed identity (A7) |
| 6 | CostRecord tag shape | `cost_center` field; `tags` map | `tags` map, at most 16 entries, values 128 chars, reserved key `cost_center` with the Grant `cost_center` pattern (#190 proposal) |
| 7 | ConnectorManifest caps are a tightening inside `v1` | allow with evidence; new `v2` | ASSUMPTION: allowed because no manifest in the repo exceeds them (test proves it); recorded as the single ADR-0004 exception |
| 10 | Typed setting bodies vs one generic body | per-kind schema; free map | Per-kind `$defs` in `system-setting.schema.json`; `AdminConfigDocument.body` is validated by kind in core (`ADMIN_KIND_MODELS`, built by PRP-65) |
| 11 | Split from the original PRP-37 (2026-11-14 second pass) | one PRP; split | Split: rows 2, 3, 4, 8 and 9 and the permission, policy-write and store items moved to PRP-65 with their numbering kept there |

## Context manifest

### Files to read first
- `packages/contracts/scripts/generate.py` - `discover_schemas` (`<area>/v<major>/*.schema.json`), staging rules, `--check`.
- `docs/adr/0004-contract-versioning.md` - `v1` additive-only rule this PRP enforces with a test.
- `packages/contracts/schemas/catalog/v1/grant.schema.json` - `cost_center` pattern; `catalog/v1/common.schema.json` `$defs` (`provenance` at :166, `etag`, `timestamp`).
- `packages/contracts/schemas/connectors/v1/connector-manifest.schema.json` - `$defs/credential_ref` (`vault_ref` pattern to reuse in `CredentialReference`).
- `packages/core/neurosphere_core/hitl/policy.py:37-110` and `pricing/models.py:64-160` - shapes `ReviewPolicyDocument` and `PriceSheetUpload` must map onto.
- `services/api/neurosphere_api/ingest/auth.py:34-47` - `ProducerRegistration` fields `ProducerRecord` must carry.
- `tests/contracts/validators.py:661` (`FIELD_APPLICABILITY`), `tests/contracts/test_error_taxonomy.py`, `packages/core/tests/test_errors.py`.

### Interfaces consumed
- PRP-01 contract conventions (`schema_version` `1.x.y`, `x-ns-name`, `additionalProperties: false`), PRP-05 `neurosphere_core.errors`, PRP-06 policy and revocation models (shape reference for the identity schemas). All shipped.

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
- Errors: `NotFoundError`, `MethodNotAllowedError`, `PayloadTooLargeError`, `InternalError` in `neurosphere_core.errors`.

Permissions, `policy_admin` and `neurosphere_core.admin` names are provided by PRP-65.

### Patterns to match
- Schema file and `$id` style: `packages/contracts/schemas/cost/v1/cost-record.schema.json:1-10`.
- Contract tests per family: `tests/contracts/test_grant_and_mcp_server.py`, `test_connector_manifest.py`.

### Gotchas
- `generate.py` regenerates `packages/contracts/ts/src/index.ts` and every family; items that change schemas are serial, never parallel.
- Pydantic ignores `if/then/else` (PRP-01 deviation): cross-field rules need JSON Schema tests plus a core validator.
- `StructuredQuery` is a `response_model` in `services/api/openapi.json`; the enum change regenerates it (Tier 3, at merge, not before).
- Adding error codes breaks `test_every_contract_code_has_exactly_one_class` until core error classes exist: same item.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - packages/core/neurosphere_core/errors/**
  - packages/core/tests/test_errors.py
  - packages/core/neurosphere_core/audit/builders.py
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
tier1:
  - packages/contracts/schemas/**
tier2_appends: []
must_not_touch:
  - services/api/**
  - services/workers/**
  - frontend/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/auth/**
  - packages/core/neurosphere_core/admin/**
  - packages/core/neurosphere_core/stores/**
  - infra/**
  - .github/workflows/ci.yml
```

## Implementation blueprint

Parallelization: items 1, 2, 3 are serial (shared generated output). Item 4 last.

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

### Item 4 - Integration and close-out
- Deliverable: rebase on `main`; regenerate contracts and Tier-3 files (`services/api/openapi.json`, `docs/reference/**`, PRP status table, `PRPs/INDEX.md`); CHANGELOG entry (a `changelog.d/` fragment instead if PRP-68 has merged first); completion note listing every provided schema and error name for PRP-39..57 and PRP-65 authors; follow-up issue numbers.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-3.
- Acceptance criteria: validation gates below pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q tests/contracts packages/core/tests/test_errors.py tests/unit/connector_conformance services/api/tests/test_openapi_drift.py
pnpm --filter ./packages/contracts/ts test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
All schema changes are additive inside `v1` except the documented manifest cap. Stored `CostRecord`s without `tags` stay valid. No data is migrated and no container is added here. Nothing reads the new `admin/v1` schemas until PRP-65 and PRP-39+ ship, so revert is a plain `git revert` plus a contracts regeneration.

## Live and open gates
None. Contract work is fully provable offline.

## NOT building
Ingest tag mapping, ledger tag queries, API error handler changes, catalog provenance population, budget alert delivery; and everything PRP-65 builds (permissions, deployment-scope helper, policy write repository, `admin_config` store).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 7 is an ASSUMPTION for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-37-contracts-admin | admin/v1 common, credential-reference and identity schemas, examples, bindings, credential walker; admin-config-document moved to item 2 (its body is the item-2 kind schemas) |
| 2 | verifying | prp-37-contracts-admin | producer, connector, domain, SpendBudget (title renamed: query/v1 owns Budget), price sheet, review policy, system setting, checklist item and AdminConfigDocument (body pinned per kind); mapping tests to PriceSnapshot, ReviewPolicyRegistry, ProducerRegistration |
| 3 | verifying | prp-37-contracts-admin | CostRecord.tags, query grant/mcp_server/grants_access_to, 4 error codes + core classes (audit denial enum mirrored), manifest caps, provenance test, additive-only baseline + test, ADR-0004 amendment; follow-up #272 for API handlers |
| 4 | merged | prp-37-contracts-admin | merge step: rebase on main, regenerate Tier-3 (openapi.json, docs/reference, status table, INDEX.md, CHANGELOG), close out |

## Completion note (filled at ship)
- Date and PR: shipped 2026-11-15, PR #273 (branch `prp-37-contracts-admin`).
- Provided names (for PRP-39..57 and PRP-65 authors): `neurosphere_contracts.admin.v1.<module>` / `packages/contracts/ts/src/admin/v1/<file>.ts`:
  `common` (`$defs`: `admin_kind`, `config_version`, `reason_code`, `principal_id`, `customer_id`, `cloud`, `canonical_id`, `domain_id`, `record_id`, `slug`, `display_name`, `timestamp`, `date`, `etag`, `role`, `grant_permission`, `decimal_amount`, `currency`, `https_url`, `azure_resource_id`, `cost_tags`, `doc_path`),
  `CredentialReference`, `AdminConfigDocument`, `RoleAssignmentChange`, `DomainMembershipChange`, `ResourceGrantChange`, `PrincipalAccessSummary`, `RevocationRequest`, `RevocationStatus`, `ProducerRecord`, `ProducerSecretIssued`, `ConnectorConfig`, `DomainDefinition`, `SpendBudget` (module `budget`), `PriceSheetUpload`, `ReviewPolicyDocument`, `SystemSetting`, `FirstRunChecklistItem`.
  Revised: `CostRecord.tags`; `StructuredQuery` entities `grant`, `mcp_server`, relation `grants_access_to`; `ProblemDetails` codes `not_found`, `method_not_allowed`, `payload_too_large`, `internal_error`; core `NotFoundError`, `MethodNotAllowedError`, `PayloadTooLargeError`, `InternalError`.
- Deviations: (1) admin `budget.schema.json` is titled `SpendBudget`, not `Budget`, because `query/v1` already exports `Budget` from the TS index. (2) `setting_key` contains the segment `key`; the credential walker allows it only while enum-constrained (plus `secret_uri`, pattern-bound to Key Vault hosts, and `PriceSheetRow.token_meter`, a price meter). (3) Admin change requests carry `schema_version` and machine `reason` codes (not free text); `ResourceGrantChange` has no `op` (removal is a route delete) and `RevocationRequest` names no target (the route does). (4) The audit `denial.code` enum and core `audit.builders.DenialCode` gained the four new codes, because the existing validator keeps audit denial codes equal to the taxonomy and core passes `NeuroSphereError.code` into `DenialCode` (`packages/core/neurosphere_core/audit/builders.py` is outside the declared ownership: a four-line additive Literal mirror). (5) `CostRecord.tags` and `SpendBudget.tags_filter` share one grammar; the generated Pydantic models keep key/value bounds but not the 16-entry cap or the `cost_center` pattern (ADR-0004 projection), checked by `validate_cost_tags`. (6) Item 1 committed without `admin-config-document`, which landed with item 2 because its body is pinned to the item-2 kind schemas.
- Reviewer follow-ups applied at merge: rendered `ProblemDetails.schema_version` is now `1.1.0` (taxonomy 1.1.0); `audit/builders.py` added to the Ownership block; the status-table date line is regenerated at merge, not carried from the branch.
- Descoped items: none.
- OPEN gates: none live (contract-only PRP). Tier-3 regeneration at merge: `services/api/openapi.json` (drift test fails until regenerated), `docs/reference/**` (`test_api_page_states_error_taxonomy` and `test_regeneration_equals_committed_output` fail until regenerated), status table, `PRPs/INDEX.md`, CHANGELOG.
- Env vars for the operator: none.
- Follow-up issues: #272 (API handlers emit the four new problem codes; the frontend `TAXONOMY_CODES` list is in its scope). For PRP-42: validate per-kind `ConnectorConfig.settings` values (URL, resource id, integer) server-side, since a neutral key such as `endpoint` can still carry a 512-char secret-like string. For PRP-46: call a core validator (`validate_cost_tags`) for the 16-entry cap and `cost_center` pattern; the generated `CostTags` and admin `cost_tags` models do not enforce them. Still open: #226 (permissions and stores half is PRP-65), #190 beyond tags (ingest mapping, ledger queries), #114 (deployment-scope helper, PRP-65), #195 (catalog provenance population), #148 (non-enum items).
- Product check (can an operator use it without editing files): no, by design: this PRP ships contracts only; the console and APIs that use them are PRP-39..57 and PRP-65.
