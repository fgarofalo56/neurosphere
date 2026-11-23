---
name: PRP-78-copilot-graph-timeline-and-recommender-tools
status: active
started: 2026-11-22
priority: P0
order: 69
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 7
ns: NS-06, NS-02, NS-03, NS-08
depends_on: [PRP-70-contracts-revision-restored-scope, PRP-73-graph-access-and-sensitivity-questions, PRP-72-agent-and-tool-recommender-backend, PRP-71-realistic-seeded-world-and-demo-profile]
wave: W23
branch: prp-78-copilot-graph-tools
allow_parallel: true
issues: []
---

# PRP-78: Copilot graph, timeline and recommender tools, tool-call audit, demo-profile copilot

## Goal
Give the copilot the three tools the original PRD asked for and the shipped copilot lacks, all bounded and structured: `graph_query` (neighbours, impact and data-access questions over the catalog graph, depth and budget capped, scope server-derived, no model-authored query text), `get_timeline` ("what changed in the last hour": audit-recorded changes, metric shifts and new recommendations in one ordered list) and `recommend_agent` (the PRP-72 task-to-agent matcher). Every tool call, allowed or refused, is written to the audit chain; the SSE stream emits progress events before the model finishes; and the copilot answers in the local demo profile through an explicitly labelled recorded demo model, with the documented path to a real endpoint unchanged. It is for the operations lead and the SRE personas, who today get a disabled dock and, with an endpoint, a copilot that cannot answer "which agents touch EU customer data?" or "what changed in the last hour?". It runs in W23 after PRP-73 (access queries) and PRP-72 (matcher) because it consumes both.

Out of scope: `search_docs`, the 100-question groundedness set and Helm copilot values (PRP-80); provisional token streaming of unjudged text (decided against here, clarification 5); the first real-model turn (operator-gated, PRP-64); MCP exposure of the new tools (the MCP tool list in `services/api/neurosphere_api/mcp/server/tools.py` stays as is; PRP-69 or a follow-up); new catalog queries or matcher logic (PRP-73, PRP-72).

## Why
- Restores original 5e (`git show 9fbf5f4c:docs/PRD.md`): "Tool-calling supports at minimum: graph query, catalog lookup, telemetry metric pull, recommendation engine call." Shipped tools are five (`packages/core/neurosphere_core/copilot/tools/builtin.py:70-76`); `_require_query` refuses any `max_depth` other than 0 and any `traversal` (`builtin.py:119-131`), so no graph query is possible, and `list_recommendations` lists detector findings, not agent selection.
- Restores the 5e stories "As an operations lead, I want to ask 'which agents touch EU customer data?' and get a grounded answer with citations to graph nodes" and "As an SRE, I want to ask 'what changed in the last hour that could explain the error spike?' and get a timeline." Neither is answerable: no relationship tool, no residency filter, no change tool (gap analysis section 2, 5e rows).
- Restores 5g "Full audit logging of graph writes, catalog changes, and copilot tool-calls, retained per policy": tool calls live only in per-turn memory (`services/api/neurosphere_api/copilot/engine.py:208-216`); `configure_copilot` accepts a `refusal_sink` (`copilot/dependencies.py:175`) that `runtime/builders/copilot.py:214-237` never passes.
- The v1.2 line that constrains, not removes, this: `docs/PRD.md:30` "Use a declarative chart/query schema and sandboxed renderer, not generated JavaScript or unrestricted SQL/Cypher/KQL", and CLAUDE.md "No arbitrary LLM-generated SQL/Cypher/JavaScript execution". The original asked for "a templated graph query (Cypher/Gremlin)" (`9fbf5f4c:PRP.md:54`); this PRP restores the capability as bounded structured tools (gap analysis section 5 item 2). `docs/PRD.md:21` demoted agent selection, which PRP-72 restores and this PRP exposes.
- Copilot is off everywhere by default (`runtime/builders/copilot.py:92,118`, `docker-compose.yml:148`); the only model doubles are test fixtures (`copilot/models/recorded.py` replays one fixed scenario and ignores the request).
- First token: the engine buffers the whole model turn and releases text only after the judge (`engine.py:628-679`); the only early events are per-tool `started|ok|refused` (`engine.py:513-528`), and the first-token evidence (119-140 ms) excludes provider time (`docs/evidence/G07/copilot/README.md`).

