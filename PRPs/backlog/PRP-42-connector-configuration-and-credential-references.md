---
name: PRP-42-connector-configuration-and-credential-references
status: backlog
priority: P0
order: 30
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-39-identity-admin-api-and-revocation]
wave: W14
branch: prp-42-connector-config
allow_parallel: true
issues: []
---

# PRP-42: Connector configuration with credential references

## Goal
Let an admin configure the data-collection roles (Azure Monitor and APIM gateway polling, Foundry discovery, billing export, and an OTel record) through an audited API, and make the worker roles read that configuration from the `admin_config` store with the environment as fallback. Credentials are stored as references only: a Key Vault secret URI or a managed-identity client id, never a value. The roles that need a secret (the producer secret of `gateway_poll` and `billing_export`) resolve it from Key Vault at startup with the workload identity; nothing secret is stored, logged or returned. It is for the operator who today must set 15 or more `NS_GATEWAY_POLL_*`, `NS_FOUNDRY_DISCOVERY_*` and `NS_BILLING_EXPORT_*` variables per profile and still gets idle roles because no profile sets them (lane-d step 2), and for PRP-57 (console) and PRP-58 (hosted wiring). It runs in W14 on PRP-37 and PRP-39, in parallel with PRP-41, which owns the API ingest auth, `edge.py` and `main.py`.

Out of scope: the producer registry and generated producer secrets (PRP-41); the connector SDK and reference connectors (PRP-50, which also owns `foundry_discovery` and `billing_export` internals); the `gateway_poll` poller internals beyond its settings loader (PRP-46); the console pages (PRP-57); role, identity and RBAC wiring in hosted profiles and the G04 live run (PRP-58, PRP-64); catalog quarantine wiring in `factories.py` (PRP-43, serial after this PRP); an OTel collector deployment (it stays a compose profile; the OTel record is stored and validated, nothing consumes it yet).

## Why
- All three connector roles idle unless env is set and no profile sets it: compose has no `NS_GATEWAY_POLL_*`, `NS_FOUNDRY_DISCOVERY_*` or `NS_BILLING_EXPORT_*`; Helm `workers.roles` is empty (`infra/helm/values.yaml:150`); hosted Bicep runs seven roles without any connector role (`infra/demo/main.bicep:273`) (lane-d step 2, #220).
- Each builder starts from a settings object read only from env (`services/workers/neurosphere_workers/runtime/factories.py:1125,1179,1242`), and treats a partial configuration as a terminal `RoleConfigError`; there is no store, no API and no UI (lane-d step 1, "Connector registration with credential refs").
- The producer secret is a plaintext `SecretStr` from env (`ingestion/gateway_poll/settings.py:35`, `ingestion/billing_export/settings.py:48`); the repo has no Key Vault secret reader (`grep` for `SecretClient` in `packages/` and `connectors/` is empty) and no `azure-keyvault-secrets` dependency.
- Connector credentials "live nowhere in product" (`docs/validation/lane4-identity-docs-operator-setup.md:123`); PRP-37 defines the reference-only vocabulary (`CredentialReference`, A7).
- Gateway registrations already live in a Cosmos registry (`POST /domains/{d}/gateways`, `services/api/neurosphere_api/gateway/router.py:205`); `gateway_poll` only picks domains from it (`factories.py:1130-1136`).

## Acceptance criteria
- [ ] Given customer-level `config.manage`, When an admin `POST`s a `ConnectorConfig` of kind `gateway_poll`, `foundry_discovery`, `billing_export` or `otel`, Then it is validated by the SAME settings class the worker uses (a value the worker would refuse is a 422 with the field pointer and no stored document), stored as an `admin_config` document of kind `connector_config`, audited, and returned with an `ETag`.
- [ ] Given a request body carrying any secret-looking field, an `https` URL with userinfo or a query string, a Key Vault URI of another cloud, or a `settings` value that is not a bounded scalar, Then it is 422 and nothing is stored; a `CredentialReference` of kind `key_vault_secret` must use the deployment cloud's vault suffix, compared as DNS labels with a leading dot.
- [ ] Given a stored enabled `gateway_poll` or `billing_export` config whose `credential` is a Key Vault reference, When the worker role starts, Then it builds its settings from the stored fields, reads the producer secret from Key Vault through the workload identity (REST, no new dependency), and posts to ingest with it; env values for the same kind are ignored when a stored config exists (stored wins, A1).
- [ ] Given no stored config for a kind, a store read failure, or `NS_WORKER_CONNECTOR_CONFIG_SOURCE=env`, Then the role behaves exactly as today (existing `services/workers/tests/{gateway_poll,billing_export_role,foundry_discovery_role,worker_roles}` pass unchanged); a store failure is one structured log line with a reason code, never a startup failure.
- [ ] Given a stored config with `enabled=false`, Then the role idles with an info log and does not fall back to env for that kind; given a Key Vault read failure (403, 404, timeout), Then the role fails with `RoleConfigError("connector_credential_unavailable")` and no URI or secret in any message.
- [ ] Given a config naming `producer_id`, Then creation checks the admin store: a producer that exists with the wrong cloud, a missing source id or the wrong source kind (`gateway` for polling, `billing` for billing export) is 422; a producer absent from the store (file-based) is accepted and the response lists `producer_not_in_store` under `warnings`.
- [ ] The role-specific Government guards are unchanged: `billing_export` in Government fails `billing_export_cloud_unsupported`, gateway metrics are skipped in Government, and a stored value cannot widen them.
- [ ] No response, log line, audit payload or exception contains a secret value; `secret_uri` is never logged (CodeQL secret-name rule, PRP-37 gotcha); callers without customer-level `config.manage` get 403 and a denial record on every route.
- [ ] The routes are in the route inventories and boot under `verify_route_permissions`; `docs/runbooks/connector-config.md` explains create, the Key Vault role assignment the operator must make (Key Vault Secrets User for the worker identity), restart-to-apply, and the env fallback.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Credentials | Store values; references | A7: `CredentialReference` only (Key Vault secret URI or managed identity); the worker resolves at startup |
| 2 | Key Vault client | New `azure-keyvault-secrets` dependency; REST with the existing identity stack | ASSUMPTION: REST `GET {vault}/secrets/{name}?api-version=7.4` through `httpx` with a `DefaultAzureCredential` token (scope `https://vault.azure.net/.default`, Government `https://vault.usgovcloudapi.net/.default`), because a dependency is a Tier-1 change (`pyproject.toml`, `uv.lock`, five Dockerfiles) this PRP does not own; revisit in PRP-52 if a library is preferred |
| 3 | Stored vs env precedence | Env wins; stored wins | Stored wins per connector kind when a config exists (A1: applies on restart, no hot reload); env is the fallback and the bootstrap path |
| 4 | Gateway registration "through the same store" | Duplicate registrations into `admin_config`; keep the gateway registry as the one store | ASSUMPTION: gateways stay in the existing `gateways` container (`POST /domains/{d}/gateways`); a `gateway_poll` config only selects `domain_ids`. A second copy would drift. Flag at plan approval |
| 5 | Permission | `config.manage` in a domain; customer-level | Customer-level `config.manage` via `require_customer_control(Permission.CONFIG_MANAGE)` (`actions/customer_control.py:91`) |
| 6 | Where per-kind validation lives | Core; worker package | Worker package `connector_config/` (core must not import workers); the API imports it, as it already does for write targets (`runtime/builders/write_targets.py`) |
| 7 | OTel | Worker role; stored record only | ASSUMPTION: stored and validated (`producer_id`, `source_id` only), no consumer; the collector is a compose profile and a hosted collector is #220 follow-up work |
| 8 | Managed-identity client id | Apply everywhere; where supported | ASSUMPTION: applied to credentials this PRP builds (Key Vault reader, billing blob credential); `foundry_discovery`'s `default_token_provider` is checked in item 3 and the limit is recorded if it takes no client id |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/runtime/factories.py:1105-1300` - the three connector builders and `_tick_role`, `_noop` idle pattern, `RoleConfigError` reasons.
- `services/workers/neurosphere_workers/ingestion/{gateway_poll,billing_export,foundry_discovery}/settings.py` - the settings classes the stored config must validate against (`unconfigured`, `domains`, `domain_id_valid`, `storage_url_valid`, `parse_projects`).
- `services/workers/neurosphere_workers/ingestion/gateway_poll/producers.example.json` - producer file shape with source kinds.
- `services/workers/neurosphere_workers/runtime/settings.py:55-100` - `WorkerSettings`, `StoreSettings`, how `cfg.customer_id` and `cfg.cloud` arrive.
- `services/api/neurosphere_api/runtime/builders/gateway.py` - builder with a shared Cosmos client and override seam.
- `services/api/neurosphere_api/actions/customer_control.py:91-110`, `mcp/admin/router.py:96-198`.
- `docs/security/runbooks/key-vault-references.md` - Key Vault reference vocabulary and the Commercial/Government suffix rule.
- `PRPs/backlog/PRP-37-*.md`, `PRP-39-*.md` - "Interfaces provided"; `PRP-41-producer-registry.md` for the `admin/sources` package file.

### Interfaces consumed
- PRP-37: `ConnectorConfig` {`connector_kind` `gateway_poll|foundry_discovery|billing_export|otel`, `domain_ids`, `settings`, `credential`, `enabled`}, `CredentialReference`, `AdminConfigDocument`; `neurosphere_core.admin` `AdminConfigRepository`, `CosmosAdminConfigRepository`, `InMemoryAdminConfigRepository`, `ADMIN_KIND_MODELS`, `admin_config_chain_id`; container `admin_config`; `Permission.CONFIG_MANAGE`.
- PRP-39: package `neurosphere_api.admin` (root file not edited here).
- PRP-41 (same wave, no code dependency): documents of kind `producer` read through the repository as `ProducerRecord` for the producer-reference check.
- Shipped: `GatewayPollSettings`, `FoundryDiscoverySettings`, `BillingExportSettings`, `RoleConfigError`, `ClientLifetime.register`, `default_token_provider`, `cfg.settings.cloud_profile.login_host`.

### Interfaces provided
- Routes under `/api/v1/admin/sources/connectors`: `POST` (create), `GET` (list, optional `connector_kind`), `GET /{config_id}`, `PUT /{config_id}` (replace, `If-Match`), `POST /{config_id}/enable`, `POST /{config_id}/disable`, `DELETE /{config_id}` (retire).
- Core: `neurosphere_core.admin.connectors` - `ConnectorConfigAdmin`, `check_credential_reference(reference, cloud)`, `ConnectorKindValidator` protocol.
- Worker package `neurosphere_workers.connector_config` - `ConnectorConfigSettings` (`NS_WORKER_CONNECTOR_CONFIG_SOURCE=auto|env|store`, `NS_WORKER_CONNECTOR_CONFIG_TIMEOUT_SECONDS`), `load_stored_config(cfg, lifetime, kind)`, `resolve_gateway_poll_settings`, `resolve_foundry_discovery_settings`, `resolve_billing_export_settings`, `KeyVaultSecretReader`, per-kind validators registered for the API.
- Component `admin_connectors` (optional) in `runtime/status.py`; audit operations `connector.create`, `connector.replace`, `connector.enable`, `connector.disable`, `connector.retire`.
- Reason codes: `connector_credential_unavailable`, `connector_config_store_unavailable`, `producer_not_in_store`.

### Patterns to match
- Idle role with a logged event: `factories.py:1126-1135`; settings built from init arguments (init beats env) as in `gateway_poll/settings.py:27-32`.
- Cloud-gated disable with a reason: `factories.py:1257-1258` (`billing_export_cloud_unsupported`).
- DNS-label suffix comparison, never substring: `ingestion/billing_export/settings.py:23,86-95`.
- Admin router and audited mutation: `mcp/admin/router.py:96-198`; ETag create and replace: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Worker test fakes: `services/workers/tests/gateway_poll`, `billing_export_role`, `foundry_discovery_role`.

### Gotchas
- Do not edit `ingest/auth.py`, `ingest/bootstrap.py`, `edge.py` or `main.py` (PRP-41). Both PRPs may need `services/api/neurosphere_api/admin/sources/__init__.py`: if it is absent at rebase, create it with exactly the one-line docstring `"""Data-source admin routes (producers, connectors)."""`; identical content merges cleanly.
- Each PRP builds its own `AdminConfigRepository` over the shared Cosmos client (stateless wrapper); a later PRP may consolidate into one shared key. Do not wait for PRP-41.
- A partial stored config must fail the same way a partial env config does (`RoleConfigError`), but at API creation time as a 422, so an admin never saves a config that crashes the role.
- Secret-looking names: any `settings` key matching `secret|key|password|token` is refused even though pydantic ignores unknown keys (`extra="ignore"`).
- `GatewayPollSettings` reads `api_base_url` through an alias; construct with field names (`populate_by_name=True`) and test that env `NS_API_BASE_URL` does not leak in when a stored value exists.
- The worker image has no `az` and `.env.example` is agent-blocked: list new `NS_WORKER_CONNECTOR_CONFIG_*` names in the completion note.
- Hosted and Helm profiles do not run connector roles yet (PRP-58); local proof uses the compose emulators and in-memory twins only.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/admin/sources/connectors/**
  - services/api/neurosphere_api/runtime/builders/admin_connectors.py
  - packages/core/neurosphere_core/admin/connectors/**
  - packages/core/tests/admin_connectors/**
  - services/workers/neurosphere_workers/connector_config/**
  - services/api/tests/admin_connectors_api/**
  - services/workers/tests/connector_config_worker/**
  - tests/security/authz/test_admin_connectors*.py
  - docs/runbooks/connector-config.md
tier1:
  - services/workers/neurosphere_workers/runtime/factories.py
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
  - services/api/neurosphere_api/admin/sources/producers/**
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/runtime/builders/edge.py
  - services/api/neurosphere_api/main.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py
  - services/workers/neurosphere_workers/ingestion/billing_export/**
  - services/workers/neurosphere_workers/ingestion/foundry_discovery/**
  - connectors/**
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (core and worker package share no file). Item 3 needs 1 and 2; item 4 needs 2 and 3; item 5 after 4; item 6 last.

### Item 1 - Connector administration in core  [P]
- Deliverable: `neurosphere_core/admin/connectors/` with `ConnectorConfigAdmin` over `AdminConfigRepository` (create, replace with `If-Match`, enable, disable, retire, get, list by kind, bounded page), `check_credential_reference(reference, cloud)` (Key Vault host compared as labels with a leading dot, cloud match, no userinfo or query), secret-name and scalar bounds on `settings`, domain ids canonical for the deployment customer and cloud, and the `ConnectorKindValidator` protocol that returns normalised settings or raises with field pointers.
- Owned files: `packages/core/neurosphere_core/admin/connectors/**`, `packages/core/tests/admin_connectors/**`.
- Must NOT touch: PRP-37 modules in `neurosphere_core/admin/*.py`.
- Depends on: PRP-37 merged.
- Acceptance criteria: Government deployment refuses a `vault.azure.net` reference and the reverse; `evil-vault.azure.net` and `vault.azure.net.evil.test` are refused; secret-named settings keys refused; a stale `If-Match` raises `stale_version`; retire keeps the document readable.
- Tests: `packages/core/tests/admin_connectors/test_credential_reference.py`, `test_connector_admin.py`.
- Pattern references: `billing_export/settings.py:86-95`, `mcp/cosmos_store.py:86-140`.

### Item 2 - Worker package: stored config, Key Vault reader, settings resolution  [P]
- Deliverable: `neurosphere_workers/connector_config/` with `ConnectorConfigSettings`, a bounded-timeout loader over `CosmosAdminConfigRepository` for the worker's customer, `KeyVaultSecretReader` (REST, workload identity, host check, `SecretStr` result, no URI in errors), `resolve_*_settings(cfg, lifetime)` returning the existing settings classes built from init arguments (stored wins per kind; `enabled=false` returns an "idle" marker; no record or read failure returns the env-built object), and per-kind validators that construct the settings class to prove the stored fields are acceptable.
- Owned files: `services/workers/neurosphere_workers/connector_config/**`, `services/workers/tests/connector_config_worker/test_loader.py`, `test_keyvault_reader.py`, `test_resolve.py`.
- Must NOT touch: `factories.py` (item 4), the three `ingestion/*/settings.py` files.
- Depends on: PRP-37 merged.
- Acceptance criteria: stored config beats env and env `NS_API_BASE_URL` does not leak in; no record leaves env behaviour byte-identical; Key Vault 403, 404 and timeout map to `connector_credential_unavailable`; the reader refuses a host that is not a label-suffix match for the deployment cloud and never logs the URI or value.
- Tests: the three files above (fake `httpx.MockTransport`, no network).
- Pattern references: `factories.py:1124-1171`, `gateway_poll/settings.py:27-95`, `ingestion/billing_export/settings.py:86-95`.

### Item 3 - Admin routes
- Deliverable: `admin/sources/connectors/{router,service,models}.py` implementing the routes, validation through the item-2 validators, producer-reference check against `producer` documents, `warnings` in the response, every mutation through `run_audited_mutation` on `admin_config_chain_id`; `register(registry)` hook; `admin/sources/__init__.py` only if absent (see Gotchas).
- Owned files: `services/api/neurosphere_api/admin/sources/connectors/**`, `services/api/tests/admin_connectors_api/test_routes.py`, `test_validation.py`.
- Must NOT touch: `admin/__init__.py`, `admin/sources/producers/**`.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 1, 2, 6 and 8; a partial `billing_export` config (no `manifest_blob`) is 422 with the pointer; replace needs `If-Match`; list never contains a secret value.
- Tests: `services/api/tests/admin_connectors_api`.
- Pattern references: `mcp/admin/router.py:96-198`, `catalog/router.py:36-37`.

### Item 4 - Composition: API builder and worker factories
- Deliverable: builder module `runtime/builders/admin_connectors.py` (new, Tier-2 append in `default_builders`) that builds `ConnectorConfigAdmin` over the shared Cosmos client (in-memory twin under local or a backend override) and reports `admin_connectors`; in `factories.py` the three connector builders call `resolve_*_settings` instead of constructing settings directly, and an idle marker returns the existing `_noop` role.
- Owned files: `services/api/neurosphere_api/runtime/builders/admin_connectors.py` (new), `services/workers/neurosphere_workers/runtime/factories.py` (`build_gateway_poll`, `build_foundry_discovery`, `build_billing_export` bodies only), `services/api/tests/admin_connectors_api/test_builder.py`, `services/workers/tests/connector_config_worker/test_factories_stored.py`.
- Must NOT touch: other builder bodies, the `BUILDERS` order, `build_actions`, `build_lifecycle`, `build_recommendations`.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 3, 4 and 5 through the real builders with fakes; with no store everything in `services/workers/tests/{gateway_poll,billing_export_role,foundry_discovery_role,worker_roles}` passes unchanged; with Cosmos unavailable `admin_connectors` reports disabled with a reason code.
- Tests: the two new files; re-run `services/api/tests/{runtime_api,runtime_routes,runtime_data,runtime_planes}`.
- Pattern references: `runtime/builders/gateway.py`, `factories.py:1124-1171`.

### Item 5 - Authorization, secrecy and Government negative suite
- Deliverable: deny cases per route (no role, viewer, auditor, ordinary-domain admin, expired control-domain admin, other customer, other cloud), a Government deployment refusing Commercial references, and a leak test over logs, audit payloads, exception text and OpenAPI examples for a created config with a Key Vault reference.
- Owned files: `tests/security/authz/test_admin_connectors.py`, `tests/security/authz/test_admin_connectors_secrecy.py`.
- Must NOT touch: shared harness files except additive helpers.
- Depends on: item 4.
- Acceptance criteria: every route has a deny case per dimension, none skipped; zero secret or vault-URI occurrences in captured output.
- Tests: `tests/security/authz`.
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 6 - Integration and close-out
- Deliverable: `routers.py` hook, `status.py` component, route inventories, `docs/runbooks/connector-config.md` and `mkdocs.yml` nav, rebase, regenerate Tier-3 files (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry, completion note with env vars (`NS_WORKER_CONNECTOR_CONFIG_SOURCE`, `NS_WORKER_CONNECTOR_CONFIG_TIMEOUT_SECONDS`) and the product check (can an admin turn on billing export without setting env?).
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green; a follow-up issue records the OTel consumer and the Key Vault SDK question.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/admin_connectors services/api/tests/admin_connectors_api services/workers/tests/connector_config_worker services/workers/tests/gateway_poll services/workers/tests/billing_export_role services/workers/tests/foundry_discovery_role services/workers/tests/worker_roles services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_planes services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: configs are new `admin_config` documents (container from PRP-37; hosted environments get it at the next deploy, PRP-58). Rollback: set `NS_WORKER_CONNECTOR_CONFIG_SOURCE=env` (the roles ignore the store) or revert the PR; stored documents are inert. With no stored config every role behaves as before, so the change is safe to ship before any profile uses it.

## Live and open gates
OPEN, not run here: a real Key Vault secret read and a real billing, Foundry or Azure Monitor call with stored config (needs `NS_LIVE_APPROVED=1`, an approved vault and identity role assignment); handed to PRP-58 for wiring and PRP-64 for the G04 live run. Local proof is in-memory twins, `httpx.MockTransport` and the compose emulators only.

## NOT building
A Key Vault client library dependency; secret creation or rotation in Key Vault; connector credential storage of any value; an OTel collector deployment or consumer; a second copy of gateway registrations; hot reload of stored config; the console pages; poller or connector behaviour changes.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 4, 7 and 8 are ASSUMPTIONS for plan approval)

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
- Product check (can an operator use it without editing files):
