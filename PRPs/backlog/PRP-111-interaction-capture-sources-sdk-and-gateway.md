---
name: PRP-111-interaction-capture-sources-sdk-and-gateway
status: backlog
priority: P1
order: 111
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-01, NS-08, NS-09
depends_on: [PRP-103-interaction-capture-policy-and-edge, PRP-79-agent-sdk-and-telemetry-onboarding, PRP-100-telemetry-tool-service-identity-and-aggregates]
wave: W26
branch: prp-111-capture-sources
allow_parallel: true
issues: []
---

# PRP-111: Interaction capture sources: agent SDK, OTLP tool parts and the gateway log

## Goal
Add the places captured content can come from, all feeding the one capture path PRP-103 built at the ingest edge (policy match, detect, redact, encrypt, store, reference); this PRP adds no second capture path. Three sources: (1) an explicit opt-in in the agent SDK (`neurosphere_agent.capture`): off by default, a separate call per interaction, parts selectable, credentials redacted client-side before anything leaves the agent process, and nothing sent unless the server says a capture policy covers that source and domain; (2) OTLP tool input and tool output attributes mapped into the `tool_input` and `tool_output` parts on the existing OTLP route; (3) the APIM gateway LLM log, read by the gateway poller only when an approved capture policy covers that gateway's source, with the message columns treated as UNVERIFIED until the vendor documentation is fetched in item 1. Every source ends in the same PRP-103 pipeline, so the six metadata-only guards stay closed and nothing raw is ever written. It is for the security and compliance teams of gap G-a and for agent developers who opt in, and it runs in W26 after PRP-103, PRP-79 (the SDK) and PRP-100 (tool and service identity on spans).

Out of scope: the capture policy store, the edge pipeline, the detectors, the encrypted store, the explorer (PRP-103, PRP-101, PRP-102, PRP-104); the SDK policy guard (PRP-114, `neurosphere_agent/guard/`); conversation content from SaaS assistants (PRP-122 to PRP-125, through this same edge path); ingest load profiles with capture on (PRP-84); hosted enablement (PRP-109 for the demo domain, PRP-136 for live gates).

## Why
- The edge can capture only what arrives as OTLP body attributes: PRP-103 maps `BODY_FIELD_NAMES` (`packages/core/neurosphere_core/payload/guard.py:21-35`) to `prompt`, `response` and `system_instructions` and leaves tool parts and the `edge_push` source to this PRP (`PRPs/backlog/PRP-103-interaction-capture-policy-and-edge.md:54`, clarification 6). Tool arguments and results are not body field names at all; today they vanish only because the OTLP mapping keeps no attribute bag (`telemetry-event.schema.json` properties end at `payload_ref`).
- The ingest edge has exactly three producer routes (`services/api/neurosphere_api/ingest/router.py:98-107`; producer path allowlist `services/api/neurosphere_api/authz/routes.py:78-92`): no route accepts the PRP-99 `ContentEnvelope`, so an SDK has no way to send content beside its span.
- The agent SDK planned in PRP-79 "exposes no option to send bodies" (`PRPs/backlog/PRP-79-agent-sdk-and-telemetry-onboarding.md:37`); the design changes that to "no option in PRP-79; opt-in capture is PRP-111" and reserves `neurosphere_agent/capture/` (design section 6).
- The gateway poller's KQL is an allowlist that never projects message bodies (`connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/queries.py:59-78`; test `connectors/reference/azure-monitor/tests/test_apim_gateway_logs.py:32-33` names `RequestMessages` and `ResponseMessages` as forbidden), and the poller posts only to `/api/v1/ingest/events` (`services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:75`). A gateway in front of models is where most enterprise traffic is visible.
- `docs/PRD.md:12`: "Redact before persistence and external transmission; prompt/response bodies disabled by default." Owner direction 2026-11-16: the ultimate team AI governance and auditing tool, every gap planned; GD-14 reverses the metadata-only decision for opt-in capture only.

## Acceptance criteria
- [ ] Given no active capture policy for source S and domain D (or the `interaction_capture` setting off), When the SDK capture call runs, Then no content leaves the process (`capture.skipped_no_policy` counter, a test transport sees zero content bytes), and When any client posts content to the new route anyway, Then the content is dropped at the edge exactly as PRP-103 drops unrequested bodies, the telemetry event is still accepted, and nothing is stored.
- [ ] Given an active policy for S and D with parts `prompt`, `response`, `tool_input`, When the SDK sends an interaction with all five parts, Then only the three allowed parts are sent (intersection computed client-side and re-checked at the edge), one interaction is stored through the PRP-103 pipeline with `capture_source: edge_push`, and the published event carries `payload_ref` and passes `find_body_fields` with no paths.
- [ ] The SDK replaces every credential category (PRP-101 `CREDENTIAL_CATEGORIES`) with the `[[ns-redacted:<category>]]` placeholder before sending; a test with runtime-generated keys, JWTs and connection strings finds none of them, nor any hash or prefix of them, on the wire, in SDK logs or in the stored blob.
- [ ] Given an OTLP span with tool input and tool output attributes (names fixed by item 1) under an active policy that includes `tool_input`/`tool_output`, Then those parts are captured through the same pipeline (`capture_source: otlp_attributes`); with no policy, the published event, quarantine and archive records contain no tool argument canary.
- [ ] Given a gateway registration whose source has no active policy, Then the poller never runs the content query (asserted on the fake Log Analytics client: zero content queries). Given an active policy, Then the content query selects only the verified message columns joined by correlation id, credentials are redacted in the worker before the post, each row is posted with its event through the content route, and no row content is written to the watermark, the registration document, quarantine, a log line or an exception.
- [ ] The existing gateway query is unchanged and its test still proves message columns are never projected; the content query is a separate fixed template that can only be built from a `CaptureAuthorization` value returned by the capture-scope call.
- [ ] If item 1 cannot verify the message columns, or the gateway is in Government with an `unverified` capability row, Then the gateway source reports `not_supported` with a reason code on the PRP-103 capture status, and the SDK and OTLP sources still work.
- [ ] The two new producer routes return 401 without a credential (same body as today), 403 on cloud mismatch, 429 under the existing per-producer rate limit, and are listed in `PRODUCER_AUTHENTICATED_PATHS` in both the `/api/v1/ingest` and `/v1/ingest` forms; the capture-scope answer contains only allow, parts, max part length, policy version and a cache lifetime, never policy text, detector configuration or other sources.
- [ ] With capture on for all three sources, the six-guard negative suite from PRP-103 (event bus, worker pipeline, quarantine, archive, audit seal, SIEM, logs) passes for SDK and gateway traffic too.
- PRP exit: touched suites, `tests/security/capture_guards`, `tests/security/capture_sources`, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Capture turned on by | SDK flag; server policy; both | ASSUMPTION (GD-1, recommended default): capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; recommended default (a): a second steward approves; no change to who holds `action.approve`. OPEN for the owner. Here: both the SDK flag and the server policy. Off by default everywhere; the SDK sends only when the app opts in AND the server's approved capture policy covers the source and domain; the edge re-checks and drops otherwise |
| 2 | How an SDK sends content | Inside OTLP attributes; separate envelope | ASSUMPTION (GD-27, recommended default): two new producer routes, `POST /api/v1/ingest/interactions` and `POST /api/v1/ingest/capture-scope`, and the worker switch `NS_GATEWAY_POLL_CAPTURE_ENABLED` (default false), which must also be true before the gateway poller captures. Here: a separate route `POST /api/v1/ingest/interactions` taking one CloudEvents telemetry event plus its PRP-99 `ContentEnvelope` (same `event_id`); the edge processes the event as `/events` does and hands the envelope to PRP-103's `CapturePipeline`, so the published event carries the `payload_ref`. The request model is API-local (no contracts owner in W26) |
| 3 | How a client learns whether to send | Always send; ask | GD-27 (row 2): `POST /api/v1/ingest/capture-scope` (POST-only, like every producer route) with a `domain_id`; answers allow, parts, `max_part_chars`, policy version, cache lifetime for the caller's own sources only |
| 4 | Gateway content path | Worker stores; edge stores | The poller posts to the edge content route; the PRP-103 pipeline detects, redacts, encrypts and stores. This keeps one capture path (the design's PRP-111 entry said "redacted in the worker before it is stored"; the worker still redacts credentials before the post, and storage happens only at the edge) |
| 5 | Client-side redaction | None; credentials only; full policy | Credentials only, with PRP-101 `redact` forced to the credential categories; the server applies the full policy (dictionaries and kept categories live server-side) |
| 6 | What is never stored | see GD-4 | ASSUMPTION (GD-4, recommended default): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact |
| 7 | Captured content to copilot or MCP | yes; no | ASSUMPTION (GD-3, recommended default): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Here: this PRP adds no reader |
| 8 | Gateway capture switch in the worker | Policy only; policy plus worker setting | GD-27 (row 2): `NS_GATEWAY_POLL_CAPTURE_ENABLED` (default false) must also be true before the poller asks for a capture scope, so an operator can stop the gateway source without touching policies |
| 9 | Tool attribute names | Assume OTel names; verify | Verify-first in item 1 (OpenTelemetry GenAI semantic conventions); the design does not state them and none is coded from memory |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-103-interaction-capture-policy-and-edge.md` "Interfaces provided", Gotchas and clarification 6 - the pipeline you feed.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided" - `ContentEnvelope`, `ContentPart`, `ContentPartKind`, `PayloadRef` additions, `InteractionRecord.capture_source`.
- `PRPs/backlog/PRP-101-sensitive-information-detectors-and-redaction.md` "Interfaces provided" - `redact`, `RedactionConfig`, `CREDENTIAL_CATEGORIES`.
- `PRPs/backlog/PRP-79-agent-sdk-and-telemetry-onboarding.md` "Interfaces provided" - the SDK's client, `init`, env names.
- `services/api/neurosphere_api/ingest/service.py` (order of work, `authorize`, `_parse`) and `ingest/router.py:87-121`.
- `services/api/neurosphere_api/authz/routes.py:78-92` and `services/api/tests/ingest/test_route_authz.py:14-27` - the producer path invariant.
- `connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/queries.py:59-125` and `connector.py:195-360` - fixed KQL templates and the poll loop.
- `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:75-200` - `IngestClient`, `GatewayPoller`.
- `connectors/reference/otel-generic/neurosphere_connector_otel_generic/convert.py:62-73` - `redact_outgoing` (the SDK's existing body drop).

### Interfaces consumed
- PRP-103: `CapturePipeline.capture(...) -> PayloadRef`, `CaptureMatcher.match(source_id, domain_id, event_id)`, `extract_body_parts(item) -> ContentEnvelope`, `IngestService.attach_capture(pipeline)`, counters on `app.state.interaction_capture_stats`, capture status route, audit operations `interaction.capture` and `interaction.capture_dropped`.
- PRP-99: `ContentEnvelope` {`schema_version`, `cloud`, `source_id`, `event_id`, `trace_id`, `span_id`, `occurred_at`, `parts` 1-5 of `ContentPart` {`part`, `text` 1-32768 chars, `truncated`}}, `check_content_envelope_parts`, `ContentPartKind` (`prompt`, `response`, `tool_input`, `tool_output`, `system_instructions`), `InteractionRecord.capture_source` (`edge_push`, `otlp_attributes`, `gateway_log`).
- PRP-101: `redact(text, config, detector_set, budget)`, `default_detector_set()`, `RedactionConfig`, `CREDENTIAL_CATEGORIES`.
- PRP-79: package `neurosphere_agent` in `connectors/agent-sdk-python` (`init`, the configured ingest client and token, `agent_span`), quickstart `docs/connectors/quickstart.md`. Design section 6 asks PRP-79 to reserve `neurosphere_agent/{capture,guard}/`; if its shipped text still says "no option to send bodies", this PRP's runbook section supersedes it.
- PRP-100: tool and service identity on spans (`tool`, `service` on `TelemetryEvent`); the tool-part extraction uses the same span.
- Shipped: `IngestService.authorize`, `TokenBucketLimiter`, `register_with_alias`, `GatewayPoller`, `AzureMonitorConnector`.

### Interfaces provided
- Routes (producer-authenticated, POST-only, both prefix forms): `POST /api/v1/ingest/interactions` (body `{event, content}`; 202 `IngestResult` plus `capture` `captured|skipped_no_policy|dropped|shed|failed`), `POST /api/v1/ingest/capture-scope` (body `{domain_id}`; `CaptureScopeAnswer` {`allowed`, `parts`, `max_part_chars`, `capture_policy_version`, `cache_ttl_seconds`}).
- API: `neurosphere_api.ingest.content_mapping` - `extract_tool_parts(item) -> list[ContentPart]`, `TOOL_INPUT_ATTRIBUTES`, `TOOL_OUTPUT_ATTRIBUTES` (from item 1).
- SDK: `neurosphere_agent.capture` - `CaptureOptions(enabled=False, parts=...)`, `capture_interaction(event_id, *, prompt=None, response=None, tool_input=None, tool_output=None, system_instructions=None) -> CaptureOutcome`, counters `capture.sent`, `capture.skipped_no_policy`, `capture.redacted_credentials`, `capture.failed`; env `NS_AGENT_CAPTURE_ENABLED` (default false).
- Connector: `neurosphere_connector_azure_monitor.queries.APIM_LLM_CONTENT_COLUMNS`, `content_template(authorization)`, `CaptureAuthorization`; worker setting `NS_GATEWAY_POLL_CAPTURE_ENABLED`.
- Capture status gains source rows `sdk`, `otlp_tool_parts`, `gateway_log` with state `ok|disabled|not_supported` and reason codes.

### Patterns to match
- Fixed KQL template selected by enum, never interpolated: `queries.py:52-111`.
- Producer route with alias registration: `ingest/router.py:98-121`.
- Values-never-returned walk: `payload/guard.py:67-104`.
- Opt-in SDK behaviour with counters: PRP-79's `redact_outgoing` use in its exporter (`convert.py:62-73`).
- Gateway poller batch post and error handling: `poller.py:136-170`.

### Gotchas
- UNVERIFIED (design U-3): that APIM gateway LLM logs can carry request and response messages, under which table and column names (PRP-33's test names `RequestMessages` and `ResponseMessages` only as forbidden projections), whether logging them must be enabled per API, size limits and whether long messages are split across rows. Item 1 fetches Microsoft Learn and records what it found; if false, the gateway is not a content source (SDK and OTLP only) and the criterion is recorded OPEN. Also unverified: OpenTelemetry GenAI attribute names for tool call arguments and results.
- Never add tool attribute names to `BODY_FIELD_NAMES` or change `payload/guard.py`: the guard is one of the six; extraction reads the parsed document before mapping, as PRP-103 does.
- `payload_ref` and request-model keys must not end in `prompt` or `response` (`is_body_field` matches the last dotted segment); the route body's content lives under `content.parts[].text`, and the edge must extract it before any guard walk sees the request. Test the published message with `find_body_fields`.
- `tests/ingest/test_route_authz.py:14-19` asserts `PRODUCER_AUTHENTICATED_PATHS` equals the ingest router's POST paths in both forms; add both forms of both routes or the app refuses to boot.
- The capture-scope answer is cached by the client for at most its `cache_ttl_seconds`; a policy turned off stops capture within that bound and the edge drops anything sent meanwhile.
- The poller must hold content only in memory for one post; `IngestPostError` paths must not include the batch in the exception or log extra.
- Government: the edge enforces the cloud match; the gateway source is `not_supported` in Government until the capability row is verified (PRP-33 rows are `unverified`).
- Synthetic content only: canaries `NSCANARY-<uuid>` and credential-shaped values built at runtime (gitleaks fingerprints).
- New test directories need unique names (`capture_sources_edge`, `capture_sources_sdk`, `gateway_poll_capture`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/ingest/content_mapping.py
  - services/api/neurosphere_api/ingest/service.py
  - services/api/neurosphere_api/ingest/router.py
  - services/api/neurosphere_api/ingest/capture.py
  - services/api/tests/capture_sources_edge/**
  - services/api/tests/ingest/test_route_authz.py
  - connectors/agent-sdk-python/neurosphere_agent/capture/**
  - connectors/agent-sdk-python/neurosphere_agent/__init__.py
  - connectors/agent-sdk-python/pyproject.toml
  - connectors/agent-sdk-python/tests/capture_sources_sdk/**
  - connectors/reference/azure-monitor/**
  - services/workers/neurosphere_workers/ingestion/gateway_poll/**
  - services/workers/tests/gateway_poll_capture/**
  - tests/security/capture_sources/**
  - docs/runbooks/interaction-audit.md
  - docs/connectors/quickstart.md
  - scripts/gates/gateway_capture_live.py
tier1: []
tier2_appends:
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/path_aliases/test_aliases.py
  - services/workers/neurosphere_workers/runtime/settings.py
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/payload/**
  - packages/core/neurosphere_core/interactions/**
  - packages/core/neurosphere_core/classification/**
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - services/api/neurosphere_api/runtime/builders/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - connectors/agent-sdk-python/neurosphere_agent/guard/**
  - connectors/reference/otel-generic/**
  - pyproject.toml
```

## Implementation blueprint

Parallelization: item 1 first (it fixes names the rest code against). Items 2, 3 and 4 [P] after item 1 (edge, SDK and connector share no file). Item 5 after 2 and 4. Item 6 after 2-5. Item 7 is `[serial-after: PRP-117]`. Item 8 last.

### Item 1 - Verify-first record
- Deliverable: fetch Microsoft Learn for the APIM LLM gateway log (table, message columns, how message logging is enabled, size limits, splitting, Government availability) and the OpenTelemetry GenAI semantic conventions for tool call arguments and results; record URL, retrieval date, what was found and the fallback in a "Verified sources" section of `connectors/reference/azure-monitor/README.md` and in `docs/runbooks/interaction-audit.md` ("Capture sources"). Fields not verified are not coded.
- Owned files: those two documents.
- Depends on: PRP-103 merged.
- Acceptance criteria: each fact has a URL and date or is marked OPEN with its fallback.
- Tests: none (documents); item 4 tests cite the recorded names.
- Pattern references: design section 2.5 "Verify-first files".

### Item 2 - Edge: content route, capture scope and tool parts  [P]
- Deliverable: `ingest/content_mapping.py` (`extract_tool_parts`); `ingest/service.py` methods `ingest_with_content` (event as `/events`, envelope validated by `check_content_envelope_parts`, `event_id` must match, hand-off to the attached `CapturePipeline` with `capture_source: edge_push`) and `capture_scope` (matcher answer for the caller's own sources); `ingest/capture.py` composes tool parts with `extract_body_parts` on the OTLP path; `ingest/router.py` two routes; `authz/routes.py` four paths.
- Owned files: the four ingest modules, `services/api/tests/capture_sources_edge/**`, `services/api/tests/ingest/test_route_authz.py`; Tier-2 lines in `authz/routes.py`, route inventories, `path_aliases/test_aliases.py`.
- Must NOT touch: `otlp_mapping.py`, `payload/guard.py`, `limits.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 1, 2 (edge side), 4 and 8; with no pipeline attached the new route behaves as `/events` and counts `capture_skipped_no_policy`; existing `services/api/tests/ingest` passes.
- Tests: `services/api/tests/capture_sources_edge/test_content_route.py`, `test_capture_scope.py`, `test_tool_parts.py`, `services/api/tests/ingest`.
- Pattern references: `ingest/router.py:98-121`, PRP-103's capture branch in `service.py`.

### Item 3 - SDK opt-in capture  [P]
- Deliverable: `neurosphere_agent/capture/` (`CaptureOptions`, `capture_interaction`, a scope cache honouring `cache_ttl_seconds`, client-side credential redaction through PRP-101 `redact`, part intersection, post to `/ingest/interactions`, counters, never raising into the agent: failures count and drop); one export line in `neurosphere_agent/__init__.py` if PRP-79 exposes no public client accessor; quickstart section "Opt-in interaction capture" with the off-by-default statement.
- Owned files: `connectors/agent-sdk-python/neurosphere_agent/capture/**`, `__init__.py` (one line), `connectors/agent-sdk-python/tests/capture_sources_sdk/**`, `docs/connectors/quickstart.md` (section).
- Must NOT touch: PRP-79's exporter and span modules, `guard/` (PRP-114).
- Depends on: item 1; PRP-79 merged.
- Acceptance criteria: criteria 1 and 3 (SDK side), 2 (intersection); with `enabled=False` the module makes no network call.
- Tests: `connectors/agent-sdk-python/tests/capture_sources_sdk/test_capture_opt_in.py`, `test_client_redaction.py`.
- Pattern references: PRP-79's `verify_connection`; `convert.py:62-73`.

### Item 4 - Azure Monitor content template  [P]
- Deliverable: `queries.py` `APIM_LLM_CONTENT_COLUMNS` (verified names only), `CaptureAuthorization` (gateway source id, domain, parts, policy version, issued from a capture-scope answer), `content_template(authorization)` (fixed KQL, correlation ids bound through the documented parameter path, never interpolated), a connector method that runs it and returns rows as transient values; README section.
- Owned files: `connectors/reference/azure-monitor/**`.
- Must NOT touch: `connectors/reference/apim-gateway/**` (PRP-112 W25 shipped it), `_APIM_GATEWAY_QUERY`.
- Depends on: item 1.
- Acceptance criteria: criterion 6; the content template cannot be selected through `template_for(kind)`; `test_apim_gateway_logs.py` passes unchanged.
- Tests: `connectors/reference/azure-monitor/tests/test_llm_content_template.py`, existing `connectors/reference/azure-monitor/tests`.
- Pattern references: `queries.py:52-111`, `connector.py:336-360`.

### Item 5 - Gateway poller capture
- Deliverable: `gateway_poll/` asks `capture-scope` per (gateway source, domain) when `NS_GATEWAY_POLL_CAPTURE_ENABLED` is true, runs the content template only for an allowed answer, redacts credentials, builds one `ContentEnvelope` per event and posts pairs to `/ingest/interactions`; content is never added to `_Outcome`, the registration, the watermark or logs; settings field and Tier-2 line in worker `runtime/settings.py` only if the poller settings need a global (prefer `GatewayPollSettings`).
- Owned files: `services/workers/neurosphere_workers/ingestion/gateway_poll/**`, `services/workers/tests/gateway_poll_capture/**`.
- Must NOT touch: `runtime/factories.py` (constructor parameters have defaults, so the builder body is unchanged).
- Depends on: items 2 and 4.
- Acceptance criteria: criteria 5 and 7; with the switch false the poller behaves byte-for-byte as today (`services/workers/tests/gateway_poll` passes).
- Tests: `services/workers/tests/gateway_poll_capture/test_poller_capture.py`, `test_no_content_retained.py`, `services/workers/tests/gateway_poll`.
- Pattern references: `poller.py:225-345`.

### Item 6 - Negative and constraint suite
- Deliverable: `tests/security/capture_sources/`: the six-guard suite re-run with SDK, OTLP tool and gateway traffic (reuse PRP-103's harness from `tests/security/capture_guards`); "no second path" test (only `CapturePipeline` writes to `InteractionStore`, enumerated by import graph); secrets never stored; capture-scope answers leak no policy internals; unrequested content dropped; Government gateway `not_supported`.
- Owned files: `tests/security/capture_sources/**`.
- Must NOT touch: `tests/security/capture_guards/**` (import its helpers only).
- Depends on: items 2-5.
- Acceptance criteria: criterion 9; every case runs in CI (unmarked).
- Tests: `tests/security/capture_sources`.
- Pattern references: PRP-103 item for `tests/security/capture_guards`.

### Item 7 - SDK dependency declaration  [serial-after: PRP-117]
- Deliverable: after PRP-117 (W26 lockfile owner) merges: declare `neurosphere-core` (workspace) as a direct dependency of `connectors/agent-sdk-python/pyproject.toml` (the capture module imports `neurosphere_core.classification`, today only transitive through `neurosphere-connector-otel-generic`) and regenerate `uv.lock`; no new third-party package.
- Owned files: `connectors/agent-sdk-python/pyproject.toml`, `uv.lock` (lock regeneration only).
- Depends on: items 3 and PRP-117 merged.
- Acceptance criteria: `uv lock --check` clean; licence report unchanged.
- Tests: `uv run pytest -q connectors/agent-sdk-python`.
- Pattern references: `connectors/reference/otel-generic/pyproject.toml:6-15`.

### Item 8 - Integration and close-out
- Deliverable: live gate script `scripts/gates/gateway_capture_live.py` (refuses without `NS_LIVE_APPROVED=1`; enables message logging on a throwaway APIM only with operator approval, posts a synthetic prompt, checks one interaction with `capture_source: gateway_log`); runbook "Capture sources" section complete; threat-model note handed to the reviewer; rebase; Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, index); changelog fragment; completion note with env vars (`NS_AGENT_CAPTURE_ENABLED`, `NS_GATEWAY_POLL_CAPTURE_ENABLED`) and the product check.
- Owned files: the gate script, runbook, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green; the live gate is recorded OPEN unless run.

## How the hard constraints are kept
- Metadata-only by default: every source is off until an approved capture policy matches; the SDK flag alone captures nothing; the edge re-checks and drops unrequested content (criterion 1).
- One capture path: all three sources end in PRP-103's `CapturePipeline`; the "no second path" test enforces it; the six guards are unchanged and re-tested.
- Secrets never stored: client-side and worker-side credential redaction before transmission, then PRP-101 redaction at the edge; failures drop content.
- No content to copilot, MCP, logs, audit payloads, SIEM or OpenAPI examples: this PRP adds no reader; OpenAPI examples use the PRP-99 placeholder text; audit records carry ids and counts (PRP-103 operations).
- Authorization on every path: producer credential, cloud match and rate limit on both routes; capture scope answers only for the caller's own sources.
- Government boundary: content never leaves the deployment's cloud (edge cloud match); no external classification call.
- Synthetic content only in tests and demos.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/capture_sources_edge services/api/tests/ingest services/api/tests/interaction_capture_edge services/api/tests/authz services/api/tests/path_aliases connectors/agent-sdk-python connectors/reference/azure-monitor/tests services/workers/tests/gateway_poll services/workers/tests/gateway_poll_capture tests/security/capture_sources tests/security/capture_guards tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, only if this session holds the compose stack): seed a local capture policy (PRP-103 `NS_ENV=local` seed), run the quickstart agent with `NS_AGENT_CAPTURE_ENABLED=true`, confirm one interaction in the explorer metadata list.

## Migration and rollback
No data migration. Off switches: unset `NS_AGENT_CAPTURE_ENABLED` (SDK sends nothing), set `NS_GATEWAY_POLL_CAPTURE_ENABLED=false` (no content query), or suspend the capture policy through an approved `capture_policy_change` (edge stops within the scope cache lifetime). Revert the PR to remove the routes; stored interactions remain under PRP-102 retention and holds.

## Live and open gates
Gateway log read on a real APIM with message logging enabled: `scripts/gates/gateway_capture_live.py`, `NS_LIVE_APPROVED=1` and operator approval; OPEN until run, handed to PRP-136. SDK and OTLP sources need no live gate (proven on the local stack).

## NOT building
A second capture or storage path; capture without an approved policy; a model-based detector (structured identifiers only, GD-6); content from SaaS assistants (only where a vendor API exposes it, PRP-122 to PRP-125); endpoint, browser or network DLP; gateway content capture for traffic that does not pass a NeuroSphere-registered gateway; gateway capture in Government until verified; any copilot, MCP or export reader of content; the SDK policy guard (PRP-114); a TypeScript SDK.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1-3, 6-8 are ASSUMPTIONS; gateway columns and tool attribute names are verify-first)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | serial-after PRP-117 |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files or calling raw APIs):
