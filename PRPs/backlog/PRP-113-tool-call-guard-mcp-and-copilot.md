---
name: PRP-113-tool-call-guard-mcp-and-copilot
status: backlog
priority: P1
order: 113
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-06, NS-08, NS-09
depends_on: [PRP-105-policy-engine-core, PRP-78-copilot-graph-timeline-and-recommender-tools, PRP-108-agent-approval-gate-and-platform-control-actions]
wave: W26
branch: prp-113-tool-call-guard
allow_parallel: true
issues: []
---

# PRP-113: Tool-call guard for the copilot, the MCP server and the MCP client

## Goal
Put the policy decision in front of every tool call NeuroSphere itself makes or serves. A pre-invoke decision hook runs inside `ToolRegistry.invoke` after argument validation and before the handler, for the copilot's tools (point `tool_call`) and for the MCP server's tools (point `mcp_server`, which already go through the same registry); the same decision runs in the MCP client before NeuroSphere calls a registered external server (point `mcp_client`). The decision is PRP-105's `decide` over published policies and their enforcement bindings, per tool or per server through the binding `target`. In `audit` (the default) nothing is blocked and a would-deny is recorded; in `enforce` the call is refused before the handler or the outbound connection runs. Every deny and would-deny is audited without the tool arguments. These points are inside NeuroSphere's own process, so here a block is a real block; the PRP says so and claims nothing beyond these three paths. It runs in W26, after PRP-78 (copilot tools and the tool-call observer) and PRP-108 (bindings change only through approved actions).

Out of scope: gateway enforcement (PRP-112); the workload decision API and the SDK guard (PRP-114); copilot and MCP governance tools (`list_policies`, `list_violations`, draft tools; PRP-116, which owns `copilot/tools/governance_*.py` and later `mcp/server/tools.py`); authoring bindings (bindings are created at publish by PRP-105 and change mode only through PRP-108's `enforcement_mode_change`); tool calls inside third-party agents or SaaS assistants (no hook exists; design section 8 item 1).

## Why
- `ToolRegistry.invoke` is the single hook point for copilot tools and has only a refusal sink: unregistered names, scope-shaped and undeclared arguments, schema and timeout, then the handler (`packages/core/neurosphere_core/copilot/tools/registry.py:143-176`, sink `:178-193`); there is no pre-invoke policy callback.
- The MCP server routes every tool call through the same registry (`services/api/neurosphere_api/mcp/server/factory.py:383-389`, registry built per request at `:323-329` by `build_mcp_registry`, `mcp/server/tools.py:452-487`).
- The MCP client's only call-time gate is `check_callable` (server active, cloud, boundary, tool approved with a live hash; `packages/core/neurosphere_core/mcp/registry.py:286-308`), called from `ExternalMcpClient.call_tool` (`services/api/neurosphere_api/mcp/client/connector.py:303-325`); no governance policy is consulted.
- `docs/PRD.md:37` requires server-side authorization for "copilot, tools and push channels"; `:41` "require approval for new tools"; the 2026-11-16 owner direction plans every gap; design section 2.3 names tool calls as enforcement point 2.
- PRP-105 provides `decide` and bindings but nothing calls it on a tool path.

## Acceptance criteria
- [ ] Given no binding for the point in the caller's domains, When a tool is invoked, Then the call behaves exactly as today (existing `packages/core/tests/copilot`, `services/api/tests/copilot_api` and `services/api/tests/mcp_api` pass unchanged) and no decision record is written.
- [ ] Given a published policy with a `tool_call` binding in `audit` whose rule matches the tool (for example `registration_required` or `data_sensitivity_access` over the tool's catalog edges), When the copilot invokes it, Then the handler runs, the result is unchanged, and one `govpolicy.decide` audit record with effect `audit`, the rule ids, the point and the tool name is written; the tool arguments appear nowhere in audit, logs or metrics.
- [ ] Given the same binding moved to `enforce` by an approved `enforcement_mode_change`, Then the handler is never called (asserted with a spy), the caller gets `forbidden` reason `policy_denied` with the policy and rule ids only, and a `govpolicy.decide` record with effect `deny` is written.
- [ ] The same holds for an MCP client call through point `mcp_server` (the NeuroSphere MCP server's tools) and for an outbound external call through point `mcp_client`, where a deny happens before any connection is opened (asserted with the transport fake: zero requests).
- [ ] A binding with `target` set to one tool or one server applies only to it; a binding with `target` null applies to every tool of that point in its domain; customer-wide policies apply in every domain the caller's scope holds.
- [ ] Given an active PRP-105 exception for the subject and rule, Then an `enforce` decision is `allow` with the exception id in the record.
- [ ] Given the decider unavailable or its snapshot stale beyond twice the cache lifetime, Then `enforce` bindings deny with `policy_unavailable` (fail closed inside NeuroSphere's own boundary) and `audit` bindings allow and count `tool_guard_degraded`; neither path raises an unhandled error into the copilot stream or the MCP session.
- [ ] The decision uses only the server-derived `IdentityScope`; no tool argument can name a scope, domain or policy to widen or skip the check (the existing scope-shaped-key refusal runs first), and the decision never returns ids from domains outside the scope.
- [ ] The decision adds no I/O to the call path beyond the decider's in-memory snapshot; a test pins that `invoke` makes no store call when the snapshot is fresh.
- [ ] `GET /api/v1/governance/enforcement/tools/bindings` and `.../decisions/summary` (counts by effect, point, tool, last 24 hours; no arguments) are scope-filtered, in the route inventories and deny every ABAC dimension; the PRP-112 bindings page shows the tool, MCP-server and MCP-client rows with the capability statement "blocks NeuroSphere's own tool calls only".
- PRP exit: touched suites, `tests/security/authz`, frontend lint/typecheck/test, ruff, pyright, `validate_planning.py` pass; PR open, CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Enforcement default | `audit`; `enforce` | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: per point and target, only through PRP-108's approved `enforcement_mode_change` |
| 2 | Failure mode when the decider is unavailable | Fail open; fail closed | Decided by the owner 2026-11-16 (GD-22): in `enforce` mode the tool-call guard blocks (`policy_unavailable`) when the policy engine is unreachable; in `audit` mode it fails open with a counter. Here: these points are NeuroSphere's own boundary. Not the SDK rule (GD-8 is fail-open for the cooperative SDK, PRP-114) |
| 3 | Which rule kinds apply to tools | All; those with a tool meaning | Those PRP-105 marks decidable at request time and binds to these points (`POINTS_BY_RULE_KIND`): `registration_required`, `required_owner`, `required_approval`, `data_sensitivity_access`, `residency`. `model_allow_list` is a model-call rule (gateway, SDK) |
| 4 | Subject id for built-in copilot tools and MCP servers | Catalog only; derived ids | ASSUMPTION: a tool with a catalog `Tool` entity uses its canonical id; a built-in NeuroSphere tool uses `<cloud>:<customer>:neurosphere:tool:<tool name>` and is never subject to `registration_required` (product code), only to rules whose binding names it; an external server uses its catalog `McpServer` id when one exists, else `<cloud>:<customer>:neurosphere:mcp_server:<server id>` (registered servers carry no domain, `mcp/models.py:171-188`) |
| 5 | How the guard reaches the registries without Tier-1 builder edits | Edit `copilot.py`, `mcp.py`, `planes.py`; new builder | New builder module `runtime/builders/tool_guard.py` appended to `default_builders` after `planes`, `copilot`, `mcp` and `governance`; it publishes `app.state.tool_guard` and attaches the guard to the MCP client through `attach_guard`; the copilot engine and MCP server factory read `app.state.tool_guard` when they build their per-request registry. Correction to the design ("T1: none" holds; the call sites `copilot/engine.py`, `mcp/server/factory.py`, `mcp/server/tools.py`, `mcp/client/connector.py` become owned files) |
| 6 | Where decisions are audited | New container; audit chain | Audit chain only (`govpolicy.decide` from PRP-99's conventions) for `deny` and audit-mode would-deny; allows are counted, not recorded; PRP-78's `ToolCallObserver` event gains `decision_effect` and `rule_ids` |

## Context manifest

### Files to read first
- `temp/audit/governance-core-design.md` section 2.3 and the PRP-113 entry.
- `packages/core/neurosphere_core/copilot/tools/registry.py` - `ToolRegistry.invoke`, `RefusalSink`, and PRP-78's `ToolCallObserver`/`ToolCallEvent`.
- `packages/core/neurosphere_core/copilot/tools/errors.py` - fixed-reason errors (`:25-40`).
- `services/api/neurosphere_api/copilot/engine.py:369-379` - per-turn registry construction (after PRP-78: `build_copilot_registry`).
- `services/api/neurosphere_api/mcp/server/factory.py:250-330,383-410` - per-request registry, `call_tool`.
- `services/api/neurosphere_api/mcp/server/tools.py:452-487` - `build_mcp_registry`.
- `services/api/neurosphere_api/mcp/client/connector.py:1-27,303-325` - `ExternalMcpClient.call_tool`.
- `services/api/neurosphere_api/runtime/builders/planes.py:379` - where the MCP client is built.
- `PRPs/backlog/PRP-105-policy-engine-core.md` and `PRPs/backlog/PRP-78-copilot-graph-timeline-and-recommender-tools.md` "Interfaces provided".
- `PRPs/backlog/PRP-112-gateway-policy-enforcement-apim.md` "Interfaces provided" (the bindings page this PRP extends).

### Interfaces consumed
- PRP-105: `PolicyDecider.decide(scope, PolicyDecisionRequest)`, `BindingStore.list(point=, target=)`, `ENFORCEMENT_POINT_CAPABILITIES`, `POINTS_BY_RULE_KIND`, `ExceptionStore.active_for`, `app.state.governance_policy`, permissions `govpolicy.read`; audit operation `govpolicy.decide`.
- PRP-99: `PolicyDecisionRequest` (`decision_point` `tool_call`/`mcp_server`/`mcp_client`, `operation` `tool_invoke`/`mcp_call`, `tool_id`, `mcp_server_id`), `PolicyDecisionResponse` (`effect`, `matches`, `reason_codes`, `degraded`), `EnforcementBinding.target`.
- PRP-78: `ToolCallObserver`, `ToolCallEvent`, `build_copilot_registry(deps, *, sink, observer)`, the documented extension point it leaves in `ToolRegistry.invoke` for this PRP (design section 6).
- PRP-108: `enforcement_mode_change` (the only way a binding reaches `enforce`).
- PRP-112: `frontend/src/features/governance/enforcement/` page and its point table.
- Shipped PRP-22: `ExternalMcpClient`, `check_callable`, MCP server factory.

### Interfaces provided
- Core: `neurosphere_core.copilot.tools.registry` - `ToolDecisionHook` protocol (`async before_invoke(spec_name, scope) -> ToolDecision`), `ToolRegistry(specs, *, sink, observer, decision_hook=None, point="tool_call")`; error `ToolPolicyDeniedError` (`forbidden`, reason `policy_denied`) in `copilot/tools/errors.py`.
- Core: `neurosphere_core.governance.enforcement.tools` - `PolicyToolGuard(decider, bindings, *, point)` implementing the hook; `ToolSubject` id rules of clarification 4; `McpClientGuard` (`async check(scope, server, tool_name) -> ToolDecision`); counters `tool_guard_decisions_total{effect,point}`, `tool_guard_degraded_total`.
- API: `runtime/builders/tool_guard.py` (`BUILDER`, optional component `tool_guard`, setting `NS_TOOL_GUARD_ENABLED` default true; false removes the hook and logs it at startup), `app.state.tool_guard` (`ToolGuards`: `copilot`, `mcp_server`, `mcp_client`); `services/api/neurosphere_api/mcp/server/guard.py` and `mcp/client/guard.py` (adapters); `ExternalMcpClient.attach_guard(guard)`; `build_mcp_registry(..., decision_hook=None)`.
- Routes under `/api/v1/governance/enforcement/tools`: `GET /domains/{domain}/bindings`, `GET /domains/{domain}/decisions/summary`.
- Frontend: `frontend/src/features/governance/enforcement/tools/` rows on the PRP-112 bindings page.

### Patterns to match
- Refusal before the handler with fixed reasons and no values: `registry.py:143-165` (scope-shaped and undeclared keys).
- Attaching a component after composition: PRP-41's store layer attached in an `on_startup` hook (`services/api/neurosphere_api/ingest/producer_store.py`, `runtime/builders/edge.py`).
- MCP client refusal before connecting: `connector.py:318-325` (`check_callable` before `_session`).
- Builder module with an optional component: `services/api/neurosphere_api/runtime/builders/admin_system.py`.

### Gotchas
- Order inside `invoke`: registration check, scope-shaped keys, undeclared keys, schema validation, THEN the decision, then the timeout-wrapped handler. Deciding before validation would let malformed input reach the decider; deciding after the handler would not be a guard.
- The decision request carries ids only (tool name, subject ids, operation, domain); never put `raw_args` or the validated args model into the request, the audit record, a log line or a metric label (PRP-78 rule: tool arguments are never written to audit).
- PRP-78 changed `engine.py`, `registry.py` and `builtin.py` in W23; rebase onto it and use `build_copilot_registry`, do not restore `build_default_registry` calls.
- PRP-116 (W27) adds governance tools and edits `mcp/server/tools.py` after this PRP; keep the `decision_hook` parameter keyword-only with a default so its calls do not change.
- Adding the builder breaks the pinned `default_builders` and component tests: `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`.
- `RegisteredServer` has no domain; a customer-wide `mcp_client` binding lives in the customer-control domain. The decision for an outbound call uses the caller's scope domains plus customer-wide policies.
- The MCP client drift path (`_record_drift`) must still run on a hash mismatch; the guard runs before `check_callable`, and a guard deny ends the call without touching the drift path.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/copilot/tools/registry.py
  - packages/core/neurosphere_core/copilot/tools/errors.py
  - packages/core/neurosphere_core/governance/enforcement/tools/**
  - packages/core/tests/governance_enforcement_tools/**
  - services/api/neurosphere_api/copilot/engine.py
  - services/api/neurosphere_api/mcp/server/guard.py
  - services/api/neurosphere_api/mcp/server/factory.py
  - services/api/neurosphere_api/mcp/server/tools.py
  - services/api/neurosphere_api/mcp/client/guard.py
  - services/api/neurosphere_api/mcp/client/connector.py
  - services/api/neurosphere_api/governance/enforcement/tools/**
  - services/api/neurosphere_api/runtime/builders/tool_guard.py
  - services/api/tests/governance_tool_guard_api/**
  - frontend/src/features/governance/enforcement/tools/**
  - frontend/src/features/governance/enforcement/EnforcementBindingsPage.tsx
  - tests/security/authz/test_governance_tool_guard*.py
  - tests/security/tool_guard/**
  - docs/runbooks/tool-call-guard.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/tests/runtime_gateway_builder/test_gateway_builder.py
  - services/api/tests/runtime_data/data_helpers.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/governance-enforcement.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/governance/policy/**
  - packages/core/neurosphere_core/governance/enforcement/gateway/**
  - packages/core/neurosphere_core/copilot/tools/builtin.py
  - packages/core/neurosphere_core/mcp/**
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - services/api/neurosphere_api/runtime/builders/mcp.py
  - services/api/neurosphere_api/runtime/builders/planes.py
  - connectors/agent-sdk-python/**
  - connectors/reference/**
```
`frontend/tests/mock-api/features/governance-enforcement.ts` is PRP-112's file; this PRP appends handlers only.

## Implementation blueprint

Parallelization: items 1 and 2 [P] (core registry versus core guard; item 2 codes against item 1's protocol, frozen in its first commit). Item 3 after 1 and 2; item 4 after 2; item 5 after 3 and 4; item 6 after 5; item 7 after 6; item 8 last.

### Item 1 - Pre-invoke hook in `ToolRegistry`  [P]
- Deliverable: `ToolDecisionHook`, `ToolDecision`, the `decision_hook` and `point` parameters, the call in `invoke` at the position in Gotchas, `ToolPolicyDeniedError`, decision fields on the PRP-78 `ToolCallEvent`.
- Owned files: `copilot/tools/registry.py`, `copilot/tools/errors.py`, `packages/core/tests/governance_enforcement_tools/test_registry_hook.py`.
- Must NOT touch: `builtin.py`, other tool modules.
- Depends on: PRP-78 merged.
- Acceptance criteria: criteria 1, 3 (handler spy) and 9 at the registry level; no-hook behaviour byte-identical.
- Tests: `test_registry_hook.py`, plus `packages/core/tests/copilot` and `packages/core/tests/copilot_graph_tools`.
- Pattern references: `registry.py:143-193`.

### Item 2 - Policy tool guard in core  [P]
- Deliverable: `governance/enforcement/tools/{__init__,guard,subject,mcp_client}.py`: `PolicyToolGuard` (binding lookup by point and target, `decide` call, mode handling, exceptions, fail-closed and fail-open of clarification 2, audit of deny and would-deny through an injected recorder, counters) and `McpClientGuard`.
- Owned files: `packages/core/neurosphere_core/governance/enforcement/tools/**`, `packages/core/tests/governance_enforcement_tools/test_guard.py`, `test_subject.py`, `test_failure_modes.py`.
- Must NOT touch: `governance/policy/**`, `governance/enforcement/gateway/**`.
- Depends on: item 1's protocol.
- Acceptance criteria: criteria 2, 3, 5, 6, 7 and 8 on fakes.
- Tests: the three files above.
- Pattern references: PRP-105 `decide` tests.

### Item 3 - Copilot and MCP server wiring
- Deliverable: `runtime/builders/tool_guard.py` (builds the three guards from `app.state.governance_policy`, publishes `app.state.tool_guard`, reports `tool_guard`); `copilot/engine.py` passes the copilot guard with point `tool_call`; `mcp/server/guard.py` and `factory.py` pass the MCP-server guard with point `mcp_server` through `build_mcp_registry(..., decision_hook=)`.
- Owned files: `runtime/builders/tool_guard.py`, `copilot/engine.py`, `mcp/server/{guard,factory,tools}.py`, `services/api/tests/governance_tool_guard_api/test_wiring.py`; Tier-2 builder and status lines and the pinned builder tests.
- Must NOT touch: `runtime/builders/copilot.py`, `mcp.py`, `planes.py`.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 2, 3 and 4 (server part) through the HTTP harnesses; with `governance_policy` disabled the guard component is `disabled` and calls behave as today.
- Tests: `test_wiring.py`, plus `services/api/tests/copilot_api`, `services/api/tests/mcp_api`, `services/api/tests/runtime_api`.
- Pattern references: `runtime/builders/admin_system.py`.

### Item 4 - MCP client guard
- Deliverable: `mcp/client/guard.py`; `ExternalMcpClient.attach_guard` and the guard call in `call_tool` before `check_callable` and before `_session`; the builder attaches it in a startup hook.
- Owned files: `mcp/client/{guard,connector}.py`, `services/api/tests/governance_tool_guard_api/test_mcp_client_guard.py`.
- Must NOT touch: `packages/core/neurosphere_core/mcp/**`, `planes.py`.
- Depends on: item 2.
- Acceptance criteria: criterion 4 (client part: zero transport requests on deny); drift recording unchanged on a hash mismatch when allowed.
- Tests: the file above plus `services/api/tests/mcp_api/test_client.py`.
- Pattern references: `connector.py:303-367`.

### Item 5 - Read routes
- Deliverable: `services/api/neurosphere_api/governance/enforcement/tools/{__init__,router,service,models}.py` for the two routes; summary from the guard counters and the audit search on `govpolicy.decide` (bounded window, no arguments).
- Owned files: those modules, `services/api/tests/governance_tool_guard_api/test_routes.py`; Tier-2 route lines and inventories.
- Must NOT touch: `governance/enforcement/gateway/**`.
- Depends on: items 3 and 4.
- Acceptance criteria: criterion 10 (API part).
- Tests: `test_routes.py`.
- Pattern references: PRP-112 gateway routes; `audit/search.py` bounded queries.

### Item 6 - Bindings page rows
- Deliverable: `frontend/src/features/governance/enforcement/tools/` rows (tool, MCP server, MCP client; mode, target, last-24h counts, capability statement) on the PRP-112 page; mock handlers appended.
- Owned files: `frontend/src/features/governance/enforcement/tools/**`, appended handlers.
- Must NOT touch: PRP-112's page files except one mount line in `EnforcementBindingsPage.tsx` for the extra rows (PRP-112 merged in W25 and no other W26 PRP edits that page).
- Depends on: item 5.
- Acceptance criteria: criterion 10 (UI part).
- Tests: `frontend/src/features/governance/enforcement/tools/tool-bindings.test.tsx`.
- Pattern references: PRP-112 `EnforcementBindingsPage`.

### Item 7 - Authorization and leak suite
- Deliverable: ABAC cases for the routes; tests that tool arguments never reach audit, logs, metrics or error bodies on allow, would-deny and deny; scope cannot be widened through arguments; out-of-scope ids never appear in a decision.
- Owned files: `tests/security/authz/test_governance_tool_guard.py`, `tests/security/tool_guard/**`.
- Must NOT touch: shared harness files except additive helpers.
- Depends on: item 6.
- Acceptance criteria: criteria 2, 8 and 10; none skipped.
- Tests: `tests/security/authz`, `tests/security/tool_guard`.
- Pattern references: `packages/core/tests/copilot/test_tool_scope.py`, `services/api/tests/mcp_api/test_server_no_passthrough.py`.

### Item 8 - Integration and close-out
- Deliverable: `docs/runbooks/tool-call-guard.md` (points, what is blocked and what is not, subject ids, failure modes, how to move a binding to enforce through approval); mkdocs nav; rebase; Tier-3 regeneration; changelog fragment; completion note and product check.
- Owned files: runbook, Tier-2 lines, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/governance_enforcement_tools packages/core/tests/copilot packages/core/tests/copilot_graph_tools packages/core/tests/mcp_core services/api/tests/governance_tool_guard_api services/api/tests/copilot_api services/api/tests/mcp_api services/api/tests/runtime_api services/api/tests/runtime_gateway_builder services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/security/tool_guard services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. With no binding for a point, behaviour is unchanged. To turn a block off: an approved `enforcement_mode_change` back to `audit` or `off`. Emergency: `NS_TOOL_GUARD_ENABLED=false` removes the hook (component `disabled`, calls behave as before PRP-113) and is logged at startup; or revert the PR.

## Live and open gates
None. All three points are in NeuroSphere's own process and are proven on the HTTP harnesses and fakes; no external call is made (the MCP client tests use the transport fake).

## NOT building
Guards for tool calls inside third-party agents, SaaS assistants or customer code (no hook; the SDK guard of PRP-114 is cooperative only); argument-content inspection or DLP on tool inputs and outputs (no captured content reaches a decision; design decision GD-3); new rule kinds; binding authoring (PRP-105 creates, PRP-108 changes mode); copilot or MCP governance tools (PRP-116); any change to `check_callable`, SSRF pinning or tool approval (shipped PRP-22, unchanged).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 2 and 4 are ASSUMPTIONS; PRP-78's observer names come from its backlog file)

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
- Product check (can an operator use it without editing files or calling raw APIs):
