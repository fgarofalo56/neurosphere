---
name: prp-06-identity-authz-and-audit
status: backlog
review: required
created: 2026-10-08
model: opus
phase: 1
ns: NS-08
depends_on: PRP-05
wave: W4
absorbs: P1.3
---

# PRP-06: Identity, authorization and audit

## Goal

Ship the security spine that every query, tool, export, search and push path inherits: Entra JWT validation with cloud-specific issuers and audiences, server-side derivation of `IdentityScope` from verified claims plus a policy store, a fail-closed `require(permission)` dependency, an append-only hash-chained audit store, a revocation list with TTL, and an ABAC negative suite proving cross-domain and cross-customer denial on the API, search, export, cache and (through an interface) push paths. It is for every later PRP that serves data, and for the security auditor persona. It runs on Opus with a required review because a defect here is data exposure across domains or clouds and is hard to reverse once downstream PRPs build on it. It lands in W4, after PRP-05 provides the core types, error taxonomy, app factory and clients.

> NS-08: "Entra ID with cloud-specific authorities/audiences, managed identities where supported and vault references elsewhere. Roles: Viewer, Analyst/Pro, Domain Steward/Owner, Admin, Security Auditor; custom resource-scoped permissions. Pro status does not imply administration. Privileged access remains scoped, time-bound and auditable; no unrestricted 'God' bypass."

> NS-08: "Server-side ABAC/RBAC for APIs, queries, exports, search indexes, copilot, tools and push channels. Fail closed on authorization errors; secure cache keys and federation summaries."

The fail-closed rule, as binding text: a policy store outage returns 503, never 200 and never an allow; privileged roles are scoped and there is no bypass. Authorization is enforced at every query, tool, export, push and action path (project CLAUDE.md hard constraints).

## Acceptance criteria

- [ ] Item 1: No token returns 401; a token with the wrong audience returns 401; a token from the dev issuer is rejected unless `NS_ENV=local`; an expired token and a token signed by an unknown `kid` (after one JWKS refresh) return 401.
- [ ] Item 2: Given a request carrying a forged `domain_id` header, query parameter or body field, then the derived `IdentityScope` is unchanged; roles Viewer, Analyst, Steward, Admin, Auditor map to documented permission sets; resource-scoped grants narrow, never widen, and expire.
- [ ] Item 3: `require(permission)` returns 403 for insufficient scope and 503 (taxonomy `dependency_transient`) when the policy store errors or times out; the cache key is a hash of the scope and never of the raw token; there is no code path with an allow-on-error branch.
- [ ] Item 4: Update and delete on the audit container are rejected; the hash chain verifies end to end and a single tampered record is detected at its position; allow, deny and before/after records are written; SIEM export hook emits redacted records.
- [ ] Item 5: A revoked principal receives 403 within the configured TTL (default value stated in code and docs; measured in test with a fake clock); revocation invalidates scope-keyed caches and notifies registered push-session closers through the interface.
- [ ] Item 6: 100 percent of negative cases deny across the API, search, export, cache and push-interface paths; a privileged role (Admin, Auditor) cannot read another domain or customer without an explicit scoped grant; the suite fails if a case is removed without a reason entry.
- [ ] PRP exit: `verify-gates.ps1 -Mode full` green; `pytest tests/security/authz` all denies hold; one reviewer pass approves (review: required, one rework round max); gitleaks clean; `python scripts/validate_planning.py` shows no failure attributable to this file.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| C1 | Model and review | sonnet; opus | **opus, review required** (master table; decision D6: risk concentrated in contracts, authz, actions, MCP). One review pass, approve unless a blocking defect (wrong behavior, security, data loss, broken contract), max one rework round. |
| C2 | Live gates | live Entra tenant test; mocked IdP only | **Mocked IdP and local JWKS in CI.** Decision D7 allows Commercial live runs per PRP, but a live Entra token smoke needs a registered app and is optional, **operator-approved, requires NS_LIVE_APPROVED=1**. Government tenant verification stays OPEN (no Government subscription). |
| C3 | Dev issuer | always on; local only | **Dev issuer only when `NS_ENV=local`.** It is a self-signed local JWKS minted by a test helper. Startup fails if a dev issuer is configured with `NS_ENV` other than `local`. Never a default in any compose profile other than local. |
| C4 | Issuers and audiences | derive from tenant id; configured | **Configured per cloud**: Commercial `https://login.microsoftonline.com/<tenant>/v2.0`, Government `https://login.microsoftonline.us/<tenant>/v2.0`; audience is the API app id URI from settings. Both v1 and v2 issuer forms are allowlisted explicitly; anything else is 401. |
| C5 | Policy store | Cosmos container; Entra groups only | **Cosmos policy container** holding role assignments, resource-scoped grants (with expiry and reason) and domain membership; Entra group or app-role claims are inputs, not authority. A missing policy document means no grants (deny), distinct from store unavailability (503). |
| C6 | Role set | fixed; extensible | **Fixed five roles per NS-08: Viewer, Analyst, Steward, Admin, Auditor.** "Pro" is an Analyst capability tier, not Admin. Custom permissions are resource-scoped grants layered on top. |
| C7 | Privileged access | break-glass bypass; scoped grants | **No bypass.** Admin manages configuration within granted domains; Auditor reads audit and evidence, not data; elevated access is a time-bound, reason-bearing grant that is itself audited. |
| C8 | Scope shape | free dict; contract type | **`IdentityScope` from PRP-01/PRP-05**: principal id (pseudonymous subject), cloud, customer_id, set of domain_ids, role set, grant ids, issued-at, policy version. Constructible only through `from_verified_claims` here. |
| C9 | Cache key | token hash; scope hash | **Scope hash** (SHA-256 over canonical JSON of the scope plus policy version) with the cloud prefix. Tokens never enter keys. A policy version bump invalidates entries. |
| C10 | Audit storage | Cosmos container; append blob | **Cosmos container with hash chain** (each record stores `prev_hash` and `hash` over canonical JSON); immutability enforced by the repository API exposing no update/delete and by container configuration where the service supports it. Emulator cannot prove service-side immutability (recorded as an emulator delta). Retention conflicts belong to PRP-23. |
| C11 | Audit content | full request; metadata | **Metadata and decisions only**: actor pseudonym, action, target ids and versions, scope hash, decision, reason code, correlation id, before/after digests. No prompt or response bodies; no tokens. |
| C12 | Revocation TTL | fixed; configured | **Configured with a documented default** (`NS_REVOCATION_TTL_SECONDS`); effect is bounded by TTL, and the doc states it plainly rather than implying instant revocation. |
| C13 | Push paths | build WebSocket gateway; interface only | **Interface only** (`PushSessionRegistry.close_for_principal`); the gateway is PRP-18. The negative suite uses a fake registry. |
| C14 | Policy cache | cache decisions; no cache | **Short in-process cache of policy documents** keyed by policy version with TTL; on store error with expired cache the request fails closed (503). A stale-but-unexpired cache entry may serve; expiry is never extended on error. |
| C15 | Pseudonymization | raw subject; HMAC | **Principal id is HMAC-SHA256 of tenant id plus object id** with a vault-referenced key; raw object ids never appear in logs or audit records. Key is a vault reference, never a file. |

## Context manifest

### Files that matter