## Acceptance criteria
- [ ] Given a steward of domain A and an agent X in A with `writes` edges to source S, When the model calls `graph_query` with a `StructuredQuery` `neighbors` from S, relation `writes`, direction `incoming`, Then X is returned with the edge, its provenance and evidence ids, both cited; nodes in a domain the caller cannot read never appear, not even as path intermediates.
- [ ] `graph_query` refuses `max_depth` above 3, more than 50 start ids, a `neighbors`/`impact_paths` query without traversal, any unknown key, any scope-shaped key and any string argument that is not part of the `StructuredQuery` contract; an over-budget walk returns `truncated` and the answer says so.
- [ ] Given sources tagged `sensitivity_categories: [pii]` or `residency_geography: eu_eea` (PRP-70 fields), When the model calls `graph_query` with a `list` query on `grounding_source` filtered on those fields and `access_mode: any`, Then the agents that read or write them are returned through the PRP-73 access query, cited per agent and per asset.
- [ ] Given a 1-hour window, `get_timeline` returns, newest first and at most 100 entries: audit-recorded changes (operation, subject id, outcome, time; never before/after bodies or actor names) only for domains where the caller holds `audit.read`; error and latency shifts between the window and the previous window from hour aggregates; recommendations created in the window; and a `sections_omitted` list naming any section it could not include and why.
- [ ] `recommend_agent` takes an `AgentMatchRequest` (PRP-70), runs the PRP-72 matcher in at most 5 readable domains (context-narrowed when the dock is narrowed), merges by score and cites each candidate entity; with no matcher composed the tool is not registered.
- [ ] Every tool invocation produces one audit record on the domain or read-audit chain (operation `copilot.tool_call`, channel `chat`, tool name, outcome `allowed|refused|failed`, domain ids, result count bound by `state_digest`); refusals carry the reason code; no argument value, prompt text or returned row is recorded; an audit write failure is logged and counted and never changes the answer.
- [ ] The SSE stream emits `progress` `{phase: model|tools|checking, iteration}` before each model pass and before the judge; the PRP-19 wire order and terminal semantics are otherwise unchanged and unknown-event tolerance in `frontend/src/features/copilot/stream.ts` keeps older clients working; the dock shows the phase.
- [x] (Clarification 6, decided 2026-11-16) `NS_COPILOT_MODE=recorded` is accepted only with `NS_ENV=local` (otherwise `misconfigured`); it composes `RecordedDemoAdapter`, which answers a fixed list of demo questions by calling the real tools and composing an extractive answer from the tool results it received, cites only issued handles, and answers anything else with an abstention; `GET /api/v1/copilot/status` reports `synthetic: true` and the dock labels answers "Recorded demo model, not AI".
- [ ] The existing copilot suites, the PRP-12 injection corpus (78/78, 0 overscoped) and the MCP and reports registries (five tools, unchanged) stay green; new injection cases cover traversal smuggling, depth inflation and timeline window inflation.
- PRP exit: touched suites, `tests/security`, ruff, pyright, frontend lint/typecheck/test, `validate_planning.py` pass; PR open with CI green; live model turn written OPEN and handed to PRP-64.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Graph tool input | free graph query text; `StructuredQuery` | `StructuredQuery` (`neighbors`, `impact_paths`, `list` on `grounding_source`), the existing allowlisted contract (`docs/PRD.md:30`); `access_mode` is a tool-level argument beside the query (PRP-70 adds no such `StructuredQuery` field) |
| 2 | Depth cap | contract max 5; copilot cap | Copilot cap 3, 100 nodes, 300 edges (server constants), below the contract ceiling |
| 3 | Where new tools register | extend `build_default_registry`; separate builder | New `build_copilot_registry`; `build_default_registry` keeps exactly five tools because MCP (`mcp/server/tools.py`) and reports (`runtime/builders/planes.py:333`) build on it |
| 4 | Timeline for callers without `audit.read` | deny; partial | Partial with `sections_omitted` (ASSUMPTION: metric and recommendation sections need only `data.read`) |
| 5 | Provisional token streaming | stream then retract; progress events only | Progress events only: unjudged text is never shown (PRP-19 terminal semantics); ASSUMPTION, recorded for owner review |
| 6 | Local demo copilot | stay disabled; recorded demo model | Decided by the owner 2026-11-16 ("Allow recorded mode locally", D15): allow a `recorded` mode for the LOCAL demo only, under three conditions: it works only when `NS_ENV=local`, it is labelled synthetic in status and UI, and it answers by quoting real tool results. This overrides, for the local demo only, the 2026-11-11 PRP-19 round 2 decision "No fake or sandbox model mode"; hosted Azure still needs a real approved model endpoint. Background: that decision said "No fake or sandbox model mode"; the 2026-11-16 restored-scope assignment asks for "copilot on in the local demo profile with the recorded model" and PRP-71 could not deliver it. Resolution: this PRP owns a `recorded` mode (`NS_COPILOT_MODE=recorded`, only with `NS_ENV=local`, labelled synthetic in status and UI, extractive over real tool results, never default outside the demo profile) and the demo-profile switch (`NS_DEMO_COPILOT_MODE`, shipped by PRP-71 as `disabled`). History: the fallback (descope items 6 and 8) was not needed after the 2026-11-16 decision |
| 7 | Audit of allowed tool calls | refusals only; every call | Every call, read-audit failure rule (PRP-48 decision 3: a failed read-audit write is logged and counted, never blocks) |
| 8 | Domains for `recommend_agent` | all readable; capped | At most 5 readable domains, context-narrowed first; truncation flagged |
| 9 | Geography filter for the `list` access query (decided by the owner 2026-11-22 at plan approval) | map `eu_eea` to region group `eu`; two-step lookup | Two-step: the shipped PRP-73 `AccessQuery` has no `residency_geography` filter (only `residency_regions`/`region_group`) and `catalog/**` is must-not-touch, so `graph_query` first runs the catalog `list` on `grounding_source` with the contract filters through the existing `CatalogReader` port (at most 50 asset ids, truncation flagged), then `who_accesses(asset_ids=..., modes=...)` |
| 10 | Demo copilot switch blocked by the seeded stored setting (decided by the owner 2026-11-22) | leave demo off; extend item 8 | Extend item 8: `scripts/sandbox/sbx_demo_settings.py` seeds a stored `copilot` setting with `enabled: false`, which beats env (PRP-45), and `tests/unit/demo_profile/test_compose_passthrough.py` pins `disabled`; item 8 also owns those two files and `tests/unit/demo_profile/test_demo_settings.py` |
| 11 | Pre-existing copilot tests pin the old SSE sequence, status JSON and five-tool offer (decided by the owner 2026-11-22) | hide progress behind a flag; extend item 5 | Extend item 5: it also owns `services/api/tests/copilot_api/{test_abstention,test_copilot_status,test_engine_policy,test_sse_contract}.py` and updates their pinned expectations additively (the `progress` event, `CopilotStatus.synthetic`, `get_timeline` in the offered tools); `tests/integration/copilot/**` is already owned |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/copilot/tools/builtin.py` - `_readable_domains`, `_require_query`, `_filter_values`, `_build_result`, `build_default_registry` (`:448`).
- `packages/core/neurosphere_core/copilot/tools/registry.py` - `ToolRegistry.invoke` (`:143`), `RefusalSink`, `SCOPE_SHAPED_KEYS`.
- `packages/core/neurosphere_core/copilot/tools/ports.py`, `args.py` - port and argument conventions.
- `services/api/neurosphere_api/copilot/engine.py` - `run`, `_tool_phase` (`:499`), `_invoke`, `_tool_content` (citation handles), `_judge` (`:681`).
- `services/api/neurosphere_api/runtime/builders/copilot.py` - `CopilotMode`, `_install` (`:214`), `build` (`:260`).
- `packages/core/neurosphere_core/catalog/protocol.py:390-470` - `GraphResult`, `NeighborsRequest`, `ImpactRequest`, `GraphQuery`; `app.state.catalog_graph` set in `runtime/builders/data.py:247-256`.
- `services/api/neurosphere_api/audit/search_store.py` (`AuditSearchFilter`, `AuditSearchStore`) and `audit/access.py:182` `resolve_chains`.
- `services/api/neurosphere_api/authz/read_audit.py` - allowed-read record shape and failure rule.
- `packages/core/neurosphere_core/copilot/models/recorded.py` - `FixtureAdapter`, `AdapterDescriptor(synthetic=True)`.
- `PRPs/backlog/PRP-72-agent-and-tool-recommender-backend.md`, `PRPs/backlog/PRP-73-graph-access-and-sensitivity-questions.md` - "Interfaces provided" (names below are copied from them).

### Interfaces consumed
- PRP-70: `StructuredQuery` keyword fields `tag`, `capability`, `sensitivity_category`, `residency_region`, `residency_geography`, boolean `contains_personal_data`; `AgentMatchRequest`, `AgentMatchResponse`, `AgentMatchCandidate`, `AgentMatchSignal`.
- PRP-73 "Interfaces provided": `neurosphere_core.catalog.graph.access` (`AccessQuery`, `AccessResult`, `AccessRow`, `AccessEngine` with `who_accesses` and `dependents`, `MAX_ASSET_PAGES`, `MAX_ACCESSORS`); `region_groups`. PRP-73 composes no component ("component name none"), so `tooling.build_tool_ports` constructs the `AccessEngine` over the shared catalog repository; the `AccessReader` port here wraps `AccessEngine.who_accesses`.
- PRP-72 (purpose: a core matcher taking the server-derived scope, one domain and a match request, returning ranked candidates with per-signal explanation). PRP-72 "Interfaces provided": `neurosphere_core.recommendations.matching.AgentMatcher.match(scope, domain, request: AgentMatchRequest) -> AgentMatchResponse` on `app.state.agent_matcher` (optional component `agent_matcher`) and the port `neurosphere_core.recommendations.matching.AgentMatchReader` (a `Protocol` PRP-72 defines; this PRP defines no port of that name and only re-exports it from `copilot/tools/ports.py`); absent means `recommend_agent` is not registered. Wire shapes are PRP-70's `AgentMatchRequest` and `AgentMatchResponse`; no conversion adapter is needed.
- Shipped: `GraphQuery` on `app.state.catalog_graph` (PRP-10/35), `AUDIT_SEARCH_STORE` and `AUDIT_REPOSITORY` shared keys (PRP-40, PRP-06), `AggregateReader` (`AGGREGATE_READER`), `RecommendationStore`, `build_allowed`/`build_denied` (`packages/core/neurosphere_core/audit/builders.py:175-181`), PRP-45 stored copilot setting overlay. PRP-55, PRP-58 and PRP-60 are treated as shipped; nothing here depends on them.

### Interfaces provided
- Core: `neurosphere_core.copilot.tools.graph` (`graph_query`, caps `MAX_GRAPH_DEPTH=3`, `MAX_GRAPH_NODES=100`, `MAX_GRAPH_EDGES=300`), `.timeline` (`get_timeline`, `TimelineEntry`, `MAX_TIMELINE_WINDOW=24h`), `.matching` (`recommend_agent`); ports `GraphReader`, `AccessReader`, `ChangeLogReader` in `ports.py`, which also re-exports PRP-72's `AgentMatchReader`; `CopilotToolDependencies` and `build_copilot_registry(deps, *, sink, observer)`; `ToolCallObserver` protocol and `ToolCallEvent` in `registry.py`; `COPILOT_TOOL_NAMES`.
- Core: `neurosphere_core.copilot.models.demo.RecordedDemoAdapter` and scripts under `copilot/models/fixtures/demo/`.
- API: `neurosphere_api.copilot.tooling` - `build_tool_ports(ctx)` (the one place the builder binds tool ports; PRP-80 adds `search_docs` here without touching the Tier-1 builder), `AuditChangeLogReader`, `CopilotToolAuditor` (observer plus refusal sink).
- SSE event `progress` {`phase`, `iteration`}; `CopilotStatus.synthetic` (bool); `NS_COPILOT_MODE=recorded` (local only); audit operation `copilot.tool_call`.

### Patterns to match
- Tool shape and double domain filter: `builtin.py:213-253` (`_search_catalog`).
- Allowed-read audit with failure counting: `services/api/neurosphere_api/authz/read_audit.py:176`.
- Multi-chain audit merge, newest first: `services/api/neurosphere_api/audit/search.py:44-60` (`collect`).
- Scripted adapter for tests: `services/api/tests/copilot_api/copilot_api_harness.py:304-335` (`ScriptedAdapter`, `say`, `call`).
- Builder override seam: `runtime/builders/copilot.py:260-280` (`ctx.overrides.model_adapter`).

### Gotchas
- Core cannot import `neurosphere_api`: the timeline's audit source is a core `ChangeLogReader` port implemented in `neurosphere_api.copilot.tooling` over `AuditSearchStore` and `resolve_chains`.
- The model sees `cite_as` handles, never record ids (`engine.py:249-275`); `RecordedDemoAdapter` must read handles from the tool turns in `ModelRequest.turns`, or every answer abstains `unsupported_citation`.
- `StructuredQuery` traversal relations allow `grants_access_to`; keep the copilot relation allowlist explicit and test it.
- Adding a tool to `build_default_registry` would silently add it to MCP and report runs: tests in `services/api/tests/mcp_api/test_server_scope.py` and `packages/core/tests/copilot/test_tool_allowlist.py:46-54` pin the five names; leave them unchanged.
- New SSE event names must stay additive: the frontend parser drops unknown events (`stream.ts:200-260`); the e2e mock (`frontend/tests/mock-api/copilot.ts`) needs a `progress` fixture.
- New test directories: `packages/core/tests/copilot_graph_tools/`, `services/api/tests/copilot_tools_api/` (unique names; `copilot` and `copilot_api` exist).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/copilot/tools/**
  - packages/core/neurosphere_core/copilot/models/demo.py
  - packages/core/neurosphere_core/copilot/models/fixtures/demo/**
  - packages/core/tests/copilot_graph_tools/**
  - services/api/neurosphere_api/copilot/**
  - services/api/tests/copilot_tools_api/**
  - services/api/tests/copilot_api/test_abstention.py
  - services/api/tests/copilot_api/test_copilot_status.py
  - services/api/tests/copilot_api/test_engine_policy.py
  - services/api/tests/copilot_api/test_sse_contract.py
  - services/api/openapi.json
  - docs/reference/**
  - services/api/tests/runtime_planes/test_copilot_builder.py
  - tests/integration/copilot/**
  - frontend/src/features/copilot/**
  - frontend/tests/mock-api/copilot.ts
  - frontend/tests/e2e/copilot.spec.ts
  - docs/runbooks/copilot.md
  - infra/dev/demo-profile.env
  - scripts/sandbox/sbx_demo_check.py
  - scripts/sandbox/sbx_demo_settings.py
  - tests/unit/demo_profile/test_demo_settings.py
  - tests/unit/demo_profile/test_compose_passthrough.py
tier1:
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - docker-compose.yml
  - Makefile
tier2_appends: []
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/recommendations/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/recommendations/**
  - services/api/neurosphere_api/mcp/**
  - services/api/neurosphere_api/runtime/builders/planes.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - infra/bicep/**
  - infra/demo/**
  - infra/helm/**
  - infra/appservice/**
  - infra/dev/fakes/**
```

## Implementation blueprint

Parallelization: items 1, 2 and 3 are [P] (separate core modules and test files; each adds its own port class at the end of `ports.py`, merged in order 1, 2, 3). Item 4 after 1-3. Items 5 and 6 after 4; item 7 after 5; item 8 after 6 and 7.

### Item 1 - `graph_query` tool  [P]
- Deliverable: `copilot/tools/graph.py` and `GraphQueryArgs {query: StructuredQuery, access_mode: read|write|any|None}`; `neighbors`/`impact_paths` through `GraphReader` (the `GraphQuery` protocol) with copilot caps and relation allowlist; `list` on `grounding_source` with `access_mode`: contract filters resolved to at most 50 asset ids through the existing `CatalogReader` port, then `AccessReader` (PRP-73) `who_accesses` on those ids (clarification 9); records for nodes and edges with provenance and evidence ids; every node re-filtered against readable domains.
- Owned files: `copilot/tools/graph.py`, `copilot/tools/ports.py` (append `GraphReader`, `AccessReader`), `packages/core/tests/copilot_graph_tools/test_graph_query.py`.
- Must NOT touch: `builtin.py` tool bodies.
- Depends on: PRP-70, PRP-73 merged.
- Acceptance criteria: criteria 1-3.
- Tests: `test_graph_query.py`, `test_graph_scope.py` (out-of-scope intermediates, depth and budget refusals).
- Pattern references: `builtin.py:213-253`, `catalog/protocol.py:422-470`.

### Item 2 - `get_timeline` tool  [P]
- Deliverable: `copilot/tools/timeline.py`, `TimelineArgs {window_minutes 5..1440, sections}`; `ChangeLogReader` port; metric shifts from `MetricsReader` hour grain (errors, latency) comparing window and previous window; recommendations by `created_at`; merge newest first, cap 100, `sections_omitted`.
- Owned files: `copilot/tools/timeline.py`, `ports.py` (append `ChangeLogReader`), `packages/core/tests/copilot_graph_tools/test_timeline.py`.
- Depends on: none.
- Acceptance criteria: criterion 4; actor pseudonyms and before/after bodies never in records.
- Tests: `test_timeline.py`.
- Pattern references: `builtin.py:256-305` (`_get_cost_summary`), `audit/search.py:44-60`.

### Item 3 - `recommend_agent` tool  [P]
- Deliverable: `copilot/tools/matching.py`, `RecommendAgentArgs {request: AgentMatchRequest}`; uses PRP-72's `AgentMatchReader` (re-exported by `ports.py`, not redefined); domain fan-out cap 5; merge by score; candidate records cite entity ids with signals.
- Owned files: `copilot/tools/matching.py`, `ports.py` (re-export `AgentMatchReader` from PRP-72), `packages/core/tests/copilot_graph_tools/test_recommend_agent.py`.
- Depends on: PRP-72 merged.
- Acceptance criteria: criterion 5; a scope-shaped key inside `request` is refused by contract (`additionalProperties: false`).
- Tests: `test_recommend_agent.py`.
- Pattern references: `builtin.py:308-346` (`_list_recommendations`).

### Item 4 - Copilot registry and tool-call observer
- Deliverable: a documented extension point for later guards and tools (PRP-113 adds a pre-invoke policy decision in `ToolRegistry.invoke`; PRP-116 adds the governance tools): `ToolCallObserver` and a registration hook are the only seams, ownership of `copilot/tools/registry.py` stays with this PRP in W23 and is handed on in the completion note; `build_copilot_registry` (five defaults plus the three new tools when their ports are bound); `ToolCallObserver` called by `ToolRegistry.invoke` after every call with name, outcome, domain ids and record count (no values); `COPILOT_TOOL_NAMES`; `build_default_registry` unchanged.
- Owned files: `copilot/tools/registry.py`, `copilot/tools/__init__.py`, `copilot/tools/builtin.py` (registry function only), `packages/core/tests/copilot_graph_tools/test_registry.py`.
- Depends on: items 1-3.
- Acceptance criteria: default registry still five tools; copilot registry eight with all ports; observer sees refusals and successes; existing `packages/core/tests/copilot` passes.
- Tests: `test_registry.py`, `packages/core/tests/copilot`.
- Pattern references: `registry.py:143-190`.

### Item 5 - Engine, progress events and audit sink
- Deliverable: engine builds the copilot registry from `ToolPorts` plus new optional ports; `progress` SSE event; `neurosphere_api.copilot.tooling` with `build_tool_ports(ctx)`, `AuditChangeLogReader`, `CopilotToolAuditor` (one record per call, PRP-48 failure rule); `CopilotStatus.synthetic`.
- Owned files: `services/api/neurosphere_api/copilot/{engine,models,dependencies,tooling}.py`, `services/api/tests/copilot_tools_api/test_progress_and_audit.py`, `test_injection_graph.py`.
- Depends on: item 4.
- Acceptance criteria: criteria 6, 7 and 9.
- Tests: the two new files plus `services/api/tests/copilot_api` (corpus) and `tests/security`.
- Pattern references: `authz/read_audit.py:176`, `engine.py:499-535`.

### Item 6 - Recorded demo adapter and `recorded` mode
- Decision: clarification 6 was decided by the owner on 2026-11-16 (D15); no owner stop applies to this item or item 8.
- Deliverable: `RecordedDemoAdapter` with demo scripts (which agents touch EU data, who writes to a named source, what changed in the last hour, which agent should summarize a support ticket, cost this week); builder accepts `recorded` only under `NS_ENV=local`; builder binds ports through `build_tool_ports` and passes the auditor.
- Owned files: `copilot/models/demo.py`, `copilot/models/fixtures/demo/**`, `runtime/builders/copilot.py`, `services/api/tests/runtime_planes/test_copilot_builder.py`, `services/api/tests/copilot_tools_api/test_demo_adapter.py`.
- Depends on: item 5.
- Acceptance criteria: criterion 8; with `NS_ENV` other than local, `recorded` reports `misconfigured`; the five demo questions answer with resolving citations on the sandbox world.
- Tests: the two test files; `tests/integration/copilot` (unmarked wiring test extended).
- Pattern references: `copilot/models/recorded.py:101-112`, `runtime/builders/copilot.py:260-280`.

### Item 7 - Dock: progress and demo label
- Deliverable: `stream.ts` parses `progress`; dock shows the phase and, when `synthetic`, the "Recorded demo model, not AI" label; mock fixture and e2e case.
- Owned files: `frontend/src/features/copilot/**`, `frontend/tests/mock-api/copilot.ts`, `frontend/tests/e2e/copilot.spec.ts`.
- Depends on: item 5.
- Acceptance criteria: unit tests for parse and label; a11y unchanged; Playwright copilot spec passes on the mock API.
- Tests: `frontend/src/features/copilot/copilot.test.tsx`, `frontend/tests/e2e/copilot.spec.ts`.
- Pattern references: `stream.ts:213-260`.

### Item 8 - Demo profile default, runbook and close-out  [serial-after: PRP-71]
- Deliverable: switch the PRP-71 local demo profile to the recorded mode: set `NS_DEMO_COPILOT_MODE=recorded` in `infra/dev/demo-profile.env` and, if compose does not already map it to `NS_COPILOT_MODE`, the one passthrough line in `docker-compose.yml` (Tier 1 in this PRP's ownership; nobody else owns it in W23). Remove the `pending_prp_78` state from `scripts/sandbox/sbx_demo_check.py` (PRP-71 file, granted here for that one check). Runbook section (recorded mode, the eight tools, the real-endpoint path, audit records); Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`); changelog fragment; completion note with OPEN live turn and env vars.
- Owned files: `docs/runbooks/copilot.md`, `infra/dev/demo-profile.env`, `scripts/sandbox/sbx_demo_check.py`, `scripts/sandbox/sbx_demo_settings.py` (no stored `copilot` row in recorded mode, clarification 10), `tests/unit/demo_profile/test_demo_settings.py`, `tests/unit/demo_profile/test_compose_passthrough.py`, `docker-compose.yml` (one line), this PRP file, Tier-3 files.
- Depends on: items 6, 7; PRP-71 merged.
- Acceptance criteria: validation gates pass; product check: a fresh demo stack answers the five demo questions in the dock without editing files.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/copilot packages/core/tests/copilot_graph_tools services/api/tests/copilot_api services/api/tests/copilot_tools_api services/api/tests/runtime_planes services/api/tests/mcp_api services/api/tests/reports tests/integration/copilot tests/security services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: audit records are new appends; no container. Turn off: `NS_COPILOT_MODE=disabled` (default) removes the copilot; without PRP-72/PRP-73 components on `app.state` the corresponding tools are simply not registered. Revert the PR to return to the five-tool copilot; audit records written meanwhile stay valid.

## Live and open gates
The first real-model turn with the new tools (`NS_LIVE_APPROVED=1`, an operator-approved Foundry endpoint in Limitlessdata) is OPEN and handed to PRP-64 (a row to add there). First-token time against a real provider stays OPEN (G07). Everything here is proven with the recorded demo adapter, scripted test adapters and in-memory twins.

## NOT building
`search_docs` and the groundedness set (PRP-80); provisional token streaming; MCP exposure of the new tools; model-authored query text of any kind; any policy, violation, interaction or governance tool (PRP-116 adds them; the copilot never gets an interaction-content tool); a pre-invoke policy decision (PRP-113); copilot write tools beyond the existing `propose_action`; a hosted recorded mode; usage metrics for weekly active copilot users (follow-up).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4 and 5 are ASSUMPTIONS; row 6 was decided by the owner on 2026-11-16)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-78-item-1 | review pass 1 (items 1-3) APPROVED 2026-11-22, no blockers; follow-up: explicit node field allowlist in `_node_row`; | sonnet; 33d2bdbf verify PASS (pytest 273); merged a57c3d84 2026-11-22; `grants_access_to` excluded from copilot relations |
| 2 | merged | prp-78-item-2 | review pass 1 APPROVED; | sonnet; 4e4f2463 verify PASS (pytest 248); merged bd73ba9d 2026-11-22 (ports.py tail conflict resolved, both kept); audit.read-only caller is denied, not partial (item 4 fixes) |
| 3 | merged | prp-78-item-3 | review pass 1 APPROVED; | sonnet; 215f638b verify PASS (pytest 242); merged 3ebfe791 2026-11-22; post-merge wave A: ruff, pyright 0, pytest 311 passed |
| 4 | merged | prp-78-item-4 | review pass 2 (items 4-5) APPROVED 2026-11-22; | sonnet; 3e7c9846 verify PASS (ruff, pyright 0, pytest core+mcp 538 passed); merged 157a7cfe 2026-11-22 (post-merge core 333 passed); timeline partial fix + review follow-ups 2, 4 folded in; `ToolResult.domain_ids` excluded from dumps (MCP shape unchanged) |
| 5 | merged | prp-78-item-5 + prp-78-item-5-fix1 | sonnet; 1c1ae24a + fix 5cf77e5e (13 pinned tests updated, clarification 11); verify PASS 2026-11-22 (ruff, pyright 0, corpus 78/78, pytest 2623 passed); merged 120325ac; review pass 2 APPROVED; follow-ups: builtin tools populate domain_ids, share `_subject_target`, change-log 5-page cap should flag truncation, document `synthetic=false` when not ready |
| 6 | merged | prp-78-item-6 | review pass 3 (items 6-8) APPROVED 2026-11-22; | sonnet; 652eb64d verify PASS 2026-11-22 (ruff, pyright 0, pytest 676 passed; agent wide run 2446 passed); merged 625f8042 (post-merge 103 passed); descriptor kind `fixture` (no `recorded_demo` AdapterKind), synthetic true; stored setting cannot select recorded; integration wiring test not extended (builder tests cover it) |
| 7 | merged | prp-78-item-7 | review pass 3 APPROVED; follow-up: keep the progress live region mounted so the first phase is announced; | merged 1bc823d0 2026-11-22 (review in pass 3); | sonnet; dispatched against item 5's committed wire shape; 9a89f7bb verify PASS 2026-11-22 (eslint 0, tsc 0, vitest copilot 40 passed, e2e catalog+copilot 32 passed; agent's 3 catalog axe failures were full-suite load flakes, pass in isolation on both branches); merges after 5 |
| 8 | merged | prp-78-item-8 | sonnet; 60e22d16 verify PASS 2026-11-22 (ruff, pytest demo_profile+sandbox_stack+docs+release+openapi drift 399 passed, validate_planning PASS); merged 6db8987d; review pass 3 APPROVED; also touched `tests/integration/real_stack/test_demo_profile.py` (pending_prp_78 removal); follow-up: runbook note to reseed a demo DB that already holds the disabled copilot row; no compose edit needed (passthrough + NS_ENV local already present) |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: `NS_COPILOT_MODE=recorded` (local only).
- Follow-up issues:
- Product check (can an operator use it without editing files):
