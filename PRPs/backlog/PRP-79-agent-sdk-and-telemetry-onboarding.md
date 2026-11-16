---
name: PRP-79-agent-sdk-and-telemetry-onboarding
status: backlog
priority: P1
order: 70
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-01, NS-09
depends_on: [PRP-58-hosted-data-path-and-environment-hardening]
wave: W22
branch: prp-79-agent-sdk-onboarding
allow_parallel: true
issues: []
---

# PRP-79: Agent SDK and telemetry onboarding

## Goal
Let an agent developer connect an agent to NeuroSphere in a few lines and see it on the map without asking an operator to read a collector runbook. It ships a small agent-side Python package (`neurosphere-agent`) that wraps the existing OTLP/JSON path with the right resource attributes, a redaction guard and a connection check; an ingest edge that also accepts gzip request bodies (what standard OpenTelemetry exporters send by default); a quarantine read API and an admin page so malformed events stop vanishing from the user's view; and a "connect your agent in ten minutes" quickstart that is run against the local stack by a test. It is for the platform engineer in original feature 5a. It runs in W22 after PRP-58, which turns the producer store on in every profile so a producer can be registered through the admin API (PRP-41) and the UI (PRP-57) in any environment.

Out of scope: the platform and copilot dogfooding span exporter (a separate follow-up; see NOT building); the Entra producer authenticator and signed payloads (a separate follow-up, the seam stays in `ingest/auth.py`); OTLP protobuf at the edge (needs a new `opentelemetry-proto`/`protobuf` dependency, deferred; see Clarifications); the TypeScript SDK; ingest throughput and autoscaling (PRP-84); producer registry and its admin page (PRP-41, PRP-57, shipped); the quarantine replay action (stays the CLI `neurosphere_workers.quarantine`); publishing the package to PyPI (needs operator approval).

## Why
- Original PRD 5a, `git show 9fbf5f4c:docs/PRD.md` lines 33-45. Story: "As a platform engineer, I want to plug in a new agent with a standard SDK/webhook and have its telemetry flow automatically." Criterion: "At-least-once delivery with idempotent consumers; dead-letter queue for malformed events." The original NFR also asks for signed telemetry sources and that the platform dogfoods its own telemetry (split out here, see NOT building).
- v1.2 replaced rather than removed it: `docs/PRD.md:12` "Event Hubs has no built-in service-bus-style DLQ: implement quarantine explicitly." Quarantine exists as a blob store with a replay CLI (`services/workers/neurosphere_workers/quarantine/blob.py`), but no API or UI reads it (gap analysis 5a: zero "quarantine" matches in `services/api/neurosphere_api` and `frontend/src`). The "agent-side SDK" half of the story was never built: `connectors/sdk-python` and `sdk-ts` are connector-author SDKs.
- Today an agent developer needs an operator to register a producer, then a collector configured for JSON encoding by reading `docs/runbooks/ingest.md`; there is no "instrument your agent" document. `connectors/reference/otel-generic` has `ConnectorSpanExporter` and `readable_spans_to_otlp` (`convert.py:123`) but requires a Key Vault credential broker and manifest (`connector.py:193-231`), which is the wrong weight for an agent process.
- The edge accepts only `application/json` with identity encoding (`services/api/neurosphere_api/ingest/router.py:67-86`), so a stock `OTLPSpanExporter` with default gzip compression is refused with `unsupported_media_type`; unknown agents are auto-created as `draft` entities with `discovered_from=telemetry` (`services/workers/neurosphere_workers/projections/catalog/handler.py:19-23,275-300`), so the visible result of onboarding already exists.
- The edge mapping needs `gen_ai.agent.id` for the agent identity and fills the customer, source and cloud claims from the producer registration when omitted (`ingest/otlp_mapping.py:47-49,78`), so the SDK needs to send only the agent id and the credential.

## Acceptance criteria
- [ ] Given a registered producer and its secret in an environment variable, When a developer calls `neurosphere_agent.init(agent_id=..., ingest_url=...)` and runs one span through `agent_span(...)`, Then the edge answers 202 and, on the local stack, the agent appears as a `draft` catalog entity within the projection interval.
- [ ] Given `neurosphere_agent.verify_connection()`, Then it returns a result with a reason code for each failure class (`ingest_not_configured` 503, unauthorized 401, rate-limited 429, unreachable, unsupported media) and a plain-English next step; it never prints the credential or the response body.
- [ ] Given a span carrying prompt or response attributes, Then they are dropped before send and counted (reuse of `redact_outgoing`); the package exposes no option to send bodies.
- [ ] Given an exporter that sends `Content-Encoding: gzip`, When the body is within `max_body_bytes` after decompression, Then the edge accepts it; Given a decompressed size over the limit, a malformed gzip stream, a nested or non-gzip encoding, Then the edge answers the existing 4xx reason codes with a bounded amount of work (no unbounded decompression); `identity` bodies behave exactly as today.
- [ ] Given a customer-level administrator, When they call `GET /api/v1/admin/quarantine`, Then they get a bounded page of quarantine records (doc id, reason, attempts, quarantined time, source id, event id, replayed flag) filterable by reason and date, and `GET /api/v1/admin/quarantine/{doc_id}` returns the record with its body-free payload or hash and size; callers without customer-level `config.manage` get 403 with a denial record; the list never scans more than a configured number of blobs and reports `truncated`.
- [ ] Given the admin console, Then a Quarantine page lists and filters records, shows the reason with a one-line explanation per `QuarantineReason`, shows the replay command text for an operator, and states that replay is a CLI action; it passes axe and keyboard checks.
- [ ] Given the local stack with the dev producer, Then an integration test runs the quickstart's code verbatim (extracted from `docs/connectors/quickstart.md` between marker comments) and sees 202 plus the entity; a second test posts a malformed event, waits for the worker, and finds it through the quarantine API.
- [ ] The new workspace member is in `pyproject.toml` members, `uv.lock`, `docs/licenses.md` and the ADR-0002 table, every `uv sync --frozen` Dockerfile still builds its lock closure (verified per image with `grep` of the lock closure; copies added only where the closure demands), and the sharded CI python job still covers the new test root.
- [ ] No credential appears in the package, the docs examples, test output or log lines; the quickstart reads the secret from an environment variable and names the dev-only compose secret as dev only.
- PRP exit: touched suites, `tests/security/authz`, frontend gates for the page, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | SDK weight | Wrap the connector (vault broker); standalone thin package | Thin package `connectors/agent-sdk-python` depending on `httpx`, `opentelemetry-sdk` and `neurosphere-connector-otel-generic` for the shared conversion (`readable_spans_to_otlp`, `redact_outgoing`, one mapping). It does not use the vault broker: the credential is a bearer token read from `NS_AGENT_INGEST_TOKEN` or passed to `init`. ASSUMPTION: depending on the reference connector (and through it `neurosphere-core`) is acceptable inside this repo; a standalone wheel with a vendored mapping is a follow-up if the package is ever published. |
| 2 | Protobuf | Add now; defer | ASSUMPTION: defer. `opentelemetry-proto` and `protobuf` are not in `uv.lock`; adding them is a dependency and licence decision for a later PRP. The SDK sends OTLP/JSON, which the edge already accepts; gzip is added because it is stdlib and the default of common exporters. |
| 3 | Gzip safety | Trust `Content-Length`; bounded streaming decompress | Bounded streaming decompression capped at `max_body_bytes` of decompressed output and a compressed-size cap; anything else is refused with the existing reason codes. |
| 4 | Quarantine visibility | Records with no customer id hidden; shown to customer admins | ASSUMPTION: the deployment is single customer, so a customer-level administrator sees records whose `customer_id` equals theirs or is null (unparseable events are the ones most worth seeing). Revisit if multi-customer hosting is ever introduced. |
| 5 | Replay | Button; CLI only | CLI only. A replay button is an action path and would need the action executor (PRP-17); read-only here. |
| 6 | Permission | New permission; existing | Customer-level `config.manage` via `require_customer_control`, the same gate as producers (PRP-41), so no contracts change. |
| 7 | Dogfooding and Entra authenticator | Include; split | Split into follow-up PRPs. Including both exceeds one session (gap analysis R9 sizing note). Reported to the orchestrator. |
| 8 | Where the producer comes from | Built-in; operator-registered | Operator-registered through the PRP-41/PRP-57 path; the quickstart shows the admin page route and the dev-only compose producer `dev-ingest` for the local stack. |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/ingest/router.py` - `_read`, media-type and encoding check at lines 67-86; the three routes.
- `services/api/neurosphere_api/ingest/limits.py` - `read_limited`, `check_declared_length`; model for a bounded decompressor.
- `services/api/neurosphere_api/ingest/otlp_mapping.py` - claim attributes and `AGENT_ID_ATTRS`, `_OPERATION_KIND`, token and model attribute tables the SDK must emit.
- `connectors/reference/otel-generic/neurosphere_connector_otel_generic/convert.py` and `exporter.py` - `readable_spans_to_otlp`, `redact_outgoing`, `ConnectorSpanExporter` thread model.
- `connectors/reference/otel-generic/collector/README.md` - what an operator is told today.
- `services/workers/neurosphere_workers/quarantine/blob.py` and `ingestion/models.py:109-140`, `ingestion/reasons.py` - `BlobContainer`, `QuarantineRecord`, `QuarantineReason`, `create_quarantine_container`.
- `services/api/neurosphere_api/admin/sources/producers/router.py` - admin router and `require_customer_control` pattern to copy.
- `frontend/src/features/admin/sources/ProducersPage.tsx`, `routes.tsx`, `apiPaths.ts` and `frontend/src/features/admin/shared/areas.ts` - admin page, route and area registration.
- `docs/runbooks/ingest.md` - dev producer (`dev-ingest`, customer `synthco`, source `dev-source`) and the store switch.
- `pyproject.toml` (members, sources), `docs/licenses.md`, `docs/adr/0002-stack-pins.md:189`, `services/api/Dockerfile`.

### Interfaces consumed
- PRP-41/PRP-58: producer store on in every profile; producers created through `/api/v1/admin/sources/producers`; a producer id plus secret forms the bearer token.
- Shipped: edge routes `POST /api/v1/ingest/otlp/traces|metrics|events` (and the `/v1/ingest` alias); `QuarantineSettings` (`NS_QUARANTINE_CONTAINER`, `NS_QUARANTINE_STORAGE_ACCOUNT`); `require_customer_control(Permission.CONFIG_MANAGE)`; `ADMIN_AREAS` registry; the worker ingestion role that writes quarantine blobs.
- No PRP-70 types are needed: the quarantine view models are API-local (no contracts change).

### Interfaces provided
- Package `neurosphere_agent` (distribution `neurosphere-agent`, directory `connectors/agent-sdk-python`): `init(agent_id, ingest_url, token=None, ...)`, `agent_span(...)` context manager (sets `gen_ai.agent.id`, `gen_ai.operation.name`, model, provider and token-usage attributes), `emit_event(...)` for a CloudEvents webhook post, `verify_connection() -> ConnectionCheck`, `shutdown()`. Env names `NS_AGENT_INGEST_URL`, `NS_AGENT_INGEST_TOKEN`, `NS_AGENT_ID`.
- Edge: gzip request bodies accepted on all three ingest routes (`ingest/encoding.py`, `router.py` `_read` and `limits.py`). PRP-84 (W23) later edits the same `ingest/router.py` only to add the `ingest_overloaded` 429 admission check and never `_read`, `encoding.py` or `limits.py`; this PRP adds no overload, rate-limit or publisher change.
- Routes `GET /api/v1/admin/quarantine` and `GET /api/v1/admin/quarantine/{doc_id}`; package `neurosphere_api.admin.quarantine`; component `quarantine_reader` (optional) in `runtime/status.py`; settings `NS_QUARANTINE_LIST_MAX_BLOBS` (default 5000).
- Frontend route `/admin/quarantine`, area `quarantine` in `ADMIN_AREAS`; docs `docs/connectors/quickstart.md`.

### Patterns to match
- Admin router with customer control and bounded page: `admin/sources/producers/router.py`, `models.py`.
- Optional component built in a builder with a reason code when unconfigured: `runtime/builders/edge.py:17-27`.
- Thin exporter on its own event-loop thread: `otel-generic/exporter.py:28-45`.
- Admin page with list, filters and strings table: `frontend/src/features/admin/sources/ProducersPage.tsx`, `strings.ts`, `hooks.ts`.
- Workspace member `pyproject.toml`: `connectors/reference/otel-generic/pyproject.toml`.
- Compose-integration test marker and stack skip rules: `tests/integration/ingestion/support.py`.

### Gotchas
- Gzip: decompress incrementally with a hard output cap; do not call `gzip.decompress` on a request body. `Content-Length` describes the compressed size; keep the compressed cap too. Reject multi-member or trailing-garbage streams with the same reason code as malformed.
- Quarantine records are in Blob, not Cosmos; the container listing has no total count and `list_doc_ids` loads every name. The API wrapper pages with its own bounded iteration over `BlobContainer.list_blobs` and sets `truncated`; do not modify the worker package.
- Blob metadata (`reason`, `customer_id`, `quarantined_date`) is only a listing filter and is never trusted over the record; re-check `customer_id` on the loaded record before returning it.
- `doc_id` comes from the path: validate it against a strict pattern before building a blob name (path traversal and prefix injection).
- Records never carry bodies (`find_body_fields` is enforced in `QuarantineRecord`); the API must not add fields beyond the record's own.
- The local compose stack uses Azurite with a connection string only when `NS_ENV=local`; hosted uses managed identity (`create_quarantine_container`). The API compose service needs `NS_QUARANTINE_*` set; that edit is in `docker-compose.yml`, a Tier-1 file PRP-71 holds in W20, not W22: sequence it as a one-line additive change in item 5, `[serial-after: PRP-78]` (PRP-78 holds `docker-compose.yml` as Tier 1 in W22 for the demo-profile switch), and rebase.
- A new workspace member can break all five `uv sync --frozen` images (api, workers, both `.dev` Dockerfiles, `scripts/sandbox/Dockerfile.seed`) only if the lock closure of a built package references it; `neurosphere-connector-otel-generic` is not copied into the api image today, so check closures before adding COPY lines.
- New test roots: use `connectors/agent-sdk-python/tests` (covered by the `connectors` testpath and shard); do not add a new top-level root.
- `.env.example` is agent-blocked: hand the operator a script for any new variable, or document variables in the runbook only.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/agent-sdk-python/**
  - services/api/neurosphere_api/ingest/router.py
  - services/api/neurosphere_api/ingest/limits.py
  - services/api/neurosphere_api/ingest/encoding.py
  - services/api/tests/ingest_encoding/**
  - services/api/neurosphere_api/admin/quarantine/**
  - services/api/neurosphere_api/runtime/builders/quarantine.py
  - services/api/tests/admin_quarantine_api/**
  - tests/security/authz/test_admin_quarantine*.py
  - tests/integration/agent_onboarding/**
  - frontend/src/features/admin/quarantine/**
  - frontend/tests/mock-api/features/admin-quarantine.ts
  - frontend/tests/e2e/admin-quarantine/**
  - docs/connectors/quickstart.md
  - docs/runbooks/quarantine.md
tier1:
  - pyproject.toml
  - uv.lock
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
  - services/api/Dockerfile
  - services/api/Dockerfile.dev
  - services/workers/Dockerfile
  - services/workers/Dockerfile.dev
  - scripts/sandbox/Dockerfile.seed
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/features/admin/shared/areas.ts
  - frontend/src/features/admin/routes.tsx
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - docker-compose.yml
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/ingest/auth.py
  - services/api/neurosphere_api/ingest/service.py
  - services/api/neurosphere_api/ingest/otlp_mapping.py
  - services/api/neurosphere_api/ingest/producer_store.py
  - services/workers/neurosphere_workers/quarantine/**
  - connectors/reference/**
  - connectors/sdk-python/**
  - frontend/src/features/admin/sources/**
```

## Implementation blueprint

Parallelization: items 1, 2 and 3 [P] (SDK package, edge encoding and the quarantine API share no file). Item 4 needs 3; item 5 needs 1, 2 and 3; item 6 last.

### Item 1 - Agent SDK package and workspace wiring  [P]
- Deliverable: `connectors/agent-sdk-python` with `pyproject.toml` (hatchling, dependencies `httpx`, `opentelemetry-sdk`, `neurosphere-connector-otel-generic`), module `neurosphere_agent` exposing `init`, `agent_span`, `emit_event`, `verify_connection`, `shutdown`; a span exporter on a dedicated loop thread that posts gzip-free OTLP/JSON with `Authorization: Bearer <token>`, bounded retry and `Retry-After`, redaction through `redact_outgoing`, failures logged by reason code only; workspace wiring in root `pyproject.toml` (member and source), `uv.lock`, `docs/licenses.md`, ADR-0002 table; Dockerfile closure check recorded in the item notes.
- Owned files: `connectors/agent-sdk-python/**`, the Tier-1 files named in Ownership.
- Must NOT touch: `connectors/reference/**`, `connectors/sdk-python/**`.
- Depends on: PRP-58 merged (soft; the code does not need it, the quickstart does).
- Acceptance criteria: criteria 1 (against a fake edge), 2, 3 and 9; the credential is never in `repr`, logs or exceptions; `init` twice is idempotent; `shutdown` flushes; a span without prompt text and with a body attribute sends the first and drops the second.
- Tests: `connectors/agent-sdk-python/tests/test_init_and_span.py`, `test_verify_connection.py`, `test_redaction.py`, `test_secret_hygiene.py`, plus `uv lock --check` and the workspace-member tests under `tests/unit`.
- Pattern references: `otel-generic/exporter.py`, `otel-generic/pyproject.toml`, `connectors/sdk-python/tests/`.

