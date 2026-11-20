---
name: PRP-72-agent-and-tool-recommender-backend
status: active
started: 2026-11-20
priority: P0
order: 62
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-03, NS-02
depends_on: [PRP-70-contracts-revision-restored-scope]
wave: W20
branch: prp-72-agent-tool-recommender
allow_parallel: true
issues: []
---

# PRP-72: Agent and tool recommender (matcher, API, feedback)

## Goal
Ship the capability the owner asked for in the original product definition and never got: give the platform a task description or workflow context and get back a ranked list of candidate agents (and tools) with a 0-1 score, a confidence value and an explanation that names the graph relationships and telemetry signals behind each rank. An operator can accept or reject a candidate and that feedback moves later rankings by a bounded, visible amount. It is a transparent weighted-signal model, not a trained one: capability/tag match, lexical relevance from the existing search port, historical success/latency/usage from the per-agent aggregates, graph proximity to the caller's domain or named data assets, and a feedback prior. Every signal's contribution is returned. It is for the operations lead ("which agent should handle summarize this support ticket?") and the platform engineer ("why was this agent suggested?"), and it is the backend that PRP-75 (page), PRP-78 (copilot `recommend_agent` tool) and the acceptance-rate metric build on. It runs in W20 on top of PRP-70, which provides the match and feedback contract types and the agent tags and capabilities.

Out of scope: the "Find an agent" page and the acceptance-rate tile (PRP-75); the copilot and MCP `recommend_agent` tool and its audit (PRP-78); seeding realistic tagged agents and descriptions (PRP-71); the Azure AI Search fixes and any vector or semantic ranking (PRP-60 and a later PRP); tag and capability entry in the registration form (PRP-76); the six existing detectors and their review flow (shipped, untouched); live latency on Azure AI Search (PRP-64).

## Why
- Original PRD 5c, `git show 9fbf5f4c:docs/PRD.md` lines 59-69. Story: "As an operations lead, I want the system to suggest which agent to invoke for 'summarize this support ticket.'" and "As a platform engineer, I want recommendations ranked with an explanation (why this agent was suggested)." Acceptance criteria restored here: "Returns ranked list of candidate agents with confidence score and explanation referencing graph relationships/telemetry signals.", "Supports feedback loop (accept/reject) that retrains/adjusts ranking.", "p95 recommendation latency < 1s for catalogs up to 10k agents." Success metric (line 17): "Recommendation acceptance rate (operator picks suggested agent/tool) > 60%".
- v1.2 demoted it: `docs/PRD.md:21` "Agent/tool selection is an optional secondary recommendation capability, not the product's primary purpose." The owner decision of 2026-11-16 restores it; it stays a recommendation, never an action (no agent is invoked or changed by it).
- Nothing matches a task to an agent today: `packages/core/neurosphere_core/recommendations/` is only a store (`store.py`, `cosmos_store.py`), the kind enum is the six detector kinds, and the list is ordered by id (gap analysis 5c; `cosmos_store.py:203`). The only user action is "Route to review", which changes nothing in later generation.
- The pieces exist: `AuthorizedSearch` (`search/protocol.py:83-87`) is scope-first and lexical BM25 only; per-agent aggregates are a `SubjectMetricsReader` with `latest_subject_points` over `agent:<id>` keys (`aggregates/subject.py:93-108`), error rate unknown stays `None`; `GraphQuery.neighbors` is bounded by a `Budget` (`catalog/protocol.py:422-432`); `SignalBreakdown` and `SimilaritySignalProvider` show the per-signal explanation pattern (`services/workers/neurosphere_workers/recommendations/duplicates/models.py`).
- Agents have no tags or capabilities field today (`agent.schema.json` properties end at `current_version_id`); the fixture indexer already reads a `tags` key (`search/fixture/index.py:_TEXT_KEYS`) that no entity carries. PRP-70 adds the field; this PRP consumes it.
- No latency evidence exists for matching: the nearest harness is `tests/load/catalog_latency` on 200 in-memory agents and is explicitly not a claim. The fixture BM25 is a linear scan, so 10k agents is a real risk to the 1 s target and is measured here.

## Acceptance criteria
- [ ] Given a task text and an analyst whose scope covers two domains with tagged agents, When they `POST /api/v1/recommendations/domains/{domain}/match`, Then the response lists at most `limit` candidates best first, each with `score` in 0-1 (relative, not a probability) and `signals` (PRP-70 `AgentMatchSignal`: `signal`, `value` or null when unobserved, `weight`, `contribution`, `detail_code`) whose contributions sum to the score; `confidence` is an API-local wrapper field (PRP-70 has none).
- [ ] Given an agent in a domain outside the caller's scope that matches the text perfectly, Then it is absent from candidates, from `matched` counts and from every explanation (scope is applied before ranking; out-of-scope documents never influence scores).
- [ ] Given a candidate with no aggregate points (cold start), Then the telemetry signals are marked unobserved, their weight is redistributed over observed signals, the candidate is flagged `cold_start`, and its confidence is capped below the confidence of an otherwise equal candidate with observed telemetry. Unknown error rate is never treated as 0.
- [ ] Given context entity ids (a domain node or named data assets) in the request, Then candidates within graph distance 2 of any of them get a proximity signal with the relationship path in the explanation (edge type and hop count); ids outside scope are refused with the standard error, not silently ignored.
- [ ] Given a caller's `accepted` or `rejected` decision (PRP-70 `AgentMatchFeedbackRequest`) for a candidate of a match they received, When posted to `.../match/feedback`, Then it is stored once per (principal, match, candidate), a later change replaces it, a feedback for a match or candidate the caller was not shown is refused, and a repeat of the same task text ranks the accepted candidate higher and the rejected one lower by at most the configured bound (default 0.15 of score), with the feedback contribution shown in the explanation.
- [ ] Given fewer than 3 distinct principals' feedback for a candidate, Then the feedback prior is 0 and reported as insufficient evidence; one principal cannot move a ranking alone.
- [ ] Given `GET .../match/metrics`, Then it returns counts of matches, matches with feedback, accepts and rejects and the acceptance rate for a window; the rate is `null` (not 0) when there is no feedback.
- [ ] Given a 10k-agent catalog in the in-memory repository, Then `tests/load/agent_match` measures p50/p95/max of `match` for a fixed task set and writes the numbers to `temp/agent_match/p95.json` labelled with the backend; the completion note reports the measured p95 against the 1 s target as MET or NOT MET and, if NOT MET, the changes tried. The bound on candidate pool size is configurable and the response sets `partial` with a reason when a budget stopped the work.
- [ ] No task text, prompt body or per-principal identifier is stored in clear: stored match and feedback documents hold normalized tokens (at most 32), the principal pseudonym, ids, decision and timestamps, with a TTL; no value of those fields appears in logs.
- [ ] Callers without `data.read` on the addressed domain get 403 with a denial record; feedback needs the same permission; the new routes are in the route inventories and boot under `verify_route_permissions`.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model type | Trained ranker; transparent weighted signals | Transparent weighted signals with a bounded feedback prior (gap analysis section 5 item 10: a trained model without usage history would be fabricated confidence). "Retrains" in the original criterion is restated as "adjusts ranking". |
| 2 | Embeddings | In scope now; later | ASSUMPTION: later. The search port has no vector support; `SimilaritySignalProvider` (duplicates slot) is the documented seam for a future embedding signal. Not built here. |
| 3 | What "confidence" means | Same as score; separate | Separate and honest: derived from score, the share of weight that was observed, and the margin to the next candidate; never presented as a probability (explanation text says so). |
| 4 | Candidate pool | Addressed domain only; every in-scope domain | ASSUMPTION: every domain in the caller's scope, with no request-side narrowing field (PRP-70 `AgentMatchRequest` has no scope-shaped field and `AgentMatchResponse` carries one `domain_id`); the path domain is the authorization target and the "home domain" for proximity. Telemetry is read per domain (aggregate reads are one customer and domain each), capped at 20 domains per call with `partial` set beyond. |
| 5 | Tools as candidates | Agents only; agents and tools | Both, selected by a request `candidate_types` field (`agent`, `tool`; PRP-70 `AgentMatchRequest`). ASSUMPTION: tools have no subject aggregates, so their telemetry signals are unobserved and flagged. |
| 6 | Feedback anti-gaming | Count raw votes; per-principal and minimum evidence | Per-principal, one decision per (match, candidate), at least 3 distinct principals before any adjustment, adjustment bounded. |
| 7 | Task text retention | Store text; store tokens | Tokens only (normalized, stop-words removed, at most 32), TTL 180 days (ASSUMPTION), so feedback can apply to similar future tasks (token Jaccard at least 0.5) without keeping free text. |
| 8 | Weights | Hard-coded; settings | Defaults in code, overridable by `NS_MATCH_WEIGHTS` style settings (names in "Interfaces provided"); the returned explanation always carries the weights used. Defaults are a starting point, not tuned values (reported as such). |
| 9 | Copilot / MCP tool | Here; PRP-78 | PRP-78. This PRP exposes the `AgentMatcher` on `app.state.agent_matcher` and a pure service class the tool calls. |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/search/protocol.py` - `AuthorizedSearch`, `SearchRequest` (budget mandatory), `SearchFilters.entities`.
- `packages/core/neurosphere_core/search/fixture/index.py` - BM25 fixture, `_TEXT_KEYS`, linear scan; where 10k latency will show.
- `services/api/neurosphere_api/runtime/builders/search.py` - how the index is composed and refreshed per scope; `SearchRuntime`.
- `packages/core/neurosphere_core/aggregates/subject.py` and `aggregates/models.py:268-288` - `SubjectMetricsReader`, `SubjectPoint` (`p95_ms`, `error_rate`, `event_count`), key limits.
- `packages/core/neurosphere_core/catalog/protocol.py:412-444` and `catalog/graph/query.py:127-215` - `GraphQuery`, `NeighborsRequest`, bounded walk.
- `services/workers/neurosphere_workers/recommendations/duplicates/models.py` - `SignalBreakdown` explanation shape to imitate.
- `services/api/neurosphere_api/recommendations/router.py`, `dependencies.py`, `models.py`, `review.py` - route style, path-domain authorization, audited write.
- `packages/core/neurosphere_core/recommendations/cosmos_store.py` and `stores/containers.py:125-150` - Cosmos store and container spec pattern (copilot_conversations shows `default_ttl=TTL_PER_ITEM`).
- `services/api/neurosphere_api/runtime/builders/data.py:359-366` - `_recommendations` builder; `data.py:643` attempt order.
- `tests/load/catalog_latency/harness.py` - world loader, scope builder and percentile helper; `sandbox/config.py:192-222` for the agent-count override.
- PRP-70 "Interfaces provided" - match request/response, feedback and tags/capabilities.

### Interfaces consumed
- PRP-70 "Interfaces provided" (exact names): `tags`, `capabilities`, `environment` on `Agent` and `Tool`; `AgentMatchRequest` (`task_text`, `candidate_types`, `required_capabilities`, `preferred_tags`, `context_entity_ids`, `environment`, `limit`, `max_graph_depth`); `AgentMatchResponse` (`match_id`, `domain_id`, `ranker`, `cold_start`, `signals_unavailable`, `candidates`, `truncated`, `partial_reason`) with `AgentMatchCandidate` and `AgentMatchSignal`; `AgentMatchFeedbackRequest` (`match_id`, `entity_id`, `decision` accepted|rejected, `reason_code`); stored `AgentMatchFeedback` (`task_digest`, `rank_at_decision`, `score_at_decision`, `expires_at`). PRP-70 provides NO per-candidate `confidence`, NO metrics response and NO `domain_ids`; this PRP defines `confidence` and the metrics response as API-local models in `match_models.py` (not contracts) and has no request-side domain filter.
- Shipped: `AuthorizedSearch`; `SubjectMetricsReader` (PRP-49); `GraphQuery` and `RepositoryGraphQuery`; `CatalogRepository.get_entity`; `IdentityScope` and `Permission.DATA_READ`; `run_audited_mutation`; `Budget` contract; `ContainerSpec` registry.
- PRP-71 (soft): tagged, described seed agents so the local demo returns useful candidates; tests here use their own fixtures.

### Interfaces provided
- Core package `neurosphere_core.recommendations.matching` (new): `AgentMatcher.match(scope, domain, request: AgentMatchRequest) -> AgentMatchResponse` (PRP-70 contract type), `FeedbackStore` protocol with `InMemoryFeedbackStore` and `CosmosFeedbackStore`, `MatchSettings` (weights, candidate cap, feedback bound, min principals, TTL), signal functions `tag_signal`, `lexical_signal`, `telemetry_signal`, `proximity_signal`, `feedback_signal`, and `combine` (renormalizes over observed signals).
- Port for consumers (PRP-78 names it `AgentMatchReader`): `neurosphere_core.recommendations.matching.AgentMatchReader`, a `Protocol` with `async match(scope, domain, request: AgentMatchRequest) -> AgentMatchResponse`, satisfied structurally by `AgentMatcher`; consumers read it from `app.state.agent_matcher`.
- Routes under `/api/v1/recommendations/domains/{domain}`: `POST /match` (200), `POST /match/feedback` (202), `GET /match/metrics`. Permission `data.read`.
- Container `recommendation_feedback` (partition `/customer_id`, `/domain_id`, per-item TTL) holding documents of kind `match` and `feedback`; owner `neurosphere_core.recommendations.matching.cosmos_store`.
- `app.state.agent_matcher` and `app.state.recommendation_feedback_store`; component `agent_matcher` (optional) in `runtime/status.py`.
- Settings `NS_MATCH_CANDIDATE_CAP` (default 200), `NS_MATCH_FEEDBACK_BOUND` (0.15), `NS_MATCH_MIN_PRINCIPALS` (3), `NS_MATCH_FEEDBACK_TTL_DAYS` (180), `NS_MATCH_WEIGHTS` (JSON of signal weights).
- Load harness `tests/load/agent_match` and its result file `temp/agent_match/p95.json`.

### Patterns to match
- Path-domain authorization and 503 on unset dependency: `services/api/neurosphere_api/recommendations/router.py` and `dependencies.py:21-28`.
- Explanation as a frozen Pydantic model of named parts: `duplicates/models.py` `SignalBreakdown`.
- Scope-then-rank, tie-break by canonical id: `search/fixture/index.py` module docstring.
- In-memory twin plus Cosmos store sharing one test file: `packages/core/neurosphere_core/recommendations/tests/` and `aggregates/cosmos.py`.
- Measured-not-asserted latency run with a labelled result file: `tests/load/catalog_latency/test_catalog_p95.py`.

### Gotchas
- Aggregate reads are one customer and one domain each and capped (`MAX_SUBJECT_KEYS_PER_READ`=2000, 100 keys per Cosmos `IN`); group candidates by domain and batch, never read per candidate.
- `AuthorizedSearch` needs a mandatory `Budget`; build one from the matcher's time and result limits and surface `truncated` and `partial_reason` (`limit` or `timeout_ms`) from the `SearchResult`.
- Search covers entities that carry `domain_id`; tools without one are not searchable (indexer skips them). Say so in the response `signals_unavailable` list and `partial_reason` rather than hiding it.
- The Azure search provider has known defects (colon keys, worker writes not indexed) fixed by PRP-60; develop against the fixture provider and do not claim Azure latency.
- Adding `agent_matcher` as an optional component changes `/readyz` composition output: update `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py` and `runtime_data/data_helpers.py` where they pin component sets or `default_builders` order.
- The feedback container is new: `infra/compose/cosmos-containers.json` and `infra/demo/modules/cosmos-data.bicep` are generated or checked against `stores/containers.py` by existing tests; edit all three together.
- New test directory names must be unique (`packages/core/tests/agent_match`, `services/api/tests/agent_match_api`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/recommendations/matching/**
  - packages/core/tests/agent_match/**
  - services/api/neurosphere_api/recommendations/match.py
  - services/api/neurosphere_api/recommendations/match_models.py
  - services/api/neurosphere_api/recommendations/match_dependencies.py
  - services/api/tests/agent_match_api/**
  - tests/load/agent_match_latency/**
  - tests/security/authz/test_agent_match*.py
  - docs/runbooks/agent-match.md
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
  - services/api/neurosphere_api/runtime/builders/data.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/recommendations/store.py
  - packages/core/neurosphere_core/recommendations/cosmos_store.py
  - packages/core/neurosphere_core/search/**
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/neurosphere_core/catalog/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/mcp/**
  - services/api/neurosphere_api/copilot/**
  - services/api/neurosphere_api/recommendations/router.py
  - frontend/**
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (signals and feedback store share no file). Item 3 needs both; item 4 needs 3; item 5 [P] with item 4 after item 3's service exists; item 6 last.

### Item 1 - Signals and combiner  [P]
- Deliverable: `matching/signals.py` and `matching/combine.py`: tag and capability match (normalized tokens, exact tag equals 1, token overlap fraction otherwise); lexical relevance from `AuthorizedSearch` scores normalized to 0-1 by the top hit; telemetry signal from `SubjectPoint` (success = 1 minus error rate, latency score from `p95_ms` against the candidate pool median, usage from `event_count` log-scaled; each part `None` when unknown); graph proximity from bounded `neighbors` walks started at the context entities (one walk per context id, results cached per call, hop count and edge type kept); `combine` renormalizes weights over observed signals, returns per-signal contribution, `cold_start`, and confidence per clarification 3.
- Owned files: `packages/core/neurosphere_core/recommendations/matching/{__init__,models,settings,signals,combine}.py`, `packages/core/tests/agent_match/test_signals.py`, `test_combine.py`.
- Must NOT touch: `search/**`, `aggregates/**`, `catalog/**`.
- Depends on: PRP-70 merged.
- Acceptance criteria: contributions sum to the score within 1e-9; unobserved signals carry weight 0 in the sum and are listed; score is monotonic in each observed signal with others fixed; ties break by canonical id ascending; unknown error rate never contributes as 0.
- Tests: `packages/core/tests/agent_match/test_signals.py`, `test_combine.py` (including a hypothesis-style monotonic check on fixed inputs).
- Pattern references: `duplicates/models.py` `SignalBreakdown`, `search/fixture/index.py`.

### Item 2 - Feedback store and prior  [P]
- Deliverable: `matching/feedback.py` (`FeedbackStore` protocol, `InMemoryFeedbackStore`, `feedback_signal` that returns a bounded prior from smoothed per-agent accept share over similar-task feedback weighted at most 3 distinct principals' worth per agent, 0 below `NS_MATCH_MIN_PRINCIPALS`), `matching/cosmos_store.py` (`CosmosFeedbackStore`, documents of kind `match` and `feedback` with per-item TTL), metrics aggregation (`window` counts and acceptance rate, `None` when no feedback). Add `recommendation_feedback` to `stores/containers.py`, `infra/compose/cosmos-containers.json` and `infra/demo/modules/cosmos-data.bicep`.
- Owned files: `matching/feedback.py`, `matching/cosmos_store.py`, `packages/core/tests/agent_match/test_feedback.py`, `test_feedback_cosmos.py`, the three Tier-1 store files.
- Must NOT touch: the existing recommendation store modules.
- Depends on: PRP-70 merged.
- Acceptance criteria: one decision per (principal, match, candidate) with replace; feedback for an unknown match or a candidate not in that match is refused; stored documents hold tokens, pseudonym, ids, decision, timestamps and `ttl` only; the prior never exceeds the bound in either direction; with fewer than the minimum principals the prior is 0.
- Tests: `packages/core/tests/agent_match/test_feedback.py`, `test_feedback_cosmos.py` (emulator marker like `recommendations/tests`), plus the container-registry tests that compare `containers.py` with the JSON and Bicep.
- Pattern references: `neurosphere_core/recommendations/cosmos_store.py`, `stores/containers.py:130-136`.

### Item 3 - `AgentMatcher` service
- Deliverable: `matching/service.py`: `AgentMatcher.match` runs candidate generation (search over `candidate_types` with the scope's domains, plus tag-match candidates found through the same search request over `tags` tokens, union capped at `NS_MATCH_CANDIDATE_CAP`), re-fetches each candidate with the caller's scope, batches telemetry per domain, runs proximity walks, applies feedback, ranks, writes the `match` document (tokens and candidate ids) and returns a PRP-70 `AgentMatchResponse`; a total time budget sets `partial` with a reason code. `record_feedback` and `metrics` use the store.
- Owned files: `matching/service.py`, `packages/core/tests/agent_match/test_service.py`.
- Must NOT touch: signals and feedback modules except through their public functions.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 1-7 at service level with in-memory twins; an out-of-scope agent never appears or influences `matched`; context ids outside scope raise the scope error; a reader failure degrades the telemetry signals to unobserved with a reason code rather than failing the call; the call performs a bounded number of backend calls (asserted with counting fakes: at most 1 search, 1 aggregate read per domain, at most 1 neighbors walk per context id).
- Tests: `packages/core/tests/agent_match/test_service.py`, `test_scope_isolation.py`.
- Pattern references: `catalog/graph/query.py` budget handling, `map/service.py:235-278` bounded subject loading.

### Item 4 - API routes and composition
- Deliverable: `recommendations/match.py` (router with the three routes, path-domain authorization, `data.read`, feedback recorded through `run_audited_mutation` like the review-request route), `match_models.py` (request and response re-exports of PRP-70 contracts plus API-only wrappers), `match_dependencies.py`; the `_agent_matcher` step in `runtime/builders/data.py` (reuses the composed search, catalog graph, aggregate reader and the feedback store; reports `agent_matcher` disabled with a reason code when search or the catalog is unavailable) and `app.state` keys; `routers.py` hook line.
- Owned files: `services/api/neurosphere_api/recommendations/match*.py`, `services/api/tests/agent_match_api/**`, `runtime/builders/data.py` (Tier-1, additive step only).
- Must NOT touch: `recommendations/router.py`, other builders.
- Depends on: item 3.
- Acceptance criteria: criteria 1, 4, 5, 7 and 10 over HTTP; 422 on a task longer than the contract bound or more than the allowed context ids; 503 `recommendations_unconfigured`-style code when the matcher is not composed; with search not composed the route answers `capability_unavailable` and `/readyz` shows the reason; existing `runtime_api`, `runtime_routes`, `runtime_data` and `recommendations` suites pass after updating the pinned component sets.
- Tests: `services/api/tests/agent_match_api/test_match_routes.py`, `test_feedback_routes.py`, `test_matcher_builder.py`.
- Pattern references: `recommendations/router.py`, `runtime/builders/data.py:359-366`.

### Item 5 - Authorization suite and 10k-agent latency profile  [P]
- Deliverable: ABAC cases for each route (no role, viewer without the domain, wrong domain, other customer, other cloud, expired scope) with denial records; a leak test that greps logs and stored documents for task text; `tests/load/agent_match/` with a 10k-agent in-memory run (reuse `catalog_latency.harness` helpers; sandbox `custom` profile with `agents=10000`, tagged and described by a local helper because seed agents have no text), fixed task set, p50/p95/max recorded to `temp/agent_match/p95.json`, labelled in-memory and not a live claim.
- Owned files: `tests/security/authz/test_agent_match*.py`, `tests/load/agent_match/**`.
- Must NOT touch: `tests/load/catalog_latency/**` (import from it only).
- Depends on: item 4.
- Acceptance criteria: every route has a deny case per dimension; the load test records its result and fails only on correctness (in-scope results, non-empty ranking), never on a latency threshold; the measured p95 is printed.
- Tests: `tests/security/authz`, `tests/load/agent_match`.
- Pattern references: `tests/load/catalog_latency/test_catalog_p95.py`, PRP-41 `test_admin_producers.py`.

### Item 6 - Integration and close-out
- Deliverable: Tier-2 appends and route inventories; `docs/runbooks/agent-match.md` (signals, weights, cold start, feedback rules, settings, what is not claimed); regenerate Tier 3 (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`); changelog fragment under `changelog.d/`; completion note with the measured 10k p95 and the product check (type a task on the local stack, read the explanation).
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/agent_match packages/core/neurosphere_core/recommendations services/api/tests/agent_match_api services/api/neurosphere_api/recommendations/tests services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/authz tests/security/authz tests/load/agent_match_latency services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local check (not CI): `docker compose up -d --wait`, post a task to the match route with a seeded scope, read the explanation, post feedback from three principals and re-run.

## Migration and rollback
One new container (`recommendation_feedback`); it is created on demand under `NS_ENV=local` and by the Bicep module in hosted environments. No existing data changes. Rollback: the matcher is an optional component, so a missing search or catalog disables it with a reason code; reverting the PR leaves an inert empty container. Stored documents expire by TTL.

## Live and open gates
No live call is made. Open: latency on Azure AI Search with 10k agents (after PRP-60; operator-gated, handed to PRP-64), the 60 percent acceptance-rate outcome (an adoption metric, instrumented here and displayed by PRP-75, not claimable), and any embedding signal.

## NOT building
Trained or LLM-based ranking; embeddings or a vector index; automatic invocation of the chosen agent; the page (PRP-75); copilot and MCP tool wiring (PRP-78); registration-form tag entry (PRP-76); cross-customer or cross-cloud matching; storing free-text tasks.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 2, 4, 5 and 7 accepted by the owner at plan approval 2026-11-20; PRP-70 names are taken from its "Interfaces provided")

## Execution state
Plan deltas approved by the owner 2026-11-20: (a) item 4 also makes the Tier-2 route-registration appends (`routers.py`, `authz/routes.py`, `runtime/status.py`, `tests/authz/test_route_inventory.py`, `test_startup_route_check.py`, `runtime_routes/manifest_calls.py`, `tests/integration/real_stack/test_manifest_routes.py`) because its routes cannot boot under `verify_route_permissions` without them; item 6 keeps `mkdocs.yml`, the runbook and Tier 3. (b) item 5 runs after item 4, not in parallel.

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-a64d4cddf1640f4ed | sonnet; ruff/format/pyright clean, 20 passed; commit cc9bcbaf, merge c1b9a43b; 2026-11-20 |
| 2 | merged | worktree-agent-a9a6f931a1c4de93f | sonnet; ruff/format/pyright clean, 94 passed; commit 62e7929e, merge dceaab1e; also edited two pinned container-set tests (stores_registry, hosted_demo drift). OPEN: Cosmos emulator test 3 passed, 2 errors - local emulator refuses create/delete database (PostgresError E58P01), existing stores_cosmos suite fails the same way; CosmosFeedbackStore unverified against the emulator; 2026-11-20 |
| 3 | merged | worktree-agent-ac35667f5d6a86f04 | sonnet; ruff/format/pyright clean, 76 passed (3 emulator tests deselected); commit d6eae127. Deviations: feedback prior is a signed bounded adjustment outside combine (weights.feedback_prior ignored); tools without domain_id are absent with no flag (search never returns them); partial_reason limited by the contract to limit/timeout_ms; 2026-11-20 |
| 4 | merged | worktree-agent-ad2b15243ed2cefcb | sonnet; ruff/format/pyright (repo-wide) clean, 534 passed; commit f90567c9. Deviations: added match_composition.py (SyncedAgentMatcher refreshes the per-scope search index); capability_unavailable is a 409; /readyz shows agent_matcher disabled without a reason (registry only carries reasons on failed), reason is in the 409 body; no authz/routes.py or inventory edits needed (discovered through require); 2026-11-20 |
| 5 | merged | worktree-agent-a5a249bca25ede1fc | sonnet; ruff/format/pyright clean, 28 passed (new authz files, coverage, load test); commit 27460a34, merge ea1bf3d8. 3 routes x 6 deny dimensions, leak test, no production defect. 10k-agent in-memory p95 2012 ms at cap 200 (NOT MET), 539 ms at cap 50; about 98 percent of the time is the in-memory repository's O(n) get_entity on candidate re-fetch; 2026-11-20 |
| 6 | in-progress | prp-72-agent-tool-recommender (orchestrator inline) | docs and Tier 3 started alongside item 5; 2026-11-20 |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can a person use it): type a task on the local stack and read the ranked explanation; the measured 10k-agent p95:
