---
name: PRP-46-cost-center-attribution-and-ingest-follow-ups
status: backlog
priority: P1
order: 33
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions]
wave: W15
branch: prp-46-cost-center
allow_parallel: true
issues: [239, 190, 148, 179, 167, 168, 169]
---

# PRP-46: Cost-center attribution and ingest follow-ups

## Goal
Make the cost center that the APIM gateway already emits (`x-ns-cost-center` on `llm-emit-token-metric`, carried by the poller as the `nscostcenter` CloudEvent extension) survive ingest and reach the cost ledger, where it can be filtered, instead of being dropped at the edge. It also closes the small ingest and gateway follow-ups that were filed against PRP-07, PRP-33 and PRP-34: one-time counter creation, a visible count of non-billing invoiced records the outbox drops, consistent reason families, gateway inventory hardening, visible attribution loss on the gateway record, and three PRP-34 leftovers on the APIM write path. It is for FinOps users and stewards who need spend by cost center, and for operators who need to see when attribution is silently lost. It is `review: required` because it changes the ledger entry shape and an authorization boundary (the MCP and grant publication-record permission).

Out of scope: the `CostRecord.tags` schema itself (PRP-37, merged earlier); dashboards and finops routes that group by cost center (follow-up issue: `finops` is PRP-21's and `dashboards/router.py` is PRP-48's in this wave); Government attribution (no verified App Insights host, #179 item 3, operator); the `Subscription ID` dimension live check and the G17 observe rerun (#179 item 4, #148 item 6, PRP-64); `.env.example` names (#148 item 3, agent-blocked, listed under "Env vars for the operator"); gateway inventory chunking for very large APIM instances (follow-up issue, see Clarifications 7); connector SDK and billing-export internals (PRP-50); producer registry and `ingest/{auth,bootstrap}.py` (PRP-41).

## Why
- `IngestService._cloudevent_message` validates the cost data and never looks at extensions other than `nsrequestid` (`services/api/neurosphere_api/ingest/service.py:308-355`, `ingest/cloudevents.py:20-40`); telemetry events are built by `_telemetry_message` with no extension read (`service.py:158-169`). The poller sets `nscostcenter` (`gateway_poll/poller.py:75,178-190`) and the value is discarded (#190, #178 duplicate).
- `HubMessage` is `extra="forbid"` with no field for it (`packages/core/neurosphere_core/payload/wire.py:30-45`), `Observation` and `LedgerEntry` have none (`packages/core/neurosphere_core/ledger/models.py:123-146,174-210`), and `LedgerFilters` cannot filter on it (`ledger/totals.py:50-65`).
- `CostCenterIndex.lookup` falls back from the (ApiId, ApimSubscriptionId) key to the subscription alone with no record of which was used, and `_cost_centers` swallows a failure with only a log line (`connectors/reference/azure-monitor/.../gateway_mapping.py:135-175`, `poller.py:327-356`); `GatewayRegistration.poll_status` is a single code (`packages/core/neurosphere_core/gateway/models.py:163`) (#179 items 1 and 2).
- `ARM_ID_PATTERN` accepts a resource group named `..` (`gateway/models.py:70`) and `GatewayService._record_failure` swallows every exception (`services/api/neurosphere_api/gateway/service.py:254-263`) (#148 item 2).
- `process_batch` creates the duplicates counter on every batch (`services/workers/neurosphere_workers/ingestion/pipeline.py:242-244`); `_map_cost` returns `None` for a non-billing invoiced record with no signal (`projections/outbox/mapping.py:120-126`); `claim_mismatch` on `observation_source` is a whole-request 403 while `invoiced_not_billing` is a per-item mapping error (`ingest/service.py:339-346`) (#167, #168, #169).
- PRP-34 leftovers verified in code: the create step PUTs with `if_match=None` (`connectors/reference/apim-gateway/.../applier.py:163-172`, `arm.py:293-305`); the grant recorder has no stale-intent guard that the MCP recorder has (`services/workers/neurosphere_workers/publication/mcp.py:160-185` versus `publication/grant.py:70-90,129`); `publication-record` for MCP needs `action.propose` while the grant record route needs `catalog.curate` (`catalog/mcp_publish.py:146,504-510` versus `catalog/grant_publish.py:101,355`).

## Acceptance criteria
- [ ] Given a cost CloudEvent with extension `nscostcenter: "CC-4410"`, when ingested, then the stored `HubMessage` data carries `tags.cost_center == "CC-4410"` and `HubMessage.cost_center == "CC-4410"`; given a telemetry CloudEvent with the extension, `HubMessage.cost_center` is set (telemetry has no tags field) (#190 items 1 and 3).
- [ ] The extension value is stripped of control characters, must match `^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$` (the Grant pattern), and `N/A` or empty is treated as absent; an invalid value never rejects the event, is not stored, and the value is never logged (#190 item 3).
- [ ] Given a cost record that already carries `tags.cost_center` and a different extension value, the record's own tag wins and the mismatch is counted, not rejected.
- [ ] Given a `HubMessage` with `cost_center`, the outbox mapping puts it on the `Observation`; `LedgerEntry.cost_center` is set when every observation of the request agrees or only one carries it, and is `None` when two observations disagree (never a guess) (#190 ledger bullet).
- [ ] `LedgerFilters(cost_center="CC-4410")` and `StoreLedgerReader.totals` filter on it; entries stored before this change still load with `cost_center=None`.
- [ ] A gateway `model_call` telemetry event for a Commercial priced model yields an estimated ledger amount through the price table, and a Government one yields `price_unresolved` (not 0); a test pins both (#148 item 4 is satisfied by the existing telemetry pricing path, recorded in Clarifications 2).
- [ ] The poller still posts no unpriced `CostRecord` (decision D2 stays); a test asserts the posted events carry `nscostcenter` only for attributed rows.
- [ ] After a poll, `GatewayRegistration.poll_attribution` holds counts `attributed_row`, `attributed_exact`, `attributed_subscription_only`, `unattributed`, `metrics_query_failed` (bool), and the gateway detail API returns it; a failing metrics query shows `metrics_query_failed=true` and the poll status stays `ok` (#179 items 1 and 2).
- [ ] An ARM id whose resource group is `.` or `..`, or ends with `.`, is refused by `normalize_arm_id`; a failed `_record_failure` logs the exception type with the gateway id and never raises; a 403 on an optional inventory list (backends, policy fragments) downgrades that list to empty with `capabilities[...]="unreadable"` instead of failing the sync (#148 item 2).
- [ ] `process_batch` creates its duplicates counter once per `PipelineDeps`, asserted by a counting meter fake (#167).
- [ ] A non-billing invoiced record dropped by `_map_cost` increments a counter `ns.outbox.cost_dropped{reason="invoiced_not_billing"}` and logs the reason code once per batch, never the record (#168).
- [ ] An `observation_source` that disagrees with the producer registration is a per-item `MappingError` with the new reason `observation_source_mismatch` beside `invoiced_not_billing`; identity claims (`customer_id`, `cloud`, `source_id`) stay whole-request 403 `claim_mismatch`; `docs/runbooks/ingest-cost-attribution.md` lists the families (#169).
- [ ] A create step now sends `If-None-Match: *`; given a resource that appears between plan and apply, the PUT answers 412 and the applier raises `StaleVersionError(reason="resource_appeared")` without overwriting; the in-memory twin behaves the same (PRP-34 create race).
- [ ] Given a grant published by an intent applied at t2, replaying an older intent applied at t1 < t2 is refused with `stale_intent` (409), in the API record route and in the worker recorder (PRP-34 grant replay).
- [ ] `POST .../mcp-servers/{id}/publication-record` requires `catalog.curate` on the server's domain, like the grant route; `publish` and `unpublish` keep `action.propose` (PRP-34 permission mismatch).
- [ ] PRP exit: targeted suites, `ruff`, `pyright`, `python packages/contracts/scripts/generate.py --check`, `services/api/tests/test_openapi_drift.py` and `verify-gates.ps1 -Mode full` pass; live attribution checks are reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How does a telemetry-only gateway event carry the cost center | Reverse D2 and post an unpriced `CostRecord`; add a `HubMessage` field | `HubMessage.cost_center` (core wire model, not a contract). `CostRecord.amount` is required, so an unpriced record would need a contract change or a fake 0. D2 stays |
| 2 | Gateway token pricing (#148 item 4) | New poller pricing; rely on ledger pricing | Rely on it: gateway telemetry is `span_kind=model_call` with a request id, so `_map_telemetry` already estimates it from the price table. Posting a second priced `CostRecord` would be summed by `fold.py` (same rank) and double count. This PRP adds the pinning test only |
| 3 | `LedgerEntry.cost_center` when observations disagree | First wins; `None` | `None` (unknown is never a guess) |
| 4 | Which reason family for `observation_source` mismatch (#169) | Both whole-request 403; both per-item | ASSUMPTION: per-item for source-authority failures (one bad item must not block a batch), whole-request for identity claims; new additive code `observation_source_mismatch` |
| 5 | MCP `publication-record` permission | Keep `action.propose`; align to `catalog.curate` | ASSUMPTION: align to `catalog.curate` because the route writes a catalog entity, like the grant route. Stewards who held only `action.propose` lose the manual record path; the worker recorder is the normal path |
| 6 | Poll attribution storage | New counters document; fields on the registration | Fields on `GatewayRegistration` (`poll_attribution`), written by the poller with the existing `poll_status` replace |
| 7 | Inventory 2 MB cap (#148 item 2 chunking) | Chunk the inventory; fail explicitly; defer | Defer to a follow-up issue; not built here |
| 8 | Dashboards by cost center | Include; defer | Defer: filter lives in the ledger and `LedgerFilters`; the finops and dashboard routes are owned elsewhere this wave |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/ingest/service.py` - `_cloudevent_message`, `_telemetry_message`, `resolve_scope`, `_forbidden`.
- `services/api/neurosphere_api/ingest/{reasons,cloudevents}.py` and `packages/core/neurosphere_core/payload/wire.py` - reason enum, extensions, `HubMessage`.
- `services/workers/neurosphere_workers/projections/outbox/mapping.py` - `_map_telemetry`, `_map_cost`.
- `packages/core/neurosphere_core/ledger/{models,fold,totals,service}.py` - `Observation`, `LedgerEntry`, folding, filters.
- `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py` and `connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/gateway_mapping.py` - extension emit and `CostCenterIndex`.
- `packages/core/neurosphere_core/gateway/{models,inventory}.py` and `services/api/neurosphere_api/gateway/service.py`.
- `services/workers/neurosphere_workers/ingestion/pipeline.py:225-260`.
- `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/{applier,arm,inmemory}.py`.
- `services/workers/neurosphere_workers/publication/{grant,mcp}.py`, `services/api/neurosphere_api/catalog/{grant_publish,mcp_publish}.py`.
- `docs/runbooks/ingest-cost-attribution.md`.

### Interfaces consumed
- `CostRecord.tags` (PRP-37): map of at most 16 string entries, key `^[a-z][a-z0-9_.-]{0,62}$`, value up to 128 chars, reserved key `cost_center` with the Grant pattern.
- `Permission.CATALOG_CURATE` and `require` (`neurosphere_api.authz`); PRP-48 (W15) edits `catalog/router.py`, `ui_adapters/catalog.py`, `actions/**`, `deploy/**` route files: this PRP edits none of them.
- PRP-42's gateway settings loader (`gateway_poll/settings.py`) is read only here.

### Interfaces provided
- `HubMessage.cost_center: str | None` and `neurosphere_core.payload.cost_center.sanitize_cost_center`.
- `Observation.cost_center`, `LedgerEntry.cost_center`, `LedgerFilters.cost_center`.
- `GatewayRegistration.poll_attribution` (`PollAttribution` model) in gateway responses and `openapi.json`.
- Reason code `ReasonCode.OBSERVATION_SOURCE_MISMATCH = "observation_source_mismatch"`.
- `ApimArm.put(..., if_none_match: bool = False)` and `HttpApimArm`/`InMemoryApim` support.
- `check_grant_intent` plus new `check_grant_not_superseded(doc, stored)` in `publication/grant.py`.

### Patterns to match
- Closed reason enum with grouping comments: `ingest/reasons.py:9-37`.
- Idempotent replace with ETag in the poller: `gateway_poll/poller.py:403-437`.
- The MCP stale-intent guard to mirror: `publication/mcp.py:168-185`.
- Counter creation once in a deps object: `pipeline.py:242-244` (move into `PipelineDeps`).
- Test rigs: `services/workers/tests/gateway_poll/support.py` (`Rig`), `services/api/tests/ingest/test_cloudevents.py`.

### Gotchas
- `cost_center` must be stamped from the extension only after producer scope is resolved; never read it from `data` (a producer could put anything there). Tags already inside `data` are validated by the contract.
- `fold.py` sums observations of the same rank, so do not add a second gateway observation for the same request (Clarification 2).
- `ledger` documents are stored as written; `cost_center` defaults to `None` and the content hash includes it only when set, so existing hashes stay valid (assert in a test).
- `GatewayRegistration` is `extra="forbid"`: old stored documents load without the new field; new documents read by an old worker fail, so deploy API and workers together.
- `poller.py` must not touch `gateway_poll/settings.py` (PRP-42 owns the loader).
- `HttpApimArm.put` callers pass `if_match=None` for non-create updates today; only the create path gains `if_none_match`.
- The MCP route change breaks tests that grant a steward only `action.propose` (`services/api/tests/catalog_api/test_mcp_publish.py:260`); update the fixtures, do not weaken the route.
- New ingest reason codes appear in `openapi.json` and `docs/reference/**` (Tier 3).

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/ingest/service.py
  - services/api/neurosphere_api/ingest/reasons.py
  - services/api/neurosphere_api/ingest/cloudevents.py
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - services/api/neurosphere_api/ingest/publisher.py
  - services/api/neurosphere_api/ingest/router.py
  - services/api/neurosphere_api/ingest/limits.py
  - services/api/neurosphere_api/ingest/settings.py
  - services/api/neurosphere_api/gateway/**
  - packages/core/neurosphere_core/gateway/**
  - packages/core/neurosphere_core/payload/wire.py
  - packages/core/neurosphere_core/payload/cost_center.py
  - packages/core/neurosphere_core/ledger/**
  - services/workers/neurosphere_workers/projections/outbox/**
  - services/workers/neurosphere_workers/ingestion/pipeline.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/__init__.py
  - connectors/reference/azure-monitor/**
  - connectors/reference/apim-gateway/**
  - services/workers/neurosphere_workers/publication/**
  - services/api/neurosphere_api/catalog/grant_publish.py
  - services/api/neurosphere_api/catalog/mcp_publish.py
  - services/api/tests/ingest/test_ingest_cost_center.py
  - services/api/tests/gateway_api/test_gateway_hardening.py
  - services/api/tests/catalog_api/test_mcp_publish.py
  - services/api/tests/catalog_api/test_grant_publish_replay.py
  - packages/core/tests/ledger/test_ledger_cost_center.py
  - packages/core/tests/gateway_core/test_gateway_hardening.py
  - packages/core/tests/payload/test_cost_center_sanitize.py
  - services/workers/tests/outbox/test_outbox_cost_center.py
  - services/workers/tests/gateway_poll/test_poll_attribution.py
  - services/workers/tests/ingestion/test_pipeline_counter.py
  - services/workers/tests/publication_replay/**
  - docs/runbooks/ingest-cost-attribution.md
tier1: []
tier2_appends: []
must_not_touch:
  - services/api/neurosphere_api/ingest/auth.py
  - services/api/neurosphere_api/ingest/bootstrap.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/settings.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/ui_adapters/**
  - packages/contracts/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - packages/core/neurosphere_core/aggregates/**
```

## Implementation blueprint
Parallelization map: Items 1, 3, 4, 5 are independent [P] (disjoint files). Item 2 waits for 1 (`HubMessage.cost_center`). Item 6 is last. `openapi.json` and `docs/reference/**` are regenerated in Item 6 only.

### Item 1 - Ingest reads the cost center; reason families  [P]
- Deliverable: `sanitize_cost_center` helper (new), `HubMessage.cost_center`, `IngestService` reads `nscostcenter` for telemetry and cost CloudEvents after scope resolution, merges into `CostRecord.tags` (record's own tag wins), per-item `observation_source_mismatch`, runbook table of reason families, counted tag-mismatch metric.
- Owned files: `payload/{wire,cost_center}.py`, `ingest/{service,reasons,cloudevents}.py`, `services/api/tests/ingest/test_ingest_cost_center.py`, `packages/core/tests/payload/test_cost_center_sanitize.py`, `docs/runbooks/ingest-cost-attribution.md`.
- Must NOT touch: `ingest/auth.py`, `ingest/bootstrap.py`, `packages/contracts/**`.
- Depends on: none (PRP-37 merged).
- Acceptance criteria: criteria 1 to 3 and 12; existing `test_cloudevents.py` updated only where the 403-to-item change requires it.
- Tests: `uv run pytest -q services/api/tests/ingest packages/core/tests/payload`.
- Pattern references: `service.py:308-355`, `cloudevents.py:30-40`, `reasons.py:9-37`.

### Item 2 - Worker path to the ledger; outbox and pipeline counters
- Deliverable: `Observation.cost_center` set by `_map_telemetry` and `_map_cost`; `fold.py` derives `LedgerEntry.cost_center` (agree or single, else `None`); `LedgerFilters.cost_center`; `StoreLedgerReader.totals` passes it; outbox counter for dropped non-billing invoiced records (#168); duplicates counter created once (#167); pinning pricing test for gateway telemetry (Clarification 2).
- Owned files: `ledger/{models,fold,totals,service,cosmos}.py`, `projections/outbox/mapping.py`, `ingestion/pipeline.py`, `packages/core/tests/ledger/test_ledger_cost_center.py`, `services/workers/tests/outbox/test_outbox_cost_center.py`, `services/workers/tests/ingestion/test_pipeline_counter.py`.
- Must NOT touch: `aggregates/**`, `factories.py`.
- Depends on: Item 1.
- Acceptance criteria: criteria 4 to 6, 10, 11; a stored pre-change ledger document loads and keeps its content hash.
- Tests: `uv run pytest -q packages/core/tests/ledger services/workers/tests/outbox services/workers/tests/ingestion`.
- Pattern references: `mapping.py:60-130`, `fold.py:38-60`, `totals.py:50-65`.

### Item 3 - Poller attribution counts and gateway hardening  [P]
- Deliverable: `CostCenterIndex.lookup` returns the tag and how it was derived (`row`, `exact`, `subscription_only`); poller tallies counts and writes `poll_attribution`; `PollAttribution` model on `GatewayRegistration` (additive); `normalize_arm_id` rejects `.`/`..`/trailing-dot groups; `_record_failure` logs the type; optional inventory lists degrade on 403.
- Owned files: `connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/gateway_mapping.py`, `connectors/reference/azure-monitor/tests/**`, `gateway_poll/poller.py`, `gateway_poll/__init__.py`, `packages/core/neurosphere_core/gateway/{models,inventory}.py`, `services/api/neurosphere_api/gateway/service.py`, `services/workers/tests/gateway_poll/test_poll_attribution.py`, `packages/core/tests/gateway_core/test_gateway_hardening.py`, `services/api/tests/gateway_api/test_gateway_hardening.py`.
- Must NOT touch: `gateway_poll/settings.py`, `ingest/**`.
- Depends on: none.
- Acceptance criteria: criteria 7 to 9; the existing `test_cost_center.py` still passes (extension only for attributed rows).
- Tests: `uv run pytest -q services/workers/tests/gateway_poll connectors/reference/azure-monitor/tests packages/core/tests/gateway_core services/api/tests/gateway_api`.
- Pattern references: `poller.py:327-356,425-437`, `gateway_mapping.py:135-175`.

### Item 4 - APIM create-race guard  [P]
- Deliverable: `if_none_match` keyword on `ApimArm.put`, `HttpApimArm`, `InMemoryApim`; the applier's create step passes it and maps 412 to `StaleVersionError(reason="resource_appeared")`.
- Owned files: `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/{arm,applier,inmemory}.py`, `connectors/reference/apim-gateway/tests/test_apim_write_apply.py`, `connectors/reference/apim-gateway/tests/test_apim_write_http_arm.py`.
- Must NOT touch: planner, translators, `connectors/sdk-python/**`.
- Depends on: none.
- Acceptance criteria: criterion 13; reversal of a failed create still never deletes a resource this run did not create.
- Tests: `uv run pytest -q connectors/reference/apim-gateway/tests services/workers/tests/action_executor`.
- Pattern references: `applier.py:155-175`, `arm.py:293-305`, `inmemory.py:126-137`.

### Item 5 - Grant replay guard and MCP record permission  [P]
- Deliverable: `check_grant_not_superseded` (apply time of the intent versus `provenance.recorded_at` of the last record, same rule as the MCP guard) called by the API record route and the worker recorder; `publication-record` for MCP uses `CurateAccess`; fixtures updated.
- Owned files: `publication/grant.py`, `publication/recorder.py`, `catalog/grant_publish.py`, `catalog/mcp_publish.py`, `services/api/tests/catalog_api/test_mcp_publish.py`, `services/api/tests/catalog_api/test_grant_publish_replay.py` (new), `services/workers/tests/publication_replay/**` (new).
- Must NOT touch: `catalog/router.py`, `publication/mcp.py` logic beyond a shared helper import.
- Depends on: none.
- Acceptance criteria: criteria 14 and 15; an idempotent replay of the same recorded intent still returns the stored entity unchanged.
- Tests: `uv run pytest -q services/api/tests/catalog_api services/api/tests/catalog services/workers/tests/publication_replay services/workers/tests/action_executor`.
- Pattern references: `publication/mcp.py:160-185`, `grant_publish.py:248-262`.

### Item 6 - Integration and close-out
- Deliverable: regenerate `services/api/openapi.json`, `docs/reference/**`; `python packages/contracts/scripts/generate.py --check`; `python scripts/prp_status.py --write`; cross-test grep for `HubMessage(`, `LedgerEntry(`, `GatewayRegistration(`, `ReasonCode` over `tests/`, `services/*/tests`, `packages/core/tests`; CHANGELOG entry; completion note with "Env vars for the operator" (none new; the `.env.example` names from #148 item 3 listed for the operator).
- Owned files: this PRP file; generated Tier 3 files.
- Depends on: Items 1 to 5.
- Acceptance criteria: reference section 6 satisfied; follow-up issues filed for dashboards by cost center, inventory chunking, `.env.example` names.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/ingest services/api/tests/gateway_api services/api/tests/catalog_api services/api/tests/catalog packages/core/tests/payload packages/core/tests/ledger packages/core/tests/gateway_core services/workers/tests/outbox services/workers/tests/ingestion services/workers/tests/gateway_poll services/workers/tests/publication_replay services/workers/tests/action_executor connectors/reference/azure-monitor/tests connectors/reference/apim-gateway/tests services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python packages/contracts/scripts/generate.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive fields only: `HubMessage.cost_center`, `Observation.cost_center`, `LedgerEntry.cost_center`, `GatewayRegistration.poll_attribution`; stored documents without them load. Messages already on the hub lack the field and are processed unchanged. Roll API and workers out together (new documents are `extra="forbid"` for older readers). Rollback: revert the PR; the extra fields on stored documents would make an old worker reject them, so revert only before ledger writes with `cost_center` have occurred or after a one-off strip. The MCP permission change is reverted by reverting Item 5.

## Live and open gates
Government attribution (#179 item 3), the `Subscription ID` dimension check and the G17 observe rerun (#179 item 4, #148 item 6) need `NS_LIVE_APPROVED=1` and an operator; handed to PRP-64 and reported OPEN. Nothing in this PRP makes a paid call.

## NOT building
Unpriced `CostRecord` posting (D2 reversal); dashboards or finops grouping by cost center; Government cost-center sources; gateway inventory chunking; `.env.example` edits; producer registry changes; connector SDK changes.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided or labelled ASSUMPTION

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-46-cost-center | done (ingest extension, reasons, runbook) |
| 2 | merged | prp-46-cost-center | done (ledger, outbox counter, pipeline counter) |
| 3 | merged | prp-46-cost-center | done |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint:
- Descoped items:
- OPEN gates (#179 items 3 and 4, #148 item 6):
- Env vars for the operator (none new; list #148 item 3 names for `.env.example`):
- Follow-up issue numbers (dashboards by cost center, inventory chunking):
- Issue state (#190, #178, #148, #179, #167, #168, #169):
