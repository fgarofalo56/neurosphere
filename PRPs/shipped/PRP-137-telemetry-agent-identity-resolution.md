---
name: PRP-137-telemetry-agent-identity-resolution
status: shipped
priority: P0
order: 59
review: required
created: 2026-11-16
started: 2026-11-22
shipped: 2026-11-22
pr: 375
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-02
depends_on: []
wave: W19
branch: prp-137-agent-identity-resolution
allow_parallel: true
issues: []
---

# PRP-137: Telemetry agent identity resolution (external id to canonical agent id)

## Goal
Make telemetry that arrives through the OpenTelemetry path count for the agent that sent it. Today an OTLP span carries only the agent's external id (`gen_ai.agent.id`), and nothing in production code turns it into the catalog's canonical agent id, so those agents get no per-agent aggregate series, no health on the map, no performance signal for the recommender and no cost attribution. This PRP adds one resolver from (cloud, customer, source, external id) to a canonical agent id using catalog alias documents, applies it where the workers read stored events (so the stored archive is not rewritten and a later alias takes effect), surfaces ids with no alias as draft agents marked as discovered from telemetry (the "undeclared agents" PRP-76 lists) instead of dropping them, adds a re-resolution job that re-applies an alias to past events idempotently, and proves the whole path through the real normalisation pipeline. It is for the steward who sees an agent in the catalog but no traffic, and for PRP-74, PRP-100 and PRP-134, which read per-agent series. It runs in W19 beside PRP-67 and PRP-70, before PRP-100, PRP-74, PRP-103 and PRP-107 (W22), and edits none of their files; `runtime/factories.py` is its own Tier-1 file in W19.

Out of scope: tool and service identity (PRP-100); the map (PRP-74 reads the series this PRP makes exist); the registration form, the undeclared-agent list and any catalog service change (PRP-76); cost records and ledger entries (the ledger carries no agent id; see PRP-134); merging a draft into a registered agent (never automatic; a steward deprecates the draft); an automatic trigger for re-resolution when an alias is added (follow-up, see clarification 8); Entra, run-as and entitlement identity (PRP-118).

## Why
- The telemetry contract has both fields and the comment says resolution is expected: `external_agent_id` "as reported by the source system" and `canonical_agent_id` "Null until resolution succeeds" (`packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:183-189`). The catalog `Agent` carries `external_agent_id` "resolution to this ID is recorded by alias documents" (`packages/contracts/python/neurosphere_contracts/catalog/v1/agent.py:89-92`), and `docs/PRD.md:14` promises "Stable cloud/customer/source-qualified IDs resolve collisions and agent aliases" (NS-02).
- The OTLP mapping sets only the external id (`services/api/neurosphere_api/ingest/otlp_mapping.py:265`) and never the canonical one. A grep of `packages/core`, `services/api` and `services/workers` for `external_agent_id` and `canonical_agent_id` finds writers only in the Foundry poller (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:246`, an entity field, not an alias), the sandbox generator (`sandbox/costs.py:76`, which sets the canonical id directly) and tests. PRP-100's report (`temp/audit/writer-reports/100.md`, finding 2) found the same gap and left it unfixed.
- Every consumer reads only the canonical field, so an OTLP agent is invisible: `contribution_from_event` uses `event.canonical_agent_id` (`services/workers/neurosphere_workers/aggregates/mapping.py:167`); the catalog projection's `_agent` returns None without it (`services/workers/neurosphere_workers/projections/catalog/mapping.py:122-124`, so no `USES_MODEL` or `INVOKES` edge is built from that agent); online evaluation falls back to the raw external id as a label (`services/workers/neurosphere_workers/evaluation/online.py:94-95`).
- No production code writes an alias. `CatalogRepository.put_alias` and `resolve_alias` exist (`packages/core/neurosphere_core/catalog/protocol.py:244-253`, `catalog/repo/engine.py:312-345,402`) and only the model resolver reads one (`AliasModelResolver`, `projections/catalog/handler.py:94-111`). The mechanism is built and unused for agents.
- The local demo hides the defect: the sandbox sets canonical ids on every event, so per-agent series exist locally and the hosted OTLP path is the first place they do not.

## Acceptance criteria
- [ ] Given an OTLP span with `gen_ai.agent.id = support-bot` from source `otel-prod`, an active `external_id` alias for (`otel-prod`, `support-bot`) pointing at a registered agent, When the event passes the real ingestion pipeline and the aggregates and projection workers, Then the agent's `model_call` appears in that agent's aggregate series and the catalog gets the `USES_MODEL` edge from that agent.
- [ ] Given the same span with no alias, Then it is resolved to a deterministic derived id `<cloud>:<customer>:<source>:agent:<slug>` (collision-safe, see clarification 3), the aggregate series exists under that id, and a draft agent with `attributes.discovered_from = "telemetry"`, `attributes.agent_identity = "derived_from_external_id"` and the `external_agent_id` is created if absent; the event is never dropped and never quarantined for lacking an alias.
- [ ] Given an event with neither ids, Then it is counted as `no_agent_id` and keeps `canonical_agent_id` null (as today); given an event that already carries a canonical id, Then it is kept unchanged when it belongs to the event's cloud and customer and is of type `agent`, and counted `declared`.
- [ ] Given an alias added after events were processed (the series sits under the derived id), When the re-resolution job runs for that source and external id over a window, Then the contributions move to the aliased agent, the old series points disappear, the rollups agree with a from-scratch run, and running the job twice changes nothing.
- [ ] Given an alias that points to another customer, another cloud or a non-agent id, Then it is ignored with a counted reason (`alias_target_invalid`) and the derived id is used; resolution never crosses cloud or customer (no Government to Commercial bridge).
- [ ] The resolver is read-only for the worker aggregates path: the alias lookup uses the worker's server-derived scope, never a value from the event; a lookup failure raises `DependencyTransientError` so the outbox entry retries, and never silently falls back to the derived id (which would split the series).
- [ ] Declaring or repointing an alias is a person action: `PUT /api/v1/agent-identity/domains/{domain}/aliases` needs `catalog.curate` in that domain, audits the change, retires a previous active alias for the same key before adding the new one, and returns `reresolve_needed: true` with the exact job arguments.
- [ ] Counters (no ids in labels, no event content): resolved by alias, derived, declared, no id, invalid alias target, lookup failures, drafts created, contributions moved by re-resolution; shown in the `/readyz`-style worker status the other workers use.
- [ ] Tests run through the real pipeline: `map_span` (OTLP mapping) to `process_batch` to the archive fake to the outbox to `AggregateProjection` and `CatalogProjection`, not hand-built events with a canonical id.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated; the runbook explains how to declare an alias and when to run re-resolution.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Where to resolve | At ingest edge; in the normaliser before archive; at read time in the workers | At read time, by wrapping `TraceEventSource` and the evaluation `RecordSource`. The archive stays exactly what arrived (it is an audit-grade record), a later alias applies to events not yet processed, and `ingestion/pipeline.py` is untouched (PRP-84 owns it later) |
| 2 | Alias lookup key | New key; the existing `AliasKey` | `AliasKey(alias_source_id=slug(event.source_id), alias_kind="external_id", alias_value=external id)`, the shape `AliasModelResolver` already uses with `source_native_id` |
| 3 | Unresolved id | Drop; quarantine; deterministic derived id | Derived id `<cloud>:<customer>:<source>:agent:<slug>`; when the slug differs from the lowercased external id, append `-<first 8 hex of sha256(external id)>` so two external ids that slug to the same text cannot merge |
| 4 | Alias for a derived draft | Write one; write none | None. A derived alias would block the later real alias (`put_alias` refuses a second active alias for the same key, `engine.py:336-345`). The derived id is recomputed every time; only a declared or discovered mapping is an alias document |
| 5 | Who writes aliases | New code in the catalog service; a new small API; the Foundry poller | The Foundry poller writes an alias for each discovered agent that has an external id; people use the new `agent-identity` route. `catalog/service.py` is PRP-76's file and is not edited; PRP-76 may call `declare_agent_alias` later |
| 6 | Cache | None; bounded TTL cache | ASSUMPTION: bounded cache (10 000 keys), 60 s for alias hits, 15 s for misses (`NS_AGENT_IDENTITY_POSITIVE_TTL_SECONDS`, `..._NEGATIVE_TTL_SECONDS`), so a new alias is picked up within a minute without a lookup per event |
| 7 | Conflict with a registered agent with the same external id | Merge; leave both | Leave both. The draft stays until a steward deprecates it; nothing merges agents automatically |
| 8 | Trigger for re-resolution | Automatic on alias write; operator job | Decided by the owner 2026-11-16 (GD-38): re-resolution after an alias change is an operator job (`python -m neurosphere_workers.agent_identity reresolve`); an automatic trigger is a follow-up. Here: plus the `reresolve_needed` hint, because the API process cannot enqueue worker work without a new store |
| 9 | Scope of re-resolution | All history; the aggregate window | The aggregates window (`window_start`, `aggregates/handler.py:59`) and the archive names the reader indexes, capped by `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS` (default 50 000); older events stay under the derived id and the report says so |
| 10 | Domain for OTLP events (they arrive with no `domain_id`, so edges and drafts never fire) | Stamp at read time; ship and follow up; attribute at the ingest edge | Decided by the owner 2026-11-22 during execution: stamp at read time in the resolving sources, never overwriting an event's own domain. `alias`/`declared` take the resolved agent's catalog domain (cached `get_entity` in the worker scope); `derived` takes the operator setting `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN` (unset or foreign: counted `domain_unattributed`, behaviour as before). Item 6b |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/catalog/protocol.py:162-169,244-253` - `AliasKey`, `put_alias`, `resolve_alias`.
- `packages/core/neurosphere_core/catalog/repo/engine.py:312-345,368-415` - alias uniqueness, no repoint, scoped resolve.
- `packages/contracts/schemas/catalog/v1/alias.schema.json` - alias fields, `status` active or retired, person aliases forbidden.
- `services/workers/neurosphere_workers/projections/catalog/handler.py:84-111,142-195` - `AliasModelResolver` (the pattern), `CatalogProjection.handle`, `_ensure_entities`.
- `services/workers/neurosphere_workers/projections/catalog/discovery.py:25-75` - draft entity shape and `DISCOVERED_FROM`.
- `services/workers/neurosphere_workers/projections/catalog/source.py` - `TraceEventSource`, `LoadedEvent`.
- `services/workers/neurosphere_workers/aggregates/handler.py:104-150` and `mapping.py:150-175` - where the event is loaded and the agent id is used.
- `services/workers/neurosphere_workers/runtime/archive_reader.py:95-215` - `ArchiveTraceEventSource`, `ArchiveRecordSource`.
- `services/workers/neurosphere_workers/runtime/factories.py:450-500,1108-1145` - where the sources are built.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:230-290` - create-only discovery.
- `services/workers/neurosphere_workers/evaluation/online.py:80-110` - the raw external id fallback.
- `temp/audit/writer-reports/100.md` and `PRPs/backlog/PRP-100-*.md` - what it leaves to this PRP.

### Interfaces consumed
- Shipped: `CatalogRepository.resolve_alias` and `put_alias`, `Alias` contract, `TraceEventSource`, `OutboxEntry`, `AggregateProjection.handle`, `CatalogProjection.handle`, `run_audited_mutation`, `require(Permission.CATALOG_CURATE, domain_from_path("domain"))`.
- PRP-70 and PRP-71 are not dependencies: this PRP needs no new contract field (the telemetry and catalog fields it uses ship today) and builds its own fixtures. PRP-71's demo world may later include one OTLP-path agent with an external id only (a fixture request to PRP-71, not an edit).
- PRP-100 (W22, merges after this PRP): reads `event.canonical_agent_id` unchanged; this PRP stamps it before PRP-100's code sees it.

### Interfaces provided
- Core `neurosphere_core.agent_identity` (new): `agent_alias_key(source_id, external_id)`, `derive_agent_id(cloud, customer, source, external_id)`, `AgentIdentityResolver.resolve(...) -> AgentResolution` (`canonical_id`, `status`: `alias|derived|declared|none`), `AliasLookup` protocol, `CatalogAliasLookup`, `declare_agent_alias(repo, scope, ...)`, `ResolutionStats`.
- Worker `neurosphere_workers.agent_identity` (new): `ResolvingTraceEventSource`, `ResolvingRecordSource`, `reresolve_external_id(...)`, CLI `python -m neurosphere_workers.agent_identity reresolve`.
- `LoadedEvent.agent_resolution: str | None` (additive, default None) in `projections/catalog/source.py`.
- API `neurosphere_api.agent_identity` (new), prefix `/api/v1/agent-identity`: `PUT /domains/{domain}/aliases`, `GET /domains/{domain}/aliases?source_id=&external_agent_id=`. Audit operations `agent_identity.alias_declare`, `agent_identity.alias_retire`.
- Settings `NS_AGENT_IDENTITY_POSITIVE_TTL_SECONDS`, `NS_AGENT_IDENTITY_NEGATIVE_TTL_SECONDS`, `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS`.
- Consumers: PRP-74 (map health for OTLP agents), PRP-100 (agent series beside tool and service series), PRP-134 (per-agent cost series; the ledger itself has no agent id), PRP-72's `telemetry_signal`, PRP-76 (undeclared list reads the drafts).

### Patterns to match
- Alias-first with a deterministic fallback: `projections/catalog/handler.py:94-111`.
- Create-if-absent draft with `discovered_from`: `projections/catalog/discovery.py:29-75` and `handler.py:275-302`.
- Worker CLI entry: `services/workers/neurosphere_workers/ingestion/__main__.py`.
- Idempotent contribution replace: `aggregates/handler.py:152-168` (id `EVENT_PREFIX + doc_id`).
- Audited admin write with a domain permission: `services/api/neurosphere_api/catalog/router.py` PUT routes (read the nearest one before copying).

### Gotchas
- `TelemetryEvent` is a frozen Pydantic model: stamp with `model_copy(update=...)` using the contract `CanonicalId` type, then run the grammar check (`validate_canonical_id_grammar` in `tests/contracts`) in a test; do not build a string-typed field.
- The alias lookup needs an `IdentityScope`; the aggregates worker has none today. Build it the way `build_projections` does (`build_policy_stack`, `build_identity`) and read `scope_provider.get()` per batch, not per event.
- `resolve_alias` returns None for an out-of-scope alias, so a missing alias and a forbidden one look the same; both fall to the derived id and are counted `derived`.
- `put_alias` cannot repoint (`engine.py:368-379`): repoint is retire plus add, and the retire must be a status change to `retired` on the same canonical id.
- `AliasModelResolver` has no cache; this resolver does, so tests must inject a clock and assert the TTL edges.
- `ArchiveRecordSource` yields dicts whose contract is under `record["contract"]` (`evaluation/online.py:83-85`); the wrapper copies the dict and never mutates the archive record.
- Test packages: use unique directory names (`packages/core/tests/agent_identity`, `services/workers/tests/agent_identity_worker`, `services/api/tests/agent_identity_api`); same-named test dirs shadow each other.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/agent_identity/**
  - packages/core/tests/agent_identity/**
  - services/workers/neurosphere_workers/agent_identity/**
  - services/workers/tests/agent_identity_worker/**
  - services/workers/neurosphere_workers/projections/catalog/source.py
  - services/workers/neurosphere_workers/projections/catalog/handler.py
  - services/workers/neurosphere_workers/projections/catalog/discovery.py
  - services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py
  - services/api/neurosphere_api/agent_identity/**
  - services/api/neurosphere_api/runtime/builders/agent_identity.py
  - services/api/tests/agent_identity_api/**
  - tests/security/authz/test_agent_identity.py
  - tests/integration/ingestion/test_agent_identity_resolution.py
  - docs/runbooks/agent-identity-resolution.md
tier1:
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - services/api/tests/runtime_routes/test_manifest_routes_serve.py
  - tests/integration/real_stack/test_manifest_routes.py
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/tests/runtime_gateway_builder/test_gateway_builder.py
  - services/api/tests/runtime_data/data_helpers.py
  - services/api/tests/admin_identity_api/test_builder.py
  - services/api/tests/analytics_runtime/test_analytics_builder.py
  - docs/runbooks/system-settings.md
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/aggregates/**
  - packages/core/neurosphere_core/catalog/**
  - services/workers/neurosphere_workers/aggregates/**
  - services/workers/neurosphere_workers/ingestion/pipeline.py
  - services/workers/neurosphere_workers/ingestion/resolve_subjects.py
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/map/**
  - services/api/neurosphere_api/catalog/**
```
`services/workers/neurosphere_workers/runtime/factories.py` is this PRP's Tier-1 file in W19: PRP-67 and PRP-70 do not own it, and PRP-107 and PRP-103 (W22) merge after this PRP. The wiring lines are item 6 and need no `[serial-after]`. `services/api/tests/runtime_api/test_readiness.py` and the other pinned builder-order tests (`runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`) change because item 5 adds an API builder; nobody else in W19 owns them (PRP-103 does in W22, later), so item 5 edits them with the builder (alternative: no new builder, see item 5).

## Implementation blueprint

Parallelization: items 1 and 5 touch no common file; item 2 needs 1; item 3 needs 2; item 4 needs 3; item 6 needs 2 to 4; item 7 last before close-out.

### Item 1 - Core resolver  [P]
- Deliverable: `neurosphere_core/agent_identity/` with `keys.py` (`agent_alias_key`, `derive_agent_id`, slug rule of clarification 3, owned-agent check mirroring `projections/catalog/mapping.py:110-124`), `resolver.py` (`AgentIdentityResolver`, bounded TTL cache with an injected clock, `AgentResolution`, `ResolutionStats`), `lookup.py` (`AliasLookup` protocol, `CatalogAliasLookup` over a `CatalogRepository` and a scope getter, `declare_agent_alias` doing retire-then-add for a repoint).
- Owned files: `packages/core/neurosphere_core/agent_identity/**`, `packages/core/tests/agent_identity/**`.
- Must NOT touch: `catalog/**`, contracts.
- Depends on: nothing.
- Acceptance criteria: statuses `alias`, `derived`, `declared`, `none` per the criteria; foreign cloud, customer or type targets give `alias_target_invalid`; a lookup exception propagates; derived ids are stable, grammar-valid and differ for two external ids that slug alike; cache hit, miss and expiry behave with an injected clock.
- Tests: `packages/core/tests/agent_identity/test_keys.py`, `test_resolver.py`, `test_lookup_catalog.py` (in-memory catalog repository, including repoint).
- Pattern references: `projections/catalog/handler.py:94-111`, `catalog/repo/engine.py:368-415`.

### Item 2 - Resolving event sources
- Deliverable: `neurosphere_workers/agent_identity/sources.py` with `ResolvingTraceEventSource` (wraps `get_event`, `find_span`, `find_child_spans`, stamps `canonical_agent_id`, sets `LoadedEvent.agent_resolution`) and `ResolvingRecordSource` (copy of each archive record dict with `canonical_agent_id` set in the inner contract); `LoadedEvent` gains `agent_resolution` in `projections/catalog/source.py`.
- Owned files: `services/workers/neurosphere_workers/agent_identity/**`, `projections/catalog/source.py`, `services/workers/tests/agent_identity_worker/test_sources.py`.
- Must NOT touch: `aggregates/**`, `runtime/archive_reader.py`.
- Depends on: item 1.
- Acceptance criteria: the wrapped source returns the same events with only the agent field and `agent_resolution` changed; the inner source is never mutated; child-span lookups stamp both parent and child; existing `InMemoryTraceEventSource` tests pass unchanged.
- Tests: `services/workers/tests/agent_identity_worker/test_sources.py`; existing `services/workers/tests/projections` and `neurosphere_workers/aggregates/tests`.
- Pattern references: `runtime/archive_reader.py:107-175`.

### Item 3 - Surface unresolved agents as drafts
- Deliverable: `CatalogProjection.handle` creates, for every event whose `agent_resolution == "derived"` and whose domain is in scope, a draft `Agent` through a new `agent_discovery_entity(event)` in `discovery.py` (display name from the external id capped at 256, `platform` and `source_id` from the event source, `external_agent_id`, attributes `discovered_from=telemetry`, `agent_identity=derived_from_external_id`); create-if-absent, a create conflict is success; an event without a domain counts `agent_undiscoverable_no_domain`.
- Owned files: `projections/catalog/handler.py`, `projections/catalog/discovery.py`, `services/workers/tests/agent_identity_worker/test_discovery.py`.
- Must NOT touch: `projections/catalog/mapping.py`, `catalog/**` in core or API.
- Depends on: item 2.
- Acceptance criteria: a replay creates no second draft and never updates an existing declared or curated agent; the draft validates as `Agent`; an out-of-scope domain quarantines nothing and is counted; existing `services/workers/tests/projections` suite passes unchanged.
- Tests: `services/workers/tests/agent_identity_worker/test_discovery.py`; existing projections suite.
- Pattern references: `discovery.py:47-75`, `handler.py:275-302`.

### Item 4 - Re-resolution job
- Deliverable: `reresolve.py` and `__main__.py`: given customer, source id, external id and an optional since, list archive names through `ArchiveReader`, read matching records (bounded by `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS`), and for each matching telemetry event call the aggregates and catalog handlers with a synthetic `OutboxEntry` (kind `event`, `ref_id` the doc id), so the contribution with the same id is replaced and the rollups rebuild; the report lists examined, matched, moved, skipped-out-of-window and a `truncated` flag.
- Owned files: `services/workers/neurosphere_workers/agent_identity/{reresolve,__main__}.py`, `services/workers/tests/agent_identity_worker/test_reresolve.py`.
- Must NOT touch: `aggregates/**`, `outbox/**`.
- Depends on: items 2 and 3.
- Acceptance criteria: the alias-added-later criterion, including a second run with identical store contents; a truncated scan says so; the job refuses to run with no customer or an event from another customer.
- Tests: `services/workers/tests/agent_identity_worker/test_reresolve.py` (in-memory aggregate and catalog stores).
- Pattern references: `aggregates/handler.py:104-168`, `ingestion/__main__.py`.

### Item 5 - Alias declaration API
- Deliverable: `neurosphere_api/agent_identity/` router, models and service for the two routes; `PUT` validates that the target agent exists in scope and is in the path domain, retires any previous active alias for the key, writes the new one, audits, and returns the job hint; `GET` returns the active alias or 404 without revealing out-of-scope ids. Builder `runtime/builders/agent_identity.py` (`COMPONENTS = ("agent_identity",)`, optional) binds the repository already on `app.state`. The builder adds its lines to the three pinned-order tests (`runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`), which nobody else owns in W19; if a conflict still appears, register the router through `routers.py` only and read the repository from `app.state` (no component), and say so in the completion note.
- Owned files: `services/api/neurosphere_api/agent_identity/**`, `runtime/builders/agent_identity.py`, `services/api/tests/agent_identity_api/**`, `tests/security/authz/test_agent_identity.py`, the three pinned-order tests above (one added line each).
- Must NOT touch: `catalog/**`, `ingest/**`.
- Depends on: item 1.
- Acceptance criteria: only `catalog.curate` in the domain may write; viewers, auditors, other-domain stewards and expired users get 403 and a denial record; a conflicting target in another domain is indistinguishable from missing; every new route is in the route inventories and boots under `verify_route_permissions`; audit records carry ids and reason codes, no event content.
- Tests: `services/api/tests/agent_identity_api/test_routes.py`, `test_repoint.py`; `tests/security/authz/test_agent_identity.py`.
- Pattern references: `services/api/neurosphere_api/catalog/router.py` (PUT with `If-Match`), PRP-41's admin routes (`admin/sources/producers`).

### Item 6 - Worker wiring and Foundry alias
- Deliverable: `build_projections`, `build_aggregates` and `build_evaluation` in `runtime/factories.py` wrap their sources with the resolving decorators and a `CatalogAliasLookup` over the worker's `CosmosCatalogRepository` and scope provider (three small edits, one import block); the Foundry poller writes an `external_id` alias for each discovered agent that has an external id (collision counted, never raised); settings classes for the three env vars.
- Owned files: `runtime/factories.py` (wiring lines only; Tier-1 of this PRP in W19), `ingestion/foundry_discovery/poller.py`, `services/workers/tests/agent_identity_worker/test_factory_wiring.py`, `services/workers/tests/foundry_discovery_role` additions.
- Must NOT touch: anything in `factories.py` outside the three wiring edits.
- Depends on: items 2 to 4.
- Acceptance criteria: with the switch settings at default the roles resolve; a lookup outage makes the outbox entry retry (no checkpoint advance), not a split series; existing `services/workers/tests/{worker_roles,foundry_discovery_role,projections,evaluation_worker}` pass unchanged.
- Tests: `services/workers/tests/agent_identity_worker/test_factory_wiring.py`.
- Pattern references: `factories.py:450-495` (`build_projections`, `build_aggregates`).

### Item 7 - Tests through the real pipeline
- Deliverable: an in-process end-to-end test and an emulator variant. The in-process test feeds real OTLP trace JSON through `map_span`, wraps each result as a hub message, runs `process_batch` with the ingestion fakes, then runs the outbox entries through `AggregateProjection` and `CatalogProjection` built with resolving sources and in-memory stores. Cases: alias present; no alias (derived plus draft); alias added later plus re-resolution; two external ids that slug alike; an alias for another customer; a lookup outage.
- Owned files: `services/workers/tests/agent_identity_worker/test_pipeline_end_to_end.py`, `tests/integration/ingestion/test_agent_identity_resolution.py` (marker `integration`, emulators).
- Must NOT touch: `tests/integration/ingestion/support.py` (read-only reuse of `otlp_attr`, `Pipeline`).
- Depends on: items 2 to 4.
- Acceptance criteria: every acceptance criterion above that concerns data has one assertion here; the test fails if resolution is removed (checked once by disabling the wrapper locally).
- Tests: the two files.
- Pattern references: `tests/integration/ingestion/support.py:252-310` (`push_otlp_traces`, `otlp_model_call_spans`), `services/workers/tests/ingestion`.

### Item 6b - Domain attribution for OTLP events (added 2026-11-22, clarification 10)
- Deliverable: the resolver also returns a domain for events with none (the resolved agent's catalog domain for `alias`/`declared`, the discovery-domain setting for `derived`); the resolving sources stamp it; settings and wiring carry `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN`; counters `domain_from_agent`, `domain_from_setting`, `domain_unattributed`; the item 7 tests drop their hand-stamped domain.
- Owned files: `packages/core/neurosphere_core/agent_identity/**`, `packages/core/tests/agent_identity/**`, `services/workers/neurosphere_workers/agent_identity/**`, `services/workers/tests/agent_identity_worker/**`, `tests/integration/ingestion/test_agent_identity_resolution.py`.
- Depends on: items 6 and 7.
- Acceptance criteria: a real OTLP span (no domain) with an alias gets the `USES_MODEL` edge in the agent's domain; with no alias and the setting set it gets a draft in that domain; an event's own domain is never overwritten; a re-resolution that moves a contribution between domains leaves no stale points in the old domain.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends, `docs/runbooks/agent-identity-resolution.md` (what an alias is, derived ids, declaring and repointing, running re-resolution and reading its report, limits), mkdocs nav, regenerate Tier-3 (`openapi.json`, `docs/reference/**`, PRP index and status table), changelog fragment `changelog.d/PRP-137-telemetry-agent-identity-resolution.md`, completion note stating which PRPs consume the fix (74, 100, 134) and the product check: an OTLP agent shows an aggregate series and a map health value after the pipeline runs.
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/agent_identity services/workers/tests/agent_identity_worker services/workers/tests/projections services/workers/tests/worker_roles services/workers/tests/foundry_discovery_role services/workers/tests/evaluation_worker services/workers/neurosphere_workers/aggregates/tests services/api/tests/agent_identity_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, not CI): `docker compose up -d --wait`, then `uv run pytest -q -m integration tests/integration/ingestion/test_agent_identity_resolution.py` (use 127.0.0.1 endpoints; do not run two compose sessions at once).

## Migration and rollback
No schema change and no data migration. Events already archived keep their raw fields; the next worker read resolves them. Existing series keyed by a canonical id from a producer are untouched (`declared`). Rollback: remove the three wrappers (or set the TTL settings to zero, which makes every lookup go to the repository) or revert the PR; derived-id series created meanwhile become orphans that the 90-day aggregate window (`WINDOW_DAYS`) and prune job age out, and the draft agents stay as ordinary drafts a steward can deprecate.

## Live and open gates
None run here: in-memory twins and, locally, the emulators. A hosted check that an OTLP agent from a real producer gets a series is part of PRP-82's signed-in smoke and PRP-136's hosted runs; recorded OPEN until evidenced.

## NOT building
An alias for derived drafts; automatic merging of a draft into a registered agent; rewriting archived events; resolution of cost records or the ledger (they carry no agent id); a catalog-service hook that writes aliases on registration (PRP-76 may add it using `declare_agent_alias`); an automatic re-resolution trigger (follow-up); fuzzy matching of display names to agents; person aliases (forbidden by the Alias contract).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 6 and 9 accepted by the owner at plan approval 2026-11-22; row 8 decided 2026-11-16)

Plan approval 2026-11-22: item 5 runs after item 1 (it calls `declare_agent_alias`); item 5 keeps its own builder and also owns the builder-pinned files PRP-139 found: `services/api/tests/admin_identity_api/test_builder.py`, `services/api/tests/analytics_runtime/test_analytics_builder.py`, `docs/runbooks/system-settings.md`, `services/api/tests/runtime_routes/test_manifest_routes_serve.py`, plus the `services/api/openapi.json` and `docs/reference/**` regen. One reviewer pass covers the whole PRP diff before item 8.

Deviation (item 2, 2026-11-22): the worker test directory is `services/workers/tests/agent_identity_worker`, not `agent_identity`, because two top-level `agent_identity` test packages shadow each other in one pytest session (collection error). Ownership paths above are updated to match.

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-137-item1 | sonnet; 80bb2748 merged de870c2f; ruff+pyright clean, 176 passed (agent_identity+catalog) 2026-11-22 |
| 2 | merged | prp-137-item2 | sonnet; 08065343 merged 3afa5669; test dir renamed agent_identity_worker; ruff+pyright clean, 179 passed (core+worker agent_identity, projections, aggregates, evaluation) 2026-11-22 |
| 3 | merged | prp-137-item3 | sonnet; 82f3f154 merged 7f70ee92; ruff+pyright clean, 254 passed (agent_identity core+worker, projections, worker_roles, aggregates, evaluation) 2026-11-22 |
| 4 | merged | prp-137-item4 | sonnet; 2f9f5e99 merged 7a2c66eb; ruff+pyright clean, 265 passed; CLI dependency seam left for item 6 2026-11-22 |
| 5 | merged | prp-137-item5 | sonnet; e89901d2 + f3e21ff5 merged 717d906e; ruff+format+pyright clean in worktree; worktree 2005 passed, integration 2072 passed; review APPROVE 2026-11-22 |
| 6 | merged | prp-137-item6 | sonnet; 3d0135d3 merged 8965f003; agent cut off by a PC restart, gates re-run by orchestrator: ruff+pyright clean, 289 passed; post-merge 382 passed 2026-11-22 |
| 7 | merged | prp-137-item7 | sonnet; cef95b00 merged f05a5189; 188 passed, integration file collects 3; found the OTLP domain gap (clarification 10); emulator run pending 2026-11-22 |
| 6b | merged | prp-137-item6b | sonnet; 6cd83db8 merged 10d4b906; ruff+pyright clean, 405 passed post-merge; cross-domain re-resolution proven clean 2026-11-22; review APPROVE |
| 8 | merged | prp-137-item8 | sonnet docs b2c4855d merged 899f4972 (tests/docs 127 passed, mkdocs --strict clean); orchestrator 4a807b20 counters in /readyz (owner OK, supervisor.py outside ownership), 153 passed; emulator integration 3 passed; review APPROVE (8 non-blocking -> follow-ups) 2026-11-22; full workers 1120 passed; full api 2596 passed + 2 mcp_api load timeouts (66 passed alone); emulator ingestion commercial file times out on known EH throttle (untouched path); PR #375 CI green, squash-merged 261da0d2 2026-11-22 |

## Completion note (filled at ship)
- Date, PR: 2026-11-22, PR #375 squash-merged as `261da0d2` (CI green). Item merges on the integration branch: de870c2f (1), 3afa5669 (2), 7f70ee92 (3), 7a2c66eb (4), 717d906e (5), 8965f003 (6), f05a5189 (7), 10d4b906 (6b), 899f4972 + 4a807b20 (8). Independent review: APPROVE, no blockers.
- Deviations:
  - The worker test directory is `services/workers/tests/agent_identity_worker`: two top-level `agent_identity` test packages failed collection in one pytest session.
  - Item 6b was added (clarification 10, owner decision 2026-11-22). OTLP events carry no `domain_id`, so edges and drafts never fired for real OTLP traffic. The resolving sources now stamp a domain at read time: the agent's catalog domain for `alias`/`declared`, `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN` for `derived`, and never over an event's own domain.
  - `services/workers/neurosphere_workers/runtime/supervisor.py` (outside the declared ownership, with owner approval) reports a role's `counters()` under `counters` in `/readyz` (criterion 8). `CountersRole` forwards `idle_reason`.
  - Item 5 owned the builder-pinned files PRP-139 found (plan approval). Its route test was renamed `test_alias_routes.py` to avoid a basename clash with `admin_producers_api`.
  - The re-resolution CLI dependencies are built in `agent_identity/wiring.py` and `factories.py` (item 6), not in item 4.
  - Rollback text corrected: the aggregate window is 90 days (`WINDOW_DAYS`), not 7.
- Descoped items: none.
- Product check: an OTLP span through `map_span`, `process_batch`, the archive, the outbox and the aggregates and catalog projections gives a per-agent series, a `USES_MODEL` edge in the agent's domain and, without an alias, a draft agent. In-process tests and the local emulator variant (3 passed) both confirm it. The tests fail when resolution is removed. Map health for an OTLP agent then follows from PRP-74, which reads these series.
- Consumers: PRP-74 (map health for OTLP agents), PRP-100 (agent series beside tool and service series), PRP-134 (per-agent cost series), PRP-76 (undeclared-agent list reads the drafts).
- OPEN gates:
  - Hosted check that an OTLP agent from a real producer gets a series and map health (PRP-82 signed-in smoke, PRP-136); nothing was run against Azure.
  - Local emulator file `tests/integration/ingestion/test_pipeline_commercial.py` (not touched by this PRP) timed out at 420 of 1143 events on the known Event Hubs emulator throttle and backlog. It was not re-run on wiped volumes.
- Env vars for the operator: `NS_AGENT_IDENTITY_POSITIVE_TTL_SECONDS` (60), `NS_AGENT_IDENTITY_NEGATIVE_TTL_SECONDS` (15), `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS` (50000), and `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN` (unset: derived agents get no domain, so no draft and no edge). Runbook: `docs/runbooks/agent-identity-resolution.md`.
- Follow-up issues: #376 (alias repoint atomicity and retire-audit ordering), #377 (resolver single-flight, declared-id existence, Foundry alias counters in `/readyz`), #378 (automatic re-resolution trigger, indexed archive scan).