- `PRP.md` sections 1-3; project `CLAUDE.md` hard constraints ("Authorization is enforced at every query/tool/export/push/action path. Privileged users have scoped permissions, never an unrestricted bypass.").
- `docs/PRD.md` NS-08 (quoted above), NS-04 (self-approval is PRP-17), NS-05 (revocation closes sessions), NS-09 (OAuth audience and scope validation, PRP-22).
- `docs/ARCHITECTURE.md` diagram 1 (API authorization and policy), section 6 ("Search and push paths enforce the same policy as REST.").
- `docs/adr/0002-stack-pins.md`: azure-identity 1.26, azure-cosmos 4.17, FastAPI 0.143, Starlette 1.7, Pydantic 2.14, httpx 0.28 / respx 0.23, pytest 9.1; no JWT library is pinned, so adding one (for example PyJWT or authlib, MIT/BSD) requires a licence row in ADR-0002 and the integrator step.
- `docs/RESEARCH-AND-GATES.md` (G02 boundary and ATO is separate; G12 emulator deltas; Government identity endpoints).
- `docs/DECISIONS-LOG.md` D6 (model), D7 (live approval), D11 (shared core).
- `.claude/hooks/config.ps1`, `.env.example` (names only; do not read `.env`), `pyproject.toml` (ruff S rules on: crypto and subprocess rules matter here), `scripts/validate_planning.py`.
- Created by PRP-05: `packages/core/neurosphere_core/{errors,scope,paging,cloud,observability,clients}/`, `services/api/neurosphere_api/{app.py,main.py,middleware/,health/}`, `services/api/openapi.json`, `docker-compose.yml` `app` profile.
- Created by PRP-01: `packages/contracts/schemas/{scope,audit,errors}/` and generated Python models (`IdentityScope`, `AuditRecord`).
- Consumed later: PRP-07 ingest edge uses producer identity (separate from user JWT); PRP-10 catalog and PRP-14 dashboards call `require(permission)`; PRP-17 action executor rechecks permission; PRP-18 implements push closers; PRP-22 adds MCP audience checks; PRP-12 threat model references this PRP.

### Patterns to match

No product code exists yet, so these are rules.

- Pydantic v2 models, `model_config = ConfigDict(extra="forbid")`; frozen models for scope and claims.
- FastAPI dependency `require(permission, resource=...)` declared per route; no router-level blanket allow; every route declares a permission or is on an explicit public allowlist (`/healthz`, `/readyz`, OpenAPI if configured).
- Exceptions from `neurosphere_core.errors` only: `unauthorized` (401), `forbidden` (403), `dependency_transient` (503 for policy outage); no ad hoc `HTTPException`.
- Async Cosmos access through `neurosphere_core.clients`; audit and policy repositories take a client by injection for testability.
- Tests beside packages for unit behavior, cross-package denial suite in `tests/security/authz/`; `pytest.mark.integration` for emulator tests.
- Negative tests are table-driven: each row is (path, principal, attempted target, expected status, reason code).

### Conventions

- ruff (line 100, py312, S rules on) and pyright standard; conventional commits (`feat(auth): ...`); owned-file discipline; evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Security-sensitive code needs a threat note in the item PR description naming the abuse case covered; PRP-12 consumes these.
- Constant-time comparison for hash checks (`hmac.compare_digest`); no `==` on digests.
- Forward slashes in commands; Python is `python`; temp files in `temp/`.

### Gotchas

- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.

PRP-specific gotchas:

- Algorithm confusion: accept only RS256 (and explicitly listed algorithms) from the JWKS; reject `none` and any HMAC algorithm when a public key is configured. Pin `alg` from the key, not the token header.
- Validate `iss`, `aud`, `exp`, `nbf`, `tid`; reject tokens whose `tid` is not the configured tenant for this deployment. Multi-tenant `common` authority is not allowed.
- JWKS cache: bounded size, refresh at most once per unknown `kid` per interval to avoid refresh-driven DoS; if the JWKS fetch fails and the cache is expired, fail closed (401 for the token, 503 where the cause is infrastructure per taxonomy).
- Cloud isolation: a Commercial-issued token presented to a Government deployment (and vice versa) fails on issuer; tests cover both directions. Never fall back to the other cloud's authority.
- Scope derivation must read only verified claims and the policy store; request headers, query, body, model output and cookies are never inputs. A test fuzzes these inputs.
- Cache keys: include cloud, customer_id, scope hash and policy version; a shared key across users is a cross-domain leak. Exports and search must use the same scope object, not a re-derived one.
- Search: the negative suite must verify the server-side filter is applied by the `AuthorizedSearch` fixture (PRP-03) and that the interface forbids a caller-supplied filter that widens scope. The Azure AI Search implementation arrives in PRP-10, which must re-run this suite.
- Audit before/after: record intent before the change and outcome after; a denied attempt is audited too (denied records). A failed audit write for a mutating action blocks the action (fail closed).
- Hash chain concurrency: appends need a per-partition sequence; use an ETag-guarded tail pointer or a single-writer partition to avoid forks; a fork is detected by chain verification.
- Emulator limits: the Cosmos emulator enforces no auth, so repository immutability here is by API surface; do not claim service-level immutability (C10).
- Pseudonymous principal ids: do not log object ids, UPNs or emails; redaction filter from PRP-05 must be extended only through PRP-05's owned files, so add test coverage here instead.
- TTL math uses an injectable clock; never `time.sleep` in tests.

### External references

- Entra access token validation: https://learn.microsoft.com/entra/identity-platform/access-tokens (validate issuer, audience, signature, lifetime; observed 2026-10-08).
- Entra national clouds: https://learn.microsoft.com/entra/identity-platform/authentication-national-cloud (Government authority `login.microsoftonline.us`).
- Entra app roles and group claims: https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps.
- JWT best current practices (RFC 8725): https://www.rfc-editor.org/rfc/rfc8725.
- OAuth 2.0 JWT access token profile (RFC 9068): https://www.rfc-editor.org/rfc/rfc9068.
- OWASP ASVS authorization chapter: https://owasp.org/www-project-application-security-verification-standard/.
- Cosmos DB RBAC and emulator limits: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026; no auth enforcement).
- Event Hubs geo-DR does not copy Entra RBAC: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06).
- NIST SP 800-53 Rev 5 AC and AU families (mapping is PRP-23): https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final.

## Implementation blueprint

Shared must-not-touch for every item (the "shared list"): root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`, `packages/contracts/**`, `packages/core/neurosphere_core/{errors,scope,paging,cloud,observability,clients}/` (PRP-05; import only), `services/api/neurosphere_api/{main.py,app.py,middleware/,health/}` (PRP-05), `frontend/**`, `.github/workflows/**`. New dependencies (a JWT library) are added in one serialized integrator commit with an ADR-0002 licence row.

### Item 1 — jwt-validation  [P]
- Deliverable: token extraction, signature and claims validation, JWKS fetch/cache with refresh rules, per-cloud issuer and audience configuration, dev-issuer helper gated on `NS_ENV=local`, typed `VerifiedClaims` model.
- Owned files (may edit): `packages/core/neurosphere_core/auth/jwt/`, `packages/core/tests/auth/jwt/`.
- Must NOT touch: `packages/core/neurosphere_core/auth/scope/` (item 2), `auth/revocation/` (item 5), `audit/` (item 4), `services/**`, `tests/security/**`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - Missing token, malformed token, wrong audience, wrong issuer, wrong tenant, expired, not-yet-valid, unknown kid, `alg=none` and HMAC-with-public-key tokens each return 401 (table-driven).
  - Dev issuer token accepted only when `NS_ENV=local`; with `NS_ENV=prod` it is rejected (test) and startup with a dev issuer configured fails.
  - Commercial token against Government config and the reverse both return 401.
  - JWKS refresh is rate limited; failure with expired cache fails closed.
- Pattern references: gotchas above; RFC 8725; C3, C4.
- Tests to write: `packages/core/tests/auth/jwt/test_validation.py`, `test_jwks_cache.py`, `test_dev_issuer.py`, `test_cloud_isolation.py`.

### Item 2 — scope-derivation
- Deliverable: `IdentityScope.from_verified_claims`, policy repository interface and Cosmos implementation, role-to-permission map, resource-scoped grants with expiry, caller-input ignoring guarantee, pseudonymous principal id function.
- Owned files (may edit): `packages/core/neurosphere_core/auth/scope/`, `packages/core/tests/auth/scope/`.
- Must NOT touch: `packages/core/neurosphere_core/auth/jwt/` (item 1), `auth/revocation/` (item 5), `scope/` type package (PRP-05), `services/**`; plus the shared list.
- Depends on: item 1.
- Acceptance criteria:
  - A forged `domain_id` in header, query, body or cookie never changes the derived scope (property test with random injected values).
  - Viewer, Analyst, Steward, Admin, Auditor each get exactly the documented permission set; Analyst/Pro never implies Admin; Auditor has no data-read permission.
  - Resource-scoped grants narrow to named resources and expire at the stated time; expired grants contribute nothing.
  - A missing policy document yields an empty grant set (deny); a store exception is raised as `dependency_transient` and never converted to an empty scope.
- Pattern references: C5-C9, C15; frozen Pydantic models.
- Tests to write: `packages/core/tests/auth/scope/test_derivation.py`, `test_roles.py`, `test_grants.py`, `test_principal_pseudonym.py`.

### Item 3 — policy-middleware
- Deliverable: FastAPI dependencies `current_scope` and `require(permission, resource=None)`, public-route allowlist check, route inventory test that every non-public route declares a permission, scope-hash cache key helper, policy-store error mapping to 503.
- Owned files (may edit): `services/api/neurosphere_api/authz/`, `services/api/tests/authz/`.
- Must NOT touch: `services/api/neurosphere_api/audit/` (item 4), `packages/core/neurosphere_core/auth/**` (items 1, 2, 5; import only), `tests/security/**`; plus the shared list.
- Depends on: item 2.
- Acceptance criteria:
  - Insufficient scope returns 403 with taxonomy body and reason code; missing or invalid token returns 401.
  - Policy store outage or timeout returns 503, not 200 and not 403-as-allow; there is no allow-on-error branch (AST test scans the module for exception handlers returning allow).
  - Route inventory test fails when a new route has no permission and is not allowlisted.
  - Cache key helper output differs across scope, cloud and policy version, and never includes token material (test).
- Pattern references: dependency-per-route rule; C9, C14; fail-closed rule.
- Tests to write: `services/api/tests/authz/test_require.py`, `test_fail_closed.py`, `test_route_inventory.py`, `test_cache_key.py`.

### Item 4 — audit-store  [P]
- Deliverable: audit repository (append, read by range, verify chain), hash-chain implementation, allow/deny/before/after record builders over the PRP-01 `AuditRecord`, SIEM export hook interface with a file/stdout reference sink, API routes for Auditor read and chain verify.
- Owned files (may edit): `packages/core/neurosphere_core/audit/`, `services/api/neurosphere_api/audit/`, `packages/core/tests/audit/`, `services/api/tests/audit/`.
- Must NOT touch: `packages/core/neurosphere_core/auth/**` (items 1, 2, 5), `services/api/neurosphere_api/authz/` (item 3), `tests/security/**`; plus the shared list.
- Depends on: none (uses PRP-05 clients and PRP-01 contracts).
- Acceptance criteria:
  - Repository exposes no update or delete; attempted update/delete through any public API raises `forbidden`; emulator test confirms no code path mutates a written record.
  - Chain verification passes on N appended records and reports the first tampered index when one record is altered or removed or reordered.
  - Concurrent appends on one partition never fork the chain (test with parallel writers).
  - Records contain no prompt/response bodies, tokens or raw object ids (scan test); a failed audit write for a mutating call raises, and the caller aborts.
- Pattern references: C10, C11; hash-compare rule.
- Tests to write: `packages/core/tests/audit/test_chain.py`, `test_immutability.py`, `test_redaction_scan.py`, `services/api/tests/audit/test_audit_routes.py`.

### Item 5 — revocation
- Deliverable: revocation list model and store (Cosmos, TTL), `is_revoked(principal, issued_at)` check wired into scope derivation through an interface, cache-invalidation hook, `PushSessionRegistry` protocol with `close_for_principal`, admin revoke operation (permissioned and audited via interfaces).
- Owned files (may edit): `packages/core/neurosphere_core/auth/revocation/`, `packages/core/tests/auth/revocation/`.
- Must NOT touch: `packages/core/neurosphere_core/auth/jwt/` (item 1), `auth/scope/` (item 2; item 2 consumes the interface, integration happens in item 6 fixtures), `audit/` (item 4), `services/**`; plus the shared list.
- Depends on: item 2.
- Acceptance criteria:
  - With a fake clock, a revoked principal gets 403 no later than the configured TTL after revocation; boundary just before and after TTL tested.
  - Revocation calls every registered cache invalidator and `close_for_principal` on registered push registries; a failing closer is logged and does not abort other closers.
  - Revocation store outage fails closed (503), consistent with the fail-closed rule.
- Pattern references: C12, C13.
- Tests to write: `packages/core/tests/auth/revocation/test_ttl.py`, `test_fanout.py`, `test_fail_closed.py`.

### Item 6 — abac-negative-suite
- Deliverable: cross-domain and cross-customer denial suite with shared fixtures: two customers, two domains each, principals per role including privileged; paths covered are API routes, `AuthorizedSearch` fixture, export function, scope-keyed cache, and the push registry interface; reason-tracked case table; coverage report that fails on removed cases.
- Owned files (may edit): `tests/security/authz/`.
- Must NOT touch: every non-test path (items 1-5 own the implementation); `tests/security/injection/` (PRP-12), `tests/security/egress/` (PRP-20), `tests/security/mcp/` (PRP-22); plus the shared list.
- Depends on: items 3, 4, 5.
- Acceptance criteria:
  - 100 percent of negative cases deny; the suite prints counts per path (API, search, export, cache, push) and fails if any path has zero cases.
  - Admin and Auditor principals cannot read another domain or customer without a scoped, unexpired grant; with such a grant they read only the granted resource.
  - A revoked principal is denied on every path after TTL; a policy store outage yields 503 on every path.
  - Every denial and every allow in the suite appears in the audit store with the correct decision.
- Pattern references: table-driven negative tests; C7, C13.
- Tests to write: `tests/security/authz/test_api_paths.py`, `test_search_paths.py`, `test_export_paths.py`, `test_cache_paths.py`, `test_push_interface.py`, `test_privileged_roles.py`, `conftest.py`.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
uv sync --frozen
uv run ruff check packages services tests
uv run pyright
uv run pytest packages/core/tests/auth packages/core/tests/audit services/api/tests/authz services/api/tests/audit -m "not integration and not live"
docker compose up -d --wait
uv run pytest tests/security/authz
gitleaks detect --no-banner --redact
```

The negative suite must report zero allowed cross-scope accesses; any allow is a blocking defect. No `scripts/gates/` live script is required. An optional Commercial Entra token smoke is **operator-approved, requires NS_LIVE_APPROVED=1** and, if built, belongs to `scripts/gates/` in a later change.

## Live and open gates

| Gate | Touch | Evidence that narrows it |
|---|---|---|
| G02 FedRAMP/DoD boundary and agency ATO | Feeds | Authorization design and tests only; no authorization claim; PRP-20/23 own the gate |
| G12 emulator parity | Narrows | Recorded deltas: Cosmos emulator has no auth enforcement and cannot prove audit immutability at service level; Event Hubs emulator lacks Entra |
| G01 service/feature/region/SKU matrix | Not touched | Government identity endpoints are configuration facts |

Open items to carry: live Entra validation on Commercial and on a Government tenant has not run; service-level audit immutability on real Cosmos (for example immutable storage or write-once configuration) is unverified.

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Frontend sign-in and role display (PRP-04). Action approval workflow and self-approval prohibition (PRP-17).
- The WebSocket gateway (PRP-18); only the registry interface exists here.
- MCP OAuth resource-server behavior and confused-deputy tests (PRP-22).
- Producer authentication at the ingest edge (PRP-07); that is service identity, not user JWT.
- Azure AI Search scope filter implementation (PRP-10); this PRP tests the fixture and the interface.
- Retention, legal hold and audit lifecycle rules (PRP-23); STRIDE threat model (PRP-12).
- Federation summaries authorization (PRP-21); copilot tool scope pass-through (PRP-19).
- Any compliance, FedRAMP or ATO claim.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Reviewer verdict (one pass, max one rework round):
- Deviations from blueprint and why:
- Descoped items:
- Open gates / untested live items:
- Follow-ups:
