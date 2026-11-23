---
name: PRP-100-telemetry-tool-service-identity-and-aggregates
status: shipped
started: 2026-11-23
shipped: 2026-11-23
pr: 391
priority: P0
order: 100
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-05
depends_on: [PRP-70-contracts-revision-restored-scope, PRP-71-realistic-seeded-world-and-demo-profile]
wave: W22
branch: prp-100-telemetry-tool-service-identity
allow_parallel: true
issues: []
---

# PRP-100: Telemetry tool and service identity, and per-tool and per-service aggregates

## Goal
Carry the identity of a tool, a service and an MCP server from the OTLP edge to the aggregates, so that "which tool is failing" and "which service is slow" are answered from measured spans and not guessed from the graph. The OTLP mapping keeps the tool name and the service attributes it drops today and fills the three optional PRP-70 (F1) telemetry fields; a pure resolver builds the canonical tool and service ids; the subject-series model gains the kinds `tool` and `service`; the aggregates worker rolls up calls, errors and latency per tool and per service the same way it does per agent and per model today; the reader and the health thresholds are the existing ones. It is for the SRE on the live map and for PRP-74 (map topology), whose last item swaps its inferred service and tool health for these points, and for PRP-134 (success metrics) and PRP-109 (north-star scenario). It runs in W22, after the PRP-70 contracts (with F1) and the PRP-71 seed (which emits tool and service identity).

Out of scope: the F1 schema change itself (PRP-70 item 7 owns `telemetry-event.schema.json`; this PRP only consumes the generated bindings); the map node kinds, facets, derived health and push (PRP-74 and PRP-77); the SDK setting tool and service identity on spans (PRP-79); resolving `external_agent_id` to a canonical agent id (nothing does this today, see Why; PRP-137 fixes it in the earlier wave W19, and is the source of agent series for OTLP agents); the content channel and anything about bodies (PRP-103); alert rules on tool or service error rates (PRP-132); cost per tool (no price basis exists).

## Why
- The OTLP mapping reads the operation name and maps `execute_tool` to span kind `tool_call` (`services/api/neurosphere_api/ingest/otlp_mapping.py:81-90`, `:255`, `:270`) but never reads a tool name or a service name: `map_span` fills only `external_agent_id` from `gen_ai.agent.id` (`:265`). A `tool_call` span is therefore anonymous. The graph builder gets a tool only when a producer happens to put a canonical tool ref in `data_source_refs` (`services/workers/neurosphere_workers/projections/catalog/mapping.py:188-200`).
- The telemetry envelope has no tool or service property and is closed (`packages/contracts/schemas/telemetry/v1/telemetry-event.schema.json:7` `additionalProperties: false`; agent identity is `external_agent_id` and `canonical_agent_id` at `:46-55`). PRP-70 folds the additive F1 fields in (design section 3.1); without them the PRP-71 demo world has no tool or service identity.
- `SubjectKind = Literal["agent", "model"]` (`packages/core/neurosphere_core/aggregates/subject.py:35`), `SubjectPoint.subject_kind` is the same two values (`aggregates/models.py:277`), and the aggregates worker counts only `model_call` spans (`services/workers/neurosphere_workers/aggregates/mapping.py:153-154`). A tool or service has no series at all (PRP-74 clarification 4 says so and falls back to inference).
- The map therefore infers service and tool health from neighbours: PRP-74 clarification 5 plans `derive_health` (failing when at least half of at least two dependents fail; it "cannot show ok"). The measured error rate exists only for agents and models (`map/service.py:288-289` `health_for_error_rate(point.error_rate)`, thresholds `subject.py:44-45`).
- Verified while planning: no production code resolves `external_agent_id` to `canonical_agent_id` (`grep` over `services/` and `packages/core/` finds the field read by aggregates, projections, evaluation and recommendations, and written only by tests, the sandbox generator `sandbox/costs.py:76` and the Foundry poller for the external id `ingestion/foundry_discovery/poller.py:246`). OTLP agents therefore never get an agent subject series. This PRP must not copy that gap for tools and services (clarification 2).
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool" and every identified gap planned. `docs/PRD.md` NS-05 promises a live map; original PRD 5d asked for "node health, traffic volume, recent errors" of agents, services and tools.

