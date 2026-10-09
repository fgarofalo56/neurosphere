---
name: prp-07-telemetry-ingestion-and-cost-ledger
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-01
depends_on: PRP-01, PRP-05
wave: W4
absorbs: P1.1
---

# PRP-07: Telemetry ingestion and cost ledger

## Goal

Ship the durable ingestion path and the cost ledger that everything downstream reads: an authenticated push endpoint (OTLP/JSON and CloudEvents) that checks producer identity and redacts before publishing to Event Hubs, a normalizer worker with a blob checkpoint store, validation, deduplication, watermarks and bounded retries, an explicit quarantine container with a replay CLI, a redacted archive, and a cost ledger plus outbox that feeds later projections without double counting gateway, application and billing observations. It is for the platform operator and for PRP-09, 10, 11, 14, 15 and 16, which consume its outputs. It lands in W4 because it needs the PRP-01 envelope contracts and the PRP-05 runtime, clients and compose app profile. The key correctness risk is cost double counting; that test is the centerpiece.

> NS-01: "Ingest OpenTelemetry traces/metrics and versioned CloudEvents through authenticated push and bounded polling connectors."

> NS-01 event envelope: "event_id, schema_version, event_time, ingestion_time, cloud, customer_id, domain_id, source_id, external_agent_id, canonical_agent_id when resolved, request_id, trace_id, span_id, parent_span_id, provider, model/version, environment, outcome, duration, token breakdown, data-source references, classification and sampling metadata. Missing fields remain null/unknown, never zero by default."

> NS-01: "Cost records distinguish estimated vs invoiced spend, currency, price version/effective date, cached tokens, retries, compute/PTU/reservation allocation and license/seat costs. Avoid double counting gateway, application and billing observations."

> NS-01: "At-least-once delivery with idempotency by source/event ID, schema compatibility, event-time watermarks, retry budgets, quarantine storage, replay and backpressure. Event Hubs has no built-in service-bus-style DLQ: implement quarantine explicitly. Redact before persistence and external transmission; prompt/response bodies disabled by default."

Bounded polling connectors are PRP-09; this PRP supplies the push edge and the pipeline they feed.

## Acceptance criteria

