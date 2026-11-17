---
name: PRP-116-copilot-and-mcp-governance-tools
status: backlog
priority: P1
order: 116
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-06, NS-08, NS-09
depends_on: [PRP-78-copilot-graph-timeline-and-recommender-tools, PRP-104-interaction-explorer-and-export, PRP-105-policy-engine-core, PRP-113-tool-call-guard-mcp-and-copilot, PRP-108-agent-approval-gate-and-platform-control-actions, PRP-109-north-star-scenario-acceptance]
wave: W27
branch: prp-116-governance-tools
allow_parallel: true
issues: []
---

# PRP-116: Copilot and MCP governance tools (metadata only)

## Goal
Let a user ask the copilot, or an MCP client acting for them, governance questions and get cited, scope-filtered answers: which policies apply here, what is violating them, why this violation was raised, which interactions were flagged for a detected category, and what the governance trail of a violation looks like. Five bounded read tools (`list_policies`, `list_violations`, `explain_violation`, `search_interactions`, `get_governance_trail`) and two draft-only tools (`request_policy_exception`, `draft_enforcement_mode_change`) are added to the copilot registry and the MCP server tool list. Captured content never reaches a model or an MCP client: `search_interactions` returns interaction metadata and detected-category findings only, the tools have no port that can decrypt, and negative tests prove no content field can pass. Every call is authorized on the caller's server-derived scope, passes PRP-113's pre-invoke decision hook, and is audited without argument values. It is for stewards, analysts and auditors working in chat or from an MCP client, and runs in W27 after PRP-78 (copilot registry and tool audit), PRP-104 (interaction metadata), PRP-105 (policy stores), PRP-108 (mode-change execution), PRP-109 (trail) and PRP-113 (decision hook on the same registries).

Out of scope: any tool that reads interaction content (decision GD-3; PRP-104's explorer is the only content reader); executing, confirming or approving anything from chat or MCP (drafts only, as today); the 100-question groundedness set and its live run (PRP-80, W31; this PRP ships its own offline governance cases that PRP-80 may fold in); the decision API for workloads (PRP-114); the policy UI (PRP-106); semantic search (PRP-135).

## Why
- The copilot has exactly five tools and no governance tool: `build_default_registry` "The five-tool allowlist" (`packages/core/neurosphere_core/copilot/tools/builtin.py:448-491`); PRP-78 adds graph, timeline and recommender tools and is told not to add policy or interaction tools (design section 6, PRP-78 row).
- MCP exposes three read tools and four action-plane tools (`services/api/neurosphere_api/mcp/server/tools.py:80-87`); its `draft_action` resolves the domain from a catalog entity (`:372-382`), so `governance_policy`, `enforcement_binding` and `capture_policy` targets cannot be drafted from MCP; PRP-108 records that these "are drafted through REST and the UI until PRP-116 adds governance draft tools" (`PRPs/backlog/PRP-108-agent-approval-gate-and-platform-control-actions.md:102`).
- MCP tool calls are not audited per call today: the server only derives a correlation id (`services/api/neurosphere_api/mcp/server/factory.py:326`); copilot tool calls are audited by PRP-78 (`copilot.tool_call`).
- `docs/PRD.md:29`: "Query catalog, metrics and evidence through authorized server tools ... Abstain when evidence is unavailable." `:42`: "Scoped MCP server tools/resources for catalog, metrics, recommendations and approved actions." Governance evidence is now one of those sources.
- Owner direction 2026-11-16: the ultimate team AI governance and auditing tool; GD-3 (recommended default): captured content is not shown to the copilot or MCP.

## Acceptance criteria
- [ ] Given a caller with `govpolicy.read` in domain D, When the copilot or MCP calls `list_policies` or `list_violations` (filters: status, severity, rule kind, policy id; bounded page, server cap 100), Then only records in domains the caller can read are returned, each row cites its record id and domain, and a caller without the permission gets `tool_permission_denied` with a refusal audit; MCP `tools/list` shows each tool only when its permission is held.
- [ ] `explain_violation(violation_id)` returns the rule kind, the matched rule's parameters, the subject, evidence references (kind and id), first and last seen, occurrence count and exception status, plus a fixed server-side explanation template per rule kind (no model-written rule text); an id outside the caller's scope is indistinguishable from a missing one.
- [ ] `search_interactions` (filters: agent, tool, data asset, detected category, time window at most 30 days) requires `data.read`, returns at most 50 rows of: interaction id, occurred at, agent, version, tool, service and MCP server ids, capture source, redaction state, part kinds with character counts, findings summary (category, count, action), sensitivity categories, data asset ids, retention class and hold flag. It never returns `content_ref`, principal pseudonyms, finding offsets or any text from the interaction.
- [ ] Content negative suite: with synthetic interactions whose content holds a per-test canary stored through PRP-102, no tool result, copilot SSE event, MCP response, audit record, log line or OpenAPI example contains the canary; the tool result models are checked by a schema walk that refuses any field named `text`, `content`, `content_ref`, `prompt`, `response`, `messages`, `body`, `parts.text` or ending in `prompt`/`response`; a static test proves the governance tool modules import neither `InteractionContentReader` nor `read_content`, `open_envelope` or any `KeyWrapper`.
- [ ] `get_governance_trail(violation_id)` requires `audit.read` (PRP-109's route permission), returns the ten steps with status, time, audit ids and refs only, and cites the trail's `chain_verified` value.
- [ ] `request_policy_exception(violation_id, reason_code, expiry_days)` requires `action.propose` in the violation's domain, calls PRP-105's exception-request service (a HITL `policy_exception` item, state requested), returns the item id and "decide in the review queue"; it never approves. `draft_enforcement_mode_change(binding_id, mode)` resolves the domain from the binding store, requires `action.propose`, drafts `enforcement_mode_change` through the action service with PRP-105's diff grammar (channel `chat` or `mcp`), refuses `enforce` where the point cannot block (`point_cannot_enforce`), and returns the intent id with "confirm in the UI"; neither tool can confirm, approve or execute.
- [ ] Every call of every new tool writes one audit record (copilot: PRP-78 `copilot.tool_call`; MCP: `mcp.tool_call`, written for every MCP tool through one observer) with tool name, outcome, domain ids and result count, and no argument value; scope-shaped arguments are refused by the registry as today; PRP-113's decision hook runs before each new tool.
- [ ] Offline governance cases (recorded model, synthetic world) answer "which agents violate the PII policy", "why was violation X raised", "which interactions in the last day had SSN findings" and "show the trail for violation X" with citations that resolve, and abstain for "show me the prompt of interaction Y".
- [ ] `build_default_registry` still has exactly five tools; existing copilot, MCP and security suites pass with their tool-name expectations updated only by the added names.
- PRP exit: touched suites, `tests/security/governance_tools`, `tests/security/mcp`, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | May content reach the copilot or MCP | Yes for investigators; no | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star |
| 2 | Permission per tool | Several | `list_policies`, `list_violations`, `explain_violation`: `govpolicy.read` (PRP-105); `search_interactions`: `data.read` (PRP-104's metadata route permission); `get_governance_trail`: `audit.read` (PRP-109); draft tools: `action.propose` |
| 3 | Principal pseudonyms in tool results | Include; exclude | ASSUMPTION: exclude; the explorer UI shows them to people, the model does not need them |
| 4 | Exception "draft" | Action intent; HITL request | HITL request through PRP-105 (exceptions are not executor kinds); the reviewer decides in the review queue |
| 5 | MCP audit | Governance tools only; every MCP tool | Decided by the owner 2026-11-16 (GD-25): every MCP tool call is audited (`mcp.tool_call`), not only the governance tools. Here: one observer (no MCP call is audited today; the cost is one record per call) |
| 6 | Enforcement default | `audit`; `enforce` | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: the mode-change draft tool proposes it through the generic actions route (GD-44), never applies it |
| 7 | Groundedness cases | Add to PRP-80's set; own file | Own file `tests/evals/copilot_governance/cases.yaml` (PRP-80 ships later, W31, and owns its 100-question set) |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-78-copilot-graph-timeline-and-recommender-tools.md` "Interfaces provided" and item 4 - `build_copilot_registry`, `ToolCallObserver`, `COPILOT_TOOL_NAMES`, `build_tool_ports`, `CopilotToolAuditor`.
- `PRPs/backlog/PRP-113-tool-call-guard-mcp-and-copilot.md` "Interfaces provided" - `ToolRegistry(..., observer, decision_hook)`, `build_mcp_registry(..., decision_hook=None)`.
- `PRPs/backlog/PRP-105-policy-engine-core.md` "Interfaces provided" - stores, `ENFORCEMENT_POINT_CAPABILITIES`, `mode_change_diff`, exception request service.
- `PRPs/backlog/PRP-104-interaction-explorer-and-export.md` "Interfaces provided" - metadata listing over `InteractionStore.query_index`.
- `PRPs/backlog/PRP-109-north-star-scenario-acceptance.md` "Interfaces provided" - the trail assembler and its response.
- `packages/core/neurosphere_core/copilot/tools/builtin.py:91-200,396-491` - `ToolDependencies`, `_build_result`, `_propose_action`, registry construction.
- `packages/core/neurosphere_core/copilot/tools/registry.py:125-195` - `ToolRegistry.invoke` and refusals.
- `services/api/neurosphere_api/mcp/server/tools.py:80-200,372-487` - names, annotations, `StatePorts`, `draft_action`, `build_mcp_registry`.
- `services/api/neurosphere_api/mcp/server/factory.py:255-380` - `tools/list` filtering by held permission.

### Interfaces consumed
- PRP-78: `build_copilot_registry(deps, *, sink, observer)`, `CopilotToolDependencies`, `COPILOT_TOOL_NAMES`, `neurosphere_api.copilot.tooling.build_tool_ports(ctx)`, `CopilotToolAuditor`, audit operation `copilot.tool_call`.
- PRP-113: `ToolRegistry(specs, *, sink, observer, decision_hook=None, point=...)`, `build_mcp_registry(..., decision_hook=None)` (keyword-only, default kept), `ToolPolicyDeniedError`.
- PRP-105: `PolicyDefinitionStore.list/get`, `ViolationStore.list/get`, `ExceptionStore`, the exception-request service used by `POST .../exception-requests`, `BindingStore.get`, `mode_change_diff`, `ENFORCEMENT_POINT_CAPABILITIES`, `app.state.governance_policy`, permissions `govpolicy.read`, `govpolicy.manage`.
- PRP-104: `app.state.interaction_explorer` metadata search (or `InteractionStore.query_index` and `get_metadata` through it), `Permission.INTERACTION_READ` (asserted NOT required and NOT used).
- PRP-102/PRP-99: `InteractionRecord` fields (the allowlist above is a subset).
- PRP-108: platform-control executes `enforcement_mode_change`.
- PRP-109: trail assembler behind `GET /api/v1/governance/trail` (`audit.read`), `GovernanceTrail` model.
- Shipped: `ActionApi.draft`, `DraftIntentBody`, `permits`, `ForbiddenError`, `ToolPermissionError`.

### Interfaces provided
- Core: `neurosphere_core.copilot.tools.governance_ports` (`PolicyReader`, `ViolationReader`, `InteractionMetadataReader`, `TrailReader`, `ExceptionRequester`, `BindingReader`), `governance_models` (result row models, `INTERACTION_TOOL_FIELDS` allowlist), `governance_tools` (read handlers, `GOVERNANCE_TOOL_NAMES`, `governance_specs(deps)`), `governance_drafts` (the two draft handlers).
- `build_copilot_registry` registers the seven tools when their ports are bound; `COPILOT_TOOL_NAMES` extended.
- MCP: `GOVERNANCE_READ_TOOL_NAMES`, `GOVERNANCE_DRAFT_TOOL_NAMES` in `mcp/server/tools.py`, added to `MCP_TOOL_NAMES` and `ANNOTATIONS`; `McpToolAuditor` observer, audit operation `mcp.tool_call`.
- Eval cases `tests/evals/copilot_governance/cases.yaml` (for PRP-80 to fold in).

### Patterns to match
- Bounded read tool with server-derived domains and citations: `builtin.py:213-256` (`_search_catalog`) and `:308-346` (`_list_recommendations`).
- Draft tool that resolves the domain server-side and never confirms: `builtin.py:396-445`, `mcp/server/tools.py:372-397`.
- MCP read spec wrapping with the scope note: `mcp/server/tools.py:452-487`.
- Audit with no argument values: PRP-78's `CopilotToolAuditor`; `authz/read_audit.py:176-193`.

### Gotchas
- Several suites assert the exact MCP tool list: `services/api/tests/mcp_api/test_server_hardening.py:78,203`, `test_server_scope.py:58`, `services/api/tests/runtime_planes/test_mcp_builder.py:189`, `tests/security/mcp/test_client_server_roundtrip.py:68`, `test_confused_deputy.py`. A steward holds the new permissions; a viewer may not hold `govpolicy.read` or `audit.read`, so per-role expectations change. Update them in this PRP and grep for `MCP_TOOL_NAMES` and `COPILOT_TOOL_NAMES` before pushing.
- `build_default_registry` must stay five tools (MCP read specs and reports build on it, PRP-78 clarification 3); register governance tools in `build_copilot_registry` and `build_mcp_registry` only.
- Audit `FORBIDDEN_KEYS` refuse `prompt`, `response`, `messages`, `body` (`audit/content_guard.py`); tool audit carries names and counts only.
- `PolicyViolationEvidence.ref` for `interaction_record` is an id; never resolve it to content.
- PRP-113 owns `mcp/server/factory.py` in W26; this PRP changes only `tools.py` (the observer is built inside `build_mcp_registry` from `StatePorts`), so `factory.py` is untouched.
- A contract model used as a tool result renames nothing in OpenAPI (tools are not routes), but MCP `outputSchema` must not include content-shaped names; the schema walk covers it.
- New test directories need unique names (`copilot_governance_tools`, `mcp_governance_tools`, `governance_tools`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/copilot/tools/governance_ports.py
  - packages/core/neurosphere_core/copilot/tools/governance_models.py
  - packages/core/neurosphere_core/copilot/tools/governance_tools.py
  - packages/core/neurosphere_core/copilot/tools/governance_drafts.py
  - packages/core/neurosphere_core/copilot/tools/builtin.py
  - packages/core/neurosphere_core/copilot/tools/__init__.py
  - packages/core/tests/copilot_governance_tools/**
  - services/api/neurosphere_api/copilot/tooling.py
  - services/api/neurosphere_api/mcp/server/tools.py
  - services/api/tests/mcp_governance_tools/**
  - services/api/tests/mcp_api/test_server_hardening.py
  - services/api/tests/mcp_api/test_server_scope.py
  - services/api/tests/runtime_planes/test_mcp_builder.py
  - tests/security/mcp/test_client_server_roundtrip.py
  - tests/security/mcp/test_confused_deputy.py
  - tests/security/governance_tools/**
  - tests/evals/copilot_governance/**
  - docs/runbooks/copilot.md
tier1: []
tier2_appends: []
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/copilot/tools/registry.py
  - packages/core/neurosphere_core/governance/**
  - packages/core/neurosphere_core/interactions/**
  - packages/core/neurosphere_core/crypto/**
  - services/api/neurosphere_api/interactions/**
  - services/api/neurosphere_api/governance/**
  - services/api/neurosphere_api/mcp/server/factory.py
  - services/api/neurosphere_api/copilot/engine.py
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - tests/evals/copilot_groundedness/**
```
`builtin.py` and `__init__.py`: the `build_copilot_registry` function and exports only (PRP-78 placed it there); `tooling.py`: port binding lines in `build_tool_ports` only.

## Implementation blueprint

Parallelization: item 1 first (ports and models). Items 2 and 3 [P] after item 1 (separate modules). Item 4 after 2 and 3; item 5 after 4; item 6 after 5; item 7 last.

### Item 1 - Ports and metadata-only result models
- Deliverable: `governance_ports.py` (the six read and request ports, no content method anywhere), `governance_models.py` (row models with explicit fields; `INTERACTION_TOOL_FIELDS`), the schema-walk and import-graph tests.
- Owned files: those modules, `packages/core/tests/copilot_governance_tools/test_models.py`, `test_no_content_imports.py`.
- Depends on: PRP-104, PRP-105, PRP-109 merged.
- Acceptance criteria: criterion 4 (static half).
- Tests: the two files.
- Pattern references: `copilot/tools/ports.py:45-104`.

### Item 2 - Read tools  [P]
- Deliverable: `governance_tools.py` read handlers: `list_policies`, `list_violations`, `explain_violation` (fixed templates per rule kind), `search_interactions` (allowlisted projection, 30-day window, 50 rows), `get_governance_trail`; each derives readable domains from scope, clamps limits, cites ids.
- Owned files: `governance_tools.py`, `packages/core/tests/copilot_governance_tools/test_read_tools.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 1, 2, 3 and 5 on in-memory fakes.
- Tests: `test_read_tools.py`.
- Pattern references: `builtin.py:213-346`.

### Item 3 - Draft tools  [P]
- Deliverable: `request_policy_exception` and `draft_enforcement_mode_change` handlers (domain from the violation or binding store, permission check, capability check, idempotency key derived as `_propose_action` does, channel from the caller).
- Owned files: `governance_drafts.py`, `packages/core/tests/copilot_governance_tools/test_draft_tools.py`.
- Depends on: item 1.
- Acceptance criteria: criterion 6.
- Tests: `test_draft_tools.py`.
- Pattern references: `builtin.py:396-445`.

### Item 4 - Copilot registration and port binding
- Deliverable: `build_copilot_registry` adds `governance_specs(deps)` when ports are bound; `COPILOT_TOOL_NAMES`; `build_tool_ports` binds the ports from `app.state.governance_policy`, `app.state.interaction_explorer` and the trail assembler; no change to the engine or builder.
- Owned files: `builtin.py` (registry function), `__init__.py`, `services/api/neurosphere_api/copilot/tooling.py`, `packages/core/tests/copilot_governance_tools/test_registry.py`.
- Depends on: items 2 and 3.
- Acceptance criteria: default registry five tools; copilot registry includes the seven when bound and omits them when PRP-105 or PRP-104 components are disabled; PRP-113's hook runs before each.
- Tests: `test_registry.py`, `packages/core/tests/copilot`, `packages/core/tests/copilot_graph_tools`, `services/api/tests/copilot_tools_api`.
- Pattern references: PRP-78 item 4.

### Item 5 - MCP tools and audit observer
- Deliverable: `mcp/server/tools.py`: governance read specs and draft specs with descriptions plus the scope note, `ANNOTATIONS` rows (reads read-only and idempotent; drafts not read-only), `MCP_TOOL_NAMES`, `McpToolAuditor` passed as the registry observer for every MCP tool; update the pinned tool-list tests.
- Owned files: `mcp/server/tools.py`, `services/api/tests/mcp_governance_tools/**`, the five pinned test files.
- Must NOT touch: `factory.py` (PRP-113).
- Depends on: item 4.
- Acceptance criteria: criteria 1 (MCP side), 6 (MCP drafts) and 7.
- Tests: `services/api/tests/mcp_governance_tools/test_tools.py`, `test_audit.py`, `services/api/tests/mcp_api`, `services/api/tests/runtime_planes/test_mcp_builder.py`, `tests/security/mcp`.
- Pattern references: `mcp/server/tools.py:372-487`.

### Item 6 - Content negative suite and offline cases
- Deliverable: `tests/security/governance_tools/` (canary through PRP-102's in-memory store, assert absent from tool results, SSE, MCP responses, audit, logs; principal pseudonym and `content_ref` absent; scope and ABAC cases: no role, wrong domain, wrong customer, expired assignment, viewer without `govpolicy.read`); `tests/evals/copilot_governance/cases.yaml` and an unmarked runner on the recorded model.
- Owned files: `tests/security/governance_tools/**`, `tests/evals/copilot_governance/**`.
- Depends on: item 5.
- Acceptance criteria: criteria 4 (runtime half) and 8.
- Tests: `tests/security/governance_tools`, `tests/evals/copilot_governance`.
- Pattern references: PRP-103's `tests/security/capture_guards` canary harness.

### Item 7 - Integration and close-out
- Deliverable: `docs/runbooks/copilot.md` section "Governance tools" (tool list, permissions, metadata-only rule, draft-only rule, MCP audit); rebase; Tier-3 regeneration (`docs/reference/**`, status table, index); changelog fragment; completion note with the product check (can a steward answer "what violates our PII policy and why" in chat without opening another page?).
- Owned files: runbook section, this PRP file, Tier-3 files.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green.

## How the hard constraints are kept
- No content to the copilot or MCP: no tool has a content port; the result models are allowlists checked by a schema walk; a static import test bans the decrypting reader and key wrappers; a runtime canary suite covers results, SSE, MCP, audit and logs.
- Authorization on every path: each tool declares its permission, readable domains come from the server-derived scope, scope-shaped arguments are refused, out-of-scope ids look missing, PRP-113's hook runs first.
- One action path: drafts go through `ActionApi.draft` (mode change) or PRP-105's exception service (HITL); nothing confirms, approves or executes from chat or MCP.
- Audit without argument values for every call; no secrets or content in audit payloads (`content_guard`).
- No generated query: tools take typed filters only; explanations are fixed templates.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/copilot_governance_tools packages/core/tests/copilot packages/core/tests/copilot_graph_tools services/api/tests/copilot_tools_api services/api/tests/mcp_governance_tools services/api/tests/mcp_api services/api/tests/runtime_planes/test_mcp_builder.py tests/security/governance_tools tests/security/mcp tests/security/authz tests/evals/copilot_governance tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. Turning it off: the tools are registered only when their ports are bound, so disabling PRP-105's component (`NS_GOVPOLICY_ENABLED=false`) removes the policy tools and disabling PRP-104's explorer removes `search_interactions`; or revert the PR. The `mcp.tool_call` audit records stay as written.

## Live and open gates
None. A live model turn with these tools is part of PRP-80's operator-gated groundedness run (PRP-64); offline cases run on the recorded model.

## NOT building
Any tool that returns or summarizes captured content (GD-3); a tool that confirms, approves or executes; publish or retire tools (drafted from the UI and REST); free-text or generated queries over policies or interactions; legal or compliance verdicts in explanations; principal pseudonyms in model context; changes to `build_default_registry`.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 3, 5 and 6 are ASSUMPTIONS)

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

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files or calling raw APIs):