### Item 2 - Gzip at the ingest edge  [P]
- Deliverable: `ingest/encoding.py` with a bounded streaming gzip reader; `ingest/router.py` `_read` accepts `identity` and `gzip` and refuses every other encoding with the existing `UNSUPPORTED_MEDIA_TYPE` code; decompressed size counts against `max_body_bytes`; `ingest/limits.py` gains the helper it needs only.
- Owned files: `services/api/neurosphere_api/ingest/{router,limits,encoding}.py`, `services/api/tests/ingest_encoding/**`.
- Must NOT touch: `ingest/auth.py`, `service.py`, `otlp_mapping.py`, `producer_store.py`.
- Depends on: none.
- Acceptance criteria: criterion 4, including a decompression bomb case (small body, huge output) refused before more than the cap is produced, and `identity` behaviour unchanged (existing `services/api/tests/ingest` passes untouched).
- Tests: `services/api/tests/ingest_encoding/test_gzip_accept.py`, `test_gzip_limits.py`, plus `services/api/tests/ingest`.
- Pattern references: `ingest/limits.py` `read_limited`, `ingest/router.py:67-86`.

### Item 3 - Quarantine read API  [P]
- Deliverable: `admin/quarantine/{__init__,router,models,reader}.py` (`register(registry)` hook; list with `reason`, `date`, `limit`, `cursor`; get by `doc_id`; a bounded blob iterator with `truncated`; customer-level gate; strict `doc_id` pattern; record re-check of `customer_id`), `runtime/builders/quarantine.py` building the reader from `QuarantineSettings` (disabled with a reason code when the container or account is not configured) and its `default_builders` line.
- Owned files: `services/api/neurosphere_api/admin/quarantine/**`, `runtime/builders/quarantine.py`, `services/api/tests/admin_quarantine_api/**`.
- Must NOT touch: `services/workers/neurosphere_workers/quarantine/**`.
- Depends on: none (fake `BlobContainer` in tests).
- Acceptance criteria: criterion 5; page cursor stable under inserts; invalid `doc_id` is 422 and never reaches storage; a record of another customer is 404; the reader never returns a body field; components pinned by `runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py` and `runtime_data/data_helpers.py` are updated.
- Tests: `services/api/tests/admin_quarantine_api/test_routes.py`, `test_reader_bounds.py`, `test_builder.py`; re-run `runtime_api`, `runtime_routes`, `runtime_data`, `runtime_gateway_builder`.
- Pattern references: `admin/sources/producers/router.py`, `runtime/builders/edge.py`.

### Item 4 - Quarantine admin page
- Deliverable: `frontend/src/features/admin/quarantine/` (page, hooks, types, strings with a one-line meaning per reason, detail drawer), the mock module `admin-quarantine.ts`, the `ADMIN_AREAS` entry, route and manifest line, axe and keyboard specs, a real-stack route row.
- Owned files: `frontend/src/features/admin/quarantine/**`, `frontend/tests/mock-api/features/admin-quarantine.ts`, `frontend/tests/e2e/admin-quarantine/**`, Tier-2 lines.
- Must NOT touch: `frontend/src/features/admin/sources/**`.
- Depends on: item 3 (response shapes).
- Acceptance criteria: criterion 6; empty, truncated and 403 states; no payload text is shown beyond the body-free `payload`; visual baselines come from the Docker job.
- Tests: `frontend/src/features/admin/quarantine/__tests__/*.test.tsx`, `frontend/tests/e2e/admin-quarantine/quarantine.spec.ts`, a11y route samples.
- Pattern references: `ProducersPage.tsx`, `admin-sources.ts` mock.

### Item 5 - Quickstart and local-stack proof  [serial-after: PRP-78]
- Deliverable: `docs/connectors/quickstart.md` (register a producer, install, five-line `init`, a span, `verify_connection`, see the draft agent on the map and in the catalog, find a rejected event in quarantine; marker comments around the runnable snippet); `tests/integration/agent_onboarding/` (extracts the snippet, runs it against the compose api, asserts 202 and the entity; posts a malformed event and finds it in the quarantine API); `docs/runbooks/quarantine.md`; compose `NS_QUARANTINE_*` lines for the api service (additive); nav entry.
- Owned files: the docs, `tests/integration/agent_onboarding/**`, Tier-2 lines (`docker-compose.yml`, `mkdocs.yml`).
- Must NOT touch: connector SDK or other runbooks except to link.
- Depends on: items 1, 2 and 3.
- Acceptance criteria: criteria 1, 7 and 10; the doc states that the dev secret is dev only and that hosted use needs a producer registered by an administrator; the integration test is `integration`-marked and skipped without the stack (reported as not run, not as passed).
- Tests: `tests/integration/agent_onboarding/test_quickstart.py`, `test_quarantine_visible.py` (local stack), `tests/docs` nav tests.
- Pattern references: `tests/integration/ingestion/support.py`, `docs/runbooks/ingest.md`.

### Item 6 - Integration and close-out
- Deliverable: Tier-2 appends (routers hook, inventories, `status.py`, mkdocs), authz suite `tests/security/authz/test_admin_quarantine*.py`, regenerate Tier 3 (`openapi.json`, `docs/reference/**`, route manifest, status table, `PRPs/INDEX.md`), changelog fragment under `changelog.d/`, completion note including the follow-up PRPs to file (dogfooding exporter, Entra authenticator, protobuf) and the product check (a developer follows the quickstart on a clean checkout).
- Owned files: Tier-2 lines, the authz tests, this PRP file, Tier-3 per reference section 2.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green including the image jobs.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/agent-sdk-python/tests services/api/tests/ingest services/api/tests/ingest_encoding services/api/tests/admin_quarantine_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/authz tests/security/authz tests/unit tests/docs services/api/tests/test_openapi_drift.py tests/test_ci_python_shards.py
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test -- src/features/admin/quarantine src/app/route-manifest.test.ts
pnpm --dir frontend exec playwright test tests/e2e/admin-quarantine tests/e2e/a11y/routes.a11y.spec.ts
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local stack check (not CI): `docker compose --profile app up -d --wait`, then `uv run pytest -q -m integration tests/integration/agent_onboarding`.

## Migration and rollback
No data migration. The edge change is additive (a new accepted encoding). The quarantine API reads existing blobs and is optional: with no quarantine container configured the component is disabled with a reason code and the routes answer 503. Rollback: revert the PR; the new workspace member is removed from `pyproject.toml` and `uv.lock` in the same revert. Dockerfile COPY lines (if any were needed) revert with it.

## Live and open gates
No live call. Open: an ingest and quarantine run on hosted Azure with a real producer (PRP-82 deploys, operator-attended; evidence in PRP-64), throughput of gzip bodies at 1k and 10k events/s (PRP-84, PRP-66), publication of the SDK to a package index (operator approval), the dogfooding exporter and Entra producer authenticator (follow-up PRPs).

## NOT building
OTLP protobuf; the TypeScript or any non-Python SDK; a published package; a quarantine replay or delete action in the UI or API; the platform and copilot self-telemetry exporter under a built-in producer (follow-up); the Entra producer authenticator and payload signing (follow-up); binary-mode CloudEvents headers; auto-registration of producers from the SDK; a collector distribution.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 2 and 4 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can a person use it): follow the quickstart on a clean checkout and watch the agent appear:
