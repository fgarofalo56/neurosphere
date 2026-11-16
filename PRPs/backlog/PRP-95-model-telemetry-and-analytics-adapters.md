---
name: PRP-95-model-telemetry-and-analytics-adapters
status: backlog
priority: P2
order: 86
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-06, NS-07
depends_on: [PRP-86-contracts-platform-dimension-and-credential-kinds, PRP-87-api-composition-seam-and-adapter-packages]
wave: W26
branch: prp-95-model-telemetry-and-analytics-adapters
allow_parallel: true
issues: []
---

# PRP-95: Model endpoints, OTLP telemetry and portable analytics

## Goal
Make the copilot, the evaluation judge, the telemetry export and the analytics query path work on a deployment that is not Azure. Three model adapters (`openai_compatible`, `bedrock`, `vertex`) join the existing `ModelAdapter` Protocol with the same redaction, gating and error taxonomy as the Azure adapters; an OTLP export option sends metrics and traces to an OpenTelemetry Collector instead of the Azure Monitor exporter; a PostgreSQL `Dialect` and adapter run the analytics contract on the portable database; and the Databricks executor takes a neutral token provider instead of building an Azure credential. It is for the operator of an AWS, GCP or on-prem install (PRP-96, PRP-97) and for PRP-98, which lists the conformance matrix. It runs in W26 on top of PRP-87 (adapter packages, pinned dependencies, `TokenProvider` in place of `AsyncTokenCredential`). Azure behaviour must not change.

Out of scope: secret readers and the credential providers that mint bearer tokens, IAM database tokens and broker credentials (PRP-94); the PostgreSQL connection pool, schema and stores (PRP-89 to PRP-91); contract and capability-matrix platform rows (PRP-86); the Helm values that set these options (PRP-96); the Collector deployment in a cluster (PRP-96) and its Terraform inputs (PRP-97); any real Bedrock, Vertex or OpenAI-compatible call (paid; OPEN, PRP-64); a Pub/Sub, OpenSearch or ClickHouse adapter (OPEN, not scoped); new dependencies (PRP-87 owns `pyproject.toml` and `uv.lock`).

## Why
- Original-PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, section 5f): "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." v1.2 removed it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem") and `docs/PRD.md:57` ("AWS/GCP hosting ... outside the initial baseline"); `PRP.md:7` ("No commitment to platform hosting on AWS/GCP/on-prem"). The owner's 2026-11-16 decision overrides those lines: all four targets (Azure, AWS, GCP, on-prem Kubernetes) are in scope. PRP-85 amends the build-authority text; this PRP builds the copilot, telemetry and analytics share.
- The adapter kind list is closed: `AdapterKind = Literal["fixture", "approved_endpoint", "foundry_agent"]` and `ADAPTER_KINDS` (`packages/core/neurosphere_core/copilot/models/protocol.py:12-13`); `resolve_adapters` loops that list and gates on the Azure `foundry` matrix rows (`copilot/models/gating.py`, header docstring and `resolve_adapters`).
- The endpoint allowlist is Azure suffixes only: `GOVERNMENT_SUFFIXES`, `COMMERCIAL_SUFFIXES` and `endpoint_problem` return `endpoint_not_approved` for any other host (`copilot/models/endpoints.py:20-31,52-77`). Token scopes are Azure OAuth scopes (`endpoints.py:33-37`, `token_scope`). `AdapterConfig` carries Azure `deployment` and `api_version` fields (`endpoints.py:44-52`).
- Every adapter and the judge are typed to `AsyncTokenCredential` from `azure.core` (`approved_endpoint.py:15`, `rest.py:14`, `gating.py:22`, `evaluation/endpoint_judge.py:26`) and `bearer_headers` sends an `x-ms-client-request-id` header (`rest.py:39-45`).
- Telemetry has one exporter: `_azure_exporters` lazily imports `azure.monitor.opentelemetry.exporter` and `configure_telemetry` attaches it only with a connection string and a non-local env (`observability/telemetry.py:35-70`); API and workers read `APPLICATIONINSIGHTS_CONNECTION_STRING` (`services/api/neurosphere_api/middleware/telemetry.py:25-27`, `services/workers/neurosphere_workers/runtime/__main__.py:77-79`). An `otel-collector` compose profile already exists (`docker-compose.yml:341`).
- Analytics already has a neutral seam: `Dialect` Protocol (`analytics/base/dialect.py:43`), `SqlExecutor` (`analytics/base/enforcement.py:68`), `VENDOR_FACTORIES` (`analytics/base/registry.py:35-39`), and an equivalence suite with the fixture adapter as oracle (`tests/integration/analytics/test_equivalence.py`). The Databricks executor already takes a `TokenProvider = Callable[[], Awaitable[str]]` (`analytics/databricks/executor.py:28,91`); only `create_databricks_executor` builds `DefaultAzureCredential` (`executor.py:168-195`).

## Acceptance criteria
- [ ] Given `AdapterConfig(kind="openai_compatible"|"bedrock"|"vertex", ...)`, When `resolve_adapters` runs, Then each kind appears once in the result (enabled, or disabled with a reason code), `fixture` is still always enabled, and the existing three kinds resolve exactly as before (existing `packages/core/tests/copilot` suites pass unchanged).
- [ ] Given a non-Azure `NS_PLATFORM`, When an endpoint host is not in the operator-approved exact-host list, Then it is refused with `endpoint_not_approved` before any request; a suffix or substring match is never accepted; an embedded credential or non-https URL is refused as today.
- [ ] Given `NS_CLOUD=government`, When any of the new kinds is configured, Then it is refused (`endpoint_cloud_mismatch` or a platform reason): Government data is never routed to a non-Azure model endpoint and the Government host rule is byte-for-byte unchanged.
- [ ] Given the recorded conversation fixtures, When the shared adapter contract suite runs, Then `openai_compatible`, `bedrock` and `vertex` normalize them to the same `TextDelta`, `ToolCallRequested`, `ActionSuggestion` and exactly one `Completed` events as the existing adapters, with the model never supplying tool definitions (the tool allowlist stays server-side), abstention on an invalid response, and no prompt, response body or credential in any error or log line.
- [ ] Given HTTP 401, 403, 429 (with and without a retry hint) and 5xx from a recorded provider, Then the taxonomy errors are the existing ones (`unauthorized`, `forbidden`, `rate_limited`, `dependency_transient`) and the message carries the status code only.
- [ ] Given `NS_TELEMETRY_EXPORTER=otlp` and an OTLP endpoint, When `configure_telemetry` runs, Then spans and metrics are handed to an OTLP exporter built without network access at construction (verified with an in-process receiver or an injected exporter); given the variable unset, behaviour and the Azure Monitor path are unchanged, and no exporter is attached when `NS_ENV=local`.
- [ ] Given `NS_ANALYTICS_BACKEND=postgres`, When the analytics registry resolves it, Then the capability matrix gates it like the other vendors (disabled with a reason where no row exists), the adapter renders only fixed parameterised statements from allowlisted identifiers, and `tests/integration/analytics/test_equivalence.py` passes for it with the fixture adapter as oracle against a PostgreSQL container (marker `portable`) and against a stub executor in the default run.
- [ ] Given a caller-supplied token provider, When `create_databricks_executor` is used, Then no Azure credential is constructed; given none, the Azure default is unchanged (existing `test_databricks_executor.py` passes).
- [ ] Reference Collector configurations for AWS, GCP and on-prem exist under `infra/observability/collector/`, contain no credential or account literal, and are parsed by a test; exporter names and image tag are recorded as verified from documentation with the date.
- [ ] Provider request and response shapes used by each adapter are recorded in `docs/` with the source URL and verification date; the Vertex section says which parts were verified and which were not.
- PRP exit: touched suites, `packages/core/tests/copilot`, `tests/security`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; every live model call listed OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where the new adapters live | `neurosphere-core`; `packages/adapters-models` | `packages/adapters-models` (`neurosphere_adapters_models`, scaffolded by PRP-87); the Protocol, kinds, endpoints and gating stay in core |
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | ASSUMPTION: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | ASSUMPTION: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR; the owner confirms at the PRP-85 ADR stop point |
| 4 | How hosts are approved off Azure | suffix table per cloud; exact-host operator list | Exact-host list in operator configuration (ASSUMPTION setting `NS_COPILOT_APPROVED_HOSTS`, comma-separated hostnames, names only); a suffix table for AWS or Google would approve any tenant's host |
| 5 | Judge | Azure-only; same kinds | ASSUMPTION: the judge gets the same three kinds through the same request builders, so `endpoint_judge.py` is generalised, not duplicated |
| 6 | Bedrock call style | Converse and ConverseStream; InvokeModel | ASSUMPTION: Converse and ConverseStream (model-neutral tool-use shape); verify first from AWS documentation, alternative InvokeModelWithResponseStream |
| 7 | Vertex shape | native `generateContent`; its OpenAI-compatible endpoint | UNVERIFIED in the design; item 4 starts by reading provider documentation and records the choice. If the OpenAI-compatible endpoint is sufficient, `vertex` becomes a thin configuration of the `openai_compatible` adapter and keeps its own kind for gating and reporting |
| 8 | Postgres analytics scope | full vendor parity; the contract's fixed query plans | ASSUMPTION: the existing fixed `QueryPlan` set only; approximate quantile via `percentile_cont`; ClickHouse stays OPEN |
| 9 | OTLP selection | new `Settings` field; env read inside telemetry | ASSUMPTION: `configure_telemetry` reads `NS_TELEMETRY_EXPORTER` (azure_monitor, otlp, none) and the standard `OTEL_EXPORTER_OTLP_ENDPOINT`, so no Tier-1 builder or `main.py` edit is needed; default keeps today's behaviour |
| 10 | Dependencies | add here; PRP-87 adds | PRP-87 only. This PRP needs `aiobotocore` (Bedrock, owner decision D-9 in PRP-85), `google-auth` (Vertex tokens, provided through PRP-94's token provider), `opentelemetry-exporter-otlp-proto-http` and `asyncpg` (analytics container tests only; core code never imports it); all four are on the design's list. If PRP-87 did not pin one, stop and report (no edit to `pyproject.toml`) |
| 11 | Cut order if the session overruns (owner decision D-12 in PRP-85) | any; ordered | Per D-12 (recommended: the Vertex adapter, item 4, is cut first and recorded OPEN). What remains merges safely: `vertex` stays out of `ADAPTER_KINDS` and resolves nowhere; PRP-96 renders only settings that exist and PRP-98 records `vertex` as OPEN |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/copilot/models/protocol.py` - `ModelAdapter`, `AdapterKind`, `ADAPTER_KINDS`, `AdapterDescriptor`.
- `packages/core/neurosphere_core/copilot/models/endpoints.py` - `AdapterConfig`, `endpoint_problem`, `require_endpoint`, `token_scope`.
- `packages/core/neurosphere_core/copilot/models/gating.py` - `resolve_adapters`, `create_adapter`, `AdapterAvailability`.
- `packages/core/neurosphere_core/copilot/models/approved_endpoint.py`, `rest.py`, `normalize.py`, `redaction.py` - body builder, SSE framing, error mapping, normalisation, redaction to reuse.
- `packages/core/neurosphere_core/evaluation/endpoint_judge.py` and `evaluation/judge.py` - `Judge`, `JudgeRequest`, strict verdict parsing.
- `packages/core/tests/copilot/test_adapter_contract.py` and `copilot/models/recorded.py` - the shared contract suite, `HttpRecording`, `replay_transport`.
- `packages/core/neurosphere_core/observability/telemetry.py` - `configure_telemetry`, `_azure_exporters`.
- `packages/core/neurosphere_core/analytics/base/{dialect,registry,enforcement,sql_adapter}.py` and `analytics/databricks/{dialect,adapter,executor}.py` - the pattern for a vendor adapter.
- `tests/integration/analytics/{test_equivalence,support,test_profile_gating}.py`.
- `services/api/neurosphere_api/runtime/builders/copilot.py:92-195` and `builders/analytics.py` - how modes and backends are named today (read only; Tier 1).

### Interfaces consumed
- PRP-87: adapter packages with pinned dependencies (`neurosphere_adapters_models` skeleton with its `registration:register` entry-point stub), `TokenProvider` replacing `AsyncTokenCredential` in `rest.py`, `approved_endpoint.py`, `gating.py` and `endpoint_judge.py` (PRP-87 item 7; if PRP-87 cut it, item 2 here makes those files accept a `TokenProvider`, as they are this PRP's owned files in W26), the `portable` pytest marker, and the backend provider through which the copilot and analytics builders ask for ports.
- PRP-94 (W27, later wave): credential and token providers (bearer token for Vertex and OpenAI-compatible, AWS credentials for Bedrock). This PRP's tests inject a static `TokenProvider`; PRP-94 item 6 wires the real providers through the PRP-87/PRP-88 seams.
- PRP-89 (same wave, not consumed): PostgreSQL pool and TLS settings. The analytics executor takes an injected pool factory; container tests build their own `asyncpg` pool from compose; PRP-94 item 6 wires PRP-89's pool into it.
- PRP-86 (W25): the capability matrix `platform` dimension, `analytics_backend` value `postgres` and the AWS/GCP rows; the new kinds and `postgres` resolve through those rows or are disabled with a reason.
- PRP-85: `NS_PLATFORM` and `DeploymentTarget` (`neurosphere_core.cloud`), the neutral port definitions (`TokenProvider`, `TelemetryExporterFactory`), and the registry of platform settings (the `NS_COPILOT_*`, `NS_TELEMETRY_EXPORTER` and `NS_ANALYTICS_BACKEND=postgres` rows are this PRP's).

### Interfaces provided
- Adapter kinds `openai_compatible`, `bedrock`, `vertex` in `ADAPTER_KINDS`; classes `OpenAICompatibleAdapter`, `BedrockAdapter`, `VertexAdapter` and judge equivalents in `neurosphere_adapters_models`; `approved_hosts_problem(...)` beside `endpoint_problem`.
- Setting names: `NS_COPILOT_APPROVED_HOSTS`, `NS_TELEMETRY_EXPORTER`, standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` (header values never in files); backend value `postgres` for `NS_ANALYTICS_BACKEND`.
- `neurosphere_core.analytics.postgres`: `PostgresDialect`, `PostgresStatementExecutor`, `create_adapter` (registered in `VENDOR_FACTORIES`).
- `create_databricks_executor(..., token_provider=...)`.
- `infra/observability/collector/{aws,gcp,onprem}.yaml` for PRP-96 and PRP-97 to mount; `docs/reference/model-providers.md` (new) for the verified request shapes.

### Patterns to match
- Adapter plus injectable `httpx` transport and recorded replay: `copilot/models/approved_endpoint.py`, `recorded.py` (`replay_transport`).
- One contract suite run against every adapter: `packages/core/tests/copilot/test_adapter_contract.py:1-50`.
- Vendor analytics adapter with a dialect and a stub endpoint: `analytics/databricks/{dialect,adapter}.py`, `analytics/base/stub.py`.
- Equivalence against an oracle: `tests/integration/analytics/test_equivalence.py`.
- Credential refusal: `copilot.py:100-110` (`CopilotCredentialConfigError`), same idea for any new `NS_COPILOT_*` setting containing a key marker.

### Gotchas
- `gating.py` consults only Azure `foundry` matrix rows. The new kinds must not be satisfied by an Azure row, and must not skip the matrix silently: they resolve through the PRP-86 `platform` rows or are disabled with a reason.
- `AdapterKind` is also the builder mode: `CopilotMode` in `services/api/neurosphere_api/runtime/builders/copilot.py:92` and `adapter_config()` (`:143-165`) require `deployment`, `region` and `model_feature`, which are Azure concepts. That file is a Tier-1 builder held by PRP-87 and PRP-78; item 7 is `[serial-after: PRP-87]` and only adds the three modes and optional fields. Report if PRP-87 already moved this behind the backend provider.
- `bearer_headers` sends `x-ms-client-request-id`; do not send Azure-specific headers to other providers.
- Bedrock is not an `httpx` transport: it uses SigV4 through `aiobotocore`. How to replay a recorded event stream is UNVERIFIED (botocore stubbing of streaming bodies); decide in item 3 and say so in the report. Do not open a socket in any default test.
- Redaction runs on the request before it leaves the boundary for every adapter; a new adapter that builds its body from the unredacted request fails the redaction suite.
- Testing on `NS_ENV=local` must not require any provider credential.
- `neurosphere_core.analytics.postgres` must not import `asyncpg` (a PRP-85 `FORBIDDEN_ROOTS` entry outside adapter paths): the executor works on the injected pool.
- Test package name clash: new test directories get unique names (`copilot_models_portable`, `analytics_postgres`, `observability_otlp`).

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-models/**
  - packages/core/neurosphere_core/copilot/models/endpoints.py
  - packages/core/neurosphere_core/copilot/models/protocol.py
  - packages/core/neurosphere_core/copilot/models/gating.py
  - packages/core/neurosphere_core/copilot/models/rest.py
  - packages/core/neurosphere_core/copilot/models/approved_endpoint.py
  - packages/core/neurosphere_core/evaluation/endpoint_judge.py
  - packages/core/neurosphere_core/observability/telemetry.py
  - packages/core/neurosphere_core/analytics/postgres/**
  - packages/core/neurosphere_core/analytics/databricks/executor.py
  - packages/core/neurosphere_core/analytics/base/registry.py
  - packages/core/tests/copilot_models_portable/**
  - packages/core/tests/analytics_postgres/**
  - packages/core/tests/observability_otlp/**
  - tests/conformance/model_adapter/**
  - tests/conformance/telemetry/**
  - tests/integration/analytics/**
  - infra/observability/collector/**
  - docs/reference/model-providers.md
tier1: []
tier2_appends:
  - tests/architecture/boundary.py
must_not_touch:
  - pyproject.toml
  - uv.lock
  - packages/adapters-models/pyproject.toml
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
  - packages/contracts/**
  - packages/core/neurosphere_core/capabilities/**
  - services/api/neurosphere_api/runtime/builders/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - infra/helm/**
  - docker-compose.yml
```

## Implementation blueprint

### Item 1 - Kinds, approved hosts and gating
- Deliverable: add `openai_compatible`, `bedrock`, `vertex` to `AdapterKind` and `ADAPTER_KINDS`; make `AdapterConfig` accept the fields they need without weakening `extra="forbid"` (still no key or secret field); add the exact-host approval (`NS_COPILOT_APPROVED_HOSTS`) used only when `NS_PLATFORM` is not azure, keeping the Azure suffix rules and the Government rule unchanged; extend `resolve_adapters` and `create_adapter` so the new kinds are gated and constructed through a registry that `packages/adapters-models` fills (core must not import the adapters package).
- Owned files: `copilot/models/{protocol,endpoints,gating}.py`; tests in `packages/core/tests/copilot_models_portable/`.
- Must NOT touch: capability data, builders, `pyproject.toml`.
- Depends on: none. Verify first: read PRP-85's `TokenProvider`, how PRP-87 item 7 threaded it, and PRP-86's capability rows; record what the gating needs.
- Acceptance criteria: criteria 1 to 3.
- Tests: `packages/core/tests/copilot_models_portable/test_kinds_and_hosts.py` (exact host, suffix trap, credential in URL, Government refusal, existing kinds unchanged).
- Pattern references: `endpoints.py:52-77`, `gating.py` `resolve_adapters`.

### Item 2 - OpenAI-compatible adapter and judge
- Deliverable: `OpenAICompatibleAdapter` (chat completions with streaming and tool calls, bearer token from the token provider, no Azure headers) reusing `build_body`, SSE framing, normalisation and redaction from core; generalise `endpoint_judge.py` to accept it; add it to the shared contract suite.
- Owned files: `packages/adapters-models/neurosphere_adapters_models/openai_compatible.py` (new), `copilot/models/rest.py` and `approved_endpoint.py` (only to expose shared helpers), `evaluation/endpoint_judge.py`; `tests/conformance/model_adapter/{checks,test_openai_compatible}.py`.
- Must NOT touch: tool allowlist code (`copilot/` outside `models/`).
- Depends on: item 1.
- Acceptance criteria: criteria 4 and 5 for this kind; a deliberately broken adapter (sends tool definitions from the model side, or skips redaction) fails the checks.
- Tests: the contract suite parameterised over all kinds; recorded fixtures under `packages/adapters-models/tests/fixtures/`.
- Pattern references: `test_adapter_contract.py`, `recorded.py`.

### Item 3 - Bedrock adapter  [P]
- Deliverable: verify first from AWS documentation (Converse and ConverseStream request, tool-use blocks, stream events, error codes, throttling), record the shapes with URL and date in `docs/reference/model-providers.md`, then implement `BedrockAdapter` and its judge path; error mapping to the taxonomy; credentials only through the provider port.
- Owned files: `packages/adapters-models/neurosphere_adapters_models/bedrock.py` (new), its fixtures and tests, the Bedrock section of the doc.
- Depends on: item 1. Parallel with items 4 to 6: separate files.
- Acceptance criteria: criteria 4 and 5 for this kind; no real call.
- Tests: `tests/conformance/model_adapter/test_bedrock.py` on a recorded or stubbed transport.
- Pattern references: item 2.

### Item 4 - Vertex adapter  [P]
- Deliverable: verify first (native request and streaming shape, tool calls, auth scope, whether the OpenAI-compatible endpoint is sufficient), record the decision and the unverified remainder, implement `VertexAdapter`, bearer token from the provider port.
- Owned files: `packages/adapters-models/neurosphere_adapters_models/vertex.py` (new), fixtures, tests, the Vertex section of the doc.
- Depends on: item 1.
- Acceptance criteria: criteria 4 and 5 for this kind; the doc states what was not verified.
- Tests: `tests/conformance/model_adapter/test_vertex.py`.

### Item 5 - OTLP export and Collector references  [P]
- Deliverable: `configure_telemetry` selects exporters from `NS_TELEMETRY_EXPORTER` (default keeps today's Azure Monitor behaviour), builds OTLP HTTP exporters for metrics and traces without network access at construction, refuses a credential-looking value in non-header config; reference Collector configs per target (verify exporter component names and the pinned contrib image from the Collector documentation; use the tag already pinned at `docker-compose.yml:343` as the baseline).
- Owned files: `observability/telemetry.py`, `infra/observability/collector/**`, `tests/conformance/telemetry/**`, `packages/core/tests/observability_otlp/**`.
- Must NOT touch: `services/api/neurosphere_api/main.py`, `middleware/telemetry.py` (callers keep passing the Azure string).
- Depends on: none beyond PRP-87's pinned exporter.
- Acceptance criteria: criterion 6 and 9.
- Tests: in-process OTLP receiver or injected exporter; `test_no_egress.py` still green.

### Item 6 - PostgreSQL analytics dialect and adapter  [P]
- Deliverable: `PostgresDialect` (placeholders, identifier quoting, `LIMIT`, `percentile_cont`, `date_trunc` buckets, UTC timestamp parameter), `PostgresStatementExecutor` (read-only transaction, `statement_timeout`, row and cost accounting, cancellation aborts the statement), `create_adapter`, registry entry, migrations for the analytics table through the existing `AnalyticsSchemaStore` Protocol as DDL text in the adapter, applied by the test (PRP-89's runner is same-wave and not consumed), matrix gating; the pool is injected (tests pass a compose-built `asyncpg` pool; PRP-94 wires PRP-89's).
- Owned files: `analytics/postgres/**` (new), `analytics/base/registry.py` (one line), `packages/core/tests/analytics_postgres/**`, `tests/integration/analytics/**`.
- Depends on: item 1 not needed; consumes PRP-87 and PRP-86 rows.
- Acceptance criteria: criterion 7.
- Tests: stub-executor run in the default suite; PostgreSQL container run with marker `portable` using a compose fragment owned by PRP-89 (`infra/compose/portable/postgres.yml`; do not edit it, skip with a clear reason when absent).
- Pattern references: `analytics/databricks/*`, `test_equivalence.py`.

### Item 7 - Neutral Databricks auth and builder registration  [serial-after: PRP-87]
- Deliverable: `create_databricks_executor` and `open_databricks_executor` accept `token_provider`; the Azure default stays. If the copilot and analytics builders still hard-code mode and backend literals (`CopilotMode`, `Backend`), add the new values additively; that edit is in Tier-1 files this PRP does not own, so do it only after PRP-87 has merged and PRP-78 is not in flight, and list the exact lines in the completion note. If it cannot be done without ownership, leave it and report.
- Owned files: `analytics/databricks/executor.py`; builder lines only under the serial-after rule.
- Acceptance criteria: criterion 8; `NS_COPILOT_MODE=bedrock` boots in a test with a prebuilt adapter override (never a live call).
- Tests: `packages/core/tests/analytics/test_databricks_executor.py` unchanged plus a new neutral-provider case in `packages/core/tests/analytics_postgres/`.

### Item 8 - Integration and close-out
- Deliverable: documentation of the new settings for the operator (`docs/reference/model-providers.md`, an `NS_*` list for the completion note because `.env.example` is agent-blocked, matching this PRP's rows in PRP-85's registry of platform settings), removal of this PRP's fixed entries (telemetry, Databricks executor) from `KNOWN_LEAKS` in `tests/architecture/boundary.py` (deletion-only Tier-2), `PRPs/reference` untouched, Tier-3 regeneration, changelog fragment `changelog.d/PRP-95-model-telemetry-and-analytics-adapters.md`, completion note.
- Owned files: the doc, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green; live items written OPEN.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/copilot packages/core/tests/copilot_models_portable packages/core/tests/analytics packages/core/tests/analytics_postgres packages/core/tests/observability packages/core/tests/observability_otlp packages/core/tests/evaluation tests/conformance/model_adapter tests/conformance/telemetry tests/integration/analytics tests/security
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Portable check (local, opt-in, not CI default): bring up the PostgreSQL compose fragment and run the analytics equivalence suite with `-m portable`.

## Migration and rollback
No data migration. Every new kind, the OTLP exporter and the `postgres` analytics backend are opt-in by setting; defaults are unchanged (`NS_COPILOT_MODE` default `disabled`, exporter default Azure Monitor, analytics default `none`). Rollback is unsetting the variables or reverting the PR; the Azure path never loads the new package.

## Live and open gates
OPEN, operator-only under `NS_LIVE_APPROVED=1` and handed to PRP-64: one real Bedrock turn, one real Vertex turn, one OpenAI-compatible endpoint turn, an OTLP export into a real Collector backend, the PostgreSQL analytics run on managed RDS or Cloud SQL, Databricks on AWS or GCP with a neutral token provider. All model calls are paid. PRP-98 records them in the conformance matrix as "recorded transport only" until run.

## NOT building
Secret readers or token minting (PRP-94); Pub/Sub, OpenSearch, ClickHouse adapters; a Google-native identity provider; Bedrock or Vertex agent runtimes (only the plain model call); changes to the copilot tool allowlist, abstention or redaction rules; any claim that a non-Azure model endpoint is authorised for any workload.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows D-1, D-2, 4, 5, 6, 7, 8, 9 are ASSUMPTIONS for plan approval; row 11 is owner decision D-12 in PRP-85)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | serial-after PRP-87 |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
