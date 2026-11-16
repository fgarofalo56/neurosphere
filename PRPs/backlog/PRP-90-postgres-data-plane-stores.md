---
name: PRP-90-postgres-data-plane-stores
status: backlog
priority: P1
order: 81
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-01, NS-02
depends_on: [PRP-88-worker-composition-seam-event-and-object-ports, PRP-89-postgres-foundation-catalog-and-security-stores]
wave: W27
branch: prp-90-postgres-data-plane-stores
allow_parallel: true
issues: []
---

# PRP-90: PostgreSQL data-plane stores

## Goal
Give the ingest-to-aggregate path a PostgreSQL implementation: the cost ledger and allocations, per-agent aggregates, the outbox and its projection and runtime checkpoints, the ingestion accepted-marker and watermark stores, the catalog candidate quarantine, price snapshots, and the lifecycle delete backends for the catalog and the ledger. Each is written against the existing Protocol, must behave like its Cosmos implementation (idempotency keys, outbox ordering and at-least-once reads, optimistic concurrency, customer and domain scoping), and is proven by a conformance module that also runs on the in-memory implementation. After this PRP the worker roles ingestion, projections, aggregates and lifecycle run end to end on PostgreSQL with in-memory streaming. It is for operators on AWS, GCP and on-prem Kubernetes (RDS, Cloud SQL or in-cluster PostgreSQL), and for PRP-92, PRP-96 and PRP-98, which need a complete non-Azure data plane.

Out of scope: the PostgreSQL pool, schema generator, migration runner, TTL sweeper, `PgCollection` helper, the catalog `DocBackend` and the security stores (PRP-89); the control-plane stores and full-text search (PRP-91); the worker composition seam and the `EventConsumer` and `ObjectStore` ports (PRP-88); Kafka and S3 or GCS (PRP-92); IAM database token providers (PRP-94); Helm values and settings rendering (PRP-96); migrating data from a Cosmos deployment (OPEN, new installs only). This PRP adds no dependency; it uses `asyncpg` through the `neurosphere_adapters_postgres` package that PRP-87 scaffolds and PRP-89 fills.

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." with "provider-specific managed-service substitutions ... behind a common abstraction layer".
- v1.2 excluded it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting, classified/air-gapped deployment ... outside the initial baseline"), `PRP.md:7`. Owner decision 2026-11-16: all four targets, on one portable backend set (ASSUMPTION D-2 below). PRP-85 amends the v1.2 lines.
- The data plane is the product's core path and every store is Cosmos-bound: `CosmosLedgerStore` (`packages/core/neurosphere_core/ledger/cosmos.py:32`), `CosmosAggregateStore` (`aggregates/cosmos.py:58`), `CosmosOutboxStore` and `CosmosCheckpointStore` (`services/workers/neurosphere_workers/projections/outbox/stores.py:108,163`), `CosmosAcceptedMarkerStore` and `CosmosWatermarkStore` (`ingestion/cosmos_stores.py:47,83`), `CosmosRuntimeCheckpointStore` (`runtime/checkpoint.py:37`), `CosmosCandidateQuarantine` (`projections/catalog/quarantine_cosmos.py:22`), `CosmosPriceSnapshotStore` (`pricing/cosmos_store.py:95`).
- Semantics ride on Cosmos facts that PostgreSQL must reproduce on purpose: the outbox orders by the server `_ts` seconds with a settle window and whole-`_ts` groups (`outbox/stores.py:119-155`), writes are `IfNotModified` on `_etag` (`ledger/cosmos.py:55-66`), creates rely on 409 for first-write-wins (`outbox/stores.py:114-118`, `ingestion/cosmos_stores.py:70-75`), and the price store is a synchronous Protocol (`pricing/store.py`) always called off the loop (`runtime/factories.py:380`, `runtime/builders/admin_platform.py:101-118`).
- Only three store families have a shared conformance module today (`packages/core/tests/{pricing,evaluation,recommendations}_cosmos/conformance.py`, plus `packages/core/tests/catalog/repo_conformance.py`). The ledger, aggregates, outbox, checkpoints, ingestion stores, quarantine and lifecycle delete backends have none, so "behaves like Cosmos" is unproven until this PRP writes them.
- Lifecycle delete backends catch Cosmos exceptions in neutral modules (`core/ledger/lifecycle_delete.py:19`, `core/catalog/lifecycle_delete.py:20`) and take a raw container, so a PostgreSQL deployment cannot honour deletion requests without a twin.

## Acceptance criteria
- [ ] Given each store below, When its conformance `CHECKS` run against `InMemory*` and against the PostgreSQL implementation (marker `portable`, compose PostgreSQL), Then both pass with identical results; each module also ships one deliberately broken implementation that fails a named check.
- [ ] Given two customers using identical ids, When any read, list, write, delete, prune, replace or advance runs for customer A, Then customer B's rows are never returned or changed; every statement binds the customer (and the domain wherever the Cosmos query filtered on it) as parameters, never by string formatting.
- [ ] Given `LedgerStore.write_entry(entry, None)` for an existing id, Then it returns False; given a stale `expected_version`, Then False and the stored row is unchanged; given the current version, Then True and the version changes. `put_allocation` is idempotent by id.
- [ ] Given `OutboxStore.append` of the same `(customer_id, id)` twice or from two concurrent tasks, Then exactly one returns True. Given `read_after(customer, cursor, limit)`, Then entries come back strictly after the cursor in `(ts, id)` order, never skipped and never duplicated across successive pages, and an entry committed inside the settle window is not returned until the window passed (the at-least-once guarantee the projection reader depends on).
- [ ] Given `CheckpointStore.advance` called concurrently with different cursors, Then the stored cursor is the maximum and never moves backwards; the runtime checkpoint `commit` is last-write-wins and survives a restart, and its ids stay apart from sink checkpoints (the `rt-` and `ckpt-` prefixes).
- [ ] Given `AcceptedMarkerStore.mark_accepted` twice, Then True then False; `WatermarkStore.advance` is monotonic and returns the resulting maximum under concurrency.
- [ ] Given `PriceSnapshotStore.put` of an existing id with the same content hash, Then False; with a different hash, Then `SnapshotConflictError`; the existing `packages/core/tests/pricing_cosmos/conformance.py` runs unchanged against the PostgreSQL store.
- [ ] Given a deletion request for ledger or catalog records, Then the PostgreSQL `DocumentBackend` twins read, page by data class with keyset paging (`id > after`), remove idempotently and project exports exactly like the Cosmos backends, and never touch an audit container.
- [ ] Given the worker roles ingestion, projections, aggregates and lifecycle built through PRP-88's registry with kinds `postgres`, in-memory event stream and in-memory object store, When a synthetic telemetry batch is ingested, Then ledger totals and aggregate documents equal those of the all-in-memory run (equivalence test).
- [ ] No generated SQL from model or user input: every statement is a fixed template with allowlisted identifiers and parameters; no secret, connection string or DSN appears in logs, errors or audit.
- PRP exit: touched suites, `tests/conformance/documents_dataplane`, `tests/conformance/outbox`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; the `portable-conformance` workflow (PRP-89) discovers and runs the new directories without edits.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | ASSUMPTION: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | ASSUMPTION: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| 3 | Outbox ordering key | PostgreSQL sequence; server timestamp seconds like `_ts` | ASSUMPTION: keep the existing `Cursor(ts, entry_id)` contract. `ts` is epoch seconds from the database clock at insert, stored in an additive column and index `(customer_id, ts, id)`; reads use the same settle window as Cosmos (`DEFAULT_SETTLE_SECONDS`, 5) and the database clock, and writer sessions set `idle_in_transaction_session_timeout` and `statement_timeout` below the settle window, so a transaction that took its `ts` earlier cannot commit behind a cursor that already passed it. A sequence alone would reorder under concurrent commits |
| 4 | Entry version / ETag | `xmin`; random token | The version string is the foundation's `etag` column (PRP-89 `PgCollection`), a fresh random token per write; never `xmin` (it changes on unrelated vacuum-free updates and is not stable across dump and restore) |
| 5 | Price snapshots: bridge or async Protocol | thread bridge; make the Protocol async | ASSUMPTION: keep the synchronous Protocol. Its callers already run it through `asyncio.to_thread` (`runtime/builders/admin_platform.py`, `runtime/factories.py:380`), so the store submits coroutines to the owning loop with `asyncio.run_coroutine_threadsafe` and raises if called from the loop thread (deadlock guard). Making it async would touch `admin/platform/price_sheet.py`, `recommendations/pipeline.py` and `right_sizing.py` |
| 6 | Cross-customer scans | forbid; keep bounded | Keep what the Protocols already do and no more: price snapshots are a global bounded list (`MAX_SNAPSHOTS`, error `price_set_too_large`); everything else is customer-scoped |
| 7 | Registration | edit PRP-88's lazy table; own module | `neurosphere_adapters_postgres/registry/dataplane.py`, which PRP-89 pre-creates and hands over (its `register_worker` is reached through PRP-89's `registration.py`, which PRP-88's lazy table imports for kind `postgres`), so no Tier-1 file is touched |
| 8 | Cut line if the session overruns | descope last item | Price snapshots last; see `## Cut line` |
| 9 | Compose lane in W27 | parallel; serialized | This PRP is the W27 compose-stack holder: it runs the portable PostgreSQL fragment first; PRP-91 and then PRP-94 run their compose-backed gates only after this PRP released it. Each uses unique schema names per test module; no file is shared |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/ledger/store.py` - `LedgerStore`, `InMemoryLedgerStore`; `ledger/cosmos.py` - `CosmosLedgerStore` (doc_type `entry` and `allocation`); `ledger/service.py:60` - `StoreLedgerReader`, which reads through any `LedgerStore` (so no separate `LedgerReader` implementation is needed).
- `packages/core/neurosphere_core/aggregates/store.py` and `aggregates/cosmos.py` - `AggregateReader`, `AggregateStore`, query shapes, `replace_bucket`, `prune`, `status`.
- `services/workers/neurosphere_workers/projections/outbox/{stores,models,reader,sink}.py` - protocols, `Cursor`, settle window, per-sink checkpoint ids. After PRP-88 the Cosmos classes sit in a sibling module.
- `services/workers/neurosphere_workers/runtime/checkpoint.py` - runtime `CheckpointStore`, `rt-` ids.
- `services/workers/neurosphere_workers/ingestion/{protocols,cosmos_stores,fakes}.py` - markers, watermarks, fakes to mirror.
- `services/workers/neurosphere_workers/projections/catalog/{quarantine,quarantine_cosmos}.py`.
- `packages/core/neurosphere_core/pricing/{store,cosmos_store}.py` and `packages/core/tests/pricing_cosmos/conformance.py`.
- `packages/core/neurosphere_core/lifecycle/adapters.py:28` (`DocumentBackend`), `ledger/lifecycle_delete.py`, `catalog/lifecycle_delete.py`, `lifecycle/rules.py` (`is_audit_container`).
- `packages/core/neurosphere_core/stores/containers.py` - specs for `cost-ledger`, `aggregates`, `outbox`, `outbox-checkpoints`, `ingestion-accepted`, `ingestion-watermarks`, `catalog_quarantine`, `price_snapshots` (partition paths `/customer_id`, `/customer_id`+`/domain_id`, `/snapshot_id`).
- `PRPs/backlog/PRP-89-postgres-foundation-catalog-and-security-stores.md` and `PRP-88-worker-composition-seam-event-and-object-ports.md` - "Interfaces provided".

### Store inventory
| Store | Protocol | Cosmos implementation it must match | Conformance module (`tests/conformance/documents_dataplane/` unless noted) |
|---|---|---|---|
| Ledger entries, allocations | `LedgerStore` `core/ledger/store.py:25` (reader: `LedgerReader` `ledger/totals.py:124`, implemented over any store by `StoreLedgerReader` `ledger/service.py:60`) | `CosmosLedgerStore` `ledger/cosmos.py:32` | `ledger_checks.py` (new) |
| Aggregates | `AggregateStore` `core/aggregates/store.py:136` (extends `AggregateReader`) | `CosmosAggregateStore` `aggregates/cosmos.py:58` | `aggregates_checks.py` (new) |
| Outbox | `OutboxStore` `wrk/projections/outbox/stores.py:41` | `CosmosOutboxStore` `:108` | `tests/conformance/outbox/outbox_checks.py` (new) |
| Projection checkpoints | `CheckpointStore` `wrk/projections/outbox/stores.py:54` | `CosmosCheckpointStore` `:163` | `tests/conformance/outbox/checkpoint_checks.py` (new) |
| Runtime checkpoints | `CheckpointStore` `wrk/runtime/checkpoint.py:19` | `CosmosRuntimeCheckpointStore` `:37` | `tests/conformance/outbox/runtime_checkpoint_checks.py` (new) |
| Accepted markers, watermarks | `AcceptedMarkerStore` `wrk/ingestion/protocols.py:47`, `WatermarkStore` `:60` | `CosmosAcceptedMarkerStore` `ingestion/cosmos_stores.py:47`, `CosmosWatermarkStore` `:83` | `ingestion_checks.py` (new) |
| Candidate quarantine | `CandidateQuarantine` `wrk/projections/catalog/quarantine.py:38` | `CosmosCandidateQuarantine` `quarantine_cosmos.py:22` | `quarantine_checks.py` (new) |
| Price snapshots | `PriceSnapshotStore` `core/pricing/store.py` (synchronous) | `CosmosPriceSnapshotStore` `pricing/cosmos_store.py:95` | existing `packages/core/tests/pricing_cosmos/conformance.py`, loaded by file path |
| Lifecycle delete, ledger | `DocumentBackend` `core/lifecycle/adapters.py:28` | `LedgerLifecycleBackend` `ledger/lifecycle_delete.py:57` | `lifecycle_delete_checks.py` (new) |
| Lifecycle delete, catalog | `DocumentBackend` `lifecycle/adapters.py:28` | `CatalogLifecycleBackend` `catalog/lifecycle_delete.py:61` | `lifecycle_delete_checks.py` (new) |

### Interfaces consumed
- PRP-89 (not merged when this PRP is written; read by purpose, adapt to its published names): the `neurosphere_adapters_postgres` pool with a `TokenProvider` hook, the schema generated from `CONTAINERS` (one table per container, partition columns, `doc jsonb`, `etag text`, `expires_at`), the migration runner behind `neurosphere_core.migrations.protocols`, the `PgCollection` helper (point read, insert, replace-if-match, upsert, delete, bounded parameterised query, single-partition transaction), neutral error translation, the compose fragment `infra/compose/portable/postgres.yml`, the `portable` pytest marker, a fixture yielding a pool with a fresh schema per module, the data-driven runner `scripts/portable/run_conformance.py` and workflow `.github/workflows/portable-conformance.yml`, and the pre-created data-plane registration module `registry/dataplane.py`. The `portable` pytest marker is PRP-87's.
- PRP-88: `WorkerBackendRegistry.register(port, kind, factory)` and the port names `documents`, `outbox`, `checkpoints`, `ingestion_stores`, `price_snapshots`, `lifecycle_delete`; the split Protocol and Cosmos modules for outbox stores, runtime checkpoint; `InMemoryEventStream` and `InMemoryObjectStore` for the end-to-end test. The four roles used here (ingestion, projections, aggregates, lifecycle) are in PRP-88's never-cut first group.
- PRP-87: package skeleton and dependency pins (`asyncpg`); the `[serial-after: PRP-87]` rule if a dependency is missing.
- Shipped: `Cursor`, `OutboxEntry`, `StoredOutboxEntry`, `LedgerEntry`, `AllocationRecord`, `Contribution`, `AggregateDoc`, `PriceSnapshot`, `SnapshotConflictError`, the error taxonomy.

### Interfaces provided
- `neurosphere_adapters_postgres.dataplane`: `PgLedgerStore`, `PgAggregateStore`, `PgOutboxStore`, `PgCheckpointStore`, `PgRuntimeCheckpointStore`, `PgAcceptedMarkerStore`, `PgWatermarkStore`, `PgCandidateQuarantine`, `PgPriceSnapshotStore`, `PgLedgerLifecycleBackend`, `PgCatalogLifecycleBackend`.
- Worker registrations for kind `postgres` on ports `documents` (ledger, aggregates), `outbox`, `checkpoints`, `ingestion_stores`, `price_snapshots`, `lifecycle_delete`.
- Conformance directories `tests/conformance/documents_dataplane/` (one `*_checks.py` per family, `test_memory.py`, `test_postgres.py`) and `tests/conformance/outbox/`, named for the portable runner's discovery.
- An additive migration (through PRP-89's runner) adding `ts` and the `(customer_id, ts, id)` index to the outbox table.
- No new `NS_*` setting; connection settings are PRP-89's.

### Patterns to match
- `CHECKS` table taking a fresh implementation, loaded by file path: `packages/core/tests/catalog/repo_conformance.py`, `tests/integration/catalog/test_repo_cosmos.py:37-42`.
- Oracle equivalence against the in-memory twin: `tests/integration/analytics/test_equivalence.py`.
- Broken implementation proving a kit can fail: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- First-write-wins by create conflict: `ingestion/cosmos_stores.py:60-75`; bounded retry replaced here by a single atomic statement.
- Fixed statement templates over allowlisted fields: `packages/core/neurosphere_core/catalog/repo/backend.py:1-11`.

### Gotchas
- Cosmos time strings are compared lexicographically (`occurred_at`, `bucket_start`, `effective_date`); keep text columns in the same fixed-width canonical formats (`format_time`, `format_bucket`) rather than casting, or boundaries shift.
- `Cursor` compares `(ts, entry_id)`; use a row comparison `(ts, id) > ($ts, $id)`; an `OR` expansion mishandles the equal-`ts` case.
- Outbox `ts` uses the database clock; do not take it from the application, or two replicas with skew reorder entries.
- `CosmosLedgerStore.read_entry` returns None when `doc_type != "entry"`; the same id may exist as an allocation in the same table.
- The runtime checkpoint and the sink checkpoints share one table (`outbox-checkpoints`); keep the id prefixes and a `kind` guard so one never reads the other.
- `list_allocations` and `list_entries` have no limit today; keep that behaviour but stream through a server-side cursor in pages so a large customer does not load one result set.
- `CandidateQuarantine.write` maps every failure to `candidate_quarantine_unavailable`; keep the reason code.
- Hash-seed flakes: no test may take `next(iter(set))`.
- Same-named test directories shadow each other: the new directories are unique (`documents_dataplane`, `outbox`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-postgres/neurosphere_adapters_postgres/dataplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/dataplane.py
  - tests/conformance/documents_dataplane/**
  - tests/conformance/outbox/**
tier1: []
tier2_appends: []
must_not_touch:
  - packages/adapters-postgres/neurosphere_adapters_postgres/controlplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/search/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/controlplane.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/foundation.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/registration.py
  - packages/adapters-postgres/pyproject.toml
  - pyproject.toml
  - uv.lock
  - infra/compose/portable/**
  - scripts/portable/**
  - .github/workflows/**
  - services/workers/neurosphere_workers/runtime/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/contracts/**
```

## Implementation blueprint

Parallelization: item 1 first (creates the package root and the shared test helpers). Items 2 to 5 [P] after item 1 (each owns its own module and conformance files). Item 6 after 1 to 5. Item 7 last. The registration file `registry/dataplane.py` is touched only by item 6.

### Item 1 - Ledger, allocations and the data-plane package root
- Deliverable: `dataplane/__init__.py` (one-line docstring), `PgLedgerStore` over `cost-ledger` (`doc_type` `entry` and `allocation`, create-if-absent and replace-if-version, half-open `occurred_at` window, per-customer lists in server-side pages), shared test helpers `tests/conformance/documents_dataplane/_support.py`, and `ledger_checks.py` with `test_memory.py` and `test_postgres.py` entries.
- Owned files: `packages/adapters-postgres/neurosphere_adapters_postgres/dataplane/{__init__,ledger}.py`, `tests/conformance/documents_dataplane/{_support,ledger_checks,test_memory,test_postgres}.py`.
- Must NOT touch: PRP-89 modules, other families' files.
- Depends on: PRP-89 merged.
- Acceptance criteria: the ledger criteria above; `StoreLedgerReader` over `PgLedgerStore` returns the same totals as over `InMemoryLedgerStore` for a generated multi-currency set; broken twin (ignores `expected_version`) fails.
- Tests: the paths above.
- Pattern references: `ledger/cosmos.py:32-120`, `ledger/store.py`.

### Item 2 - Aggregates  [P]
- Deliverable: `PgAggregateStore` implementing `AggregateStore` (read: `query`, `latest_subject_points` with chunked key lists as array parameters, `status`; write: contributions, `replace_bucket` in one transaction, `put_status`, `prune` returning the deleted count) over `aggregates`.
- Owned files: `dataplane/aggregates.py`, `tests/conformance/documents_dataplane/aggregates_checks.py`.
- Must NOT touch: ledger files.
- Depends on: item 1.
- Acceptance criteria: window and series bounds still raise `InvalidSchemaError` through the shared validators; `replace_bucket` leaves exactly the supplied docs; `prune` honours day and hour cutoffs and returns the count; no cross-customer effect; equivalence with `InMemoryAggregateStore` over a fixture event stream.
- Tests: `tests/conformance/documents_dataplane/aggregates_checks.py` via `test_memory.py` and `test_postgres.py`; `packages/core/tests/aggregates_subjects`.
- Pattern references: `aggregates/cosmos.py:58-200`.

### Item 3 - Outbox, projection checkpoints and runtime checkpoints  [P]
- Deliverable: `PgOutboxStore` (`append` with `ON CONFLICT DO NOTHING` returning inserted, `read_after` with settle window, row comparison and database clock), `PgCheckpointStore` (atomic monotonic upsert guarded by a row comparison), `PgRuntimeCheckpointStore` (last-write-wins, `rt-` ids), the additive `ts` migration, session timeouts on the writer pool, and the `outbox` conformance directory including a concurrent-writer test with a deliberate slow commit.
- Owned files: `dataplane/{outbox,checkpoints}.py`, `dataplane/migrations/**`, `tests/conformance/outbox/**`.
- Must NOT touch: PRP-89's migration runner.
- Depends on: item 1; PRP-88's split protocol modules.
- Acceptance criteria: ordering, settle, no-skip and no-duplicate paging across 2,000 entries with 4 concurrent writers; monotonic advance under 8 concurrent advancers; idempotent append; `OutboxReader` and `CostLedgerSink` from `services/workers/tests/outbox` pass against the PostgreSQL stores through a parametrised copy (do not edit the originals).
- Tests: `tests/conformance/outbox/`.
- Pattern references: `projections/outbox/stores.py:108-210`, `runtime/checkpoint.py:37-70`.

### Item 4 - Ingestion markers, watermarks and candidate quarantine  [P]
- Deliverable: `PgAcceptedMarkerStore`, `PgWatermarkStore` (one `INSERT ... ON CONFLICT DO UPDATE SET max = greatest(...) RETURNING`), `PgCandidateQuarantine` (upsert by id, reason code kept), and their checks.
- Owned files: `dataplane/{ingestion,quarantine}.py`, `tests/conformance/documents_dataplane/{ingestion,quarantine}_checks.py`.
- Must NOT touch: outbox files.
- Depends on: item 1.
- Acceptance criteria: `mark_accepted` True then False; `advance` monotonic and returns the max under concurrency; ids derived by the same hashes as Cosmos (`wm-` plus sha256 prefix) so a later data copy is byte-compatible; quarantine failure maps to `candidate_quarantine_unavailable`.
- Tests: those check modules; `services/workers/tests/ingestion/test_dedupe.py` logic re-run through a parametrised conformance copy.
- Pattern references: `ingestion/cosmos_stores.py:47-130`.

### Item 5 - Price snapshots and lifecycle delete backends  [P]
- Deliverable: `PgPriceSnapshotStore` (sync facade over the owning loop, deadlock guard, `MAX_SNAPSHOTS` bound, reuses `PriceSnapshot` resolution helpers), `PgLedgerLifecycleBackend` and `PgCatalogLifecycleBackend` implementing `DocumentBackend` (customer and cloud scoped, keyset paging, idempotent remove, audit containers refused).
- Owned files: `dataplane/{prices,lifecycle_delete}.py`, `tests/conformance/documents_dataplane/{prices,lifecycle_delete}_checks.py`.
- Must NOT touch: `packages/core/tests/pricing_cosmos/**` (imported, not edited).
- Depends on: item 1.
- Acceptance criteria: the pricing conformance module passes unchanged; calling a sync method on the loop thread raises a clear error instead of hanging; lifecycle backends pass a shared `DocumentBackend` check table against the in-memory `lifecycle/memory.py` oracle and `lifecycle_cosmos` expectations; remove then read returns None; page ordering is by id.
- Tests: those check modules; `packages/core/tests/lifecycle`, `packages/core/tests/lifecycle_cosmos`.
- Pattern references: `pricing/cosmos_store.py:95-200`, `catalog/lifecycle_delete.py:61-160`, `ledger/lifecycle_delete.py:57-130`.

### Item 6 - Registration and end-to-end role equivalence
- Deliverable: fill `registry/dataplane.py` (`register_worker` registers every factory above under kind `postgres` with PRP-88's registry) and `tests/conformance/documents_dataplane/test_roles_e2e.py`: build ingestion, projections, aggregates and lifecycle with kinds `postgres` plus in-memory stream and object store, ingest a synthetic batch (including a duplicate, a late event and a malformed event), and compare ledger totals, outbox contents and aggregate docs with the all-in-memory run.
- Owned files: `registry/dataplane.py`, `tests/conformance/documents_dataplane/test_roles_e2e.py`.
- Depends on: items 1 to 5; PRP-88 merged.
- Acceptance criteria: equality of outputs; killing the ingestion role mid-batch and restarting yields the same totals (replay safety); no role imports `azure.*` on this path (checked by running with the Azure SDK modules blocked in `sys.modules`).
- Tests: the e2e module.
- Pattern references: `tests/integration/ingestion/support.py`, `services/workers/tests/ingestion/test_crash_replay.py`.

### Item 7 - Integration and close-out
- Deliverable: changelog fragment `changelog.d/PRP-90-postgres-data-plane-stores.md`; confirm the portable runner discovers both new test directories (no workflow edit); Completion note per reference section 6 listing which stores run on PostgreSQL, the cut-line decision and the OPEN gates.
- Owned files: `changelog.d/PRP-90-postgres-data-plane-stores.md`.
- Depends on: item 6.
- Acceptance criteria: gates below pass; `python scripts/portable/run_conformance.py --list` (PRP-89) shows `documents_dataplane` and `outbox`.
- Tests: validation gates.

## Cut line
Ledger, outbox, checkpoints and ingestion stores are never cut. Price snapshots (the `PgPriceSnapshotStore` half of item 5) are last and the only cuttable unit; what remains merges safely because no other item depends on them (the e2e test then runs with the price table file). If cut: non-Azure workers load prices from `NS_LEDGER_PRICE_TABLE_FILE` (`ingestion/wiring.py` `load_price_table`) and the admin price pages report disabled with reason `price_store_unavailable`; recorded in the completion note with a follow-up issue. PRP-96 renders only settings that exist; PRP-98's matrix shows the cut stores as `disabled: <reason>`.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/conformance/documents_dataplane tests/conformance/outbox packages/core/tests/lifecycle packages/core/tests/ledger packages/core/tests/pricing_cosmos services/workers/tests/outbox services/workers/tests/ingestion tests/security/authz
docker compose -f infra/compose/portable/postgres.yml up -d --wait
uv run pytest -q -m portable tests/conformance/documents_dataplane tests/conformance/outbox
docker compose -f infra/compose/portable/postgres.yml down -v
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New installs only: PostgreSQL schema is created by PRP-89's migration runner plus this PRP's additive `ts` migration; nothing is migrated from Cosmos (OPEN). Azure deployments are untouched, and selecting `postgres` is explicit (non-Azure platform default or `NS_PLATFORM`-selected kinds from PRP-88). Rollback: revert the PR; the migration only adds a column and an index and is safe to leave in place. A bad PostgreSQL store is turned off by selecting another document backend kind; there is no cross-backend data copy, so switching an existing install is a reinstall.

## Live and open gates
No paid call is made; every proof runs against a local PostgreSQL container. OPEN and handed to PRP-98: RDS, Aurora and Cloud SQL runs with IAM database authentication (token provider from PRP-94), measured ingest and projection throughput on PostgreSQL at the original NFR scale, measured RPO and RTO of the data plane, and a backup and restore drill. All need `NS_LIVE_APPROVED=1` and an operator.

## NOT building
- Control-plane stores and full-text search (PRP-91); catalog, review queue, policy, revocation, audit, admin config (PRP-89).
- A Cosmos to PostgreSQL data migration.
- A change to the Cosmos implementations or to any Protocol (the price Protocol stays synchronous).
- Partitioning, logical replication or read replicas.
- Any new `NS_*` setting or Helm value (PRP-96).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows D-1, D-2, 3, 5 and 8 are ASSUMPTIONS; D-7 in PRP-85 applies to every store here for plan approval; PRP-89 names are read by purpose until it merges)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
