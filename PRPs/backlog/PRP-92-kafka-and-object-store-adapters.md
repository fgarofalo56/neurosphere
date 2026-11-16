---
name: PRP-92-kafka-and-object-store-adapters
status: backlog
priority: P1
order: 83
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-01, NS-08
depends_on: [PRP-87-api-composition-seam-and-adapter-packages, PRP-88-worker-composition-seam-event-and-object-ports, PRP-102-encrypted-interaction-store-and-retention]
wave: W36
branch: prp-92-kafka-and-object-store-adapters
allow_parallel: true
issues: []
---

# PRP-92: Kafka event streaming and S3 and GCS object storage

## Goal
Implement the non-Azure halves of the two ports PRP-88 introduces. For event streaming: a Kafka-API publisher for the ingest edge, an `EventConsumer` that joins a consumer group and commits only after the batch is durably accepted, and a Kafka SIEM sink. For object storage: an S3-API `ObjectStore` (Amazon S3 and any S3-compatible store) and a native Google Cloud Storage `ObjectStore`, both with atomic create-if-absent. Archive, quarantine, replay and lifecycle archive then run on them. Each adapter is proven by a conformance suite against a local container (an Apache Kafka broker and an S3-compatible store from compose fragments), extending the shared checks PRP-88 wrote, with a deliberately broken implementation per suite. At-least-once delivery, idempotent consumption, consumer-group checkpointing and the quarantine path match the Event Hubs behaviour. It is for operators on AWS (MSK, S3), GCP (Managed Kafka, GCS) and on-prem Kubernetes (Strimzi, an S3-compatible store), and for PRP-94, PRP-96 and PRP-98.

Out of scope: the ports and the worker composition seam (PRP-88); adapter package scaffolding, dependency pins and the API provider (PRP-87); broker and bucket authentication beyond local anonymous or TLS-only containers, IAM and workload-identity token providers (PRP-94); PostgreSQL stores (PRP-89 to PRP-91); Helm values, the in-cluster operators and the on-prem bundle (PRP-96); Terraform for MSK, Managed Kafka, S3 and GCS (PRP-97); a Pub/Sub adapter (OPEN: ordering keys and per-message acks do not map onto the partition and offset contract). This PRP adds no dependency and does not touch `pyproject.toml` or `uv.lock`: it uses `aiokafka`, `aiobotocore` and `google-cloud-storage` as pinned by PRP-87 in `packages/adapters-kafka` and `packages/adapters-objectstore`. Real MSK, Managed Kafka, S3 and GCS runs are OPEN and handed to PRP-98.

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer" and "Core platform logic ... is cloud-agnostic; only infra adapters differ." Original 2a: "Supports at least one managed event broker (Azure Event Hubs, Kafka, or GCP Pub/Sub)".
- v1.2 excluded it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting ... outside the initial baseline"), `PRP.md:7`. Owner decision 2026-11-16: all four targets on one portable backend set (ASSUMPTION D-2 below). PRP-85 amends the v1.2 lines.
- Event publish has a neutral Protocol with one Azure implementation: `Publisher` (`services/api/neurosphere_api/ingest/publisher.py:13`) and `EventHubsPublisher` (`:17`), which groups by `HubMessage.partition_key()` (`customer|source`, `packages/core/neurosphere_core/payload/wire.py:59`) so each source keeps its order. A Kafka message key carries the same value.
- The consumer contract is small and maps one to one: `RawMessage(partition_id, offset, sequence_number, enqueued_time)` (`services/workers/neurosphere_workers/ingestion/models.py:65`), start from the earliest position (`starting_position="-1"`, `ingestion/consumer.py:132`), commit only after `process_batch` returned (`:95-106`), drain on shutdown (`:120-165`). PRP-88 puts these behind `EventConsumer`.
- Archive and quarantine require atomic first-write-wins: the archive docstring says create-if-absent must fail when the object exists (`services/workers/neurosphere_workers/archive/protocols.py:22-24`), and `archive/sink.py:106` and `quarantine/blob.py:118` depend on it for redelivery safety. The design flags conditional writes on S3-compatible stores and the GCS S3-interop path as UNVERIFIED; this PRP verifies them first.
- The SIEM path has a neutral Protocol and one network sink: `SiemSink` (`packages/core/neurosphere_core/audit/siem.py:69`), `EventHubsSiemSink` (`audit/siem_eventhubs.py:81`, one batch per event, send timeout). The sink choice is a closed literal in `services/api/neurosphere_api/runtime/settings.py` (`AuditSiemSettings.sink`).
- Dependency licences matter: `scripts/licenses_report.py` fails copyleft packages. `aiokafka`, `aiobotocore` and `google-cloud-storage` are Apache-2.0 (PRP-87 records the rows). A local S3-compatible server image is not a linked dependency and is not scanned, but its licence needs an explicit owner note (design section 5.3), which is why item 1 verifies it.

## Acceptance criteria
- [ ] Interaction content blobs: the S3 and GCS `ObjectStore` implementations carry the interaction content container of PRP-102 (`interaction_blobs`: create-if-absent per blob, read, delete, list by prefix; only already-redacted, encrypted envelopes are written by callers), proven by an extension of the object-store conformance suite with the delete-blob-then-index ordering the lifecycle target needs; content never appears in logs or in the conformance output.
- [ ] Given the verify-first checklist (item 1), Then every UNVERIFIED point has a recorded outcome (verified, failed with the fallback taken, or OPEN) in `docs/deploy/portable-streaming-and-objects.md`, with the image tags or digests and licences actually used.
- [ ] Given `KafkaPublisher.publish(messages)`, Then each message is sent with key `partition_key()` and value `to_bytes()`, `acks=all` and idempotent production, messages with one key stay in order, and broker failures map to the taxonomy (transient to `DependencyTransientError`, authorization to `ForbiddenError`, oversize to `PayloadTooLargeError`) without echoing broker text.
- [ ] Given a handler that raises, When `KafkaEventConsumer` runs, Then no offset is committed and the batch is redelivered to the same or another group member; given a handler that returns, Then the offset after the last event of that partition batch is committed (`last_offset + 1`). Given a new consumer in the same group after a restart, Then consumption resumes after the committed offset; given a new group, Then it starts from the earliest offset.
- [ ] Given two consumers in one group on a topic with several partitions, Then every message is handled by exactly one member at a time, per-partition order is preserved, and a member leaving causes redelivery of only its uncommitted batch.
- [ ] Given a malformed message on the topic, When the real `IngestionConsumer` and pipeline run on the Kafka consumer, Then the message is quarantined through the quarantine sink and its offset is committed; given the same message delivered twice (redelivery or a producer retry), Then the ledger effect happens once (accepted markers), as with Event Hubs.
- [ ] Given `close()`, Then the in-flight handler finishes, its offset is committed, and `run` returns; no batch is committed that its handler did not finish.
- [ ] Given `KafkaSiemSink.emit(event)`, Then one record with a stable JSON body (sorted keys, ASCII) is produced within the send timeout; a timeout or broker error raises and is isolated by `SiemExporter` as for Event Hubs.
- [ ] Given `S3ObjectStore` and `GcsObjectStore`, Then they pass PRP-88's shared `ObjectStore` checks: first-write-wins under 8 concurrent writers, overwrite on `put`, `get` of a missing name raises `NotFoundError`, listing by prefix across more than 1,000 names with metadata, ASCII metadata round trip with lower-case keys, idempotent delete, customer-prefix isolation, a 5 MiB object round trip.
- [ ] Given a store that does not enforce conditional writes, Then the adapter's startup probe detects it and the role refuses to start with `capability_unavailable` reason `objectstore_atomic_create_unsupported`; it never degrades to check-then-write.
- [ ] Given `NS_ENV` other than `local`, Then plaintext Kafka, anonymous endpoints and static access keys in `NS_*` are refused with the existing "no static credential outside local" rule; non-local authentication is supplied by PRP-94's token providers, and without one the adapter raises `capability_unavailable` (`kafka_auth_unconfigured`, `objectstore_auth_unconfigured`).
- [ ] Given the deliberately broken implementations (a consumer that commits before the handler returns, an object store whose `put_if_absent` overwrites), Then the shared checks fail for each.
- [ ] No secret, key or connection string appears in logs, errors, audit or OpenAPI.
- PRP exit: touched suites, `tests/conformance/{eventstream,objectstore,siem}`, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `portable-conformance` discovers the new compose fragments and directories without edits.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Kafka client | `aiokafka`; `confluent-kafka` | `aiokafka` (Apache-2.0), as pinned by PRP-87. If item 1 finds it cannot speak to the pinned broker, the fallback `confluent-kafka` needs a dependency change: `[serial-after: PRP-87]` and a report, not an edit here |
| 4 | GCS adapter | native `google-cloud-storage`; GCS S3-interop with HMAC keys | ASSUMPTION: native (design D). `google-cloud-storage` is synchronous: calls run through `asyncio.to_thread` behind a bounded semaphore. HMAC keys are long-lived static credentials and conditional-write behaviour through the interop API is UNVERIFIED |
| 5 | Local S3-compatible store (owner decision D-5 in PRP-85) | MinIO; SeaweedFS | Per D-5: MinIO only if item 1 verifies a maintained official image and atomic `If-None-Match: *` and the owner accepted the licence note; otherwise SeaweedFS. Both are checked against the same suite; the adapter code does not depend on the choice |
| 6 | Kafka commit granularity | per message; per partition batch | Per partition batch after the handler returns, offset `last + 1`, matching the Event Hubs `update_checkpoint(events[-1])` rule. Auto-commit is off |
| 7 | Start position | latest; earliest | Earliest for a group with no committed offset (`auto_offset_reset=earliest`), as `starting_position="-1"` today |
| 8 | Partition mapping | one topic; per-source topics | One topic (`NS_KAFKA_TOPIC`, default `telemetry`); the message key is `customer|source`, so the per-source order guarantee is kept. `RawMessage.partition_id` is the partition number as text, `offset` the offset as text and `sequence_number` the offset as an int |
| 9 | SIEM wiring | edit the Tier-1 builder here | The sink class and its tests live here; selecting it (the `data.py` builder branch) is a `[serial-after: PRP-87]` item, because that file is PRP-87's seam; the `AuditSiemSettings.sink` literal gains `kafka` as a Tier-2 additive edit of `runtime/settings.py` (PRP-93 also appends there in W36). If PRP-87's provider already exposes a SIEM sink registry, only a registration is needed |
| 10 | Compose lane in W36 | parallel; serialized | Serialized: PRP-89 holds the W36 portable compose lane first, this PRP second (its compose-backed gates are `[serial-after: PRP-89]`), PRP-93 third. This PRP's fragments use their own project names (`ns-portable-kafka`, `ns-portable-objectstore`) and ports and never the fixed project name of the main stack; only one session at a time may run them |
| 11 | Event Hubs Kafka endpoint | reuse the Kafka adapter on Azure | Not scoped; Azure keeps the Event Hubs adapters from PRP-88. Whether the Event Hubs emulator speaks Kafka stays UNVERIFIED and is irrelevant here |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/ingestion/consumer.py` - commit-after-process, `starting_position`, shutdown and drain (after PRP-88: the `EventConsumer` port and `EventHubsEventConsumer` adapter in `packages/core/neurosphere_core/platform/azure/eventstream.py`).
- `services/workers/neurosphere_workers/ingestion/pipeline.py` and `ingestion/fakes.py` - `process_batch`, quarantine and dedupe behaviour to assert through the Kafka consumer.
- `services/api/neurosphere_api/ingest/publisher.py` - `Publisher`, `EventHubsPublisher`, `InMemoryPublisher`.
- `packages/core/neurosphere_core/payload/wire.py` - `HubMessage.partition_key`, `to_bytes`.
- `packages/core/neurosphere_core/audit/siem.py` and `siem_eventhubs.py` - `SiemSink`, `SiemExporter` isolation, send timeout, body encoding.
- `services/workers/neurosphere_workers/archive/sink.py` and `quarantine/blob.py` - first-write-wins callers and metadata use (`sha256`, `reason`, `customer_id`).
- `packages/core/neurosphere_core/objectstore/` and `eventstream/` (PRP-88) - ports, in-memory twins; `tests/conformance/{eventstream,objectstore}/checks.py` (PRP-88) - the shared checks this PRP extends.
- `packages/core/neurosphere_core/clients/factories.py:56-63` - the "no secret outside local" rule to generalise; `clients/errors.py` - taxonomy mapping style.
- `docker-compose.yml:50` (Azurite service) and `infra/compose/eventhubs.config.json` - local fixture conventions.
- `PRPs/backlog/PRP-87-api-composition-seam-and-adapter-packages.md`, `PRP-88-worker-composition-seam-event-and-object-ports.md`, `PRP-89-postgres-foundation-catalog-and-security-stores.md` - "Interfaces provided".

### Interfaces consumed
- PRP-88: `neurosphere_core.eventstream` (`EventConsumer`, `ConsumedEvent`, `EventBatch`, `InMemoryEventStream`), `neurosphere_core.objectstore` (`ObjectStore`, `ObjectInfo`, `InMemoryObjectStore`), `WorkerBackendRegistry.register(port, kind, factory)`, the lazy module table that already names `neurosphere_adapters_kafka.registration` and `neurosphere_adapters_objectstore.registration`, the port names `event_consumer` and `object_store:<purpose>`, and `tests/conformance/{eventstream,objectstore}/checks.py` plus their in-memory and Azure test modules.
- PRP-87: skeletons and pinned dependencies of `packages/adapters-kafka` and `packages/adapters-objectstore` with their entry-point stubs `registration:register`; the API provider and registry through which the ingest edge asks for a `Publisher`; the `portable` pytest marker.
- PRP-89 (same wave, ahead in the compose lane): the data-driven runner `scripts/portable/run_conformance.py` and the workflow `.github/workflows/portable-conformance.yml`. This PRP adds fragments and test directories only and never edits them; every step that runs or lists through them is `[serial-after: PRP-89]`.
- PRP-85: `NS_PLATFORM`, the neutral error vocabulary, the `TokenProvider` port and the registry of platform settings (the `NS_KAFKA_*`, `NS_OBJECTSTORE_*` and `NS_AUDIT_SIEM_SINK=kafka` rows are this PRP's).
- Shipped: the error taxonomy, `SiemExporter`, `HubMessage`.

### Interfaces provided
- `neurosphere_adapters_kafka`: `KafkaPublisher` (a `Publisher`), `KafkaEventConsumer` (an `EventConsumer`), `KafkaSiemSink` (a `SiemSink`, `name="kafka"`), `KafkaSettings` (env prefix `NS_KAFKA_`: `BOOTSTRAP_SERVERS`, `TOPIC`, `GROUP_ID`, `SIEM_TOPIC`, `CLIENT_ID`, `SECURITY_PROTOCOL` = `plaintext`|`ssl`, plaintext only when `NS_ENV=local`), and `registration.register_worker(registry)` (PRP-88 lazy table) / `registration.register(registry)` (PRP-87 entry point: publisher and SIEM sink) for kind `kafka`.
- `neurosphere_adapters_objectstore`: `S3ObjectStore`, `GcsObjectStore`, `ObjectStoreSettings` (env prefix `NS_OBJECTSTORE_`, beside PRP-88's `NS_OBJECTSTORE_KIND` override: `S3_ENDPOINT_URL`, `S3_REGION`, `S3_FORCE_PATH_STYLE`, `GCS_PROJECT`, `GCS_API_ENDPOINT`; the emulator endpoint is refused outside local), `probe_atomic_create(store)`, and `registration.register_worker(registry)` for kinds `s3` and `gcs`. Buckets reuse the existing container settings (`NS_ARCHIVE_CONTAINER`, `NS_QUARANTINE_CONTAINER`), so no new bucket variable.
- Compose fragments `infra/compose/portable/kafka.yml` (project `ns-portable-kafka`, broker on `127.0.0.1:29092`) and `infra/compose/portable/objectstore.yml` (project `ns-portable-objectstore`, S3 API on `127.0.0.1:29000`, optional GCS emulator under a profile).
- Conformance: `tests/conformance/eventstream/test_kafka.py`, `tests/conformance/objectstore/test_s3.py` and `test_gcs.py`, `tests/conformance/siem/{checks,test_memory,test_kafka}.py`, with broken twins.
- `docs/deploy/portable-streaming-and-objects.md`: the verification record and the operator notes for these two backends.
- Kinds `kafka`, `s3`, `gcs` on the PRP-88 registry; the SIEM sink kind `kafka` (selection wiring in item 6).
- New `NS_*` names for the operator (`.env.example` cannot be edited by an agent): all `NS_KAFKA_*` and `NS_OBJECTSTORE_*` names above, as listed in PRP-85's registry of platform settings.

### Patterns to match
- `CHECKS` tables with a broken twin: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`; shared checks loaded by file path: `tests/integration/catalog/test_repo_cosmos.py:37-42`.
- First-write-wins upload and transient mapping: `archive/sink.py:100-114`, `quarantine/blob.py:100-125`.
- Producer grouping by partition key and flush on a full batch: `ingest/publisher.py:17-45`.
- Settings with local-only relaxations and refusal elsewhere: `packages/core/neurosphere_core/clients/factories.py:56-63`.
- Opt-in lazy adapter import: `packages/core/neurosphere_core/search/azure/fallback.py:36-90`.
- Recorded-transport tests for cloud-only APIs: the existing `respx` patterns under `packages/core/tests` and `tests/unit`.

### Gotchas
- Kafka advertised listeners: a host client reaching a container broker needs `127.0.0.1:29092` advertised on the external listener, not the container hostname; use `127.0.0.1`, not `localhost` (the IPv6 forward trap).
- A Kafka offset commit is the NEXT offset to read (`last_offset + 1`); committing `last_offset` redelivers the last message forever.
- Consumer-group rebalances during a slow handler cause redelivery; set `max_poll_interval_ms` above the pipeline's batch bound and handle `CommitFailedError` as "another member owns it" (log a counts-only line, do not crash): the batch is redelivered, which the idempotent pipeline tolerates.
- S3 returns user metadata keys lower-case and only ASCII values; `ListObjectsV2` returns no metadata, so `list(include_metadata=True)` needs `HeadObject` per object: bound the concurrency (default 16) and note the cost for the archive manifest builder (`archive/sink.py:build_manifest`).
- S3 conditional write is `If-None-Match: *` on `PutObject`; a loser gets 412 (or 409 on a concurrent in-flight write). Both mean "already exists, retry as read" and map to False. Whether the pinned `botocore` model exposes `IfNoneMatch` is a verify-first item.
- `google-cloud-storage` is blocking and its emulator protocol is selected by `STORAGE_EMULATOR_HOST`; never leave that variable honoured outside `NS_ENV=local`.
- Objects with names containing `/` and the 1,024-byte S3 key limit: archive and quarantine names are well inside it; the check suite includes a long-name case.
- No test may take `next(iter(set))`. Same-named test directories shadow each other: new test directories live under `tests/conformance` with unique names.
- Container images are not scanned by the licence script: record image, tag or digest and licence in the verification record for the ADR-0002 infrastructure table that PRP-87 owns; do not edit ADR-0002 here.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-kafka/neurosphere_adapters_kafka/**
  - packages/adapters-objectstore/neurosphere_adapters_objectstore/**
  - packages/adapters-kafka/tests/**
  - packages/adapters-objectstore/tests/**
  - tests/conformance/eventstream/**
  - tests/conformance/objectstore/**
  - tests/conformance/siem/**
  - infra/compose/portable/kafka.yml
  - infra/compose/portable/objectstore.yml
  - docs/deploy/portable-streaming-and-objects.md
tier1: []
tier2_appends:
  - mkdocs.yml
  - services/api/neurosphere_api/runtime/settings.py
must_not_touch:
  - pyproject.toml
  - uv.lock
  - packages/adapters-kafka/pyproject.toml
  - packages/adapters-objectstore/pyproject.toml
  - packages/contracts/**
  - packages/core/neurosphere_core/eventstream/**
  - packages/core/neurosphere_core/objectstore/**
  - packages/core/neurosphere_core/platform/**
  - services/workers/neurosphere_workers/runtime/**
  - services/api/neurosphere_api/runtime/backends/**
  - services/api/neurosphere_api/runtime/compose.py
  - infra/compose/portable/postgres.yml
  - scripts/portable/**
  - .github/workflows/**
  - docs/adr/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 [P] after item 1 (separate packages). Item 4 after 2; item 5 after 3. Item 6 is serial. Item 7 last.

### Item 1 - Verify-first record and compose fragments
- Deliverable: run each check below against the local containers and record the outcome (verified, failed plus fallback taken, OPEN) with image tags or digests and licences in `docs/deploy/portable-streaming-and-objects.md`. (a) Kafka: an official `apache/kafka` image in KRaft single-node mode starts healthy with a host-reachable advertised listener; its licence is Apache-2.0; fallback: the same project's native-image variant. (b) `aiokafka` as pinned talks to that broker (produce with idempotence and `acks=all`, group join, manual commit); fallback: relax idempotent production and rely on consumer idempotency, or stop with `[serial-after: PRP-87]` for `confluent-kafka`. (c) The local S3-compatible store: a maintained official image is still published; its licence (MinIO is AGPL-3.0, customer-side only, owner note needed); `If-None-Match: *` on `PutObject` returns 412 to the second writer; the pinned `botocore` model has `IfNoneMatch` on `PutObject` (inspect the installed service model; fallback: add the header through a botocore event hook); fallback store: SeaweedFS (Apache-2.0); any other candidate stays UNVERIFIED until run. (d) GCS: `if_generation_match=0` yields a precondition failure for the second writer against `fake-gcs-server` or another emulator selected through `STORAGE_EMULATOR_HOST`; fallback if the emulator ignores preconditions: the adapter suite runs against an in-process fake of the `Bucket` and `Blob` calls (proves the mapping, not the service) and live GCS atomicity is recorded OPEN. (e) S3 metadata behaviour (lower-case keys, ASCII values, no metadata in `ListObjectsV2`). Write the two compose fragments (healthchecks, own project name and ports, pinned tags or digests, no secrets).
- Owned files: `infra/compose/portable/kafka.yml`, `infra/compose/portable/objectstore.yml`, `docs/deploy/portable-streaming-and-objects.md`.
- Must NOT touch: `docker-compose.yml`, PRP-89's `postgres.yml`.
- Depends on: PRP-88 merged; PRP-87 skeletons present; this PRP holds the compose lane in W36 after PRP-89.
- Acceptance criteria: `docker compose -f infra/compose/portable/kafka.yml up -d --wait` and the same for `objectstore.yml` become healthy and tear down with `down -v`; every UNVERIFIED point from the design (MinIO conditional create, GCS conditional create, `aiokafka` against the broker, image licences) has a recorded outcome; a failed check names its fallback and what it changes in this PRP.
- Tests: the doc is reviewed; the fragments are exercised by items 4 and 5.
- Pattern references: `docker-compose.yml:36-84` (service and healthcheck style), `infra/compose/eventhubs.config.json`.

### Item 2 - Kafka adapters  [P]
- Deliverable: `KafkaSettings`, `KafkaPublisher`, `KafkaEventConsumer`, `KafkaSiemSink`, broker-error translation to the taxonomy, the local-only plaintext rule, and `registration.py` (worker kind `kafka` on `event_consumer`, API publisher registration). Consumer: manual commit, earliest start, per-partition batches from `getmany`, handler awaited, then commit `last + 1`, `CommitFailedError` tolerated, `close()` finishes the in-flight batch. Sink: one record per event with a send timeout.
- Owned files: `packages/adapters-kafka/neurosphere_adapters_kafka/**`, `packages/adapters-kafka/tests/**`.
- Must NOT touch: `pyproject.toml` of the package, core ports.
- Depends on: item 1.
- Acceptance criteria: unit tests with a stub client prove key and value shape, error mapping (no broker text echoed), plaintext refusal when `NS_ENV` is not `local`, commit ordering (handler first, commit second) and `CommitFailedError` handling; the adapter imports no `azure.*`.
- Tests: `packages/adapters-kafka/tests`.
- Pattern references: `ingest/publisher.py:17-45`, `ingestion/consumer.py:96-165`, `audit/siem_eventhubs.py:81-110`.

### Item 3 - S3 and GCS object stores  [P]
- Deliverable: `ObjectStoreSettings`, `S3ObjectStore` (injected or created `aiobotocore` client, `IfNoneMatch="*"` create, 412 and 409 to False, paginated list with bounded `HeadObject` for metadata, taxonomy mapping), `GcsObjectStore` (`if_generation_match=0`, listing with metadata, `asyncio.to_thread` behind a semaphore), `probe_atomic_create`, the non-local credential refusal, and `registration.py` (kinds `s3`, `gcs` for the purposes archive, quarantine, replay, lifecycle_archive).
- Owned files: `packages/adapters-objectstore/neurosphere_adapters_objectstore/**`, `packages/adapters-objectstore/tests/**`.
- Must NOT touch: the package `pyproject.toml`, core ports.
- Depends on: item 1.
- Acceptance criteria: recorded-transport tests prove request shape (conditional header, prefix, pagination token), 404 to `NotFoundError`, 403 to `ForbiddenError`, 5xx and timeouts to `DependencyTransientError`, probe failure to `capability_unavailable`; `STORAGE_EMULATOR_HOST` and custom endpoints are refused outside local.
- Tests: `packages/adapters-objectstore/tests`.
- Pattern references: `archive/sink.py:100-114`, `packages/core/neurosphere_core/clients/factories.py:56-63`.

### Item 4 - Kafka and SIEM conformance
- Deliverable: `tests/conformance/eventstream/test_kafka.py` (loads PRP-88's `checks.py`; adds group-member split, rebalance redelivery, restart resume, new-group earliest start, early-commit broken twin, shutdown drain) and an ingestion-level test that runs the real `IngestionConsumer` and `process_batch` with in-memory sinks over Kafka: a duplicate delivery counts once and a malformed message is quarantined with its offset committed. `tests/conformance/siem/{checks,test_memory,test_kafka}.py` (one record per event, redacted JSON body, timeout raises, `SiemExporter` isolation) with a broken twin that swallows errors.
- Owned files: `tests/conformance/eventstream/test_kafka.py`, `tests/conformance/eventstream/kafka_support.py`, `tests/conformance/siem/**`.
- Must NOT touch: PRP-88's `checks.py` (extend through new modules; a needed change to `checks.py` is a follow-up note).
- Depends on: item 2.
- Acceptance criteria: the stream criteria above pass on the local broker under marker `portable`; the broken twin fails the redelivery check; tests use short session timeouts and a hard per-test timeout so a stuck rebalance fails fast.
- Tests: `tests/conformance/eventstream`, `tests/conformance/siem`.
- Pattern references: `tests/integration/catalog/test_repo_cosmos.py:37-42`, `services/workers/tests/ingestion/test_poison.py`, `test_dedupe.py`.

### Item 5 - Object store conformance
- Deliverable: `tests/conformance/objectstore/test_s3.py` (against the compose store; the atomic-create probe and the 8-writer race; long names; large object), `test_gcs.py` (emulator or the in-process fake chosen in item 1, stated in the test docstring), shared checks loaded from PRP-88's `checks.py`, and a broken twin whose `put_if_absent` overwrites. An archive-sink and quarantine-sink round trip on each store (redelivery writes once; manifest build lists with `sha256` metadata) proves the call sites.
- Owned files: `tests/conformance/objectstore/test_s3.py`, `tests/conformance/objectstore/test_gcs.py`, `tests/conformance/objectstore/store_support.py`.
- Must NOT touch: PRP-88's `checks.py` and `test_azure_blob.py`.
- Depends on: item 3.
- Acceptance criteria: the object criteria above pass for S3 on the local store; for GCS they pass on the emulator or, if item 1 recorded the fallback, on the fake with the live atomicity recorded OPEN; the broken twin fails first-write-wins.
- Tests: `tests/conformance/objectstore`, `services/workers/tests/archive`, `services/workers/tests/quarantine` unchanged.
- Pattern references: `services/workers/tests/archive/test_idempotent_write.py`.

### Item 6 - SIEM and publisher selection  [serial-after: PRP-87]
- Deliverable: only if PRP-87's provider lacks registries for the ingest `Publisher` and the SIEM sink: allow `kafka` in `AuditSiemSettings.sink` (`services/api/neurosphere_api/runtime/settings.py`, the literal beside `file` and `eventhubs`; Tier-2 additive) and add the `kafka` branch in the data builder's `_siem_exporter` (`runtime/builders/data.py`), mirroring `_eventhubs_sink` including the component report and the `audit_siem_settings_invalid` reason; select `KafkaPublisher` in the edge builder when the stream kind is `kafka`. These are PRP-87's Tier-1 files: this item runs only after PRP-87 merged and edits nothing else. If registries exist, this item is a registration check and closes empty.
- Owned files: `runtime/builders/data.py` by serial hand-off from PRP-87 (not listed in Ownership); `runtime/settings.py` as a Tier-2 line.
- Must NOT touch: builders unrelated to SIEM and the publisher.
- Depends on: items 2 and 4; PRP-87 merged.
- Acceptance criteria: `services/api/tests/runtime_data` and `runtime_api` pass unchanged (no new component, `default_builders` order unchanged); a configured `kafka` sink exports a redacted event to the local broker; an invalid configuration reports `audit_siem_settings_invalid` without echoing values.
- Tests: `services/api/tests/runtime_data`, `services/api/tests/runtime_api`, `tests/conformance/siem`.
- Pattern references: `runtime/builders/data.py:374-454`.

### Item 7 - Integration and close-out  [serial-after: PRP-89]
- Deliverable: finish `docs/deploy/portable-streaming-and-objects.md` (settings, operator notes for MSK, Managed Kafka, Strimzi, S3, GCS, the verification record, what is OPEN); `mkdocs.yml` nav line (Tier-2 append); changelog fragment `changelog.d/PRP-92-kafka-and-object-store-adapters.md`; confirm `scripts/portable/run_conformance.py --list` shows the new fragments and directories; Completion note per reference section 6 with the list of new `NS_*` names for the operator.
- Owned files: `docs/deploy/portable-streaming-and-objects.md`, `changelog.d/PRP-92-kafka-and-object-store-adapters.md`.
- Depends on: items 5 and 6.
- Acceptance criteria: gates below pass; the note records each verify-first outcome and any fallback in force.
- Tests: validation gates.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/adapters-kafka/tests packages/adapters-objectstore/tests tests/conformance/eventstream tests/conformance/objectstore tests/conformance/siem services/workers/tests/archive services/workers/tests/quarantine services/workers/tests/ingestion tests/security/authz
docker compose -f infra/compose/portable/kafka.yml up -d --wait
docker compose -f infra/compose/portable/objectstore.yml up -d --wait
uv run pytest -q -m portable tests/conformance/eventstream tests/conformance/objectstore tests/conformance/siem
docker compose -f infra/compose/portable/objectstore.yml down -v
docker compose -f infra/compose/portable/kafka.yml down -v
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: new installs on non-Azure platforms only. Azure deployments keep Event Hubs and Blob through the PRP-88 registry and are untouched. The adapters are opt-in by kind (`kafka`, `s3`, `gcs`). Rollback: revert the PR; unset the kind selection to fall back to the platform default. Topic and bucket contents are not migrated between brokers or stores (OPEN: no Event Hubs to Kafka replay, no blob copy tool).

## Live and open gates
No paid call is made. Everything here runs against local containers or recorded transports. OPEN, handed to PRP-98 (evidence recorded through PRP-64 and PRP-66), each needing `NS_LIVE_APPROVED=1` and an operator: Amazon MSK with IAM broker authentication, Google Cloud Managed Service for Apache Kafka, Strimzi on a real cluster, Amazon S3 conditional writes, GCS atomic create against the real service (always OPEN if item 1 fell back to a fake), consumer-group lag and throughput at the original NFR scale, measured RPO and RTO of the event path (a Kafka topic is not the Event Hubs geo-DR story: broker replication and retention are the operator's design), and the S3-compatible store licence acceptance by the owner.

## NOT building
- A Pub/Sub, Kinesis or OpenSearch adapter; ClickHouse, Neo4j or Qdrant.
- Broker and bucket authentication, IAM, workload identity and Secrets Manager (PRP-94).
- The Helm chart, operators and the air-gap image bundle (PRP-96); Terraform (PRP-97).
- Moving the Azure adapters; any change to the Event Hubs or Blob behaviour (PRP-88 keeps them).
- GCS through the S3-interoperable API.
- A data copy tool between Event Hubs and Kafka or between blob stores.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 4, 5 and 9 are ASSUMPTIONS or conditional for plan approval; row 5 is owner decision D-5 in PRP-85; item 1 settles the UNVERIFIED facts before coding; PRP-87, PRP-88 and PRP-89 names are read by purpose until they merge)

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