## Acceptance criteria
- [ ] Given an OTLP span with operation `execute_tool` and a tool-name attribute, When it is posted to the ingest route, Then the stored `TelemetryEvent` carries `tool.tool_name` and `tool.external_tool_id` and the span kind stays `tool_call`; a span without a tool name leaves `tool` null (never an empty object), and no existing OTLP mapping test changes.
- [ ] Given a span whose resource carries a service name, Then `service.external_service_id` is set; given an MCP server reference attribute, Then `mcp_server_ref` is set; every value is length-capped and validated against the F1 field patterns, and an invalid value is dropped with a counted reason, never rejects the span.
- [ ] `resolve_subjects` builds `<cloud>:<customer>:<source>:tool:<id>` and `<cloud>:<customer>:<source>:service:<id>` deterministically from the event scope and the external id (lowercased, `[a-z0-9._/=-]` only), with no catalog lookup; the same input always gives the same id; an id that fails the canonical grammar yields no key, not a bad one.
- [ ] `SubjectKind` is `agent | model | tool | service`; `subject_series_key("tool", id)` gives `tool:<canonical id>` and `subject_series_key("service", id)` gives `service:<canonical id>`; agent and model keys are byte-identical to today.
- [ ] Given hot-window `tool_call` spans for one tool with 10 calls and 3 errors, Then a `SubjectPoint` of kind `tool` has `event_count` 10, `error_count` 3, `error_rate` 0.3 and p50/p95 from measured durations; spans with no known outcome count in `unknown_outcome_count` and `error_rate` is null when no outcome is known, never 0 (same rules as agents).
- [ ] Given spans carrying a service reference (any span kind except `unknown`), Then a `service` point is produced with the same fields; a span with both agent and model identity still produces the agent and model points exactly as before (existing `test_subject_mapping.py` and `test_subject_rollups.py` pass unchanged).
- [ ] `SubjectMetricsReader.latest_subject_points` accepts `tool` and `service`, is scoped to the customer and domain of the caller, and `health_for_error_rate` gives `ok`, `degraded`, `failing` or `unknown` for them at the existing 0.05 and 0.25 thresholds.
- [ ] Given the PRP-71 incident (a failing service with downstream agents), When the seeded telemetry is aggregated, Then the failing service's point has an error rate at or above the failing threshold and an unrelated service's point is `ok`; the check reads `incident-manifest.json`, not a hard-coded id.
- [ ] No event, aggregate document, log line or audit record gains a body, a header value or an attribute value other than the capped names and ids above; attribute values that are not read are never copied (negative test with a span carrying `gen_ai.input.messages`: still dropped at the edge).
- PRP exit: touched suites, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated only if a route model changed (none expected).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Tool and service attribute names in OTLP | From memory; fetch the OpenTelemetry GenAI and resource conventions | Verify-first item 1 fetches the official OpenTelemetry semantic-conventions pages, writes the attribute names, the fetch date and their stability level to `docs/connectors/verification/otel-genai-tool-service.md` (new), and codes only names found there. Not asserted here |
| 2 | Where canonical tool and service ids are built | Ingest pipeline step; aggregates at rollup time | ASSUMPTION: the pure `resolve_subjects` function is called by the aggregates mapping at rollup time, so no edit to `ingestion/pipeline.py` (not in this PRP's ownership list) is needed. The stored event keeps `canonical_tool_id` and `canonical_service_id` null unless a producer set them; the rollup uses the producer's value when valid, else the derived one |
| 3 | Which spans make a service point | Only `model_call`; any span with a service reference | ASSUMPTION: any span that carries a service reference and whose kind is not `unknown`, because a service is called by tool, retrieval and agent spans, not only by model calls |
| 4 | Tool identity with no tool name | Fabricate from span name; leave unknown | Leave null (nulls are never zero); the span still counts for its agent as today |
| 5 | Series cap | New cap per kind; shared cap | ASSUMPTION: the existing `MAX_SUBJECT_SERIES_PER_BUCKET` (5000, `subject.py:38`) stays one shared cap per (domain, grain, bucket), with the existing overflow counter; a per-kind cap is a follow-up if the demo shows starvation |
| 6 | Agent resolution gap (Why, fifth bullet) | Fix here; separate PRP | PRP-137 (W19, merges earlier) resolves `external_agent_id` to a canonical id where the workers read stored events; this PRP reads `canonical_agent_id` unchanged and needs nothing from PRP-137 for tool and service series. Agent series for OTLP agents, and every consumer of per-agent data (PRP-74, PRP-134), depend on PRP-137, not on this PRP |
| 7 | Cost per tool or service | Allocate; leave out | Leave out: no price basis; points carry counts, errors and latency only |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/ingest/otlp_mapping.py` - `map_span` (`:230-280`), `_OPERATION_KIND`, `_first_text`, `AGENT_ID_ATTRS`.
- `packages/contracts/schemas/telemetry/v1/telemetry-event.schema.json` and the generated `neurosphere_contracts.telemetry.v1.telemetry_event` - the F1 fields after PRP-70 merges.
- `packages/core/neurosphere_core/aggregates/subject.py` - `SubjectKind`, `subject_series_key`, `health_for_error_rate`, `SubjectMetricsReader`.
- `packages/core/neurosphere_core/aggregates/models.py:268-290` - `SubjectPoint`; `aggregates/cosmos.py:125-160` - `latest_subject_points` query.
- `services/workers/neurosphere_workers/aggregates/mapping.py` - `contribution_from_event`, `EventFact`; `rollups.py:194-259` - `_subject_point`, `_subjects`.
- `services/workers/neurosphere_workers/aggregates/tests/support.py` and `test_subject_mapping.py` - fixture style.
- `services/workers/neurosphere_workers/projections/catalog/mapping.py:110-124,188-200` - `_owned` canonical check and the existing tool-ref path.
- `services/api/neurosphere_api/map/service.py:240-300` - the reader's caller (PRP-74 edits it, not this PRP).
- `PRPs/backlog/PRP-74-live-map-topology-backend.md` (clarifications 4 and 5) and `PRP-71-realistic-seeded-world-and-demo-profile.md` (incident manifest).

### Interfaces consumed
- PRP-70 (F1): optional nullable `TelemetryEvent.tool` {`external_tool_id`, `canonical_tool_id`, `tool_name`}, `TelemetryEvent.service` {`external_service_id`, `canonical_service_id`}, `TelemetryEvent.mcp_server_ref`, with a minor `schema_version` bump. UNVERIFIED names: PRP-70 as written does not yet list F1 (the design's section 6 change to PRP-70); item 2 reads the generated bindings and uses the real names.
- PRP-71: seeded telemetry with tool and service identity and `incident-manifest.json`.
- Shipped: `SubjectPoint`, `SubjectMetricsReader`, `health_for_error_rate`, the aggregates worker handler, `AggregateDoc`.

### Interfaces provided
- Core: `SubjectKind` adds `tool` and `service`; `subject_series_key("tool"|"service", canonical_id)`; `SubjectPoint.subject_kind` covers the four kinds; reader accepts them.
- Worker: `neurosphere_workers.ingestion.resolve_subjects` (new): `canonical_tool_id(event)`, `canonical_service_id(event)` pure functions (return `None` when no valid id).
- Aggregate documents `metric: "subject"`, `subject_kind: "tool" | "service"` in the existing aggregates container (no new container).
- For PRP-74 (last item) and PRP-77: read tool and service points through the existing `SubjectMetricsReader`; PRP-74 keeps its `derive_health` only as the fallback when a node has no point.

### Patterns to match
- Subject rollup and null rules: `workers/aggregates/rollups.py:197-259`, tests `aggregates/tests/test_nulls_not_zero.py`.
- Attribute helper with caps: `otlp_mapping.py:171-178` `_first_text`.
- Canonical ownership check: `projections/catalog/mapping.py:110-114`.

### Gotchas
- The new kinds change `AggregateDoc` shape (`subject_kind` Literal at `aggregates/models.py:277`). Readers regenerate before writers emit: the aggregates worker and the API image both import `neurosphere_core`, so ship core and worker in one PR.
- Tool and service ids must never include a URL, a path with query, or a host credential: the resolver accepts only the capped identifier alphabet and drops the rest.
- Subject documents per (domain, grain, bucket) are capped; many dynamic tool names (one per call argument) can flood the cap. The name is the registered tool name, never a span name; spans whose tool name fails the pattern are not counted.
- `external_agent_id` is not resolved until PRP-137 merges (Why). Do not let agent-less tool spans create an agent series, and do not resolve agents here (PRP-137, W19, owns it).
- UNVERIFIED: the OTel attribute names (item 1), and the F1 generated names (item 2).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - packages/core/neurosphere_core/aggregates/**
  - services/workers/neurosphere_workers/aggregates/**
  - services/workers/neurosphere_workers/ingestion/resolve_subjects.py
  - packages/core/tests/aggregates_subjects/**
  - services/api/tests/ingest_tool_service/**
  - tests/integration/tool_service_subjects/**
  - services/api/neurosphere_api/realtime/source.py
  - services/api/neurosphere_api/ingest/service.py
  - docs/connectors/verification/otel-genai-tool-service.md
  - mkdocs.yml
  - docs/connectors/verification/otel-genai-tool-service.md
tier1: []
tier2_appends: []
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/map/**
  - services/workers/neurosphere_workers/ingestion/pipeline.py
```

## Implementation blueprint

### Item 1 - Verify-first: OpenTelemetry attribute names  [P]
Deliverable: `docs/connectors/verification/otel-genai-tool-service.md`: URL, retrieval date, the attribute names for tool name, service name and instance, MCP server, their stability level, and which this PRP reads; what is not found stays uncoded.
Owned files: that file. Must NOT touch: code. Depends on: none.
Acceptance criteria: file lists every attribute item 3 will read with its source URL; any attribute not found is listed as "not read".
Tests: none (documentation); validator `python scripts/validate_planning.py` unaffected.
Pattern references: `docs/connectors/coverage.md`.

### Item 2 - Core subject kinds and resolver
Deliverable: `SubjectKind`, key function and `SubjectPoint` extended; `resolve_subjects.py` with the two pure functions; read the generated F1 bindings first and use their real names.
Owned files: `packages/core/neurosphere_core/aggregates/**`, `services/workers/neurosphere_workers/ingestion/resolve_subjects.py`, `packages/core/tests/aggregates_subjects/**`, `services/api/neurosphere_api/realtime/source.py` (guard only), resolver test `services/workers/neurosphere_workers/aggregates/tests/test_resolve_subjects.py` (new; core tests cannot import the worker package).
Must NOT touch: contracts, `ingestion/pipeline.py`. Depends on: PRP-70 merged.
Acceptance criteria: key and resolver criteria; agent and model keys unchanged; `cosmos.py` query accepts the new kinds. Realtime guard (decided 2026-11-23): `newest_subject_points` keeps returning agent and model points only, and `realtime/source.py` skips any other kind, because `DeltaNode.kind` has no `tool` or `service`; the live delta stays byte-identical until PRP-74/77 add those node kinds.
Tests: `packages/core/tests/aggregates_subjects/test_tool_service_keys.py`, `.../test_resolver.py` (new); existing suites in that directory unchanged.
Pattern references: `aggregates/subject.py:48-58`.

### Item 3 - OTLP mapping  [P]
Deliverable: `map_span` reads the verified tool, service and MCP attributes into the F1 fields, with caps and counted drops; metric points are untouched.
Owned files: `services/api/neurosphere_api/ingest/otlp_mapping.py`, `services/api/tests/ingest_tool_service/**`, `services/api/neurosphere_api/ingest/service.py` (decided 2026-11-23: two call-site changes only, pass the resource into `map_span` through a new optional keyword and merge its attribute drop counts into the existing `IngestResult.dropped_fields`; no route-model change).
Must NOT touch: `payload/guard.py`, `ingest/reasons.py`. Attribute names come from `docs/connectors/verification/otel-genai-tool-service.md`. Depends on: items 1 and 2 (names); PRP-70.
Acceptance criteria: mapping criteria; negative body-field test.
Tests: `services/api/tests/ingest_tool_service/test_otlp_tool_service.py` (new directory name is unique); existing `services/api/tests/ingest` unchanged.
Pattern references: `otlp_mapping.py:245-280`.

### Item 4 - Aggregates mapping and rollups
Deliverable: `EventFact` gains optional tool and service ids; `contribution_from_event` returns contributions for `tool_call` and service-bearing spans (not only `model_call`) without changing agent and model contributions; rollups emit tool and service points.
Owned files: `services/workers/neurosphere_workers/aggregates/**`.
Must NOT touch: ledger and cost paths. Depends on: item 2.
Acceptance criteria: tool, service, null-not-zero, unchanged agent and model criteria; idempotent re-run (existing idempotency test).
Tests: `services/workers/neurosphere_workers/aggregates/tests/test_tool_service_rollups.py` (new).
Pattern references: `rollups.py:197-259`.

### Item 5 - End-to-end check on the seeded incident
Deliverable: an integration test that aggregates the PRP-71 seeded telemetry (stored `TelemetryEvent` documents, which already carry F1 identity) in memory and asserts the failing service and a failing tool point, reading ids from `incident-manifest.json`; the failing tool is the one whose seeded spans call the outage service (the manifest names no tool). The OTLP leg is covered by item 3's tests.
Owned files: `tests/integration/tool_service_subjects/**` (new directory; decided 2026-11-23 because every module in `tests/integration/ingestion/` starts the compose emulators through an autouse fixture and the python CI job deselects them).
Must NOT touch: sandbox generator (PRP-71). Depends on: items 3, 4; PRP-71.
Acceptance criteria: incident criterion. Tests: itself (runs under the python job with in-memory stores).
Pattern references: `tests/integration/ingestion/support.py` (style only; never import that package's conftest).

### Item 6 - Integration and close-out
Deliverable: Tier-3 regeneration if needed (`openapi.json` only on route-model change), changelog fragment `changelog.d/PRP-100-telemetry-tool-service-identity-and-aggregates.md`, completion note, a hand-off line for PRP-74's last item.
Owned files: fragment only. Depends on: items 1-5.
Acceptance criteria: reference section 6 satisfied. Tests: the gate commands.

## Validation gates
```bash
uv run pytest -q packages/core/tests/aggregates_subjects services/workers/neurosphere_workers/aggregates services/api/tests/ingest services/api/tests/ingest_tool_service tests/integration/tool_service_subjects
uv run ruff check packages services tests
uv run pyright
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
No schema migration: aggregate documents are additive (`subject_kind` gains two values; old readers that pin the two-value Literal would reject a new document, so the API image ships in the same release). Roll back by reverting the PR; tool and service points already written age out with the hot window. The new mapping fields stay null when attributes are absent.

## Live and open gates
None. The real-stack run with seeded data belongs to PRP-109 and the hosted run to PRP-64. No paid or cloud call.

## NOT building
- Resolution of `external_agent_id` to a canonical agent id (PRP-137, W19).
- A tool or service catalog entity creation from telemetry (PRP-74 reads the graph; observed-entity creation is not part of the design).
- Per-edge traffic volume, cost per tool, alerting on these series (PRP-132).
- Any content, argument or result of a tool call: only the registered name and ids travel.

## Definition of Ready check
- [x] Goal, Why and acceptance criteria are specific and testable.
- [x] Every referenced path was verified in the worktree; created files are marked (new) or listed under owns.
- [x] Dependencies (PRP-70 with F1, PRP-71) are named; the F1 names are marked UNVERIFIED until PRP-70 merges.
- [x] Ownership block present and disjoint from PRP-74 (`map/**`) in W22.

## Execution state
| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 Verify-first attribute names | merged | prp-100-telemetry-tool-service-identity | orchestrator (implementers have no web fetch); GenAI conventions moved to `semantic-conventions-genai` (ae8214a8f3a9), core registry aef58d05090b; nav line added to `mkdocs.yml` (tests/docs/test_nav_allowlist requires built == nav); tests/docs 129 passed; 2026-11-23 |
| 2 Core kinds and resolver | merged | prp-100-item-2-core-kinds | sonnet; commit 778ced71, merged bccce30f; orchestrator verify PASS 2026-11-23 (aggregates_subjects + workers aggregates + api realtime + api map 164 passed, ruff clean, pyright repo-wide 0 errors); review at PR level; realtime guard in `pick_newest` (covers cosmos) |
| 3 OTLP mapping | merged | prp-100-item-3-otlp-mapping | sonnet; commit 1c3b467d, merged ab854ebc; orchestrator verify PASS 2026-11-23 (api ingest + ingest_tool_service + realtime 132 passed, ruff + format clean, pyright services/api 0 errors); F1 events stamped schema 1.1.0, others stay 1.0.0; pre-existing: root `execute_tool` span (no parent) is model-valid but schema-invalid (follow-up) |
| 4 Aggregates mapping and rollups | merged | prp-100-item-4-aggregates | sonnet; stopped once: `EventFact` lives in core `aggregates/models.py` (PRP-owned), granted that class; commit 506de67c, merged d67d1ba9; orchestrator verify PASS 2026-11-23 (workers aggregates + core aggregates_subjects + agent_identity_worker + api realtime + api map + sandbox incident 243 passed, ruff clean, pyright 0 errors); `model_call` guard on domain latency/error and agent/model keys; tool/service points carry no tokens |
| 5 End-to-end seeded incident check | merged | prp-100-item-5-seeded-incident | sonnet; commit 6e0d5155, merged e77b0735; real `AggregateProjection` over in-memory stores, ids from the read-back manifest; measured outage service error_rate 0.8596 (failing), failing tool `payment-initiation` 0.8333, 6 other services ok; orchestrator verify PASS 2026-11-23 (item 5 + workers aggregates + sandbox incident + CI shard pin + tests/docs 212 passed, ruff + format clean) |
| 6 Integration and close-out | merged | prp-100-telemetry-tool-service-identity | orchestrator; PR 391 CI green, merged ffa2d7e3 2026-11-23; changelog fragment; no route model changed, so no `openapi.json` regeneration; PR-level review APPROVED 2026-11-23 (no blockers; 4 non-blocking findings to follow-up issues); Snyk Code 0 issues on ingest, realtime, core aggregates, worker aggregates and ingestion; verify-gates full 2026-11-23: typecheck PASS, tests PASS (16363 passed, 364 deselected), build PASS, lint FAIL only on 41 errors inside untracked stale `.claude/worktrees/wf_73a5d379-*` copies (ruff over all tracked trees: all checks passed) |

## Completion note (filled at ship)
- Date, PR: 2026-11-23, PR 391, merge commit ffa2d7e3 (integration branch `prp-100-telemetry-tool-service-identity`; item merges bccce30f, ab854ebc, d67d1ba9, e77b0735). CI green on every required check; one independent PR-level review, APPROVED with no blockers.
- Deviations: item 1 added one nav line to `mkdocs.yml` (`tests/docs/test_nav_allowlist` requires built pages == nav); item 4 was granted the core `EventFact` class in `packages/core/neurosphere_core/aggregates/models.py` (outside its declared files; stopped once and approved); the OpenTelemetry GenAI conventions now live in `semantic-conventions-genai` (ae8214a8f3a9), core registry pinned at aef58d05090b. No route model changed, so `services/api/openapi.json` was not regenerated. Local verify-gates lint FAIL was confined to untracked stale `.claude/worktrees/wf_73a5d379-*` copies; ruff over tracked trees passed.
- Descoped items: none.
- OPEN gates: none in scope (real-stack seeded run belongs to PRP-109, hosted run to PRP-64). Measured in-memory: outage service error_rate 0.8596, failing tool `payment-initiation` 0.8333, six other services ok.
- Env vars for the operator: none.
- Follow-up issues: #392 (service series volume and shared subject cap), #393 (align edge and resolver id alphabets, document drop keys), #394 (root `execute_tool` span is model-valid but schema-invalid, pre-existing).