- [ ] Item 1: An unauthenticated producer gets 401; an authenticated producer whose identity does not match the claimed `source_id` or `customer_id` gets 403; an oversized body gets a size-limit error; a payload containing `prompt`/`response` fields is accepted with those fields dropped before publish; events are published to the Event Hubs emulator.
- [ ] Item 2: Fixtures for duplicates, out-of-order, malformed and mid-batch crash produce the correct records: duplicate (same source and `event_id`) stored once, out-of-order events land inside the watermark rules, malformed events go to quarantine, a crash and restart re-processes without double effect; no double-counted cost.
- [ ] Item 3: A poison event is isolated after 3 failed attempts; replaying a quarantined event is idempotent (second replay changes nothing); checkpoints advance only after durable accept or quarantine.
- [ ] Item 4: The archive contains no `prompt` or `response` fields (recursive scan test) and is partitioned by day and domain.
- [ ] Item 5: Given a gateway, application and billing observation of the same request, then exactly one cost record exists with all three observation references; estimated and invoiced amounts stay distinct; unknown token counts remain null; every record carries a price version id.
- [ ] Item 6: Commercial and Government SDK configuration tests pass against the emulator and with static endpoint assertions; any live run is gated by `NS_LIVE_APPROVED`.
- [ ] PRP exit: `verify-gates.ps1 -Mode full` green; `pytest -m integration` for ingestion passes against compose; one reviewer pass approves (review: required, one rework round max); `python scripts/validate_planning.py` shows no failure attributable to this file.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| C1 | Model and review | opus + review; sonnet + review | **sonnet, review required** (master table; decision D6). Review focuses on idempotency, redaction and double counting. One pass, max one rework round. |
| C2 | Producer identity on Event Hubs | Entra on the hub; ingest edge | **Enforced at the ingest edge.** The Event Hubs emulator lacks Entra (SAS only), so identity is checked by the push endpoint (Entra token or registered producer credential) and the edge stamps `source_id`; nothing else may publish to the hub. Emulator-vs-live delta recorded for G12. |
| C3 | Dead-letter handling | Service Bus style DLQ; explicit quarantine | **Explicit quarantine container** (Blob/Azurite) with envelope, failure reason code, attempt count and original offset; replay CLI re-injects through the edge pipeline. Event Hubs has no DLQ. |
| C4 | Checkpoint rule | after receive; after durable accept or quarantine | **Only after durable accept (ledger/archive/outbox written) or after quarantine write.** Never before. Checkpoint store is the blob store (azure-eventhub-checkpointstoreblob-aio 1.2) on Azurite locally. |
| C5 | Projection transport | Cosmos change feed; outbox collection | **Outbox collection with per-sink checkpoints.** The "all versions and deletes" change feed needs a preview API version, continuous backup and no prior partition merge (RESEARCH-AND-GATES, 2026-06-17), and the emulator is not a faithful substitute. Outbox is the baseline. |
| C6 | Dedupe key | event_id only; source + event_id | **(`source_id`, `event_id`)** within `customer_id`; the first write wins and later duplicates are counted in a metric, not stored. |
| C7 | Watermark and lateness | none; event-time watermark | **Per-source event-time watermark with a configured lateness window** (default stated in settings, not hard-coded in logic). Late events beyond the window are accepted but flagged `late=true` and excluded from hot-aggregate recomputation until reprocessed; they are never silently dropped. |
| C8 | Retry budget | unlimited; bounded | **3 attempts then quarantine** with exponential backoff and jitter via the PRP-05 runtime. |
| C9 | Payload bodies | keep; drop | **Drop `prompt`/`response` bodies by default** at the edge, before any persistence or publish; an operator opt-in is a later policy gate (G06), not this PRP. Pseudonymize people identifiers before archive. |
| C10 | Redaction scope | edge only; edge + archive | **Edge redaction plus an archive-time scan test.** Redaction runs before publish (edge), and the normalizer re-checks (defense in depth) before archive and ledger writes. |
| C11 | Cost double counting rule | sum all; reconcile by request | **One cost record per `(customer_id, request_id)` per cost category.** Observations from gateway, application and billing attach as `observations[]` with `observation_kind`; the authoritative amount is chosen by a documented precedence: invoiced > gateway-metered > application-estimated, with the others retained as evidence. Billing aggregates without request granularity attach at vendor/period granularity as separate `allocation` records, flagged `granularity=vendor_period`, never merged into per-request records. |
| C12 | Estimated vs invoiced | single amount; two fields | **Two distinct fields, never summed or substituted.** Unknown stays null; null/unknown is never 0. |
| C13 | Price source | hard-coded; versioned table | **Versioned price table** (`price_version_id`, effective date, currency, source). Records cite the version; projections later cite it too. Table content for tests is synthetic. |
| C14 | OTLP/JSON mapping | full OTLP; documented subset | **Documented subset**: traces (spans with parent ids, status, attributes) and metrics (sum, gauge) in OTLP/JSON; CloudEvents structured mode with a NeuroSphere event type namespace. Protobuf OTLP is not accepted in this PRP. |
| C15 | Live gates | live Commercial run; emulator only | **Emulator for all items.** A live Commercial run (Event Hubs with Entra, real Cosmos) is **operator-approved, requires NS_LIVE_APPROVED=1** and is optional here; if not run it is recorded OPEN. |
| C16 | Government | assume parity; disabled-with-reason | **Profile tests only.** Government endpoints come from the PRP-05 `CloudProfile`; Event Hubs data geo-replication is GA on Premium and Dedicated only with Government support unverified; no parity claim. |

## Context manifest

### Files that matter

- `PRP.md` sections 1-3; `docs/PRD.md` NS-01 (quoted above) and section 3 scale profiles (pilot 1k agents/1k events per second; enterprise 10k sustained; stress 50k sustained, 150k burst: load suites are PRP-21).
- `docs/ARCHITECTURE.md` diagram 2 (redact and authenticate -> Event Hubs -> validate normalize deduplicate -> archive, quarantine, analytics and cost ledger, catalog projection, hot aggregates) and the paragraph: "Offset/checkpoint advancement follows durable acceptance or quarantine. Separate sink checkpoints/idempotent projection reconcile partial writes; no fictional cross-store transaction. Source billing freshness differs from instrumented trace freshness."
- `docs/adr/0002-stack-pins.md`: azure-eventhub 5.15, azure-eventhub-checkpointstoreblob-aio 1.2 (last release 2025-02), azure-cosmos 4.17, cloudevents 2.2, jsonschema 4.26 (draft 2020-12), opentelemetry-sdk 1.45, FastAPI 0.143, Pydantic 2.14, hypothesis 6.168 (dev-only, MPL-2.0), pytest 9.1 / pytest-asyncio 1.4.
- `docs/RESEARCH-AND-GATES.md`: Event Hubs metadata geo-DR copies neither payloads nor RBAC; emulator facts; change feed mode caveat; G04 (provider coverage, PRP-09), G06 (payload opt-in and retention, PRP-23), G12.
- `docs/DECISIONS-LOG.md` D6, D7, D8, D11.
- `docker-compose.yml` (cosmos, azurite, eventhubs services; `app` profile from PRP-05), `infra/compose/eventhubs.config.json` (hub and consumer group definitions; this PRP reads it, does not edit it), `.claude/hooks/config.ps1`, `.env.example` (names only), `pyproject.toml` (markers), `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/telemetry/`, `schemas/cost/`, generated Pydantic models (`TelemetryEvent`, `CostRecord`), `tests/contracts/` fixtures.
- Created by PRP-05: `packages/core/neurosphere_core/{errors,scope,paging,cloud,observability,clients}/`, `services/api/neurosphere_api/app.py` router registry, `services/workers/neurosphere_workers/runtime/` (including `CheckpointStore` protocol).
- Created by PRP-03: `sandbox/` generator (duplicates, out-of-order, malformed events and seeded anomalies) and `scripts/sandbox/` seed and replay CLI; the sandbox output is this PRP's main fixture source.
- Created by PRP-06 (if merged first; not a dependency): `require(permission)`; the ingest edge does its own producer authentication meanwhile and must not import PRP-06 modules.
- Consumed later: PRP-09 connectors push through the edge; PRP-10 consumes the outbox; PRP-11 consumes normalized events; PRP-14 consumes ledger aggregates; PRP-21 adds admission control to the edge; PRP-23 adds lifecycle rules over archive.

### Patterns to match

No product code exists yet, so these are rules.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for internal records; the ingress envelope uses the generated contract model and permits only documented extension attributes.
- FastAPI router at `services/api/neurosphere_api/ingest/router.py` registered via the PRP-05 registry; handlers are thin and call a service object that is also unit-testable without HTTP.
- Workers built on the PRP-05 runtime; every worker is a pure `process_batch(events) -> BatchResult` function wrapped by the runtime so tests call it directly with fake stores.
- Async Azure clients only from `neurosphere_core.clients`; error taxonomy from `neurosphere_core.errors` (`invalid_schema` for malformed events, `dependency_transient` for retryable store failures, `rate_limited` for edge throttling).
- Tests beside packages plus `tests/integration/ingestion/`; `pytest.mark.integration` for emulator tests; `pytest.mark.live` for cloud tests; hypothesis allowed for dedupe/ordering properties (dev-only).
- Idempotent writes use deterministic document ids derived from (`customer_id`, `source_id`, `event_id`) so a retry overwrites with an equal document rather than adding.

### Conventions

- ruff (line 100, py312, S rules on) and pyright standard; conventional commits (`feat(ingest): ...`); owned-file discipline; evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Reason codes for quarantine are a closed enum in one module; free-text reasons are not stored.
- Metric names come from the PRP-05 observability constants; add new names only through PRP-05 owned files or a documented follow-up, not locally.
- Forward slashes in commands; Python is `python`; temp files in `temp/`.

### Gotchas

- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.

PRP-specific gotchas:

- The caller's `customer_id`, `domain_id` and `cloud` in the payload are claims to be checked against the authenticated producer registration, not trusted values; the edge overwrites or rejects on mismatch. This is the ingest-side form of "caller-supplied scope is ignored".
- Emulator Event Hubs has no persistence across restarts and one namespace/ten hubs; do not design tests that depend on retained offsets after a container restart, and do not rely on emulator behavior for partition counts beyond what `infra/compose/eventhubs.config.json` declares.
- Event Hubs consumers read at-least-once; the normalizer must tolerate redelivery after a crash between ledger write and checkpoint (this is exactly the crash fixture).
- Event ordering is per partition only; partition key should be (`customer_id`, `source_id`) so a source's events stay ordered; do not assume cross-source order.
- Missing numeric fields must stay null in storage and in the ledger; arithmetic with null yields null (unknown), not 0. A property test asserts totals over partially-unknown sets are reported with `coverage` and not as complete totals.
- OTLP attribute names for tokens and models vary by instrumentation version; the mapping table lives in one module with a documented fallback to null, never a guessed value.
- Currency: never sum across currencies; ledger rows carry ISO currency and aggregates group by it.
- Cached tokens, retries and PTU/reservation/seat allocations are separate fields or allocation records; do not fold them into the per-request token cost.
- Billing/provider freshness is connector-dependent and not sub-10s; the ledger stores `observed_at` and `period_end` so freshness is explicit.
- Azurite Table API is preview; use Blob only for checkpoints, archive and quarantine; Cosmos for ledger and outbox.
- Replay must pass through the same redaction and validation as live ingestion; it never writes directly to the ledger.
- A body-size cap is a security control at the edge; set it before parsing JSON, and reject deeply nested payloads (depth limit) to avoid parser DoS.

### External references

- OTLP specification (JSON encoding): https://opentelemetry.io/docs/specs/otlp/ (opentelemetry-sdk 1.45, ADR-0002, observed 2026-10-08).
- CloudEvents spec 1.0.2 and Python SDK 2.2: https://github.com/cloudevents/spec and https://pypi.org/project/cloudevents/ (ADR-0002).
- Event Hubs checkpointing and Python: https://learn.microsoft.com/azure/event-hubs/event-hubs-python-get-started-send (azure-eventhub 5.15).
- Event Hubs emulator: https://learn.microsoft.com/azure/event-hubs/overview-emulator (2026-08-26; SAS only, no persistence, requires Azurite, GA unverified).
- Event Hubs geo-DR caveat: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06) and data geo-replication https://learn.microsoft.com/azure/event-hubs/geo-replication (2026-07-11; Premium and Dedicated only, Government unverified).
- Cosmos DB change feed modes: https://learn.microsoft.com/azure/cosmos-db/change-feed-modes (2026-06-17; why the outbox is the baseline).
- Cosmos DB vNext emulator limits: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
- Cosmos DB hierarchical partition keys: https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys (2026-04-27; Python SDK >=4.6, new containers only).
- Azure Government service endpoints: https://learn.microsoft.com/azure/azure-government/compare-azure-government-global-azure (observed 2026-10-08).
- Azure Retail Prices API (price table source for later PRPs): https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices.

## Implementation blueprint

