---
name: PRP-65-admin-permissions-policy-repository-and-config-store
status: shipped
priority: P0
order: 53
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-08, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions]
wave: W12
branch: prp-65-admin-store
allow_parallel: true
issues: [265]
shipped: 2026-11-15
pr: 277
---

# PRP-65: Admin permissions, policy write repository and audited config store

## Goal
Ship the storage and authority layer that every operator control-plane PRP codes against, on top of the `admin/v1` schemas PRP-37 ships in W11, and nothing above it: two new permissions plus a core helper for deployment-scoped (customer-wide) authority, a write side for the policy store (`PolicyAdminRepository`), and a versioned, ETag-guarded `admin_config` Cosmos container with an in-memory twin and an audit chain name. It is for the authors of PRP-39, 40, 41, 42, 44, 45, 48, 53 and 57 and for PRP-23 (same wave, `lifecycle.manage`), who must build against these names instead of inventing stores. It runs in W12 as the wave owner of the stores files and `permissions.py`; permissions and stores are Tier 1 and an authorization mistake here is a security defect everywhere, which is why it is Opus with a required review (PRP-06 identity/audit model policy).

Out of scope: every schema and contract revision, including `AdminConfigDocument`, `CredentialReference` and the error classes (PRP-37, W11); every route and UI (PRP-39 identity API, PRP-40 audit search and SIEM, PRP-41 producers, PRP-42 connectors, PRP-44 domains/budgets/prices/review policy, PRP-45 system settings, PRP-53 and PRP-57 console pages); applying the deployment-scope helper to MCP admin, deploy scan and the kill switch (PRP-48, #114 behaviour half); lifecycle routes and jobs that use `lifecycle.manage` (PRP-23); real-stack seeding through `scripts/sandbox` (PRP-38).

## Why
- No admin store exists: `PolicyRepository` is read-only (`packages/core/neurosphere_core/auth/scope/policy.py:108-116`, "Writes belong to the (audited) admin path"), and the only writer is `scripts/sandbox/sbx_grant_operator.py:101-167` (lane-d step 1, unit A).
- `Permission.POLICY_MANAGE` and `REVOCATION_MANAGE` are declared (`permissions.py:74-75`) but have zero uses in `services/` (lane-d step 1); there is no deployment-scoped permission (#114, lane-e).
- `CONTAINERS` (`packages/core/neurosphere_core/stores/containers.py:96-183`) has no container for operator configuration; every later control-plane PRP needs one.

## Acceptance criteria
- [x] `Permission.LIFECYCLE_MANAGE` (`lifecycle.manage`, Admin) and `Permission.AUDIT_EXPORT` (`audit.export`, Security Auditor) exist; role sets are pinned by `test_roles.py` and `test_privileged_roles.py`; no role gains anything else.
- [x] `customer_control_domain_id(cloud, customer_id)` and `permits_customer_wide(scope, permission, *, now)` live in core and return True only for an unexpired assignment on `<cloud>:<customer>:neurosphere:domain:customer-control` (#114 schema half); `actions/customer_control.py` behaviour is unchanged.
- [ ] `PolicyAdminRepository` (in-memory and Cosmos) writes `PrincipalPolicy` with an ETag precondition and bumps `PolicyHead.policy_version` in the same partition; a stale ETag raises `stale_version`; the read protocol is unchanged.
- [ ] `admin_config` is declared in `CONTAINERS`, exported to `infra/compose/cosmos-containers.json`, and `AdminConfigRepository` (in-memory and Cosmos) supports create, get, list by kind, replace with `If-Match` and retire, with a monotonic `version`; tested on the in-memory twin and, marked `integration`, on the emulator.
- [ ] PRP exit: the touched suites, `python -m neurosphere_core.stores --check`, ruff, pyright and `validate_planning.py` pass; PR open with CI green; Tier-3 files regenerated at merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 2 | Container name | `admin-config` (lane-d text); `admin_config` | `admin_config`: every container added since PRP-17 is snake_case (`action_intents`, `price_snapshots`, `catalog_review_queue`); partition `/customer_id` |
| 3 | Policy writes: new container or existing `policy` | new; existing | Existing `policy` container and documents (`PrincipalPolicy`, `PolicyHead`), so derivation reads what admin writes with no migration |
| 4 | Deployment-scoped admin (#114) | new role; new permission; reserved control domain | Reserved control domain already used by the kill switch (`actions/customer_control.py`); roles stay the closed set of five (PRP-06 C6/C7). Core gets the helper; PRP-48 applies it |
| 8 | New permission for audit export | reuse `audit.read`; `data.export`; new `audit.export` | ASSUMPTION: new `audit.export` held by Security Auditor only (lane-d unit J "data.export-style permission"; Admin never reads audit) |
| 9 | Lifecycle permission (PRP-23 needs one in the same wave) | each PRP adds its own; PRP-65 adds | PRP-65 adds `lifecycle.manage` (Admin). If PRP-23 merges first with the same member, keep one line at rebase (Tier-2 rule) |

Row numbers are kept from the original PRP-37 (split 2026-11-14); rows 1, 5, 6, 7 and 10 stay in PRP-37.

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/auth/scope/permissions.py` - `Permission`, role sets, `PRIVILEGED_ROLES`, `permits`.
- `packages/core/neurosphere_core/auth/scope/policy.py` - `PrincipalPolicy`, `PolicyHead`, `PolicyRepository`; `cosmos_repository.py` and `memory.py` twins.
- `services/api/neurosphere_api/actions/customer_control.py` - control domain convention (read only).
- `packages/core/neurosphere_core/stores/containers.py` and `stores/__main__.py` - registry and export writer.
- `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140` - ETag create/replace pattern with mapped errors.
- `PRPs/backlog/PRP-37-contracts-revision-admin-cost-and-permissions.md` "Interfaces provided" - the `admin/v1` models this PRP stores.
- `PRPs/backlog/PRP-23-ato-evidence-and-data-lifecycle.md` Clarification 4 - the same-wave `lifecycle.manage` line.

### Interfaces consumed
- PRP-37 (W11): `neurosphere_contracts.admin.v1` models (`AdminConfigDocument`, `CredentialReference`, `admin_kind`, `config_version`, the per-kind body models listed there), `RoleAssignmentChange`, `DomainMembershipChange`, `ResourceGrantChange`; Clarification 10 (body validated by kind in core).
- PRP-05 `neurosphere_core.errors` (`StaleVersionError`, `DependencyTransientError`, `invalid_schema`), PRP-06 policy and revocation models, PRP-29 container registry. All shipped.

### Interfaces provided
- `neurosphere_core.auth.scope.permissions`: `Permission.LIFECYCLE_MANAGE`, `Permission.AUDIT_EXPORT`, `CUSTOMER_CONTROL_SOURCE`, `CUSTOMER_CONTROL_DOMAIN_NAME`, `customer_control_domain_id()`, `permits_customer_wide()`.
- `neurosphere_core.auth.scope.policy_admin`: `PolicyAdminRepository` protocol (`get_with_etag`, `list_principals`, `put_principal_policy(policy, *, if_match)`), `InMemoryPolicyAdminRepository`, `CosmosPolicyAdminRepository`, pure `apply_role_change`, `apply_membership_change`, `apply_grant_change`, `next_policy_version`.
- `neurosphere_core.admin`: `ADMIN_CONFIG_CONTAINER = "admin_config"`, `AdminConfigRepository` protocol, `InMemoryAdminConfigRepository`, `CosmosAdminConfigRepository`, `ADMIN_KIND_MODELS` (kind -> generated model), `admin_config_chain_id(customer_id)` naming `<customer>.admin-config` for audited writes.
- Cosmos container `admin_config` (partition `/customer_id`) in `CONTAINERS` and `infra/compose/cosmos-containers.json`.

### Patterns to match
- Container spec entry: `stores/containers.py:157-182`; ETag replace: `mcp/cosmos_store.py:110-133`; policy write and head bump: `scripts/sandbox/sbx_grant_operator.py:113-167`.

### Gotchas
- `PolicyHead` and `PrincipalPolicy` share partition `/customer_id`; write both in one transactional batch on Cosmos so a crash cannot leave a stale cache version.
- Never log `secret_uri`, `secret_sha256` or a tag value (CodeQL secret-name rule, #190 item 3).
- `permissions.py` is Tier 1 for this PRP in W12, and PRP-23 appends `LIFECYCLE_MANAGE` there as a Tier-2 line in the same wave: whichever merges second keeps a single line at rebase.
- `scripts/sandbox/**` belongs to PRP-38 in W12: read `sbx_grant_operator.py` as a pattern, do not edit it.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/admin/**
  - packages/core/neurosphere_core/auth/scope/policy_admin.py
  - packages/core/neurosphere_core/auth/scope/__init__.py
  - packages/core/tests/admin/**
  - packages/core/tests/stores_registry/**
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
  - infra/bicep/modules/cosmos.bicep
  - packages/core/neurosphere_core/auth/scope/permissions.py
tier2_appends:
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
must_not_touch:
  - packages/contracts/**
  - services/api/**
  - services/workers/**
  - frontend/**
  - scripts/sandbox/**
  - docker-compose.yml
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/lifecycle/**
  - packages/core/neurosphere_core/analytics/**
  - packages/core/neurosphere_core/auth/revocation/**
```

## Implementation blueprint

Parallelization: items 1, 2 and 3 share no file and depend only on PRP-37 having merged; all three may run in parallel. They all add files under the new `packages/core/tests/admin/` directory: create it without an `__init__.py` clash (reference section on test package names). Item 4 last.

### Item 1 - Permissions and deployment scope  [P]
- Deliverable: `LIFECYCLE_MANAGE` (Admin), `AUDIT_EXPORT` (Security Auditor), the customer-control constants and `customer_control_domain_id` / `permits_customer_wide`; docstring table updated; role pin tests updated (#148 item 5 `SHARED_ADMIN_STEWARD` reviewed).
- Owned files: `packages/core/neurosphere_core/auth/scope/permissions.py`, `auth/scope/__init__.py` exports, `packages/core/tests/auth/scope/test_roles.py`, `tests/security/authz/test_privileged_roles.py`, `packages/core/tests/admin/test_customer_wide.py` (new).
- Must NOT touch: `services/api/**` (customer_control.py keeps its constants until PRP-48 moves it).
- Depends on: none.
- Acceptance criteria: expired, cross-cloud and cross-customer assignments on the control domain return False; ordinary domains never satisfy `permits_customer_wide`; no wildcard introduced.
- Tests: the three files above.
- Pattern references: `permissions.py:146-190`, `customer_control.py`.

### Item 2 - Policy write repository  [P]
- Deliverable: `policy_admin.py` with protocol, twins and pure change functions; transactional head bump; stale ETag -> `StaleVersionError`; store failure -> `DependencyTransientError`.
- Owned files: `packages/core/neurosphere_core/auth/scope/policy_admin.py` (new), `packages/core/tests/admin/test_policy_admin.py` (new), `packages/core/tests/admin/test_policy_admin_cosmos.py` (new, `integration`).
- Must NOT touch: `policy.py`, `cosmos_repository.py`, `derivation.py` (read path unchanged).
- Depends on: PRP-37 (identity change schemas).
- Acceptance criteria: removing the last assignment leaves a valid document; applying a change for another customer raises; derivation over the twin sees the change after the head bump.
- Tests: the two new files.
- Pattern references: `sbx_grant_operator.py:113-167`, `cosmos_repository.py:38-90`.

### Item 3 - Admin config store  [P]
- Deliverable: `neurosphere_core/admin/` package (`models.py`, `store.py`, `cosmos_store.py`, `chains.py`), `admin_config` container spec, regenerated `infra/compose/cosmos-containers.json`.
- Owned files: `packages/core/neurosphere_core/admin/**` (new), `stores/containers.py`, `infra/compose/cosmos-containers.json`, `packages/core/tests/admin/test_config_store.py` (new), `test_config_store_cosmos.py` (new, `integration`), `packages/core/tests/stores_registry/**` only if a pin needs the new entry.
- Must NOT touch: the two Bicep modules unless the export test proves they need a change (`cosmos-data.bicep` loads the JSON).
- Depends on: PRP-37 (`AdminConfigDocument` and the per-kind schemas).
- Acceptance criteria: version increments by one per replace; `If-Match` mismatch raises `stale_version`; a body that fails its kind model is `invalid_schema`; retire keeps the document readable; the export drift test passes.
- Tests: the new files plus `packages/core/tests/stores_registry`.
- Pattern references: `stores/containers.py:157-182`, `gateway/cosmos_store.py:94-200`.

### Item 4 - Integration and close-out
- Deliverable: rebase on `main`; resolve the `permissions.py` line with PRP-23 if it merged first (one `LIFECYCLE_MANAGE` line); regenerate Tier-3 files (`docs/reference/**`, PRP status table, `PRPs/INDEX.md`); CHANGELOG entry (a `changelog.d/` fragment if PRP-68 has shipped); completion note listing every provided name for PRP-23 and PRP-39..57 authors.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-3.
- Acceptance criteria: validation gates below pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m neurosphere_core.stores --check
uv run pytest -q packages/core/tests/admin packages/core/tests/auth/scope packages/core/tests/stores_registry tests/security/authz/test_privileged_roles.py
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator suites (local, not CI): `docker compose up -d --wait` then `uv run pytest -q -m integration packages/core/tests/admin`.

## Migration and rollback
Policy writes reuse the existing `policy` container and document shapes, so no data migration. The `admin_config` container is new: local emulators create it; hosted environments get it from `cosmos-data.bicep` on the next deploy (PRP-58 / operator). The two permissions are additive; no role loses a permission. Nothing reads the new store until PRP-39+ ship, so revert is a plain `git revert` plus leaving an empty container.

## Live and open gates
None. Cosmos behaviour is proven on the emulator only; hosted container creation happens at the next operator deploy (PRP-58, PRP-64).

## NOT building
Routes, UI, mock handlers, worker pickup, any secret value storage; schema changes (PRP-37); applying `permits_customer_wide` in API code (PRP-48).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 8 is an ASSUMPTION for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-65-admin-store | permissions, control-domain helpers, role pins; tests pass locally |
| 2 | verifying | prp-65-admin-store | policy_admin.py twins + pure changes; emulator suite written, not run (PRP-38 holds compose) |
| 3 | verifying | prp-65-admin-store | neurosphere_core.admin + admin_config container + export; emulator suite written, not run (PRP-38 holds compose) |
| 4 | done | prp-65-admin-store | close-out 2026-11-15 |

## Completion note (filled at ship)
- Date and PR: 2026-11-15, PR #277 (squash-merged after green CI)
- Deviations (draft, items 1-3): `tests/unit/hosted_demo/test_cosmos_container_drift.py` container count 28 -> 29 (outside the Ownership block; forced by the new container, one line). `test_roles.py` pins were edited in place, not only appended (item 1 requires the role pins to change). `policy_admin` adds `remove_grant` and `empty_principal_policy` beyond the listed names. Role changes do not touch memberships (callers pair them with `apply_membership_change`). `validate_admin_body` also enforces the JSON Schema if/then rules Pydantic drops (credential members and vault cloud, system-setting member, secret-like connector keys, budget thresholds/tags, retail price sheet cloud/host, maker_checker default) and the customer/cloud of every canonical id in a body. Cosmos `admin_config` rows use the composite id `<kind>:<id>` with the contract document nested under `document`.
- Descoped items: none.
- OPEN gates: emulator suites `test_policy_admin_cosmos.py` and `test_config_store_cosmos.py` (marked `integration`) not run: PRP-38 held the compose stack in W12. Hosted `admin_config` container creation waits for the next operator deploy (PRP-58/64).
- Env vars for the operator: none.
- Follow-up issues: customer-level audit chains (`<customer>.admin-config`, like `.gateway`) share the catalog-shaped form, so a catalog domain literally named `admin-config` would decode to the same chain; PRP-44's domain write path must reserve that name (file an issue at merge).
- Product check (can an operator use it without editing files): no, by design: storage and authority layer only; routes and console arrive in PRP-39..57.
- Close-out additions (2026-11-15): merged origin/main; the permissions.py and test_roles.py conflicts with PRP-23 were resolved keeping a single LIFECYCLE_MANAGE line plus AUDIT_EXPORT. No serial-after items exist in this PRP. Hardened admin/models.py _check_credential to take the vault host from urllib.parse.urlsplit().hostname. Documented on InMemoryPolicyAdminRepository that a replace of a seeded document is refused as stale until get_with_etag has assigned an ETag (for PRP-38 sandbox and PRP-39 tests). Filed #279 (PRP-44 must reserve the domain name admin-config). openapi.json and docs/reference needed no regeneration (no API or SDK change).
- Acceptance boxes left unticked: criteria 3 and 4 (Cosmos halves OPEN, emulator suites not run) and criterion 5 (CI at merge). Criteria 1 and 2 have passing tests.
- Reviewer follow-up (OPEN, before PRP-39 depends on this code): run packages/core/tests/admin/test_policy_admin_cosmos.py and test_config_store_cosmos.py on the emulator and confirm CosmosBatchOperationError carries the failed operation status_code and error_index, and that each batch result row has an eTag key. The unit FakeContainer assumes both, as does the 0/1 index mapping in CosmosPolicyAdminRepository.put_principal_policy (packages/core/neurosphere_core/auth/scope/policy_admin.py).
- Deviation: tests/unit/hosted_demo/test_cosmos_container_drift.py is outside the Ownership block; container count 28 -> 29, forced by the new container.
