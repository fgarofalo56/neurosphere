---
name: PRP-50-connector-sdk-and-data-path-follow-ups
status: backlog
priority: P2
order: 38
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 2
ns: NS-09, NS-01
depends_on: []
wave: W16
branch: prp-50-connector-followups
allow_parallel: true
issues: [244, 218, 219]
---

# PRP-50: Connector SDK and data-path follow-ups

## Goal
Clear the non-blocking findings the independent reviewers filed against PRP-09 round 2 (issues #218 and #219) so the connector layer is safe to build on. The data-path connectors get their one security fix (the OTel connector accepts `evilvault.azure.net` as a Key Vault host), an export-versus-shutdown race fix, a stalled gateway-poll slice that is visible instead of reading as `partial` forever, a restated billing day that is detected instead of silently ignored, and Foundry discovery that reports project collisions and validates its domain. The SDK gets sharper write verification, a public capability check, a shared health-tracking decorator in place of two copies, and a contract kit that names what is missing. It is for connector authors and for operators who rely on the gateway poll, billing export and discovery roles. It runs in W16; items that edit files PRP-46 owns in W15 are sequenced after it.

Out of scope: hosted wiring of the `foundry_discovery` and `billing_export` roles and the G04 live gate script (PRP-58, issue #220); the G04 live run (PRP-64); a ledger supersede concept for restated invoiced amounts (PRP-07 territory, filed as a follow-up); a new Foundry deployment id scheme that includes the project (PRP-17 swap targets use the current scheme); the reconciliation granularity label for request-less billing (#218 item 10: the aggregate model belongs to PRP-49 this wave, filed as a follow-up); persisting the billing checkpoint (#218 item 9, not needed at current volume, left on the issue); `.env.example` edits (operator).

## Why
- `connectors/reference/otel-generic/neurosphere_connector_otel_generic/connector.py:79-81,111-114` keys `_CLOUD_BY_VAULT_HOST` on bare `vault.azure.net` and tests `host.endswith(suffix)`, so `evilvault.azure.net` matches; the SDK does it right with a leading dot (`connectors/sdk-python/neurosphere_connector/manifest.py:82`). Since #49 removed the commercial fallback this is the only guard (#218 item 1).
- `ConnectorSpanExporter.export` reads `self._closed` outside the lock and `shutdown` sets it after the flush (`otel-generic/neurosphere_connector_otel_generic/exporter.py:41-77`), so an export racing a shutdown can enqueue after the flush and fail by timeout (#218 item 5).
- `AzureMonitorConnector.poll` reports `stalled_slice_start` (`connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/connector.py:119,314`), but `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:60-70,311-326` only knows `ok`, `partial` and `rate_limited`: a permanently truncated slice holds the watermark and reads as `partial` forever (#218 item 2). Slice halving tests `halved < MIN_SLICE or page_end - cursor <= MIN_SLICE` (`connector.py:278-284`), so a clipped final slice can retry at a length that does not shrink it (#218 item 3).
- `BillingExportPoller` ids exclude the amount (`ingestion/billing_export/runner.py:121-160`), so a restated closed day keeps the first amount and nothing says so (#218 item 8); `foundry_discovery/poller.py` creates `model_deployment` ids without the project (`:_deployment`), so two projects with one deployment name collide and the second is dropped without a trace (#219 item 6).
- `FoundryDiscoveryPoller.__init__` accepts any `domain_id`; nothing checks it carries the runtime cloud and customer (#219 item 7). Discovered names are logged at info level (`poller.py` capabilities log) (#219 item 8).
- SDK write verify: `_strict_equal` makes `1` and `1.0` a mismatch (`connectors/sdk-python/neurosphere_connector/write/write_models.py:121-131`), `move` and `copy` without `from_` return plain `matched=False` (`:178-179`), `contract_kit.py:20,89-94` imports the private `_check_capable` and catches `AttributeError` without naming the member; `_tracked` is duplicated in `apim-gateway/.../connector.py:166` and `foundry-actions/.../connector.py:131` (#219 items 1-3, 9-11).

## Acceptance criteria
- [ ] Given a vault reference whose host is `evilvault.azure.net`, `x.vault.azure.net.evil.test` or `vault.azure.net`, When the OTel connector builds its manifest, Then it raises `unrecognized_vault_host`; `ns.vault.azure.net` and `ns.vault.usgovcloudapi.net` map to commercial and government (#218 item 1).
- [ ] Given an export racing `shutdown`, When both run on separate threads in a stress test, Then no export is enqueued after the flush and none fails by timeout; the closed check and the pending registration happen under one lock (#218 item 5).
- [ ] Given an export with an empty producer credential, When it reaches the in-process ingest edge, Then the edge answers 401 and the connector reports a failure, not a success (#218 item 7); the collector configuration test asserts that the config drops request and response bodies (config parse test, #218 item 6).
- [ ] Given a gateway poll whose source reports `stalled_slice_start`, When the poller records the outcome, Then `poll_status` is a distinct `stalled` value with the stalled slice start in the log fields and the watermark still held (#218 item 2).
- [ ] Given a final slice clipped by the window end, When the connector retries after truncation, Then it halves from the actual clipped span and does not spend page budget on a retry that cannot shrink it (#218 item 3, reproduced by a test before the fix; if it is not reproducible the finding is recorded as such). The meaning of `truncated_pages` (truncated source queries) is stated in the connector README and in the poller log field name (#218 item 4).
- [ ] Given a closed billing day posted earlier, When a later export reports a different amount for the same day, resource and meter, Then the poller counts it in `last_status.restated`, logs `billing_export.restated` with the counts only, still posts nothing for it (first amount wins, unchanged), and the docstring points to the ledger supersede follow-up (#218 item 8).
- [ ] Given two Foundry projects with a deployment of the same name, When discovery ticks, Then the second is counted in `TickStats.collisions` and logged once per tick with the project names, and no existing entity is modified (#219 item 6; the id scheme is not changed).
- [ ] Given a `domain_id` that does not start with the poller's `cloud:customer:` prefix, When `FoundryDiscoveryPoller` is constructed, Then it raises `InvalidSchemaError` (fails closed at build, #219 item 7); discovered names are logged at debug level only and remaining attribute lengths are capped like the others (#219 item 8).
- [ ] Given `check_diff_against_state` with an observed `1.0` for an expected `1`, Then the result is a documented, tested outcome (decision in Clarification 4); `move` and `copy` without `from_` return `verifiable=False` with reason `missing_from`; `MappingProxyType` observed states and `remove` on a missing parent path have tests (#219 items 1-3).
- [ ] `check_capable` is a public name exported from `neurosphere_connector.write`; the contract kit imports it and names the missing member in `write_protocol_missing` (#219 items 9-10); the private alias keeps working until no caller uses it.
- [ ] `tracked` (health recording decorator) lives in the SDK; both reference connectors import it and their local copies are gone with their tests unchanged (#219 item 11).
- [ ] A test pins that a health success arriving while the rate-limit window is open keeps `remaining=0` until the next success (#219 item 4); the claim that hosts call `drain_rotation_hooks` is checked and the result recorded: if no host calls it, the completion note says so and a follow-up issue is filed (#219 item 5), no host code is invented.
- [ ] Hosted wiring and the G04 live run are written OPEN (PRP-58, PRP-64).
- [ ] PRP exit: touched suites pass, `verify-gates.ps1 -Mode full` green, `python scripts/validate_planning.py` passes; #218 and #219 are closed only if every bullet is fixed or recorded as justified.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required | sonnet, review required: one item is a security fix and several touch ingest paths |
| 2 | Billing restatement | Add a ledger supersede now; detect and surface | Detect and surface only. A supersede concept changes ledger identity and belongs to the ledger owner; the first amount keeps winning and the follow-up is filed |
| 3 | Foundry deployment id collision | Include the project in the id; detect and count | Detect and count (the id scheme matches PRP-17 swap targets, changing it needs the PRP-17 owner); the id decision is recorded as a follow-up |
| 4 | `1` versus `1.0` in write verify | Treat as equal; keep strict and document | ASSUMPTION: keep the strict comparison (a false negative is the safe direction) and add an explicit per-connector opt-in `numeric_equivalence` parameter to `check_diff_against_state`, default off; reference connectors keep the default |
| 5 | Where gateway poll and Azure Monitor edits sit | Inside this wave; after PRP-46 | After PRP-46 (it owns both in W15): items 2 and 3 are `[serial-after: PRP-46]` and start only after it has merged and this branch is rebased |
| 6 | Paths named in the assignment | As written; corrected | The worker roles live under `services/workers/neurosphere_workers/ingestion/foundry_discovery/` and `.../billing_export/` (the assignment's `neurosphere_workers/{foundry_discovery,billing_export}` does not exist); ownership uses the real paths |
| 7 | `NS_FOUNDRY_DISCOVERY_DOMAIN_ID` validation | In the builder; in the poller constructor | In the poller constructor, so no edit to `runtime/factories.py` (PRP-45 owns builder bodies this wave); the builder fails closed because construction raises |
| 8 | Stalled status value | New constant; reuse `partial` | New `STATUS_STALLED = "stalled"` (fits `poll_status` max length 64, `gateway/models.py:163`) |
| 9 | Drain hook check | Add a host that calls it; record | Record only: no host exists in the tree that calls `drain_rotation_hooks` (only tests do); a host is a design item, not a nit |

## Context manifest

### Files to read first
- `connectors/reference/otel-generic/neurosphere_connector_otel_generic/{connector.py,exporter.py}` - vault host table and the exporter lock.
- `connectors/reference/otel-generic/tests/test_otel_generic_hardening.py`, `test_otel_generic_collector_config.py` and `tests/integration/connectors/test_otel_generic_ingest.py` - existing hardening and edge tests.
- `connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/connector.py:74-125,215-320` - slice halving, `PollResult`, `stalled_slice_start`.
- `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:60-70,255-330,415-440` - statuses and outcome recording.
- `services/workers/neurosphere_workers/ingestion/billing_export/runner.py` - key, record mapping, `TickStatus`.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/{poller,settings}.py` - id scheme, `TickStats`, logging.
- `connectors/sdk-python/neurosphere_connector/write/{write_models,write_registry,write_protocol}.py`, `contract_kit.py`, `health.py` - the SDK pieces.
- `connectors/reference/{apim-gateway,foundry-actions}/**/connector.py` (`_tracked`) and their tests.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py` - the kit run against reference connectors.
- `services/workers/tests/{gateway_poll,billing_export_role,foundry_discovery_role}/` - existing role tests.

### Interfaces consumed
- `neurosphere_connector` SDK public API (PRP-09, shipped); `GatewayRegistration.poll_status` (`packages/core/neurosphere_core/gateway/models.py:163`, free string up to 64 chars).
- `CatalogRepository.get_entity/create_entity` (PRP-10), the ingest edge (PRP-07), `CostRecord` and `TelemetryEvent` contracts (PRP-01).
- PRP-46 (W15): the final shape of `gateway_poll/**` and `connectors/reference/azure-monitor/**` before items 2 and 3 start.

### Interfaces provided
- `neurosphere_connector.write.check_capable` (public) and `neurosphere_connector.health.tracked` (new names; PRP-58 and later connectors import them).
- `STATUS_STALLED` in `gateway_poll` and the `stalled` value of `poll_status` (PRP-53/57 admin pages may display it).
- `TickStatus.restated` (billing) and `TickStats.collisions` (discovery) counters for operator surfaces.
- `check_diff_against_state(..., numeric_equivalence=False)` optional parameter.

### Patterns to match
- Suffix matching with a leading dot: `connectors/sdk-python/neurosphere_connector/manifest.py:82`.
- Counters in a per-tick status dataclass: `billing_export/runner.py` `TickStatus`, `foundry_discovery/poller.py` `TickStats`.
- Lock-guarded close flag: `exporter.py:32-48` (`_lock`, `_pending`).
- Contract kit violation style: `contract_kit.py:80-95`.
- Logging with `extra={"event": ...}` and counts only: `billing_export/runner.py` tick logs.

### Gotchas
- CodeQL fails PRs on hostname substring checks without a leading dot and on PEP 695 generics in nested functions; `tracked` keeps the `_F -> _F` TypeVar form with the `noqa: UP047` comment used today.
- Never log a credential, a vault URL path or a name that looks like a secret; log counts and reason codes.
- Do not change the billing ids or the dedupe key (they exclude the amount on purpose).
- `pyproject.toml`, `uv.lock` and Dockerfiles are off limits: the reference connectors already depend on the SDK, so moving `tracked` adds no dependency.
- The compose OTel integration test is marked `integration` and is skipped by the CI python job; use the in-process edge test for the 401 case and say so.
- Same-named test directories shadow each other: new test files go in the existing directories above, and suites run together.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/**
  - tests/integration/connectors/**
  - tests/unit/connector_conformance/**
  - services/workers/neurosphere_workers/ingestion/foundry_discovery/**
  - services/workers/neurosphere_workers/ingestion/billing_export/**
  - services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py
  - services/workers/tests/foundry_discovery_role/**
  - services/workers/tests/billing_export_role/**
  - services/workers/tests/gateway_poll/**
tier1: []
tier2_appends: []
must_not_touch:
  - pyproject.toml
  - uv.lock
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/settings.py
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/neurosphere_core/ledger/**
  - infra/**
  - docker-compose.yml
```

## Implementation blueprint

Order: items 1, 3, 4 and 5 are independent `[P]` (no shared file); item 2 waits for PRP-46; item 6 follows 5 (both edit the reference connectors' write files? no: item 5 edits the SDK, item 6 edits the two reference connectors and imports the new names); item 7 last.

### Item 1 - OTel connector security and race fixes  [P]
- Deliverable: leading-dot vault host matching; one lock around the closed check and pending registration with `shutdown` closing under the same lock; tests for the 401 on an empty credential and a collector-level body-drop assertion.
- Owned files: `connectors/reference/otel-generic/**`, `tests/integration/connectors/test_otel_generic_ingest.py`.
- Must NOT touch: `connectors/sdk-python/**`, the collector compose file's ports.
- Depends on: none.
- Acceptance criteria: the three OTel criteria above; existing hardening and mapping tests pass.
- Tests: `connectors/reference/otel-generic/tests/test_otel_generic_hardening.py` (extend), `test_otel_generic_collector_config.py` (extend), `tests/integration/connectors/test_otel_generic_ingest.py`.
- Pattern references: `sdk-python/neurosphere_connector/manifest.py:82`, `exporter.py:32-70`.

### Item 2 - Stalled slice and slice halving  [serial-after: PRP-46]
- Deliverable: `STATUS_STALLED` and its recording in `gateway_poll/poller.py` from `PollResult.stalled_slice_start`; slice halving from the actual clipped span in the Azure Monitor connector; README text on `truncated_pages`.
- Owned files: `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py`, `connectors/reference/azure-monitor/**`, `services/workers/tests/gateway_poll/**`.
- Must NOT touch: `gateway_poll/settings.py`, `gateway_poll/__init__.py` exports beyond the new constant, ingestion pipeline code.
- Depends on: PRP-46 merged; rebase first and re-read both files.
- Acceptance criteria: the stalled and halving criteria above; existing watermark-semantics tests pass.
- Tests: `services/workers/tests/gateway_poll/test_gateway_poll.py` (extend), `connectors/reference/azure-monitor/tests/test_azure_monitor_polling.py` and `test_watermark_semantics.py` (extend).
- Pattern references: `connector.py:215-320`, `poller.py:60-70,311-326`.

### Item 3 - Billing restatement surfaced  [P]
- Deliverable: an in-memory map of posted closed-day keys to amounts in `BillingExportPoller`; a changed amount increments `restated` and logs counts; docstring updated; no change to ids or posting.
- Owned files: `services/workers/neurosphere_workers/ingestion/billing_export/runner.py`, `services/workers/tests/billing_export_role/**`.
- Must NOT touch: `settings.py` behaviour, `ledger/**`, `aggregates/**`.
- Depends on: none.
- Acceptance criteria: the restatement criterion above; an unchanged re-read leaves `restated == 0` and still posts nothing new.
- Tests: `services/workers/tests/billing_export_role/test_runner.py` (extend), `test_end_to_end.py` unchanged.
- Pattern references: `runner.py` `tick` and `TickStatus`.

### Item 4 - Foundry discovery collisions and domain validation  [P]
- Deliverable: collision detection on existing `model_deployment` entities created from another project, constructor validation of `domain_id`, debug-level name logging, consistent attribute caps.
- Owned files: `services/workers/neurosphere_workers/ingestion/foundry_discovery/**`, `services/workers/tests/foundry_discovery_role/**`.
- Must NOT touch: `runtime/factories.py`, the `neurosphere_connector_foundry` package behaviour.
- Depends on: none.
- Acceptance criteria: the collision and domain criteria above; creation and never-update behaviour unchanged.
- Tests: `services/workers/tests/foundry_discovery_role/test_poller.py` (extend), `test_role_config.py`.
- Pattern references: `poller.py` `_ensure` and `TickStats`.

### Item 5 - SDK write verify, public capability check and contract kit  [P]
- Deliverable: `numeric_equivalence` option, `missing_from` reason, `check_capable` public export with the private alias kept, the kit naming the missing member, new tests.
- Owned files: `connectors/sdk-python/**`, `tests/unit/connector_conformance/**`.
- Must NOT touch: `connectors/reference/**`, `connectors/sdk-ts/**`.
- Depends on: none.
- Acceptance criteria: the three SDK write criteria above; the conformance suite still passes for every reference connector.
- Tests: `connectors/sdk-python/tests/write/test_write_connector.py` (extend), `tests/test_contract_kit.py`, `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- Pattern references: `write_models.py:121-190`, `contract_kit.py:80-95`.

### Item 6 - Shared `tracked`, health pin and drain-hook finding
- Deliverable: `tracked` in the SDK `health.py` (exported), both reference connectors switched, the rate-limit window health test, and a recorded finding on `drain_rotation_hooks`.
- Owned files: `connectors/sdk-python/neurosphere_connector/health.py`, `connectors/sdk-python/neurosphere_connector/__init__.py`, `connectors/sdk-python/tests/test_connector_health.py`, `connectors/reference/apim-gateway/**`, `connectors/reference/foundry-actions/**`.
- Must NOT touch: connector behaviour or manifests, `write_registry.py` (item 5).
- Depends on: item 5 (shared SDK package).
- Acceptance criteria: the `tracked` and health criteria above; apim-gateway and foundry-actions suites pass unchanged.
- Tests: `connectors/sdk-python/tests/test_connector_health.py`, `connectors/reference/apim-gateway/tests`, `connectors/reference/foundry-actions/tests`.
- Pattern references: `apim-gateway/.../connector.py:166-186`.

### Item 7 - Integration and close-out
- Deliverable: cross-suite run, completion note with follow-up issues (ledger supersede, deployment id scheme, reconciliation granularity label, billing checkpoint persistence, drain-hook host), regenerated Tier-3 files, #218 and #219 closed or left open with a comment per unfixed bullet.
- Owned files: this PRP file, regenerated `PRPs/PRP-MASTER-neurosphere.md` status table and `PRPs/INDEX.md`.
- Must NOT touch: `docs/RESEARCH-AND-GATES.md` (G04 row stays OPEN, PRP-64).
- Depends on: items 1-6.
- Acceptance criteria: gates below pass; hosted wiring and G04 written OPEN.
- Tests: none new.
- Pattern references: `PRPs/reference/parallel-build-reference.md` section 6.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/sdk-python/tests connectors/reference/otel-generic/tests connectors/reference/azure-monitor/tests connectors/reference/apim-gateway/tests connectors/reference/foundry-actions/tests tests/unit/connector_conformance tests/integration/connectors services/workers/tests/gateway_poll services/workers/tests/billing_export_role services/workers/tests/foundry_discovery_role services/workers/tests/worker_roles
python scripts/prp_status.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```
`tests/integration/connectors/test_otel_collector_compose.py` is `integration`-marked and needs `docker compose up -d --wait` (`127.0.0.1`); report it as not run if the stack is down.

## Migration and rollback
No data or schema migration. `poll_status` gains one more string value (`stalled`) on an existing free-text field; admin pages that switch on the value must treat unknown values as plain text. `TickStatus`, `TickStats` and the SDK signatures gain optional members with defaults. Rollback is reverting the branch; the private `_check_capable` alias and the old `_tracked` call sites keep working until the last item removes them, so a partial revert is safe.

## Live and open gates
- G04 live run (Azure Monitor, Foundry discovery, billing export, Commercial): OPEN, needs `NS_LIVE_APPROVED=1` and operator approval; handed to PRP-64 with the script from PRP-58.
- Hosted wiring (Bicep, App Service, Helm) for `foundry_discovery`, `billing_export` and the OTel profile: OPEN, PRP-58 (issue #220).
- Behaviour of a stalled slice, a billing restatement and a project collision against real services: unverified until the live run.

## NOT building
- A ledger supersede concept, a new Foundry deployment id scheme, or any change to billing ids and dedupe keys.
- Persistent billing checkpoints, a reconciliation `day_resource` label, or aggregate model changes.
- A host that drains rotation hooks, the TypeScript SDK changes, or new connectors (AWS Bedrock is PRP-62).
- Hosted infrastructure, workflow or gate-script changes.
- Any new dependency.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 4 is a labelled assumption)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-50-connector-followups | commit 8bb3ec50 |
| 2 | todo | | blocked on PRP-46 merge |
| 3 | merged | prp-50-connector-followups | restated counter |
| 4 | merged | prp-50-connector-followups | collisions, domain check |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date, PR, merged commits:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (G04 live, hosted wiring):
- Env vars for the operator (none expected):
- Follow-up issue numbers (ledger supersede, deployment id scheme, reconciliation label, checkpoint persistence, drain-hook host):
- Product check (are stalled polls, restated billing days and discovery collisions visible without reading logs?):
