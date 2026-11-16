---
name: PRP-89-postgres-foundation-catalog-and-security-stores
status: backlog
priority: P1
order: 80
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-02, NS-07, NS-08
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-87-api-composition-seam-and-adapter-packages, PRP-102-encrypted-interaction-store-and-retention]
wave: W36
branch: prp-89-postgres-foundation
allow_parallel: true
issues: []
---

# PRP-89: PostgreSQL foundation, catalog and the security-critical stores

## Goal
Ship the PostgreSQL document-store foundation in the `neurosphere_adapters_postgres` workspace package and run the catalog (documents and graph adjacency), the catalog review queue, policy and policy administration, revocation, the audit hash chain, audit search and admin config on it, each proven by a shared conformance suite that runs on the in-memory twin, the Cosmos emulator where one exists, and a local PostgreSQL container. It is for the operator who installs NeuroSphere on AWS, GCP or an on-prem cluster (owner decision 2026-11-16), where Cosmos DB does not exist, and for PRP-90, PRP-91 and PRP-94, which build on the pool, the collection helper, the schema generator and the conformance harness this PRP provides. Security weight: these are the stores that hold who may do what (policy), who is blocked (revocation) and what happened (audit); every guarantee the Cosmos implementations give that authorization depends on must hold on PostgreSQL, proven by a test, not asserted.

Out of scope: data-plane stores (ledger, aggregates, outbox, ingestion markers, quarantine, price snapshots: PRP-90); control-plane stores and PostgreSQL full-text search (PRP-91); IAM database authentication and the token provider bodies (PRP-94 fills the hook this PRP defines); Helm values and the in-cluster PostgreSQL operator (PRP-96); backup and restore tooling (PRP-98); migration of an existing Cosmos deployment (OPEN, design section 9 item 6); the composition seam and the dependency pins (PRP-87).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-106): "Platform deployable via containerized/IaC templates to Azure, AWS, GCP, or on-prem Kubernetes, with provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer." and the criterion "Core platform logic (ingestion normalization, graph API, recommendation engine, copilot) is cloud-agnostic; only infra adapters differ." The story "As an enterprise customer with data-residency requirements, I want an on-prem/air-gapped deployment option" needs a store that runs in-cluster.
- v1.2 excluded it: `docs/PRD.md:4` ("third-party AI providers are connector targets, not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting, classified/air-gapped deployment ... are outside the initial baseline"), `PRP.md:7` ("No commitment to platform hosting on AWS/GCP/on-prem"). On 2026-11-16 the owner decided to add back all four targets (Azure, AWS, GCP, on-prem Kubernetes); PRP-85 amends those lines.
- Every store is Cosmos by construction: the policy admin repository holds the only transactional batch in the codebase (`packages/core/neurosphere_core/auth/scope/policy_admin.py:553`, `execute_item_batch` with `partition_key=policy.customer_id`), and the audit chain depends on a create-only record insert plus an ETag-guarded tail (`packages/core/neurosphere_core/audit/store.py:48-71`, `audit/cosmos_store.py:120-131`).
- The catalog already has the best seam in the repo: `DocBackend` with three methods (`packages/core/neurosphere_core/catalog/repo/backend.py:90-103`) and a structured, allowlisted `Query` (`:54-80`); a PostgreSQL backend under `CatalogEngine` (`catalog/repo/engine.py:112`) runs the whole catalog and graph without a graph database.
- Only four store Protocols have a shared conformance module (`packages/core/tests/catalog/repo_conformance.py`, `packages/core/tests/{pricing,evaluation,recommendations}_cosmos/conformance.py`; plus `packages/core/tests/review_queue_cosmos/contract.py`). Policy, revocation, audit and admin config have only per-implementation tests (`packages/core/tests/admin/test_policy_admin*.py`, `packages/core/tests/auth/revocation/`, `packages/core/tests/audit/`), so "conformance-tested" would be false without new suites (design section 4.1).
- `CONTAINERS` (`packages/core/neurosphere_core/stores/containers.py:98-199`, 30 containers with partition key paths and TTL) is the single schema source to generate PostgreSQL tables from, so no second schema is maintained by hand.

## Acceptance criteria
- [ ] Given `docker compose -f infra/compose/portable/postgres.yml up -d --wait`, When `python scripts/portable/run_conformance.py --backend postgres` runs, Then every suite under `tests/conformance/catalog_backend` and `tests/conformance/documents_security` passes on PostgreSQL, the same checks pass on the in-memory implementations under plain `pytest`, and each suite's deliberately broken implementation fails at least one check.
- [ ] Optimistic concurrency: for catalog, review queue, policy, admin config and the audit tail, a replace with a stale ETag fails with the same neutral error the Cosmos implementation raises (`StaleVersionError` / `DocPreconditionFailedError` / `TailConflictError`), a replace of a missing document is distinguishable from a stale one, and every successful write returns a new ETag.
- [ ] Policy transaction: `put_principal_policy` writes the principal document and the policy head in one database transaction; Given a concurrent head change, Then the write retries exactly as `CosmosPolicyAdminRepository` does and ends in `policy_head_contended` after the same retry budget; Given a stale principal ETag, Then nothing is written (neither row changes) and the error is `policy_modified`. A fault injected between the two statements leaves both rows unchanged.
- [ ] Audit chain: `create_record` on an existing `(chain_id, sequence)` raises `SequenceTakenError`; concurrent appenders produce a gap-free, strictly increasing sequence; `query_range` returns records sorted by sequence; records read back verify through the existing chain verification, and a record altered directly in the table fails verification. UPDATE and DELETE on the audit record table are refused by the database, not only by the code.
- [ ] Revocation: a stored entry is returned until its retention expires, an `until_lifted` entry (no TTL) never expires, an expired entry reads as absent before the sweeper runs, and a store error reaches `CachedRevocationChecker` as a transient error so the existing fail-closed behaviour holds (`packages/core/tests/auth/revocation/test_fail_closed.py` passes against the PostgreSQL store).
- [ ] Isolation: every statement the collection helper builds binds the partition columns of its container; a query or point read for customer A (or domain D1) never returns a document of customer B (or domain D2) in any conformance check, including keyset paging and catalog graph traversal; a call without a partition value is refused before any SQL runs.
- [ ] No generated SQL: every statement is a fixed, parameterised template; field names come only from the existing allowlists (`catalog/repo/backend.py` `FIELDS`); a test feeds hostile field names and values and asserts refusal or parameter binding.
- [ ] Governance-core containers: the schema generator and migrations cover every container in `CONTAINERS` at execution, including the governance-core ones declared by earlier waves (`interaction_index`, `interaction_capture_policies` (PRP-102), `policy_definitions`, `policy_violations`, `policy_exceptions` (PRP-102), `notification_outbox` (PRP-102), `connector_status`, `estate_usage` (PRP-117), `ai_systems`, `risk_determinations`, `impact_assessments`, `alert_rules`, `incidents`, `attestations`, `attestation_campaigns` (PRP-127), `safety_evaluation_records` (PRP-131); `catalog_revisions` and `recommendation_feedback` likewise if declared), with the declared partition columns; a parity test fails when a declared container has no table, so `--check` has no drift. The store implementations for them are PRP-90 and PRP-91.
- [ ] Schema: `python -m neurosphere_adapters_postgres.schema --check` reports no drift between `CONTAINERS` and the versioned migrations; applying the migrations twice is a no-op; an unknown applied migration refuses startup with a reason code.
- [ ] Selecting PostgreSQL through the PRP-87 backend selector (`NS_PLATFORM` other than `azure`, resolved by `select_backends`) composes the API with every store of this PRP on PostgreSQL and the authz component ready; with the selector unset, behaviour and goldens on Azure are unchanged (existing suites and `services/api/tests/test_openapi_drift.py` pass).
- [ ] No password or DSN with credentials appears in logs, exceptions, readiness reasons or settings `repr`; outside `NS_ENV=local` a password setting is refused (credential comes from the token-provider hook, PRP-94).
- PRP exit: touched suites and the portable conformance run pass locally with output recorded, ruff, pyright, `validate_planning.py` pass; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Driver | `asyncpg`; `psycopg` 3 | `asyncpg` (design says Apache-2.0). `psycopg` 3 is LGPL-3.0 and fails the licence gate (`scripts/licenses_report.py`). Item 1 verifies the pinned version and licence row in `uv.lock`, `docs/licenses.md` and ADR-0002 from the files, nothing from memory |
| 4 | Table shape | one table per container; one shared table | One table per `ContainerSpec`: `id`, partition columns from `partition_key_paths`, `doc jsonb`, `etag text`, `expires_at timestamptz null`; primary key (partition columns, `id`) |
| 5 | Audit document column (owner decision D-7 in PRP-85) | `jsonb`; `json` | Decided by the owner 2026-11-16 (D-7 default accepted): audit records stored as `json` (text-preserving) plus extracted `chain_id`, `sequence` columns, because `jsonb` reorders keys and refuses `\u0000`; the chain must re-verify from stored bytes |
| 6 | Tenant isolation mechanism (owner decision D-7 in PRP-85) | application predicates; row-level security | Decided by the owner 2026-11-16 (D-7 default accepted): mandatory partition arguments in `PgCollection` plus a test that every built statement binds them; RLS is a follow-up defence in depth (it complicates pooled sessions) |
| 7 | Audit search on PostgreSQL | new SQL search store; existing `RepositoryAuditSearchStore` | ASSUMPTION: compose the existing `RepositoryAuditSearchStore` (`services/api/neurosphere_api/audit/search_store.py:118`) over the PostgreSQL audit store; the Protocol lives in `services/api`, which adapter packages must not import. A SQL search store is a follow-up |
| 8 | TTL | native; read filter plus sweeper | Read-time filter `expires_at IS NULL OR expires_at > now()` plus a bounded sweeper tick (design 3.2) |
| 9 | Schema migration | ORM tool; plain versioned SQL | Versioned SQL migrations generated from `CONTAINERS`, a ledger table `ns_schema_migrations`, applied by an explicit CLI step, never implicitly at request time |
| 10 | Real managed database | run now; OPEN | OPEN: RDS, Aurora, Cloud SQL and AlloyDB runs need `NS_LIVE_APPROVED=1`; handed to PRP-98 / PRP-64 |

