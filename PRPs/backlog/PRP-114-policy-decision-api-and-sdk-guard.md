---
name: PRP-114-policy-decision-api-and-sdk-guard
status: backlog
priority: P1
order: 114
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-06, NS-08, NS-09
depends_on: [PRP-105-policy-engine-core, PRP-79-agent-sdk-and-telemetry-onboarding, PRP-111-interaction-capture-sources-sdk-and-gateway, PRP-107-notification-channels-and-subscriptions, PRP-110-governance-contracts-b]
wave: W27
branch: prp-114-decide-and-sdk-guard
allow_parallel: true
issues: []
---

# PRP-114: Workload policy decision API and the cooperative SDK guard

## Goal
Let a customer's own agent ask NeuroSphere, before it acts, whether a model call, a tool use or a data-asset access matches a published policy, and get back `allow`, `deny` or `audit` with the matching rule ids and a cache lifetime. Two parts: `POST /api/v1/governance/decide`, authenticated with the agent's registered producer credential (the one PRP-41 issues and PRP-79's SDK already holds), limited to agents registered under that producer's sources, rate limited per producer, and answering from PRP-105's `PolicyDecider` without revealing policy parameters or anything about subjects outside that agent's domain; and `neurosphere_agent.guard` in the agent SDK, which calls it, caches answers, and fails open by default with a counter and an alert (GD-8), fail-closed as an explicit option. The guard is cooperative, not a security boundary: an agent that does not call it is not constrained by it, and nothing in the product, docs or UI may present its answer as enforcement. It is for agent developers who want governance feedback inside their code and for governance teams who want to see which agents ask. It runs in W27 after PRP-105 (decider), PRP-79 (SDK) and PRP-111 (SDK capture, the sub-package ordering).

Out of scope: the decision function itself and its rules (PRP-105); hard enforcement at the gateway (PRP-112), on NeuroSphere's own tool and MCP calls (PRP-113) and on registration (PRP-108); copilot and MCP governance tools (PRP-116); alert rules and incidents built on the fail-open signal (PRP-132); a TypeScript guard.

## Why
- No workload-facing decision path exists: PRP-105 provides an in-process `PolicyDecider.decide(scope, request)` and identity-authenticated routes only (`PRPs/backlog/PRP-105-policy-engine-core.md`, Interfaces provided); a customer agent holds a producer credential, not a NeuroSphere user role.
- Producer credentials are verified by `RegisteredCredentialAuthenticator` (`services/api/neurosphere_api/ingest/auth.py:84-101`, constant-time compare, one 401 body) and producer routes are a separate authorization category, exact-path and POST-only (`services/api/neurosphere_api/authz/routes.py:78-92`); per-producer token buckets exist (`ingest/limits.py:51`). The decision route reuses all three.
- Every catalog agent carries the source it reports through and its domain (`packages/contracts/schemas/catalog/v1/agent.schema.json:43,95`, both required), which bounds what a producer may ask about without a new contract field.
- PRP-99 already fixed the decision request, response and the `enforcement` stored setting (`decision_cache_ttl_seconds`, `sdk_failure_mode` default `fail_open`, `decide_rate_limit_per_minute`) (`PRPs/backlog/PRP-99-governance-contracts-a.md`, Interfaces provided); nothing serves them.
- `docs/PRD.md:31`: "Recheck current resource permission and policy at execution". Owner direction 2026-11-16: the ultimate team AI governance and auditing tool; the design's section 8 item 6 forbids presenting the SDK guard as a security boundary.

## Acceptance criteria
- [ ] Given a producer P whose sources include S and a catalog agent A with `source_id` S in domain D, When P posts a `PolicyDecisionRequest` for A, Then the answer is a `PolicyDecisionResponse` computed by PRP-105's decider over domain D (and customer-wide policies), with `matches` carrying only policy id, version, rule id, rule kind and effect; no rule parameters, display names, document URLs, other subjects or exception details appear in any response or error.
- [ ] Given an agent id from another customer, another cloud, or a source P does not hold, Then the answer is 403 `subject_not_permitted` with the same body for every case (indistinguishable from an unknown agent); a disabled or unknown producer gets 401 with the existing ingest body; a cloud mismatch gets 403 `cloud_mismatch`.
- [ ] Data-asset, tool and MCP server ids in the request that are outside D are ignored for matching and named only by count in `reason_codes` (`subject_out_of_scope`); an unregistered agent of P's customer gets `effect: audit` with `agent_not_registered` and no matches.
- [ ] Requests above `decide_rate_limit_per_minute` per producer get 429 `rate_limited` with `Retry-After`; decisions never consume the producer's ingest rate budget.
- [ ] Each `deny` and each audit-mode would-deny writes one `govpolicy.decide` audit record on the governance chain with producer id, agent id, matched rule ids, `request_ref` and correlation id, never the request's model or asset list beyond ids; `allow` writes no audit record and increments a counter.
- [ ] The SDK guard (`check_model`, `check_tool`, `check_data_access`) returns a `GuardDecision` with `effect`, `matches`, `degraded`, `fail_open` and `advisory=True`; it caches by request key for the response's `cache_ttl_seconds` (bounded size); on timeout, network error, 5xx or 429 it returns `allow` with `fail_open=True` and increments `guard.fail_open` in the default mode, and returns `deny` with reason `guard_unavailable` in `fail_closed` mode; it never raises into the agent unless the app calls `require_allowed`.
- [ ] Fail-open alert: the guard logs one warning per outage and reports the count of fail-open answers on its next successful call (header `X-NS-Guard-Fail-Open`); the API records it per producer on `GET /api/v1/governance/decide/status` (`govpolicy.read`), writes `govpolicy.sdk_fail_open_reported`, and publishes a notification through PRP-107 when that publisher is bound; an outage of a guard that never reconnects stays invisible server-side and the runbook says so.
- [ ] The words "enforce", "enforced", "block" and "blocked" do not appear in the guard's public names, docstrings, log messages or quickstart section except in the sentence "The guard is cooperative, not a security boundary; enforcement happens only at the gateway (PRP-112) and on NeuroSphere's own tool paths (PRP-113)"; a test checks it.
- [ ] The decide route is in `PRODUCER_AUTHENTICATED_PATHS`, returns 401 without a credential, and the producer-path tests compare the ingest router to the `/ingest/` subset only; the status route is in every route inventory and boots under `verify_route_permissions`.
- PRP exit: touched suites, `tests/security/authz`, `tests/security/decide`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Caller authentication | Entra workload identity; producer credential | Producer credential (design PRP-114 entry: producer-scoped), through the same authenticator as ingest. An Entra workload-identity variant is a follow-up if customers ask |
| 2 | What a producer may ask about | Any agent of its customer; agents under its sources | ASSUMPTION (GD-26, recommended default): a producer may ask the decision API only about catalog agents whose `source_id` is one of its own sources; others are 403 `subject_not_permitted` |
| 3 | Scope passed to `decide` | Wide service scope; per-request narrow scope | A per-request scope built by `decision_scope_for(producer, agent)`: the agent's domain only (plus the customer-control domain for customer-wide policies), holding only the permission PRP-105's `decide` checks (verify at execution; grant exactly that), never attached to the request or reused |
| 4 | Response redaction | Full matches; ids only | Ids only (policy, version, rule, kind, effect) and reason codes; PRP-99's response has no parameter field and none is added |
| 5 | SDK failure mode | Fail open; fail closed | ASSUMPTION (GD-8, recommended default): the SDK guard fails open with a counter and an alert. Here: `fail_closed` by `GuardOptions(failure_mode=...)` or `NS_AGENT_GUARD_FAILURE_MODE`. The server's `EnforcementSetting.sdk_failure_mode` is sent as header `X-NS-Guard-Failure-Mode` and used only when the app set nothing |
| 6 | Alert channel | Notification; status only | Status counter and audit always, plus a PRP-107 notification of event class `sdk_guard_fail_open_reported`, which PRP-110 (W25) adds to `NotificationEventClass` (PRP-107 has no separate registry and refuses classes outside the contract) |
| 7 | Rate limit | Shared with ingest; separate | Separate per-producer bucket at `decide_rate_limit_per_minute` (PRP-99 `EnforcementSetting`, default 600) |
| 8 | Enforcement default | `audit`; `enforce` | ASSUMPTION (GD-7, recommended default): `audit` for every policy and point; `enforce` only by an approved action, per point. Here: `deny` is returned only where PRP-105 says the `sdk` binding is `enforce` |
| 9 | Timeout | Fixed; configurable | ASSUMPTION: 300 ms default per call, `GuardOptions(timeout_ms=...)`, max 2000 |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-105-policy-engine-core.md` - `PolicyDecider`, `ENFORCEMENT_POINT_CAPABILITIES` (`sdk` cooperative), audit operation `govpolicy.decide`, `governance_policy_chain_id`, `GovernancePolicyPlane`.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided" - `PolicyDecisionRequest`, `PolicyDecisionResponse`, `EnforcementSetting`.
- `services/api/neurosphere_api/ingest/auth.py:44-101` and `ingest/service.py` (`authorize`) - authentication and cloud check.
- `services/api/neurosphere_api/ingest/limits.py:51-80` - `TokenBucketLimiter`.
- `services/api/neurosphere_api/authz/routes.py:78-92,240-250` - producer path category.
- `services/api/tests/ingest/test_route_authz.py:14-27`, `services/api/tests/path_aliases/test_aliases.py:115-162` - tests that pin the producer set to the ingest router.
- `services/api/neurosphere_api/admin/system/stored.py:15,56` - `STORED_SETTINGS` snapshot for the `enforcement` setting.
- `PRPs/backlog/PRP-79-agent-sdk-and-telemetry-onboarding.md` and `PRP-111-interaction-capture-sources-sdk-and-gateway.md` "Interfaces provided" - SDK client and the `capture/` sibling.
- `PRPs/backlog/PRP-107-notification-channels-and-subscriptions.md` "Interfaces provided" - `NotificationPublisher.publish`.

### Interfaces consumed
- PRP-105: `PolicyDecider.decide(scope, request, *, now) -> PolicyDecisionResponse`, `PolicyDecider.invalidate`, `app.state.governance_policy`, audit operation `govpolicy.decide` (deny and audit-mode would-deny only), `governance_policy_chain_id`, permission `govpolicy.read`.
- PRP-99: `PolicyDecisionRequest` (`decision_point`, `operation` `model_call|tool_invoke|mcp_call|data_access|register`, `agent_id`, `agent_version_id`, `tool_id`, `mcp_server_id`, `model`, `data_asset_ids` max 20, `access`, `environment`, `request_ref`; validator `check_decision_request_subject`), `PolicyDecisionResponse` (`effect`, `mode`, `matches`, `reason_codes`, `cache_ttl_seconds`, `policy_set_digest`, `degraded`), `EnforcementSetting` (`decision_cache_ttl_seconds`, `sdk_failure_mode`, `decide_rate_limit_per_minute`).
- PRP-79: `neurosphere_agent` client configuration (ingest URL, producer token). PRP-111: `neurosphere_agent/capture/` (sibling; no shared file except the one export line in `__init__.py`).
- PRP-107: `NotificationPublisher.publish(event)` with contract event classes only. PRP-110: the `sdk_guard_fail_open_reported` event class.
- Shipped: `RegisteredCredentialAuthenticator`, `TokenBucketLimiter`, `PRODUCER_AUTHENTICATED_PATHS`, `run_audited_mutation`, catalog repository `get_entity`, `STORED_SETTINGS`.

### Interfaces provided
- Route `POST /api/v1/governance/decide` (producer-authenticated; body `PolicyDecisionRequest`; 200 `PolicyDecisionResponse`; headers `X-NS-Guard-Failure-Mode` out, `X-NS-Guard-Fail-Open` in); route `GET /api/v1/governance/decide/status` (`govpolicy.read`, customer-control domain; per producer: calls, allow, deny, audit, rate limited, fail-open reported, last seen).
- API package `neurosphere_api.governance.decide` (`DecideService`, `decision_scope_for`, `redact_response`); builder `runtime/builders/governance_decide.py` (`BUILDER`, optional component `governance_decide`); `IngestService.authenticate_producer(authorization) -> ProducerRegistration` (credential and cloud check, no ingest rate token).
- Audit operations `govpolicy.decide` (PRP-99 name), `govpolicy.sdk_fail_open_reported` (new).
- SDK `neurosphere_agent.guard`: `GuardOptions(failure_mode="fail_open", timeout_ms=300, cache_size=1024)`, `check_model`, `check_tool`, `check_data_access`, `require_allowed(decision)`, `GuardDecision`, `GuardDenied`, `guard_stats()`; env `NS_AGENT_GUARD_FAILURE_MODE`.

### Patterns to match
- Producer-authenticated POST route registered by hook: `services/api/neurosphere_api/ingest/router.py:87-121`.
- Optional component builder reading shared state: `services/api/neurosphere_api/runtime/builders/admin_system.py`.
- Audited write with correlation id: `packages/core/neurosphere_core/audit/repository.py:247-270`.
- Cached snapshot with bounded lifetime: `services/api/neurosphere_api/ingest/producer_store.py`.
- SDK call that never raises into the agent: PRP-79's `verify_connection` and PRP-111's `capture_interaction`.

### Gotchas
- The decision scope is built per request and must never pass any other route dependency; a test asserts it is not stored on `request.state` and is garbage after the call.
- Agent lookup needs a system read of the catalog across the producer's customer; use it only to obtain `domain_id`, `source_id` and lifecycle, and never return anything from it. Unknown, foreign and not-permitted agents must take the same time path (no timing oracle beyond the existing dummy-hash pattern).
- `PRODUCER_AUTHENTICATED_PATHS` is asserted equal to the ingest router's paths in two tests; restrict those assertions to the `/ingest/` subset and add a decide-specific 401 test, or the suite fails. There is no `/v1/governance` alias.
- `govpolicy.decide` audit must not be written per `allow` (PRP-105 rule); counters only.
- Adding the builder changes `default_builders`: update `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`.
- The SDK must not import `neurosphere_api`; it posts JSON shaped by the PRP-99 TS/Python contract models it already depends on through `neurosphere-core`'s contracts dependency (verify; otherwise plain dicts validated by a test against the schema).
- New test directories need unique names (`governance_decide_api`, `sdk_guard`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/governance/decide/**
  - services/api/neurosphere_api/runtime/builders/governance_decide.py
  - services/api/neurosphere_api/ingest/service.py
  - services/api/tests/governance_decide_api/**
  - services/api/tests/ingest/test_route_authz.py
  - connectors/agent-sdk-python/neurosphere_agent/guard/**
  - connectors/agent-sdk-python/neurosphere_agent/__init__.py
  - connectors/agent-sdk-python/tests/sdk_guard/**
  - tests/security/decide/**
  - tests/security/authz/test_governance_decide*.py
  - docs/connectors/quickstart.md
  - docs/runbooks/governance-policy.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - services/api/tests/path_aliases/test_aliases.py
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/tests/runtime_gateway_builder/test_gateway_builder.py
  - services/api/tests/runtime_data/data_helpers.py
  - tests/integration/real_stack/test_manifest_routes.py
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/governance/**
  - packages/core/neurosphere_core/notifications/**
  - services/api/neurosphere_api/governance/policy/**
  - services/api/neurosphere_api/ingest/router.py
  - services/api/neurosphere_api/ingest/auth.py
  - connectors/agent-sdk-python/neurosphere_agent/capture/**
  - connectors/agent-sdk-python/pyproject.toml
  - pyproject.toml
  - uv.lock
```
`ingest/service.py` gains one public method only (`authenticate_producer`); PRP-111 held the file in W26.

## Implementation blueprint

Parallelization: items 1 and 4 [P] (API core and SDK share no file; the SDK codes against the PRP-99 models). Item 2 after 1; item 3 after 2; item 5 after 3 and 4; item 6 last.

### Item 1 - Decision service  [P]
- Deliverable: `governance/decide/{__init__,service,scope,redact,limits,models}.py`: `DecideService.decide(producer, request, correlation_id)` (agent lookup and source check, `decision_scope_for`, PRP-105 decider call, `redact_response`, per-producer limiter from the `enforcement` stored setting, audit for deny and would-deny, counters, fail-open report handling); `IngestService.authenticate_producer` in `ingest/service.py`.
- Owned files: those modules, `ingest/service.py` (one method), `services/api/tests/governance_decide_api/test_service.py`, `test_scope.py`, `test_redaction.py`.
- Must NOT touch: `ingest/auth.py`, `ingest/router.py`, PRP-105 packages.
- Depends on: PRP-105 merged.
- Acceptance criteria: criteria 1, 3, 4 and 5 at service level on in-memory fakes.
- Tests: the three files above.
- Pattern references: `ingest/service.py` (`authorize`), `audit/repository.py:247-270`.

### Item 2 - Routes, builder and producer path category
- Deliverable: `governance/decide/router.py` (decide and status routes, `register(registry)`), `runtime/builders/governance_decide.py`; Tier-2 lines in `routers.py`, `builders/__init__.py`, `status.py`, `authz/routes.py` (one path), route inventories and pinned builder tests; narrow the producer-set assertions in `services/api/tests/ingest/test_route_authz.py` and `path_aliases/test_aliases.py` to `/ingest/`.
- Owned files: the router and builder, `services/api/tests/governance_decide_api/test_routes.py`, `test_builder.py`, the two producer-set tests, Tier-2 lines.
- Depends on: item 1.
- Acceptance criteria: criteria 2 and 9; without PRP-105's component the route answers 503 `capability_unavailable` and the guard treats it as unavailable.
- Tests: `services/api/tests/governance_decide_api`, `services/api/tests/ingest`, `services/api/tests/path_aliases`, `services/api/tests/authz`.
- Pattern references: `ingest/router.py:98-121`, `runtime/builders/admin_system.py`.

### Item 3 - Fail-open alert path
- Deliverable: per-producer fail-open record on the status route, `govpolicy.sdk_fail_open_reported` audit, PRP-107 publisher call with event class `sdk_guard_fail_open_reported` (PRP-110).
- Owned files: `governance/decide/alerts.py`, `services/api/tests/governance_decide_api/test_fail_open_alert.py`.
- Depends on: item 2.
- Acceptance criteria: criterion 7 (server side).
- Tests: `test_fail_open_alert.py`.
- Pattern references: PRP-107's `ViolationNotificationSink` (its use of `NotificationPublisher`).

### Item 4 - SDK guard  [P]
- Deliverable: `neurosphere_agent/guard/` (`GuardOptions`, the three checks, bounded TTL cache, timeout, failure modes, `require_allowed`, `guard_stats`, fail-open warning and header report), one export line in `neurosphere_agent/__init__.py`; quickstart section "Policy guard (cooperative)".
- Owned files: `connectors/agent-sdk-python/neurosphere_agent/guard/**`, `__init__.py` (one line), `connectors/agent-sdk-python/tests/sdk_guard/**`, `docs/connectors/quickstart.md` (section).
- Must NOT touch: `capture/` (PRP-111), PRP-79 exporter modules.
- Depends on: PRP-79 and PRP-111 merged.
- Acceptance criteria: criteria 6 and 8 (SDK side), 7 (client side) against a fake transport.
- Tests: `connectors/agent-sdk-python/tests/sdk_guard/test_guard.py`, `test_failure_modes.py`, `test_wording.py`.
- Pattern references: PRP-111 `capture_interaction` (never raises), `ingest/producer_store.py` (cache lifetime).

### Item 5 - Security and leak suite
- Deliverable: `tests/security/decide/`: cross-customer, cross-cloud, foreign-source, disabled-producer and unknown-agent cases with identical bodies; response and error leak scan (no parameters, names, URLs, other subjects); the scope object cannot authorize any other route; rate limit isolation from ingest; audit records content-free; ABAC for the status route in `tests/security/authz/test_governance_decide.py`; end-to-end guard against the API on in-memory twins.
- Owned files: `tests/security/decide/**`, `tests/security/authz/test_governance_decide.py`.
- Depends on: items 3 and 4.
- Acceptance criteria: every case runs in CI (unmarked).
- Tests: `tests/security/decide`, `tests/security/authz`.
- Pattern references: `tests/security/authz/test_admin_producers.py`.

### Item 6 - Integration and close-out
- Deliverable: runbook section "Workload decisions and the SDK guard" in `docs/runbooks/governance-policy.md` (what the guard is and is not, failure modes, what the alert can and cannot see, rate limits); rebase; Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, index); changelog fragment; completion note with env vars (`NS_AGENT_GUARD_FAILURE_MODE`) and the product check (can a developer add the guard from the quickstart alone?).
- Owned files: runbook section, this PRP file, Tier-3 files.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/governance_decide_api services/api/tests/ingest services/api/tests/path_aliases services/api/tests/authz services/api/tests/runtime_api services/api/tests/runtime_gateway_builder services/api/tests/runtime_data services/api/tests/runtime_routes connectors/agent-sdk-python tests/security/decide tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. Turn off: drop the `governance_decide` component (unset or disable by its builder setting) so the route answers 503 and every guard falls back to its failure mode; or revert the PR. Agents that use the guard keep running (fail-open default).

## Live and open gates
None live: everything runs on in-memory twins and the local stack. The guard has no external dependency besides the deployment's own API.

## NOT building
A security boundary in the SDK (it is cooperative; an agent that does not call it is not constrained, and the gateway of PRP-112 is the only hard control on model traffic); blocking inside third-party SaaS; an Entra workload-identity variant of the route; disclosure of policy parameters to workloads; automatic remediation on `deny`; server-side detection of a guard that never reconnects; a TypeScript guard; alert rules and incidents on the fail-open signal (PRP-132).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 5, 6, 8 and 9 are ASSUMPTIONS; row 3 verifies PRP-105's permission at execution)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files or calling raw APIs):