Shared must-not-touch for every item (the "shared list"): root `pyproject.toml`, `docker-compose.yml`, `infra/compose/`, `docs/RESEARCH-AND-GATES.md`, `packages/contracts/**` (PRP-01), `packages/core/neurosphere_core/{errors,scope,paging,cloud,observability,clients,auth,audit}/`, `services/api/neurosphere_api/{main.py,app.py,middleware/,health/,authz/,audit/}`, `services/workers/neurosphere_workers/runtime/` (PRP-05, PRP-06; import only), `frontend/**`, `.github/workflows/**`. Dependencies are added in one serialized integrator commit.

### Item 1 — ingest-edge-api  [P]
- Deliverable: authenticated push endpoints for OTLP/JSON (`/v1/ingest/otlp/traces`, `/metrics`) and CloudEvents (`/v1/ingest/events`), producer registry check (identity -> allowed `source_id`, `customer_id`, `cloud`), body-size and nesting limits, redaction and body-dropping, schema validation against the PRP-01 envelope, publisher to Event Hubs with partition key, per-request result with accepted/rejected counts.
- Owned files (may edit): `services/api/neurosphere_api/ingest/`, `services/api/tests/ingest/`.
- Must NOT touch: `services/workers/neurosphere_workers/{ingestion,quarantine,archive,projections}/` (items 2-5), `packages/core/neurosphere_core/ledger/` (item 5), `tests/integration/ingestion/` (item 6), `scripts/replay/`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - No credential returns 401; valid credential with mismatched `source_id`/`customer_id`/`cloud` returns 403 and publishes nothing.
  - A body with `prompt` or `response` attributes (any depth) is published without them; the response lists `dropped_fields` counts only, not values.
  - Body over the size limit and payload over the nesting limit return the documented taxonomy errors before parsing completes; throttling returns `rate_limited` with `Retry-After`.
  - Invalid-schema events in a batch are rejected individually with reason codes; valid ones are accepted (partial success is explicit).
- Pattern references: C2, C9, C10, C14; thin router rule.
- Tests to write: `services/api/tests/ingest/test_auth.py`, `test_redaction.py`, `test_limits.py`, `test_otlp_mapping.py`, `test_cloudevents.py`.

### Item 2 — normalizer-worker  [P]
- Deliverable: Event Hubs consumer on the PRP-05 runtime with blob checkpoint store, validate (envelope, schema compatibility by `schema_version`), normalize (OTLP mapping to envelope), deduplicate (`source_id`, `event_id`), event-time watermark and late flag, bounded retries (3), hand-off interfaces to quarantine (item 3), archive (item 4) and ledger/outbox (item 5) via protocols defined in this item.
- Owned files (may edit): `services/workers/neurosphere_workers/ingestion/`, `services/workers/tests/ingestion/`.
- Must NOT touch: `services/workers/neurosphere_workers/{quarantine,archive,projections}/` (items 3-5; call through protocols only), `packages/core/neurosphere_core/ledger/` (item 5), `services/api/**`, `services/workers/neurosphere_workers/runtime/` (PRP-05); plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - Duplicate fixture (same source and event id, twice and across a restart) yields one stored record and a duplicate metric.
  - Out-of-order fixture within the lateness window is accepted in event-time order for watermark purposes; beyond the window it is accepted with `late=true`, never dropped.
  - Malformed fixture is handed to quarantine with a closed-enum reason; a crash between sink write and checkpoint re-processes and yields no double effect (idempotent doc ids).
  - Missing optional fields are stored as null; a property test shows no field defaults to 0.
- Pattern references: C4, C6-C8; pure `process_batch` rule.
- Tests to write: `services/workers/tests/ingestion/test_dedupe.py`, `test_watermark.py`, `test_malformed.py`, `test_crash_replay.py`, `test_null_semantics.py`.

### Item 3 — quarantine-and-replay
- Deliverable: quarantine writer (Blob container, envelope + reason + attempts + original offset, redacted), poison isolation after 3 attempts, `replay` CLI (list, inspect, replay by id or filter, dry-run) that re-injects through the validation and redaction pipeline, idempotency markers.
- Owned files (may edit): `services/workers/neurosphere_workers/quarantine/`, `scripts/replay/`, `services/workers/tests/quarantine/`.
- Must NOT touch: `services/workers/neurosphere_workers/{ingestion,archive,projections}/`, `packages/core/neurosphere_core/ledger/`, `services/api/**`; plus the shared list.
- Depends on: item 2.
- Acceptance criteria:
  - A poison event fails 3 attempts then lands in quarantine and does not block the partition (next event processed, checkpoint advances after the quarantine write).
  - Replaying the same quarantined event twice produces one ledger effect (idempotent), and the second run reports "already replayed".
  - Replay refuses events whose redaction check fails, and dry-run changes nothing.
  - Quarantined payloads contain no prompt/response bodies (scan test).
- Pattern references: C3, C4, C8; replay-through-pipeline gotcha.
- Tests to write: `services/workers/tests/quarantine/test_poison.py`, `test_replay_idempotent.py`, `test_cli.py`.

### Item 4 — redacted-archive
- Deliverable: Blob archive writer of redacted normalized events, partitioned `customer/domain/yyyy/mm/dd`, manifest per partition-day, compression, content hashes; pseudonymized identifiers.
- Owned files (may edit): `services/workers/neurosphere_workers/archive/`, `services/workers/tests/archive/`.
- Must NOT touch: `services/workers/neurosphere_workers/{ingestion,quarantine,projections}/`, `packages/core/neurosphere_core/ledger/`, `services/api/**`; plus the shared list.
- Depends on: item 2.
- Acceptance criteria:
  - Recursive scan of archive output finds no `prompt` or `response` fields at any depth and no raw person identifiers.
  - Partitions are by day and domain; the same event written twice produces one blob entry (idempotent).
  - Archive path never mixes `cloud` or `customer_id` values; a test asserts a Government-tagged event cannot be written under a Commercial-configured account.
- Pattern references: C9, C10; idempotent id rule.
- Tests to write: `services/workers/tests/archive/test_redaction_scan.py`, `test_partitioning.py`, `test_idempotent_write.py`, `test_cloud_isolation.py`.

### Item 5 — cost-ledger-and-outbox
- Deliverable: ledger model and writer (cost records, observations, allocation records, price version table), double-count resolver with documented precedence, outbox collection writer and reader with per-sink checkpoints, `LedgerReader` protocol for later aggregates.
- Owned files (may edit): `packages/core/neurosphere_core/ledger/`, `services/workers/neurosphere_workers/projections/outbox/`, `packages/core/tests/ledger/`, `services/workers/tests/outbox/`.
- Must NOT touch: `services/workers/neurosphere_workers/{ingestion,quarantine,archive}/`, `services/workers/neurosphere_workers/projections/catalog/` (PRP-10), `services/workers/neurosphere_workers/projections/` other subfolders, `services/api/**`; plus the shared list.
- Depends on: item 2.
- Acceptance criteria:
  - Given gateway, application and billing observations for one `request_id`, exactly one cost record exists, listing three observation references; precedence invoiced > gateway-metered > application-estimated determines the amount; rerunning in any order yields the same record.
  - Estimated and invoiced amounts are separate fields; neither substitutes for the other; null stays null; currency is never mixed.
  - Every record cites `price_version_id`; a record with an unknown version is stored flagged `price_unresolved` and excluded from totals with coverage reported.
  - Outbox entries are written in the same logical operation as the ledger upsert via idempotent ids; per-sink checkpoints advance independently; a sink failure does not roll back others; a restart replays from the sink's checkpoint without duplicate effect.
- Pattern references: C5, C11-C13; outbox rule.
- Tests to write: `packages/core/tests/ledger/test_double_count.py`, `test_estimated_vs_invoiced.py`, `test_price_version.py`, `services/workers/tests/outbox/test_sink_checkpoints.py`, `test_outbox_idempotent.py`.

### Item 6 — cloud-profile-tests
- Deliverable: integration suite proving the full path on compose (push -> hub -> normalizer -> archive/ledger/outbox, plus quarantine and replay) for the Commercial profile, and static plus emulator-backed configuration tests for the Government profile; sandbox fixtures drive duplicates, out-of-order and malformed cases; gated live module.
- Owned files (may edit): `tests/integration/ingestion/`.
- Must NOT touch: every non-test path (items 1-5); `tests/integration/health/`, `tests/integration/clients/`, `tests/integration/compose/` (PRP-05); `tests/security/**`; plus the shared list.
- Depends on: items 1-5.
- Acceptance criteria:
  - Commercial and Government profile tests pass against the emulator; the Government test asserts endpoint suffixes (`*.servicebus.usgovcloudapi.net`, `*.documents.azure.us`) from `CloudProfile` and that no Commercial host is configured.
  - End-to-end test: sandbox bundle in, expected counts out (stored, deduplicated, quarantined, late-flagged), cost totals with coverage, zero prompt/response fields anywhere.
  - Live module is marked `live`, skipped only with an explicit OPEN message, and cannot run without `NS_LIVE_APPROVED=1`.
- Pattern references: `pytest.mark.integration`, `pytest.mark.live`; C15, C16.
- Tests to write: `tests/integration/ingestion/test_pipeline_commercial.py`, `test_profile_government.py`, `test_double_count_e2e.py`, `test_live_commercial.py`.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
uv sync --frozen
uv run ruff check packages services scripts tests
uv run pyright
uv run pytest packages/core/tests/ledger services/api/tests/ingest services/workers/tests -m "not integration and not live"
docker compose --profile app up -d --wait
uv run pytest tests/integration/ingestion -m integration
docker compose --profile app down
```

Optional live run for the Commercial profile (real Event Hubs with Entra, real Cosmos): **operator-approved, requires NS_LIVE_APPROVED=1**; run it through a `scripts/gates/` wrapper only after the operator approves cost and subscription. Do not run it by default.

## Live and open gates

| Gate | Touch | Evidence that narrows it |
|---|---|---|
| G12 emulator parity | Narrows | Recorded deltas: no Entra on Event Hubs emulator (edge enforcement tested instead), no persistence across restarts, no RU accounting or index behavior on Cosmos emulator |
| G04 provider/API/license coverage | Feeds | Ledger records granularity labels; connector coverage evidence is PRP-09 |
| G06 privacy/retention/legal hold | Feeds | Body dropping and redaction tests; retention and opt-in policy are PRP-23 |
| G07 workload/SLO/DR | Feeds | No load claim made; PRP-21 measures throughput; Event Hubs metadata geo-DR caveat documented |
| G01 service/feature/region/SKU matrix | Not closed | Government Event Hubs data geo-replication support unverified |

Open items to carry: real Event Hubs with Entra authentication, real Cosmos partition behavior and throughput, and Government-profile runtime behavior have not run.

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Bounded polling connectors and reference connectors (PRP-09); billing reconciliation views (PRP-14).
- Analytics adapters and warehouse writes (PRP-11); catalog evidence projection and curation (PRP-10).
- Hot aggregates and dashboards (PRP-14); admission control and per-domain quotas (PRP-21).
- Retention, deletion, legal hold and payload opt-in policy (PRP-23); user-facing authorization (PRP-06).
- Protobuf OTLP, OTLP/gRPC, or any endpoint agent.
- Sampled evaluation workers (PRP-16); pricing projections and right-sizing (PRP-15).
- Any claim of complete spend observability, per-user cost attribution, or sub-10s provider billing freshness.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Reviewer verdict (one pass, max one rework round):
- Deviations from blueprint and why:
- Descoped items:
- Open gates / untested live items:
- Follow-ups:
