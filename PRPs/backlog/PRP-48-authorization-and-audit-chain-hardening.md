---
name: PRP-48-authorization-and-audit-chain-hardening
status: backlog
priority: P1
order: 35
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-08, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-65-admin-permissions-policy-repository-and-config-store]
wave: W15
branch: prp-48-authz-audit-hardening
allow_parallel: true
issues: [241, 91, 114, 69, 70, 206]
---

# PRP-48: Authorization and audit-chain hardening

## Goal
Close the authorization and audit gaps found by the PRP-06, PRP-12, PRP-22, PRP-28 and PRP-31 reviews, so the control-plane APIs built in W16-W18 sit on honest primitives. Ships: a role-gated route category with tenancy and denial audit for `/workspaces/{role}` (#91); the behaviour of the deployment-scoped admin role that PRP-37/PRP-65 declares, applied to MCP administration, deploy scan and plan, and the emergency-disable kill switch (#114 and the PRP-17 leftover); allowed-read audit for catalog search and analytics dashboards (#69); audit-chain fixes for dotted customer ids, over-long domain names and reserved customer-level chain names (#206 items 1-3); and the injection corpus README and stub clarifications (#70). For security reviewers and for every later admin route. Now, because PRP-45, PRP-53 and PRP-57 gate deployment-wide settings on this behaviour.

Out of scope: the SIEM sink, audit search and export, the auditor-readable denial chain and pre-scope failure auditing are PRP-40; the APIM UI-to-API rate limit (#69 Bicep bullet) is PRP-52; the threat-model stale-row rewrite (#69 doc part) is PRP-36; the identity admin routes and revocation route are PRP-39; domain creation that must call the reserved-name check is PRP-44; #206 item 4 (legacy chains not migrated) is accepted and documented, not built.

## Why
- `services/api/neurosphere_api/workspaces/router.py:43-48` declares `data.read` through `PERMISSION_MARKER` without enforcing it; `_holds_role` (`:51-58`) ignores which domains the assignment names; the 403 at `:78` is raised directly, so no denial is recorded (#91).
- `services/api/neurosphere_api/me/router.py:34,83` caps catalog lookups at `_MAX_CATALOG_PAGES` and falls back to `derived` labels with no log line (#91).
- `config.manage` held in ANY domain gates deployment-wide routes: `mcp/admin/router.py:53`, `deploy/scan/router.py:58`, `deploy/plan/router.py:108` (#114; PRP-22 D6). The kill switch already uses the reserved control-domain check (`actions/customer_control.py:91-110`, `actions/router.py:86,218`), which #114 asks to become a real deployment-scoped role.
- Catalog search (`catalog/router.py:260`, `ui_adapters/catalog.py:85`) and dashboards (`dashboards/router.py:98`) audit nothing on an allowed read; `audit/builders.py:170` (`build_allowed`) exists unused for reads (#69, lane-e).
- `audit/chains.py:33-39` documents that dotted customers are refused per write, with no boot check; the denial recorder `_chain` (`runtime/builders/authz.py:179-182`) raises when a member domain cannot be encoded; customer-level chains `<customer>.authz-denials` (`authz.py:107`), `<customer>.gateway` (`gateway/service.py:41`) and the kill-switch chain (`actions/emergency.py:37`) can collide with a catalog domain of the same name (#206).
- `tests/security/injection/stubs.py:143-145` answers `comply` to an `Escalate` of an already-held permission without explanation; `README.md:34-40` lacks the consumer-location and vacuous-abstain notes (#70).

## Acceptance criteria
- [ ] #91: `authz/routes.py` has a role-gated category; `GET /api/v1/workspaces/{role}` is listed in it and no longer claims `data.read`; `undeclared_routes` stays empty.
- [ ] #91: Given a viewer assignment that names only another customer's domain, When `/workspaces/viewer` is called, Then 403 `role_not_held`; the 403 is recorded by the denial recorder (test asserts one `denied` record).
- [ ] #91: `/me/domains` for a caller whose only `data.read` comes from a resource grant returns 200 with an empty list and the OpenAPI description says so; exceeding `_MAX_CATALOG_PAGES` logs one warning with the domain count only.
- [ ] #114: Given `config.manage` only in an ordinary domain, When the caller registers an MCP server, runs a deploy scan or plan, or sets emergency-disable, Then 403 `deployment_scope_required` (or the existing `customer_scope_required` code if PRP-37/PRP-65 keeps it) and a denial record; Given the PRP-37/PRP-65 deployment-scoped admin assignment, Then each route succeeds as before.
- [ ] #114: the deployment-scoped check is one dependency under `services/api/neurosphere_api/authz/`, used by all four route groups; `require_customer_control` delegates to it; no unrestricted bypass is introduced (security case added to `tests/security/authz`).
- [ ] #69: an allowed catalog search (both routes) and an allowed dashboard read append one `allowed` audit record with actor pseudonym, operation, domain and result count only (no query text, no rows); a failed audit write on these reads is logged and counted, never blocks the read (read path, not mutation) - decision row 3.
- [ ] #206.1: API start with a dotted `NS_AUTH_CUSTOMER_ID` fails the `authz` component with reason `customer_id_invalid`.
- [ ] #206.2: a denial targeting a member domain whose chain cannot be encoded is recorded on `<customer>.authz-denials`, never a 503.
- [ ] #206.3: `neurosphere_core.audit.chains` exports the reserved customer-level chain names and `is_reserved_chain_name`; `domain_audit_chain_id` refuses a catalog domain named like a reserved chain with `invalid_chain_id`; a test pins the reserved set against the three constants above.
- [ ] #70: README states where consumer suites must live and that the stub's 13 `follow_instruction` abstains are vacuous until a real adapter; the stub comment explains `Escalate` of a held permission.
- PRP exit: every route that changes deployment-wide state requires the deployment-scoped permission, and every authorization decision on the touched routes leaves an audit record.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Shape of the deployment-scoped role | New role; new permission on existing admin; assignment on the reserved control domain | Defined by PRP-37/PRP-65 (see its "Interfaces provided"). ASSUMPTION: it is evaluated against the reserved per-customer control domain the operator approved on 2026-11-05 (`customer_control.py:9-18`), so existing kill-switch grants keep working; if PRP-37/PRP-65 chose otherwise, item 3 follows PRP-37/PRP-65. |
| 2 | Which routes move to it | MCP admin, deploy scan/plan, kill switch; plus sandbox reset | The four groups #114 names. Sandbox reset stays `config.manage` (local-only, 503 elsewhere). |
| 3 | Allowed-read audit failure on a read | Fail closed (503); log and continue | ASSUMPTION: log and count, do not block a read; mutations keep failing closed. Recorded in the threat model. |
| 4 | `/me/domains` empty 200 | 403; documented 200 | Documented 200 (frontend already handles it, #91 bullet 4). |
| 5 | Reserved chain names | Reserve on domain creation; qualify customer-level chains | Reserve (no data migration). The check lives in core audit; PRP-44's domain registry calls `is_reserved_chain_name` (follow-up recorded if PRP-44 merged first). |

## Context manifest

### Files to read first
- `PRPs/reference/parallel-build-reference.md` - tiers, commands, traps, close-out.
- `services/api/neurosphere_api/authz/dependencies.py:63-262` - `PERMISSION_MARKER`, `require`, `_holds_anywhere`, `_denial`.
- `services/api/neurosphere_api/authz/routes.py:55-261` - allowlist categories, `_entry`, `route_inventory`, `verify_route_permissions`.
- `services/api/neurosphere_api/actions/customer_control.py` - reserved control domain, `require_customer_control`, denial recording.
- `services/api/neurosphere_api/workspaces/router.py`, `services/api/neurosphere_api/me/router.py`.
- `services/api/neurosphere_api/runtime/builders/authz.py:99-200` - `AuditDenialRecorder`, `_chain`.
- `packages/core/neurosphere_core/audit/chains.py`, `audit/builders.py:152-190`.
- `services/api/neurosphere_api/mcp/admin/router.py:53`, `deploy/scan/router.py:58`, `deploy/plan/router.py:108`.
- `tests/security/authz/cases.py`, `tests/security/injection/README.md`, `stubs.py`.

### Interfaces consumed
- From PRP-37/PRP-65 (names in PRP-37/PRP-65's "Interfaces provided"): the deployment-scoped admin role and its permission(s) in `permissions.py`, and their role-set pins.
- Existing: `DeniedAttempt`, `AuthzState.denial_recorder`, `AuditRepository.append`, `build_allowed`, `build_denied`.

### Interfaces provided
- `services/api/neurosphere_api/authz/deployment_scope.py` (new): `require_deployment_admin(...)` dependency and reason code `deployment_scope_required`, for PRP-45, PRP-53, PRP-57 and later admin routes.
- `services/api/neurosphere_api/authz/read_audit.py` (new): `audited_read(permission)` dependency for allowed-read audit.
- Role-gated route category in `authz/routes.py` (`ROLE_GATED_PATHS` or a marker; name chosen in item 1).
- `neurosphere_core.audit.chains.RESERVED_CHAIN_NAMES`, `is_reserved_chain_name` for PRP-44 domain creation.

### Patterns to match
- Customer-level dependency plus denial record: `actions/customer_control.py:62-110`.
- Denial record fields: `runtime/builders/authz.py:131-150`.
- Security case table: `tests/security/authz/cases.py`, `test_privileged_roles.py`.
- Route category tests: `services/api/tests/authz/test_route_inventory.py:36-97`.

### Gotchas
- `authz/dependencies.py` is Tier-1 and this PRP is its W15 owner; keep `require` backward compatible, every router imports it.
- The denial recorder fails closed on mutating routes (`customer_control.py:83-87`); the allowed-read audit must not copy that behaviour (decision 3).
- `services/api/tests/authz` and `tests/security/authz` are both packages named `authz`; run them in one session only as the reference section 4 rule allows, and name new test dirs uniquely.
- Real-stack and sandbox flows grant the operator the control-domain role (`scripts/sandbox/sbx_grant_operator.py`, `tests/integration/actions/support.py`); if the role shape changes, update the grant script and `tests/unit/sandbox_stack/test_grant_operator.py` in item 3.
- Dashboards tests live inside the package (`services/api/neurosphere_api/dashboards/tests/`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/authz/**
  - services/api/neurosphere_api/workspaces/**
  - services/api/neurosphere_api/me/**
  - packages/core/neurosphere_core/audit/**
  - services/api/neurosphere_api/runtime/builders/authz.py
  - services/api/neurosphere_api/actions/customer_control.py
  - services/api/neurosphere_api/actions/router.py
  - services/api/neurosphere_api/mcp/admin/router.py
  - services/api/neurosphere_api/deploy/scan/router.py
  - services/api/neurosphere_api/deploy/plan/router.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/ui_adapters/catalog.py
  - services/api/neurosphere_api/dashboards/router.py
  - scripts/sandbox/sbx_grant_operator.py
  - tests/unit/sandbox_stack/test_grant_operator.py
  - tests/security/injection/**
  - tests/security/authz/**
  - packages/core/tests/audit/**
  - services/api/tests/workspaces_api/**
  - services/api/tests/me_api/**
  - services/api/tests/authz/**
  - services/api/tests/deployment_scope_api/**
  - services/api/tests/read_audit_api/**
  - services/api/tests/actions_api/test_customer_control.py
  - docs/runbooks/action-plane-kill-switch.md
  - docs/security/threat-model.md
tier1:
  - services/api/neurosphere_api/authz/dependencies.py
tier2_appends:
  - services/api/tests/authz/test_route_inventory.py
  - tests/security/authz/test_privileged_roles.py
must_not_touch:
  - tests/security/authz/test_admin_platform*.py
  - packages/core/neurosphere_core/audit/siem*.py
  - packages/contracts/**
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - services/api/neurosphere_api/gateway/**
  - services/api/neurosphere_api/actions/emergency.py
  - services/api/neurosphere_api/audit/**
  - infra/**
  - frontend/**
```

## Implementation blueprint

### Item 1 - role-gated route category and workspaces  [P]
- Deliverable: role-gated category in `authz/routes.py` and a `require_role(role)` dependency in `authz/dependencies.py` that checks an unexpired assignment naming at least one domain in `scope.allowed_domains` and records denials; `workspaces/router.py` uses it and drops `_authenticated_marker`.
- Owned files: `authz/routes.py`, `authz/dependencies.py`, `workspaces/**`, `services/api/tests/workspaces_api/**`, `services/api/tests/authz/test_route_inventory.py`.
- Must NOT touch: other routers.
- Depends on: none.
- Acceptance criteria: #91 criteria 1-2.
- Tests: `services/api/tests/workspaces_api/test_role_gate.py`, extend `test_route_inventory.py`.
- Pattern references: `customer_control.py:62-110`.

### Item 2 - /me follow-ups  [P]
- Deliverable: warning log on page cap; OpenAPI description for the empty-200 case.
- Owned files: `me/**`, `services/api/tests/me_api/**`.
- Depends on: none.
- Acceptance criteria: #91 criterion 3 (log asserted with `caplog`; no domain ids in the message).
- Tests: `services/api/tests/me_api/test_page_cap_log.py`.
- Pattern references: `me/router.py:83-118`.

### Item 3 - deployment-scoped admin behaviour
- Deliverable: `authz/deployment_scope.py` (new) generalising the control-domain check over the PRP-37/PRP-65 permission; `require_customer_control` delegates to it; MCP admin, deploy scan, deploy plan and `PUT /emergency-disable` use it; grant script and kill-switch runbook updated for the new assignment.
- Owned files: `authz/deployment_scope.py`, `actions/customer_control.py`, `actions/router.py` (dependency line only), `mcp/admin/router.py:53`, `deploy/scan/router.py:58`, `deploy/plan/router.py:108`, `scripts/sandbox/sbx_grant_operator.py`, `tests/unit/sandbox_stack/test_grant_operator.py`, `services/api/tests/deployment_scope_api/**`, `services/api/tests/actions_api/test_customer_control.py`, `tests/security/authz/**`, `docs/runbooks/action-plane-kill-switch.md`.
- Must NOT touch: `permissions.py` (PRP-37/PRP-65 owns it), route handlers' bodies.
- Depends on: item 1 (`dependencies.py`).
- Acceptance criteria: #114 criteria; existing `mcp_api`, `deployment`, `actions_api` suites green with fixtures granting the new assignment.
- Tests: `services/api/tests/deployment_scope_api/test_routes.py`, new case rows in `tests/security/authz/cases.py`.
- Pattern references: `customer_control.py:91-110`, `tests/security/authz/test_privileged_roles.py`.

### Item 4 - allowed-read audit for search and analytics
- Deliverable: `authz/read_audit.py` (new) `audited_read` dependency plus a post-response recorder; applied to both catalog search routes and the dashboard route; threat-model State column updated for "Allowed-read audit".
- Owned files: `authz/read_audit.py`, `catalog/router.py` (search route), `ui_adapters/catalog.py` (search route), `dashboards/router.py`, `services/api/tests/read_audit_api/**`, `docs/security/threat-model.md` (that row only).
- Depends on: item 1 (`dependencies.py`).
- Acceptance criteria: #69 criterion; record carries no query term (test searches with a sentinel term and greps the stored record).
- Tests: `services/api/tests/read_audit_api/test_search_reads.py`, `test_dashboard_reads.py`.
- Pattern references: `audit/builders.py:170`, `runtime/builders/authz.py:131-150`.

### Item 5 - audit chain hardening  [P]
- Deliverable: reserved names and `is_reserved_chain_name` in `audit/chains.py`; boot check of the customer id and `_chain` fallback in `runtime/builders/authz.py`.
- Owned files: `packages/core/neurosphere_core/audit/chains.py`, `runtime/builders/authz.py`, `packages/core/tests/audit/**`, `services/api/tests/authz/test_denial_chain_fallback.py` (new).
- Must NOT touch: `audit/siem*.py`, `gateway/service.py`, `actions/emergency.py`.
- Depends on: none.
- Acceptance criteria: #206 criteria 1-3.
- Tests: `packages/core/tests/audit/test_reserved_chains.py`, `services/api/tests/authz/test_denial_chain_fallback.py`, `services/api/tests/runtime_api/test_compose_denial_audit.py` (re-run).
- Pattern references: `chains.py:78-108`.

### Item 6 - injection corpus README and stub  [P]
- Deliverable: README sections and stub comment per #70; no behaviour change.
- Owned files: `tests/security/injection/**`.
- Depends on: none.
- Acceptance criteria: #70 criterion; `tests/security/injection` suite green.
- Tests: `tests/security/injection` (existing).
- Pattern references: `README.md:30-40`.

### Item 7 - Integration and close-out
- Deliverable: Tier-2 inventory appends, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry, issue closure for #91, #114, #70, #206 (#69 stays open for the PRP-52 Bicep bullet), completion note.
- Owned files: Tier-2 list, this PRP file.
- Depends on: items 1-6.
- Acceptance criteria: validation gates green; PRP exit line verified by a grep of `require(Permission.CONFIG_MANAGE)` without a domain resolver returning only `sandbox/router.py`.
- Tests: `services/api/tests/test_openapi_drift.py`, `tests/docs/test_reference_coverage.py`.
- Pattern references: reference section 6.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/workspaces_api services/api/tests/me_api services/api/tests/authz services/api/tests/deployment_scope_api services/api/tests/read_audit_api services/api/tests/actions_api services/api/tests/mcp_api services/api/tests/deployment services/api/tests/catalog_api services/api/tests/ui_adapters_api services/api/neurosphere_api/dashboards/tests services/api/tests/runtime_api packages/core/tests/audit tests/security/authz tests/security/injection tests/unit/sandbox_stack services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
Authorization migration: operators who today hold `config.manage` only in an ordinary domain lose MCP admin and deploy scan/plan; they need the deployment-scoped assignment from PRP-37/PRP-65 (sandbox grant script updated; hosted operators re-run `scripts/sandbox/sbx_grant_operator.py` or, after PRP-39, the identity admin route, documented in the kill-switch runbook). A catalog domain already named like a reserved chain would fail its next audited write: item 5 test asserts none exists in seed data; a hosted check is listed for the operator. Rollback is a PR revert; no data is rewritten and no chain is migrated.

## Live and open gates
None. Live Entra sign-in with the new assignment is exercised by PRP-64's hosted operator checks (needs `NS_LIVE_APPROVED=1`), reported OPEN here.

## NOT building
- SIEM sink, audit search/export, auditor-readable denial chain, pre-scope failure audit (PRP-40); APIM rate limit (PRP-52); identity admin routes (PRP-39); domain registry (PRP-44); migration of pre-14b chains (#206 item 4, accepted).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 and 3 are assumptions to confirm at plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-48-authz-audit-hardening | `require_role` + `ROLE_GATED_PATHS`; workspaces role-gated, tenancy-bound, denial-audited |
| 2 | verifying | prp-48-authz-audit-hardening | page-cap warning (count only); OpenAPI description of the empty 200 |
| 3 | verifying | prp-48-authz-audit-hardening | `authz/deployment_scope.py` `require_deployment_admin` (reason kept `customer_scope_required`); MCP admin (all routes), deploy scan/plan, kill switch; `require_customer_control` delegates; fixtures in mcp_api, deployment, runtime_routes and integration/deploy grant the control domain |
| 4 | verifying | prp-48-authz-audit-hardening | `authz/read_audit.py` `audited_read`; catalog search (both routes) and dashboards; multi-domain reads on reserved `<customer>.read-audit`; count bound by subject digest (contract has no count field); threat-model rows updated |
| 5 | verifying | prp-48-authz-audit-hardening | `RESERVED_CHAIN_NAMES` (7 names, pinned), `is_reserved_chain_name`, `is_chain_customer_id`; boot `customer_id_invalid`; `_chain` falls back to `<customer>.authz-denials` |
| 6 | verifying | prp-48-authz-audit-hardening | README: consumer-suite locations and vacuous `follow_instruction` abstains; stub comment on `Escalate` of a held permission; `test_readme_claims.py` keeps both true |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check:
