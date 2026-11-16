---
name: PRP-88-worker-composition-seam-event-and-object-ports
status: backlog
priority: P1
order: 79
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-01, NS-07
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary]
wave: W25
branch: prp-88-worker-seam-event-object-ports
allow_parallel: true
issues: []
---

# PRP-88: Worker composition seam, event consumer and object store ports

## Goal
Make the worker side of NeuroSphere ask a backend provider for its stores, its event consumer and its object stores instead of constructing Cosmos, Event Hubs and Blob objects inside `runtime/factories.py`, and introduce the two ports the code does not have: `EventConsumer` (today `IngestionConsumer` takes an SDK client) and `ObjectStore` (today five near-identical Azure-shaped blob protocols). An `AzureWorkerBackends` provider wraps exactly today's construction, so an Azure deployment (`NS_PLATFORM` unset or `azure`) behaves identically. It is for the engineers of PRP-90 and PRP-92, who cannot add a PostgreSQL, Kafka or S3 backend while composition is Cosmos-by-construction, and for the owner's 2026-11-16 decision to host on Azure, AWS, GCP and on-prem Kubernetes.

Out of scope: the deployment-target contract, the `Backends` registry Protocol, the `TokenProvider` port, the architecture ratchet test and the ADR (PRP-85); contract and capability changes (PRP-86); the API composition seam and the adapter package scaffolding with every dependency (PRP-87); PostgreSQL stores (PRP-89 to PRP-91); Kafka, S3 and GCS implementations (PRP-92); credential providers for non-Azure backends (PRP-94); Helm and settings rendering (PRP-96). This PRP adds no dependency and does not touch `pyproject.toml` or `uv.lock`.

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." and the 5f description "provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer". Original 2a: "Supports at least one managed event broker (Azure Event Hubs, Kafka, or GCP Pub/Sub)".
- v1.2 removed it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting ... outside the initial baseline"), `PRP.md:7` ("No commitment to platform hosting on AWS/GCP/on-prem"). Owner decision 2026-11-16: all four targets. PRP-85 amends those lines; this PRP builds the worker half of the abstraction.
- Composition is Cosmos-by-construction: `services/workers/neurosphere_workers/runtime/factories.py:43-48` imports the Azure SDK, `:309-330` build the Cosmos client and blob container, and the role builders (`build_ingestion` `:408`, `build_projections` `:450`, `build_aggregates` `:471`, `build_lifecycle` `:766`, and the rest of `BUILDERS` `:1867`) instantiate `Cosmos*` classes directly. There is no backend selector.
- The event consumer has no port: `IngestionConsumer` (`ingestion/consumer.py:75`) takes an `EventHubConsumerClient`, mirrors the SDK in `PartitionContextLike` (`:41`) and `EventLike` (`:51`), and checkpoints with `update_checkpoint(events[-1])` (`:106`) into an Azure blob checkpoint store built by `create_checkpoint_store` (`packages/core/neurosphere_core/clients/factories.py:161`). The data shape is already neutral: `RawMessage(partition_id, offset, sequence_number, enqueued_time)` (`ingestion/models.py:65`).
- Five near-duplicate blob protocols use SDK method names: `BlobContainer` in `archive/protocols.py:19` and in `quarantine/blob.py:74`, `ArchiveContainer` (`packages/core/neurosphere_core/lifecycle/archive_backend.py:56`), `BlobSource` (`services/api/neurosphere_api/replay/reader.py:167`), `BlobReadable` (`runtime/archive_reader.py:39`). The archive docstring requires `azure.core.exceptions.ResourceExistsError` on create-if-absent (`archive/protocols.py:22-24`), and `archive/sink.py:106` and `quarantine/blob.py:118` catch it.
- Azure SDK imports leak into 11 worker modules outside adapters (`factories.py`, `runtime/checkpoint.py:14`, `runtime/identity.py:27`, `ingestion/consumer.py:27-28`, `ingestion/wiring.py:29-32`, `projections/outbox/stores.py:25-26`, `publication/records.py:19`, `admin_platform/prices.py:10-11`, `archive/factory.py:11-13`, `archive/sink.py:25`, `quarantine/blob.py:25-34`). The API imports worker factory helpers (`services/api/neurosphere_api/deploy/apply/bootstrap.py`, `runtime/builders/write_targets.py`), so the public names in `factories.py` must survive.

## Acceptance criteria
- [ ] Given `NS_PLATFORM` unset or `azure`, When every role in `BUILDERS` is built with fake Cosmos, Blob and Event Hubs clients, Then the recorded construction snapshot (concrete class of every store, sink, consumer and object store per role, in order) is byte-identical to the golden captured from `main` before any refactor (item 1).
- [ ] Given the existing suites, When `uv run pytest -q services/workers/tests packages/core/tests tests/unit` run unchanged, Then they pass without edits to their assertions; the only test edits are new files plus the allowlist shrink in item 7.
- [ ] Given the real-stack job (`.github/workflows/real-stack.yml`, which triggers on `services/**` and `packages/**`) and the local `integration` suites `tests/integration/ingestion`, `tests/integration/workers_runtime`, `tests/integration/real_stack`, When they run against the compose emulators, Then ingestion through projections to aggregates and the archive and quarantine paths behave as before (item 7; the local run is evidence, CI is the gate).
- [ ] Given an `EventConsumer` handler that raises, When the consumer adapter runs, Then nothing is committed and the batch is redelivered; given a handler that returns, Then the position after the last event is committed (the existing rule at `ingestion/consumer.py:95-98`); this is a shared check run against the in-memory implementation and the Event Hubs adapter.
- [ ] Given two concurrent `ObjectStore.put_if_absent` calls for one name, Then exactly one returns True and the stored bytes are the winner's; `put` overwrites; `get` of a missing name raises the taxonomy `NotFoundError`; `list` by prefix returns names with metadata; `delete` of a missing name is a no-op.
- [ ] Given a broken `ObjectStore` that overwrites on `put_if_absent` and a broken `EventConsumer` that commits before the handler returns, Then the shared checks fail for each (a vacuous pass is impossible).
- [ ] Given `IngestionConsumer`, `to_raw_message`, `build_pipeline_deps`, `create_archive_sink`, `create_quarantine_container` and every public name of `runtime/factories.py`, Then each is still importable from its current path with a compatible signature (the API and the existing tests import them).
- [ ] Given the modules `ingestion/consumer.py`, `archive/**`, `quarantine/**`, `runtime/archive_reader.py`, `lifecycle/archive_backend.py`, `projections/outbox/stores*`, `runtime/checkpoint*` and `publication/records*`, Then none imports `azure.*` or an Azure-named module except the named Azure adapter modules (checked by a local AST test, independent of PRP-85's ratchet).
- [ ] Given `NS_PLATFORM` set to `aws`, `gcp` or `kubernetes` and no backend kind registered for a port yet, Then the worker refuses to start with `capability_unavailable` (reason `platform_not_supported` or `backend_not_registered`) and never falls back to Azure.
- [ ] No behaviour change in reason codes: quarantine blob failures still surface `DependencyTransientError` with reason `quarantine_blob`, archive failures keep their current reasons.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green including `real-stack`; the composition snapshot unchanged.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Who defines `EventConsumer` and `ObjectStore` | PRP-85 with the other neutral ports; this PRP | This PRP, in new modules `neurosphere_core/eventstream/` and `neurosphere_core/objectstore/` (not under PRP-85's `platform/**`). PRP-85 designates them and lists them in `PORTS` with `introduced_by="PRP-88"`; item 2 clears that flag (one-line Tier-2 edit to `platform/inventory.py`) once the modules import |
| 4 | Seam granularity | one `Backends` object; per-port registry by kind | Per-port registry keyed `(port, kind)`: kinds `cosmos`/`postgres` (documents), `eventhubs`/`kafka` (stream), `azure_blob`/`s3`/`gcs` (objects). The default kind per port comes from `NS_PLATFORM` (azure: cosmos, eventhubs, azure_blob). Adapter modules are imported lazily by kind so an Azure image never imports `aiokafka` or `asyncpg` |
| 5 | Create-if-absent contract | raise a neutral conflict error; return a bool | ASSUMPTION: `put_if_absent` returns True when newly created and False when it existed, like `OutboxStore.append` and `mark_accepted`. Call sites already treat the conflict as a normal "first write wins" branch (`archive/sink.py:106`, `quarantine/blob.py:118`), so no new exception type is needed |
| 6 | Transient and auth errors from object stores | adapter raises taxonomy errors; call sites translate | Adapters raise taxonomy errors (`DependencyTransientError`, `ForbiddenError`, `NotFoundError`). Call sites that stamp their own reason (`quarantine_blob`) catch and re-raise with it, so reason codes do not change |
| 7 | Keep `IngestionConsumer` public surface | rewrite tests; keep names | Keep `IngestionConsumer(client, deps, settings)`, `on_event_batch(partition_context, events)`, `to_raw_message`, `run`, `request_shutdown`, `draining`. `client` is now an `EventConsumer`; `on_event_batch` stays as the Event-Hubs-shaped entry point and delegates to the new port-shaped `handle_batch`. `tests/ingestion/test_consumer_checkpoint.py` (it passes `object()` as the client) stays unchanged |
| 8 | Price snapshot loading on workers | change the sync Protocol | Out of scope. The seam exposes `load_price_snapshots(cfg)` (async, returning the list `_price_snapshots` builds today with `asyncio.to_thread`, `factories.py:380`); PRP-90 decides the PostgreSQL side |
| 9 | Cut line if the session overruns | all roles; data plane first | Data plane first; see `## Cut line` |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/runtime/factories.py` - `RuntimeConfig`, `_cosmos`, `_archive_container`, `_sync_cosmos`, `_price_snapshots`, `build_*` builders, `BUILDERS`, `role_factories`.
- `services/workers/neurosphere_workers/ingestion/consumer.py` - `IngestionConsumer`, `to_raw_message`, the commit-after-process rule and shutdown.
- `services/workers/neurosphere_workers/ingestion/wiring.py` - `build_pipeline_deps`, `ensure_blob_container`, `ensure_cosmos_containers` (the one construction path, shared with the quarantine replay CLI).
- `services/workers/neurosphere_workers/archive/{protocols,sink,factory}.py`, `quarantine/blob.py` - the two upload-first-wins sites and their transient mapping.
- `packages/core/neurosphere_core/lifecycle/archive_backend.py`, `services/workers/neurosphere_workers/runtime/archive_reader.py`, `services/api/neurosphere_api/replay/reader.py` - the three read-side blob protocols.
- `services/workers/neurosphere_workers/projections/outbox/stores.py`, `runtime/checkpoint.py`, `publication/records.py` - Protocol plus Cosmos in one module.
- `packages/core/neurosphere_core/clients/factories.py` - `create_eventhub_consumer`, `create_checkpoint_store`, `_refuse_secrets_outside_local`.
- `services/workers/tests/ingestion/test_consumer_checkpoint.py`, `services/workers/tests/worker_roles/test_builders.py` - what the tests construct and import.
- `PRPs/backlog/PRP-85-deployment-target-ports-and-adapter-boundary.md` and `PRP-87-api-composition-seam-and-adapter-packages.md` (if present) - "Interfaces provided".

### Interfaces consumed
- PRP-85: `DeploymentTarget` and the `NS_PLATFORM` accessor on `neurosphere_core.cloud` `Settings` (default `azure`; `government` only with azure), the `Backends` registry Protocol (port name to factory), the neutral document errors, the `PORTS` inventory (Tier-2: this PRP clears its two `introduced_by` flags), the `TokenProvider` port (not needed here; the Azure adapters keep using `DefaultAzureCredential`), and `KNOWN_LEAKS` in `tests/architecture/boundary.py` (deletion-only Tier-2). Not merged when this PRP is written: if an interface differs, adapt to PRP-85's published names and report.
- PRP-87 (same wave, not a dependency): the adapter package skeletons and `services/workers/pyproject.toml` (PRP-87 owns it; this PRP needs neither). The API builder for the replay blob source is PRP-87's file; item 3 keeps `reader.py` accepting a raw SDK container as well as an `ObjectStore`.
- Shipped: `neurosphere_core.clients` (`ClientLifetime`, `translating`), the error taxonomy (`neurosphere_core/errors/taxonomy.py`: `NotFoundError`, `DependencyTransientError`, `ForbiddenError`, `StaleVersionError`), `neurosphere_workers.ingestion.fakes` (blob and Cosmos fakes), `neurosphere_workers.ingestion.pipeline.process_batch`.

### Interfaces provided
- `neurosphere_core.eventstream`: `EventConsumer` Protocol (`async run(handler, *, max_batch_size, max_wait_seconds)`, `async close()`), `ConsumedEvent` (`body: bytes`, `offset: str`, `sequence_number: int`, `enqueued_time: datetime | None`), `EventBatch` (`partition_id: str`, `events: Sequence[ConsumedEvent]`), `BatchHandler`, and `InMemoryEventStream` (partitions and consumer groups, the conformance oracle). Invariant: the adapter commits the position after the last event of a batch only after the handler returned; a handler exception means no commit and redelivery.
- `neurosphere_core.objectstore`: `ObjectStore` Protocol (`put_if_absent(name, data, *, metadata=None) -> bool`, `put(...)`, `get(name) -> bytes`, `head(name) -> ObjectInfo | None`, `list(prefix, *, include_metadata=True) -> AsyncIterator[ObjectInfo]`, `delete(name)`), `ObjectInfo(name, size, metadata)`, `InMemoryObjectStore`.
- `neurosphere_core/platform/azure/eventstream.py`: `EventHubsEventConsumer`; `neurosphere_core/platform/azure/objectstore.py`: `AzureBlobObjectStore`.
- `neurosphere_workers.runtime.backends`: `WorkerBackendRegistry.register(port, kind, factory)`, `select_kinds(platform)` (defaults per platform, overridable by `NS_DOCUMENT_STORE_KIND`, `NS_EVENTSTREAM_KIND` and `NS_OBJECTSTORE_KIND`; an Azure kind with a non-Azure platform is refused), the lazy adapter-module table (`kafka` -> `neurosphere_adapters_kafka.registration`, `s3` and `gcs` -> `neurosphere_adapters_objectstore.registration`, `postgres` -> `neurosphere_adapters_postgres.registration`; each module is imported on first use of its kind and its `register_worker(registry)` is called), and the port names used by PRP-90/91/92 (`documents`, `outbox`, `checkpoints`, `ingestion_stores`, `price_snapshots`, `lifecycle_delete`, `event_consumer`, `object_store:<purpose>` with purpose in `archive`, `quarantine`, `replay`, `lifecycle_archive`).
- `neurosphere_workers.runtime.backends_azure.AzureWorkerBackends` (the Azure adapter module that holds the moved Cosmos, Event Hubs and Blob construction).
- Conformance: `tests/conformance/eventstream/checks.py` and `tests/conformance/objectstore/checks.py` (`CHECKS` tables that take a fresh implementation), with `test_memory.py` and the Azure integration modules. PRP-92 adds the Kafka, S3 and GCS modules.
- Settings: three optional override names, `NS_DOCUMENT_STORE_KIND`, `NS_EVENTSTREAM_KIND`, `NS_OBJECTSTORE_KIND` (unset means the platform default, so Azure is unchanged), as listed in PRP-85's registry of platform settings. Existing `NS_*` names are unchanged.

### Patterns to match
- `CHECKS` table that takes a fresh implementation, loaded by file path: `packages/core/tests/catalog/repo_conformance.py`, `tests/integration/catalog/test_repo_cosmos.py:37-42`.
- Deliberately broken implementation proving a kit can fail: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- Protocol, in-memory twin and Cosmos class in separate modules with re-exports: `packages/core/neurosphere_core/catalog/review_queue.py` and `review_queue_cosmos.py`.
- Idempotent first-write-wins upload with transient mapping: `archive/sink.py:100-114`.
- Explicit-name lazy imports of optional adapters: `core/search/azure/fallback.py:36-90`.

### Gotchas
- `services/api/neurosphere_api/deploy/apply/bootstrap.py` and `runtime/builders/write_targets.py` import from `neurosphere_workers.runtime.factories` (`load_*`, `register_write_targets` family). Do not rename or move those; re-export if code moves.
- `build_pipeline_deps` is shared with the quarantine replay CLI; its signature and the "containers are created only when `NS_ENV=local`" rule stay.
- S3, GCS and Azure lower-case or restrict metadata differently: the port's metadata is ASCII `str -> str` with lower-case keys, as the archive already writes (`sha256`, `reason`, `customer_id`, `quarantined_date`); `quarantine/blob.py` already drops non-printable values.
- `RuntimeConfig` and the `BUILDERS` mapping are patched by tests; keep their shape.
- The real-stack and `integration` suites need the compose emulators. PRP-88 holds the compose stack in W25 for item 7 only; do not run compose from any other item.
- Same-named test directories shadow each other: new worker test directories are `runtime_backends` and `ingestion_stream_port`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/eventstream/**
  - packages/core/neurosphere_core/objectstore/**
  - packages/core/neurosphere_core/platform/azure/eventstream.py
  - packages/core/neurosphere_core/platform/azure/objectstore.py
  - packages/core/neurosphere_core/lifecycle/archive_backend.py
  - packages/core/tests/eventstream_port/**
  - packages/core/tests/objectstore_port/**
  - services/workers/neurosphere_workers/runtime/**
  - services/workers/neurosphere_workers/ingestion/consumer.py
  - services/workers/neurosphere_workers/ingestion/wiring.py
  - services/workers/neurosphere_workers/archive/**
  - services/workers/neurosphere_workers/quarantine/**
  - services/workers/neurosphere_workers/projections/outbox/**
  - services/workers/neurosphere_workers/publication/records.py
  - services/workers/neurosphere_workers/admin_platform/prices.py
  - services/api/neurosphere_api/replay/reader.py
  - services/workers/tests/runtime_backends/**
  - services/workers/tests/ingestion_stream_port/**
  - tests/conformance/eventstream/**
  - tests/conformance/objectstore/**
tier1:
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - tests/architecture/boundary.py
  - packages/core/neurosphere_core/platform/inventory.py
must_not_touch:
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - packages/contracts/**
  - packages/core/neurosphere_core/platform/__init__.py
  - packages/core/neurosphere_core/platform/ports/**
  - packages/core/neurosphere_core/cloud/**
  - services/api/neurosphere_api/runtime/**
  - services/workers/neurosphere_workers/actions/apim.py
  - services/workers/neurosphere_workers/connector_config/**
  - tests/architecture/test_adapter_boundary.py
  - infra/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 then 3 and 4 (3 and 4 share no file once `wiring.py` is left to item 6). Item 5 [P] with 3 and 4. Item 6 after 3, 4, 5. Item 7 after 6; item 8 last.

### Item 1 - Composition snapshot baseline on unmodified code
- Deliverable: a test that builds every role in `BUILDERS` against fake Cosmos, Blob and Event Hubs clients (the patterns in `services/workers/tests/worker_roles/test_builders.py` and `tests/ingestion/support.py`) and records, per role, the ordered list of concrete class names of every store, sink, consumer and container wrapper created; a committed golden JSON captured on this branch before any other change. Roles that need external config use the same minimal env the existing tests set.
- Owned files: `services/workers/tests/runtime_backends/test_composition_snapshot.py`, `services/workers/tests/runtime_backends/golden/worker_composition.json`, `services/workers/tests/runtime_backends/conftest.py`.
- Must NOT touch: any non-test file.
- Depends on: PRP-85 merged.
- Acceptance criteria: the test passes on the untouched tree; the golden contains all 11 roles; running it twice yields identical output (sorted, no addresses or timestamps).
- Tests: `services/workers/tests/runtime_backends/test_composition_snapshot.py`.
- Pattern references: `services/workers/tests/worker_roles/test_builders.py:1-40`.

### Item 2 - Ports, in-memory implementations and shared checks
- Deliverable: `neurosphere_core/eventstream` and `neurosphere_core/objectstore` with the Protocols above, `InMemoryEventStream` and `InMemoryObjectStore`, and the `CHECKS` tables with `test_memory.py` and a deliberately broken implementation each. Then clear the two `introduced_by="PRP-88"` flags in PRP-85's `PORTS` (clarification 3).
- Owned files: `packages/core/neurosphere_core/eventstream/**`, `packages/core/neurosphere_core/objectstore/**`, `packages/core/tests/eventstream_port/**`, `packages/core/tests/objectstore_port/**`, `tests/conformance/eventstream/{checks,test_memory}.py`, `tests/conformance/objectstore/{checks,test_memory}.py`; Tier-2 line edit in `packages/core/neurosphere_core/platform/inventory.py`.
- Must NOT touch: workers, Azure adapters.
- Depends on: item 1.
- Acceptance criteria: commit-after-handler, redelivery on handler error, restart from the committed position, one group member per partition, ordering per partition; first-write-wins under 8 concurrent writers, prefix listing across more than 1000 names, metadata round trip, idempotent delete, customer-prefix isolation. The broken twins fail the matching checks. Neutral modules import no `azure.*`.
- Tests: the paths above.
- Pattern references: `packages/core/tests/catalog/repo_conformance.py`.

### Item 3 - Azure Blob object store; collapse the five protocols
- Deliverable: `AzureBlobObjectStore` over an injected `ContainerClient` (translating `ResourceExistsError`, `ResourceNotFoundError`, throttling and 5xx into the port's results and the taxonomy). `BlobArchiveSink`, the quarantine store and replay CLI, `ArchiveReader`, `ArchiveLifecycleBackend` and the API replay reader take an `ObjectStore`; the five SDK-shaped protocols are deleted. `reader.py` keeps accepting a raw SDK container by wrapping it, so PRP-87's builder needs no change in this wave. `archive/factory.py` and `create_quarantine_container` keep their signatures and build `AzureBlobObjectStore`.
- Owned files: `packages/core/neurosphere_core/platform/azure/objectstore.py`, `services/workers/neurosphere_workers/archive/**`, `quarantine/**`, `runtime/archive_reader.py`, `packages/core/neurosphere_core/lifecycle/archive_backend.py`, `services/api/neurosphere_api/replay/reader.py`, `tests/conformance/objectstore/test_azure_blob.py` (Azurite, `integration`).
- Must NOT touch: `ingestion/wiring.py`, `runtime/factories.py`, other API files.
- Depends on: item 2.
- Acceptance criteria: `services/workers/tests/archive`, `services/workers/tests/quarantine`, the archive-reader and replay-reader tests and `packages/core/tests/lifecycle` pass with their assertions unchanged; the Azure adapter passes the shared checks on Azurite; reasons `quarantine_blob` and the archive reasons are unchanged.
- Tests: those suites plus `tests/conformance/objectstore/test_azure_blob.py`.
- Pattern references: `archive/sink.py:100-114`, `quarantine/blob.py:100-125`.

### Item 4 - Event consumer port and Event Hubs adapter
- Deliverable: `EventHubsEventConsumer` wrapping `EventHubConsumerClient` (`receive_batch` with `starting_position="-1"`, commit through `update_checkpoint` after the handler returns, close-then-drain with the existing 30 s timeout). `IngestionConsumer` gains `handle_batch(EventBatch)`; `on_event_batch` and `to_raw_message` stay and delegate. `runtime/adapters.py` is unchanged unless a type annotation needs it.
- Owned files: `packages/core/neurosphere_core/platform/azure/eventstream.py`, `services/workers/neurosphere_workers/ingestion/consumer.py`, `services/workers/tests/ingestion_stream_port/**`, `tests/conformance/eventstream/test_eventhubs.py` (Event Hubs emulator, `integration`).
- Must NOT touch: `ingestion/wiring.py`, `runtime/factories.py`, `pipeline.py`.
- Depends on: item 2.
- Acceptance criteria: `services/workers/tests/ingestion` passes unchanged; the adapter passes the shared stream checks against the emulator and against a fake of the SDK slice; shutdown behaviour (in-flight batch finishes, exit code 0, 1 on unexpected receiver end) is covered by tests ported from the current behaviour; the quarantine path (malformed message quarantined, position committed) is asserted through the port.
- Tests: `services/workers/tests/ingestion_stream_port/`, `services/workers/tests/ingestion`.
- Pattern references: `ingestion/consumer.py:96-165`, `services/workers/tests/ingestion/test_consumer_checkpoint.py`.

### Item 5 - Split Protocol and Cosmos modules  [P]
- Deliverable: pure moves, no logic change. `projections/outbox/stores.py` becomes `protocols` (OutboxStore, CheckpointStore, in-memory twins) plus `cosmos_stores.py` (Cosmos classes); `runtime/checkpoint.py` keeps the Protocol and in-memory store and moves `CosmosRuntimeCheckpointStore` to `runtime/checkpoint_cosmos.py`; `publication/records.py` keeps the models, `ApplyRecordReader`, `ApplyRecordLookup`, `InMemoryApplyRecordLookup` and moves `CosmosApplyRecordLookup` to `publication/records_cosmos.py`. Old import paths keep working through re-exports so no importer changes.
- Owned files: `services/workers/neurosphere_workers/projections/outbox/**`, `runtime/checkpoint.py`, `runtime/checkpoint_cosmos.py` (new), `publication/records.py`, `publication/records_cosmos.py` (new).
- Must NOT touch: `runtime/factories.py`, `ingestion/**`.
- Depends on: PRP-85 merged.
- Acceptance criteria: `services/workers/tests/outbox`, `projections`, `runtime`, `publication_replay` pass unchanged; the Protocol modules import no Azure SDK.
- Tests: those suites plus `services/workers/tests/runtime/test_checkpoint_protocol.py`.
- Pattern references: `packages/core/neurosphere_core/catalog/review_queue_cosmos.py`.

### Item 6 - Backend registry, Azure provider, factories rewire (Tier 1)
- Deliverable: `runtime/backends.py` (registry, `select_kinds`, lazy module table, refusal for an unregistered kind) and `runtime/backends_azure.py` (`AzureWorkerBackends`: the moved `_cosmos`, `_database`, `_archive_container`, `_sync_cosmos`, `_price_snapshots`, Cosmos store construction, `create_eventhub_consumer` plus `create_checkpoint_store`, object stores per purpose). `factories.py` builders ask the provider; `ingestion/wiring.py` is split so the neutral part builds from ports and the Azure construction lives in the provider, keeping `build_pipeline_deps` and its settings classes. Roles are rewired in the order in clarification 9.
- Owned files: `services/workers/neurosphere_workers/runtime/factories.py`, `runtime/backends.py`, `runtime/backends_azure.py`, `ingestion/wiring.py`, `runtime/identity.py`, `admin_platform/prices.py`, `services/workers/tests/runtime_backends/test_backend_registry.py`.
- Must NOT touch: API files, `actions/apim.py`.
- Depends on: items 3, 4, 5.
- Acceptance criteria: the composition snapshot is byte-identical to item 1's golden; `NS_PLATFORM=aws` with no registered kind refuses with `capability_unavailable`; no module outside `backends_azure.py` and the named Azure adapters imports `azure.*`; all public names of `factories.py` and `wiring.py` still import.
- Tests: `services/workers/tests/runtime_backends`, `services/workers/tests/worker_roles`, `services/workers/tests/ingestion`, `services/workers/tests/lifecycle_worker`, `services/workers/tests/action_executor`.
- Pattern references: `factories.py:309-345`, `runtime/adapters.py:150-175`.

### Item 7 - Proof run and ratchet shrink  [serial-after: PRP-85]
- Deliverable: run the compose emulators once (this PRP holds the stack) and the local integration suites; record the commands and results in the PR; remove the worker files that no longer import Azure from `KNOWN_LEAKS` in `tests/architecture/boundary.py` and lower `LEAK_CEILING` (deletion-only Tier-2, shared with PRP-87 in W25: at rebase keep both deletions and recompute the ceiling). Allowed only after PRP-85 merged.
- Owned files: `tests/architecture/boundary.py` (Tier-2, entry removal only).
- Must NOT touch: the boundary test logic.
- Depends on: item 6; PRP-85 merged.
- Acceptance criteria: `uv run pytest -q tests/architecture` passes with a shorter list; the integration suites listed above pass or each failure is explained as pre-existing on `main`.
- Tests: `tests/architecture`, `tests/integration/ingestion`, `tests/integration/workers_runtime`, `tests/integration/real_stack`.
- Pattern references: `.github/workflows/real-stack.yml` steps.

### Item 8 - Integration and close-out
- Deliverable: changelog fragment `changelog.d/PRP-88-worker-composition-seam-event-and-object-ports.md`; `docs/dev/platform-ports.md` is regenerated from `PORTS` by PRP-85's `render_markdown()` (no hand edit); Completion note per reference section 6; Tier-3 regeneration if any generated file drifted (none expected: no route or schema changes).
- Owned files: `changelog.d/PRP-88-worker-composition-seam-event-and-object-ports.md`.
- Depends on: item 7.
- Acceptance criteria: gates below pass; the note lists OPEN gates and the kinds PRP-90 and PRP-92 must register.
- Tests: validation gates.

## Cut line
Roles are rewired in this order: ingestion, projections, aggregates, lifecycle, then actions, hitl_timers, recommendations, evaluation, gateway_poll, foundry_discovery, billing_export. Items 1-5, item 6 for the first group, and items 7-8 are the minimum ship. If the last group does not fit, those builders keep calling `AzureWorkerBackends` helpers unchanged; that merges safely because the snapshot test still passes (behaviour is identical) and on a non-Azure platform those roles refuse to start with `capability_unavailable` (`backend_not_registered`), never falling back to Azure. A follow-up issue is filed for the remaining roles; PRP-91 (the consumer of those roles' ports) states what it does in that case.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/workers/tests packages/core/tests/eventstream_port packages/core/tests/objectstore_port packages/core/tests/lifecycle tests/conformance/eventstream tests/conformance/objectstore tests/architecture services/api/tests/replay tests/security/authz
uv run pytest -q -m integration tests/integration/ingestion tests/integration/workers_runtime tests/integration/real_stack tests/conformance/eventstream tests/conformance/objectstore
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data or schema migration: stored objects, container names, blob prefixes (`records/`, `replayed/`, the archive partition-day layout), consumer group and checkpoint blobs are unchanged. There is no flag: the refactor is behaviour-neutral on Azure and `NS_PLATFORM` unset means `azure`. Rollback is `git revert` of the merge; nothing persisted depends on the new modules. The golden snapshot is the regression tripwire for any later change to composition.

## Live and open gates
Nothing here needs `NS_LIVE_APPROVED=1`; every proof runs on fakes and the local emulators. OPEN, handed to PRP-98 (which records evidence through PRP-64 and PRP-66): an Azure hosted ingest-to-aggregate smoke after this refactor, and any real AWS or GCP run of the stream and object adapters (PRP-92). No paid cloud call is made.

## NOT building
- Any Kafka, S3, GCS or PostgreSQL implementation (PRP-92, PRP-89 to PRP-91).
- A neutral token or credential port and non-Azure credential rules (PRP-85, PRP-94).
- Changes to the API composition, `ObjectStore` use in API builders beyond `replay/reader.py` (PRP-87).
- A Pub/Sub adapter (OPEN in the program design).
- Moving existing Azure adapter modules out of `neurosphere-core`.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; row 5 is an ASSUMPTION for plan approval; PRP-85 and PRP-87 interfaces are read by purpose until they merge)

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
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