## Context manifest

### Files to read first
- `temp/audit/multicloud-program-design.md` sections 1.1, 3.2, 4, 7 and M5 - the scope source.
- `PRPs/backlog/PRP-85-*.md` and `PRP-87-*.md` - "Interfaces provided" (port names, selector, package skeleton, pins).
- `packages/core/neurosphere_core/catalog/repo/backend.py` - `DocBackend`, `Query`, `ScopeFilter`, `FIELDS`, `DocConflictError`, `DocPreconditionFailedError`.
- `packages/core/neurosphere_core/catalog/repo/cosmos.py:147-200` - `CosmosBackend`, how the engine is built over it.
- `packages/core/neurosphere_core/auth/scope/policy_admin.py:300-336,440-580` - Protocol, error mapping, the batch and retry loop (after PRP-87 the Cosmos half lives in its own module).
- `packages/core/neurosphere_core/auth/revocation/store.py`, `cosmos_store.py` - `RevocationStore`, per-item TTL, `until_lifted` without TTL.
- `packages/core/neurosphere_core/audit/store.py`, `cosmos_store.py`, `repository.py:72-120` - port, errors, append algorithm.
- `packages/core/neurosphere_core/admin/store.py:142-345` - `AdminConfigRepository`, `AdminConfigStoreBase` abstract hooks.
- `packages/core/neurosphere_core/stores/containers.py` - `ContainerSpec`, `CONTAINERS`, `TTL_PER_ITEM`.
- `packages/core/neurosphere_core/migrations/protocols.py` - `DocumentStore`, `LedgerStore` for the document-migration runner.
- `packages/core/tests/catalog/repo_conformance.py` and `tests/integration/catalog/test_repo_cosmos.py:37-48` - the CHECKS pattern and loading by file path.

### Interfaces consumed
- PRP-85 (`neurosphere_core.platform`): `DeploymentTarget` and `Settings.platform` (`NS_PLATFORM`); `errors.AlreadyExistsError`, `PortUnavailableError`, `ErrorTranslator`; `ports.TokenProvider` (`get_token(*scopes) -> AccessToken(token: SecretStr, expires_on)`); `registry.PortName`, `BackendContext`, `BackendRegistry.register(target, port, factory)` and entry-point group `neurosphere.backends` (PRP-87 declares one entry point per adapter package); `inventory.PortSpec`/`PORTS`; `tests/architecture/boundary.py` (`ADAPTER_PATHS` includes `packages/adapters-*/**`, `asyncpg` is a `FORBIDDEN_ROOTS` entry outside them).
- PRP-87: the API composition seam (`select_backends`, `BuildContext.backends`, `ctx.port`), the Azure provider `neurosphere_core.platform.azure.register` as the reference, the split of `policy_admin.py` into Protocol and Cosmos modules (if PRP-87 cut its item 6, import `PolicyAdminRepository` from the mixed `policy_admin.py`), the entry-point stub `neurosphere_adapters_postgres.registration:register`, the neutral error-translator registry in `core/clients/errors.py`, the `packages/adapters-postgres` skeleton with `asyncpg` pinned in `uv.lock`, `docs/licenses.md` and ADR-0002, the `portable` pytest marker and its exclusion from the default `addopts`, the PostgreSQL container image pin in ADR-0002.
- Shipped: every Protocol listed under "Files to read first"; `CatalogEngine`; `RepositoryAuditSearchStore`; `CachedRevocationChecker`; error taxonomy `StaleVersionError`, `NotFoundError`, `DependencyTransientError`, `InvalidSchemaError`.

### Interfaces provided
- Package `neurosphere_adapters_postgres`: `PostgresSettings` (env prefix `NS_POSTGRES_`: `HOST`, `PORT`, `DATABASE`, `USER`, `SSLMODE`, `AUTH` = `password|token`, `PASSWORD` local only, `POOL_MAX`, `STATEMENT_TIMEOUT_MS`); `create_pool(settings, *, token_provider=None)` (the token provider supplies the password per new connection; PRP-94 fills it); `PgCollection` (point read, insert, replace-if-match, upsert, delete, bounded parameterised query, `transaction()` scoped to one partition); `schema` module (`table_for(ContainerSpec)`, migration list, `python -m neurosphere_adapters_postgres.schema [--check|--apply]`); `TtlSweeper`; `translate_pg_error`.
- Stores: `PostgresDocBackend` (catalog `DocBackend`), `PostgresReviewQueue`, `PostgresPolicyRepository`, `PostgresPolicyAdminRepository`, `PostgresRevocationStore`, `PostgresAuditStore`, `PostgresAdminConfigRepository`, plus `PostgresDocumentStore` / `PostgresLedgerStore` for the document-migration runner.
- Registration modules: `neurosphere_adapters_postgres/registration.py` (PRP-87's entry-point stub, filled here) exposes `register(registry)` (entry point `neurosphere.backends`, PRP-85 `BackendRegistry`) and `register_worker(registry)` (PRP-88 lazy table, `WorkerBackendRegistry`), each calling the same-named functions in `registry/foundation.py` (this PRP), `registry/dataplane.py` (empty stubs, owned by PRP-90) and `registry/controlplane.py` (empty stubs, owned by PRP-91).
- Conformance harness: `tests/conformance/<port>/checks.py` exporting `CHECKS` plus a `broken.py`, `tests/conformance/conftest.py` fixtures (`pg_dsn` from the compose fragment, unique schema per session); `scripts/portable/run_conformance.py` discovering `infra/compose/portable/*.yml` and `tests/conformance/*/`; workflow `.github/workflows/portable-conformance.yml`. Later PRPs add directories and fragments, never edit the script or the workflow.
- Compose fragment `infra/compose/portable/postgres.yml` (own project name `ns-portable-postgres`, host port 55432, bound to 127.0.0.1).

### Patterns to match
- CHECKS table taking a fresh implementation, loaded by file path: `packages/core/tests/catalog/repo_conformance.py:628`, `tests/integration/catalog/test_repo_cosmos.py:37-48`.
- Contract kit plus a deliberately broken implementation: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- ETag create and replace with error mapping: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Audit tail CAS: `packages/core/neurosphere_core/audit/cosmos_store.py:120-136`.
- Container registry export and drift CLI: `packages/core/neurosphere_core/stores/__main__.py`.

### Gotchas
- `jsonb` drops duplicate keys, reorders keys and rejects `\u0000` in strings; Cosmos accepts the latter. Conformance must include a document with a NUL-free but non-ASCII string and a key-order-sensitive audit record.
- `asyncpg` returns `jsonb` as text unless a codec is set; set the JSON codecs on every pooled connection in `init`, not per query.
- A replace that matches zero rows is either stale or missing: decide with the same statement (`RETURNING` plus a follow-up existence probe inside the transaction), never by a second unguarded read.
- `READ COMMITTED` is enough for a conditional `UPDATE ... WHERE etag = $n`; the policy transaction must still lock the head row (`SELECT ... FOR UPDATE`) or check it with the same conditional update, to match the Cosmos batch semantics.
- Revocations are partitioned by `principal_id` (`containers.py:101-107`), not customer; the principal id carries the customer segment. Keep the Cosmos partitioning, do not add a customer column the Protocol does not supply.
- The compose project name of the main stack is shared across worktrees; the portable fragment uses its own name and port. Within W36 this PRP holds the portable compose lane first, then PRP-92, then PRP-93. Use `127.0.0.1`.
- Registering an implementation in PRP-85's port inventory is an additive Tier-2 line (PRP-85 declares `PORTS` Tier-2 after it merges).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-postgres/neurosphere_adapters_postgres/__init__.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/registration.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/settings.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/pool.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/collection.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/errors.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/schema/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/ttl.py
  - packages/adapters-postgres/neurosphere_adapters_postgres/foundation/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/registry/**
  - packages/adapters-postgres/tests/**
  - tests/conformance/conftest.py
  - tests/conformance/__init__.py
  - tests/conformance/catalog_backend/**
  - tests/conformance/documents_security/**
  - infra/compose/portable/postgres.yml
  - scripts/portable/**
  - docs/runbooks/postgres.md
tier1:
  - .github/workflows/portable-conformance.yml
tier2_appends:
  - services/api/neurosphere_api/runtime/status.py
  - packages/core/neurosphere_core/platform/inventory.py
  - mkdocs.yml
must_not_touch:
  - packages/adapters-postgres/pyproject.toml
  - packages/adapters-postgres/neurosphere_adapters_postgres/dataplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/controlplane/**
  - packages/adapters-postgres/neurosphere_adapters_postgres/search/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/contracts/**
  - services/api/neurosphere_api/runtime/builders/**
  - pyproject.toml
  - uv.lock
  - infra/helm/**
  - docker-compose.yml
```
`registry/dataplane.py` and `registry/controlplane.py` are created here as empty stubs and handed over: after this PRP merges, PRP-90 owns the first and PRP-91 the second.

## Implementation blueprint

Parallelization: item 1 first. Items 2, 3 and 4 [P] after item 1 (disjoint files). Item 5 after 2. Item 6 after 2-5. Item 7 last.

### Item 1 - Foundation: settings, pool, collection helper, schema, migrations, compose fragment
- Deliverable: first step, record in the PR description the `asyncpg` version and licence as found in `uv.lock`, `docs/licenses.md` and ADR-0002 (if absent, stop and add a `[serial-after: PRP-87]` dependency item; do not edit `uv.lock` here). Then `PostgresSettings`, `create_pool` with the token-provider hook and JSON codecs, `PgCollection` (partition arguments mandatory, fixed parameterised templates, keyset paging, single-partition `transaction()`), `translate_pg_error` into the PRP-85 neutral errors, the `schema` package (tables generated from `CONTAINERS`, versioned migrations, `ns_schema_migrations` ledger, `--check`/`--apply` CLI, audit table with `json` column and an UPDATE/DELETE-refusing trigger), `TtlSweeper`, `PostgresDocumentStore`/`PostgresLedgerStore`, the compose fragment.
- Owned files: `settings.py`, `pool.py`, `collection.py`, `errors.py`, `schema/**`, `ttl.py`, `infra/compose/portable/postgres.yml`, `packages/adapters-postgres/tests/test_collection.py`, `test_schema.py`, `test_settings.py`.
- Must NOT touch: `containers.py`, `pyproject.toml` files, `uv.lock`.
- Depends on: PRP-85, PRP-87 merged.
- Acceptance criteria: criteria 6, 7, 8 and 10 at helper level; password refused outside local; DSN never in `repr`; a statement builder test enumerates every template and asserts partition placeholders.
- Tests: `packages/adapters-postgres/tests/` (unit, no database) plus `tests/conformance/documents_security/test_collection_postgres.py` (marker `portable`).
- Pattern references: `stores/__main__.py`, `mcp/cosmos_store.py:86-140`.

### Item 2 - Conformance harness and the catalog backend  [P]
- Deliverable: `tests/conformance/conftest.py` (database fixture, unique schema per run), `scripts/portable/run_conformance.py` (discovers fragments and suites, brings one fragment up, runs `pytest -m portable` on the matching directories, tears down), `tests/conformance/catalog_backend/` reusing `repo_conformance.CHECKS` by file path against `CatalogEngine` over `PostgresDocBackend` for both `PartitionKeyShape` values, plus a broken backend that ignores `if_match`; `PostgresDocBackend` in `foundation/catalog.py`.
- Owned files: `foundation/catalog.py`, `tests/conformance/conftest.py`, `tests/conformance/__init__.py`, `tests/conformance/catalog_backend/**`, `scripts/portable/**`.
- Must NOT touch: `packages/core/tests/catalog/repo_conformance.py` (load it, do not fork it).
- Depends on: item 1.
- Acceptance criteria: all catalog CHECKS pass on PostgreSQL and in-memory; the broken backend fails `check_stale_etag`; graph budgets suite (`packages/core/tests/catalog/test_graph_scope.py` checks reused where they take a repository) shows no cross-domain edge.
- Tests: `tests/conformance/catalog_backend/test_inmemory.py`, `test_postgres.py`, `test_broken.py`.
- Pattern references: `tests/integration/catalog/test_repo_cosmos.py:37-48`.

### Item 3 - Policy, policy administration and revocation  [P]
- Deliverable: `foundation/policy.py` (`PostgresPolicyRepository`, `PostgresPolicyAdminRepository` with the one-transaction write and the same retry and error reasons), `foundation/revocation.py` (`PostgresRevocationStore`, `expires_at` from retention, none for `until_lifted`); new shared suites `tests/conformance/documents_security/policy_checks.py` and `revocation_checks.py` run on in-memory, Cosmos (`integration` marker) and PostgreSQL, each with a broken implementation (non-atomic write; ignores expiry).
- Owned files: `foundation/policy.py`, `foundation/revocation.py`, `tests/conformance/documents_security/{policy,revocation}_*.py`.
- Must NOT touch: core policy and revocation modules.
- Depends on: item 1.
- Acceptance criteria: criteria 3 and 5; a fault-injection test aborts between the two statements and asserts both rows unchanged; customer A cannot read customer B's head or principal.
- Tests: the files above; re-run `packages/core/tests/admin/test_policy_admin.py`, `packages/core/tests/auth/revocation` with the PostgreSQL store through their existing fixtures where they accept a store.
- Pattern references: `policy_admin.py:530-580`, `auth/revocation/cosmos_store.py:88-160`.

### Item 4 - Audit chain and admin config  [P]
- Deliverable: `foundation/audit.py` (`PostgresAuditStore`: unique `(chain_id, sequence)`, tail row with ETag CAS, range query ordered by sequence), `foundation/admin_config.py` (`PostgresAdminConfigRepository` implementing the `AdminConfigStoreBase` hooks); shared suites `audit_checks.py` (concurrent append with 20 writers, tamper detection through the existing chain verification, refused UPDATE/DELETE) and `admin_config_checks.py`, each with a broken implementation.
- Owned files: `foundation/audit.py`, `foundation/admin_config.py`, `tests/conformance/documents_security/{audit,admin_config}_*.py`.
- Must NOT touch: `packages/core/neurosphere_core/audit/**`, `admin/**`.
- Depends on: item 1.
- Acceptance criteria: criteria 2 and 4; audit search through `RepositoryAuditSearchStore` over the PostgreSQL store returns the same pages as over the in-memory store.
- Tests: the files above.
- Pattern references: `audit/store.py:74-165` (in-memory twin with `simulate_overwrite`), `admin/store.py:348-400`.

### Item 5 - Review queue
- Deliverable: `foundation/review_queue.py` (`PostgresReviewQueue`), run through the existing shared contract `packages/core/tests/review_queue_cosmos/contract.py` loaded by file path.
- Owned files: `foundation/review_queue.py`, `tests/conformance/documents_security/review_queue_*.py`.
- Depends on: item 2 (harness).
- Acceptance criteria: the existing contract passes on PostgreSQL; enqueue is idempotent per item id; scope isolation by customer and domain.
- Tests: `tests/conformance/documents_security/test_review_queue_postgres.py`.
- Pattern references: `catalog/review_queue_cosmos.py:131`.

### Item 6 - Registration and composition
- Deliverable: `registration.py` (PRP-87's entry-point stub) exposes `register` and `register_worker`, each calling the same-named functions of `registry/foundation.py`, `registry/dataplane.py` and `registry/controlplane.py`; `registry/foundation.py` registers every store of this PRP through `BackendRegistry.register(target, PortName..., factory)` for `aws`, `gcp` and `kubernetes` (Azure keeps Cosmos); `registry/dataplane.py` and `registry/controlplane.py` stubs; an optional `postgres` readiness component (`runtime/status.py` Tier-2 append) reporting `postgres_unavailable`, `postgres_schema_drift`, `postgres_auth_missing` reason codes; the sweeper started and stopped with the composition lifetime.
- Owned files: `registration.py`, `registry/**`, `foundation/__init__.py`, `packages/adapters-postgres/tests/test_registration.py`; Tier-2 line in `runtime/status.py`.
- Must NOT touch: `runtime/builders/**` (if the seam cannot register a store without a builder edit, add a `[serial-after: PRP-87]` item and report it).
- Depends on: items 2-5.
- Acceptance criteria: criterion 9; API composed against the compose PostgreSQL with `NS_ENV=local` boots, `/readyz` ready, an authenticated catalog read and an audited admin write succeed; with the selector unset, `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data` pass unchanged.
- Tests: `packages/adapters-postgres/tests/test_registration.py`, `tests/conformance/documents_security/test_composed_api_postgres.py` (marker `portable`).
- Pattern references: the PRP-87 Azure provider (`neurosphere_core.platform.azure.register`).

### Item 7 - Integration and close-out
- Deliverable: `.github/workflows/portable-conformance.yml` (calls `scripts/portable/run_conformance.py`, `workflow_dispatch` plus path-filtered pull requests, no `|| true`); `docs/runbooks/postgres.md` (settings, schema apply, TTL sweeper, what is OPEN) and its `mkdocs.yml` nav line; port inventory lines if Tier-2; rebase, Tier-3 regeneration; `changelog.d/PRP-89-postgres-foundation-catalog-and-security-stores.md`; completion note with env vars and the product check.
- Owned files: the workflow, the runbook, Tier-2 lines, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; the portable workflow run is green on the PR.

## Cut line
Items 1-4, 6 and 7 are the minimum ship: the foundation, the conformance harness and the stores authorization depends on (catalog, policy, policy administration, revocation, audit, admin config) are never cut, and PRP-90 and PRP-91 build on them. Item 5 (review queue) may be descoped as a unit; what remains merges safely because no other item depends on it, and on a non-Azure platform the review-queue port then reports `platform_backend_missing` (PRP-85 `PortUnavailableError`) with a follow-up issue, never a silent Cosmos fallback. PRP-96 renders only settings that exist, and PRP-98's matrix shows the cut store as `disabled: platform_backend_missing`.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/adapters-postgres/tests tests/conformance packages/core/tests/catalog packages/core/tests/admin packages/core/tests/auth packages/core/tests/audit packages/core/tests/review_queue_cosmos packages/core/tests/stores_registry services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/test_openapi_drift.py tests/security/authz
docker compose -f infra/compose/portable/postgres.yml up -d --wait
python scripts/portable/run_conformance.py --backend postgres
docker compose -f infra/compose/portable/postgres.yml down -v
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New installs only: the schema is created by `python -m neurosphere_adapters_postgres.schema --apply` before first start; there is no migration from Cosmos (OPEN). Turn off: leave the backend selector at its default (Azure/Cosmos); nothing in this PRP is reachable then. Revert: revert the PR; a PostgreSQL database created for testing is dropped with the compose fragment (`down -v`). Schema migrations are forward-only; each migration file is append-only once merged.

## Live and open gates
None run here. OPEN: RDS for PostgreSQL, Aurora PostgreSQL, Cloud SQL and AlloyDB runs; IAM database authentication (PRP-94 provides the token provider, the real run is operator-gated); performance at the original NFR scale (design section 9 item 7). Handed to PRP-98, which records them with PRP-64 and PRP-66.

## NOT building
Data-plane and control-plane stores; PostgreSQL search; row-level security; a SQL-backed audit search store; Cosmos-to-PostgreSQL data migration; Helm values or an in-cluster operator; backup and restore; native DynamoDB or Firestore adapters.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 5, 6 and 7 are ASSUMPTIONS for plan approval; rows 5 and 6 are owner decision D-7 in PRP-85; PRP-85 and PRP-87 interface names must be confirmed against their merged text)

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
- Follow-up issues:
- Product check (can an operator configure and use it without editing files or calling raw APIs?):
