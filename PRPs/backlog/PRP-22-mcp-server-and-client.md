---
name: prp-22-mcp-server-and-client
status: backlog
review: required
created: 2026-10-08
model: opus
phase: 3
ns: NS-09
depends_on: PRP-06, PRP-17, PRP-19
wave: W8
absorbs: P3.5
---

# PRP-22: MCP server and client

## Goal
Ship a scoped MCP server (tools and resources over the PRP-19 tool registry, OAuth 2.1 resource-server authorization) and an MCP client for approved external servers (explicit registration, manifest validation, SSRF allowlist), plus the admin API/UI for tool allowlisting and approval, and the security tests that prove no token passthrough, no confused deputy and no SSRF. It is for developers and agents that integrate through MCP, and for administrators who must approve what the platform connects to. It is Opus-grade and review-required because every defect here is an authorization or injection defect, in a protocol (spec 2026-07-28, Python `mcp` 2.3) whose security behaviour changed in v2. It lands in W8 because it reuses authz (PRP-06), the single action executor (PRP-17) and the tool registry (PRP-19).

> Scoped MCP server tools/resources for catalog, metrics, recommendations and approved actions; MCP client supports approved external servers with explicit registration. MCP connectivity does not discover every local agent or expose complete telemetry automatically. (NS-09)

> Validate OAuth audience/scope, prevent token passthrough/confused-deputy attacks, SSRF and untrusted tool manifests; allowlist endpoints and require approval for new tools. (NS-09)

> The same action API serves copilot, recommendation buttons, REST and MCP. Recheck current resource permission and policy at execution; bind confirmation to target/version/diff and expiry. (NS-06)

## Acceptance criteria
- [ ] Item 1: Given a bearer token whose audience is another resource, When it calls any MCP server endpoint, Then the request is rejected with 401; a valid token yields tools whose results are filtered by the server-derived `IdentityScope`; the protected-resource metadata endpoint serves RFC 9728 metadata; the server is constructed with `validate_token_resource=True` set explicitly (asserted by test).
- [ ] Item 2: Given a server URL that is not registered, When the client is asked to connect, Then it is refused; given a registered URL that resolves to a loopback, link-local, private, CGNAT or metadata address, Then it is blocked.
- [ ] Item 3: Given a registered server that advertises a new tool, When the tool list is synced, Then the tool is disabled until an administrator approves it; a changed tool description or schema revokes approval until re-approved.
- [ ] Item 4: Given the same action inputs through REST and through the MCP action tool, When the intent is drafted, Then both produce the identical intent hash; confused-deputy and injection corpus cases all deny or abstain.
- [ ] PRP exit: items 1-4 green under `verify-gates -Mode full`; G08 row updated with the authorization-spec test results; reviewer finds no token-passthrough path.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/required; opus | opus, review required (D6: risk concentrated in contracts, authz, actions, MCP) |
| 2 | SDK and spec | v1 SDK; v2 | Python `mcp` 2.3 against spec 2026-07-28. The TypeScript SDK 2.x packages (`@modelcontextprotocol/server`, `@modelcontextprotocol/client` 2.3) are pinned for the TS connector SDK (PRP-09) and are not used here. `@modelcontextprotocol/sdk` 1.x is not imported anywhere |
| 3 | Server authorization | custom; SDK resource server | OAuth 2.1 resource-server support in the SDK, with RFC 9728 protected-resource metadata and `validate_token_resource=True` set explicitly (the SDK does not default it for us). JWT validation, issuers and audiences come from `neurosphere_core.auth.jwt` (PRP-06), including cloud-specific values |
| 4 | Dynamic Client Registration | support; pre-register | DCR is deprecated and is not implemented. MCP clients of the server are pre-registered in Entra |
| 5 | Token passthrough | forward user token downstream; derive | Forbidden. The server never forwards an inbound token to any downstream service. Tools run in-process against core services with an `IdentityScope` derived from the validated token and the policy store |
| 6 | Transports | stdio and HTTP; HTTP only | stdio is never authenticated per spec, so the hosted server exposes streamable HTTP only. A stdio dev entry point exists only when `NS_ENV=local` and the dev issuer is active; it refuses otherwise |
| 7 | Scope derivation | trust token claims for domain; derive | Same derivation as REST: caller- or model-supplied `domain_id`/`customer_id` arguments to any tool are ignored. Same `IdentityScope` object as REST, search, cache keys and exports |
| 8 | Tool surface | everything; allowlist | Read tools/resources for catalog, metrics, recommendations over the PRP-19 registry; action tools only as draft/validate/confirm/status calls into the PRP-17 API. MCP cannot self-approve; confirmation and approvals follow the same state machine and permission recheck at execution |
| 9 | Client registration | auto-discover; explicit | Explicit administrator registration of exact HTTPS URLs. No discovery, no wildcard hosts, redirects not followed unless the target re-passes the full SSRF check |
| 10 | SSRF policy | allow private with override; block | Blocked after DNS resolution (defends rebinding) for: loopback (127.0.0.0/8, ::1), link-local (169.254.0.0/16 including 169.254.169.254, fe80::/10), RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), unique local (fc00::/7), CGNAT (100.64.0.0/10), Azure platform address 168.63.129.16, and well-known metadata hostnames. No per-server override in this PRP; customers needing a private MCP server are a recorded follow-up |
| 11 | Untrusted manifests | trust; hash and approve | Manifests and tool descriptions from external servers are untrusted input: schema-validated, size-bounded, hashed. New tools start disabled. A hash change revokes approval. Tool outputs are data, never instructions, and external tool results cannot create or confirm an action intent |
| 12 | Government | allow all; gate | Client registration in a Government deployment is limited to servers inside the approved boundary; availability follows the capability matrix (Foundry Agent Service MCP servers are listed for Government; other combinations unverified). Never route Government data to a Commercial MCP server |
| 13 | Registry store and G08 row | any; items own | Item 2 owns the registry model and store in `neurosphere_core.mcp`. Item 4 owns the G08 row of `docs/RESEARCH-AND-GATES.md` only |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3.
- `docs/PRD.md` - NS-09 and NS-06 text.
- `docs/ARCHITECTURE.md` - action plane and trust-boundary diagrams.
- `docs/RESEARCH-AND-GATES.md` - MCP finding (retrieved 2026-10-08), G08, G05.
- `docs/adr/0002-stack-pins.md` - `mcp` 2.3, `@modelcontextprotocol/server` and `/client` 2.3, FastAPI 0.143, pydantic 2.14.
- `docs/DECISIONS-LOG.md` - D6, D7, D8.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-05: `neurosphere_core.errors`, `.../scope/`, `.../clients/`, router registry.
- Created by PRP-06: `neurosphere_core.auth.jwt`, `.../auth/scope`, `.../auth/revocation`, `neurosphere_api.authz`, `neurosphere_core.audit`.
- Created by PRP-12: `tests/security/injection/` (injection corpus and harness), `docs/security/threat-model.md` (SSRF, confused deputy abuse cases).
- Created by PRP-17: action API (`services/api/neurosphere_api/actions/`), intent hash, `neurosphere_core.actions`.
- Created by PRP-19: `packages/core/neurosphere_core/copilot/tools/` registry.
- Created by PRP-04: frontend shell, design system and API client used by the admin UI.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (here `mcp/server`, `mcp/client`, `mcp/admin`); async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`unauthorized`, `forbidden`, `capability_unavailable`, `invalid_schema`).
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.live` and `pytest.mark.integration` markers declared in root `pyproject.toml`.
- TS strict with `@fluentui/react-components`, Vitest + Testing Library, Playwright under `frontend/tests/e2e`; hidden navigation is not authorization, the API must deny.

### Conventions
- ruff line 100, py312, S rules on; pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; any live script under `scripts/gates/` refuses without `NS_LIVE_APPROVED=1`. This PRP has none.
- Forward slashes only in commands.

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
- PRP-specific: `validate_token_resource` must be set explicitly (do not rely on a default), and a test must fail if it is absent or false. The audience check and the resource check are separate; test both.
- PRP-specific: a token valid for NeuroSphere's REST API is not automatically valid for the MCP resource. Use a distinct resource identifier and test cross-use in both directions.
- PRP-specific: token passthrough is the confused-deputy path. The server holds no broad downstream identity that a low-privilege caller can borrow: every tool call recomputes scope from the caller's token and the policy store.
- PRP-specific: stdio is never authenticated. Do not wrap production tools in a stdio launcher for convenience.
- PRP-specific: MCP connectivity does not discover local agents or provide complete telemetry; docs and tool descriptions must not imply it.
- PRP-specific: SSRF checks apply to the resolved IP, to every redirect hop and to the metadata hostnames; checking only the URL string is insufficient.
- PRP-specific: action tools return a draft and a diff; a model cannot confirm its own draft. Confirmation hash binds target, version, diff and expiry exactly as in REST.
- PRP-specific: DCR is deprecated; do not add it to make a client work.

### External references
- MCP versioning and current revision 2026-07-28: https://modelcontextprotocol.io/specification/versioning (retrieved 2026-10-08).
- Python SDK 2.x (OAuth 2.1 resource-server support, `validate_token_resource`, DCR deprecation, stdio unauthenticated): https://py.sdk.modelcontextprotocol.io/ (retrieved 2026-10-08).
- TypeScript SDK 2.x packages: https://github.com/modelcontextprotocol/typescript-sdk (docs/adr/0002-stack-pins.md, observed 2026-10-08).
- RFC 9728 OAuth 2.0 Protected Resource Metadata: https://www.rfc-editor.org/rfc/rfc9728 (cited by the SDK finding of 2026-10-08).
- Foundry Agent Service in Government (MCP servers listed): https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government (retrieved 2026-10-08).
- Version pins: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - mcp-server  [P]
- Deliverable: MCP server exposing scoped tools/resources over the PRP-19 registry and PRP-17 action API, as an OAuth 2.1 resource server with RFC 9728 metadata, explicit `validate_token_resource=True`, audience and scope validation, and no token passthrough.
- Owned files (may edit): `services/api/neurosphere_api/mcp/server/`.
- Must NOT touch: `services/api/neurosphere_api/mcp/client/`, `services/api/neurosphere_api/mcp/admin/`, `packages/core/neurosphere_core/mcp/`, `packages/core/neurosphere_core/copilot/tools/` (PRP-19), `services/api/neurosphere_api/actions/` (PRP-17), `packages/core/neurosphere_core/auth/` (PRP-06), root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Token for another audience: 401; token missing the required scope: 403; expired or revoked principal: denied within the revocation TTL.
  - Every tool uses the derived `IdentityScope`; a model-supplied `domain_id` argument is ignored (test).
  - No code path forwards the inbound Authorization header (static check plus test with a recording downstream).
  - Protected-resource metadata is served and lists the authorization server for the active cloud profile; stdio entry point refuses unless `NS_ENV=local`.
- Pattern references: `require(permission)`; PRP-19 registry scope pass-through; JWT validation from PRP-06.
- Tests to write: `services/api/tests/mcp/test_server_auth.py`, `services/api/tests/mcp/test_server_scope.py`, `services/api/tests/mcp/test_server_no_passthrough.py`.

### Item 2 - mcp-client  [P]
- Deliverable: MCP client for approved external servers: explicit registration model and store, manifest validation, SSRF-safe connector, bounded results.
- Owned files (may edit): `services/api/neurosphere_api/mcp/client/`, `packages/core/neurosphere_core/mcp/`.
- Must NOT touch: `services/api/neurosphere_api/mcp/server/`, `services/api/neurosphere_api/mcp/admin/`, `packages/core/neurosphere_core/clients/` (PRP-05), `tests/security/mcp/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Unregistered server refused with `forbidden`; URL resolving to any blocked range or metadata host is refused (corpus test over the ranges in clarification 10, including DNS rebinding and redirect-to-private cases).
  - Manifest is schema-validated, size-bounded and hashed; oversized or malformed manifests are rejected with `invalid_schema`.
  - Tool outputs are returned as data with provenance; they cannot create or confirm an action intent.
  - Government profile refuses servers outside the approved boundary list.
- Pattern references: `neurosphere_core.errors`; async client factories.
- Tests to write: `packages/core/tests/mcp/test_ssrf.py`, `packages/core/tests/mcp/test_registry.py`, `services/api/tests/mcp/test_client.py`.

### Item 3 - registration-admin
- Deliverable: administrator API and UI to register servers and to allowlist and approve tools, with audit records.
- Owned files (may edit): `services/api/neurosphere_api/mcp/admin/`, `frontend/src/features/mcp-admin/`.
- Must NOT touch: `services/api/neurosphere_api/mcp/client/`, `packages/core/neurosphere_core/mcp/`, `frontend/src/features/workspaces/`, `frontend/src/api/`, `frontend/src/design-system/`, root `pyproject.toml`.
- Depends on: Item 2.
- Acceptance criteria:
  - New tool is disabled until an authorized administrator approves it; approval is audited with actor, tool hash and time.
  - A changed tool hash revokes approval and the UI shows the diff before re-approval.
  - The API enforces permission server-side; a user without the permission gets 403 even if they know the route (e2e test), and the nav item is cosmetic only.
- Pattern references: `require(permission)`; Fluent UI v9 components; typed API client from PRP-04.
- Tests to write: `services/api/tests/mcp/test_admin.py`, `frontend/src/features/mcp-admin/mcp-admin.test.tsx`, `frontend/tests/e2e/mcp-admin.spec.ts`.

### Item 4 - integration-and-security-tests
- Deliverable: client/server integration tests, confused-deputy tests, injection corpus run against MCP, intent-hash parity test, and the G08 row update.
- Owned files (may edit): `tests/security/mcp/`, `docs/RESEARCH-AND-GATES.md` (G08 row only).
- Must NOT touch: `tests/security/injection/` (PRP-12), `tests/security/authz/` (PRP-06), `services/api/neurosphere_api/mcp/`, `packages/core/neurosphere_core/mcp/`, any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: Items 1, 2, 3.
- Acceptance criteria:
  - An action drafted through MCP produces the same intent hash as the REST call with identical inputs.
  - Confused-deputy suite: token for another resource, token minted for the MCP client app but not the user, model-supplied `domain_id`, replayed token after revocation: all denied.
  - Injection corpus (PRP-12 harness) run through client tool outputs: 0 overscoped retrievals, 0 action intents created from external tool output.
  - G08 row updated to state which authorization-spec tests ran and their results.
- Pattern references: PRP-12 injection harness; PRP-17 intent hash function.
- Tests to write: `tests/security/mcp/test_confused_deputy.py`, `tests/security/mcp/test_intent_hash_parity.py`, `tests/security/mcp/test_injection_via_tool_output.py`, `tests/security/mcp/test_client_server_roundtrip.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest packages/core/tests/mcp services/api/tests/mcp
python -m pytest tests/security/mcp
pnpm --filter frontend test
pnpm --filter frontend exec playwright test frontend/tests/e2e/mcp-admin.spec.ts
docker compose --profile app up -d --wait
python -m pytest -m integration tests/security/mcp/test_client_server_roundtrip.py
```

## Live and open gates
- G08 (dependency/MCP versions and licences): item 4 records MCP authorization-spec test results in the G08 row; it stays NARROWED, not closed, because the spec revision will move.
- G05 (model swap compatibility): untouched; the MCP action path reuses the PRP-17 executor and adds no new write capability.
- G01/G02: Entra audience behaviour and MCP availability in Government are unverified; no live Government test exists (D7), so Government MCP use is OPEN.
- No live Azure item in this PRP; no paid model calls.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Dynamic Client Registration; stdio transport for hosted use; an unauthenticated mode.
- Any MCP tool that executes outside the PRP-17 executor, or any catalog-only pretend change.
- Discovery of local agents through MCP; complete telemetry exposure through MCP.
- A TypeScript MCP server; use of `@modelcontextprotocol/sdk` 1.x.
- Per-server SSRF overrides for private networks (follow-up).
- GraphQL (optional after bounded-query/security review); copilot orchestration (PRP-19).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Reviewer verdict (token passthrough, SSRF, confused deputy):
- Open gates (Government MCP, G08 spec drift):
- Follow-ups (private-network MCP servers):
