---
name: PRP-41-producer-registry
status: shipped
shipped: 2026-11-15
pr: 290
priority: P0
order: 29
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-65-admin-permissions-policy-repository-and-config-store, PRP-39-identity-admin-api-and-revocation]
wave: W14
branch: prp-41-producer-registry
allow_parallel: true
issues: [235]
---

# PRP-41: Ingest producer registry (store-backed, secret shown once)

## Goal
Let an admin register, rotate and disable ingest producers through an audited API instead of hand-editing a JSON file, and make the ingest edge authenticate against that store. A producer is created with a generated secret that is returned exactly once, stored only as a SHA-256 digest, and rotated or disabled later without a redeploy. The producers file stays as a fallback layer so every existing compose, Helm and test setup keeps working. It is for the operator who today gets `503 ingest_not_configured` in every hosted environment because no profile ever sets `NS_INGEST_PRODUCERS_FILE` (lane-d step 1 and step 2), and for PRP-42 and PRP-58, which need a producer id and a place to keep its secret reference. It runs in W14 on top of PRP-37/PRP-65 (schemas, `admin_config` container) and PRP-39 (the `neurosphere_api.admin` package root).

Out of scope: connector configuration and the Key Vault secret reader (PRP-42, which owns the worker `runtime/factories.py` bodies); the console page for producers (PRP-57); enabling the store switch in the hosted, Helm and App Service profiles (PRP-58); per-producer rate-limit or source editing beyond the `sources` map; Entra-token producer auth (the seam in `ingest/auth.py` stays as is); ingest counters and reason families (PRP-46, which owns the rest of `ingest/**` one wave later).

## Why
- No producer route exists: the registry is a static JSON file named by `NS_INGEST_PRODUCERS_FILE` (`services/api/neurosphere_api/ingest/settings.py:34`, `ingest/bootstrap.py:44-63`), and unset means every ingest route is 503 (`ingest/router.py:60-63`). Compose sets it (`docker-compose.yml:163`); `infra/demo` and `infra/appservice` never do (lane-d step 1, "Ingest producer registration").
- Producer secrets are handed out "out of band" with no show-once or rotate path (`docs/validation/lane4-identity-docs-operator-setup.md:117-118`); the file format carries `secret_sha256` but nothing generates or rotates a secret.
- Internal pollers (`gateway_poll`, `billing_export`) need a producer with a known source kind; today they read a plaintext secret from env (`services/workers/neurosphere_workers/ingestion/gateway_poll/settings.py:35`, `billing_export/settings.py:48`). The registry is where those producers should come from (lane-d unit C).
- The authenticator already depends on a sync `ProducerRegistry.get` protocol (`ingest/auth.py:63-65`) with a constant-time compare and a dummy hash for unknown ids (`:84-101`), so a store-backed registry slots in without changing the wire contract.
- `main.create` runs the ingest bootstrap before `compose_app` (`main.py:30-33`); the shared Cosmos client only exists inside composition, so the store layer must attach later (`runtime/builders/edge.py:19-26` is where the ingest component is reported).

