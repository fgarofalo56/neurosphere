---
name: prp-05-api-worker-runtime-and-self-observability
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 0/1
ns: NS-08
depends_on: PRP-01, PRP-03
wave: W3
absorbs: new
---

# PRP-05: API and worker runtime, shared core, self-observability

## Goal

Ship the backend skeleton every Python PRP builds on: the shared library `packages/core` (decision D11: workers must not import the API app), a FastAPI app factory with correlation IDs, typed error handlers and a committed OpenAPI export, a worker runtime with graceful shutdown, checkpoint interface and backoff, OpenTelemetry plus redacting structured logs, `/healthz` and `/readyz` with dependency probes, thin async Cosmos and Event Hubs client factories, and the `app` compose profile that runs api and workers against the PRP-03 emulators. It is for the authors of PRP-06 through PRP-12 who need one agreed place for scope types, errors, cloud endpoints and clients. It lands in W3 because it needs the PRP-01 contracts and the PRP-03 compose stack. Authentication and authorization enforcement are deliberately absent (PRP-06): the `IdentityScope` type exists here with no derivation.

> NS-08: "Entra ID with cloud-specific authorities/audiences, managed identities where supported and vault references elsewhere."

> NS-08: "Private networking/default-deny egress, approved endpoints, threat modeling, prompt-injection isolation, supply-chain scanning, secret rotation and incident response are foundational, not final-phase additions."

> PRD section 3 (planning targets, to be measured rather than guaranteed): "regional core API availability 99.9%; dashboard p95 <=2s on bounded 90-day aggregates; catalog p95 <=500ms on indexed scoped queries; map freshness p95 <=10s after normalized ingestion."

The SLO figures in this PRP are those planning targets, quoted as targets. Nothing here measures or guarantees them.

## Acceptance criteria

- [ ] Item 1: The Government cloud profile resolves login to `login.microsoftonline.us`, Cosmos to `*.documents.azure.us`, Event Hubs to `*.servicebus.usgovcloudapi.net`, Search to `*.search.azure.us`, and management to `management.usgovcloudapi.net`; the Commercial profile resolves the `.com`/`.windows.net` equivalents; unit tests cover both and a Government profile containing a Commercial suffix fails.
- [ ] Item 2: Every response, including 4xx and 5xx, carries `x-correlation-id` (echoed if supplied and valid, generated otherwise); error responses use the PRP-01 taxonomy body; the OpenAPI JSON is committed and a CI diff check fails on drift.
- [ ] Item 3: Given a worker with an in-flight batch, when SIGTERM arrives, then the batch drains, the checkpoint is committed only after the batch completes, and the process exits 0 (test).
- [ ] Item 4: A log line containing a fake bearer token, SAS signature and connection-string key is redacted in test; SLO metric names exist and are emitted in a unit test using the in-memory exporter.
- [ ] Item 5: `/healthz` returns 200 while the process is up; `/readyz` returns 503 with a per-dependency reason when the Cosmos emulator is stopped (integration test); `docs/ops/slo.md` states the PRD section 3 targets as targets.
- [ ] Item 6: Integration test round-trips one document through the Cosmos emulator and one event through the Event Hubs emulator using the client factories; both local-key and managed-identity code paths are constructed (identity path unit-tested with a fake credential).
- [ ] Item 7: `docker compose --profile app up -d --wait` reaches healthy for api and workers.
- [ ] PRP exit: `verify-gates.ps1 -Mode full` green; `pytest -m integration` selector passes against compose; ruff and pyright clean; `python scripts/validate_planning.py` shows no failure attributable to this file.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| C1 | Where shared code lives | `packages/core`; duplicate per service | **`packages/core` (decision D11)**, import name `neurosphere_core`. `services/workers` depends on core, never on `neurosphere_api`. |
| C2 | Model and review | opus + review; sonnet + none | **sonnet, review none** (master table; decision D6). Authorization risk is in PRP-06. |
| C3 | Live gates | live Azure smoke; emulator only | **Emulator only.** Decision D7 allows per-PRP live approval, but nothing here needs paid resources. Managed-identity paths are unit-tested with a fake credential and recorded OPEN for live. |
| C4 | Emulator limits | ignore; document | Cosmos vNext emulator has no auth enforcement, no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes; Event Hubs emulator is SAS only, one namespace and ten hubs, no persistence, needs Azurite. Tests must not assert RU, index or Entra behavior. Deltas are recorded for G12. |
| C5 | Cloud profile selection | build-time; env `NS_CLOUD` | **Env `NS_CLOUD` = `commercial` or `government`** read once into a frozen settings object (pydantic-settings 2.15). Unknown value fails startup. No default that silently picks Commercial in a non-local env. |
| C6 | Local vs managed identity | env switch; separate classes | **One factory, switch by `NS_ENV`**: `local` may use emulator keys from the compose environment; anything else requires `DefaultAzureCredential`/managed identity and refuses key strings. |
| C7 | Correlation ID format | UUID4; W3C trace-id; any string | **Accept caller value matching `^[A-Za-z0-9._-]{8,64}$`, else generate a UUID4.** Also attached to the OTel span as `ns.correlation_id`. |
| C8 | OpenAPI drift check | manual; CI diff | **Committed `services/api/openapi.json` plus a pytest that regenerates and compares.** The file path is owned by item 2. |
| C9 | Worker checkpoint interface | Event Hubs specific; abstract | **Abstract `CheckpointStore` protocol** in `neurosphere_workers.runtime`; the blob implementation arrives with PRP-07. Rule: advance only after durable accept or quarantine. |
| C10 | Probe behavior on dependency timeout | 200 with warnings; 503 | **503 from `/readyz`, 200 from `/healthz`.** Fail closed. Probe timeout default 2 s, configurable. |
| C11 | SLO documentation form | prose; table | **Table with target, measurement method and owner PRP**, each phrased "target, to be measured". Grafana/Workbook JSON in `infra/observability/` visualizes metric names only. |
| C12 | Dockerfile scope | production images; dev only | **Dev Dockerfiles only** (`Dockerfile.dev`). Production multi-stage non-root images are PRP-13. |
| C13 | Exceptions to error taxonomy | add new names; reuse | **Use the PRP-01 names only**: unauthorized, forbidden, capability_unavailable, stale_version, rate_limited, invalid_schema, dependency_transient. A new name needs a contract change in PRP-01 first. |

## Context manifest

### Files that matter

- `PRP.md` sections 1-3 (binding preamble).
- `docs/PRD.md` NS-08 and section 3 (targets quoted above); `docs/ARCHITECTURE.md` diagram 1 (API authorization and policy sits between APIM and modules) and section 6 (query safety, search and push enforce the same policy).
- `docs/adr/0002-stack-pins.md` Backend table: FastAPI 0.143, Starlette 1.7, Pydantic 2.14, pydantic-settings 2.15, uvicorn 0.54, azure-cosmos 4.17 (hierarchical partition keys need >=4.6), azure-eventhub 5.15, azure-eventhub-checkpointstoreblob-aio 1.2, azure-identity 1.26, azure-monitor-opentelemetry 1.8, opentelemetry-sdk 1.45 (contrib `0.66b` aligned), httpx 0.28 / respx 0.23, pytest 9.1 / pytest-asyncio 1.4.
- `docs/RESEARCH-AND-GATES.md` (G12 emulator parity; G07 SLO/DR evidence is PRP-21; Event Hubs geo-DR caveat).
- `docs/DECISIONS-LOG.md` D6, D7, D8 (Compose with emulators), D11 (shared core).
- `pyproject.toml` (ruff line 100, py312, S rules; pyright standard; markers `live` and `integration`; uv workspace members enabled by PRP-00), `docker-compose.yml` (cosmos, azurite, eventhubs services), `infra/compose/eventhubs.config.json` (emulator hub definitions), `.claude/hooks/config.ps1`, `.env.example` (names only), `scripts/validate_planning.py`.
- Created by PRP-00: `packages/core/pyproject.toml`, `packages/core/neurosphere_core/__init__.py`, `services/api/pyproject.toml`, `services/api/neurosphere_api/__init__.py`, `services/workers/pyproject.toml`, `services/workers/neurosphere_workers/__init__.py`.
- Created by PRP-01: `packages/contracts/python/` (generated Pydantic models: error taxonomy, `IdentityScope`, `TelemetryEvent`).
- Created by PRP-03: compose profiles and `infra/compose/` helper configs, egress-blocked test network, `Makefile` dev targets.
- Consumed later: PRP-06 fills scope derivation and `require(permission)`; PRP-07 uses the clients and `CheckpointStore`; PRP-08 uses cloud profiles; PRP-13 replaces dev Dockerfiles.

### Patterns to match

No product code exists yet, so these are rules.

- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; settings via pydantic-settings; no mutable module globals.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`, registered through one router registry in the app factory.
- Async Azure SDK clients created only from `packages/core/neurosphere_core/clients`; service code never constructs an SDK client directly.
- Raise exceptions from `neurosphere_core.errors`; one handler maps each to the contract HTTP status and body; never `HTTPException` with ad hoc bodies.
- Tests beside packages (`packages/core/tests/`, `services/api/tests/`, `services/workers/tests/`) plus cross-package suites in `tests/`; `pytest.mark.integration` for emulator tests, `pytest.mark.live` for cloud tests.
- Logging: structured JSON, one logger factory in `neurosphere_core.observability`, redaction filter installed by default.

### Conventions

- ruff config in root pyproject (line 100, py312, S rules on) and pyright standard; conventional commits (`feat(core): ...`); owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1` (none in this PRP).
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

- `packages/core` must not import `neurosphere_api` or `neurosphere_workers` (import-linter or a pytest AST scan enforces it); workers import core only.
- The `IdentityScope` type created here has no derivation logic and no default constructor from request input; a model that can be built from a request body would let callers supply scope. Make construction internal (`from_verified_claims` arrives in PRP-06).
- Government endpoint suffix table (Item 1) is a profile fact; never concatenate hosts from user input. The cloud profile is read at startup from `NS_CLOUD` and not request-overridable.
- Hierarchical partition keys need azure-cosmos >=4.6 and new containers only (RESEARCH-AND-GATES, retrieved 2026-10-08); the client factory only creates clients, container design is PRP-10.
- Event Hubs checkpointing uses the blob checkpoint store (azure-eventhub-checkpointstoreblob-aio 1.2, last release 2025-02); PRP-05 defines only the protocol.
- Compose service healthchecks must not call external hosts; the egress-blocked network from PRP-03 applies.
- `/readyz` must not leak connection strings or keys in its failure body; reasons are enumerated codes.
- The emulator Cosmos has no auth enforcement: a passing local test says nothing about RBAC. Do not write tests that imply it does.
- OTel exporters must be disabled by default in `NS_ENV=local` to avoid outbound calls; exporting to Azure Monitor requires explicit configuration.
- uvicorn workers handle SIGTERM themselves; the worker runtime has its own signal handling and must not rely on uvicorn.

### External references

- FastAPI lifespan and exception handlers: https://fastapi.tiangolo.com/advanced/events/ (FastAPI 0.143, ADR-0002, observed 2026-10-08).
- Cosmos DB Python SDK and hierarchical partition keys: https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys (updated 2026-04-27; Python >=4.6).
- Cosmos DB vNext Linux emulator: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026, limits in C4).
- Event Hubs emulator: https://learn.microsoft.com/azure/event-hubs/overview-emulator (2026-08-26; SAS only, GA status unverified).
- Event Hubs geo-DR caveat: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06; metadata only).
- Azurite: https://learn.microsoft.com/azure/storage/common/storage-use-azurite (Table API preview).
- Azure Government endpoints and identity: https://learn.microsoft.com/azure/azure-government/compare-azure-government-global-azure and https://learn.microsoft.com/entra/identity-platform/authentication-national-cloud (observed 2026-10-08).
- Azure Government audit scope including Resource Graph: https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope (updated 2026-09-21).
- OpenTelemetry Python: https://opentelemetry.io/docs/languages/python/ (opentelemetry-sdk 1.45, contrib 0.66b aligned, ADR-0002).

## Implementation blueprint

Shared must-not-touch for every item (the "shared list"): root `pyproject.toml`, `docs/RESEARCH-AND-GATES.md`, `packages/contracts/**` (PRP-01), `frontend/**`, `connectors/**`, `infra/bicep/**`, `.github/workflows/**`; `docker-compose.yml` except where item 7 owns it. Dependency additions to member `pyproject.toml` files and `uv.lock` are made in one serialized integrator commit before lanes start.

### Item 1 — core-primitives  [P]
- Deliverable: `IdentityScope` type (construction restricted, no derivation), error taxonomy exception classes with HTTP status and retryable flag mapped from the PRP-01 contract, pagination and budget models (page size, cursor, node/edge/time budgets), and a frozen `CloudProfile` for Commercial and Government with the endpoint suffix table.
- Owned files (may edit): `packages/core/neurosphere_core/errors/`, `packages/core/neurosphere_core/scope/`, `packages/core/neurosphere_core/paging/`, `packages/core/neurosphere_core/cloud/`.
- Must NOT touch: `packages/core/neurosphere_core/observability/` (item 4), `packages/core/neurosphere_core/clients/` (item 6), `packages/core/neurosphere_core/auth/` (PRP-06), `packages/core/neurosphere_core/capabilities/` (PRP-02), `services/**`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - Government profile resolves login `login.microsoftonline.us`, Cosmos `*.documents.azure.us`, Event Hubs `*.servicebus.usgovcloudapi.net`, Search `*.search.azure.us`, management `management.usgovcloudapi.net`; Commercial resolves the public-cloud hosts; table-driven tests.
  - A validator rejects any Government profile host that is not in the Government suffix set.
  - Every exception has `http_status` and `retryable` equal to the contract values (cross-checked against `packages/contracts/python`).
  - `IdentityScope` cannot be constructed from an arbitrary dict via the public API (test).
- Pattern references: Pydantic v2 `extra="forbid"`; error taxonomy rule.
- Tests to write: `packages/core/tests/test_cloud_profile.py`, `packages/core/tests/test_errors.py`, `packages/core/tests/test_scope_type.py`, `packages/core/tests/test_paging.py`.

### Item 2 — fastapi-app-factory
- Deliverable: `create_app(settings)` factory, router registry, correlation ID middleware, exception handlers for the taxonomy, request size limit middleware, OpenAPI export script and committed `openapi.json`.
- Owned files (may edit): `services/api/neurosphere_api/main.py`, `services/api/neurosphere_api/app.py`, `services/api/neurosphere_api/middleware/`, `services/api/openapi.json`, `services/api/tests/` (item 2 files only: `test_app.py`, `test_middleware.py`, `test_openapi_drift.py`).
- Must NOT touch: `services/api/neurosphere_api/health/` (item 5), `services/api/neurosphere_api/authz/` and `audit/` (PRP-06), `services/api/neurosphere_api/ingest/` (PRP-07), `packages/core/**`, `services/workers/**`; plus the shared list.
- Depends on: item 1.
- Acceptance criteria:
  - Every response, including 404, 422, 500, carries `x-correlation-id`; supplied valid values are echoed, invalid ones replaced.
  - Unhandled exceptions return the taxonomy body without stack traces or internal hostnames.
  - `openapi.json` regenerates identically; the drift test fails when a route changes without regeneration.
  - Router registry rejects two routers claiming the same prefix.
- Pattern references: FastAPI router-per-module; error handler rule; C7, C8.
- Tests to write: `services/api/tests/test_app.py`, `services/api/tests/test_middleware.py`, `services/api/tests/test_openapi_drift.py`.

### Item 3 — worker-runtime  [P]
- Deliverable: worker base class and runner: signal handling, graceful drain, `CheckpointStore` protocol, exponential backoff with jitter and retry budget, lightweight health HTTP endpoint, structured lifecycle logs.
- Owned files (may edit): `services/workers/neurosphere_workers/runtime/`, `services/workers/tests/runtime/`.
- Must NOT touch: other `services/workers/neurosphere_workers/*` packages (ingestion, quarantine, archive, projections: PRP-07 and later), `packages/core/**`, `services/api/**`; plus the shared list.
- Depends on: item 1.
- Acceptance criteria:
  - SIGTERM drains the in-flight batch, commits the checkpoint only after completion, exits 0; SIGKILL simulation leaves the checkpoint at the prior value (test).
  - Backoff respects the retry budget and surfaces `dependency_transient` after exhaustion; no unbounded retry.
  - The health endpoint reports `draining` during shutdown.
- Pattern references: C9; checkpoint-after-durable-accept rule.
- Tests to write: `services/workers/tests/runtime/test_shutdown.py`, `services/workers/tests/runtime/test_backoff.py`, `services/workers/tests/runtime/test_checkpoint_protocol.py`.

### Item 4 — otel-and-logging  [P]
- Deliverable: OTel tracer and meter setup (exporters off by default locally, Azure Monitor exporter optional), JSON log formatter, redaction filter (bearer tokens, SAS signatures, connection-string keys, `Authorization` headers, fields named `prompt`/`response`/`password`), SLO metric name constants.
- Owned files (may edit): `packages/core/neurosphere_core/observability/`, `packages/core/tests/observability/`.
- Must NOT touch: `packages/core/neurosphere_core/errors|scope|paging|cloud|clients/` (other items), `services/**`, `infra/observability/` (item 5); plus the shared list.
- Depends on: item 1.
- Acceptance criteria:
  - A log record containing a fake bearer token, a SAS `sig=` value and an `AccountKey=` value is emitted with each replaced by a redaction marker; the original substrings never appear in captured output.
  - SLO metric names (`ns.api.request.duration`, `ns.api.request.errors`, `ns.dashboard.query.duration`, `ns.catalog.query.duration`, `ns.map.freshness.lag`) are defined once and emitted via the in-memory exporter in test.
  - No network call is made when `NS_ENV=local` (socket-blocking test).
- Pattern references: logging rule; secrets and PII gotcha.
- Tests to write: `packages/core/tests/observability/test_redaction.py`, `packages/core/tests/observability/test_metrics.py`, `packages/core/tests/observability/test_no_egress.py`.

### Item 5 — health-and-slo
- Deliverable: `/healthz` and `/readyz` routes with pluggable dependency probes (Cosmos, Event Hubs, Blob), SLO document, Grafana dashboard JSON and Azure Workbook JSON over the item 4 metric names.
- Owned files (may edit): `services/api/neurosphere_api/health/`, `docs/ops/slo.md`, `infra/observability/`, `services/api/tests/health/`.
- Must NOT touch: `services/api/neurosphere_api/main.py`, `app.py`, `middleware/` (item 2; register the router through the registry interface only), `packages/core/**`, `services/workers/**`, `infra/compose/`, `infra/bicep/**`; plus the shared list.
- Depends on: items 2, 3.
- Acceptance criteria:
  - `/readyz` returns 503 with enumerated reason codes when the Cosmos emulator is down; 200 when up (integration test, `pytest.mark.integration`).
  - Failure bodies contain no connection strings, keys or hostnames beyond the dependency name.
  - `docs/ops/slo.md` lists API availability 99.9%, dashboard p95 <=2s, catalog p95 <=500ms and map freshness p95 <=10s as planning targets, each with measurement method and owner PRP (PRP-14, 10, 18, 21), and states provider billing freshness is not sub-10s and the Copilot first-token <=3s target excludes provider outages.
  - Dashboard JSON parses and references only item 4 metric names.
- Pattern references: C10, C11; fail-closed rule.
- Tests to write: `services/api/tests/health/test_probes.py`, `services/api/tests/health/test_readyz_integration.py`, `tests/integration/health/test_dashboard_json.py`.

### Item 6 — cosmos-and-eventhub-clients  [P]
- Deliverable: async factories for Cosmos, Event Hubs producer and consumer, Blob checkpoint client; managed-identity path via `DefaultAzureCredential`, local-key path only when `NS_ENV=local`; endpoint hosts taken from `CloudProfile`; closing and lifetime helpers.
- Owned files (may edit): `packages/core/neurosphere_core/clients/`, `packages/core/tests/clients/`, `tests/integration/clients/`.
- Must NOT touch: `packages/core/neurosphere_core/errors|scope|paging|cloud|observability/` (read-only imports allowed), `services/**`, `docker-compose.yml`; plus the shared list.
- Depends on: item 1.
- Acceptance criteria:
  - Integration test writes and reads back one Cosmos document and sends and receives one event via the emulators using the factories.
  - With `NS_ENV` not `local`, passing a key or connection string raises `invalid_schema` (config) before any client is built.
  - Government profile builds endpoint URLs with the Government suffixes (unit test, no network).
  - SDK exceptions are translated to taxonomy errors (`dependency_transient`, `forbidden`, `stale_version` for 412).
- Pattern references: async client rule; C6; emulator limits (C4).
- Tests to write: `packages/core/tests/clients/test_factories.py`, `packages/core/tests/clients/test_error_translation.py`, `tests/integration/clients/test_emulator_roundtrip.py`.

### Item 7 — compose-app-services
- Deliverable: `api` and `workers` services in `docker-compose.yml` under profile `app`, dev Dockerfiles, healthchecks wired to `/readyz` and the worker health endpoint, env wiring to emulators.
- Owned files (may edit): `docker-compose.yml`, `services/api/Dockerfile.dev`, `services/workers/Dockerfile.dev`.
- Must NOT touch: `infra/compose/` (PRP-03), `Makefile` (PRP-03), production Dockerfiles (PRP-13), all `packages/**` and `services/**/neurosphere_*` code; plus the shared list.
- Depends on: items 2, 3.
- Acceptance criteria:
  - `docker compose --profile app up -d --wait` reports api and workers healthy; `docker compose down` leaves no orphan containers.
  - Default profile (no `app`) is unchanged and still starts only emulators.
  - Containers run on the PRP-03 egress-blocked network where applicable and carry no secrets in the compose file.
- Pattern references: PRP-03 compose profiles; secrets rule.
- Tests to write: `tests/integration/compose/test_app_profile.py` (marked `integration`).

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
uv sync --frozen
uv run ruff check packages services tests
uv run pyright
uv run pytest packages/core services/api services/workers -m "not integration and not live"
docker compose up -d --wait
uv run pytest tests/integration/clients tests/integration/health -m integration
docker compose --profile app up -d --wait
uv run pytest tests/integration/compose -m integration
docker compose --profile app down
```

No live script in this PRP. Any later managed-identity smoke against Azure is **operator-approved, requires NS_LIVE_APPROVED=1** and would live under `scripts/gates/`.

## Live and open gates

| Gate | Touch | Evidence that narrows it |
|---|---|---|
| G12 emulator parity | Narrows | Documented emulator-vs-live deltas from C4 recorded in the completion note; tests avoid asserting RU, index, auth behavior |
| G07 workload/SLO/DR | Starts | `docs/ops/slo.md` states targets and measurement methods; measured evidence is PRP-21 |
| G01 service/feature/region/SKU matrix | Not closed | Government hosts are a static profile, not an availability claim; capability matrix is PRP-02 |

Open items to carry: managed-identity access against real Cosmos and Event Hubs (Commercial and Government) has not run; Government endpoints are unit-tested as strings only.

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- JWT validation, scope derivation, policy middleware, audit, revocation (PRP-06).
- Ingest endpoint, normalizer, quarantine, archive, cost ledger (PRP-07).
- Catalog repository and graph (PRP-10), search implementations (PRP-03 fixture, PRP-10 Azure).
- Capability matrix loader and validator (PRP-02); analytics adapters (PRP-11).
- Production Dockerfiles, image publishing, Helm and Bicep (PRP-13, PRP-08).
- Network policy and threat model (PRP-12); SLO measurement under load (PRP-21).
- Any claim that SLO targets are met, or any availability, FedRAMP or ATO claim.

## Definition of Ready check

- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)

- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Open gates / untested live items:
- Follow-ups:
