---
name: PRP-93-generic-oidc-identity
status: backlog
priority: P1
order: 84
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-08, NS-09
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-87-api-composition-seam-and-adapter-packages]
wave: W36
branch: prp-93-generic-oidc
allow_parallel: true
issues: []
---

# PRP-93: Generic OIDC identity beside Entra (API, workers and frontend)

## Goal
Let a deployment on AWS, GCP or an on-prem cluster sign users in and validate their access tokens with a generic OpenID Connect issuer (Keycloak, Amazon Cognito or the customer's own IdP), configured explicitly per deployment, while the Entra path stays byte-for-byte as strict as it is today. The API gains an OIDC validator that produces the same `VerifiedClaims` the scope deriver already consumes, with an exact issuer, a pinned JWKS URI, RS256 only, explicit audiences (or an explicit client-id check for issuers that omit `aud`) and a declared claim map in which every missing, unmapped or ambiguous claim denies. Authorization stays where it is: the server derives scope from the policy store, never from token roles or groups. The frontend gains an `AuthClient` seam with the existing MSAL implementation and an `oidc-client-ts` implementation (authorization code with PKCE) chosen by runtime config. It is for the operator of a non-Azure deployment, which today cannot sign anyone in (owner decision 2026-11-16), and it runs in W36 after PRP-85 and PRP-87.

Out of scope: workload identity, secret readers and IAM tokens (PRP-94); Helm values that render the identity block and the `kind` sign-in smoke (PRP-96); Cognito user pool Terraform (PRP-97); contract changes to the principal id grammar (PRP-86 or a later contracts PRP, see clarification 4); several identity providers active in one deployment; a Google-native IdP (OPEN, design section 9 item 9).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-106): "Platform deployable via containerized/IaC templates to Azure, AWS, GCP, or on-prem Kubernetes ... behind a common abstraction layer" and "Core platform logic ... is cloud-agnostic; only infra adapters differ." No non-Azure deployment can be used without a sign-in path.
- v1.2 excluded it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting, classified/air-gapped deployment ... are outside the initial baseline"), `PRP.md:7`. On 2026-11-16 the owner decided to add back all four targets; PRP-85 amends those lines. NS-08 ("Entra ID with cloud-specific authorities/audiences") stays true for Azure.
- The validator is Entra-only by construction: issuers come only from the per-cloud Entra table (`packages/core/neurosphere_core/auth/jwt/config.py:36-55`), the tenant must be a GUID (`config.py:62-74`), required claims include `tid` and `oid` (`auth/jwt/validator.py:43`), and `VerifiedClaims.issuer_kind` is `Literal["entra", "dev"]` with `tenant_id` fixed at 36 characters (`auth/jwt/claims.py:24-28`).
- Scope derivation repeats the GUID rule (`auth/scope/derivation.py:80-97`) and the worker's own claims are hard-coded `issuer_kind="entra"` with a GUID tenant (`services/workers/neurosphere_workers/runtime/identity.py:93-141`).
- The frontend can only sign in through MSAL: `frontend/package.json:21-22`, authority hosts fixed to the two Entra hosts (`frontend/src/auth/authority.ts`), runtime config requires `cloud`, `tenantId`, `clientId` (`frontend/src/app/config.ts:7-60`), and the MSAL instance type is threaded through the Tier-1 shell (`frontend/src/app/Providers.tsx:2`, `App.tsx:2`, `main.tsx:3-19`).
- Token roles are not an authorization input today (no consumer of `VerifiedClaims.roles` or `.groups` in `packages/core` or `services/api`; scope comes from `PolicyRepository` in `derivation.py:159-205`). The OIDC path must keep it that way, so a role claim injected by a misconfigured IdP grants nothing.

## Acceptance criteria
- [ ] Given `NS_AUTH_PROVIDER` unset or `entra`, Then every existing JWT, scope, authz and realtime suite passes unchanged and the Entra validator, config and claims behave byte-for-byte as before (golden test over a fixed token set: same accept/reject and same reason codes).
- [ ] Given `NS_AUTH_PROVIDER=oidc` and a complete `NS_AUTH_OIDC_*` configuration, When a token signed by the configured issuer with an allowed audience arrives, Then the API returns `VerifiedClaims` with `issuer_kind="oidc"`, `tenant_id` = the configured tenant label, `object_id` = the mapped subject, and the request is authorized only by what the policy store grants that pseudonymous principal.
- [ ] Rejections (401, one body, reason code only, never token content): issuer not exactly equal; audience not in the list (or, in `client_id` mode, client id not in the list); `alg` other than RS256 including `none`, HS256 signed with the public key, and a `kid` not in the pinned JWKS; expired, not yet valid, or missing `exp`/`nbf`/`iat`; missing or non-string subject; tenant claim configured and missing or different; a required exact-value claim (for example `token_use=access`) missing or different; a mapped list claim that is not a list of strings.
- [ ] Configuration fails closed at startup (component `authz` disabled with a reason code, never a permissive default): missing issuer, JWKS URI, audiences or client ids, tenant label or subject claim; JWKS URI not `https` or not on the issuer's origin (unless an explicit allowlisted origin is configured); `http` issuer outside `NS_ENV=local`; wildcard audience; `NS_AUTH_PROVIDER=oidc` with `NS_CLOUD=government`.
- [ ] Role-claim injection: a valid OIDC token carrying `roles: ["Admin"]` (and the Keycloak and Cognito group claim shapes) for a principal with no policy assignment gets 403 on an admin route and appears as a denial record; token roles and groups never change the derived `IdentityScope`.
- [ ] The dev issuer stays local-only exactly as today (`config.py` `_dev_issuer_local_only`); the OIDC config cannot be used to smuggle a dev issuer in any other environment.
- [ ] The MCP server verifier (`services/api/neurosphere_api/mcp/server/verifier.py:45-90`) and the realtime gateway (`services/api/neurosphere_api/realtime/gateway.py:234-240`) accept OIDC tokens through the same authenticator with no code path of their own; stdio MCP still accepts only the dev issuer.
- [ ] Workers on an OIDC deployment build their own `VerifiedClaims` with `issuer_kind="oidc"` and the configured tenant label; the pseudonymous principal id equals the one the API derives for the same subject (shared pseudonym key).
- [ ] Keycloak conformance: against the local container realm, the suite covers a good token, wrong issuer, wrong audience, algorithm confusion, expired, missing subject and role-claim injection; Cognito and an optional customer IdP are configuration profiles tested with recorded metadata documents and locally signed tokens.
- [ ] Frontend: runtime config `identity.kind` selects `entra` (MSAL, unchanged behaviour and visuals) or `oidc` (authorization code with PKCE through `oidc-client-ts`); invalid identity config shows the existing configuration error page; vitest, typecheck, lint and the e2e suite pass for both kinds on the mock API; no token is written to `localStorage` (session storage or memory only, as MSAL is configured today).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend gates and `validate_planning.py` pass; the Keycloak conformance run passes locally with output recorded; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 2 | Portable identity | native IdP per cloud; generic OIDC | Generic OIDC with per-IdP configuration profiles (D-2); Entra remains first-class and can also serve a non-Azure deployment |
| 3 | Providers per deployment, and Government (owner decision D-6 in PRP-85) | one; several issuers at once | Decided by the owner 2026-11-16 (D-6 default accepted): exactly one provider per deployment (`NS_AUTH_PROVIDER=entra|oidc`), so subjects from two issuers can never collide in one pseudonym space, and OIDC is refused with `NS_CLOUD=government`. Multi-issuer is a follow-up |
| 4 | Principal id segment (owner decision D-3 in PRP-85) | change the grammar; keep `entra` | Decided by the owner 2026-11-16 (D-3 default accepted): keep the contract grammar `<cloud>:<customer>:entra:(person|principal):p-<hex>` (`packages/contracts/schemas/admin/v1/common.schema.json:36-39`) for OIDC principals; renaming it would be a PRP-86 contract change |
| 5 | Tenant equivalent | token claim; configured label | Configured `NS_AUTH_OIDC_TENANT_LABEL` (canonical segment grammar) is the pseudonym tenant input; optional `NS_AUTH_OIDC_TENANT_CLAIM` must then equal it exactly or the token is refused |
| 6 | Issuers without `aud` | refuse; client-id mode | `NS_AUTH_OIDC_AUDIENCE_MODE=aud` (default) or `client_id` with `NS_AUTH_OIDC_CLIENT_ID_CLAIM` and `NS_AUTH_OIDC_CLIENT_IDS`; plus `NS_AUTH_OIDC_REQUIRED_CLAIMS` exact-value pairs. UNVERIFIED: that Cognito access tokens carry `client_id` and `token_use` and no `aud` (design 3.2); the profile is built from recorded documents and marked UNVERIFIED until a real pool is used |
| 7 | JWKS source | discovery at runtime; pinned URI | Pinned `NS_AUTH_OIDC_JWKS_URI`, never derived from a token; reuse `JwksCache` limits (size, key count, refresh interval, RSA >= 2048). Discovery documents are read only by an offline helper that prints settings |
| 8 | Nested claims (Keycloak `realm_access.roles`) | top-level only; path | Claim map accepts a top-level name or an explicit two-segment path; any other shape is a startup error. UNVERIFIED: Keycloak claim layout is checked against the container in item 5 |
| 9 | Frontend library | own PKCE code; `oidc-client-ts` | `oidc-client-ts` (design says Apache-2.0; verify version and licence in item 6 through the licence gate and pin in ADR-0002) |
| 10 | Real IdP runs | now; OPEN | OPEN: Cognito sign-in, a customer Keycloak realm and any Google option need an operator; handed to PRP-98 / PRP-64 |

## Context manifest

### Files to read first
- `temp/audit/multicloud-program-design.md` section 1.2 ("JWT validation" row), 3.2 ("Identity" row), M9.
- `PRPs/backlog/PRP-85-*.md`, `PRP-87-*.md` - "Interfaces provided" (platform axis, authenticator selection in the authz seam).
- `packages/core/neurosphere_core/auth/jwt/config.py` - `JwtConfig`, `DevIssuerTrust`, `ALLOWED_ALGORITHMS`, `normalize_tenant_id`.
- `packages/core/neurosphere_core/auth/jwt/validator.py` - check order, `_REQUIRED_CLAIMS`, `_reject`, `create_jwt_validator`.
- `packages/core/neurosphere_core/auth/jwt/jwks.py` - `JwksCache`, `HttpJwksFetcher`, `parse_jwks` limits.
- `packages/core/neurosphere_core/auth/jwt/claims.py` - `VerifiedClaims`.
- `packages/core/neurosphere_core/auth/scope/derivation.py:80-205` - `ScopeDerivationConfig`, `ScopeDeriver.derive`.
- `services/api/neurosphere_api/runtime/builders/authz.py:258-335` - `_tenant`, `_deriver`, `_authenticator`.
- `services/workers/neurosphere_workers/runtime/identity.py` - `EnvClaimsSource`, `build_policy_stack`.
- `frontend/src/auth/` (`AuthProvider.tsx`, `msal.ts`, `authority.ts`, `token.ts`, `roles.ts`), `frontend/src/app/config.ts`, `frontend/src/app/{Providers,App,main}.tsx`.
- `frontend/tests/e2e-support/stubMsal.ts`, `frontend/tests/mock-api/server.ts` (`/config.json` handler).

### Interfaces consumed
- PRP-85: `DeploymentTarget` / `NS_PLATFORM`, the rule "government requires azure", the multicloud-hosting ADR threat-model delta (IdP no longer Azure-managed), and the registry of platform settings (the `NS_AUTH_PROVIDER` and `NS_AUTH_OIDC_*` rows are this PRP's).
- PRP-87: the authz composition seam through which the authenticator is selected (if it exposes no selection point, item 4 is `[serial-after: PRP-87]` and edits `runtime/builders/authz.py`, see the item).
- Shipped: `JwtValidator`, `JwksCache`, `VerifiedClaims`, `ScopeDeriver`, `PrincipalPseudonymizer`, `TokenAuthenticator` (`services/api/neurosphere_api/authz/state.py:44`), MCP `TokenValidator` shape, frontend `AuthProvider`, `getToken`, `parseConfig`.

### Interfaces provided
- Core package `neurosphere_core.auth.oidc`: `OidcIssuerConfig`, `ClaimMap`, `OidcSettings` (env prefix `NS_AUTH_OIDC_`: `ISSUER`, `JWKS_URI`, `JWKS_ALLOWED_ORIGIN`, `AUDIENCES`, `AUDIENCE_MODE`, `CLIENT_ID_CLAIM`, `CLIENT_IDS`, `TENANT_LABEL`, `TENANT_CLAIM`, `SUBJECT_CLAIM`, `ROLES_CLAIM`, `GROUPS_CLAIM`, `SCOPES_CLAIM`, `IDENTITY_TYPE_CLAIM`, `APP_IDENTITY_VALUES`, `REQUIRED_CLAIMS`, `LEEWAY_SECONDS`), `OidcValidator` (same `authenticate`/`validate` shape as `JwtValidator`), `create_oidc_validator`, profile data `profiles/keycloak.json`, `profiles/cognito.json`.
- `VerifiedClaims.issuer_kind` gains `"oidc"`; `tenant_id` length rule becomes per kind (36-character GUID for `entra`/`dev`, canonical segment for `oidc`).
- `NS_AUTH_PROVIDER` (`entra` default, `oidc`) on API and worker `AuthSettings` (Tier-2 new fields).
- Frontend: `AuthClient` interface (`signIn`, `signOut`, `getToken`, `account`), `createMsalAuthClient`, `createOidcAuthClient`; runtime config `identity` block `{kind: "entra", tenantId, clientId}` or `{kind: "oidc", authority, clientId, scope, redirectPath}`; legacy top-level `tenantId`/`clientId` still accepted and mean `entra`.
- Compose fragment `infra/compose/portable/keycloak.yml` (own project name, realm import from `infra/compose/portable/keycloak/realm.json` with synthetic users only).

### Patterns to match
- Fail-closed config with value-free messages: `auth/jwt/config.py:133-165`.
- Validator rejection with one reason code: `auth/jwt/validator.py:47-50,99-160`.
- Recorded JWKS and locally signed tokens: `packages/core/tests/auth/jwt/jwt_helpers.py`, `test_cloud_isolation.py`.
- Dev-issuer local-only test: `packages/core/tests/auth/jwt/test_dev_issuer.py`.
- Authz deny-case harness: `tests/security/authz/test_api_paths.py`.

### Gotchas
- Do not loosen any Entra rule to fit OIDC: add an OIDC branch beside it. The golden test in item 1 is the guard.
- PyJWT's `audience` check cannot express client-id mode; disable it only in that mode and do the check yourself before building claims, with a test that an absent `aud` plus a wrong client id is refused.
- JWKS from a misconfigured IdP may contain symmetric (`oct`) keys: `parse_jwks` must keep dropping them (`_PRIVATE_MEMBERS` contains `k`); add a test with an `oct` key whose `kid` matches the token.
- The pseudonym input becomes `tenant_label:subject`; changing the tenant label after go-live changes every principal id (state this in the runbook; it is equivalent to a new tenant).
- `NS_AUTH_TENANT_ID` remains required for Entra and must be ignored, not validated as a GUID, when the provider is `oidc`.
- Frontend: Fluent dialog tests need `hidden: true`; Playwright needs unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` per worktree; visual baselines are Docker-only. The Keycloak container holds the portable compose lane after PRP-89 and PRP-92 in W36.
- CodeQL: never log a claim value or token fragment; hostname checks use exact origin comparison, never `endswith` without a leading dot.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/auth/oidc/**
  - packages/core/neurosphere_core/auth/jwt/**
  - packages/core/neurosphere_core/auth/scope/derivation.py
  - packages/core/tests/auth/oidc_validator/**
  - packages/core/tests/auth/jwt/**
  - services/workers/neurosphere_workers/runtime/identity.py
  - services/workers/tests/runtime_identity_oidc/**
  - services/api/tests/authz_oidc/**
  - tests/conformance/oidc/**
  - tests/security/authz/test_oidc*.py
  - infra/compose/portable/keycloak.yml
  - infra/compose/portable/keycloak/**
  - frontend/src/auth/**
  - frontend/src/app/config.ts
  - frontend/src/app/main.tsx
  - frontend/tests/e2e-support/**
  - frontend/tests/e2e/auth-oidc/**
  - docs/runbooks/identity-oidc.md
tier1:
  - frontend/src/app/Providers.tsx
  - frontend/src/app/App.tsx
  - frontend/tests/mock-api/server.ts
  - frontend/package.json
  - pnpm-lock.yaml
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
  - services/workers/neurosphere_workers/runtime/settings.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/auth/scope/pseudonym.py
  - packages/core/neurosphere_core/auth/scope/policy*.py
  - services/api/neurosphere_api/runtime/builders/**
  - services/workers/neurosphere_workers/connector_config/**
  - packages/adapters-*/**
  - pyproject.toml
  - uv.lock
  - infra/helm/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 6 [P] after item 1 (core versus frontend). Item 3 after 2. Item 4 after 3. Item 5 after 4. Item 7 after 6. Item 8 last.

### Item 1 - Entra golden and claims model
- Deliverable: a golden test that pins today's Entra accept/reject decisions and reason codes over a fixed token set (Commercial, Government, v1, v2, dev issuer, cross-cloud); `VerifiedClaims.issuer_kind` gains `"oidc"` with a per-kind `tenant_id` validator.
- Owned files: `auth/jwt/claims.py`, `packages/core/tests/auth/jwt/test_entra_golden.py`.
- Must NOT touch: Entra validation logic.
- Depends on: PRP-85, PRP-87 merged.
- Acceptance criteria: criterion 1; an `oidc` claims object with a GUID-shaped label is accepted only for kind `oidc`; an `entra` claims object with a non-GUID tenant is refused.
- Tests: `packages/core/tests/auth/jwt/test_entra_golden.py`, `test_claims_kinds.py`.
- Pattern references: `packages/core/tests/auth/jwt/test_cloud_isolation.py`.

### Item 2 - OIDC configuration and claim map
- Deliverable: `auth/oidc/config.py` (`OidcIssuerConfig`, `ClaimMap`, `OidcSettings`, every startup refusal in criterion 4), `auth/oidc/profiles/{keycloak,cognito}.json` (claim-map presets, no secrets, marked UNVERIFIED where clarification 6 or 8 says so), `python -m neurosphere_core.auth.oidc.describe <discovery.json>` offline helper that prints settings from a saved discovery document.
- Owned files: `auth/oidc/__init__.py`, `config.py`, `profiles/**`, `describe.py`, `packages/core/tests/auth/oidc_validator/test_config.py`.
- Depends on: item 1.
- Acceptance criteria: criterion 4 and 6, each refusal a named test with a reason code.
- Tests: `packages/core/tests/auth/oidc_validator/test_config.py`.
- Pattern references: `auth/jwt/config.py:96-165`.

### Item 3 - OIDC validator
- Deliverable: `auth/oidc/validator.py` (`OidcValidator`, `create_oidc_validator`) reusing `extract_bearer_token`, size and shape checks, the RS256 allowlist and `JwksCache` on the pinned URI; audience or client-id check; tenant claim; required exact claims; claim extraction with deny on ambiguity.
- Owned files: `auth/oidc/validator.py`, `packages/core/tests/auth/oidc_validator/test_validator.py`, `test_algorithm_confusion.py`, `test_profiles.py` (recorded Keycloak and Cognito metadata, locally signed tokens).
- Depends on: item 2.
- Acceptance criteria: criterion 3 complete; `oct` key and `alg: none` refused; JWKS refresh rate limit honoured.
- Tests: the files above.
- Pattern references: `auth/jwt/validator.py`, `packages/core/tests/auth/jwt/test_jwks_cache.py`.

### Item 4 - Scope derivation, API selection and workers
- Deliverable: `ScopeDerivationConfig` accepts a tenant label when the provider is `oidc` (GUID rule unchanged for Entra); API and worker `AuthSettings` gain `provider` (Tier-2 new fields); the authenticator is selected through the PRP-87 seam; `EnvClaimsSource` builds `oidc` claims when configured. If the PRP-87 seam offers no selection point, this item is `[serial-after: PRP-87]` and makes the minimal edit in `services/api/neurosphere_api/runtime/builders/authz.py` (`_tenant`, `_authenticator`) only after confirming no other W36 PRP holds that file; report it.
- Owned files: `auth/scope/derivation.py`, `services/workers/neurosphere_workers/runtime/identity.py`, Tier-2 lines, `services/api/tests/authz_oidc/**`, `services/workers/tests/runtime_identity_oidc/**`.
- Depends on: item 3.
- Acceptance criteria: criteria 2, 7 and 8; with the provider unset `services/api/tests/runtime_api`, `services/api/tests/authz` and `packages/core/tests/auth/scope` pass unchanged.
- Tests: `services/api/tests/authz_oidc/test_builder.py`, `test_mcp_and_realtime.py`; `services/workers/tests/runtime_identity_oidc/test_claims_source.py`.
- Pattern references: `runtime/builders/authz.py:258-335`, `services/api/tests/admin_identity_api/test_builder.py`.

### Item 5 - Keycloak conformance and authorization negatives  [serial-after: PRP-89]
- Deliverable: `infra/compose/portable/keycloak.yml` plus a realm export with synthetic users, groups and a role mapper; `tests/conformance/oidc/` (CHECKS run on the recorded-fixture issuer by default and on the container with marker `portable`, plus a broken validator that skips the issuer check); first step: record the actual Keycloak token claim layout (issuer string, `aud`, `azp`, roles path) and update the Keycloak profile from it, removing its UNVERIFIED mark only for what was observed; `tests/security/authz/test_oidc_role_injection.py`.
- Owned files: the compose fragment and realm, `tests/conformance/oidc/**`, `tests/security/authz/test_oidc*.py`.
- Depends on: item 4; PRP-89 merged (same wave: its harness `tests/conformance/conftest.py` and `scripts/portable/run_conformance.py`), and PRP-92 done with the W36 portable compose lane.
- Acceptance criteria: criteria 5 and 9; the broken validator fails.
- Tests: `tests/conformance/oidc/test_fixture_issuer.py`, `test_keycloak.py`, `test_broken.py`; `tests/security/authz/test_oidc_role_injection.py`.
- Pattern references: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.

### Item 6 - Frontend AuthClient and OIDC client  [P]
- Deliverable: first step, run the licence gate for `oidc-client-ts` (`python scripts/licenses_report.py --check` after `pnpm add`), record version and licence, add the ADR-0002 frontend row. Then `AuthClient` interface; MSAL implementation wrapping today's code unchanged; `oidc-client-ts` implementation (code flow with PKCE, session storage); `config.ts` parses the `identity` block with legacy fields meaning `entra`; `Providers.tsx`, `App.tsx`, `main.tsx` take an `AuthClient` instead of `IPublicClientApplication`; e2e stub for both kinds.
- Owned files: `frontend/src/auth/**`, `frontend/src/app/config.ts`, `main.tsx`, Tier-1 `Providers.tsx`, `App.tsx`, `frontend/package.json`, `pnpm-lock.yaml`, `docs/licenses.md`, `docs/adr/0002-stack-pins.md`, `frontend/tests/e2e-support/**`.
- Depends on: item 1 only for the naming of `issuer_kind`.
- Acceptance criteria: criterion 10 at unit level; MSAL path renders identically (existing visual baselines unchanged).
- Tests: `frontend/src/auth/AuthClient.test.ts`, `oidcClient.test.ts`, `frontend/src/app/config.test.ts` (extend), existing `AuthProvider.test.tsx`.
- Pattern references: `frontend/src/auth/msal.ts`, `frontend/src/auth/AuthProvider.tsx`.

### Item 7 - Mock API and e2e for OIDC
- Deliverable: mock server serves an `identity.kind` chosen by an env switch; e2e spec signs in through the OIDC stub, loads two routes, signs out.
- Owned files: Tier-1 `frontend/tests/mock-api/server.ts`, `frontend/tests/e2e/auth-oidc/**`.
- Depends on: item 6.
- Acceptance criteria: criterion 10 end to end on the mock API; the default e2e run (Entra) unchanged.
- Tests: `frontend/tests/e2e/auth-oidc/oidc-sign-in.spec.ts`.
- Pattern references: `frontend/tests/e2e-support/stubMsal.ts`.

### Item 8 - Integration and close-out
- Deliverable: `docs/runbooks/identity-oidc.md` (settings, Keycloak and Cognito profiles, the tenant-label warning, what is UNVERIFIED and OPEN) and its `mkdocs.yml` line; rebase, Tier-3 regeneration (`openapi.json` should not change; prove it); `changelog.d/PRP-93-generic-oidc-identity.md`; completion note with env vars and the product check.
- Owned files: runbook, Tier-2 lines, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/auth services/api/tests/authz_oidc services/api/tests/authz services/api/tests/runtime_api services/api/tests/test_openapi_drift.py services/workers/tests/runtime_identity_oidc tests/conformance/oidc tests/security/authz
docker compose -f infra/compose/portable/keycloak.yml up -d --wait
python scripts/portable/run_conformance.py --backend keycloak
docker compose -f infra/compose/portable/keycloak.yml down -v
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/licenses_report.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. Existing deployments keep `NS_AUTH_PROVIDER` unset (Entra) and an unchanged `config.json`. Turn off: set `NS_AUTH_PROVIDER=entra` (or unset) and serve the legacy config. Revert: revert the PR; the `oidc-client-ts` dependency and its licence and ADR rows go with it. Changing the tenant label of a live OIDC deployment re-keys every principal id; the runbook treats it as a new tenant.

## Live and open gates
None run here. OPEN: Cognito sign-in and token validation against a real user pool; a customer-operated Keycloak realm; any Google identity option (design section 9 item 9); EKS/GKE sign-in through the chart (PRP-96 local `kind` smoke covers Keycloak only). Handed to PRP-98, which records them with PRP-64.

## NOT building
Several providers at once; group-to-role synchronisation from token claims into the policy store; a Google-native IdP; SAML; renaming the `entra` principal-id segment; Helm rendering of the identity block; Cognito Terraform.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 3 and 4 (owner decisions D-6 and D-3 in PRP-85) and the UNVERIFIED provider facts in rows 6 and 8 need owner confirmation or item-5 observation)

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
- Product check (can an operator configure and use it without editing files or calling raw APIs?):
