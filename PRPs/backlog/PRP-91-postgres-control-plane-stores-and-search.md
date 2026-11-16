---
name: PRP-91-postgres-control-plane-stores-and-search
status: backlog
priority: P1
order: 82
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-02, NS-04, NS-06, NS-09
depends_on: [PRP-87-api-composition-seam-and-adapter-packages, PRP-88-worker-composition-seam-event-and-object-ports, PRP-89-postgres-foundation-catalog-and-security-stores, PRP-60-search-indexing-hardening, PRP-105-policy-engine-core, PRP-127-ai-system-register-tiering-and-impact-assessments, PRP-131-model-and-agent-cards-and-safety-evaluation-records]
wave: W37
branch: prp-91-postgres-control-plane-stores-and-search
allow_parallel: true
issues: []
---

# PRP-91: PostgreSQL control-plane stores and full-text search

## Goal
Give the control plane a PostgreSQL implementation: action intents and execution control, human-in-the-loop items and decisions, recommendations, evaluation runs and results, the MCP server registry, the deploy register, gateways and gateway apply records, lifecycle holds, requests, pseudonym mappings and jobs, copilot conversations, reports and the synthetic sandbox store, plus PostgreSQL full-text search behind the `AuthorizedSearch` and `IndexSink` Protocols with the scope predicate applied inside the SQL `WHERE` clause. Each store matches its Cosmos implementation (idempotency keys, optimistic concurrency by ETag, TTL, customer and domain scoping) and is proven by a conformance module that also runs on the in-memory implementation; search gets the first shared search suite in the repo, with the fixture index as oracle. It is for operators on AWS, GCP and on-prem Kubernetes, and for PRP-96 and PRP-98.

Out of scope: the PostgreSQL pool, schema generator, `PgCollection`, migrations, TTL sweeper, catalog backend and the security stores (catalog, review queue, policy, revocation, audit, audit search, admin config: PRP-89); data-plane stores (PRP-90); the API composition seam, adapter package scaffolding and dependency pins (PRP-87); the search indexing contract itself (PRP-60); search provider settings for the admin console (PRP-45 and later); OpenSearch and vector search (OPEN); Helm values (PRP-96). This PRP adds no dependency and does not edit `pyproject.toml` or `uv.lock`.

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." and "provider-specific managed-service substitutions ... behind a common abstraction layer".
- v1.2 excluded it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting ... outside the initial baseline"), `PRP.md:7`. Owner decision 2026-11-16: all four targets on one portable backend set (ASSUMPTION D-2 below). PRP-85 amends the v1.2 lines.
- About 24 store Protocols have no shared conformance module (only catalog, pricing, evaluation and recommendations do: `packages/core/tests/catalog/repo_conformance.py`, `packages/core/tests/{pricing,evaluation,recommendations}_cosmos/conformance.py`). The control-plane stores below are Cosmos-bound with Cosmos semantics in their docstrings: ETag `IfNotModified` replace and 412/404 to `stale_version` (`hitl_cosmos/store.py:11-12`, `mcp/cosmos_store.py:5-6`, `reports/cosmos_store.py:5-6`), an idempotency lookup document in a reserved partition (`actions/cosmos_store.py:9-19`), per-document TTL (`api/copilot/cosmos_store.py:3-8`), and cross-partition scans in the HITL and intent worker paths (`hitl_cosmos/store.py:18-26`, `IntentStore.list_in_states`).
- Search has an Azure implementation and a fixture but no second backend and no shared suite: `AuthorizedSearch` (`packages/core/neurosphere_core/search/protocol.py:84`), `AzureAuthorizedSearch` (`search/azure/client.py:62`), `FixtureSearchIndex` (`search/fixture/index.py:89`), `IndexSink` (`search/indexer.py:58`). The provider is a closed literal `Literal["fixture","azure"]` in `services/api/neurosphere_api/runtime/builders/search.py:89`.
- Some neutral modules mix the Protocol with Cosmos: `core/lifecycle/jobs.py:24-25`, `core/gateway/records.py:37-39`, `api/sandbox/repository.py:17-18`. PRP-87 splits them; this PRP builds on the split.
- The security-critical rule is unchanged by the platform: authorization is enforced at every query path, so the PostgreSQL search applies cloud, customer, allowed domains and granted resources in SQL before ranking, never after (`FixtureSearchIndex._in_scope`, `fixture/index.py:106-125`, is the reference).

## Acceptance criteria
- [ ] Governance-core control-plane stores: PostgreSQL implementations with conformance modules (same rules as every store here) for `policy_definitions`, `policy_violations`, `policy_exceptions` (PRP-105: version heads, violation de-duplication keys, exception expiry), `ai_systems`, `risk_determinations`, `impact_assessments`, `attestations`, `attestation_campaigns` (PRP-127, PRP-130), `alert_rules`, `incidents` (PRP-127, PRP-132; timeline documents) and `safety_evaluation_records` (PRP-131); and, if PRP-135's vector backend has shipped, a `pgvector` column and similarity query behind its embedding port with the scope predicate in the SQL `WHERE` clause (otherwise recorded as not applicable).
- [ ] Given each store below, When its conformance `CHECKS` run against the in-memory implementation and against PostgreSQL (marker `portable`), Then both pass with identical outcomes; each module ships one deliberately broken implementation that fails a named check. Existing shared modules (recommendations, evaluation) run unchanged against PostgreSQL.
- [ ] Given two customers (and two domains within one customer) using identical ids, When any read, list, write, delete or transition runs for one, Then the other's rows are never returned or changed; every statement binds customer (and domain where Cosmos filtered on it) as parameters.
- [ ] Given `IntentStore.create` replayed with the same `(principal_id, idempotency_key)` and identical payload, Then the original intent is returned; with a different payload digest, Then `idempotency_key_reused`; concurrent first creates yield exactly one stored intent. Given `replace` with a stale `if_match`, Then `stale_version` reason `intent_modified`. `ExecutionControl.set` is last-write-wins and an unreadable store is treated as disabled (`require_execution_enabled` still fails closed).
- [ ] Given HITL, MCP, gateway, report and deploy register replaces with a stale ETag, Then `stale_version` with the same reason codes as Cosmos (`etag_mismatch`, `server_modified`, `report_modified`); create-only registrations conflict on a duplicate; `HitlStore.due` and `open_maker_checker` stay bounded, ordered, and return only what Cosmos returns.
- [ ] Given a conversation or turn past its `expires_at`, Then reads and lists do not return it (read-time filter) and the TTL sweeper from PRP-89 removes it; a new turn extends the conversation expiry exactly as `api/copilot/cosmos_store.py:166-178` does.
- [ ] Given gateway apply records, Then versions and head are append-only: a changed immutable facet is refused with `StaleVersionError` like `core/gateway/records.py:96-111`.
- [ ] Given a lifecycle job, hold, request or mapping, Then enqueue, place, release, remove, destroy and `JobStore` transitions match the in-memory twins and the Cosmos behaviour (idempotent enqueue, `active()` ordering).
- [ ] Given a search request, When `PostgresAuthorizedSearch.search(scope, request)` runs, Then the result ids equal the `FixtureSearchIndex` result ids over the same documents for term, entity and domain filters (membership and scope filtering are compared, never scores); documents outside the caller's cloud, customer, allowed domains and granted read resources are absent; the term never reaches SQL text; the budget limit sets `partial` with reason `limit`; a statement timeout yields `partial` with reason `timeout_ms`; `IndexSink.upsert` is idempotent by id and `delete(ids)` (PRP-60) removes.
- [ ] Given `NS_SEARCH_PROVIDER=postgres`, Then `/readyz` shows search composed and `app.state.search_runtime.provider == "postgres"`; given PostgreSQL unavailable, Then the component is disabled with a reason code, never a silent fixture fallback.
- [ ] No generated SQL from user or model input; no DSN or secret in logs, errors, audit or OpenAPI.
- PRP exit: touched suites, `tests/conformance/documents_controlplane`, `tests/conformance/search`, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated only if a settings or status change requires it.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Search ranking and matching | `pg_trgm` fuzzy; exact token | ASSUMPTION: exact-token parity with the fixture. Text is tokenised in Python with the shared `tokenize` (`[a-z0-9]+`, lower-case) at index time into a `tokens text[]` column plus a generated `tsvector` for ranking; the query is the OR of validated tokens bound as a parameter. This keeps membership equal to the fixture oracle; `pg_trgm` (named in the design) would change membership and is left out |
| 4 | Where the search table comes from | `CONTAINERS`; own migration | Own table `search_documents` (columns `id`, `entity`, `cloud`, `customer_id`, `domain_id`, `tokens`, `tsv`, `doc jsonb`) created by an additive migration through PRP-89's runner; the search index is not a Cosmos container, so `stores/containers.py` stays untouched |
| 5 | Statement budget | client-side timer; server-side | `SET LOCAL statement_timeout` from `Budget.timeout_ms` inside the transaction; on cancel return `partial` reason `timeout_ms` with no hits (the fixture returns hits found so far; the divergence is documented in the suite as a known difference, compared only for non-timeout cases) |
| 6 | Where the API-package stores live | adapter package; API package | `ConversationStore`, `ReportStore` and `SandboxStore` and their model types are defined in `services/api`, which the adapter package must not import. The PostgreSQL twins therefore live beside them as `copilot/postgres_store.py`, `reports/postgres_store.py` and `sandbox/postgres_store.py` and import `PgCollection` from the adapter package; they are lazily imported by kind. PRP-85's boundary rules list these three files in `ADAPTER_PATHS` |
| 7 | Cut line if the session overruns | descope last | See `## Cut line` |
| 8 | Cross-partition scans | forbid; keep as Cosmos | Keep exactly the bounded scans the Protocols define (`IntentStore.list_in_states`, `HitlStore.due` and `open_maker_checker`, id lookups across domains inside one customer); each gets an index and a conformance check for the bound and the order |
| 9 | Compose lane in W37 | parallel; serialized | PRP-90 is the W37 compose-stack holder; this PRP runs its compose-backed gates `[serial-after: PRP-90]` (after PRP-90 released PostgreSQL), before PRP-94, with its own schema names. No file is shared with PRP-90 or PRP-94 |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/actions/{store,control,cosmos_store}.py` - `IntentStore`, `ExecutionControl`, the idempotency lookup layout, `list_in_states`.
- `packages/core/neurosphere_core/hitl/{store,decisions}.py` and `hitl_cosmos/store.py` - `HitlStore`, `DecisionStore`, scans, ETag mapping.
- `packages/core/neurosphere_core/{recommendations,evaluation}/{store,cosmos_store}.py` and the two `*_cosmos/conformance.py` modules.
- `packages/core/neurosphere_core/mcp/{store,cosmos_store}.py`, `deploy/register/{store,cosmos_store}.py`, `gateway/{store,cosmos_store,records}.py`.
- `packages/core/neurosphere_core/lifecycle/{targets,jobs,cosmos,memory}.py`.
- `services/api/neurosphere_api/copilot/{store,cosmos_store}.py`, `reports/{store,cosmos_store}.py`, `sandbox/repository.py`.
- `packages/core/neurosphere_core/search/{protocol,indexer}.py`, `search/fixture/index.py`, `search/azure/{client,filters}.py`, `packages/core/tests/search/search_helpers.py`.
- `services/api/neurosphere_api/runtime/builders/search.py` - `SearchSettings`, `SearchRuntime`, provider dispatch.
- `PRPs/backlog/PRP-60-search-indexing-hardening.md`, `PRP-87-api-composition-seam-and-adapter-packages.md`, `PRP-89-postgres-foundation-catalog-and-security-stores.md` - "Interfaces provided".

### Store inventory
| Store | Protocol | Cosmos implementation it must match | Conformance module to write (`tests/conformance/documents_controlplane/` unless noted) |
|---|---|---|---|
| Action intents | `IntentStore` `actions/store.py:67` | `CosmosIntentStore` `actions/cosmos_store.py:138` | `intents_checks.py` |
| Execution control | `ExecutionControl` `actions/control.py:57` | `CosmosExecutionControl` `:362` | `execution_control_checks.py` |
| HITL items | `HitlStore` `hitl/store.py:68` | `CosmosHitlStore` `hitl_cosmos/store.py:165` | `hitl_checks.py` |
| HITL decisions | `DecisionStore` `hitl/decisions.py:72` | `CosmosDecisionStore` `:326` | `hitl_checks.py` |
| Recommendations | `RecommendationStore` `recommendations/store.py:36` | `CosmosRecommendationStore` `recommendations/cosmos_store.py:109` | existing `packages/core/tests/recommendations_cosmos/conformance.py`, loaded by file path |
| Evaluation | `EvaluationStore` `evaluation/store.py:109` | `CosmosEvaluationStore` `evaluation/cosmos_store.py:186` | existing `packages/core/tests/evaluation_cosmos/conformance.py` |
| MCP registry | `McpServerStore` `mcp/store.py:66` | `CosmosMcpServerStore` `mcp/cosmos_store.py:83` | `mcp_checks.py` |
| Deploy register | `RegisterStore` `deploy/register/store.py:26` | `CosmosRegisterStore` `register/cosmos_store.py:47` | `register_checks.py` |
| Gateways | `GatewayStore` `gateway/store.py:54`, `GatewayModeLookup` `:84` | `CosmosGatewayStore` `gateway/cosmos_store.py:94` | `gateway_checks.py` |
| Gateway records | neutral Protocol from PRP-87's split of `gateway/records.py` (twin `InMemoryGatewayRecordStore` `:113`) | `CosmosGatewayRecordStore` `:183` | `gateway_records_checks.py` |
| Lifecycle holds, requests, mappings | `HoldRegistry` `lifecycle/targets.py:70`, `RequestQueue` `:94`, `PseudonymMappingStore` `:61` | `CosmosHoldRegistry` `lifecycle/cosmos.py:186`, `CosmosRequestQueue` `:240`, `CosmosMappingStore` `:132` | `lifecycle_checks.py` |
| Lifecycle jobs | `JobStore` `lifecycle/jobs.py:85` | `CosmosJobStore` `:163` | `lifecycle_checks.py` |
| Conversations | `ConversationStore` `api/copilot/store.py:152` | `CosmosConversationStore` `copilot/cosmos_store.py:77` | `conversations_checks.py` |
| Reports | `ReportStore` `api/reports/store.py:84` | `CosmosReportStore` `reports/cosmos_store.py:94` | `reports_checks.py` |
| Sandbox | `SandboxStore` `api/sandbox/repository.py:64` | `CosmosSandboxStore` `:127` | `sandbox_checks.py` |
| Search query | `AuthorizedSearch` `search/protocol.py:84` | `AzureAuthorizedSearch` `search/azure/client.py:62`; oracle `FixtureSearchIndex` `search/fixture/index.py:89` | `tests/conformance/search/checks.py` |
| Search indexing | `IndexSink` `search/indexer.py:58` | `AzureIndexSink` `:103`; twin `FixtureSearchStore` `:74` | `tests/conformance/search/checks.py` |

### Interfaces consumed
- PRP-89 (not merged when this PRP is written; read by purpose and adapt to its published names): pool with `TokenProvider` hook, schema generated from `CONTAINERS` (partition columns, `doc jsonb`, `etag`, `expires_at`), migration runner, TTL sweeper with read-time filter, `PgCollection` (point read, insert, replace-if-match, upsert, delete, bounded parameterised query, single-partition transaction), error translation, `infra/compose/portable/postgres.yml`, the per-module schema fixture, `scripts/portable/run_conformance.py`, and the pre-created control-plane registration module `registry/controlplane.py` (reached through PRP-89's `registration.py` `register` and `register_worker`).
- PRP-87: package skeleton and dependency pins; the `portable` pytest marker; the backend provider and registry through which API builders ask for stores; the split Protocol modules for `gateway/records.py`, `lifecycle/jobs.py`, `sandbox/repository.py` (if PRP-87 cut its item 6, import those Protocols from the mixed modules); `runtime/builders/search.py` seam. Item 7 is `[serial-after: PRP-87, PRP-60]`.
- PRP-88: `WorkerBackendRegistry` and port names for the worker-side stores (actions, hitl_timers, lifecycle, recommendations, evaluation, gateway_poll builders); `InMemoryEventStream`/`InMemoryObjectStore` are not needed here. If PRP-88 cut its late-role group (its `## Cut line`), see this PRP's `## Cut line`.
- PRP-60: `IndexSink.delete(ids)`, `neurosphere_core.search.azure.schema.encode_document_key` (Azure-only; PostgreSQL stores raw canonical ids), `wrap_catalog_for_search`, `IndexingCatalogRepository`.
- Shipped: the error taxonomy, `Budget`, `IdentityScope`, `compute_scope_hash`.

### Interfaces provided
- `neurosphere_adapters_postgres.controlplane`: `PgIntentStore`, `PgExecutionControl`, `PgHitlStore`, `PgDecisionStore`, `PgRecommendationStore`, `PgEvaluationStore`, `PgMcpServerStore`, `PgRegisterStore`, `PgGatewayStore`, `PgGatewayRecordStore`, `PgHoldRegistry`, `PgRequestQueue`, `PgMappingStore`, `PgJobStore`.
- `neurosphere_adapters_postgres.search`: `PostgresAuthorizedSearch`, `PostgresIndexSink` (one object serves both Protocols, like `FixtureSearchStore`), the `search_documents` migration.
- `services/api/neurosphere_api/{copilot,reports,sandbox}/postgres_store.py`: `PgConversationStore`, `PgReportStore`, `PgSandboxStore`.
- Registrations under kind `postgres` in `registry/controlplane.py` (`register` for the API provider, `register_worker` for the worker registry).
- Search provider value `postgres` (`NS_SEARCH_PROVIDER=postgres`); no other new `NS_*` setting. Connection settings are PRP-89's.
- Conformance: `tests/conformance/documents_controlplane/`, `tests/conformance/search/` (`checks.py`, `test_memory.py` or `test_fixture.py`, `test_postgres.py`).

### Patterns to match
- `CHECKS` table, loaded by file path: `packages/core/tests/catalog/repo_conformance.py`, `tests/integration/catalog/test_repo_cosmos.py:37-42`.
- Oracle equivalence: `tests/integration/analytics/test_equivalence.py`.
- Broken implementation proving a kit can fail: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- Scope-first search: `search/fixture/index.py:106-125`, `search/azure/filters.py` (allowlisted values only).
- Fixed templates over allowlisted fields: `packages/core/neurosphere_core/catalog/repo/backend.py:1-11`.

### Gotchas
- Idempotency layout: keep the reserved partition `(customer_id, "__idempotency__")` and the id `idem-<sha256(principal_id, key)>` so the table content is shape-compatible with Cosmos; PostgreSQL can create the intent and the lookup row in one transaction, which is stricter than Cosmos and still satisfies the Protocol.
- HITL `decisions` partition by `review_item_id` and carry no customer or domain on the document; the table keeps `review_item_id` as its partition column and the conformance check asserts a decision is only readable through an item the caller can read.
- Evaluation looks an id up across domains first (`evaluation/cosmos_store.py:281`): a differing re-put anywhere in the customer is a conflict; keep that.
- Gateway store point queries are cross-domain by customer and gateway id and by ARM id (`gateway/cosmos_store.py:140,159`); index both.
- `RecommendationStore` and the evaluation store write several partitions without a transaction in Cosmos; a PostgreSQL transaction is allowed but must keep the same idempotent upsert result.
- Sandbox is an isolated synthetic store with a fixed allowlist of containers (`sandbox/repository.py:38-40`); the PostgreSQL twin must keep the allowlist and never share tables with real data.
- `HitlStore` rows carry an `etag` field in the model; the PostgreSQL row's `etag` column is the source, as `hitl_cosmos/store.py:158` sets it from `_etag`.
- `runtime/builders/search.py` is a PRP-87 Tier-1 builder and PRP-60 also edits it; this PRP's change to it is a serial item.
- Same-named test directories shadow each other: new directories are `documents_controlplane` and `search` under `tests/conformance`.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-postgres/neurosphere_adapters_postgres/controlplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/search/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/controlplane.py
  - services/api/neurosphere_api/copilot/postgres_store.py
  - services/api/neurosphere_api/reports/postgres_store.py
  - services/api/neurosphere_api/sandbox/postgres_store.py
  - tests/conformance/documents_controlplane/**
  - tests/conformance/search/**
tier1:
  - services/api/neurosphere_api/runtime/builders/search.py
tier2_appends: []
must_not_touch:
  - packages/adapters-postgres/neurosphere_adapters_postgres/dataplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/dataplane.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/foundation.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/registration.py
  - packages/adapters-postgres/pyproject.toml
  - pyproject.toml
  - uv.lock
  - infra/compose/portable/**
  - scripts/portable/**
  - .github/workflows/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/contracts/**
  - services/workers/neurosphere_workers/runtime/**
```

## Implementation blueprint

Parallelization: item 1 first (creates the package root and shared helpers). Items 2 to 6 [P] after item 1 (distinct modules and conformance files). Item 7 after 1 to 6 (registration and the Tier-1 search builder edit, `[serial-after: PRP-87, PRP-60]`). Item 8 last.

### Item 1 - Package root, shared helpers and PostgreSQL full-text search
- Deliverable: `controlplane/__init__.py` and `search/__init__.py` (one-line docstrings), `_support.py` test helpers, `PostgresAuthorizedSearch` and `PostgresIndexSink` over `search_documents` with the additive migration, `tests/conformance/search/checks.py` (scope isolation across customers, domains, granted resources and clouds; term and filter membership equal to `FixtureSearchIndex`; limit and timeout partials; idempotent upsert; delete; a term containing quotes, `|`, `&`, `:` and SQL fragments returns an empty or normal result and never errors) with `test_fixture.py` and `test_postgres.py`, and a broken twin that filters scope after ranking.
- Owned files: `packages/adapters-postgres/neurosphere_adapters_postgres/search/**`, `controlplane/__init__.py`, `tests/conformance/search/**`, `tests/conformance/documents_controlplane/_support.py`.
- Must NOT touch: PRP-89 modules, the search builder (item 7).
- Depends on: PRP-89, PRP-60 merged.
- Acceptance criteria: the search criteria above; the broken twin fails the scope check.
- Tests: `tests/conformance/search`, `packages/core/tests/search`.
- Pattern references: `search/fixture/index.py:89-200`, `search/indexer.py:74-101`, `packages/core/tests/search/test_fixture_scope_filter.py`.

### Item 2 - Actions and HITL  [P]
- Deliverable: `PgIntentStore`, `PgExecutionControl`, `PgHitlStore`, `PgDecisionStore` with their checks (idempotent create, replay and digest mismatch, concurrent creates, stale replace, state paging with opaque `k1.` cursors, cross-partition `list_in_states` bound and order, `due` and `open_maker_checker`, fail-closed control, decision immutability).
- Owned files: `controlplane/{intents,execution_control,hitl}.py`, `tests/conformance/documents_controlplane/{intents,execution_control,hitl}_checks.py`.
- Must NOT touch: other families.
- Depends on: item 1.
- Acceptance criteria: the action and HITL criteria above; `services/workers/tests/action_executor` and `hitl_timers` logic runs against `PgIntentStore` through a parametrised copy of the in-memory fixtures.
- Tests: those check modules via `test_memory.py` and `test_postgres.py`.
- Pattern references: `actions/cosmos_store.py:138-420`, `hitl_cosmos/store.py:165-380`.

### Item 3 - Recommendations and evaluation  [P]
- Deliverable: `PgRecommendationStore` and `PgEvaluationStore` loading the existing conformance modules by file path (no copy) plus a PostgreSQL-specific module for the cross-domain id conflict.
- Owned files: `controlplane/{recommendations,evaluation}.py`, `tests/conformance/documents_controlplane/{test_recommendations,test_evaluation}_postgres.py`.
- Must NOT touch: `packages/core/tests/{recommendations,evaluation}_cosmos/**` (imported only).
- Depends on: item 1.
- Acceptance criteria: both existing conformance tables pass unchanged on PostgreSQL; windowed result reads equal the in-memory store.
- Tests: the two modules above.
- Pattern references: `packages/core/tests/recommendations_cosmos/test_recommendation_conformance.py`.

### Item 4 - MCP registry, deploy register, gateways and gateway records  [P]
- Deliverable: `PgMcpServerStore` (create-only registration, ETag replace), `PgRegisterStore` (consent rows), `PgGatewayStore` (gateway and inventory docs, cross-domain lookups), `PgGatewayRecordStore` (version rows plus head, append-only facets) and their checks.
- Owned files: `controlplane/{mcp,register,gateways}.py`, `tests/conformance/documents_controlplane/{mcp,register,gateway,gateway_records}_checks.py`.
- Must NOT touch: `core/gateway/records.py` (PRP-87 split it).
- Depends on: item 1; PRP-87 merged.
- Acceptance criteria: stale-ETag and duplicate-create behaviour with the Cosmos reason codes; immutable facet refusal; lookups by ARM id and gateway id scoped to the customer.
- Tests: those check modules.
- Pattern references: `mcp/cosmos_store.py:83-140`, `gateway/records.py:96-111,183-290`.

### Item 5 - Lifecycle holds, requests, mappings and jobs  [P]
- Deliverable: `PgHoldRegistry`, `PgRequestQueue`, `PgMappingStore`, `PgJobStore` and `lifecycle_checks.py` against the in-memory twins in `lifecycle/memory.py` and `InMemoryJobStore`.
- Owned files: `controlplane/lifecycle.py`, `tests/conformance/documents_controlplane/lifecycle_checks.py`.
- Must NOT touch: `lifecycle/**` core modules.
- Depends on: item 1; PRP-87 merged (jobs split).
- Acceptance criteria: idempotent enqueue and mapping, `active()` holds, release returns whether a hold existed, job state transitions and checkpoints as `job_checkpoint`; stores are bound to one customer and stamp `customer_id`.
- Tests: `lifecycle_checks.py`; `packages/core/tests/lifecycle`, `packages/core/tests/lifecycle_cosmos`.
- Pattern references: `lifecycle/cosmos.py:132-290`, `lifecycle/jobs.py:85-200`.

### Item 6 - Conversations, reports and sandbox  [P]
- Deliverable: `PgConversationStore` (expiry through `expires_at`, read-time filter, newest-turn extension), `PgReportStore` (ETag replace and delete, `sort_key` listing), `PgSandboxStore` (container allowlist) in the API package, with checks.
- Owned files: `services/api/neurosphere_api/{copilot,reports,sandbox}/postgres_store.py`, `tests/conformance/documents_controlplane/{conversations,reports,sandbox}_checks.py`.
- Must NOT touch: the existing `cosmos_store.py` and `repository.py` modules.
- Depends on: item 1; PRP-87 merged.
- Acceptance criteria: expiry and extension rules; report stale-ETag reason `report_modified`; sandbox refuses an unlisted container before any SQL; owner-scoped reads (`/owner` partition) never cross principals.
- Tests: those check modules; `services/api/tests/copilot_api`, `services/api/tests/reports`, `services/api/tests/sandbox_api` unchanged.
- Pattern references: `copilot/cosmos_store.py:77-200`, `reports/cosmos_store.py:94-170`, `sandbox/repository.py:127-190`.

### Item 7 - Registration, search provider and end-to-end checks  [serial-after: PRP-87, PRP-60]
- Deliverable: fill `registry/controlplane.py` (register every store under kind `postgres` with PRP-87's API provider through `register` and PRP-88's worker registry through `register_worker`); widen the search provider in `runtime/builders/search.py` to accept `postgres` (the provider literal at `:89` and the dispatch at `:218-258`), composing `PostgresAuthorizedSearch` behind the same scope cache and write hook (`wrap_catalog_for_search`), disabled with a reason code when PostgreSQL is unavailable. An API-level test boots the app with kind `postgres` stand-ins for the control-plane stores and checks `/readyz` components and one authorized search.
- Owned files: `registry/controlplane.py`, `services/api/neurosphere_api/runtime/builders/search.py`, `tests/conformance/documents_controlplane/test_api_composition.py`.
- Must NOT touch: other builders.
- Depends on: items 1 to 6; PRP-87 and PRP-60 merged (the file is their Tier-1 and shared with PRP-60's edits).
- Acceptance criteria: criteria on provider `postgres`; existing `services/api/tests/runtime_data/test_search_builder.py` suites pass unchanged; the `default_builders` order and component sets pinned in `services/api/tests/runtime_api/test_readiness.py` are unchanged (no new builder is added).
- Tests: `services/api/tests/runtime_data/test_search_builder.py`, `tests/conformance/documents_controlplane/test_api_composition.py`.
- Pattern references: `runtime/builders/search.py:218-264`.

### Item 8 - Integration and close-out
- Deliverable: changelog fragment `changelog.d/PRP-91-postgres-control-plane-stores-and-search.md`; regenerate Tier-3 files only if `openapi.json` or `docs/reference/**` drift; confirm the portable runner discovers `documents_controlplane` and `search`; Completion note per reference section 6 with the cut-line outcome.
- Owned files: `changelog.d/PRP-91-postgres-control-plane-stores-and-search.md`.
- Depends on: item 7.
- Acceptance criteria: gates below pass; `python scripts/portable/run_conformance.py --list` lists both directories.
- Tests: validation gates.

## Cut line
The governance-core control-plane group (policy, register, risk, attestation, alerting, safety records and `pgvector`) may be split into a follow-up PRP as a unit (design expectation: PRP-90 or PRP-91 splits); those stores are then reported `disabled: platform_backend_missing` on non-Azure platforms, never a Cosmos fallback, and PRP-96 and PRP-98 show them so.
Actions, HITL, recommendations, evaluation, MCP, lifecycle, conversations and search (and items 7-8) are never cut. If the session overruns, the deploy register, gateways and gateway records (part of item 4) and reports and the sandbox store (part of item 6) are descoped; what remains merges safely because item 7 registers only the stores that exist, and the descoped ones are reported "disabled with a reason" (capability `platform_not_supported` or `store_backend_unavailable`) on non-Azure platforms, never silently missing, with a follow-up issue. If PRP-88 cut its late-role group, item 7 still registers the worker-side stores, but the actions, hitl_timers, recommendations, evaluation and gateway_poll roles keep refusing to start on non-Azure platforms with `capability_unavailable` (`backend_not_registered`) until PRP-88's follow-up lands; this is recorded in the completion note. PRP-96 renders only settings that exist; PRP-98's matrix shows cut stores as `disabled: <reason>`.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/conformance/documents_controlplane tests/conformance/search packages/core/tests/search packages/core/tests/lifecycle packages/core/tests/lifecycle_cosmos packages/core/tests/recommendations_cosmos packages/core/tests/evaluation_cosmos services/api/tests/runtime_data/test_search_builder.py services/api/tests/runtime_api tests/security/authz
docker compose -f infra/compose/portable/postgres.yml up -d --wait
uv run pytest -q -m portable tests/conformance/documents_controlplane tests/conformance/search
docker compose -f infra/compose/portable/postgres.yml down -v
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New installs only; nothing is migrated from Cosmos or Azure AI Search (OPEN). The `search_documents` table is created by an additive migration through PRP-89's runner and populated by the existing indexer from the catalog (a full refresh rebuilds it). Azure deployments are untouched: the new provider value and store kinds are opt-in. Rollback: revert the PR; unset `NS_SEARCH_PROVIDER` or select another provider, drop `search_documents` if wanted (derived data only). Control-plane tables hold data, so switching an existing non-Azure install between backends is a reinstall.

## Live and open gates
No paid call is made; every proof runs on a local PostgreSQL container. OPEN, handed to PRP-98: RDS and Cloud SQL runs with IAM database authentication (PRP-94 token provider), search latency and relevance on a catalog at the original NFR scale, an OpenSearch adapter, and the Azure-only features listed as disabled on non-Azure platforms (deploy scan, APIM gateway management are disabled by PRP-86 and PRP-96, not by this PRP). Live runs need `NS_LIVE_APPROVED=1` and an operator.

## NOT building
- Catalog, review queue, policy, revocation, audit, audit search and admin config stores (PRP-89); data-plane stores (PRP-90).
- Fuzzy or semantic search, `pg_trgm`, `pgvector` or OpenSearch.
- Cosmos to PostgreSQL data migration.
- Changes to any Protocol or Cosmos store; the Azure AI Search path stays as PRP-60 leaves it.
- New settings other than the `postgres` search provider value, or Helm values (PRP-96).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 3, 5, 6 and 7 are ASSUMPTIONS; D-7 in PRP-85 applies to every store here for plan approval; PRP-87 and PRP-89 names are read by purpose until they merge)

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
