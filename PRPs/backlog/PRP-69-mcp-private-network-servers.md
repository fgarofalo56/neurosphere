---
name: PRP-69-mcp-private-network-servers
status: backlog
priority: P3
order: 57
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-09, NS-08
depends_on: []
wave: W20
branch: prp-69-mcp-private-network
allow_parallel: true
issues: [267, 115]
---

# PRP-69: Private-network MCP servers (per-server SSRF override)

## Goal
Let a customer register an external MCP server that lives inside its own private network (private endpoint, VNet) without weakening the SSRF defences every other registration relies on. Today the MCP client refuses any server whose host resolves to a private, loopback, link-local, CGNAT or metadata address, with no override (PRP-22 clarification 10), so private MCP servers cannot be used at all (#115). This PRP first records the design in an ADR (exact host plus CIDR, administrator-approved and audited, its interaction with DNS-rebinding pinning, the Government boundary and the threat model), and only after the owner accepts that ADR in the session implements it in the core SSRF policy, the client, the admin API and the admin page. It is for administrators of customer-hosted deployments. It is Opus and review-required because a defect here is an SSRF defect against the deployment's own network.

Out of scope: the MCP resource server (`services/api/neurosphere_api/mcp/server/**`, unchanged); Helm, Bicep and App Service network changes such as egress allowlist entries for a private CIDR (PRP-67 owns `infra/**` in W20; this PRP documents the operator step only); stored feature settings (PRP-45 shipped them for the MCP server; a stored switch for this feature is a follow-up); the deployment-scoped admin role itself (PRP-48); live Government runs (no Government subscription, OPEN as in PRP-64).

## Why
- `packages/core/neurosphere_core/mcp/ssrf.py:25` says "There is no per-server override"; `:59-81` blocks 10/8, 172.16/12, 192.168/16 and 100.64/10 next to metadata and loopback, and `vet_target` (`:182-207`) refuses the target when any resolved address is blocked.
- `PRPs/shipped/PRP-22-mcp-server-and-client.md:52` (clarification 10) and `:198` (NOT building) defer the override; `:271-272` files it as #115. The issue asks for an exact host plus CIDR, administrator-approved and audited, and for the DNS-rebinding, Government boundary and threat-model interactions to be designed.
- `packages/core/neurosphere_core/mcp/registry.py:82-125` (`new_registration`) refuses blocked IP literals at registration; `RegisteredServer` (`models.py:171-196`) has no field that could carry an override.
- `McpClientPolicy` (`models.py:228-253`) knows only the cloud and the Government host suffixes; it is built at `services/api/neurosphere_api/runtime/builders/planes.py:372` from the cloud alone, so there is no deployment switch.
- `docs/security/threat-model.md:342-359` (AC-3) names private endpoints (Cosmos, Key Vault, Event Hubs) as SSRF targets, and `docs/security/dfd/ssrf.md` defence S4 blocks private ranges outright: an override must not reopen the deployment's own data plane.
- `packages/core/neurosphere_core/mcp/urls.py:61-84` refuses `.internal`, `.local`, `.home.arpa` and single-label names before DNS; private DNS zones often use such names, so the ADR must say whether the override touches hostname rules.

## Acceptance criteria
- [ ] `docs/adr/0009-mcp-private-network-servers.md` exists, decides every row marked ADR in the Clarifications table, cites the code and threat-model rows above, and carries `Status: accepted` with the owner's name and date. STOP POINT: items 2 to 7 start only after the owner accepts the ADR in the session; if the owner does not, the PRP ships the ADR as `proposed` and records items 2 to 7 as descoped.
- [ ] Given no override on a server (the default), when it connects, then behaviour is unchanged: the existing suites `packages/core/tests/mcp_core/test_mcp_ssrf.py`, `services/api/tests/mcp_api/test_client.py` and `tests/security/mcp/` pass without edits.
- [ ] Given a server with an override for its exact host and CIDR list and the deployment switch on, when the host resolves only to public addresses or addresses inside the listed CIDRs, then the connection is pinned to those vetted addresses (resolve once, never re-resolve); when any address is outside both, the whole target is refused with `ssrf_blocked_address`.
- [ ] Never-overridable addresses (metadata 169.254.169.254, platform 168.63.129.16, loopback, link-local, unspecified, multicast, documentation and reserved ranges, and every range the ADR keeps closed) are refused even when inside a listed CIDR, and a CIDR that overlaps them, or is not inside the overridable ranges, is refused when the override is set.
- [ ] An override is bound to one server id and its exact host: another server, a changed URL or a redirect target cannot use it; changing a server's URL clears its override.
- [ ] With the deployment switch off (default), an override cannot be set (refused with a stable code) and any stored override is ignored at connect time; the server view says so.
- [ ] Setting and clearing an override are separate audited mutations through the existing MCP admin audit chain; a refused attempt is audited; the permission is the one the ADR fixes; `If-Match` is honoured like `PATCH /servers/{server_id}`.
- [ ] Government: the override never lets a Government deployment reach a host outside the approved boundary (`check_boundary` still runs) and never routes to a Commercial host; a test pins this.
- [ ] Admin page: the MCP server detail page shows the override and lets an administrator set or clear it after a confirmation that shows the exact host and CIDRs.
- [ ] `docs/security/threat-model.md` AC-3 and A4 and `docs/security/dfd/ssrf.md` describe the override, its limits and its tests; an operator runbook states the network step (egress allowlist entry) the product cannot do itself.

PRP exit: every box ticked or, if the ADR is not accepted, the ADR merged as `proposed` with items 2 to 7 descoped in the completion note; review APPROVED; Validation gates green; PR open, CI green; #115 closed only if items 2 to 7 shipped.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Override shape (ADR) | (a) per server: exact host plus a list of CIDRs; (b) deployment-wide private CIDR allowlist; (c) per-server "allow private" flag | ASSUMPTION: (a), as #115 proposes. (b) lets any registered server reach the whole list; (c) has no address bound. |
| 2 | Which ranges an override may open (ADR) | (a) RFC 1918 and fc00::/7 only; (b) also CGNAT 100.64/10; (c) any non-public range | ASSUMPTION: (a). Metadata, 168.63.129.16, loopback, link-local, multicast, documentation, reserved, NAT64-embedded blocked addresses stay closed in every option. CGNAT is offered to the owner, not assumed. |
| 3 | Hostname rules (`.internal`, `.local`, single-label) (ADR) | unchanged; overridable per server | ASSUMPTION: unchanged; the administrator registers a name outside the reserved suffixes. The override relaxes address checks only. |
| 4 | IP-literal URLs inside a private CIDR (ADR) | allow; refuse | ASSUMPTION: refuse; a DNS name keeps SNI and certificate verification against a name (`transport.py:6-9`). |
| 5 | DNS rebinding | keep resolve-once-and-pin; re-resolve per request | Keep: every resolved address must pass (public, or inside the server's CIDRs and not never-overridable), the transport connects only to vetted addresses (`ssrf.py:1-8`, `transport.py:82-130`). Not an assumption: it follows from the shipped design. |
| 6 | Approval and permission (ADR) | (a) `config.manage` at deployment scope (PRP-48), one administrator, audited; (b) a new permission (Tier-2 append to `permissions.py`); (c) maker-checker: a second administrator approves | ASSUMPTION: (a) with a separate audited operation; (b) and (c) offered to the owner. Choosing (b) adds a Tier-2 append and the inventories in `tier2_appends`. |
| 7 | Deployment switch (ADR) | env setting, default off; stored setting (PRP-45 store); none | ASSUMPTION: an `NS_`-prefixed boolean in the API runtime settings, default off; its exact name is fixed in the ADR and listed under "Env vars for the operator". |
| 8 | Government boundary (ADR) | (a) boundary rule unchanged, the override must also pass `check_boundary`; (b) the override exempts the host from the boundary; (c) feature disabled in Government | ASSUMPTION: (a). It never bridges Government to Commercial (CLAUDE.md hard constraint). (c) offered if the owner prefers. |
| 9 | Overlap with the deployment's own private endpoints (ADR) | (a) document and rely on the egress allowlist and the exact host bind; (b) refuse CIDRs that overlap an operator-declared reserved list | ASSUMPTION: (a) in this PRP, with (b) recorded as the stronger option; the app does not know its own subnet ranges today. |
| 10 | Implementation without an accepted ADR | proceed on assumptions; stop | Stop (Acceptance box 1). |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/mcp/ssrf.py` - `_V4`, `_V6`, `blocked_address_reason`, `vet_target`, `VettedTarget`.
- `packages/core/neurosphere_core/mcp/urls.py:61-84,203-218` - hostname blocks, `check_hostname_allowed`.
- `packages/core/neurosphere_core/mcp/models.py:171-196,228-253` - `RegisteredServer`, `McpClientPolicy`.
- `packages/core/neurosphere_core/mcp/registry.py:73-125,286-308` - `check_boundary`, `new_registration`, `check_callable`.
- `packages/core/neurosphere_core/mcp/service.py:36-130` - `McpRegistry` operations (`register`, `update`).
- `packages/core/neurosphere_core/mcp/cosmos_store.py:69-84` - `_from_row`, `_body` (stored shape).
- `services/api/neurosphere_api/mcp/client/connector.py:169-200` - `_check_server`, `_session` calling `vet_target`.
- `services/api/neurosphere_api/mcp/client/transport.py:82-130` - `PinnedNetworkBackend`.
- `services/api/neurosphere_api/mcp/admin/{router,service,models}.py` - routes, `_audited`, `ServerView`.
- `services/api/neurosphere_api/runtime/builders/planes.py:366-375` - `_mcp_admin` composition.
- `docs/security/threat-model.md:216-243,342-359` and `docs/security/dfd/ssrf.md`.
- `PRPs/shipped/PRP-22-mcp-server-and-client.md:51-54,105,193-198` - decisions 9, 10, 12 and the SSRF gotcha.

### Interfaces consumed
- `config.manage` and the deployment-scoped admin dependency (PRP-48, shipped by W20); `run_audited_mutation` and the MCP admin audit chain (PRP-22).
- `McpRegistry`, `ExternalMcpClient`, `vet_target`, `Resolver` (PRP-22).
- API runtime settings classes (`runtime/settings.py`, PRP-29 wire contract).

### Interfaces provided
- ADR-0009 (`docs/adr/0009-mcp-private-network-servers.md`).
- Core: a `PrivateNetworkOverride` model (exact host, CIDR tuple, set by, set at) on `RegisteredServer`; `vet_target(..., override=...)`; a `McpClientPolicy` field for the deployment switch (names final in the ADR).
- API: set and clear routes under `/api/v1/mcp/admin/servers/{server_id}/` (paths final in the ADR) and override fields on `ServerView`; new stable error codes in `neurosphere_core.mcp.errors`.
- Audit operations `mcp.server.network_override.set` and `.clear` (names final in the ADR).

### Patterns to match
- `packages/core/neurosphere_core/mcp/ssrf.py:59-127` - explicit network tables, no reliance on `ipaddress` registry flags.
- `services/api/neurosphere_api/mcp/admin/service.py:219-276` - audited register/update, refused-attempt audit.
- `services/api/neurosphere_api/mcp/admin/router.py:132-151` - `PATCH` with `If-Match` and ETag.
- `packages/core/tests/mcp_core/test_mcp_ssrf.py` with `mcp_core_helpers.StubResolver` - stubbed DNS, no network.
- `frontend/src/features/mcp-admin/McpServerDetailPage.tsx` and `frontend/tests/mock-api/mcpAdmin.ts`.

### Gotchas
- `RegisteredServer` is `extra="forbid"` and frozen; the new field must be optional with a `None` default so stored documents without it still load (test a pre-PRP document through `cosmos_store._from_row`).
- Next free ADR number at writing is 0009 (`docs/adr/` ends at 0008); re-list the directory at session start and take the next free number if another PRP used it.
- Check the CIDR against never-overridable ranges at set time and every resolved address at connect time; set-time validation alone is not a defence.
- CodeQL fails on hostname substring checks: compare parsed hosts and use `ipaddress` network membership, never string prefixes.
- Changing `ServerView` or adding routes regenerates `services/api/openapi.json` (Tier 3) and the API reference; a contract model used as `response_model` renames components.
- The real-stack SSRF refusal with real DNS stayed OPEN in PRP-22 (the resolver sinkholed the test name); keep every new test on `StubResolver`.
- Run `snyk_code_scan` on the changed core and API MCP modules (user rule) and record the result.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - docs/adr/0009-mcp-private-network-servers.md
  - packages/core/neurosphere_core/mcp/**
  - packages/core/tests/mcp_core/test_mcp_private_network.py
  - services/api/neurosphere_api/mcp/client/**
  - services/api/neurosphere_api/mcp/admin/**
  - services/api/tests/mcp_api/test_client_private_network.py
  - services/api/tests/mcp_api/test_admin_private_network.py
  - frontend/src/features/mcp-admin/**
  - frontend/tests/mock-api/mcpAdmin.ts
  - tests/security/mcp/test_private_network_override.py
  - docs/security/threat-model.md
  - docs/security/dfd/ssrf.md
  - docs/runbooks/mcp-private-network.md
tier1: []
tier2_appends:
  - mkdocs.yml
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
must_not_touch:
  - services/api/neurosphere_api/mcp/server/**
  - services/api/neurosphere_api/health/probes.py
  - scripts/sandbox/**
  - infra/**
  - packages/contracts/**
  - packages/core/neurosphere_core/audit/**
```

`services/api/neurosphere_api/runtime/builders/planes.py` (Tier 1, API composition body) is not granted to this PRP; item 5 is `[serial-after: PRP-67]` and needs the orchestrator to confirm no other W20 PRP holds it.

## Implementation blueprint

Parallelization: item 1 first and alone (stop point). Item 2 after 1. Items 3 and 4 after 2 and independent of each other [P]. Item 5 after 2 (serial-after PRP-67). Item 6 after 4. Item 7 after 3 to 6. Item 8 closes out.

### Item 1 - ADR-0009 (stop point)
- Deliverable: `docs/adr/0009-mcp-private-network-servers.md` in the ADR-0008 shape (Status, Date, Deciders, Relates to, Context, Options, Criteria, Decision, Consequences) deciding Clarifications rows 1-4 and 6-9, naming the setting, routes, error codes and audit operations; `mkdocs.yml` nav line. Present it to the owner; record acceptance or rejection in the Execution state.
- Owned files: `docs/adr/0009-mcp-private-network-servers.md` (new), `mkdocs.yml` (one nav line).
- Must NOT touch: code.
- Depends on: none.
- Acceptance criteria: Acceptance box 1; every Clarifications ASSUMPTION is either confirmed or replaced by the owner's choice in the ADR.
- Tests: `uv run pytest -q tests/docs`; `python scripts/validate_planning.py`.
- Pattern references: `docs/adr/0008-docs-site-tool.md`.

### Item 2 - Core policy: override model and vetting
- Deliverable: `PrivateNetworkOverride` model, optional `RegisteredServer` field, set-time validation (exact host equals the server host, CIDRs inside the overridable ranges, no overlap with never-overridable ranges, bounded count), `vet_target` accepting an override, policy switch field, registry/service operations to set and clear (clear on URL change), error codes.
- Owned files: `packages/core/neurosphere_core/mcp/**`, `packages/core/tests/mcp_core/test_mcp_private_network.py` (new).
- Must NOT touch: `test_mcp_ssrf.py` expectations (they must pass unchanged), contracts.
- Depends on: item 1 accepted.
- Acceptance criteria: Acceptance boxes 2 to 6 at the core level; Government case (box 8) through `check_boundary`.
- Tests: `packages/core/tests/mcp_core/test_mcp_private_network.py` (rebinding answer mixing an in-CIDR and a metadata address, CIDR containing 168.63.129.16, IPv4-mapped and NAT64 forms, other server id, switch off, stored document without the field).
- Pattern references: `ssrf.py:59-127,182-207`; `registry.py:82-125`.

### Item 3 - Client wiring  [P]
- Deliverable: `ExternalMcpClient` passes the server's override to `vet_target` only when the policy switch is on; pinned transport unchanged.
- Owned files: `services/api/neurosphere_api/mcp/client/**`, `services/api/tests/mcp_api/test_client_private_network.py` (new).
- Must NOT touch: `transport.py` pinning logic beyond what the override needs.
- Depends on: item 2.
- Acceptance criteria: boxes 3 and 6 end to end through the client with `StubResolver`; existing `test_client.py` unchanged and green.
- Tests: `services/api/tests/mcp_api/test_client_private_network.py`.
- Pattern references: `connector.py:169-200`; `services/api/tests/mcp_api/client_fixtures.py`.

### Item 4 - Admin API  [P]
- Deliverable: set and clear routes, audited through `_audited` (refusals audited), `If-Match`, override fields on `ServerView`; route inventories updated (Tier 2).
- Owned files: `services/api/neurosphere_api/mcp/admin/**`, `services/api/tests/mcp_api/test_admin_private_network.py` (new), the Tier-2 inventories.
- Must NOT touch: the permission dependency PRP-48 placed on the router (reuse it).
- Depends on: item 2.
- Acceptance criteria: box 7; a viewer gets 403, an unscoped admin per PRP-48 rules; audit records carry no URL beyond what existing records carry.
- Tests: `services/api/tests/mcp_api/test_admin_private_network.py`; `services/api/tests/authz/test_route_inventory.py`.
- Pattern references: `admin/service.py:219-276`; `admin/router.py:132-151`.

### Item 5 - Deployment switch composition  [serial-after: PRP-67]
- Deliverable: the ADR-named setting as a new field in `runtime/settings.py` (Tier 2) and the one-line `McpClientPolicy(...)` change in `planes.py:372`; env-clearing conftests updated where they list MCP names.
- Owned files: `services/api/neurosphere_api/runtime/settings.py` (new field only); `runtime/builders/planes.py` line 372 only, once the orchestrator confirms it.
- Must NOT touch: other builder bodies, Helm, Bicep.
- Depends on: item 2; PRP-67 merged or confirmed not to touch `planes.py`.
- Acceptance criteria: box 6 through the composed app (switch unset means off); `/readyz` unchanged.
- Tests: `services/api/tests/runtime_planes`.
- Pattern references: `runtime/settings.py:121` (`AuditSiemSettings` shape).

### Item 6 - Admin page
- Deliverable: override panel on the server detail page, set/clear with a confirmation dialog showing exact host and CIDRs, disabled state when the switch is off; mock API handlers.
- Owned files: `frontend/src/features/mcp-admin/**`, `frontend/tests/mock-api/mcpAdmin.ts`.
- Depends on: item 4.
- Acceptance criteria: box 9; a11y unchanged; no free-text CIDR is sent without client-side format checks (server stays authoritative).
- Tests: `frontend/src/features/mcp-admin/mcp-admin.test.tsx`.
- Pattern references: `McpServerDetailPage.tsx`; Fluent dialog tests query with `hidden: true`.

### Item 7 - Security suite, threat model and runbook
- Deliverable: `tests/security/mcp/test_private_network_override.py` (rebinding, cross-server reuse, Government, switch off, never-overridable inside CIDR); threat-model AC-3 and A4 rows and test table; DFD S4 text; `docs/runbooks/mcp-private-network.md` with the egress allowlist step (Helm `networkPolicy.egressAllowlist`, NSG) and what the product does not do.
- Owned files: those paths, plus `mkdocs.yml` nav line (Tier 2).
- Depends on: items 3 to 6.
- Acceptance criteria: box 10; every threat-model test path exists.
- Tests: `tests/security/mcp`; `tests/docs`.
- Pattern references: `docs/security/threat-model.md:342-359`; `tests/security/mcp/test_confused_deputy.py`.

### Item 8 - Integration and close-out
- Deliverable: rebase; regenerate Tier 3 (`openapi.json`, API reference, status table, INDEX, execution plan); Snyk Code scan on changed MCP modules; changelog entry per the reference's close-out rule; completion note with "Env vars for the operator" (the switch); review pass; close #115 only if items 2 to 7 shipped.
- Owned files: the Ownership block plus Tier-3 regenerated files.
- Depends on: items 1 to 7 (or item 1 only, if the ADR was not accepted).
- Acceptance criteria: PRP exit line.
- Tests: the gates below.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/mcp_core services/api/tests/mcp_api services/api/tests/runtime_planes services/api/tests/authz services/api/tests/runtime_routes services/api/tests/test_openapi_drift.py tests/security/mcp tests/docs
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Stored MCP server documents gain one optional field; documents without it load unchanged, so no data migration. Turn the feature off by unsetting the deployment switch (default off): stored overrides are then ignored at connect time and private targets are refused again. Revert is a `git revert` of the PR; documents that carry the field would then fail the `extra="forbid"` model, so before reverting clear every override through the API (runbook step) or drop the field with a one-off script recorded in the runbook.

## Live and open gates
No live run here. A real private-network MCP server reached through a VNet needs an operator-built environment and `NS_LIVE_APPROVED=1`; it is OPEN and handed to PRP-64 as an optional row. Real-DNS refusal (OPEN since PRP-22) stays OPEN. Government stays OPEN (no subscription).

## NOT building
- Network changes (Helm egress entries, NSG rules, private DNS zones); the runbook describes them.
- Relaxing hostname rules or allowing IP-literal private URLs (unless the owner's ADR decision says otherwise).
- A stored-setting UI for the switch (follow-up on PRP-45's store).
- Overrides for the MCP resource server, chart URLs or connectors.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1-4 and 6-9 are ASSUMPTIONs the ADR must confirm; item 1 is a stop point)

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
- Product check:
