---
name: PRP-39-identity-admin-api-and-revocation
status: shipped
shipped: 2026-11-15
pr: 283
priority: P0
order: 24
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-08
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-65-admin-permissions-policy-repository-and-config-store]
wave: W13
branch: prp-39-identity-admin
allow_parallel: true
issues: [230]
---

# PRP-39: Identity admin API and principal revocation

## Goal
Give an admin an audited API to see who has access and to change it: list principals, assign and remove role assignments, domain memberships and resource-scoped grants (each with expiry and reason), and revoke a principal, either bounded by token issue time (today's model) or blocked until an admin lifts it. Every write goes through `run_audited_mutation`, is deny-by-default, refuses self-modification and refuses anything outside the actor's own managed domains; there is no bypass. The composed app finally instantiates `RevocationService`, so the push fan-out that PRP-06 built has a production caller. This is the backend for the PRP-53 users/roles page and the base package (`neurosphere_api.admin`) that PRP-41, 42, 44 and 45 add sub-packages to. It runs in W13, right after PRP-37/PRP-65 supplies the contracts and the policy write repository; the first admin is still bootstrapped by `make grant-operator`.

Out of scope: the console page (PRP-53); route-category and `/workspaces/{role}` tenancy and applying deployment scope to MCP admin, deploy scan and the kill switch (PRP-48, #91, #114); audit search, export and SIEM (PRP-40); cross-replica WebSocket close e2e (deferred by PRP-18, issue to be filed there); producer, connector and platform admin (PRP-41, 42, 44).

## Why
- `POLICY_MANAGE` and `REVOCATION_MANAGE` are declared (`packages/core/neurosphere_core/auth/scope/permissions.py:74-75`) and given to Admin (`:90-99`), but no route requires them (lane-d step 1; `grep -rn POLICY_MANAGE services` is empty).
- `PolicyRepository` has no write method (`auth/scope/policy.py:108-116`); the only writer is `scripts/sandbox/sbx_grant_operator.py:101-167`, one operator at a time (lane4 2.2, `docs/validation/lane4-identity-docs-operator-setup.md:108`).
- `RevocationService` (`auth/revocation/service.py:137`) is instantiated nowhere outside a docstring (`auth/revocation/__init__.py:18`); PRP-06 close-out: "no composed RevocationService or admin revoke route" (`PRPs/shipped/PRP-06-identity-authz-and-audit.md:293`).
- Block-until-lifted revocation was left OPEN as follow-up (2) (`PRP-06-*.md:285`): `CachedRevocationChecker` denies only tokens issued before `revoked_at` (`auth/revocation/checker.py:1-17`), so a revoked user can sign in again immediately.
- Hosted users "can sign in but see nothing" and only an operator with Cosmos access can fix it (lane4 4.1, `lane4-identity-docs-operator-setup.md:191-197`).

## Acceptance criteria
- [x] Given an admin holding `policy.manage` in domain D, when they `PUT` a role assignment for principal P in D with `expires_at` and `reason`, then P's policy document changes, `PolicyHead.policy_version` advances, P's next request derives the new scope, and before/after audit records land on D's chain.
- [x] A change naming any domain where the actor lacks `policy.manage` returns 403 `target_out_of_scope` and writes a denial record; nothing is written to the policy store.
- [x] An actor changing their own policy document gets 403 `self_modification_forbidden` (ASSUMPTION row 3).
- [x] Assigning `security_auditor` or `admin`, or any change on the customer-control domain, requires `permits_customer_wide(actor, POLICY_MANAGE)` (PRP-37/PRP-65); privileged assignments without `expires_at` are 422 (contract rule, C7).
- [x] Resource-scoped grants require `policy.manage` on the domain that owns the resource and always carry `expires_at` and `reason`; `grant.write` is not accepted for them (Clarification 2).
- [x] Concurrent edits: a stale `If-Match` returns 409 `stale_version`; a missing `If-Match` on update returns 428-equivalent `invalid_schema` reason `precondition_required` (no lost update).
- [x] `GET /api/v1/admin/identity/principals` lists only principals that have a membership or assignment in a domain the actor manages, and shows only those domains' entries; page size bounded; no UPN, email or raw object id in any response or log.
- [x] `POST /api/v1/admin/identity/principals/{principal_id}/revocation` with `mode: issued_before` behaves as PRP-06 (403 within `NS_REVOCATION_TTL_SECONDS`, cache invalidators and push closers called, intent and outcome audited); with `mode: until_lifted` every token is refused, including ones issued after revocation, until `DELETE .../revocation` lifts it (audited); proven with a fake clock.
- [x] Revocation of a principal in another cloud or customer is 403 `cross_scope_target`; a revocation store outage is 503 and never an allow.
- [x] Every new route is in the route inventories and boots under `verify_route_permissions`; `services/api/openapi.json` regenerated.
- [x] PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; runbook `docs/runbooks/identity-admin.md` explains bootstrap (grant script) then the API.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Permission for role and membership changes | `config.manage`; `policy.manage` | `policy.manage` in every domain the change names (ASSIGNMENTS) |
| 2 | Permission for resource-scoped grants | `grant.write`; `policy.manage` | `policy.manage` on the resource's domain. `grant.write` governs catalog Grant documents (`permissions.py:23-26`), not `PolicyGrant`; ASSIGNMENTS named it, the code says otherwise |
| 3 | Maker limits | domain scope only; plus no self-change; plus role-subset rule | ASSUMPTION: domain scope plus no self-modification plus customer-wide authority for privileged roles; no role-subset rule (it would stop Admin assigning Steward, which Admin cannot hold) |
| 4 | Revocation modes | TTL only (C12); add until-lifted | Both; request chooses, default `issued_before` so C12 behaviour is unchanged (PRP-06 follow-up 2) |
| 5 | Who may revoke | `revocation.manage` any domain (current `ScopePermissionRevocationAuthorizer`); shared domain | Keep the shipped default authorizer; lifting requires the same permission |
| 6 | First admin bootstrap | API; script | Script stays (`make grant-operator`); the API needs an existing admin |
| 7 | Principal discovery | Graph lookup; pseudonymous ids only | Pseudonymous canonical ids only; display names are PRP-53's concern and never come from Entra through this API |

## Context manifest

### Files to read first
- `PRPs/shipped/PRP-37-contracts-revision-admin-cost-and-permissions.md` completion note (once shipped) - exact names delivered.
- `packages/core/neurosphere_core/auth/scope/policy_admin.py` (PRP-37/PRP-65) - write repository and pure change functions.
- `packages/core/neurosphere_core/auth/revocation/service.py:70-240` - `RevocationService`, authorizer, auditor protocols.
- `packages/core/neurosphere_core/auth/revocation/{model,checker,store,cosmos_store}.py` - entry, TTL cache, store; where `mode` and lift go.
- `services/api/neurosphere_api/runtime/builders/authz.py:101-374` - published keys `POLICY_REPOSITORY`, `REVOCATION_STORE`, `REVOCATION_HOOKS`, `REVOCATION_CHECKER`; `AuditDenialRecorder`.
- `services/api/neurosphere_api/runtime/builders/__init__.py:167-180,356` - `SharedKey`s and `default_builders()`.
- `services/api/neurosphere_api/actions/customer_control.py` - customer-level check order to mirror.
- `services/api/neurosphere_api/mcp/admin/router.py:96-198` - an existing audited admin router.
- `packages/core/neurosphere_core/audit/repository.py:247-270` - `run_audited_mutation`.
- `services/api/neurosphere_api/routers.py:200-251` - register hooks.
- `tests/security/authz/{world.py,cases.py,test_api_paths.py}` - ABAC negative-suite harness.

### Interfaces consumed
- From PRP-37/PRP-65: `RoleAssignmentChange`, `DomainMembershipChange`, `ResourceGrantChange`, `PrincipalAccessSummary`, `RevocationRequest`, `RevocationStatus` (`neurosphere_contracts.admin.v1`); `PolicyAdminRepository`, `CosmosPolicyAdminRepository`, `InMemoryPolicyAdminRepository`, `apply_role_change`, `apply_membership_change`, `apply_grant_change`; `Permission.POLICY_MANAGE`, `Permission.REVOCATION_MANAGE`, `permits_customer_wide`, `customer_control_domain_id`; `NotFoundError` for an unknown principal.
- From PRP-06 (shipped): `RevocationService`, `ScopePermissionRevocationAuthorizer`, `RevocationHookRegistry`, `CachedRevocationChecker`, `require(permission, resource=...)`, `AuditRepository`, `domain_audit_chain_id`.

### Interfaces provided
- Package root `neurosphere_api.admin` (with `register(registry)` that later admin sub-packages extend by adding their own hook lines in `routers.py`).
- Routes under `/api/v1/admin/identity`: `GET /principals`, `GET /principals/{principal_id}`, `PUT|DELETE /principals/{principal_id}/role-assignments/{assignment_id}`, `PUT|DELETE /principals/{principal_id}/domain-memberships/{domain_id}`, `PUT|DELETE /principals/{principal_id}/grants/{grant_id}`, `POST|GET|DELETE /principals/{principal_id}/revocation`.
- Builder `runtime/builders/admin.py`: `BUILDER = BuilderSpec("admin", ("policy_admin", "revocation_service"), build)`; shared keys `POLICY_ADMIN_REPOSITORY`, `REVOCATION_SERVICE`; components `policy_admin`, `revocation_service` in `OPTIONAL_COMPONENTS`.
- Core: `RevocationEntry.mode`, `RevocationStore.lift(principal_id, *, lifted_by)`, `RevocationService.lift(actor, principal_id, *, reason)`.
- Audit operations: `policy.role_assign`, `policy.role_remove`, `policy.membership_add`, `policy.membership_remove`, `policy.grant_put`, `policy.grant_remove`, `principal.revoke` (existing), `principal.revoke_lift`.

### Patterns to match
- Audited admin mutation: `services/api/neurosphere_api/mcp/admin/router.py:96-198`.
- Builder module and publish: `runtime/builders/gateway.py`, `runtime/builders/authz.py:230-302`.
- Customer-level check: `actions/customer_control.py` (docstring order of checks).
- ABAC case style: `tests/security/authz/cases.py`, `test_api_paths.py`.

### Gotchas
- Principal ids contain colons; use a path converter and the canonical pattern, and never echo an invalid value (it may be a UPN).
- The policy cache is keyed by `policy_version`; forgetting the head bump leaves other replicas serving the old scope until TTL.
- `until_lifted` entries must not inherit the per-item revocation `ttl` (`revocations` container uses `TTL_PER_ITEM`), or a block silently expires.
- `REVOCATION_HOOKS` is published by the authz builder; the admin builder must run after it (order in `default_builders`).
- Do not edit `authz/dependencies.py` (PRP-21 owns it in W13); everything here works through `require`.
- New test dirs need unique names (`admin_identity_api`); the existing `services/api/tests/audit` and `packages/core/tests/audit` already shadow each other.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/admin/__init__.py
  - services/api/neurosphere_api/admin/identity/**
  - services/api/neurosphere_api/runtime/builders/admin.py
  - services/api/tests/admin_identity_api/**
  - tests/security/authz/test_admin_identity*.py
  - packages/core/neurosphere_core/auth/revocation/**
  - packages/core/tests/auth/revocation/**
  - docs/runbooks/identity-admin.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - services/api/neurosphere_api/authz/dependencies.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - packages/contracts/**
  - packages/core/neurosphere_core/auth/scope/**
  - frontend/**
```

## Implementation blueprint

Parallelization: item 1 [P] (core only). Items 2-4 share the admin package: serial 2 -> 3 -> 4. Item 5 after 3 and 4. Item 6 last.

### Item 1 - Block-until-lifted revocation in core  [P]
- Deliverable: `RevocationEntry.mode` (`issued_before` default, `until_lifted`), checker refuses all tokens for an unlifted `until_lifted` entry, `lift` on both stores (audited through `RevocationAuditor`), `RevocationService.lift`, no TTL on blocking entries.
- Owned files: `packages/core/neurosphere_core/auth/revocation/**`, `packages/core/tests/auth/revocation/test_until_lifted.py` (new).
- Must NOT touch: `auth/scope/**`, services.
- Depends on: none.
- Acceptance criteria: existing `test_ttl.py`, `test_fanout.py`, `test_fail_closed.py`, `test_service.py`, `test_store.py` pass unchanged; until-lifted denies a token issued after revocation and allows it after lift plus TTL; stored entries without `mode` read as `issued_before`.
- Tests: `packages/core/tests/auth/revocation`.
- Pattern references: `checker.py:87-110`, `cosmos_store.py:100-135`, `service.py:159-208`.

### Item 2 - Admin builder and package root
- Deliverable: `neurosphere_api/admin/__init__.py` with `register`; `runtime/builders/admin.py` composing `CosmosPolicyAdminRepository` (container `NS_AUTH_POLICY_CONTAINER`) or a backend override, and `RevocationService` with the shipped authorizer, an auditor adapter onto `AuditRepository` (customer chain `<customer>.identity-admin`), and the published hooks.
- Owned files: `admin/__init__.py`, `runtime/builders/admin.py`, `services/api/tests/admin_identity_api/test_builder.py` (new), Tier-2 lines in `builders/__init__.py` and `status.py`.
- Must NOT touch: `builders/authz.py`, `builders/data.py`.
- Depends on: PRP-37/PRP-65 merged.
- Acceptance criteria: with authz disabled both components report `disabled` with a reason; with authz configured both are `ok`; the revocation service's hooks object is identical to `REVOCATION_HOOKS`.
- Tests: `services/api/tests/admin_identity_api/test_builder.py`.
- Pattern references: `runtime/builders/gateway.py`, `authz.py:230-302`.

### Item 3 - Principal read and policy write routes
- Deliverable: list and detail routes; PUT/DELETE for role assignments, memberships and grants with `If-Match`; scope, self-modification and privileged checks; every write through `run_audited_mutation` on each named domain's chain; denials through the installed denial recorder.
- Owned files: `services/api/neurosphere_api/admin/identity/{router,service,models}.py` (new), `services/api/tests/admin_identity_api/test_policy_routes.py` (new).
- Must NOT touch: authz package, contracts.
- Depends on: item 2.
- Acceptance criteria: the first seven PRP criteria.
- Tests: `services/api/tests/admin_identity_api`.
- Pattern references: `mcp/admin/router.py:96-198`, `customer_control.py`.

### Item 4 - Revocation routes
- Deliverable: POST (revoke with mode), GET (status), DELETE (lift) on `/principals/{principal_id}/revocation`, mapping `RevocationOutcome` to `RevocationStatus`, including `propagation_bound_seconds`.
- Owned files: `services/api/neurosphere_api/admin/identity/revocation.py` (new), `services/api/tests/admin_identity_api/test_revocation_routes.py` (new).
- Depends on: items 1 and 3.
- Acceptance criteria: revocation criteria above; a push closer registered on the hooks is called once per revoke.
- Tests: `services/api/tests/admin_identity_api`.
- Pattern references: `service.py:159-208`, `services/api/tests/realtime` push-closer tests.

### Item 5 - ABAC negative suite for identity admin
- Deliverable: cross-customer, cross-cloud, cross-domain, self-grant, privileged-without-customer-scope, expired-assignment and revoked-actor cases for every new route; denial records asserted.
- Owned files: `tests/security/authz/test_admin_identity.py` (new), `tests/security/authz/test_admin_identity_revocation.py` (new).
- Must NOT touch: shared harness files (`world.py`, `cases.py`) except additive helpers agreed with PRP-48 at rebase.
- Depends on: items 3 and 4.
- Acceptance criteria: every new route has at least one deny case per dimension; no case is skipped.
- Tests: `tests/security/authz`.
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 6 - Integration and close-out
- Deliverable: `routers.py` hook line; route inventories; runbook and `mkdocs.yml` nav; rebase, regenerate `openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`; CHANGELOG; completion note with the operator product check (can an admin grant a second user without Cosmos access?).
- Owned files: Tier-2 lines, `docs/runbooks/identity-admin.md` (new), Tier-3 files.
- Depends on: items 1-5.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/auth services/api/tests/admin_identity_api services/api/tests/authz services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/realtime tests/security/authz services/api/tests/test_openapi_drift.py tests/docs
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: policy documents keep their shape; revocation entries without `mode` read as `issued_before`. Turn off by not granting `policy.manage` (routes deny) or by reverting the `routers.py` hook. An `until_lifted` entry written before a revert would be read as `issued_before` by old code (fails open to TTL behaviour), so lift blocks before reverting and say so in the runbook.

## Live and open gates
None required (in-memory and emulator). An optional live Entra token run of the new routes needs `NS_LIVE_APPROVED=1` and is handed to PRP-64; report OPEN if not run.

## NOT building
Console UI, Entra group sync, Graph lookups of display names, bulk import of assignments, approval workflow for access changes, cross-replica close e2e.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 3 is an ASSUMPTION; row 2 corrects ASSIGNMENTS and needs plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-39-identity-admin | mode, merge_entries, lift on both stores, RevocationService.lift/status; 103 revocation tests pass |
| 2 | merged | prp-39-identity-admin | builders/admin.py (policy_admin, revocation_service; disabled without authz), admin + identity package roots, plane; admin ordered before analytics (test_readiness pin +1 line) |
| 3 | merged | prp-39-identity-admin | list/detail + role/membership/grant PUT/DELETE with If-Match; scope, self, customer-wide checks; multi-chain audit; replica cache invalidation via REVOCATION_HOOKS.invalidate_caches; route inventory pin added |
| 4 | merged | prp-39-identity-admin | POST/GET/DELETE revocation through the composed RevocationService; issued_before and until_lifted proven on the composed app with a fake clock; push closer called once per revoke |
| 5 | merged | prp-39-identity-admin | tests/security/authz/test_admin_identity{,_revocation}.py: 76 cases over the 11 routes (cross-customer, cross-cloud, cross-domain, self, privileged, expired, revoked); harness files untouched |
| 6 | merged | prp-39-identity-admin | done on branch: routers.py hook, route inventory pin, runbook docs/runbooks/identity-admin.md, mkdocs nav. Left for the merge step: rebase, regenerate openapi.json (drift test fails until then), docs/reference, status table, INDEX, changelog fragment, completion note, CI green |

## Completion note (filled at ship)
- Date and PR: 2026-11-15, PR #283
- Deviations (draft from the implementation session): `RevocationStore.lift` takes `lifted_at` as a required keyword (the service supplies its clock) and a lift turns the entry into `issued_before` with `lifted_at`/`lifted_by` (old tokens stay refused). `CachedRevocationChecker` now takes the narrower `RevocationReader` (get only) so existing get-only fakes still type-check. Added `RevocationService.status`, `.store`, `.propagation_bound_seconds` and `RevocationHookRegistry.invalidate_caches` (cache invalidators only; used after a lift and after every policy write so the writing replica applies the new scope at once). The registry cannot carry a reason on `disabled`, so "disabled with a reason" is `disabled` plus a logged reason code. `POLICY_ADMIN_REPOSITORY` / `REVOCATION_SERVICE` keys are declared in `builders/admin.py` (the documented "further keys in its own module" route), not in `builders/__init__.py`. The admin builder sits before `analytics` (so the analytics "registered last" pin holds); `services/api/tests/runtime_api/test_readiness.py` (outside Ownership) gained the "admin" line in its two order pins. Resource ownership for grants comes from a `ResourceDomainResolver` (default: catalog `get_entity` under the actor's scope; backend override `resource_domains`); a resource the actor cannot see is refused as `target_out_of_scope`. GET routes of revocation use the same authorizer as revoke. The plain `issued_before` Cosmos body omits `mode` so pre-PRP-39 code still reads it. `RevocationRequest.mode` is required by the PRP-37 contract, so the "default issued_before" of Clarification 4 applies to the core service only.
- Descoped items: none. Reviewer follow-ups not fixed in this PR: (a) `admin/identity/service.py` `list_principals` fetches at most MAX_LIST_LIMIT documents then applies the cursor in memory, so principals beyond the cap are unreachable by paging (sets truncated=true only); push cursor and ordering into `PolicyAdminRepository.list_principals`. (b) `_write` puts the full PrincipalPolicy dump in before/after audit subjects on every named domain chain, so domain D readers see entries for domains they do not manage; filter to named domains or store a digest. (c) `cosmos_store.py` keeps `lifted_at`/`lifted_by` on a lifted entry; pre-PRP-39 `RevocationEntry` is extra=forbid, so after a rollback old code returns 503 (revocation_entry_invalid) for that principal until retention expires; the runbook step "lift blocks before reverting" does not cover this (drop the lift fields from the stored body or document it). (d) `_write` reimplements `run_audited_mutation` for several chains; a multi-chain helper in core audit would keep one implementation. (e) `remove_role`/`remove_grant` on a principal with no policy document return 409 stale (with If-Match) instead of 404. The `builders/admin.py` docstring ("runs LAST") was fixed in the close-out commit.
- OPEN gates: optional live Entra token run of the new routes (PRP-64, needs `NS_LIVE_APPROVED=1`), not run. Compose/emulator checks not run (PRP-21 holds the stack in W13); Cosmos behaviour of `lift` and of a body without `ttl` is covered by fakes only.
- Env vars for the operator: none new.
- Follow-up issues: #284 (problem.py echoes the path in `instance`), #285 (reserve the `identity-admin` domain name), PRP-53 console page; reviewer follow-ups (a) to (e) above are not yet filed as issues.
- Product check (can an operator use it without editing files): partly. After the one-time `make grant-operator`, an admin can grant a second user, change roles, memberships and grants and revoke or block a user through the API with no Cosmos access; there is no console page until PRP-53.
