---
name: PRP-103-interaction-capture-policy-and-edge
status: backlog
priority: P0
order: 103
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-01, NS-08
depends_on: [PRP-99-governance-contracts-a, PRP-101-sensitive-information-detectors-and-redaction, PRP-102-encrypted-interaction-store-and-retention]
wave: W22
branch: prp-103-capture-policy-and-edge
allow_parallel: true
issues: []
---

# PRP-103: Interaction capture policy and the ingest-edge capture path

## Goal
Add the seventh path beside the six metadata-only guards, without opening any of them. When, and only when, the deployment-wide switch is on, the customer's retention policy opts in to bodies, and an approved, active capture policy matches the producer's registered source and the event's domain, the ingest edge takes the body fields that `drop_body_fields` would discard, detects and redacts them (PRP-101), encrypts and stores the redacted result (PRP-102), and puts only a `payload_ref` (pointer, redaction state, detected categories, detector-set version, capture-policy version, part kinds) on the event. In every other case the edge behaves exactly as today. Secrets are always replaced by a typed placeholder; if anything in detection, redaction, encryption or storage fails, the content is dropped and the event says `redaction_failed`. Capture is shed before telemetry under load. It also ships the capture-policy store and matcher, the `capture_policy_change` apply and read-back functions that PRP-108's `platform-control` target will call, a read-only admin page for capture policies and status, and a negative test per guard. It is for the security and compliance teams who asked for interaction audit (gap G-a), and runs in W22 on PRP-99, PRP-101 and PRP-102. Opus: this is the first code that handles real prompt and response text.

Out of scope: who may read content, the explorer, export and replay (PRP-104); executing `capture_policy_change` through the executor and its approval rules (PRP-108; until it lands policies exist only through the `NS_ENV=local` seed); SDK opt-in, OTLP tool input and output parts, gateway log content (PRP-111); `content_rule` violations (PRP-105); hosted enablement (PRP-109); ingest load profiles with capture on (PRP-84).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every gap planned; GD-14 reverses the 2026-11-06 metadata-only decision (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:71-72`) for opt-in capture, while `docs/PRD.md:12` stays true: "prompt/response bodies disabled by default".
- The edge drops bodies by key name and keeps nothing: `services/api/neurosphere_api/ingest/service.py:1-7` (order of work), `:116-124` (`_parse` returns `drop_body_fields(parsed)`); `packages/core/neurosphere_core/payload/guard.py:67-104`. Nothing in the tree ever sets `payload_ref` (only the replay reader reads it, `replay/reader.py:187,207-208`).
- The six guards this PRP must leave closed, verified: contract `packages/contracts/schemas/telemetry/v1/telemetry-event.schema.json:5,7` (no body field, `additionalProperties: false`; `payload_ref` `:154-157`, `$defs` `:287-312`); edge `ingest/service.py:124`; worker `services/workers/neurosphere_workers/ingestion/pipeline.py:144-145` (`BODY_FIELD_PRESENT`); quarantine `services/workers/neurosphere_workers/quarantine/blob.py:156`; archive `services/workers/neurosphere_workers/archive/serialize.py:57-64` (`redact_record`); audit seal `packages/core/neurosphere_core/audit/chain.py:110` calling `audit/content_guard.py:121` (`assert_metadata_only`). SIEM (`audit/siem.py:62` `to_siem_event`) and logs (`observability/redaction.py:12-23`) are checked too.
- The edge has no trustworthy domain: the stamped scope is cloud, customer and source only (`ingest/otlp_mapping.py:116-121`); `domain_id` comes from the payload. A capture policy must therefore key on the registered source.
- `docs/security/threat-model.md:190` states "`payload/guard.py` drops bodies by default before persist or publish"; the threat model must gain rows for the new path.

## Acceptance criteria
- [ ] Given no active capture policy (or the `interaction_capture` stored setting absent or disabled, or `bodies_retained` false, or no `interaction_content` retention rule), When any ingest route is called, Then the published messages, the 202 body and every counter are identical to today, and the existing `services/api/tests/ingest` suite passes unchanged.
- [ ] Given an approved, active policy for source S and domain D, When a span from S with `domain_id` D carries body attributes, Then exactly one interaction is stored (redacted, encrypted), the published event carries `payload_ref` with `redaction_state: redacted` and the policy version, and the published message passes `find_body_fields` with no paths; a span from S with another or a null domain, or from another source, is not captured.
- [ ] Credentials in captured text are stored only as the PRP-99 placeholder `[[ns-redacted:<detected_category>]]`; decrypting the stored blob in the test finds no generated secret, no hash or prefix of it; payment cards are redacted unless the policy keeps them (GD-4).
- [ ] Given an injected failure in detection, redaction, key wrap or storage, Then nothing is written, the event carries `payload_ref` with `redaction_state: redaction_failed` and an index-only record, the telemetry item is still accepted, and `capture_failed` increments with a reason code.
- [ ] Each captured interaction appends one `interaction.capture` audit record (and each drop one `interaction.capture_dropped`) on the domain chain with the triggering `correlation_id`, ids and counts only; if that audit write fails, the content is not kept (blob removed or never written) and the drop is counted.
- [ ] Given the capture in-flight queue reaches `shed_capture_at_queue_percent` of its capacity, or the policy's `sampling.max_per_minute` is exceeded, Then content is shed (no `payload_ref`), `capture_shed` increments and telemetry is still published; ingest latency with capture off is unchanged.
- [ ] With capture ON, a negative test per guard proves body-free output: the event-bus message, the worker pipeline (accepts the event, still quarantines a message that carries a body with `BODY_FIELD_PRESENT`), the quarantine record, the archive record, audit records (sealed), SIEM events and all log records contain no canary from the captured content.
- [ ] `capture_policy_change` apply and read-back functions validate the diff, refuse a policy without an approving audit id, write the new version with ETag, and return the stored state for verify; there is no API route that creates or changes a capture policy.
- [ ] `GET /api/v1/admin/interactions/capture-policies` and `GET /api/v1/admin/interactions/capture-status` need `config.manage` in the domain (customer-control for all domains), are in every route inventory, return metadata and counters only, and the admin page shows each policy, its scope, parts, modes, sampling, approval audit id, status and the reason capture is off when it is off.
- PRP exit: touched suites, `tests/security/capture_guards`, `tests/security/authz`, ruff, pyright, frontend lint/typecheck/test/e2e, `validate_planning.py` pass; PR open with CI green; `openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Reverse metadata-only | keep; reverse for opt-in | Decided by the owner 2026-11-16 (GD-14): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log |
| 2 | Capture default and who approves a `capture_policy_change` | (a) a second steward approves; (b) the maker-checker approver rule is relaxed for the governance action kinds so an admin approves | Decided by the owner 2026-11-16 (GD-1): capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; decided: a second steward approves; no change to who holds `action.approve`; admins do not approve these (option (b), relaxing the approver rule so an admin approves, was not chosen). Here: capture policies are NOT an `admin_kind`; they live in PRP-102's container `interaction_capture_policies` and this PRP's `CapturePolicyStore` is the only code over it; a change is applied only by PRP-108's handler through `apply_capture_policy_change` |
| 3 | What is never stored | see GD-4 | Decided by the owner 2026-11-16 (GD-4): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: credentials are always replaced by the PRP-99 placeholder |
| 4 | Captured content to copilot or MCP | yes for investigators; no | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Here: this PRP adds no reader at all |
| 5 | Domain trust at the edge | trust payload domain; source only; source and domain | Decided by the owner 2026-11-16 (GD-46): the payload `domain_id` is trusted for capture only together with the registered source; an event with no domain is never captured. Here: the policy keys on the registered source AND the payload domain |
| 6 | Which fields become which part | everything as one part; mapped | ASSUMPTION: the existing `BODY_FIELD_NAMES` map to parts `prompt` (`prompt`, `gen_ai.prompt`, `gen_ai.input.messages`, `messages`, `*.prompt`), `response` (`response`, `completion`, `gen_ai.completion`, `gen_ai.output.messages`, `*.response`), `system_instructions` (`gen_ai.system_instructions`); tool parts are PRP-111. `InteractionRecord.capture_source` is `otlp_attributes`; the `ContentEnvelope` push (`edge_push`) arrives with PRP-111 |
| 7 | Failure pointer | omit `payload_ref`; pointer to an index-only record | ASSUMPTION: `payload_ref.pointer` is required by the contract, so a failure writes an index-only record (no blob) and points to it |
| 8 | Deployment switch | env var; stored setting | The PRP-99 `interaction_capture` stored setting (`InteractionCaptureSetting`); absent or `enabled: false` means off; ASSUMPTION: applied at restart like other stored settings |
| 9 | Sampling | random; deterministic | `CapturePolicy.sampling.rate` applied deterministically by hash of the event id (a retry gets the same answer); `max_per_minute` is a per-policy token bucket |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/ingest/service.py` - order of work, `_parse`, `_telemetry_message`, `_finish`, the three ingest paths.
- `packages/core/neurosphere_core/payload/guard.py` - the guard this PRP must not change.
- `services/api/neurosphere_api/runtime/builders/edge.py:1-60` - attaching to the bootstrapped ingest service through `on_startup` (PRP-41 precedent).
- `services/api/neurosphere_api/admin/system/stored.py` and `runtime/builders/admin_system.py:1-14` - `STORED_SETTINGS` snapshot.
- `services/workers/neurosphere_workers/ingestion/pipeline.py:130-150`, `quarantine/blob.py:150-160`, `archive/serialize.py:55-66`, `audit/chain.py:100-115`, `audit/siem.py:44-66` - the guards the negative suite drives.
- `services/workers/neurosphere_workers/runtime/factories.py:735-761` - `_lifecycle_targets` (serial item 7).
- `services/api/neurosphere_api/admin/sources/producers/router.py` - admin route style.
- PRP-99, PRP-101, PRP-102 "Interfaces provided"; PRP-107 "Interfaces provided" for the `factories.py` state after its merge.

### Interfaces consumed
- PRP-99 (`PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided"): `CapturePolicy` (`domain_id`, `source_ids`, `parts`, `detector_set_version`, `customer_dictionary_ids`, `redaction_mode`, `kept_categories`, `sampling` {`rate`, `max_per_minute`}, `max_part_chars`, `retention_days`, `state` `proposed`|`active`|`suspended`|`retired`, `approved_intent_id`, `approved_audit_id` required when active, `version`); `InteractionRecord`, `RedactedContent`, `DetectionFinding`, `DetectedCategory`, `ContentPartKind`; `PayloadRef` additions `interaction_id`, `capture_policy_id`, `capture_policy_version`, `detector_set_version`, `detected_categories`, `content_parts` (list of {`part`, `char_count`, `truncated`}); `ContentEnvelope` (transient; parts up to 32768 chars); manifest action `capture_policy_change`; `InteractionCaptureSetting` (`max_content_chars_per_interaction`, `shed_capture_at_queue_percent`); `TargetRef.entity_type` `capture_policy`; audit operations `interaction.capture`, `interaction.capture_dropped`.
- PRP-101: `redact`, `default_detector_set`, `RedactionConfig`, `Finding`, `RedactionFailed`.
- PRP-102: `InteractionStore`, `RedactedContent`, `KeyVaultKeyWrapper`, `LocalFileKeyWrapper`, `InteractionSettings`, `content_writes_enabled`, container `interaction_capture_policies`, `build_targets(..., interaction_index=, interaction_blobs=)`.
- Shipped: `IngestService`, `HubMessage`, `load_policy_file`, `require`, `require_customer_control`, `RouterRegistry`, `run_audited_mutation`.

### Interfaces provided
- Core `neurosphere_core.interactions`: `CapturePolicyStore` (Cosmos and in-memory), `CaptureMatcher.match(source_id, domain_id, event_id) -> CaptureDecision | None`, `apply_capture_policy_change(store, change, approved_audit_id) -> CapturePolicy`, `read_back_capture_policy(store, policy_id) -> CapturePolicy` (for PRP-108), `seed_local_capture_policy(...)` (`NS_ENV=local` only), `extract_body_parts(item) -> ContentEnvelope` (pure; does not change `payload/guard.py`), `CapturePipeline.capture(...) -> PayloadRef`.
- API: `IngestService.attach_capture(pipeline)`; component `interaction_capture` (optional) in `runtime/status.py`; counters `captured`, `capture_skipped_no_policy`, `capture_failed{reason}`, `capture_shed` on `app.state.interaction_capture_stats`.
- Routes `GET /api/v1/admin/interactions/capture-policies`, `GET /api/v1/admin/interactions/capture-policies/{policy_id}`, `GET /api/v1/admin/interactions/capture-status`.
- Settings (ASSUMPTION) `NS_INTERACTION_CAPTURE_QUEUE_CAPACITY` (default 64; shedding starts at the stored setting's percent), `NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST` (default 100).
- Audit operations `interaction.capture`, `interaction.capture_dropped` (PRP-99 names), `capture_policy.apply`, `capture_policy.seed_local` (ASSUMPTION names); pointer scheme `interaction:<interaction_id>` (PRP-104 resolves it).

### Patterns to match
- Attach after bootstrap: `runtime/builders/edge.py` `admin_producers` (on_startup hook, reason codes).
- Audited write with ETag: `audit/repository.py:247-270` `run_audited_mutation`; `mcp/cosmos_store.py:86-140`.
- Admin read routes: `admin/sources/producers/router.py`; customer control `actions/customer_control.py:91`.
- Iterative, values-never-returned walk: `payload/guard.py:67-104`.
- Frontend admin area: `frontend/src/features/admin/sources/routes.tsx`, `shared/areas.ts`.

### Gotchas
- `payload_ref` keys must never end in `prompt` or `response` and `content_parts` must be a list, not an object keyed by part names: `is_body_field` matches the last dotted segment (`guard.py:45-55`) and the worker would quarantine every captured event as `BODY_FIELD_PRESENT`. Audit `FORBIDDEN_KEYS` (`content_guard.py:21-45`) include `prompt`, `response`, `messages`, `body`: audit details for capture use counts and ids only.
- Extraction runs on the parsed document BEFORE `drop_body_fields`, and the dropped values are released before publish; keep the parsed body out of exceptions and logs (the request body may be logged by nothing; check `observability` filters).
- Capture must not make ingest slower when off: the branch is one attribute check when no pipeline is attached.
- `otlp_mapping.py` belongs to PRP-100 in this wave: attach `payload_ref` in `service.py` on the mapped `TelemetryEvent` (copy with update), never in the mapping.
- Adding the `interactions` builder changes `default_builders`: update `services/api/tests/runtime_api/test_readiness.py`, `services/api/tests/runtime_gateway_builder/test_gateway_builder.py` and `services/api/tests/runtime_data/data_helpers.py`.
- Key Vault calls per captured interaction may be throttled (limits verified in PRP-102 item 1): bounded in-flight work plus shedding is the protection; never queue content in memory unbounded.
- Synthetic content only: canaries are generated per test (`NSCANARY-<uuid>`); credential-shaped values are built at runtime.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/ingest/service.py
  - services/api/neurosphere_api/ingest/capture.py
  - services/api/neurosphere_api/runtime/builders/interactions.py
  - services/api/neurosphere_api/admin/capture/**
  - packages/core/neurosphere_core/interactions/__init__.py
  - packages/core/neurosphere_core/interactions/policy.py
  - packages/core/neurosphere_core/interactions/policy_store.py
  - packages/core/neurosphere_core/interactions/capture.py
  - packages/core/tests/interaction_capture_policy/**
  - services/api/tests/interaction_capture_edge/**
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/tests/runtime_gateway_builder/test_gateway_builder.py
  - services/api/tests/runtime_data/data_helpers.py
  - tests/security/capture_guards/**
  - tests/security/authz/test_capture_admin.py
  - services/workers/tests/lifecycle_interactions/test_factory_wiring.py
  - frontend/src/features/admin/capture/**
  - frontend/tests/mock-api/features/capture.ts
  - frontend/tests/e2e/admin-capture/**
  - docs/runbooks/interaction-audit.md
  - docs/security/threat-model.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/features/admin/shared/areas.ts
  - frontend/src/features/admin/routes.tsx
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/core/neurosphere_core/payload/**
  - packages/core/neurosphere_core/audit/**
  - packages/core/neurosphere_core/classification/**
  - packages/core/neurosphere_core/crypto/**
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - services/api/neurosphere_api/ingest/router.py
  - services/api/neurosphere_api/ingest/bootstrap.py
  - services/workers/neurosphere_workers/ingestion/**
  - services/workers/neurosphere_workers/quarantine/**
  - services/workers/neurosphere_workers/archive/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - packages/core/neurosphere_core/actions/targets.py
  - packages/contracts/**
```

## Implementation blueprint

Parallelization: items 1 and 2 [P]; item 3 after both; item 4 after 3; item 5 after 1 and 4; item 6 after 4; item 7 `[serial-after: PRP-107]`; item 8 last. W22 merge order: PRP-107 merges before PRP-103's item 7 (the last code item; item 8 is close-out), because PRP-107 owns `runtime/factories.py`; nothing in PRP-107 is `[serial-after: PRP-103]`, so there is no cycle.

### Item 1 - Capture policy store, matcher and governed change functions  [P]
- Deliverable: `interactions/policy.py` and `policy_store.py`: policy model bound to PRP-99's `capture-policy`, Cosmos and in-memory stores over `interaction_capture_policies` with ETag versions, the matcher (stored setting on, retention opt-in, active, approved audit id present, source and domain match, deterministic sampling), `apply_capture_policy_change` and `read_back_capture_policy` audited through `run_audited_mutation`, and `seed_local_capture_policy` that refuses unless `NS_ENV=local`.
- Owned files: `interactions/{policy,policy_store}.py`, `packages/core/tests/interaction_capture_policy/**`.
- Must NOT touch: `actions/targets.py` (PRP-108 adds the kind to `ACTION_CONNECTORS`).
- Depends on: PRP-99, PRP-102.
- Acceptance criteria: criterion 8; every off reason is a distinct code (`setting_off`, `retention_not_enabled`, `no_policy`, `not_approved`, `source_mismatch`, `domain_mismatch`, `domain_missing`, `not_sampled`).
- Tests: `packages/core/tests/interaction_capture_policy/test_matcher.py`, `test_apply_and_read_back.py`, `test_local_seed_refused.py`.
- Pattern references: `audit/repository.py:247-270`, `mcp/cosmos_store.py:86-140`.

### Item 2 - Body extraction and the capture pipeline  [P]
- Deliverable: `interactions/capture.py`: `extract_body_parts` (iterative, per OTLP span and per CloudEvent telemetry item, mapping per row 6, size caps from the content envelope, values never in errors), `CapturePipeline` (redact with PRP-101, refuse on `RedactionFailed`, seal and store with PRP-102, build `payload_ref` and the index record with findings summary, index-only record on failure, bounded in-flight semaphore and shed).
- Owned files: `interactions/capture.py`, `interactions/__init__.py` (exports), tests in `packages/core/tests/interaction_capture_policy/test_pipeline.py`.
- Must NOT touch: `payload/guard.py`.
- Depends on: PRP-101, PRP-102.
- Acceptance criteria: criteria 3, 4, 5, 6 at unit level with in-memory store and local key wrapper.
- Tests: `packages/core/tests/interaction_capture_policy/test_pipeline.py`, `test_extract.py`.
- Pattern references: `payload/guard.py:67-104`.

### Item 3 - The edge branch
- Deliverable: `ingest/service.py` gains `attach_capture` and, in the OTLP traces and CloudEvents telemetry paths only, the capture step between parse and drop; the mapped `TelemetryEvent` gets `payload_ref` before `_telemetry_message`; `ingest/capture.py` holds the per-request adapter and counters. With no pipeline attached the code path is unchanged.
- Owned files: `services/api/neurosphere_api/ingest/{service,capture}.py`, `services/api/tests/interaction_capture_edge/**`.
- Must NOT touch: `otlp_mapping.py`, `router.py`, `bootstrap.py`, `limits.py`.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 1-6 through `IngestService` with a fake publisher.
- Tests: `services/api/tests/interaction_capture_edge/test_edge_capture.py`, `test_capture_off_identical.py`, plus `services/api/tests/ingest`.
- Pattern references: `ingest/service.py:184-196` (`_finish`).

### Item 4 - Composition builder and status
- Deliverable: `runtime/builders/interactions.py`: builds the store (Cosmos and blob on the shared clients; in-memory and local key only under `NS_ENV=local`), the key wrapper from `InteractionSettings`, the detector set, the policy store and matcher; attaches the pipeline to `app.state.ingest_service` in an `on_startup` hook; reports `interaction_capture` ok, or disabled with the off reason; registered in `default_builders`.
- Owned files: `runtime/builders/interactions.py`, the three pinned builder tests, `runtime/status.py` (append), `runtime/builders/__init__.py` (append).
- Must NOT touch: `builders/data.py`, `builders/edge.py`, `main.py`.
- Depends on: item 3.
- Acceptance criteria: missing Key Vault or blob configuration outside local reports `disabled` with a reason and ingest still serves; existing `runtime_api`, `runtime_routes`, `runtime_data` pass.
- Tests: `services/api/tests/interaction_capture_edge/test_builder.py`; re-run `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`, `runtime_gateway_builder`.
- Pattern references: `runtime/builders/edge.py`.

### Item 5 - Read-only admin API and page
- Deliverable: `admin/capture/` router and service for the three routes; `frontend/src/features/admin/capture/` page (policy list, detail, status with off reasons and counters, a note that changes are proposed as `capture_policy_change` actions and execute once PRP-108 ships); mock-api feature; e2e and a11y sample.
- Owned files: `services/api/neurosphere_api/admin/capture/**`, `frontend/src/features/admin/capture/**`, `frontend/tests/mock-api/features/capture.ts`, `frontend/tests/e2e/admin-capture/**`, Tier-2 lines.
- Must NOT touch: `frontend/src/app/Shell.tsx`, `frontend/tests/mock-api/server.ts`.
- Depends on: items 1 and 4.
- Acceptance criteria: criterion 9; no route writes.
- Tests: `services/api/tests/interaction_capture_edge/test_admin_routes.py`, `tests/security/authz/test_capture_admin.py`, `frontend/src/features/admin/capture/*.test.tsx`, `frontend/tests/e2e/admin-capture/capture.spec.ts`.
- Pattern references: `admin/sources/producers/router.py`, `frontend/src/features/admin/sources/routes.tsx`.

### Item 6 - Guard negative suite
- Deliverable: `tests/security/capture_guards/`: one test per guard with capture ON (contract rejects any content field; edge messages; worker pipeline on the published bytes; quarantine; archive `redact_record`; audit seal of every record the capture path writes; SIEM `to_siem_event`; caplog over all loggers), each also run with capture OFF; plus a test that the published message bytes with capture OFF equal a golden run with no pipeline attached.
- Owned files: `tests/security/capture_guards/**`.
- Must NOT touch: worker or audit source.
- Depends on: item 4.
- Acceptance criteria: criterion 7.
- Tests: `tests/security/capture_guards/test_six_guards.py`, `test_siem_and_logs.py`, `test_off_is_identical.py`.
- Pattern references: `tests/security/authz/test_admin_producers_secrecy.py`.

### Item 7 - Worker lifecycle target wiring  [serial-after: PRP-107]
- Deliverable: after PRP-107 (W22 owner of `workers/runtime/factories.py`) has merged and this branch is rebased, pass the interaction index container and content blob container to `build_targets` in `_lifecycle_targets` (`factories.py:735-761`), each registered only when configured, as the archive is.
- Owned files: the `_lifecycle_targets` lines of `services/workers/neurosphere_workers/runtime/factories.py`, `services/workers/tests/lifecycle_interactions/test_factory_wiring.py`.
- Must NOT touch: any other function in `factories.py`.
- Depends on: item 4; PRP-107 merged.
- Acceptance criteria: with the settings unset the registry is as today; with them set the `interaction_content` target is registered; `services/workers/tests/lifecycle_worker` passes.
- Tests: `services/workers/tests/lifecycle_interactions/test_factory_wiring.py`, `services/workers/tests/lifecycle_worker`.
- Pattern references: `factories.py:735-761`.

### Item 8 - Integration and close-out
- Deliverable: `docs/security/threat-model.md` rows for the capture path (information disclosure, tampering of policy, repudiation of reads, denial of service by capture) beside row `:190`; runbook sections (turning capture on, off reasons, counters, shedding, what is never stored); Tier-2 lines; Tier-3 regeneration; changelog fragment; completion note with env vars and the product check (capture cannot be turned on outside local until PRP-108).
- Owned files: threat model rows, runbook, Tier-2 lines, this PRP file, changelog fragment, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## How the hard constraints are kept
- Authorization on every path: no route reads content; the admin routes need `config.manage`; capture policy changes have no route and go through the executor (PRP-108).
- Same executor for button, chat and MCP: `capture_policy_change` is an action kind; this PRP ships only apply and read-back for it.
- No secrets in files, prompts or logs: credentials placeholdered before encryption, never stored, hashed or logged; key ids only.
- Never bridge Government to Commercial: the key wrapper refuses another cloud's vault host; no external detector is called.
- Synthetic data only in tests and demos.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/interaction_capture_policy services/api/tests/interaction_capture_edge services/api/tests/ingest services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/authz tests/security/capture_guards tests/security/authz services/workers/tests/lifecycle_interactions services/workers/tests/lifecycle_worker services/workers/tests/ingestion services/workers/tests/quarantine services/workers/tests/archive tests/integration/ingestion services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New container documents only (capture policies) and, when capture is on, new interaction records. Off by default at four levels (stored setting, retention opt-in, approved policy, source and domain match). To stop capture: disable the `interaction_capture` stored setting (restart) or set `retain_prompt_response_bodies` false; already stored content expires through its retention rule or is purged through the lifecycle API. Reverting the PR restores today's edge exactly; stored content stays encrypted and is purged through PRP-102's lifecycle target.

## Live and open gates
None here. Capture end to end on the hosted app (synthetic domain only, enabled by the approval action) is PRP-109, evidenced by PRP-136 with `NS_LIVE_APPROVED=1`; OPEN until then.

## NOT building
- A settings toggle or API route that turns capture on; any capture outside an approved policy.
- Capture from SaaS assistants, the agent SDK or gateway logs (PRP-111, PRP-122 to PRP-125; per-prompt SaaS content only where a vendor API exposes it, design section 8 item 3).
- Detection of names, addresses or free-text sensitive content ("structured identifiers only", design section 8 item 4).
- Endpoint, browser or network DLP; blocking inside third-party SaaS; any Purview parity claim (design section 8 items 1, 2, 5).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1-4 are GD decisions made 2026-11-16; rows 5-9 are ASSUMPTIONS)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | serial-after PRP-107 |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
