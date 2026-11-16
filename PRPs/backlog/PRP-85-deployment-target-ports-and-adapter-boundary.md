---
name: PRP-85-deployment-target-ports-and-adapter-boundary
status: backlog
priority: P1
order: 76
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-07, NS-08
depends_on: []
wave: W34
branch: prp-85-deployment-target-ports
allow_parallel: true
issues: []
---

# PRP-85: Deployment target, neutral ports and the adapter boundary (multi-cloud foundation)

## Goal
Lay the foundation every other multi-cloud hosting PRP (PRP-86 to PRP-98) builds on, without changing any Azure behaviour: an ADR that records the two program decisions (D-1 platform axis, D-2 portable backend set) and the per-port target mapping; a `DeploymentTarget` axis selected by `NS_PLATFORM` (`azure` default) beside the existing `NS_CLOUD` boundary class, with "government requires azure" enforced at settings load; a `PlatformProfile`; neutral port Protocols for the ports that have no neutral home today (event publisher, secret reader, token provider, telemetry exporter; the event consumer and object store ports are designated here and introduced by PRP-88) plus designation of the existing neutral Protocols (document stores, catalog `DocBackend`, search, model, judge, SIEM, analytics); a `Backends` registry Protocol; a machine-readable port inventory; an AST import-boundary test with a ratchet list of today's Azure leaks; a platform-outputs schema that the Helm and Terraform PRPs share; and the amendments to `docs/PRD.md`, `PRP.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md` and `AGENTS.md` that make multi-cloud hosting and the restored original scope part of the build authority. It is for the implementers of PRP-86..98, who code against the names in "Interfaces provided", and for the owner, who decided D-1 and D-2 on 2026-11-16. It runs alone in W34 because it amends the build-authority documents and every later wave depends on its names.

Out of scope: rewiring any composition root or adapter (API seam and adapter package scaffolding: PRP-87; worker seam, event-consumer and object-store adoption: PRP-88); any contract schema change, including the capability-matrix `platform` dimension and new credential-reference kinds (PRP-86); any non-Azure implementation (PRP-89..95); Helm, Terraform and on-prem references (PRP-96, PRP-97); filling the RPO/RTO table, the conformance matrix and making the boundary ratchet strict (PRP-98); a sixth Mermaid diagram in `docs/ARCHITECTURE.md` (the validator pins five).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-107): "Platform deployable via containerized/IaC templates to Azure, AWS, GCP, or on-prem Kubernetes, with provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer." Criteria: "Reference IaC (Terraform/Bicep) provided for each of the four target environments.", "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ.", "Documented RPO/RTO per deployment target." Story: "As an enterprise customer with data-residency requirements, I want an on-prem/air-gapped deployment option." This PRP serves the "common abstraction layer" and "only infra adapters differ" criteria.
- v1.2 excluded it: `docs/PRD.md:4` "third-party AI providers are connector targets, not a commitment to deploy the platform on AWS/GCP/on-prem"; `docs/PRD.md:57` "AWS/GCP hosting, classified/air-gapped deployment ... are outside the initial baseline"; `PRP.md:7` "No commitment to platform hosting on AWS/GCP/on-prem."; `PRP.md:11` "Terraform is not a second mandatory implementation."; `CLAUDE.md:3` "These v1.2 documents are the build authority." and `docs/ARCHITECTURE.md:8` "standalone Kafka/PubSub/Kinesis are historical comparisons, not supported hosting promises". On 2026-11-16 the owner restored multi-cloud hosting with all four targets (Azure, AWS, GCP, on-prem Kubernetes); without amending these lines every later PRP contradicts the build authority.
- There is no platform axis: `CloudName` has two members (`packages/core/neurosphere_core/cloud/profile.py:12-14`), `Settings` reads only `NS_ENV` and `NS_CLOUD` (`packages/core/neurosphere_core/cloud/settings.py:13-30`), and Helm fails on any other cloud value (`infra/helm/templates/deployment.yaml:2-4`).
- Several ports have no neutral Protocol: the event publisher Protocol imports `EventData` beside it (`services/api/neurosphere_api/ingest/publisher.py:8,13-14`); the ingestion consumer takes an `EventHubConsumerClient` with SDK-shaped slices (`services/workers/neurosphere_workers/ingestion/consumer.py:27-28,41-62`); the blob Protocol requires `azure.core.exceptions.ResourceExistsError` (`services/workers/neurosphere_workers/archive/protocols.py:19-24`); the secret reader Protocol lives in the workers (`services/workers/neurosphere_workers/connector_config/keyvault.py:64-65`); model adapters take `AsyncTokenCredential` (`packages/core/neurosphere_core/copilot/models/approved_endpoint.py:14`).
- Leaks are not enforced: re-measured on this tree, non-test product code has 146 `azure` import lines in 66 files, and 36 files outside adapter-named modules (core 14, API 10, workers 11, docs-assistant 1; list in `temp/audit/multicloud-program-design.md` section 2.1, re-verified). The only boundary test today is "core never imports the services" (`packages/core/tests/test_import_boundaries.py:8-30`).

## Acceptance criteria
- [ ] ADR `docs/adr/<NNNN>-multicloud-hosting.md` (number settled per Clarification 4) exists in the ADR-0008 shape (Status, Date, Deciders, Relates to, Context, Options, Criteria, Decision, Consequences) and records D-1 (the `commercial:` segment off Azure is a boundary label, not a hosting claim), D-2 (Pub/Sub, OpenSearch, Neo4j, ClickHouse and Qdrant recorded OPEN), the outcomes of the owner decisions D-3 to D-12 below (decided 2026-11-16; D-13 stays open), the per-port mapping (design section 3.2), the portable-backend licence notes (asyncpg not psycopg, OpenTofu not Terraform, MinIO AGPL owner note), the platform-outputs schema, the threat-model delta (database, broker, object store and IdP become trust boundaries not managed by Azure on other platforms), the Azure-only features that degrade (design section 6) and the OPEN list (design section 9). D-1 and D-2 were decided by the owner on 2026-11-16, so the ADR records them as decided and items 2-7 do not wait on them (the only owner stop left in this PRP is the exact `CLAUDE.md`/`AGENTS.md` wording in item 6).
- [ ] Given `NS_PLATFORM` unset, When `Settings()` loads, Then `platform == DeploymentTarget.AZURE` and every existing settings, cloud-profile and composition test passes unchanged. Given `NS_PLATFORM=aws|gcp|kubernetes` and `NS_CLOUD=government`, Then loading fails with a validation error naming `NS_PLATFORM`; given an unknown value, Then it fails; given `NS_PLATFORM=kubernetes` and `NS_CLOUD=commercial`, Then it loads and `platform_profile.cloud_profile is None`.
- [ ] Every Protocol in "Interfaces provided" is importable from `neurosphere_core.platform.ports`, is `runtime_checkable`, imports no vendor SDK, and has an in-memory reference implementation used by its unit test (token expiry refresh, publish partition key). No Protocol for the event consumer or the object store is defined under `platform/` (PRP-88 owns them).
- [ ] `neurosphere_core.platform.inventory.PORTS` lists every port of design section 1 with its Protocol dotted path, required or optional, and the Azure implementation dotted path; a test imports every dotted path, and fails when a Protocol named in `ports/__init__.py` is missing from the inventory. The `event_consumer` and `object_store` entries name PRP-88's paths (`neurosphere_core.eventstream.EventConsumer`, `neurosphere_core.objectstore.ObjectStore`) with `introduced_by="PRP-88"`; the import test treats such an entry as pending (no import) until PRP-88 clears the flag.
- [ ] Given a new non-test product module that imports `azure` (or another vendor root in `FORBIDDEN_ROOTS`) outside an adapter path, When `tests/architecture` runs, Then it fails naming the file; Given a `KNOWN_LEAKS` entry whose file no longer leaks, Then it fails asking for the entry to be removed (the list only shrinks); lazy imports inside functions count.
- [ ] `docs/PRD.md`, `PRP.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md` and `AGENTS.md` state that hosting on Azure, AWS, GCP and on-prem Kubernetes (including an air-gapped, non-classified on-prem install) is in scope by owner decision of 2026-11-16, that the original PRD sections 5a-5g (`git show 9fbf5f4c:docs/PRD.md`) are restored alongside v1.2, and that Government stays Azure-only; `python scripts/validate_planning.py` passes (five Mermaid blocks, Fabric/Synapse/Databricks still named, no banned phrase).
- [ ] `docs/ops/rpo-rto.md` exists with one row per target and every value "target, unmeasured" (RTO 4 h, RPO 15 min from `docs/PRD.md:53`); `docs/dev/platform-ports.md` is generated from `PORTS` and a test fails when it drifts.
- PRP exit: touched suites, ruff, pyright, `validate_planning.py` pass; PR open with CI green; no file under `services/**`, `infra/**` or `packages/contracts/**` changed.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Where the neutral Protocols live | `neurosphere_core.platform.ports`; per-feature packages | `neurosphere_core.platform.ports` (one module per port family); existing neutral Protocols are designated in place, not moved, so no import breaks |
| 4 | ADR number | 0009; next free at execution | `docs/adr/` holds 0001-0008 and PRP-69 reserves `0009-mcp-private-network-servers.md`. At execution take the lowest number neither present in `docs/adr/` nor reserved by a `docs/adr/NNNN-` path in an unshipped PRP under `PRPs/backlog/` or `PRPs/active/` (expected 0010). The slug `multicloud-hosting` is fixed; PRP-86..98 cite the ADR by slug |
| 5 | Port registration for non-Azure adapters | static list in core (Tier-2 appends); `importlib.metadata` entry points | ASSUMPTION: entry-point group `neurosphere.backends` (PRP-87 declares one per adapter package, so W36 PRPs never share a registration file); Azure registers explicitly from its composition roots |
| 6 | Does this PRP edit `scripts/validate_planning.py` | own it; leave it | Leave it: the banned phrases are only "No Microsoft Fabric / OneLake" and "No real-data ingestion paths" (`scripts/validate_planning.py:75`), which the amendments do not use; no sixth diagram is added (`:88-90` pins five) |
| 7 | Where the port page lives | `docs/architecture/ports.md` (design); a published existing folder | `docs/dev/platform-ports.md`: `docs/architecture/` does not exist and is not in the `exclude_docs` allowlist of `mkdocs.yml`, while `docs/dev/` is published |
| 8 | Leak baseline | the 36 files of the design; regenerate at execution | Regenerate at execution: PRP-70..84 ship before W34 and may add or remove leaks; every entry names the PRP that removes it (87, 88, 95, 98) |
| 9 | Build-authority edits to `CLAUDE.md` and `AGENTS.md` | edit; leave to the owner | Edit, but only after the owner approves the exact diff in the session (owner decision D-13 below) |

## Owner decisions (decided 2026-11-16)
The single list for the program (PRP-85 to PRP-98); other PRPs cite these ids instead of repeating the question. On 2026-11-16 the owner accepted the recommended defaults for D-1 and D-2 (the Clarifications rows above) and for D-3 to D-12; each is decided as written in the third column and the item 1 ADR records the outcomes. D-13 is NOT decided: this PRP still stops for owner approval of the exact `CLAUDE.md` and `AGENTS.md` wording (item 6) before those two files change. If the owner later reverses a decided entry, the affected PRPs are re-planned.

| Id | Decision | Decided default (accepted 2026-11-16; D-13 open) | Affects |
|---|---|---|---|
| D-3 | Principal ids of non-Entra users: keep the literal `entra` segment (`<cloud>:<customer>:entra:(person|principal):p-<hex>`) as a namespace label, or widen the contract pattern to `(entra|oidc)` | Decided: Keep the segment (one pattern site, every example and stored id untouched); OIDC principals are minted under it from a hash of tenant label and subject | PRP-86, PRP-93 |
| D-4 | Hyphenated AWS and GCP region names: loosen the `region` pattern of `capability-matrix-entry` and the deployment-manifest `$defs/region`, or add a separate `provider_region` field | Decided: Loosen the pattern as a reviewed `ALLOWED_TIGHTENINGS` entry recorded in ADR-0004 (a versioning exception to PRP-70's empty allowlist) | PRP-86, PRP-97, PRP-98 |
| D-5 | On-prem S3-compatible object-store reference: MinIO (AGPL-3.0 server, customer-run, never linked) or SeaweedFS (Apache-2.0) | Decided: MinIO with the AGPL owner note in ADR-0002, only if PRP-92 item 1 verifies a maintained official image and atomic `If-None-Match: *`; otherwise SeaweedFS. Adapter code does not depend on the choice | PRP-87, PRP-92, PRP-96, PRP-98 |
| D-6 | Identity: exactly one identity provider per deployment (`NS_AUTH_PROVIDER=entra|oidc`) and generic OIDC refused when `NS_CLOUD=government` | Decided: Yes to both; multi-issuer is a follow-up | PRP-93, PRP-96 |
| D-7 | PostgreSQL security stores: audit records stored as exact bytes (`json` column, not `jsonb`) with an UPDATE/DELETE-refusing trigger; tenant isolation by mandatory partition arguments in `PgCollection` rather than row-level security | Decided: Yes; row-level security is a later defence-in-depth follow-up | PRP-89, PRP-90, PRP-91 |
| D-8 | Whether a Vault/OpenBao KV secret reader is in scope beside the AWS, GCP and Kubernetes-file readers | Decided: In scope (the design's reader set); it can be cut to a follow-up without affecting the other readers | PRP-94, PRP-96, PRP-98 |
| D-9 | AWS SDK flavour: `aiobotocore` for the adapters while PRP-62 locks `boto3`, both in one `uv.lock` | Decided: `aiobotocore`, co-resolved with PRP-62's `boto3` in PRP-87 item 1; if they cannot co-resolve, stop and ask (adapters use `boto3` plus `to_thread`, or PRP-62 moves to `aiobotocore`) | PRP-87, PRP-92, PRP-94, PRP-95, PRP-62 |
| D-10 | One container image set for all platforms (platform chosen at run time by `NS_PLATFORM`) or per-platform images | Decided: One image set; cost (image size, scan surface) recorded in the ADR | PRP-87, PRP-96 |
| D-11 | When PRP-98 makes the boundary strict: may it leave a named exception (an allowlist entry naming the owning PRP and a follow-up issue) or must it block until the leak is fixed | Decided: Named exception allowed, each with owning PRP and follow-up issue; PRP-98 never edits product code | PRP-98 (and every PRP with a `KNOWN_LEAKS` entry) |
| D-12 | Cut order if PRP-95 overruns its session | Decided: Cut the Vertex adapter first (recorded OPEN); any further cut is decided by the owner at that point | PRP-95, PRP-96, PRP-98 |
| D-13 | Exact diffs to `CLAUDE.md` and `AGENTS.md` (the agents' operating instructions) | OPEN, not decided: shown to and approved by the owner in the PRP-85 session before item 6 commits them | PRP-85 |

## Context manifest

### Files to read first
- `temp/audit/multicloud-program-design.md` sections 1-3, 7 and 9 - port inventory, leak list, mapping, OPEN list (if the planning worktree is gone: `git log --all -- temp` is empty; ask the owner for the file).
- `packages/core/neurosphere_core/cloud/profile.py` and `cloud/settings.py` - `CloudName`, `CloudProfile`, `Settings` validator.
- `packages/core/tests/test_import_boundaries.py` - AST import walk to extend.
- `packages/core/neurosphere_core/catalog/repo/backend.py:54-110` - `Query`, `DocBackend` (the model for a small neutral port).
- `services/api/neurosphere_api/ingest/publisher.py`, `services/workers/neurosphere_workers/ingestion/consumer.py`, `ingestion/models.py:65` (`RawMessage`), `archive/protocols.py`, `connector_config/keyvault.py:60-100` - SDK-shaped ports to neutralise.
- `packages/core/neurosphere_core/observability/telemetry.py:35-60` - `configure_telemetry(metric_readers=, span_processors=)`.
- `scripts/validate_planning.py:63-96` - doc rules.
- `docs/adr/0008-docs-site-tool.md` - ADR shape; `mkdocs.yml:76-100,182-189` - publish allowlist and ADR nav.
- `docs/PRD.md:1-4,53,57`, `PRP.md:1-16`, `docs/ARCHITECTURE.md:1-12`, `CLAUDE.md:1-12`, `AGENTS.md:1-4` - lines to amend.

### Interfaces consumed
- Shipped: `CloudName`, `CloudProfile`, `profile_for`, `Settings` (`neurosphere_core.cloud`); `neurosphere_core.errors` taxonomy (`NotFoundError`, `StaleVersionError`, `DependencyTransientError`, `CapabilityUnavailableError`); `HubMessage` (`neurosphere_core.payload`); `CredentialReference` (`neurosphere_contracts.admin.v1.credential_reference`); `ClientLifetime` (`neurosphere_core.clients.lifetime`).
- Existing neutral Protocols designated as ports (not moved): `CatalogRepository`, `GraphQuery`, `DocBackend`; the per-store Protocols of design section 1.1; `AuthorizedSearch`, `IndexSink`; `ModelAdapter` (`copilot/models/protocol.py`); `Judge` (`evaluation/judge.py:80`); `SiemSink` (`audit/siem.py`); `AnalyticsAdapter`.
- PRP-70..84 shipped (W19-W32); none of their names is needed here, but their files enter the leak scan.

### Interfaces provided
- `neurosphere_core.platform.target`: `DeploymentTarget(StrEnum)` = `azure`, `aws`, `gcp`, `kubernetes`; `PlatformProfile` (frozen: `target`, `boundary: CloudName`, `cloud_profile: CloudProfile | None` (Azure only), `azure_features_available: bool`); `platform_profile_for(target, boundary) -> PlatformProfile`; `PlatformConfigError`. `neurosphere_core.cloud.Settings` gains `platform: DeploymentTarget = azure` (env `NS_PLATFORM`) and property `platform_profile`; `cloud_profile` is unchanged.
- `neurosphere_core.platform.ports` (new Protocols, all async, `runtime_checkable`):
  - `EventPublisher`: `publish(messages: Sequence[HubMessage]) -> None` (partition key = `HubMessage.partition_key()`).
  - `SecretReader`: `read(reference: CredentialReference) -> SecretStr` (same signature as the worker Protocol, which PRP-94 re-points here).
  - `TokenProvider`: `get_token(*scopes: str) -> AccessToken`, `close() -> None`; `AccessToken(token: SecretStr, expires_on: int)`.
  - `TelemetryExporterFactory`: `__call__(settings) -> TelemetryExporters | None`; `TelemetryExporters(metric_readers, span_processors)` feeds `configure_telemetry`.
  - Designated (re-exported, unchanged): document store backend = `DocBackend` plus the per-store Protocols listed in `PORTS`; search = `AuthorizedSearch`, `IndexSink`; model client = `ModelAdapter`, `Judge`; SIEM = `SiemSink`; analytics = `AnalyticsAdapter`.
  - Designated, introduced by PRP-88 (listed in `PORTS`, not defined or re-exported here): event consumer = `neurosphere_core.eventstream.EventConsumer`; object store = `neurosphere_core.objectstore.ObjectStore` (contracts as in PRP-88 "Interfaces provided").
- `neurosphere_core.platform.errors`: `AlreadyExistsError` (create conflict for documents), `PortUnavailableError(reason)`, `ErrorTranslator` Protocol (`translate(exc: BaseException) -> NeuroSphereError | None`).
- `neurosphere_core.platform.registry`: `PortName(StrEnum)` (one value per inventory port, e.g. `catalog_backend`, `policy_store`, `audit_store`, `event_publisher`, `event_consumer`, `object_store`, `search`, `index_sink`, `token_provider`, `secret_reader`, `model_adapter`, `judge`, `telemetry_exporter`, `siem_sink`); `BackendContext` (settings, platform profile, environ, lifetime); `BackendFactory = Callable[[BackendContext], object]`; `Backends` Protocol (`target`, `supports(port) -> bool`, `create(port, ctx) -> object`, raising `PortUnavailableError("platform_backend_missing")`); `BackendRegistry` (`register(target, port, factory)`, `for_target(target) -> Backends`, `load_entry_points(group="neurosphere.backends")`).
- `neurosphere_core.platform.inventory`: `PortSpec(name, protocol, required, family, implementations: Mapping[DeploymentTarget, tuple[str, ...]], disabled_reason: Mapping[DeploymentTarget, str], introduced_by: str | None)`, `PORTS`, `port(name)`, `render_markdown()`. After this PRP merges, `PORTS` is a Tier-2 registry: later PRPs add one implementation path per line or clear their own `introduced_by` flag, never reshape entries.
- `neurosphere_core.platform.outputs`: `PlatformOutputs` model and `outputs.schema.json` (endpoints, role or service-account identifiers, bucket, topic and secret names; names only, never values), consumed by PRP-96 values and emitted by PRP-97 Terraform.
- `tests/architecture/boundary.py`: `SCANNED_ROOTS`, `FORBIDDEN_ROOTS` (`azure`, `boto3`, `botocore`, `aiobotocore`, `google.cloud`, `google.auth`, `asyncpg`, `aiokafka`), `ADAPTER_PATHS` (name-marked Azure adapters such as `*_cosmos.py` and `publisher_eventhubs.py`, `neurosphere_core/platform/azure/**`, `neurosphere_api/runtime/backends/**` (PRP-87), `neurosphere_workers/runtime/backends_azure.py` (PRP-88; `runtime/backends.py` stays neutral), the API-package PostgreSQL stores `neurosphere_api/{copilot,reports,sandbox}/postgres_store.py` (PRP-91; they import the adapter package, never a driver), `packages/adapters-*/**`), `KNOWN_LEAKS: dict[str, str]` (path -> removing PRP), `LEAK_CEILING`. After this PRP merges, `KNOWN_LEAKS` and `LEAK_CEILING` are deletion-only Tier-2: a later PRP removes only the entries it fixed and lowers the ceiling; at rebase both deletions are kept and the ceiling recomputed.
- The multicloud-hosting ADR; `docs/dev/platform-ports.md`; `docs/ops/rpo-rto.md` (PRP-98 fills it).
- Registry of platform settings (the single list of new settings for PRP-96 Helm values and PRP-97 Terraform outputs; each row is implemented by its owner PRP, not here, except `NS_PLATFORM`). Names only; no row holds a credential value.

| Setting | Owner PRP | Meaning |
|---|---|---|
| `NS_PLATFORM` | PRP-85 | Deployment target `azure` (default), `aws`, `gcp`, `kubernetes`; `government` only with `azure` |
| `NS_DOCUMENT_STORE_KIND` | PRP-88 | Optional document-store kind override (`cosmos`, `postgres`); unset = platform default; an Azure kind on a non-Azure platform is refused |
| `NS_EVENTSTREAM_KIND` | PRP-88 | Optional event-stream kind override (`eventhubs`, `kafka`); unset = platform default |
| `NS_OBJECTSTORE_KIND` | PRP-88 | Optional object-store kind override (`azure_blob`, `s3`, `gcs`); unset = platform default |
| `NS_POSTGRES_HOST`, `_PORT`, `_DATABASE`, `_USER`, `_SSLMODE`, `_POOL_MAX`, `_STATEMENT_TIMEOUT_MS` | PRP-89 | PostgreSQL connection (names only) |
| `NS_POSTGRES_AUTH`, `NS_POSTGRES_PASSWORD` | PRP-89 | `password` or `token`; the password setting is refused outside `NS_ENV=local` (token comes from PRP-94) |
| `NS_SEARCH_PROVIDER=postgres` | PRP-91 | New value of the existing search provider setting |
| `NS_KAFKA_BOOTSTRAP_SERVERS`, `_TOPIC`, `_GROUP_ID`, `_SIEM_TOPIC`, `_CLIENT_ID`, `_SECURITY_PROTOCOL` | PRP-92 | Kafka API broker, topics, consumer group; `plaintext` only when `NS_ENV=local` |
| `NS_OBJECTSTORE_S3_ENDPOINT_URL`, `_S3_REGION`, `_S3_FORCE_PATH_STYLE`, `_GCS_PROJECT`, `_GCS_API_ENDPOINT` | PRP-92 | S3-API and GCS object-store addressing; emulator endpoints refused outside local |
| `NS_AUDIT_SIEM_SINK=kafka` | PRP-92 | New value of the existing SIEM sink setting |
| `NS_AUTH_PROVIDER` | PRP-93 | `entra` (default) or `oidc`; one provider per deployment (D-6) |
| `NS_AUTH_OIDC_*` (`ISSUER`, `JWKS_URI`, `JWKS_ALLOWED_ORIGIN`, `AUDIENCES`, `AUDIENCE_MODE`, `CLIENT_ID_CLAIM`, `CLIENT_IDS`, `TENANT_LABEL`, `TENANT_CLAIM`, `SUBJECT_CLAIM`, `ROLES_CLAIM`, `GROUPS_CLAIM`, `SCOPES_CLAIM`, `IDENTITY_TYPE_CLAIM`, `APP_IDENTITY_VALUES`, `REQUIRED_CLAIMS`, `LEEWAY_SECONDS`) | PRP-93 | Generic OIDC issuer, pinned JWKS, audiences and claim map |
| `NS_SECRETS_AWS_ACCOUNTS`, `_AWS_REGION`, `_GCP_PROJECTS`, `_K8S_MOUNT_ROOTS`, `_VAULT_ADDRESS`, `_VAULT_MOUNT`, `_VAULT_PATH_PREFIX`, `_VAULT_AUTH`, `_VAULT_ROLE` | PRP-94 | Secret-reader allowlists and Vault/OpenBao addressing (Vault rows depend on D-8) |
| `NS_WORKLOAD_IDENTITY` | PRP-94 | Workload identity source `azure`, `eks`, `gke`, `none` |
| `NS_COPILOT_MODE` (`openai_compatible`, `bedrock`, `vertex`) | PRP-95 | New values of the existing copilot mode setting |
| `NS_COPILOT_APPROVED_HOSTS` | PRP-95 | Exact-host allowlist for model endpoints off Azure |
| `NS_TELEMETRY_EXPORTER` | PRP-95 | `azure_monitor` (default), `otlp`, `none`; OTLP uses the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` |
| `NS_ANALYTICS_BACKEND=postgres` | PRP-95 | New value of the existing analytics backend setting |

### Patterns to match
- AST import scan: `packages/core/tests/test_import_boundaries.py:11-30`.
- Settings validator: `packages/core/neurosphere_core/cloud/settings.py:20-26`.
- Small neutral port with an in-memory twin: `packages/core/neurosphere_core/catalog/repo/backend.py:90-110` and `repo/memory.py:53`.
- ADR shape and stop point: `docs/adr/0008-docs-site-tool.md`; `PRPs/backlog/PRP-69-mcp-private-network-servers.md` item 1.

### Gotchas
- Do not name a test directory `platform`: with `__init__.py` it shadows the stdlib `platform` module in the pytest session. Use `packages/core/tests/platform_ports/`.
- `Settings` is `frozen` and `extra="forbid"`; adding a field is fine, but the `cloud_profile` property must stay byte-identical (45 non-test files read it).
- CLAUDE.md says git-history material is not build authority, and the original PRD lives in git history (`9fbf5f4c`): the amendment must name that commit and sections 5a-5g explicitly as restored, and keep the hard constraints winning on conflict.
- `validate_planning.py` also runs `prp_status.py --check` and the INDEX check: PRP-85..98 must already be in the master index (plan-merge step), or the gate fails for reasons unrelated to this PRP.
- The leak scan must exclude in-package test directories (for example `packages/core/neurosphere_core/recommendations/tests/`), not only top-level `tests/`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/platform/__init__.py
  - packages/core/neurosphere_core/platform/target.py
  - packages/core/neurosphere_core/platform/errors.py
  - packages/core/neurosphere_core/platform/registry.py
  - packages/core/neurosphere_core/platform/inventory.py
  - packages/core/neurosphere_core/platform/outputs.py
  - packages/core/neurosphere_core/platform/outputs.schema.json
  - packages/core/neurosphere_core/platform/ports/**
  - packages/core/neurosphere_core/cloud/**
  - packages/core/tests/platform_ports/**
  - packages/core/tests/cloud/**
  - packages/core/tests/test_cloud_profile.py
  - tests/architecture/**
  - docs/adr/0010-multicloud-hosting.md
  - docs/dev/platform-ports.md
  - docs/ops/rpo-rto.md
  - docs/PRD.md
  - PRP.md
  - docs/ARCHITECTURE.md
  - CLAUDE.md
  - AGENTS.md
tier1: []
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - packages/core/neurosphere_core/platform/azure/**
  - packages/contracts/**
  - services/**
  - infra/**
  - scripts/validate_planning.py
  - pyproject.toml
  - uv.lock
  - docs/RESEARCH-AND-GATES.md
  - docs/security/threat-model.md
```

## Implementation blueprint

Parallelization: item 1 first (stop point). Then items 2 and 5 [P]; item 3 after 2; item 4 after 3; item 6 after 1 and in parallel with 2-5 (docs only); item 7 last.

### Item 1 - Multicloud-hosting ADR
- Deliverable: settle the number (Clarification 4); write the ADR with D-1, D-2, the per-port mapping, licence notes, the platform-outputs schema outline, the threat-model delta, the degradation table and the OPEN list; `mkdocs.yml` nav line. Record D-1 and D-2 (decided 2026-11-16) and D-3 to D-12 ("Owner decisions (decided 2026-11-16)") in the ADR as decided; D-13 stays open until item 6.
- Owned files: `docs/adr/<NNNN>-multicloud-hosting.md` (new; the Ownership block names the expected `0010`; if Clarification 4 yields another number, the ownership line follows it), `mkdocs.yml` (one nav line).
- Must NOT touch: other ADRs, `docs/security/threat-model.md` (PRP-98 writes the threat-model delta into it).
- Depends on: none.
- Acceptance criteria: criterion 1; `tests/docs/test_nav_allowlist.py` passes.
- Tests: `tests/docs/test_nav_allowlist.py`.
- Pattern references: `docs/adr/0008-docs-site-tool.md`.

### Item 2 - DeploymentTarget, NS_PLATFORM and PlatformProfile  [P]
- Deliverable: `platform/target.py`; `cloud/settings.py` field, validator ("government requires azure") and `platform_profile` property; `platform/__init__.py` exports.
- Owned files: `packages/core/neurosphere_core/platform/{__init__,target}.py` (new), `packages/core/neurosphere_core/cloud/**`, `packages/core/tests/platform_ports/test_target.py` (new), `packages/core/tests/test_cloud_profile.py` (additive cases only).
- Must NOT touch: `CloudProfile` fields, `profile_for`, any caller of `cloud_profile`.
- Depends on: item 1 accepted.
- Acceptance criteria: criterion 2; `packages/core/tests/cloud` and `test_cloud_profile.py` pass unchanged apart from added cases.
- Tests: `packages/core/tests/platform_ports/test_target.py`, `packages/core/tests/cloud`, `packages/core/tests/test_cloud_profile.py`.
- Pattern references: `cloud/settings.py:20-30`.

### Item 3 - Neutral port Protocols, errors and the Backends registry
- Deliverable: `platform/ports/{events,secrets,tokens,telemetry,documents,search,models}.py` (new Protocols plus re-exports of the designated ones; no event-consumer or object-store module, PRP-88 introduces those), in-memory reference implementations under `platform/ports/memory.py`, `platform/errors.py`, `platform/registry.py` with entry-point loading that tolerates zero entry points.
- Owned files: `packages/core/neurosphere_core/platform/{ports/**,errors.py,registry.py}` (new), `packages/core/tests/platform_ports/test_ports.py`, `test_registry.py` (new).
- Must NOT touch: the modules that define the designated Protocols.
- Depends on: item 2.
- Acceptance criteria: criterion 3; `BackendRegistry.for_target(kubernetes).create(...)` with nothing registered raises `PortUnavailableError("platform_backend_missing")`; no vendor import under `platform/` (checked by item 5).
- Tests: `packages/core/tests/platform_ports/test_ports.py`, `test_registry.py`.
- Pattern references: `catalog/repo/backend.py:90-110`, `catalog/repo/memory.py:53`.

### Item 4 - Port inventory, generated port page and platform outputs
- Deliverable: `platform/inventory.py` (`PORTS` from design section 1, Azure implementation paths verified by import), `render_markdown()` writing `docs/dev/platform-ports.md`, drift test; `platform/outputs.py` and `outputs.schema.json` with a valid and an invalid example in the test.
- Owned files: `packages/core/neurosphere_core/platform/{inventory,outputs}.py`, `outputs.schema.json` (new), `docs/dev/platform-ports.md` (new), `packages/core/tests/platform_ports/test_inventory.py`, `test_outputs.py` (new), `mkdocs.yml` (one nav line).
- Must NOT touch: `docs/deploy/**` (PRP-96, PRP-97).
- Depends on: item 3.
- Acceptance criteria: criteria 4 and 7 (port page half); a `PlatformOutputs` field that looks like a secret value (`password`, `secret_value`, `connection_string`) is refused by a test.
- Tests: `packages/core/tests/platform_ports/test_inventory.py`, `test_outputs.py`, `tests/docs/test_nav_allowlist.py`.
- Pattern references: `docs/reference/generate.py` (generated-page drift style).

### Item 5 - Import-boundary test with ratchet  [P]
- Deliverable: `tests/architecture/boundary.py` (constants), `test_adapter_boundary.py` (new leak fails, stale entry fails, ceiling), `KNOWN_LEAKS` regenerated from the current tree with the removing PRP per entry (API and core leaks: PRP-87; worker leaks: PRP-88; telemetry and Databricks executor: PRP-95; `stores/containers.py`: PRP-98; docs-assistant model: no owning PRP yet, named under D-11).
- Owned files: `tests/architecture/**` (new).
- Must NOT touch: `packages/core/tests/test_import_boundaries.py` (left as is).
- Depends on: none.
- Acceptance criteria: criterion 5; a planted temporary leak in a test fixture tree is caught (the test takes the scanned roots as a parameter).
- Tests: `tests/architecture/test_adapter_boundary.py`.
- Pattern references: `packages/core/tests/test_import_boundaries.py:11-30`.

### Item 6 - Build-authority amendments and RPO/RTO skeleton
- Deliverable: show the owner the diff first (Clarification 9). `docs/PRD.md:4` and `:57`: hosting on all four targets in scope, classified deployment and formal certifications still out; a short "Restored scope (owner decision 2026-11-16)" paragraph naming original sections 5a-5g at `9fbf5f4c`, the restoring PRPs (70-84, 85-98) and that hard constraints win on conflict. `PRP.md:7,11,13`: replace the no-commitment sentence, scope "Terraform is not a second mandatory implementation" to Azure, and qualify the Event Hubs and "no standalone Kafka" sentence as the Azure profile with the Kafka API on the other targets. `docs/ARCHITECTURE.md`: Events, Compute, Catalog and Search rows gain the portable counterpart; no new diagram. `CLAUDE.md` read-order and Mission lines and `AGENTS.md:3`: same facts in one sentence each, Government Azure-only. `docs/ops/rpo-rto.md` skeleton plus nav line.
- Owned files: `docs/PRD.md`, `PRP.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`, `AGENTS.md`, `docs/ops/rpo-rto.md` (new), `mkdocs.yml` (one nav line).
- Must NOT touch: `README.md`, `docs/RESEARCH-AND-GATES.md` (PRP-98 adds the gate rows), `scripts/validate_planning.py`.
- Depends on: item 1 accepted.
- Acceptance criteria: criteria 6 and 7 (RPO/RTO half); Fabric, Synapse and Databricks still named in the three docs; exactly five Mermaid blocks.
- Tests: `tests/test_planning_alignment.py`, `tests/docs/test_nav_allowlist.py`.
- Pattern references: existing one-paragraph style of `PRP.md` section 2.

### Item 7 - Integration and close-out
- Deliverable: rebase; regenerate Tier-3 (`docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`); changelog fragment `changelog.d/PRP-85-deployment-target-ports-and-adapter-boundary.md`; completion note listing every provided name for PRP-86..98 authors, the ADR number, the final `KNOWN_LEAKS` count, and `NS_PLATFORM` for the operator.
- Owned files: this PRP file, the changelog fragment, Tier-3 files per reference section 2.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/platform_ports packages/core/tests/cloud packages/core/tests/test_cloud_profile.py packages/core/tests/test_import_boundaries.py tests/architecture tests/docs tests/test_planning_alignment.py services/api/tests/runtime_api
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data or schema migration: `NS_PLATFORM` defaults to `azure`, so every existing deployment, compose file and Helm release is unchanged and needs no new setting. Rollback is a revert of the PR; the new modules have no callers until PRP-87 and PRP-88. The document amendments are reverted with the PR if the owner withdraws the decision.

## Live and open gates
None: no cloud call, no deployment and no paid service. Every real AWS, GCP and on-prem run is OPEN and handed to PRP-98, which hands the operator runs to PRP-64 and PRP-66.

## NOT building
Composition rewiring; adapters; contract changes; Helm `platform` value or the Helm Government guard change (PRP-96); Terraform; the conformance-coverage test (PRP-98, once `tests/conformance/` exists); moving `ContainerSpec.partition_key()` out of the Tier-1 stores registry (PRP-98 or the next stores owner); a widened cloud enum (D-1 alternative).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 and D-3 to D-12 were decided by the owner 2026-11-16; row 5 is an ASSUMPTION for the owner; row 9 is D-13, still open: the owner approves the exact `CLAUDE.md`/`AGENTS.md` diffs in item 6)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | prp-85-deployment-target-ports | D-1, D-2 decided 2026-11-16 |
| 2 | todo | prp-85-deployment-target-ports | |
| 3 | todo | prp-85-deployment-target-ports | |
| 4 | todo | prp-85-deployment-target-ports | |
| 5 | todo | prp-85-deployment-target-ports | |
| 6 | todo | prp-85-deployment-target-ports | STOP: owner approves CLAUDE.md/AGENTS.md diff (D-13) |
| 7 | todo | prp-85-deployment-target-ports | |

## Completion note (filled at ship)
- Date and PR:
- ADR number (D-1 and D-2 decided by the owner 2026-11-16) and the D-13 outcome:
- Provided names (for PRP-86..98 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: `NS_PLATFORM` (default `azure`).
- Follow-up issues:
- Product check (can an operator use it without editing files): no, by design; foundation only.