## Acceptance criteria
- [x] Given an admin holding customer-level `config.manage`, When they `POST /api/v1/admin/sources/producers` with an id, a cloud, and a `sources` map, Then the response is 201 with a `ProducerSecretIssued` body containing the secret once; a later `GET` of the same producer never contains the secret or its digest; the stored document holds only `secret_sha256`.
- [x] Given the issued secret, When a producer posts to an ingest route with `Authorization: Bearer <producer_id>.<secret>`, Then it authenticates (2xx on a valid event) within `NS_INGEST_PRODUCER_REFRESH_SECONDS` of creation on another replica and immediately on the creating replica.
- [x] Rotate returns a new secret once and the old secret is refused (401) immediately on the same replica; disable makes the producer unusable (401 `Producer credential rejected.`, same body as an unknown producer) and `enable` restores it with the current secret; both need `If-Match` and are audited.
- [x] A producer whose `cloud` differs from the deployment cloud, or whose `customer_id` differs from the caller's customer, is refused at creation (422 / 403) and nothing is stored (`Never bridge Government data to Commercial`).
- [x] Given both a store record and a file entry with the same `producer_id`, Then the store record wins; given the store unreachable, Then file producers still authenticate and store-only producers fail closed with 401 (never an allow); a store outage at startup does not stop the app and shows as a reason code, not a message.
- [x] Given `NS_INGEST_PRODUCER_STORE` unset or false and a producers file set, Then behaviour is byte-for-byte as today (existing `services/api/tests/ingest` suite passes unchanged); given neither set, ingest stays 503 `ingest_not_configured` and `/readyz` shows `composition.ingest.disabled`.
- [x] No log line, audit record, exception text, OpenAPI example or test snapshot contains a secret or a digest; audit records carry `producer_id`, source ids and a digest-free summary (CodeQL secret-name rule).
- [x] Callers without customer-level `config.manage` (including `config.manage` in an ordinary domain, viewers, auditors, expired admins) get 403 on every new route and a denial record; every new route is in the route inventories and boots under `verify_route_permissions`.
- [x] `docs/runbooks/ingest.md` documents create, show-once, rotate, disable and the file fallback, and how a producer id and secret are handed to a poller (PRP-42).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where producers live | New container; `admin_config` documents of kind `producer` | `admin_config` (PRP-37/PRP-65), `AdminConfigDocument.kind = producer`, body `ProducerRecord`, document id = `producer_id` |
| 2 | Secret handling | Store value; store digest | Generated server-side (`secrets.token_urlsafe(32)`), returned once, only `hash_secret` digest stored (A7: references or digests, never values) |
| 3 | Permission | `config.manage` in any domain; customer-level | Customer-level `config.manage` through the shipped `require_customer_control(Permission.CONFIG_MANAGE)` (`services/api/neurosphere_api/actions/customer_control.py:91`); PRP-48 later moves the check, the route code does not change |
| 4 | Store vs file | Replace the file; layer both | Layer: store first, file fallback (lane-d unit C: "file stays as a fallback") |
| 5 | Sync registry vs async store | Async authenticator; cached snapshot | ASSUMPTION: cached snapshot refreshed by a background task every `NS_INGEST_PRODUCER_REFRESH_SECONDS` (default 30) plus immediate local invalidation on writes, because `ProducerRegistry.get` is sync and PRP-46 owns the ingest service. Propagation to other replicas is bounded by the refresh interval and stated in the runbook |
| 6 | Rotation overlap | Immediate cut-over; two valid secrets for a window | ASSUMPTION: immediate cut-over. A grace window needs a second digest field in `ProducerRecord` (PRP-37/PRP-65 contract); file a follow-up if operators need it |
| 7 | When the store layer is on | Always; opt-in | ASSUMPTION: opt-in `NS_INGEST_PRODUCER_STORE=true` (default false), so a stack without the store behaves as today; PRP-58 turns it on in hosted and Helm profiles |
| 8 | Credential vocabulary | Values; references | A7: this PRP stores a digest of a secret the producer already holds; the internal pollers keep their secret in Key Vault and reference it from the connector config (PRP-42) |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/ingest/auth.py` - `ProducerRegistration`, `ProducerRegistry` protocol, `StaticProducerRegistry`, `RegisteredCredentialAuthenticator`, `hash_secret`.
- `services/api/neurosphere_api/ingest/bootstrap.py` - `configure_ingest_from_settings`, `_close_on_shutdown`; no-op when unset.
- `services/api/neurosphere_api/ingest/router.py:36-66` - `build_service(registry=...)`, `_service` 503.
- `services/api/neurosphere_api/runtime/builders/edge.py` and `main.py` - where ingest is configured and reported.
- `services/api/neurosphere_api/actions/customer_control.py:91-110` - `require_customer_control`.
- `services/api/neurosphere_api/mcp/admin/router.py:96-198` - audited admin routes with `If-Match` and `ETag`.
- `packages/core/neurosphere_core/audit/repository.py:247-270` - `run_audited_mutation`.
- `PRPs/backlog/PRP-37-contracts-revision-admin-cost-and-permissions.md` and `PRP-39-identity-admin-api-and-revocation.md` - "Interfaces provided".
- `services/api/tests/ingest/test_bootstrap.py` - producers-file test precedent; `docs/runbooks/ingest.md`.

### Interfaces consumed
- PRP-37/PRP-65: `neurosphere_contracts.admin.v1` `ProducerRecord` {`producer_id`, `customer_id`, `cloud`, `sources`, `secret_sha256`, `status` `active|disabled`, `rotated_at`} and `ProducerSecretIssued` (response only); `AdminConfigDocument`; `neurosphere_core.admin` `ADMIN_CONFIG_CONTAINER = "admin_config"`, `AdminConfigRepository` (create, get, list by kind, replace with `If-Match`, retire; monotonic `version`), `InMemoryAdminConfigRepository`, `CosmosAdminConfigRepository`, `ADMIN_KIND_MODELS`, `admin_config_chain_id(customer_id)`; `Permission.CONFIG_MANAGE`; errors `StaleVersionError`, `NotFoundError`, `DependencyTransientError`.
- PRP-39: package root `neurosphere_api.admin` (`admin/__init__.py`, `register(registry)`) and the builder pattern in `runtime/builders/admin.py`. This PRP does not edit either file; it adds its own hook line in `routers.py`.
- Shipped: `IngestService.authorize` (`ingest/service.py`), `RouterRegistry`, `run_audited_mutation`, `AUDIT_REPOSITORY` shared key, `require_customer_control`.

### Interfaces provided
- Routes under `/api/v1/admin/sources/producers`: `POST` (create, 201, `ProducerSecretIssued`), `GET` (list, bounded page), `GET /{producer_id}`, `POST /{producer_id}/rotate`, `POST /{producer_id}/disable`, `POST /{producer_id}/enable`; `ETag` on reads, `If-Match` on every mutation.
- Core: `neurosphere_core.admin.producers` - `ProducerAdmin` (create, rotate, set_status, get, list), `issue_secret()`, `registration_from_record`.
- API: `neurosphere_api.ingest.producer_store` - `ProducerStoreSettings` (`NS_INGEST_PRODUCER_STORE`, `NS_INGEST_PRODUCER_REFRESH_SECONDS`), `StoreProducerRegistry`, `LayeredProducerRegistry`.
- Component `admin_producers` (optional) in `runtime/status.py`; `app.state.admin_producers`.
- Audit operations `producer.create`, `producer.rotate`, `producer.disable`, `producer.enable` on chain `<customer>.admin-config`.
- Package `neurosphere_api.admin.sources` (`__init__.py`, one-line docstring `"""Data-source admin routes (producers, connectors)."""`); PRP-42 adds `connectors` beside `producers` and creates the identical file if it is absent at rebase.

### Patterns to match
- Opt-in bootstrap that is a no-op when unset: `ingest/bootstrap.py:44-63`.
- Admin router with `If-Match` and `ETag` and audited mutation: `mcp/admin/router.py:96-198`.
- ETag create and replace on Cosmos: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Producers-file test construction: `services/api/tests/ingest/test_bootstrap.py:46`, `tests/integration/ingestion/support.py:154`.
- Env-clearing test conftest: `services/api/tests/runtime_planes/conftest.py:8-36` (add `NS_INGEST_PRODUCER_` names to the conftests that clear `NS_INGEST_`).

### Gotchas
- `ProducerRegistry.get` is sync and runs on the request path; never call the async repository from it. Read the cached snapshot, refresh in a task owned by the composition lifetime (start in an `on_startup` hook, cancel in `on_shutdown`).
- Unknown and disabled producers must cost the same as a wrong secret: keep the `_DUMMY_HASH` branch and the single 401 body (`ingest/auth.py:84-101`).
- Test fixtures must not contain literal 64-hex digests (gitleaks `generic-api-key`, fingerprints are commit-scoped): compute digests with `hash_secret` in the test.
- `build_service` annotates `registry: StaticProducerRegistry | None` (`ingest/router.py:46`); widen it to the `ProducerRegistry` protocol, one line, or pyright fails.
- Bootstrap order: `main.create` calls the ingest bootstrap before `compose_app`; the store layer is attached by the edge builder through an `on_startup` hook. Until then the layered registry serves file entries only.
- `ProducerRegistration.sources` maps source id to `gateway|application|billing`; a billing producer must carry kind `billing` (billing_export posts `amount_kind=invoiced`).
- Same-named test directories shadow each other: new tests live in `services/api/tests/admin_producers_api` (unique).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/admin/sources/__init__.py
  - services/api/neurosphere_api/admin/sources/producers/**
  - packages/core/neurosphere_core/admin/producers/**
  - packages/core/tests/admin_producers/**
  - services/api/neurosphere_api/ingest/auth.py
  - services/api/neurosphere_api/ingest/bootstrap.py
  - services/api/neurosphere_api/ingest/producer_store.py
  - services/api/neurosphere_api/ingest/router.py
  - services/api/tests/admin_producers_api/**
  - tests/security/authz/test_admin_producers*.py
  - docs/runbooks/ingest.md
tier1:
  - services/api/neurosphere_api/runtime/builders/edge.py
  - services/api/neurosphere_api/main.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - services/api/neurosphere_api/admin/__init__.py
  - services/api/neurosphere_api/admin/identity/**
  - services/api/neurosphere_api/admin/sources/connectors/**
  - services/api/neurosphere_api/runtime/builders/admin.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/authz/dependencies.py
  - services/workers/**
  - packages/contracts/**
  - infra/**
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (core and API ingest side share no file). Item 3 after 1 and 2 needs the service; item 4 after 3; item 5 after 4; item 6 last.

### Item 1 - Producer administration in core  [P]
- Deliverable: `neurosphere_core/admin/producers/` with `issue_secret()` (token plus digest), `ProducerAdmin` over `AdminConfigRepository` (create refuses a duplicate id, rotate, `set_status`, get, list with page bound), `registration_from_record(ProducerRecord)` producing an ingest-compatible registration dict, and customer and cloud binding checks.
- Owned files: `packages/core/neurosphere_core/admin/producers/**`, `packages/core/tests/admin_producers/**`.
- Must NOT touch: PRP-37/PRP-65 modules in `neurosphere_core/admin/*.py`, ingest code.
- Depends on: PRP-37/PRP-65 merged.
- Acceptance criteria: the stored body validates as `ProducerRecord` and holds a digest only; two creations with the same id raise; a stale `If-Match` raises `stale_version`; cloud or customer mismatch raises before any write; secret has at least 256 bits of entropy and never appears in `repr` or exception text.
- Tests: `packages/core/tests/admin_producers/test_producer_admin.py`, `test_secret_hygiene.py`.
- Pattern references: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`, `ingest/auth.py:44-47`.

### Item 2 - Store-backed registry and layered authentication  [P]
- Deliverable: `ingest/producer_store.py` with `ProducerStoreSettings`, `StoreProducerRegistry` (immutable snapshot, `refresh(repository)`, `invalidate(producer_id)`), `LayeredProducerRegistry(store, fallback)`, and a refresher task; `ingest/bootstrap.py` builds the service when a file is set or `NS_INGEST_PRODUCER_STORE` is true and exposes the layered registry on `app.state`; `ingest/router.py` annotation widened; `ingest/auth.py` gains only what the layers need (disabled records are excluded from the snapshot).
- Owned files: `services/api/neurosphere_api/ingest/{auth,bootstrap,producer_store,router}.py`, `services/api/tests/admin_producers_api/test_layered_registry.py`.
- Must NOT touch: `ingest/service.py`, `ingest/settings.py`, `limits.py`, `otlp_mapping.py` (PRP-46 owns them in W15).
- Depends on: none (uses fakes until item 4).
- Acceptance criteria: store wins over file for the same id; empty store plus file behaves exactly as `StaticProducerRegistry`; refresh failure keeps the last snapshot and records a reason code, never raises into a request; an unknown id still takes the dummy-hash path; existing `services/api/tests/ingest` passes unchanged.
- Tests: `services/api/tests/admin_producers_api/test_layered_registry.py`, `test_refresh_failure.py`, plus `services/api/tests/ingest`.
- Pattern references: `ingest/bootstrap.py:44-63`, `ingest/auth.py:63-101`.

### Item 3 - Admin routes
- Deliverable: `admin/sources/producers/{router,service,models}.py` implementing the routes in "Interfaces provided"; every mutation through `run_audited_mutation` on `admin_config_chain_id`, secret never in audit payloads; `register(registry)` hook; `admin/sources/__init__.py`.
- Owned files: `services/api/neurosphere_api/admin/sources/__init__.py`, `services/api/neurosphere_api/admin/sources/producers/**`, `services/api/tests/admin_producers_api/test_routes.py`.
- Must NOT touch: `admin/__init__.py`, identity routes.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 1, 3, 4 and 7; create then rotate then disable round trip with `ETag` and `If-Match`; missing `If-Match` is `invalid_schema` reason `precondition_required`; list is bounded and never echoes digests.
- Tests: `services/api/tests/admin_producers_api/test_routes.py`, `test_show_once.py`.
- Pattern references: `mcp/admin/router.py:96-198`, `catalog/router.py:36-37`.

### Item 4 - Composition: edge builder and main
- Deliverable: edge builder builds `ProducerAdmin` over the `admin_config` repository (Cosmos on the shared client, in-memory only under `NS_ENV=local` or a backend override), attaches the store layer to the ingest registry through an `on_startup` hook, reports `admin_producers`, and invalidates the local snapshot after each write; `main.py` passes the store switch to the ingest bootstrap.
- Owned files: `runtime/builders/edge.py`, `main.py`, `runtime/status.py` (append `admin_producers`), `services/api/tests/admin_producers_api/test_producers_builder.py`.
- Must NOT touch: `runtime/builders/data.py`, `admin.py`.
- Depends on: item 3.
- Acceptance criteria: with the switch off the ingest component is exactly as before; with it on and a fake repository, a created producer authenticates; cosmos unavailable reports `admin_producers` disabled with a reason code and file producers keep working; existing `runtime_api`, `runtime_routes` and `runtime_data` suites pass.
- Tests: `services/api/tests/admin_producers_api/test_producers_builder.py`; re-run `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`, `ingest`.
- Pattern references: `runtime/builders/edge.py:17-27`, `runtime/builders/gateway.py` (shared Cosmos client, override seam).

### Item 5 - Authorization and secrecy negative suite
- Deliverable: ABAC cases for every route (no role, viewer, auditor, ordinary-domain admin, expired customer-control admin, wrong customer, wrong cloud) with denial records asserted; a leak test that runs create, rotate and a failing write and greps logs, audit payloads and exception strings for the secret and digest.
- Owned files: `tests/security/authz/test_admin_producers.py`, `tests/security/authz/test_admin_producers_secrecy.py`.
- Must NOT touch: shared harness files (`world.py`, `cases.py`) except additive helpers.
- Depends on: item 4.
- Acceptance criteria: every route has a deny case per dimension, none skipped; no secret or digest in any captured output.
- Tests: `tests/security/authz`.
- Pattern references: `tests/security/authz/test_api_paths.py`, PRP-39 `test_admin_identity.py`.

### Item 6 - Integration and close-out
- Deliverable: `routers.py` hook and the Tier-2 inventories; `docs/runbooks/ingest.md` section; rebase, regenerate Tier-3 (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`); CHANGELOG entry; completion note with env vars for the operator (`NS_INGEST_PRODUCER_STORE`, `NS_INGEST_PRODUCER_REFRESH_SECONDS`) and the product check (can an admin onboard a producer without touching a file?).
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/admin_producers services/api/tests/admin_producers_api services/api/tests/ingest services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/authz tests/security/authz tests/integration/ingestion services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator check (local, not CI): `docker compose up -d --wait`, create a producer through the API with the store switch on, post one event with the issued secret.

## Migration and rollback
No data migration: producers created through the API are new `admin_config` documents; file producers are untouched. Rollback: set `NS_INGEST_PRODUCER_STORE=false` (the store layer is not attached; file producers authenticate exactly as before) or revert the PR; leftover `admin_config` documents are inert. Rotating or disabling a producer is the incident response for a leaked secret.

## Live and open gates
None run here: all behaviour is proven on in-memory twins and, locally, the Cosmos emulator. Enabling the store layer in hosted, Helm and App Service profiles and a hosted ingest smoke are PRP-58 (deploy and the G04 run are operator-gated and handed to PRP-64).

## NOT building
Console page; per-producer rate-limit or quota editing; secret overlap window; Entra-token producers; a bulk import of the producers file; pushing a new secret to Key Vault (the operator does that, PRP-42 documents it); cross-replica instant propagation (bounded by the refresh interval).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 5, 6 and 7 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | done | prp-41-producer-registry | core ProducerAdmin, secret hygiene (9 tests) |
| 2 | done | prp-41-producer-registry | StoreProducerRegistry, LayeredProducerRegistry, bootstrap switch |
| 3 | done | prp-41-producer-registry | six routes, audited, show-once |
| 4 | done | prp-41-producer-registry | edge builder, admin_producers component, startup refresher |
| 5 | done | prp-41-producer-registry | ABAC + secrecy suites |
| 6 | done | prp-41-producer-registry | routers hook, inventory, runbook done; Tier-3 regeneration, changelog fragment and close-out done in the close-out commit |

## Completion note (filled at ship)
- Date and PR: 2026-11-15, PR #290 (issue 235).
- Deviations: `services/api/tests/runtime_api/test_readiness.py` was edited to add `composition.admin_producers.disabled` (not in the Ownership block; a required consequence of the new optional component, not another PRP's Tier-1 file). Tier-3 `openapi.json` and `docs/reference/**` were first committed on the branch and were regenerated again after merging `origin/main`. No `[serial-after]` items existed in this PRP.
- Descoped items: none. Assumptions on clarification rows 5, 6 and 7 were taken as stated (unattended run).
- OPEN gates: hosted ingest smoke and enabling the store layer in hosted, Helm and App Service profiles (PRP-58, operator-gated, G04 via PRP-64). Nothing live was run here; all behaviour is proven on in-memory twins.
- Env vars for the operator: `NS_INGEST_PRODUCER_STORE` (true to attach the store layer), `NS_INGEST_PRODUCER_REFRESH_SECONDS` (cross-replica refresh interval). `.env.example` not edited.
- Follow-up issues: (a) race in `StoreProducerRegistry.refresh` (producer_store.py): a refresh that started before an admin write can overwrite the local snapshot with pre-write state after `apply()`; fix with a write-generation counter captured before awaiting the loader. (b) `StoreProducerRegistry` loads at most `MAX_LIST_LIMIT` (1000) records per refresh; more producers silently fail closed with 401; needs pagination or a documented cap. (c) `test_only_the_issued_contract_model_mentions_a_secret_or_digest` (tests/security/authz/test_admin_producers_secrecy.py and services/api/tests/admin_producers_api/test_openapi_committed.py) only greps for `digest`; also flag `secret_sha256` in every schema except `ProducerSecretIssued`. Issue numbers not filed (unattended run).
- Reviewer follow-ups verified: the prior blocking item is fixed (openapi.json carries the six `/api/v1/admin/sources/producers` paths plus ProducerCreateRequest, ProducerPage, ProducerSourceView, ProducerView, ProducerSecretIssued; refs resolve; the only secret-shaped field is the show-once `ProducerSecretIssued.secret`). Routes all use `require_customer_control(Permission.CONFIG_MANAGE)`; If-Match is required before any write on rotate, disable and enable; audit detail is a reason code.
- Product check (can an operator use it without editing files): an admin can create, rotate, disable and enable producers through the audited API with no file edit (runbook `docs/runbooks/ingest.md`). There is no console page yet (PRP-57), so raw API calls are needed until then; the hosted profiles still need the store switch (PRP-58).
