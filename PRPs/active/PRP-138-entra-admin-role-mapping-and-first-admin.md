---
name: PRP-138-entra-admin-role-mapping-and-first-admin
status: active
priority: P0
order: 138
review: required
created: 2026-11-17
started: 2026-11-18
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 6
ns: NS-08, NS-10
depends_on: []
wave: W18b
branch: prp-138-entra-admin-role-mapping
allow_parallel: true
issues: []
---

# PRP-138: Entra admin role mapping and first admin (app roles and groups to NeuroSphere roles)

## Goal
Let an Entra identity be a NeuroSphere administrator without a developer script. Today authority comes only from documents in the Cosmos policy store, and the only way to create the first admin is a script that writes to Cosmos directly. This PRP adds one deployment-configured mapping from Entra app role values (the `roles` claim, the default path) and, optionally, Entra group object ids (the `groups` claim) to NeuroSphere roles. The mapping is applied at request time inside scope derivation, only for a token of the exact tenant and audience the mapping names. A mapped administrator receives the same scoped `admin` role every other administrator has, on the customer control domain and on every registered domain, with an expiry equal to the token's expiry. Each use is audited. The Admin console gains a read-only view of the effective mapping, a "your access" view that shows which roles came from Entra and which from the policy store, and a 403 state that names the missing permission. It is for the owner who deployed NeuroSphere, signed in with Entra and got "Access denied" on every Admin page (decision D20, `docs/DECISIONS-LOG.md:18`). It runs in W18b and merges first in that wave, before PRP-139 and PRP-140.

Out of scope: writing roles into the policy store from token claims (rejected, clarification 1); calling Microsoft Graph to resolve group overage (follow-up; overage fails closed here); generic OIDC issuers (PRP-93 builds on this later, clarification 12); service principals receiving mapped roles; editing the mapping from inside the product (it is deployment configuration); any new role or permission; content capture approval (administrators do not hold it, GD-1); navigation changes (PRP-140); hosted connector enablement, seeding and empty states (PRP-139); Helm and `infra/appservice` parameter wiring (the setting is documented for them; only the hosted demo profile is wired, in item 9).

## Why
- The owner asked for it after the 0.1.0-rc.4 deploy: "administrators come from Entra" is decision D20 (`docs/DECISIONS-LOG.md:18`), which names this PRP.
- Token roles are never authority today. The deriver's own description says "Entra role, group and scope claims are never authority (C5)" (`packages/core/neurosphere_core/auth/scope/derivation.py:6-7`) and it builds roles only from `policy.role_assignments` (`derivation.py:275-290`). The validator already parses both claims into `VerifiedClaims` (`packages/core/neurosphere_core/auth/jwt/validator.py:210-212`, `auth/jwt/claims.py:37-39`) and nothing reads them.
- The frontend uses the ID token `roles` claim for display and navigation only (`frontend/src/auth/roles.ts:4-6`, `frontend/src/auth/useRoles.ts:11-17`, `frontend/src/app/navigation.ts:20-23,42`). So a user with the Entra `admin` app role sees the Admin entries and every API call answers 403. The grant script says exactly that: "Entra app roles only drive navigation display; authority comes from the policy store. Without this grant a real sign-in shows the pages but every API call answers 403" (`scripts/sandbox/sbx_grant_operator.py:5-6`).
- Admin routes need a permission on the reserved customer control domain: `customer_control_domain_id` and `permits_customer_wide` (`packages/core/neurosphere_core/auth/scope/permissions.py:219-238`), used by `require_deployment_admin` (`services/api/neurosphere_api/authz/deployment_scope.py:90-118`), which `require_customer_control` delegates to (`services/api/neurosphere_api/actions/customer_control.py:54-61`). A miss is 403 `customer_scope_required` (`deployment_scope.py:60-61,111-114`).
- The first admin can only be created by a script: local mode writes to the emulator; hosted mode needs the operator's own credential on the Cosmos endpoint and reads the pseudonym key from Key Vault (`scripts/sandbox/sbx_grant_operator.py:20-23`), behind a temporary data role (`scripts/gates/hosted_demo.py:1538`, `seed-access`). Privileged roles carry a 30 day expiry (`sbx_grant_operator.py:55`, `PRIVILEGED_TTL`), renewed only by re-running the script (`:17-18`), so that admin lapses silently.
- A fresh deployment has no policy head, and the deriver loads no principal document without one (`derivation.py:191-199`). The identity admin API cannot bootstrap either: every write needs `policy.manage` first (`services/api/neurosphere_api/admin/identity/router.py:1-12`) and privileged assignments need customer-wide authority (`admin/identity/service.py:19-21`).
- There is no customer-wide role form. The policy model needs at least one domain id per assignment (`packages/core/neurosphere_core/auth/scope/policy.py:67-78`) and the contract says "At least one; there is no tenant-wide form" (`packages/contracts/python/neurosphere_contracts/scope/v1/identity_scope.py:70-75`) and "There is deliberately no wildcard, all-domains or bypass field" (`identity_scope.py:92`). "All domains" therefore has to be an explicit list built by the server.
- The 403 the owner saw says nothing useful: the API returns "insufficient scope for this operation" for every permission miss (`services/api/neurosphere_api/authz/dependencies.py:430`) and the console shows "Access denied ... contact your administrator" (`frontend/src/features/admin/shared/strings.ts:15-17`, `AdminStates.tsx:23-36`).
- The Entra app registration already has the five app role values from the local setup script (`scripts/gates/p29_entra_local.py:14-16`), which also states "App roles only drive navigation display" (`p29_entra_local.py:23-24`). The building block exists; the server does not use it.

## Acceptance criteria
- [ ] Given a deployment with a mapping `{claim: roles, value: admin, role: admin, domains: all, customer_control: true}` bound to its tenant and audience, an empty policy store (no policy head, no principal document) and an empty domain registry, When a user whose access token carries `roles: ["admin"]` calls `GET /api/v1/admin/system/status`, Then the answer is 200, no script ran and nothing was written to the policy store.
- [ ] Given the same mapping and three registered domains, Then the derived scope holds one `admin` assignment whose `domain_ids` are exactly the control domain plus the three active domains, with `expires_at` equal to the token's `exp`; When a fourth domain is registered, Then it is in the scope within the directory cache time (30 s default) with no configuration change; a retired domain drops out the same way.
- [ ] Given no mapping configured (the default), Then a token carrying `roles: ["admin"]` or any `groups` value changes nothing: the derived scope is byte-for-byte what it is today, an admin route answers 403 and a denial record is written. Every existing JWT, scope and authz suite passes unchanged.
- [ ] Negative, each with a test: a role value not in the mapping; an absent `roles` claim; a token of another tenant or another audience than the mapping names (refused or unmapped, never mapped); a `dev` issuer token outside `NS_ENV=local`; an app-only token (`identity_type == "app"` or no `scp` claim); a mapping whose `tenant_id` or `audience` differs from `NS_AUTH_TENANT_ID` / `NS_AUTH_AUDIENCES` (the `authz` component fails at startup with `role_mapping_binding_mismatch`, protected routes answer 503); malformed mapping JSON, an unknown role name, a duplicate entry id, one claim value mapped to two roles, a `groups` value that is not a GUID, a domain id of another cloud or customer (startup `role_mapping_invalid`).
- [ ] Groups: given a `groups` entry and a token whose `groups` claim holds that object id, the role is applied; given a token with a group overage indicator (`_claim_names` with a `groups` member, or `hasgroups`), Then no group entry is applied (app role entries still are), the counter `groups_overage` increments, `GET /api/v1/me/access` reports `groups_overage: true`, and no Microsoft Graph call is made.
- [ ] No bypass: the mapped admin holds exactly the `admin` permission set (`permissions.py:108-118`) and nothing else. Tests show the mapped admin gets 403 on a route needing `action.approve` and on audit read (`audit.read`), cannot change its own stored policy document (`self_modification_forbidden`), and passes every admin route only through the same `require` and `require_deployment_admin` dependencies as a stored admin. No code path checks the claim instead of the scope.
- [ ] Time bound and revocable: a mapped assignment's `expires_at` is the token `exp`, so it never outlives the token; after the app role or group is removed in Entra, the next token maps nothing (access ends within one token lifetime); an administrator can end it at once with the existing principal revocation, which the deriver checks before any mapping (`derivation.py:183`).
- [ ] Audit: the first request of each token that results in a mapped role appends one `identity.claim_role_applied` record (actor pseudonym, scope hash, mapping entry ids, claim kind, role, domain count, token issued-at and expiry). It carries no token, no claim list, no group object id and no name. When that audit write fails the request is refused with 503 `audit_write_failed`. Logs carry reason codes and counts only.
- [ ] `GET /api/v1/admin/identity/role-mapping` (needs `policy.manage` on the control domain) returns the effective mapping: bound tenant, audience and cloud, each entry's id, claim kind, value, role, domain mode and control flag, and whether the mapping is active. `GET /api/v1/me/access` (any authenticated caller, own data only) returns the caller's roles with `source` (`entra_app_role`, `entra_group`, `policy_store`), mapping entry id, domain count, `customer_control`, `expires_at`, plus `mapping_configured` and `groups_overage`.
- [ ] Admin console: the Identity area shows a read-only "Entra role mapping" panel and a "Your access" panel; the forbidden state on every admin page names the missing permission and whether it is needed on the whole deployment, and links to "Your access". No control edits the mapping.
- [ ] Government and Commercial never cross: the mapping is one object per deployment; a token of the other cloud is already refused (`derivation.py:168-169`); tests assert a Commercial mapping never applies to a Government token and the other way round; the operator script refuses to run when `az cloud show` does not match `--cloud`.
- [ ] Operator path: `scripts/gates/entra_admin_mapping.py plan` prints the app role and assignment diff with Graph reads only; `apply` needs `NS_LIVE_APPROVED=1` and `--approve entra-app`, adds the app role value if missing, assigns one group or user to it, and prints the mapping parameter; nothing is changed silently and a second run sends nothing.
- [ ] Real-stack test: against the compose emulators with an empty policy container, a stand-in token carrying the mapped role opens `GET /api/v1/admin/system/status`, creates a domain and then reads `GET /api/v1/me/domains` with that domain present.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend lint, typecheck, test and e2e, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated; the runbook explains configuring the mapping, the Entra step and revocation; the live gate is recorded OPEN until an operator runs it.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Where the mapping is applied | (a) At request time in scope derivation; (b) written into the policy store at sign-in | (a). The API never sees a sign-in, only bearer tokens, so (b) would mean a policy write on a request path made by a caller who has no authority yet, a `PolicyHead` bump that invalidates every cached principal (`policy.py:7-8`), and a stored grant that outlives the Entra role until something removes it. With (a) nothing is stored, the grant ends with the token, and first-admin bootstrap needs no write. Cost: a claim-mapped admin with no stored document does not appear in the principals list; the panel says so and the audit record is the trail |
| 2 | How "all domains" is represented | (a) A wildcard or customer-wide flag in the scope contract; (b) an explicit list built by the server at derivation | (b). No customer-wide form exists and the contract forbids one (`identity_scope.py:70-75,92`; `permissions.py:3-5`). A mapping entry says `domains: "all"`; the deriver expands it to the control domain (when `customer_control` is true) plus every active domain in the domain registry (`packages/core/neurosphere_core/admin/platform/domains.py:84-93`), read through a 30 s cache. Future domains are covered when they are registered. The scope contract, `permits` and `permits_customer_wide` are unchanged |
| 3 | What "all domains" covers | Registry domains only; also domains that exist only in data | ASSUMPTION: active domains in the domain registry only. A domain that exists in catalog data but was never registered is not covered. Alternative: also union the catalog's domain entities (a second store on the request path). Hosted starts empty (PRP-139), so registered domains are the whole set there |
| 4 | More domains than a role can list | Truncate; deny | ASSUMPTION: the contract caps `domain_ids` at 1024 and the registry list at 1000 (`admin/store.py:65`). At 1000 or more active domains an `all` entry denies with 503 `role_mapping_domain_overflow` instead of granting a silent partial scope ("nothing returns a partial or empty scope on error", `derivation.py:9`). Alternative: grant the control domain only |
| 5 | Which roles can be mapped | `admin` only; all five | ASSUMPTION: all five existing roles (`viewer`, `analyst`, `domain_steward`, `admin`, `security_auditor`), from a closed constant `MAPPABLE_ROLES`. A role added later (for example `interaction_investigator`, GD-2) is not mappable until someone adds it on purpose. One claim value maps to exactly one role; a configuration mapping one value to two roles is refused at startup. Alternative: `admin` only |
| 6 | Capture approval (GD-1, GD-20) | n/a | Decided by the owner (D19, `docs/DECISIONS-LOG.md:17`; `PRPs/backlog/PRP-99-governance-contracts-a.md:59,283,307`): administrators do not approve content capture; a second steward holding `action.approve` does. The mapped admin gets the unchanged `admin` permission set, which has no `action.approve` (`permissions.py:108-118`, "it does not inherit Steward approval", `permissions.py:20`). A test asserts it |
| 7 | Time bound (C7) | Fixed TTL in config; token expiry | Token expiry. `PRIVILEGED_ROLES` must carry `expires_at` (`permissions.py:143`, `policy.py:74-78`); a mapped assignment's `expires_at` is the token `exp`, for every mapped role, privileged or not. The derived scope already expires no later than the token (`derivation.py:265-268`). Nothing renews it except a new token from Entra |
| 8 | Revocation | n/a | Losing the Entra app role or group ends access when the current access token expires (at most one token lifetime; the lifetime is set by the tenant. UNVERIFIED: the Entra default of about one hour). Immediate removal uses the existing principal revocation, checked before mapping (`derivation.py:183`). The runbook states both |
| 9 | Binding to tenant and audience | Implied by the deployment; explicit in the mapping | Explicit. The mapping object carries `tenant_id` and `audience`; both must equal the deployment's `NS_AUTH_TENANT_ID` and one of `NS_AUTH_AUDIENCES` or the `authz` component fails closed. At request time the mapping applies only when `issuer_kind == "entra"`, and the token's tenant and audience equal the mapping's. A mapping copied to another deployment therefore grants nothing |
| 10 | Service principals | Map them too; users only | ASSUMPTION: users only. A token with `identity_type == "app"`, or with no `scp` claim, is never mapped (UNVERIFIED: that app-only Entra tokens carry no `scp`; the `idtyp` claim is optional, so both checks are used). The operator script creates the app role with allowed member type `User` only. Alternative: allow applications with a separate entry flag |
| 11 | Group overage | Call Graph; fail closed | Fail closed, no Graph call in this PRP. Follow-up issue: resolve overage through Graph with a managed identity. App roles are the default path because Microsoft's guidance prefers them and they have no overage |
| 12 | Consistency with PRP-93 | n/a | PRP-93 requires that an OIDC token carrying `roles: ["Admin"]` with no policy assignment gets 403 and never changes the scope (`PRPs/backlog/PRP-93-generic-oidc-identity.md:40`). This PRP keeps that true: the mapping module accepts `issuer_kind == "entra"` only (constant `MAPPED_ISSUER_KINDS`), and with no mapping configured no claim is read at all. This PRP adds the Entra form of the same injection test now. PRP-93's evidence line "no consumer of `VerifiedClaims.roles`" (`PRP-93:33`) becomes "one consumer, Entra only, behind an explicit mapping"; PRP-93 must leave `oidc` out of `MAPPED_ISSUER_KINDS`. A later OIDC mapping would be a new owner decision that reuses `ClaimRoleMapping` with PRP-93's claim map. PRP-93's "NOT building: group-to-role synchronisation ... into the policy store" (`PRP-93:245`) matches clarification 1 |
| 13 | Audit granularity | Every request; once per token | Once per token per replica: a bounded cache keyed by principal, token issued-at and mapping entry ids. A restart or a second replica may write a duplicate record; that is accepted. Audit write failure denies (ASSUMPTION; alternative: allow safe methods and log a warning, as ordinary denials do, `dependencies.py:419-428`) |
| 14 | Who may see their own access | `data.read` holders (as `/me/domains`, `me/router.py:51`); any authenticated caller | ASSUMPTION: any authenticated caller, through a new fifth route category (exact path allowlist plus a marker, GET only), because the person who needs the answer is the one who has no role yet. It returns only the caller's own roles. Alternative: gate on `data.read` and leave a roleless user with the 403 text only |
| 15 | Naming the permission in a 403 | New problem field; detail text | Detail text only: "this operation needs `<permission>`" (and the existing deployment wording, `deployment_scope.py:111-114`). No contract change. The reason codes stay as they are |
| 16 | Hosted parameter | Edit hosted Bicep in the main PR; a later item | A later item (9), done as a second small PR after PRP-139 has merged, because PRP-139 owns the hosted Bicep in this wave and PRP-138 merges first. See the Ownership note |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/auth/scope/derivation.py:1-20,122-204,255-329` - the deriver, its rules, where roles are built.
- `packages/core/neurosphere_core/auth/scope/permissions.py:1-40,108-118,143-149,219-238` - role table, admin set, privileged roles, control domain.
- `packages/core/neurosphere_core/auth/scope/policy.py:67-78` - `PolicyRoleAssignment` and the time-bound rule.
- `packages/core/neurosphere_core/auth/jwt/claims.py`, `validator.py:181-215,247-257` - `VerifiedClaims`, where `roles` and `groups` are read.
- `packages/core/neurosphere_core/admin/platform/domains.py:1-20,84-110` - `DomainRegistry`.
- `services/api/neurosphere_api/runtime/builders/authz.py:1-31,268-306,350-397` - `_deriver`, `_authz`, `build`, the lazily resolved `AuditDenialRecorder`.
- `services/api/neurosphere_api/runtime/builders/__init__.py:372-406` and `admin_platform.py:178` - builder order (authz runs before admin_platform) and `DOMAIN_REGISTRY`.
- `services/api/neurosphere_api/authz/dependencies.py:114-190,395-430`, `authz/routes.py:1-22,84-105`, `authz/deployment_scope.py` - derivation per request, denial text, route categories.
- `services/api/neurosphere_api/me/router.py`, `admin/identity/router.py:1-60`, `admin/identity/service.py:1-31`, `admin/system/router.py:1-11`.
- `frontend/src/features/admin/shared/AdminStates.tsx`, `strings.ts`, `areas.ts`, `frontend/src/features/admin/identity/PrincipalsPage.tsx`, `hooks.ts`, `types.ts`, `frontend/tests/mock-api/features/admin-core.ts`.
- `tests/security/authz/test_deployment_scope.py`, `test_privileged_roles.py`, `test_admin_identity.py`, `world.py`, `support.py`.
- `tests/integration/real_stack/conftest.py`, `test_operator_grant.py`.
- `scripts/gates/p29_entra_local.py` (app role plan and approval pattern), `scripts/gates/hosted_demo.py:8-20,1447-1480` (`entra-redirect`), `infra/demo/main.bicep:56-59,240-270`.
- `PRPs/shipped/PRP-39-identity-admin-api-and-revocation.md`, `PRP-53-admin-console-identity-status-and-audit.md`, `PRP-65-admin-permissions-policy-repository-and-config-store.md`, `PRPs/backlog/PRP-93-generic-oidc-identity.md:33,40`.

### Interfaces consumed
- Shipped: `ScopeDeriver`, `ScopeDerivation`, `ScopeDerivationConfig`, `VerifiedClaims`, `JwtValidator`, `TtlCache`, `Role`, `role_permissions`, `customer_control_domain_id`, `DomainRegistry`, `AuditRepository`, `AuditContext`, `build_allowed`, `domain_audit_chain_id`, `require`, `require_deployment_admin`, `current_derivation`, `current_scope`, `BuildContext.maybe_shared`, `AuthSettings`, frontend `QueryErrorState`, `ErrorState`, the identity feature hooks.
- Microsoft Learn (verified): app roles assigned to users or groups arrive in the `roles` claim of the API access token; an app must handle an absent claim, no assignment and several values; app roles are preferred over groups for app authorization; assigning a group to an app role needs at least Entra ID P1; the `groups` claim holds object ids; over 200 groups in a JWT, `groups` is omitted and an overage indicator is emitted, and the app must not rely on the claim values; "Groups assigned to the application" limits the claim to assigned groups, direct membership only. Sources: https://learn.microsoft.com/security/zero-trust/develop/configure-tokens-group-claims-app-roles and https://learn.microsoft.com/entra/architecture/customize-tokens
- No unshipped dependency.

### Interfaces provided
- Core `neurosphere_core.auth.scope.claim_mapping` (new): `ClaimRoleMapping` (frozen; `tenant_id`, `audience`, `entries`), `ClaimRoleEntry` (`id`, `claim`: `roles|groups`, `value`, `role`, `domains`: `"all"` or a list of canonical domain ids, `customer_control: bool`), `parse_claim_role_mapping(raw_json) -> ClaimRoleMapping | None`, `MAPPABLE_ROLES`, `MAPPED_ISSUER_KINDS`, `ClaimGrant` (`entry_id`, `claim`, `role`, `domain_ids`, `customer_control`, `expires_at`), `DomainDirectory` protocol (`async active_domain_ids(customer_id) -> tuple[str, ...]`), `ClaimGrantObserver` protocol (`async on_claim_grants(scope, grants, issued_at, expires_at)`), `matching_entries(mapping, claims, *, allow_dev_issuer)`.
- `VerifiedClaims.groups_overage: bool = False` (additive).
- `ScopeDerivation.claim_grants: tuple[ClaimGrant, ...] = ()` (additive); mapped assignment ids are `entra.<entry id>`.
- `ScopeDeriver(...)` gains keyword-only `claim_mapping`, `domain_directory`, `claim_grant_observer`, `allow_dev_issuer`, all defaulting to off; the worker deriver (`services/workers/neurosphere_workers/runtime/identity.py:179-184`) passes none and is unchanged.
- Setting `NS_AUTH_ROLE_MAPPINGS` (JSON object, not a secret): `{"tenant_id": "<guid>", "audience": "<api app id>", "entries": [{"id": "ns-admins", "claim": "roles", "value": "admin", "role": "admin", "domains": "all", "customer_control": true}]}`. At most 32 entries.
- API: `GET /api/v1/me/access`; `GET /api/v1/admin/identity/role-mapping`. Route category `AUTHENTICATED_SELF_PATHS` with `require_authenticated()`. Audit operation `identity.claim_role_applied`. Readiness reasons `role_mapping_invalid`, `role_mapping_binding_mismatch`. Shared key `CLAIM_ROLE_MAPPING` on the build context.
- Operator script `scripts/gates/entra_admin_mapping.py` (`plan`, `apply`, `verify`).
- Hosted parameter `entraRoleMappings` (item 9).
- Consumers: PRP-139 (the hosted environment's first admin registers domains and connectors through the console), PRP-140 (no interface; it must not key navigation on anything new here), PRP-93 (clarification 12), PRP-82 and PRP-136 hosted smoke runs.

### Patterns to match
- Late-bound dependency resolved per call because a later builder publishes it: `AuditDenialRecorder(lambda: ctx.maybe_shared(AUDIT_REPOSITORY))` in `runtime/builders/authz.py` (`_denial_recorder`).
- Deny on any failure inside derivation: `derivation.py:216-225` (`_guarded`) and the `policy_document_invalid` path.
- Deployment-scoped read route: `admin/system/router.py:81-83` (`AdminScope`).
- Marker-based route category: `ROLE_GATED_PATHS` and `require_role` (`authz/routes.py:98-104`, `authz/dependencies.py:307-320`).
- Startup refusal with a reason code: `_tenant`, `_authenticator` (`runtime/builders/authz.py:259-265,319-334`).
- Operator script, dry-run by default, `--apply` behind `NS_LIVE_APPROVED=1`: `scripts/gates/p29_entra_local.py:1-5,190-240,288-306`.
- Admin console panel with query states: `frontend/src/features/admin/identity/PrincipalsPage.tsx` and `shared/AdminStates.tsx`.

### Gotchas
- The audit metadata guard rejects GUID-shaped person ids (see the note in `AuditDenialRecorder`, `runtime/builders/authz.py`). Record the mapping entry id, never the group object id; the entry id pattern is `^[a-z][a-z0-9-]{0,62}$`.
- The control domain's audit chain: build it with `domain_audit_chain_id(customer, control_domain)` and prove in a test that `customer-control` encodes. UNVERIFIED until that test runs; if it does not encode, stop and ask, do not pick another chain.
- `configure_authz` compares cloud and tenant only when the scope source is a `ScopeDeriver` (`authz/state.py:104-110`); a wrapper would skip that check. Do not wrap the deriver; add the behaviour inside it.
- `authz` builds before `admin_platform` (`runtime/builders/__init__.py:391-406`). The domain directory and the audit repository must be resolved per call. When the registry is not published and an `all` entry matches, derivation raises `DependencyTransientError` (`domain_directory_unavailable`); it never falls back to the control domain alone.
- The deriver's existing docstring claims role claims are never authority (`derivation.py:6-7`); rewrite it to state the one exception and its conditions. Leave `policy.py:10` (still true for the policy store).
- Mapped assignments skip the `domain_memberships` clip (`derivation.py:276-282`) because the mapping is the membership; they still pass `_owned` (`derivation.py:249-253`), so an explicit domain of another cloud or customer is dropped even if startup validation missed it.
- The scope cache key and `scope_hash` already cover roles; do not add a second hash input. `policy_version` stays `none` when there is no policy head.
- The string "insufficient scope for this operation" also appears in `services/api/neurosphere_api/admin/identity/service.py` and `audit/access.py`; grep tests for it before changing the text, and change only `authz/dependencies.py`.
- The frontend reads display roles from the ID token, the API from the access token. With one app registration for both (`infra/demo/main.bicep:266-268` sets the audience to the client id) they agree; the runbook says what happens when they differ.
- Anyone who can assign the app role in Entra (app owners, Application Administrator, Cloud Application Administrator) can now create a NeuroSphere admin. The runbook and the mapping panel state this.
- Assigning a group to an app role needs Entra ID P1; on a free tenant the script must report that and offer `--assign-user`.
- Do not regenerate visual baselines: `frontend/tests/e2e/visual/__screenshots__/**` is PRP-140's in this wave. If a visual test covers the Identity page or a forbidden state, say so in the completion note so PRP-140 regenerates after rebase.
- `.env.example` cannot be edited by an agent; list `NS_AUTH_ROLE_MAPPINGS` under "Env vars for the operator".
- Test packages need unique directory names (`packages/core/tests/auth_claim_mapping`, `services/api/tests/authz_claim_mapping`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/auth/scope/claim_mapping.py
  - packages/core/neurosphere_core/auth/scope/derivation.py
  - packages/core/neurosphere_core/auth/scope/__init__.py
  - packages/core/neurosphere_core/auth/jwt/claims.py
  - packages/core/neurosphere_core/auth/jwt/validator.py
  - packages/core/tests/auth_claim_mapping/**
  - services/api/neurosphere_api/authz/claim_audit.py
  - services/api/neurosphere_api/authz/__init__.py
  - services/api/neurosphere_api/authz/deployment_scope.py
  - services/api/neurosphere_api/me/**
  - services/api/neurosphere_api/admin/identity/role_mapping.py
  - services/api/neurosphere_api/admin/identity/router.py
  - services/api/tests/authz_claim_mapping/**
  - tests/security/authz/test_claim_role_mapping.py
  - tests/integration/real_stack/test_entra_role_mapping.py
  - frontend/src/features/admin/identity/**
  - frontend/src/features/admin/shared/AdminStates.tsx
  - frontend/src/features/admin/shared/strings.ts
  - frontend/src/features/admin/shared/shared.test.tsx
  - frontend/tests/mock-api/features/role-mapping.ts
  - scripts/gates/entra_admin_mapping.py
  - tests/unit/gates/test_entra_admin_mapping.py
  - docs/runbooks/entra-role-mapping.md
  - docs/runbooks/identity-admin.md
tier1:
  - services/api/neurosphere_api/runtime/builders/authz.py
  - services/api/neurosphere_api/authz/dependencies.py
  - services/api/neurosphere_api/authz/routes.py
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - mkdocs.yml
deferred_after_prp_139:
  - infra/demo/main.bicep
  - infra/demo/main.bicepparam
  - scripts/gates/hosted_demo.py
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/neurosphere_core/auth/scope/policy.py
  - packages/core/neurosphere_core/auth/scope/policy_admin.py
  - services/workers/**
  - services/api/neurosphere_api/admin/identity/service.py
  - frontend/src/app/**
  - frontend/src/features/admin/routes.tsx
  - frontend/src/features/admin/shared/areas.ts
  - frontend/tests/e2e/visual/__screenshots__/**
  - infra/demo/modules/**
  - infra/helm/**
  - infra/appservice/**
  - scripts/gates/hosted_demo_seed.py
  - scripts/sandbox/**
```
Tier-1 in W18b: `runtime/builders/authz.py` (two wiring edits in `_deriver` and one startup check), `authz/dependencies.py` (the denial detail text and `require_authenticated`), and `authz/routes.py` (the fifth category is a logic change in `_entry`, not only an allowlist line). PRP-139 and PRP-140 do not need those files; their Tier-2 line additions to `authz/routes.py` allowlists still rebase cleanly.

Hosted Bicep: `infra/demo/main.bicep` and `scripts/gates/hosted_demo.py` are likely PRP-139's in this wave, so they are not in `owns` or `tier1`. They are listed under `deferred_after_prp_139` and edited only in item 9, as a second small pull request after PRP-139 has merged. The usual serial-after tag is deliberately not written on item 9: `scripts/prp_execution_plan.py` orders a wave by that tag and would place this PRP after PRP-139, while the wave needs PRP-138 merged first. The orchestrator may instead give PRP-139 the two-line edit (see item 9); either way the parameter name and value are fixed here.

The Admin console change adds no route and no navigation entry: both panels live inside the existing Identity page, so `features/admin/routes.tsx`, `shared/areas.ts` and `frontend/src/app/**` (PRP-140) are untouched. `shared/AdminStates.tsx` and `shared/strings.ts` are edited for the forbidden state; if PRP-139's empty-state work also needs them, PRP-139 rebases on this PRP.

## Implementation blueprint

Parallelization: items 1, 2, 6 and 8 start together (four lanes, no common file). Item 3 needs 1 and 2. Item 4 needs 3. Item 5 needs 4. Item 7 needs 5. Item 10 closes the first pull request. Item 9 is a second pull request after PRP-139 has merged.

### Item 1 - Core mapping model and parser  [P]
- Deliverable: `claim_mapping.py` with the models, `parse_claim_role_mapping` (strict: unknown keys refused, at most 32 entries, entry id pattern, role in `MAPPABLE_ROLES`, `groups` values must be GUIDs, `roles` values `^[A-Za-z0-9._-]{1,120}$`, no duplicate ids, no claim value mapped to two roles, explicit domain ids must be canonical domain ids), `matching_entries` (returns nothing unless the issuer kind is in `MAPPED_ISSUER_KINDS` or dev is allowed, tenant and audience equal the mapping, the token is a delegated user token, and for `groups` entries `groups_overage` is false), and the two protocols. Empty or unset input returns `None` (mapping off).
- Owned files: `packages/core/neurosphere_core/auth/scope/claim_mapping.py`, `packages/core/tests/auth_claim_mapping/test_parse.py`, `test_matching.py`.
- Must NOT touch: `permissions.py`, `policy.py`, contracts.
- Depends on: nothing.
- Acceptance criteria: every refusal in the negative criterion has a parser or matcher test; matching is exact string equality (no case folding of role values, lowercase comparison for GUIDs); several matching values give the union; the module logs nothing.
- Tests: the two files above.
- Pattern references: `auth/scope/policy.py:56-78` (frozen models), `auth/jwt/config.py:99-113` (explicit audiences).

### Item 2 - Group overage flag on verified claims  [P]
- Deliverable: `VerifiedClaims.groups_overage: bool = False`; the validator sets it when the payload has `hasgroups` true or a `_claim_names` object with a `groups` member, and then leaves `groups` empty even if the token also carries values. Any other shape of those two claims is ignored, not an error.
- Owned files: `auth/jwt/claims.py`, `auth/jwt/validator.py`, `packages/core/tests/auth_claim_mapping/test_overage.py`.
- Must NOT touch: `auth/jwt/config.py`, `jwks.py`, `dev_issuer.py`.
- Depends on: nothing.
- Acceptance criteria: existing `packages/core/tests/auth/jwt` suites pass unchanged; tokens with each overage shape give `groups_overage` true and `groups == ()`; a normal token is unchanged.
- Tests: `test_overage.py`.
- Pattern references: `validator.py:247-257` (`_str_list`), `validator.py:269-273` (`_identity_type`).

### Item 3 - Scope derivation applies the mapping
- Deliverable: `ScopeDeriver` accepts the four keyword arguments. After the revocation check and the policy load, `_build` adds one role per matched role: `domain_ids` from the entry (explicit list, or the directory's active domains through a `TtlCache` keyed by customer with the policy cache TTL), plus the control domain when `customer_control` is true, filtered by `_owned`, capped per clarification 4; `expires_at` is the token `exp`; assignment id `entra.<entry id>`; `allowed_domains` gains the domains when the role confers `data.read`. `ScopeDerivation.claim_grants` lists what was applied. When grants are non-empty and an observer is set, it is awaited before the derivation is returned and its failure is `DependencyTransientError` (`audit_write_failed`). With no mapping the code path is not entered. Docstring rewritten. `auth/scope/__init__.py` exports the new names.
- Owned files: `auth/scope/derivation.py`, `auth/scope/__init__.py`, `packages/core/tests/auth_claim_mapping/test_derivation_mapping.py`.
- Must NOT touch: `cache.py`, `hashing.py`, `permissions.py`.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 1 to 3, 5 and 7 at the core level; a stored assignment and a mapped one for the same role both appear and the scope validates against the contract; a revoked principal is refused before mapping; a directory error, a missing directory and an overflow each deny with their reason code; existing `packages/core/tests/auth/scope` suites pass unchanged; derived scope with mapping off is identical to today's for a fixed input (golden comparison).
- Tests: `test_derivation_mapping.py` (in-memory policy repository from `packages/core/tests/auth/scope/scope_helpers.py`, a fake directory, an injected clock).
- Pattern references: `derivation.py:255-303`, `derivation.py:216-225`.

### Item 4 - API composition, audit observer and denial text
- Deliverable: `AuthSettings.role_mappings: str | None` (`NS_AUTH_ROLE_MAPPINGS`); in `_deriver`, parse it (`role_mapping_invalid`), check the binding against the tenant and `auth.audiences` (`role_mapping_binding_mismatch`), publish `CLAIM_ROLE_MAPPING`, and pass the mapping, a directory that resolves `DOMAIN_REGISTRY` per call, the observer and `allow_dev_issuer = (env == "local")`. `authz/claim_audit.py`: `ClaimGrantAuditObserver` with the once-per-token cache (10 000 keys) appending `identity.claim_role_applied` through the lazily resolved audit repository on the control domain's chain, plus counters (applied, overage, unmatched values count; no ids in labels). `authz/dependencies.py`: denial detail names the permission; `require_authenticated()` with `AUTHENTICATED_MARKER`. `authz/routes.py`: `AUTHENTICATED_SELF_PATHS = {"/api/v1/me/access"}`, compliant only for GET with the marker. `deployment_scope.py`: detail text aligned.
- Owned files: `runtime/builders/authz.py`, `runtime/settings.py` (new field), `runtime/builders/__init__.py` (new key), `authz/claim_audit.py`, `authz/dependencies.py`, `authz/routes.py`, `authz/__init__.py`, `authz/deployment_scope.py`, `services/api/tests/authz_claim_mapping/test_builder.py`, `test_claim_audit.py`, `test_route_category.py`.
- Must NOT touch: `runtime/compose.py`, `main.py`, `app.py`, `authz/state.py`, any other builder.
- Depends on: item 3.
- Acceptance criteria: the startup refusals; with the setting unset the composition is identical (component list and readiness unchanged); the audit record content and the once-per-token rule; a failing audit repository gives 503; the marker alone on another path, or the path without the marker, fails `verify_route_permissions`; existing `services/api/tests/authz` and `runtime_api` suites pass with only the pinned detail-text assertions updated.
- Tests: the three files above.
- Pattern references: `runtime/builders/authz.py:259-306`, `authz/routes.py:219-262`, `authz/dependencies.py:307-320`.

### Item 5 - Read views: own access and effective mapping
- Deliverable: `GET /api/v1/me/access` in `me/router.py` (depends on `require_authenticated()` and `current_derivation`; builds the list from the scope's roles, tagging those whose assignment id starts with `entra.` using `claim_grants`, the rest `policy_store`; includes `mapping_configured`, `groups_overage`; never returns claim values or the mapping itself). `GET /api/v1/admin/identity/role-mapping` in `admin/identity/role_mapping.py`, registered from `admin/identity/router.py`, behind `require_deployment_admin(Permission.POLICY_MANAGE)`, returning the parsed mapping and `active`.
- Owned files: `me/**`, `admin/identity/role_mapping.py`, `admin/identity/router.py`, `services/api/tests/authz_claim_mapping/test_me_access.py`, `test_role_mapping_view.py`, Tier-2 route inventory lines.
- Must NOT touch: `admin/identity/service.py`, `admin/identity/plane.py`.
- Depends on: item 4.
- Acceptance criteria: criterion 9; a roleless caller gets 200 with an empty list from `/me/access`; an unauthenticated caller gets 401; a domain admin without the control domain gets 403 `customer_scope_required` on the mapping view; both routes are in the route inventories and boot under `verify_route_permissions`; response models are local Pydantic models (not contract models, so no OpenAPI component is renamed).
- Tests: the two files above.
- Pattern references: `me/router.py:117-140`, `admin/system/router.py:81-100`.

### Item 6 - Admin console: mapping, own access, clearer 403  [P]
- Deliverable: in `frontend/src/features/admin/identity/`: `RoleMappingPanel.tsx` (read-only table of entries, the bound tenant and audience, a note that Entra assignment decides membership and that claim-mapped users without stored policy are not in the principals list), `MyAccessPanel.tsx` (roles with a source badge, expiry, overage notice), hooks and types, both rendered in `PrincipalsPage.tsx`. `QueryErrorState` shows the API detail (the permission name) under the title and, for 403, a disclosure that loads `/api/v1/me/access` so a denied user sees what they hold. Mock API feature `role-mapping.ts` serving both routes for the mock personas.
- Owned files: `frontend/src/features/admin/identity/**`, `shared/AdminStates.tsx`, `shared/strings.ts`, `shared/shared.test.tsx`, `frontend/tests/mock-api/features/role-mapping.ts`, one line in `frontend/tests/mock-api/features/index.ts`.
- Must NOT touch: `frontend/src/app/**`, `features/admin/routes.tsx`, `shared/areas.ts`, `frontend/tests/mock-api/server.ts`, visual baselines.
- Depends on: nothing at start (the response shapes are fixed in item 5's deliverable); verified against the real API in item 7.
- Acceptance criteria: criterion 10; the panels render loading, empty ("no mapping configured"), error and forbidden states; no input, button or request can change the mapping; axe checks in the existing identity tests pass; dialog and disclosure tests query with `hidden: true` where Tabster hides content.
- Tests: `frontend/src/features/admin/identity/identity.test.tsx` additions, `role-mapping.test.tsx`, `shared/shared.test.tsx` additions.
- Pattern references: `identity/PrincipalsPage.tsx`, `identity/hooks.ts`, `shared/AdminStates.tsx:15-57`.

### Item 7 - Security suites and real-stack test
- Deliverable: `tests/security/authz/test_claim_role_mapping.py`: a world with a mapping and one without, run against the composed app: mapped admin passes every deployment-scoped admin route listed by `test_deployment_scope.py`'s route set; role injection with no mapping (the PRP-93 criterion in Entra form); wrong tenant, wrong audience, dev issuer outside local, app-only token, unmapped value, overage; mapped admin denied on `action.approve`, audit read and self-modification; Commercial mapping with a Government token and the reverse; expiry at token `exp`; revoked mapped principal; audit record present and free of GUIDs and token text. `tests/integration/real_stack/test_entra_role_mapping.py` (marker `integration`, compose emulators, empty policy container, stand-in validator from `conftest.py`): criterion 13.
- Owned files: the two test files.
- Must NOT touch: `tests/security/authz/world.py`, `cases.py`, `case_manifest.json` (read-only reuse; build the mapping world inside the new file).
- Depends on: item 5.
- Acceptance criteria: every acceptance criterion about authorization has one assertion here; the suite fails when `matching_entries` is replaced by a version that ignores the tenant or audience check (checked once locally, noted in the completion note).
- Tests: the two files.
- Pattern references: `tests/security/authz/test_deployment_scope.py:173-229`, `test_admin_identity.py:341-436`, `tests/integration/real_stack/test_operator_grant.py`.

### Item 8 - Operator script and runbook  [P]
- Deliverable: `scripts/gates/entra_admin_mapping.py`. `plan` (default): Graph reads through `az rest`, prints app role values before and after and whether the group or user is already assigned. `apply`: refuses without `NS_LIVE_APPROVED=1` and `--approve entra-app`, refuses when `az cloud show` does not match `--cloud`, adds the missing app role (allowed member type `User`, reusing `plan_roles` from `p29_entra_local.py`), assigns `--group-object-id` or `--assign-user`, reports a P1 licence refusal in plain words, and prints the `NS_AUTH_ROLE_MAPPINGS` value and the `entraRoleMappings` parameter to use. `verify` (live gate): calls `/api/v1/me/access` and `/api/v1/admin/system/status` on a deployed URL with a token held in memory, writes evidence under `docs/evidence/PRP-138/`, and reports OPEN when not approved. No token, secret or object id is printed. `docs/runbooks/entra-role-mapping.md`: what the mapping is, the setting, the Entra step, who can now create admins, group limits and overage, revocation, first-admin walkthrough, how the display roles and API roles relate; a short pointer added to `docs/runbooks/identity-admin.md`.
- Owned files: `scripts/gates/entra_admin_mapping.py`, `tests/unit/gates/test_entra_admin_mapping.py`, the two runbooks, one `mkdocs.yml` nav line.
- Must NOT touch: `scripts/gates/p29_entra_local.py` (import only), `scripts/gates/hosted_demo.py`.
- Depends on: nothing.
- Acceptance criteria: criterion 12 with `az` stubbed (no network, no cloud call in tests); a second `apply` sends nothing; the script never runs `az deployment`. UNVERIFIED and to be recorded as such in the runbook: that `az account get-access-token` can obtain a token for the API app in the operator's tenant; if not, `verify` prints the manual browser check instead.
- Tests: `tests/unit/gates/test_entra_admin_mapping.py`.
- Pattern references: `scripts/gates/p29_entra_local.py:190-306`, `scripts/gates/hosted_demo.py:1447-1480`.

### Item 9 - Hosted parameter wiring (second pull request, after PRP-139 has merged)
- Deliverable: `infra/demo/main.bicep` gains `param entraRoleMappings object = {}` and one `apiSettings` line `NS_AUTH_ROLE_MAPPINGS: empty(entraRoleMappings) ? '' : string(entraRoleMappings)`; `main.bicepparam` documents it; `scripts/gates/hosted_demo.py` accepts `--entra-role-mappings-file` (a JSON file path under `temp/`, validated with `parse_claim_role_mapping` before `plan`) and passes it to the deployment. The default leaves the mapping off.
- Owned files: the three files under `deferred_after_prp_139` (additive lines only).
- Must NOT touch: `infra/demo/modules/**`, worker settings, anything PRP-139 changed.
- Depends on: items 1 to 8 merged; PRP-139 merged; branch rebased on `main`.
- Acceptance criteria: `az bicep build` of `infra/demo/main.bicep` passes (local tool, no cloud call); the what-if hash test for `hosted_demo.py` covers the new argument; with the parameter unset the rendered app settings are unchanged apart from the empty key.
- Tests: `tests/unit/gates/test_hosted_demo_flow.py` and `test_hosted_demo_refuses.py` (one case each for the new argument).
- Pattern references: `infra/demo/main.bicep:56-59,266-268`, `scripts/gates/hosted_demo.py:216-217,487-488`.

### Item 10 - Integration and close-out (first pull request)
- Deliverable: Tier-2 appends, regenerate Tier 3 (`openapi.json`, `docs/reference/**`, PRP index, status table, execution plan), changelog fragment `changelog.d/PRP-138-entra-admin-role-mapping-and-first-admin.md`, completion note with `NS_AUTH_ROLE_MAPPINGS` under "Env vars for the operator", the OPEN live gate, the follow-up issues (Graph overage resolution; Helm and `infra/appservice` parameter; listing claim-mapped principals) and the product check: a new deployment with the mapping set lets the first admin open Admin pages and register a domain with no script.
- Owned files: Tier-2 lines, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 8.
- Acceptance criteria: gates pass; CI green; the PRP file moves to shipped only after item 9 merges (until then item 9 is `todo` in the execution state and the hosted gate is OPEN).

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/auth_claim_mapping packages/core/tests/auth services/api/tests/authz_claim_mapping services/api/tests/authz services/api/tests/runtime_api services/api/tests/runtime_routes tests/security/authz tests/unit/gates/test_entra_admin_mapping.py services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, not CI): `docker compose up -d --wait`, then `uv run pytest -q -m integration tests/integration/real_stack/test_entra_role_mapping.py` (use 127.0.0.1 endpoints; only one session in the wave may run compose, and this PRP asks for it only for this one test).

## Migration and rollback
No schema change, no contract change and no data migration. Nothing is written to the policy store, so there is nothing to clean up. Existing stored assignments keep working beside mapped ones. Rollback: unset `NS_AUTH_ROLE_MAPPINGS` (the mapping is off after the next restart and every scope is derived as before) or revert the pull request. Removing a person: remove the app role or group assignment in Entra, and revoke the principal in the console when it must take effect before the token expires. The script-made grant (`sbx_grant_operator.py`) still works and is no longer needed for the first admin.

## Live and open gates
None run here: in-memory fakes, the stand-in validator and, locally, the emulators. Live gate G-138 (OPEN until evidenced): on the hosted Commercial deployment, an operator runs `entra_admin_mapping.py apply` and `verify` with `NS_LIVE_APPROVED=1`, deploys with `entraRoleMappings` (item 9), signs in and opens the Admin pages; evidence in `docs/evidence/PRP-138/`. A Government run is a separate OPEN gate and is never satisfied by the Commercial one. Group assignment needs an Entra ID P1 tenant; on a tenant without it the gate is run with a user assignment and says so.

## NOT building
Writing claim-derived roles into the policy store; a wildcard, customer-wide role or bypass; Microsoft Graph calls from the API (overage resolution, nested groups, transitive membership); mapping for service principals or managed identities; OIDC, Keycloak or Cognito role mapping (PRP-93 decides later); editing the mapping in the console; a new role or permission; any change to who holds `action.approve` or to capture approval; Entra Privileged Identity Management integration; Helm and `infra/appservice` parameters (documented setting only); listing claim-mapped principals in the principals table; changing navigation or the display role parsing.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (owner accepted assumption rows 3, 4, 5, 10, 13 and 14 as written on 2026-11-18; row 16: PRP-138 edits the hosted Bicep in item 9, as a second pull request after PRP-139)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-aeeac7001ca09a4f8 (opus) | 479 passed on branch (auth_claim_mapping + auth), ruff and pyright clean; commit c3aad0fc, merge 1fd99ecb; 2026-11-18 |
| 2 | merged | worktree-agent-a2d0f3c11b0ff26fd (opus) | 382 passed (auth_claim_mapping + auth), ruff and pyright clean; commit 7e7933bc, merge ab419ace; 2026-11-18 |
| 3 | in-progress | worktree (implementer, opus) | dispatched 2026-11-18 |
| 4 | todo | | |
| 5 | todo | | |
| 6 | in-progress | worktree (implementer, opus) | dispatched 2026-11-18 |
| 7 | todo | | |
| 8 | in-progress | worktree (implementer, opus) | dispatched 2026-11-18 |
| 9 | todo | | second pull request, after PRP-139 has merged |
| 10 | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
