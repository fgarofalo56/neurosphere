---
name: PRP-87-api-composition-seam-and-adapter-packages
status: backlog
priority: P1
order: 78
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-07, NS-08
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-51-composition-and-api-hygiene, PRP-67-hosted-environment-hardening]
wave: W25
branch: prp-87-api-composition-seam
allow_parallel: true
issues: []
---

# PRP-87: API composition seam and adapter-package scaffolding (no Azure behaviour change)

## Goal
Make the API composition ask a `Backends` provider (PRP-85) for every port instead of constructing Cosmos, Blob, Event Hubs and credential objects inline, with an Azure provider that wraps exactly today's construction, and prove that nothing changes on Azure. In the same wave, scaffold the five adapter workspace packages with every dependency the program needs (root and service `pyproject.toml`, `uv.lock`, licence register, ADR-0002 pins, the `portable` test marker), so no later multi-cloud PRP touches the lockfile. Then remove the API and core Azure leaks that sit on the seam: split the Protocol-plus-Cosmos modules, turn the SDK error translator into a registry, and let model and judge adapters take a `TokenProvider`. It is for PRP-89, 91, 93, 94 and 95, which register non-Azure implementations against this seam, and for operators of existing Azure deployments, who must see no difference. It is Opus because it rewires `builders/authz.py`, the policy store and about 40 construction sites in Tier-1 files under a strict no-change bar.

Out of scope: the worker composition (`services/workers/neurosphere_workers/runtime/factories.py`), the event-consumer and object-store ports and the five blob Protocols (PRP-88, same wave); any non-Azure implementation (PRP-89..95); contracts (PRP-86); Helm and compose (PRP-96); moving `ContainerSpec.partition_key()` out of `packages/core/neurosphere_core/stores/containers.py` (Tier-1 stores file, not granted here; stays on the ratchet list for PRP-98); telemetry, the Databricks executor and the docs-assistant model leak (PRP-95); the generalised "no static credential outside local" rule for other platforms (PRP-94); the frontend `oidc-client-ts` dependency (PRP-93 owns `pnpm-lock.yaml` in W26).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-107): "with provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer" and "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." v1.2 excluded hosting outside Azure (`docs/PRD.md:4`, `:57` "AWS/GCP hosting ... outside the initial baseline"; `PRP.md:7` "No commitment to platform hosting on AWS/GCP/on-prem."). The owner restored it on 2026-11-16 with all four targets.
- Composition is Cosmos by construction: builders build `Cosmos*` stores inline and only a test override can swap them (`services/api/neurosphere_api/runtime/builders/data.py:231-245` for the catalog; `_backend` at `:210-217`); `CompositionOverrides` documents itself as test-only (`runtime/overrides.py:1-11`). About 40 distinct `Cosmos*` constructions appear under `runtime/` (grep of `Cosmos[A-Z]\w*` names), plus `DefaultAzureCredential` in `builders/{data,blob,copilot,gateway,search,admin_platform}.py` and `azure.cosmos` in `runtime/compose.py:31`.
- Neutral modules carry Cosmos: Protocol, in-memory and Cosmos classes share `packages/core/neurosphere_core/auth/scope/policy_admin.py:33-34`, `gateway/records.py:37-39`, `lifecycle/jobs.py:24-25` and `services/api/neurosphere_api/sandbox/repository.py:17-18`; the publisher Protocol module imports `EventData` (`ingest/publisher.py:8`); neutral delete code catches `CosmosResourceNotFoundError` (`catalog/lifecycle_delete.py:20`, `ledger/lifecycle_delete.py:19`).
- The SDK error translator is Azure-only and used by neutral code: `packages/core/neurosphere_core/clients/errors.py:8-14` imports `azure.core` and `azure.eventhub` and reads `x-ms-retry-after-ms` (`:29`).
- Model and judge adapters take `AsyncTokenCredential` (`copilot/models/approved_endpoint.py:14`, `evaluation/endpoint_judge.py:25`), so a Bedrock or Vertex token cannot be passed.
- Every Azure SDK is a hard dependency of `neurosphere-core` (`packages/core/pyproject.toml:11-17`); no adapter package exists; the five `uv --frozen` Dockerfiles already copy `packages/` (`services/api/Dockerfile:18`, `services/workers/Dockerfile:18`, both `Dockerfile.dev:16`, `scripts/sandbox/Dockerfile.seed:17`), so new packages under `packages/` need no Dockerfile edit.

## Acceptance criteria
- [ ] No Azure behaviour change, proved five ways: (1) the composition snapshot (item 2), captured from the pre-refactor code and committed before any rewiring, is byte-identical after every later item; (2) every existing suite in the gates passes with no existing test file edited; (3) `services/api/tests/test_openapi_drift.py` passes with no regeneration diff; (4) the `real-stack` workflow (`.github/workflows/real-stack.yml`, triggered by `services/**` and `packages/**`) is green on the PR; (5) no file under `infra/**`, `docker-compose.yml` or any Dockerfile changes, so the Helm and Bicep goldens are untouched.
- [ ] Given `NS_PLATFORM` unset or `azure`, When the API composes, Then entry points in group `neurosphere.backends` are never loaded and every component is built by the Azure provider. Given `NS_PLATFORM=kubernetes` (local env) with no adapter registered, Then composition completes, every store-backed component reports `failed("platform_backend_missing")`, `/readyz` is 503 with reason codes only, and `create_cosmos_client` and `DefaultAzureCredential` are never called (asserted by patched factories that raise).
- [ ] No builder under `services/api/neurosphere_api/runtime/builders/` and not `runtime/compose.py` imports `azure` or names a `Cosmos*` class; they obtain stores, clients and credentials only through `ctx.backends` (checked by a test that scans those files).
- [ ] `tests/architecture` `KNOWN_LEAKS` loses every API and core file this PRP fixes (at least `runtime/compose.py`, `runtime/builders/*.py`, `ingest/publisher.py`, `sandbox/repository.py`, `gateway/dependencies.py`, `clients/errors.py`, `policy_admin.py`, `gateway/records.py`, `lifecycle/jobs.py`, both `lifecycle_delete.py`, `approved_endpoint.py`, `rest.py`, `gating.py`, `endpoint_judge.py`), and the ratchet test passes.
- [ ] `uv sync` resolves; `uv lock --check` passes; the lock diff adds only the five workspace members and the new dependencies with their transitive packages (no unrelated version moves, reported in the item notes); `python scripts/licenses_report.py --check` passes with a row for every new package; ADR-0002 carries a pin row (version range, licence, source URL, date looked up) for every new Python dependency and every tool and container image the program names; the API and worker images still build from their Dockerfiles (Alpine base: musl wheels or a build step must exist for every new native dependency).
- [ ] The `portable` marker is registered and deselected by default (`addopts`), so CI's `python` job skips container-backed conformance suites exactly as it skips `integration`.
- PRP exit: gates pass; PR open with CI green including `real-stack`, `security` and `helm`; no Tier-3 file changes except `PRPs/**` status files.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | ASSUMPTION: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | ASSUMPTION: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| 1 | What proves "no Azure change" | existing suites only; plus a composition snapshot | Both, plus OpenAPI drift and the real-stack job (criterion 1). The snapshot records, per profile: component status and reason, the qualified class name of every object a builder installs on `app.state` or publishes as a shared key, the builder order, the route table (method, path, name) and the number of calls to each patched client factory |
| 2 | Snapshot profiles | production-like env; local env | Local only: PRP-51 refuses `CompositionOverrides` outside `NS_ENV=local`, and the snapshot needs the fake Cosmos factory. Profiles: Commercial, Government, Commercial with search `fixture` and copilot recorded adapter, Commercial with every optional component off |
| 3 | Cut line if the session runs long | none; ordered | Ordered; see `## Cut line` |
| 4 | Back-compat for moved Cosmos classes | edit every importer; keep the old import path | Keep the old path through a module `__getattr__` (PEP 562) plus a `TYPE_CHECKING` import, so importers outside this PRP's files (worker `lifecycle/assembly.py`, `job_source.py`, `runtime/factories.py`, `neurosphere_core/gateway/__init__.py`, tests) keep working unchanged; the shim imports only the `*_cosmos` module, which is an adapter path |
| 5 | One image or per-platform images (owner decision D-10 in PRP-85) | one image, platform chosen by `NS_PLATFORM`; per-platform extras | ASSUMPTION (D-10 recommended default): one image set; API and workers depend on the adapter packages |
| 6 | AWS SDK flavour (owner decision D-9 in PRP-85) | `aiobotocore` (design); `boto3` with `to_thread` (PRP-62) | ASSUMPTION (D-9 recommended default): `aiobotocore`; item 1 resolves it with PRP-62's `boto3` in one lock and stops if they cannot co-resolve |
| 7 | Versions and licences | from memory; looked up | Looked up in the session from PyPI and the project pages; `scripts/licenses_report.py` decides; a `PLATFORM_GATED`, `ALIASES` or carried-forward entry needs a cited reason; any copyleft result stops the item (`psycopg` is LGPL-3.0 and is not used) |
| 8 | MinIO as the on-prem object-store reference (owner decision D-5 in PRP-85) | MinIO (AGPL-3.0 server, customer-run); SeaweedFS | Per D-5: the ADR-0002 infrastructure row records the chosen store (MinIO with the AGPL note, or SeaweedFS) and the alternative; no object-store server code is linked |
| 9 | Registration discovery | static list; entry points | Entry points (PRP-85 Clarification 5): each adapter `pyproject.toml` declares `[project.entry-points."neurosphere.backends"]` -> `neurosphere_adapters_<x>.registration:register`, a stub that registers nothing until its owner fills it |

## Context manifest

### Files to read first
- `PRPs/shipped/PRP-85-deployment-target-ports-and-adapter-boundary.md` - "Interfaces provided" (ports, `Backends`, `BackendRegistry`, `PortName`, `KNOWN_LEAKS`).
- `services/api/neurosphere_api/runtime/builders/__init__.py:1-150,240-370` - `BuildContext`, shared keys, `cosmos_client()`, `on_startup`.
- `services/api/neurosphere_api/runtime/overrides.py` - `CompositionOverrides.backends` (test seam that stays).
- `services/api/neurosphere_api/runtime/builders/data.py:200-260` - `_backend`, catalog construction (the pattern repeated about 40 times).
- `services/api/neurosphere_api/runtime/compose.py:25-120` - shared client and container step.
- `services/api/tests/runtime_data/data_helpers.py:50-110` and `services/api/tests/runtime_api/test_readiness.py` - fake Cosmos factory and status assertions to reuse in the snapshot.
- `packages/core/neurosphere_core/clients/errors.py`, `clients/factories.py:54-130` - translator and credential refusal.
- `packages/core/neurosphere_core/auth/scope/policy_admin.py`, `gateway/records.py`, `lifecycle/jobs.py`, `services/api/neurosphere_api/sandbox/repository.py` - modules to split.
- `pyproject.toml` (workspace, sources, markers), `packages/core/pyproject.toml`, `services/api/pyproject.toml`, `services/workers/pyproject.toml`, `scripts/licenses_report.py:1-60`, `docs/adr/0002-stack-pins.md` sections "Backend" and "Infrastructure and tooling".
- `PRPs/backlog/PRP-62-aws-bedrock-reference-connector.md` (or `shipped/`) - its `boto3` choice and licence notes.

### Interfaces consumed
- PRP-85: `DeploymentTarget`, `Settings.platform`, `PlatformProfile`; `neurosphere_core.platform.ports` (`TokenProvider`, `AccessToken`, `EventPublisher`, designated store Protocols); `neurosphere_core.platform.errors` (`AlreadyExistsError`, `PortUnavailableError`, `ErrorTranslator`); `neurosphere_core.platform.registry` (`PortName`, `BackendContext`, `Backends`, `BackendRegistry`); `tests/architecture/boundary.py` `KNOWN_LEAKS`.
- PRP-51 (W19, shipped): overrides refused outside local; `runtime/builders/__init__.py` order and the dedicated startup error type.
- PRP-67 (W20, shipped): `health/probes.py` reason codes and `probe_unconfigured`.
- Shipped: `ClientLifetime`, `create_cosmos_client`, `CONTAINERS`, `ensure_local_containers`, every `Cosmos*` store class.

### Interfaces provided
- `BuildContext.backends` (a `Backends` for the active platform) and `ctx.port(PortName.X)` (returns the created object or raises `ComponentUnavailableError` with the port's reason code); `ctx.cosmos_client()` and `ctx.cosmos_database()` remain for the Azure provider only.
- `neurosphere_api.runtime.backends`: `select_backends(settings, overrides) -> Backends`; `neurosphere_api.runtime.backends.azure.register(registry)` for API-local ports (copilot conversations, reports, sandbox, audit search, replay archive client).
- `neurosphere_core.platform.azure`: `register(registry)` for core ports; `AzureTokenProvider(credential)` implementing `TokenProvider`; `azure_error_translator`.
- `neurosphere_core.clients.errors`: `register_translator(translator)`; `translate_sdk_error` and `translating()` keep their signatures and consult the registry (Azure translator registered at import of the Azure provider).
- Split modules: `neurosphere_core.auth.scope.policy_admin_cosmos`, `neurosphere_core.gateway.records_cosmos`, `neurosphere_core.lifecycle.jobs_cosmos`, `neurosphere_api.sandbox.repository_cosmos`, `neurosphere_api.ingest.publisher_eventhubs`; `neurosphere_api.ingest.publisher.Publisher` is an alias of `EventPublisher`.
- Model adapters (`ApprovedEndpointAdapter`, REST helper, gating) and `EndpointJudge` accept a `TokenProvider`.
- Packages: `packages/adapters-postgres` (`neurosphere_adapters_postgres`), `packages/adapters-kafka` (`neurosphere_adapters_kafka`), `packages/adapters-objectstore` (`neurosphere_adapters_objectstore`), `packages/adapters-cloudauth` (`neurosphere_adapters_cloudauth`), `packages/adapters-models` (`neurosphere_adapters_models`), each with `registration.register`, `py.typed` and its declared dependencies (design 5.3: `asyncpg`; `aiokafka`; `aiobotocore`, `google-cloud-storage`, `google-auth`; core gains `opentelemetry-exporter-otlp-proto-http`).
- pytest marker `portable` ("requires the portable backend containers"); ADR-0002 infrastructure rows for OpenTofu, the AWS and Google Terraform providers, `kind`, CloudNativePG, Strimzi, `apache/kafka`, PostgreSQL, MinIO, Keycloak, OpenBao and the OpenTelemetry Collector contrib image.

### Patterns to match
- Builder lookup with a test override: `runtime/builders/data.py:210-217` (`_backend`).
- Status reporting and fake Cosmos: `services/api/tests/runtime_api/test_readiness.py`, `services/api/tests/runtime_data/data_helpers.py:73-110`.
- Workspace member plus dependency plumbing: PRP-62 item 1 (`pyproject.toml` member and `[tool.uv.sources]` lines, licence and ADR rows).
- AST scan over a file set: `packages/core/tests/test_import_boundaries.py:11-30`.

### Gotchas
- Capture the snapshot before touching any builder, in its own commit; regenerating it later defeats the proof. If a snapshot difference is intended (none should be), stop and ask.
- The Azure path must not call `entry_points()`; a broken third-party entry point must never affect an Azure deployment.
- Same-named test modules across the five new packages collide in one pytest session (no `__init__.py`): name them `test_adapters_<x>_skeleton.py`.
- `--strict-markers` is on (`pyproject.toml` `addopts`): register `portable` in the same commit that first uses it.
- `services/workers/pyproject.toml` is owned here although PRP-88 owns the rest of `services/workers/**` in W25: PRP-88 must not edit it; if it needs a dependency it adds a `[serial-after: PRP-87]` item.
- The images are `python:3.12-alpine`: check that `asyncpg`, `aiokafka` and any Google native dependency install under `uv sync --frozen` in the builder stage before committing the lock.
- PEP 562 shims: keep the `TYPE_CHECKING` import so pyright still types `CosmosJobStore` and friends; repo-wide pyright runs in CI.
- `translating()` is imported by neutral modules; the registry must be populated before first use, so the Azure provider registers at import of `neurosphere_core.platform.azure` and the API composition imports it first.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/runtime/backends/**
  - packages/core/neurosphere_core/platform/azure/__init__.py
  - packages/core/neurosphere_core/platform/azure/registration.py
  - packages/core/neurosphere_core/platform/azure/credentials.py
  - packages/core/neurosphere_core/platform/azure/stores.py
  - packages/core/neurosphere_core/platform/azure/errors.py
  - packages/core/neurosphere_core/clients/errors.py
  - packages/core/neurosphere_core/auth/scope/policy_admin*.py
  - packages/core/neurosphere_core/gateway/records*.py
  - packages/core/neurosphere_core/lifecycle/jobs*.py
  - packages/core/neurosphere_core/catalog/lifecycle_delete.py
  - packages/core/neurosphere_core/ledger/lifecycle_delete.py
  - packages/core/neurosphere_core/copilot/models/approved_endpoint.py
  - packages/core/neurosphere_core/copilot/models/rest.py
  - packages/core/neurosphere_core/copilot/models/gating.py
  - packages/core/neurosphere_core/evaluation/endpoint_judge.py
  - services/api/neurosphere_api/ingest/publisher*.py
  - services/api/neurosphere_api/sandbox/repository*.py
  - services/api/neurosphere_api/gateway/dependencies.py
  - services/api/neurosphere_api/health/probes.py
  - packages/adapters-*/**
  - packages/core/pyproject.toml
  - services/api/pyproject.toml
  - services/workers/pyproject.toml
  - packages/core/tests/platform_azure/**
  - services/api/tests/composition_snapshot/**
  - services/api/tests/runtime_backends/**
tier1:
  - services/api/neurosphere_api/runtime/builders/*.py
  - services/api/neurosphere_api/runtime/compose.py
  - pyproject.toml
  - uv.lock
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
tier2_appends:
  - services/api/neurosphere_api/runtime/status.py
  - tests/architecture/boundary.py
must_not_touch:
  - services/workers/neurosphere_workers/**
  - packages/core/neurosphere_core/platform/azure/eventstream.py
  - packages/core/neurosphere_core/platform/azure/objectstore.py
  - packages/core/neurosphere_core/platform/ports/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/observability/**
  - packages/core/neurosphere_core/copilot/models/endpoints.py
  - packages/core/neurosphere_core/copilot/models/protocol.py
  - packages/contracts/**
  - infra/**
  - docker-compose.yml
  - frontend/**
  - services/api/neurosphere_api/main.py
  - services/api/neurosphere_api/app.py
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (no shared file). Item 3 after 2. Items 4 and 5 after 3, serial (both edit Tier-1 builder files; one builder file per commit). Item 6 after 4. Item 7 after 5. Item 8 last.

### Item 1 - Adapter packages, dependencies, licences and pins  [P]
- Deliverable: five package skeletons (pyproject with dependencies and entry point, `__init__.py`, `registration.py` stub, `py.typed`, one uniquely named import test); root `[tool.uv.sources]` and dev-group members; API and worker dependencies on the adapters; `opentelemetry-exporter-otlp-proto-http` in core aligned with the `opentelemetry-sdk` range; `portable` marker plus `addopts` deselection; `uv lock`; `python scripts/licenses_report.py`; ADR-0002 rows (Clarification 7) including the infrastructure and tooling rows; local Alpine image build check for API and workers.
- Owned files: `packages/adapters-*/**` (new), `pyproject.toml`, `uv.lock`, `packages/core/pyproject.toml`, `services/api/pyproject.toml`, `services/workers/pyproject.toml`, `docs/licenses.md`, `docs/adr/0002-stack-pins.md`.
- Must NOT touch: Dockerfiles (they already copy `packages/`), `scripts/licenses_report.py` unless a cited `ALIASES` or `PLATFORM_GATED` line is unavoidable (then report it).
- Depends on: PRP-85 merged; Clarification 6 resolved.
- Acceptance criteria: criteria 5 and 6; lock diff reported.
- Tests: `packages/adapters-*/tests/test_adapters_*_skeleton.py`, `tests/test_licenses_report.py`, `tests/test_ci_python_shards.py`.
- Pattern references: PRP-62 item 1; `packages/core/pyproject.toml`.

### Item 2 - Composition snapshot baseline  [P]
- Deliverable: `services/api/tests/composition_snapshot/` with a recorder (Clarification 1) and goldens for the four profiles of Clarification 2, generated from the unmodified code and committed alone.
- Owned files: `services/api/tests/composition_snapshot/**` (new).
- Must NOT touch: any product file.
- Depends on: PRP-85 merged.
- Acceptance criteria: the snapshot test passes on the pre-refactor commit and fails when a builder installs a different class (proved with a stub builder in the test).
- Tests: `services/api/tests/composition_snapshot`.
- Pattern references: `services/api/tests/runtime_api/test_readiness.py`, `runtime_data/data_helpers.py:73-110`.

### Item 3 - Backends seam and the Azure provider
- Deliverable: `neurosphere_core.platform.azure` (`register`, `AzureTokenProvider`, store factories for core ports wrapping today's constructors), `neurosphere_api.runtime.backends` (`select_backends`, API-local Azure registration), `BuildContext.backends` and `ctx.port`, `compose.py` Cosmos client and container step moved behind the Azure provider; non-Azure targets get an empty registry plus entry points.
- Owned files: `packages/core/neurosphere_core/platform/azure/{__init__,registration,credentials,stores,errors}.py` (new), `services/api/neurosphere_api/runtime/backends/**` (new), `runtime/builders/__init__.py`, `runtime/compose.py`, `packages/core/tests/platform_azure/**`, `services/api/tests/runtime_backends/**` (new).
- Must NOT touch: other builder modules (items 4, 5).
- Depends on: item 2.
- Acceptance criteria: criterion 2; snapshot unchanged.
- Tests: `packages/core/tests/platform_azure`, `services/api/tests/runtime_backends`, `services/api/tests/composition_snapshot`, `services/api/tests/runtime_api`.
- Pattern references: `runtime/builders/__init__.py:240-320`.

### Item 4 - Rewire data, planes, lifecycle and authz builders
- Deliverable: `builders/{data,planes,lifecycle,authz}.py` obtain every store, client and credential through `ctx.port`; the `_backend` override lookup stays first, unchanged.
- Owned files: `services/api/neurosphere_api/runtime/builders/{data,planes,lifecycle,authz}.py`.
- Must NOT touch: route modules, `authz/dependencies.py`.
- Depends on: item 3.
- Acceptance criteria: criteria 1 and 3 for these files.
- Tests: `services/api/tests/runtime_data`, `runtime_planes`, `runtime_api`, `lifecycle_api`, `admin_identity_api`, `authz`, `tests/security/authz`, `services/api/tests/composition_snapshot`.
- Pattern references: `data.py:210-245`.

### Item 5 - Rewire the remaining builders
- Deliverable: `builders/{copilot,search,gateway,blob,admin,admin_platform,admin_connectors,admin_system,edge,mcp,analytics,write_targets,admission}.py` through `ctx.port` wherever they construct an Azure object; files that construct none are left untouched; the builder-scan test of criterion 3.
- Owned files: the builder modules named, `services/api/tests/runtime_backends/test_builders_use_ports.py` (new).
- Depends on: item 3 (serial after item 4 to keep one Tier-1 writer).
- Acceptance criteria: criteria 1 and 3.
- Tests: `services/api/tests/runtime_gateway_builder`, `write_targets_runtime`, `analytics_runtime`, `copilot_api`, `admin_platform_api`, `admin_connectors_api`, `admin_system_api`, `mcp_api`, `replay`, `ingest`, `services/api/tests/runtime_backends`, `services/api/tests/composition_snapshot`.
- Pattern references: item 4.

### Item 6 - Split mixed modules and the translator registry (cuttable unit)
- Deliverable: move Cosmos classes to the `*_cosmos` / `publisher_eventhubs` modules with PEP 562 shims; `clients/errors.py` becomes a registry with the Azure translator in `platform/azure/errors.py`; both `lifecycle_delete.py` modules catch `NotFoundError` from the translator instead of the Cosmos exception; `KNOWN_LEAKS` entries removed.
- Owned files: the split modules listed in Ownership, `clients/errors.py`, `catalog/lifecycle_delete.py`, `ledger/lifecycle_delete.py`, `tests/architecture/boundary.py` (treated as Tier-2 in W25: this PRP only deletes its own `KNOWN_LEAKS` lines and lowers `LEAK_CEILING`; PRP-88 deletes worker lines; at rebase keep both deletions and recompute the ceiling).
- Depends on: item 4.
- Acceptance criteria: criterion 4 for these files; existing tests that import old paths pass unchanged.
- Tests: `packages/core/tests/admin`, `gateway_core`, `lifecycle_cosmos`, `lifecycle`, `clients`, `services/api/tests/sandbox_api`, `ingest`, `services/workers/tests/lifecycle_worker`, `tests/architecture`.
- Pattern references: `packages/core/neurosphere_core/catalog/repo/{backend,cosmos,memory}.py` (Protocol, adapter and twin in separate modules).

### Item 7 - TokenProvider in adapters, gateway credential and probes (cuttable unit)
- Deliverable: `ApprovedEndpointAdapter`, the REST helper, gating and `EndpointJudge` take `TokenProvider`; the Azure provider passes `AzureTokenProvider`; `gateway/dependencies.py` likewise; `health/probes.py` builds probes from the provider (Azure keeps `NS_PROBE_*` names and defaults byte-for-byte).
- Owned files: `copilot/models/{approved_endpoint,rest,gating}.py`, `evaluation/endpoint_judge.py`, `services/api/neurosphere_api/gateway/dependencies.py`, `health/probes.py`.
- Depends on: item 5.
- Acceptance criteria: criterion 4 for these files; `packages/core/tests/copilot/test_adapter_contract.py` and the judge tests pass unchanged.
- Tests: `packages/core/tests/copilot`, `packages/core/tests/evaluation`, `services/api/tests/gateway_api`, `services/api/tests/health`, `services/api/tests/composition_snapshot`.
- Pattern references: `approved_endpoint.py:94-140`.

### Item 8 - Integration and close-out
- Deliverable: rebase on `main` (PRP-86 and PRP-88 may have merged; re-run the snapshot); confirm `openapi.json` has no diff; regenerate the other Tier-3 files; changelog fragment `changelog.d/PRP-87-api-composition-seam-and-adapter-packages.md`; completion note with the provided names, the lock diff summary, the final `KNOWN_LEAKS` count, any cut unit and its follow-up issue.
- Owned files: this PRP file, the changelog fragment, Tier-3 files per reference section 2.
- Depends on: items 1-7 (or 1-5 under the cut line).
- Acceptance criteria: validation gates pass; CI green including `real-stack`.

## Cut line
Items 1-5 are the minimum ship (scaffolding with every dependency, snapshot, seam, every builder through the provider); with them merged, Azure behaviour is proven unchanged and PRP-88..95 can start. Items 6 and 7 may each be descoped as a unit: their files stay on `KNOWN_LEAKS` with a follow-up issue, and what remains merges safely because nothing in items 1-5 depends on them. Never ship a half-rewired builder file. Consumers of a cut unit: if item 6 is cut, PRP-89 imports `PolicyAdminRepository` and PRP-91 imports the gateway-records, jobs and sandbox Protocols from the mixed modules (their Interfaces consumed say so); if item 7 is cut, the model adapters and judge still take `AsyncTokenCredential` and PRP-95 makes them accept a `TokenProvider` in its own owned files (PRP-95 item 2).

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
python scripts/licenses_report.py --check
uv run pytest -q services/api/tests/composition_snapshot services/api/tests/runtime_backends services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_planes services/api/tests/runtime_routes services/api/tests/runtime_gateway_builder services/api/tests/write_targets_runtime services/api/tests/analytics_runtime services/api/tests/copilot_api services/api/tests/admin_identity_api services/api/tests/admin_platform_api services/api/tests/admin_connectors_api services/api/tests/admin_system_api services/api/tests/mcp_api services/api/tests/lifecycle_api services/api/tests/sandbox_api services/api/tests/ingest services/api/tests/replay services/api/tests/gateway_api services/api/tests/health services/api/tests/authz services/api/tests/test_openapi_drift.py packages/core/tests/platform_azure packages/core/tests/admin packages/core/tests/gateway_core packages/core/tests/lifecycle_cosmos packages/core/tests/lifecycle packages/core/tests/clients packages/core/tests/copilot packages/core/tests/evaluation services/workers/tests/lifecycle_worker packages/adapters-postgres packages/adapters-kafka packages/adapters-objectstore packages/adapters-cloudauth packages/adapters-models tests/architecture tests/security/authz tests/test_licenses_report.py tests/test_ci_python_shards.py
docker build -f services/api/Dockerfile -t ns-api:prp87 .
docker build -f services/workers/Dockerfile -t ns-workers:prp87 .
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local): PRP-88 holds the W25 compose lane, so run this only when PRP-88's item 7 is not running the stack: `docker compose up -d --wait`, then `uv run pytest -q -m integration tests/integration/real_stack`.

## Migration and rollback
No data, schema or setting migration: Azure composition builds the same objects from the same settings, and `NS_PLATFORM` defaults to `azure`. Rollback is a revert of the PR; the snapshot makes a partial revert detectable. A dependency problem found after merge is fixed by a follow-up lock change from the next `uv.lock` owner, never by editing the lock in another PRP.

## Live and open gates
None run. The composition change is proven on fakes and the emulators; a hosted Azure smoke after merge belongs to the existing hosted gates (PRP-64, PRP-66). Every non-Azure target stays OPEN until PRP-98.

## NOT building
Non-Azure implementations; worker composition; the object-store and event-consumer ports' adoption; `containers.py` changes; generalised credential refusal for other platforms; per-platform images; frontend dependencies; removing the Azure SDKs from `neurosphere-core`.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows D-1, D-2, 5 and 6 are ASSUMPTIONS; rows 5, 6 and 8 are owner decisions D-10, D-9 and D-5 in PRP-85; the cut line needs plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | prp-87-api-composition-seam | |
| 2 | todo | prp-87-api-composition-seam | commit alone, before item 3 |
| 3 | todo | prp-87-api-composition-seam | |
| 4 | todo | prp-87-api-composition-seam | |
| 5 | todo | prp-87-api-composition-seam | |
| 6 | todo | prp-87-api-composition-seam | cuttable unit |
| 7 | todo | prp-87-api-composition-seam | cuttable unit |
| 8 | todo | prp-87-api-composition-seam | |

## Completion note (filled at ship)
- Date and PR:
- Provided names (for PRP-88..95 authors):
- Lock diff summary and new licence rows:
- Deviations:
- Descoped items (cut line):
- OPEN gates:
- Env vars for the operator: none (`NS_PLATFORM` is PRP-85's).
- Follow-up issues:
- Product check (can an operator use it without editing files): yes for Azure, unchanged; no other platform is usable until PRP-89..96.
