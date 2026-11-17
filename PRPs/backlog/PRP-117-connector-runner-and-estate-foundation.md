---
name: PRP-117-connector-runner-and-estate-foundation
status: backlog
priority: P1
order: 117
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-09, NS-01
depends_on: [PRP-99-governance-contracts-a, PRP-42-connector-configuration-and-credential-references]
wave: W26
branch: prp-117-connector-runner-foundation
allow_parallel: true
issues: []
---

# PRP-117: Connector runner and estate foundation

## Goal
Make "add a connector" a change that touches only the connector's own directory. This PRP ships one generic worker role, `connector_runner`, that discovers every installed connector package through a Python entry point, loads the enabled `ConnectorConfig` documents PRP-42 already stores, runs each connector on its own interval with jitter and a per-config lease, and records what each one covered and how fresh it is. It scaffolds all ten estate connector packages in one Tier-1 pass (workspace members, lock, licence register, pins and the five Dockerfiles) with a `not_built` descriptor each, replaces the hand-kept conformance case list with enrolment by discovery, adds a verification-file template with a CI check that a connector cannot leave `not_built` without a recorded verification, and adds a Coverage page to the admin console. After it, PRP-118, 120 to 126 and 133 run in parallel without sharing a file. It is for the operator who wants to see what part of the AI estate is governed and what is not, and for the PRP authors who build the connectors.

Out of scope: any vendor or Microsoft API call and every real connector body (PRP-118, 120, 121, 122, 123, 124, 125, 126, 133 each own their directory); the contract enum values (PRP-99 adds `generic` and the ten kinds; PRP-110 adds the `usage-report` and `shadow-ai-finding` schemas); capture of content (PRP-103); the Bedrock connector (PRP-62, which this PRP unblocks); Helm, Bicep and compose role lists and hosted enabling (PRP-109, PRP-63); a hot reload of configuration (A1: applies on restart, as PRP-42 decided).

## Why
- Scheduling is hard-wired per kind. The role table is a fixed tuple of eleven names (`services/workers/neurosphere_workers/runtime/roles.py:18-30`), the three connector roles are separate builders (`runtime/factories.py:1233`, `:1289`, `:1353`) listed in `BUILDERS` (`factories.py:1867-1879`), and `connector_kind` is a closed four-value enum (`packages/contracts/schemas/admin/v1/connector-config.schema.json:25`, mirrored at `packages/contracts/python/neurosphere_contracts/admin/v1/connector_config.py:42`). A new connector today means a contract change, a role, a builder and a Dockerfile edit.
- A new workspace package is a shared-file change: the root `pyproject.toml` lists each member twice (`:31-37`, `:46-51`), `uv.lock` records it, `docs/licenses.md` carries a first-party row per member (`docs/licenses.md:88-89`), `docs/adr/0002-stack-pins.md` too (`:184-185`), and each of the five `uv --frozen` images copies members by directory (`services/api/Dockerfile:20-25`, the `.dev` twin `:18-23`, `services/workers/Dockerfile:20-25`, its `.dev` twin, `scripts/sandbox/Dockerfile.seed:19-24`). Four connector PRPs in one wave would each edit all of those.
- The conformance suite breaks when a package is added: `tests/unit/connector_conformance/test_reference_connectors_conformance.py:235-238` asserts the parametrized case ids equal every `connectors/reference/*/pyproject.toml` directory, and the cases are hand-written lists (`:175-185`). PRP-62 (W30) adds `connectors/reference/aws-bedrock` and forbids itself from editing that file, so the two PRPs conflict (design section 6).
- Coverage reporting exists in the SDK (`HealthTracker`, `CoverageReport`, `FreshnessReport` in `connectors/sdk-python/neurosphere_connector/health.py`) but nothing persists or shows it; `docs/connectors/coverage.md` is hand-written and four NS-09 targets are "not built" or "GAP" there. `docs/PRD.md` NS-09: "Publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent." Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool" and every identified gap planned; the design's G-e names this as the main structural obstacle.
- Stored configuration already carries the right shape (`ConnectorConfig`: `connector_kind`, `domain_ids`, bounded scalar `settings`, `credential` by reference, `enabled`) and the worker already resolves a Key Vault secret from it (`connector_config/resolve.py:111-130`, `_secret`), but the admin service allows one active config per kind (`packages/core/neurosphere_core/admin/connectors/service.py:14`, `_one_per_kind` at `:182-196`) and validates through a fixed table (`connector_config/validators.py:87-93`).

## Acceptance criteria
- [ ] Given the ten scaffolded packages and no stored config, When the worker runs `NS_WORKER_ROLES=connector_runner`, Then the role idles with one info log and reports no failure; `all` includes it; `parse_roles("connector_runner")` is accepted and the pinned role tuple test lists it.
- [ ] Given a stored enabled `ConnectorConfig` whose kind has a discovered descriptor with status `built`, When the interval elapses, Then the connector's `collect` runs once per interval plus bounded jitter; two runner replicas never run the same config concurrently (per-config lease with expiry, tested with a fake clock and two runners).
- [ ] Given a descriptor with status `not_built`, Then the config is accepted by the API (validators registered) but the runner never calls a vendor; the status document says `not_built` with the descriptor's reason; given a config whose kind has no installed descriptor, Then the runner records `connector_not_installed` and keeps running the others.
- [ ] Given a connector that raises, times out or is rate limited, Then the runner records a reason code (never exception text), backs off for that config only, and every other config keeps its schedule.
- [ ] Given a deployment cloud the descriptor does not list in `supported_clouds`, Then the config is refused at the API (422, `connector_cloud_unsupported`) and skipped by the runner; nothing is rerouted to another cloud.
- [ ] Given a connector uses the runner's HTTP client, Then only https requests to the descriptor's `allowed_hosts` succeed (exact host or DNS-label suffix, never substring), the target is vetted with the MCP SSRF resolver, redirects to other hosts are refused, and a test proves a refused request opens no socket.
- [ ] Given a package that declares an entry in `neurosphere.connector_bindings` for its kind, When the runner starts, Then that kind's `RunContext` carries the binding's targets, `update_fields` and `upsert_edges` sinks and its extras, a binding whose entry name differs from its `kind` is refused, a kind with no binding gets the create-only `InventorySink` only, and no connector PRP needs to edit `connector_runner/**` (proved by a test binding registered from a tmp path).
- [ ] Each tick writes one `connector_status` document per config: state (`healthy|degraded|rate_limited|failing|not_built|idle`), coverage (expected, answered, unknown as null), freshness lag (null when unknown, never 0), last success, reason code, descriptor display name, verification file link. No secret, URL with userinfo or vendor body is stored (leak test greps documents, logs and audit).
- [ ] `GET /api/v1/admin/sources/coverage` returns the status documents for the caller's customer, bounded and sorted; customer-level `config.manage` only; wrong customer and no-role callers get 403 and a denial record; the route is in the route inventories.
- [ ] Conformance by discovery: adding a package with a descriptor needs no edit to `tests/unit/connector_conformance/`; the old equality test is replaced by one that compares on-disk packages with the hand-written case ids plus discovered descriptors; a deliberately broken discovered connector fails the kit.
- [ ] Verification gate: a descriptor with status other than `not_built` whose `docs/connectors/verification/<package-dir>.md` is missing, or lacks any required heading of the template, fails `scripts/connector_estate_check.py` and the pytest wrapper; a `not_built` scaffold passes without the file.
- [ ] The admin console Coverage page lists every scaffolded and built connector with state, coverage, freshness, reason and verification link, labels `not_built` and unknown values plainly, and passes the existing a11y and mock-api suites.
- [ ] Workspace and images: `uv lock --check` passes; the lock diff only adds the ten members and no third-party package (they depend on `neurosphere-connector` and `httpx`, already direct); `python scripts/licenses_report.py` passes; all five Dockerfiles copy the ten directories; `tests/release/test_dockerfiles.py` passes.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` and `docs/reference/**` regenerated; live gate recorded in "Live and open gates".

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How a connector registers | Edit a central table; entry points | Entry point group `neurosphere.connectors`; entry name equals the `connector_kind`; the object is a `ConnectorDescriptor`. Installed means copied into the image and a workspace member, so scaffolds are pre-installed by this PRP |
| 2 | One role or a role per connector | One role per kind (today); one generic role | One generic role `connector_runner` for the ten estate kinds. The three existing roles and `otel` are untouched and keep running as today |
| 3 | Which connectors the runner schedules | All; read-only | Read connectors only (`mode="read"`). Write connectors (`github-issues`, PRP-133) are reached through the action executor's `ACTION_CONNECTORS`, never scheduled |
| 4 | Where status lives | Memory; new container | ASSUMPTION: two containers declared here, `connector_status` and `estate_usage` (partition `/customer_id`), because the API process cannot see worker memory. This PRP is the Tier-1 owner of the W26 stores files (`stores/containers.py`, `cosmos-containers.json`, `cosmos-data.bicep`) for these two containers; no other W26 PRP (111, 113, 115) lists them |
| 5 | Config cardinality | One per kind (shipped rule); many | Keep one active config per kind (`service.py:14`). Decided by the owner 2026-11-16 (GD-48): one active estate connector config per vendor kind (one tenant per vendor); multi-tenant is a follow-up. Here: the follow-up changes `_one_per_kind` |
| 6 | Enum values | This PRP adds them; PRP-99 adds them | PRP-99 adds `generic`, `entra_identity`, `purview`, `unity_catalog`, `m365_copilot`, `github_copilot`, `cursor`, `openai_enterprise`, `anthropic_claude`, `entra_shadow_ai`, `github_issues` to `connector_kind` (PRP-99 schema work). This PRP only registers validators for them; `generic` is the kind for third-party packages |
| 7 | Settings validation | Per-kind code in `validators.py`; descriptor-declared | Descriptor-declared `SettingSpec` map (key, type, bound, required); one generic validator in a new module is appended to `VALIDATORS`. Connector PRPs never edit `validators.py` or `stored.py` |
| 8 | Where connector output goes | Each connector writes stores; runner-provided sinks | Runner-provided sink ports in the SDK (`UsageSink`, `InventorySink`, `EventSink`). A connector never holds a store client or a producer secret |
| 9 | User-level vendor data | Store ids; pseudonymise | Connectors receive a `Pseudonymizer` port and emit only the catalog `person_id` form; ASSUMPTION: HMAC-SHA256 with a per-config salt held as a Key Vault reference; vendor user ids, UPNs and emails never leave the connector call |
| 10 | Estate order (GD-9) | Recommended order; by licences held | Decided by the owner 2026-11-16 (GD-9): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: this PRP ships every scaffold so the order is only a merge order |
| 11 | Default for content | On; off | Off. The runner passes `content_mode="off"` in the connector context and refuses a descriptor setting named like a body field; content paths exist only through PRP-103 (the connector PRPs state how) |
| 12 | Coverage document | Edit `docs/connectors/coverage.md` per connector; generate | Generated `docs/connectors/estate-coverage.md` from descriptors and verification files, so no connector PRP edits `coverage.md`; this PRP adds one pointer line there |
| 13 | How a connector gets extra ports (a target list, entity updates, edge upserts) | A registration line per connector PRP in `connector_runner/**`; a per-kind binding hook | Per-kind binding hook. Entry point group `neurosphere.connector_bindings`; entry name equals the `connector_kind`; the object is a `ConnectorBinding` (see Interfaces provided). The runner discovers bindings at start the same way it discovers descriptors, and hands the binding's ports to that kind's `RunContext`. Connector PRPs never edit `connector_runner/**`: PRP-118 and PRP-120 write the binding modules the runner already points at (PRP-117 declares the entry points), and PRP-121 writes none |

## Context manifest

### Files to read first
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py,vault.py,contract_kit.py}` - `BaseConnector` (`:29`), `build_manifest` (`manifest.py:138`), capability literal (`:31-40`, includes `usage_reports`, `audit_events`, `catalog_discovery`), `HealthTracker`, `CredentialBroker`, `check_connector_contract` (`contract_kit.py:100`).
- `services/workers/neurosphere_workers/runtime/{roles.py,factories.py,adapters.py}` - role tuple, `BUILDERS`, `_tick_role` (`factories.py:344`), `PeriodicTick` (`adapters.py:51`).
- `services/workers/neurosphere_workers/connector_config/{loader.py,resolve.py,stored.py,validators.py,keyvault.py}` - how stored configs load and credentials resolve.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py` and the builder at `factories.py:1289-1346` - create-only catalog discovery and per-target connector construction to imitate.
- `services/workers/neurosphere_workers/actions/executor.py:185` (`_LeaseKeeper`) - lease with expiry.
- `packages/core/neurosphere_core/mcp/ssrf.py` (`vet_target`, `Resolver`) - egress vetting reused by the HTTP client.
- `packages/core/neurosphere_core/admin/connectors/service.py` - `ConnectorConfigAdmin`, `OBSERVATION_KINDS` (`:53-57`), `_one_per_kind`.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py` - socket guard (`:53-74`), cases (`:175-185`), equality test (`:235-238`).
- `connectors/reference/azure-billing/pyproject.toml` and `neurosphere_connector_azure_billing/connector.py` - per-package layout and manifest.
- `services/api/neurosphere_api/admin/sources/connectors/router.py` and `frontend/src/features/admin/sources/ConnectorsPage.tsx` - route and page patterns.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` (the `admin/v1` section), `PRPs/backlog/PRP-62-aws-bedrock-reference-connector.md` (Ownership and item 5), `docs/connectors/coverage.md`.

### Interfaces consumed
- PRP-99: `connector_kind` open-ended with the eleven new values; manifest `actions` additions; `CredentialReference` (existing). Until PRP-99 merges this PRP cannot store an estate config; the dependency is real.
- PRP-42 (shipped): `ConnectorConfig`, `ConnectorConfigAdmin(validators=...)`, `ConnectorKindValidator`, `load_stored_config`, `KeyVaultSecretReader`, reason codes `connector_credential_unavailable`, `connector_config_store_unavailable`.
- PRP-110 (W25, contracts B): `usage-report` schema (seat, active users, feature, period, declared granularity) and `shadow-ai-finding`; this PRP's `UsageSink` carries the generated model; not written yet, consumed by purpose. Names are confirmed against its merged schemas at execution.
- Shipped: `CatalogRepository` and the create-only discovery rule (`foundry_discovery/poller.py`), the ingest API with a producer (as `gateway_poll` does), `AdminConfigRepository`, `run_audited_mutation`, `require_customer_control(Permission.CONFIG_MANAGE)`.

### Interfaces provided
- SDK (new files in `connectors/sdk-python/neurosphere_connector/`): `descriptor.py` - `ConnectorDescriptor` {`kind`, `display_name`, `mode` (`read|write`), `status` (`built|not_built`), `not_built_reason`, `verification_file`, `supported_clouds`, `allowed_hosts`, `settings` (map of `SettingSpec`), `default_interval_seconds`, `min_interval_seconds`, `emits_events`, `build(ctx) -> EstateConnector`, `conformance_factory() -> EstateConnector`}; `estate.py` - `EstateConnector(BaseConnector)` with `async collect(ctx: RunContext) -> RunResult`, `NotBuiltConnector`, `RunContext` {`config`, `credentials` (`CredentialBroker`), `http` (egress-guarded `httpx.AsyncClient`), `usage`, `inventory`, `events`, `pseudonymize`, `content_mode`, `clock`, `since` watermark}, `RunResult` {`coverage`, `freshness`, `watermark`, `reason`}; `sinks.py` - `UsageSink`, `InventorySink`, `EventSink` protocols.
- Entry point group `neurosphere.connectors`; each package declares `[project.entry-points."neurosphere.connectors"] <kind> = "<module>:DESCRIPTOR"`.
- Per-kind binding hook (new SDK file `connectors/sdk-python/neurosphere_connector/binding.py`): `ConnectorBinding` {`kind`, `targets(env) -> Sequence[str]` (optional list of identities or references the connector should look up), `inventory(env) -> InventoryPorts` (optional), `extras(env) -> Mapping[str, object]` (optional named ports placed on `RunContext.extras`)}; `BindingEnvironment` {`catalog` (a bounded read view of the catalog in the worker's derived scope), `clock`, `customer_id`, `config_id`}; `InventoryPorts` {`create` (the create-only `InventorySink`), `update_fields` (`EntityFieldSink`: set named attribute fields on an existing entity, never create), `upsert_edges` (`EdgeUpsertSink`: upsert and end-date edges, the connector never holds a store client)}. Each sink applies the runner's tenancy and audit guards. A binding that needs worker-side projections lives in the worker package, so this PRP pre-declares the three known entries in `services/workers/pyproject.toml` (Tier-1 here): `entra_identity = "neurosphere_workers.projections.identity.binding:BINDING"` (written by PRP-118), `purview = "neurosphere_workers.projections.labels.binding:BINDING"` and `unity_catalog = "neurosphere_workers.projections.labels.binding:UNITY_BINDING"` (both written by PRP-120; PRP-121 supplies only the Unity normalisation rule). A binding module that does not exist yet or fails to import is recorded as `binding_unavailable` and the kind runs with the default sink, never a crash. Any other package may declare an entry in its own `pyproject.toml`. Absent a binding, the kind gets the default create-only `InventorySink` and no extras. The binding is code in the connector's own package; the runner, not the connector, constructs the sinks.
- Scaffolded packages (directory, distribution, module, kind): `entra-identity` / `neurosphere-connector-entra-identity` / `neurosphere_connector_entra_identity` / `entra_identity` (PRP-118); `purview` (`purview`, PRP-120); `unity-catalog` (`unity_catalog`, PRP-121); `m365-copilot` (`m365_copilot`, PRP-122); `github-copilot` (`github_copilot`) and `cursor` (`cursor`) (PRP-123); `openai-enterprise` (`openai_enterprise`, PRP-124); `anthropic-claude` (`anthropic_claude`, PRP-125); `entra-shadow-ai` (`entra_shadow_ai`, PRP-126); `github-issues` (`github_issues`, mode `write`, PRP-133). Distribution and module names follow the same dash and underscore forms as the directory.
- Worker package `neurosphere_workers.connector_runner`: `ConnectorRunner`, `discover_descriptors()`, `RunnerSettings` (`NS_WORKER_CONNECTOR_RUNNER_TICK_SECONDS` default 15, `NS_WORKER_CONNECTOR_RUNNER_JITTER_PERCENT` default 10, `NS_WORKER_CONNECTOR_RUNNER_MAX_CONCURRENCY` default 4, `NS_WORKER_CONNECTOR_RUNNER_LEASE_SECONDS` default 120), `build_connector_runner` role builder, `EgressGuardedTransport`, store-backed sinks. Role name `connector_runner`.
- Core: `neurosphere_core.admin.estate` - `ConnectorStatus` model, `ConnectorStatusRepository` (in-memory and Cosmos), containers `connector_status` and `estate_usage`.
- API: `GET /api/v1/admin/sources/coverage`; package `neurosphere_api.admin.sources.coverage`; optional component `admin_coverage`.
- Docs and checks: `docs/connectors/verification/_TEMPLATE.md` (required headings: Source URLs and retrieval date; Endpoints or reports found; Permissions and admin roles; Licence or plan required; Fields used; Latency and granularity; Rate limits; Cloud availability; Content fields present and dropped; Degradation if absent; Fixtures recorded), `scripts/connector_estate_check.py`, generated `docs/connectors/estate-coverage.md`.
- Rule for later connector PRPs: see "Shared-file rules for the connector wave" in Gotchas.

### Patterns to match
- Idle role with a logged event and a terminal `RoleConfigError`: `factories.py:1233-1282`.
- Create-only catalog discovery with collision counting: `ingestion/foundry_discovery/poller.py`.
- Lease with expiry: `workers/actions/executor.py:185`; optimistic concurrency on Cosmos: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- DNS-label suffix comparison, never substring: `ingestion/billing_export/settings.py:23,86-95`.
- Optional component with a reason code: `services/api/neurosphere_api/runtime/builders/edge.py:17-27`.
- Admin router, `ETag`, audited mutations: `mcp/admin/router.py:96-198`; list page with strings table: `frontend/src/features/admin/sources/ConnectorsPage.tsx`, `strings.ts`, `hooks.ts`.
- Socket guard in connector tests: `test_reference_connectors_conformance.py:53-74`.

### Gotchas
- The scaffolds must not add a third-party dependency; a connector that needs a vendor SDK becomes its wave's lockfile owner (design section 2.5) and says so in its own PRP. All four of 122-124 use `httpx`, already a direct dependency (`pyproject.toml:21`).
- Entry points are read at process start from installed metadata; a package copied into an image but not listed in `services/workers/pyproject.toml` (and the root file) is not installed. `uv sync --frozen --package neurosphere-workers` installs only what that package reaches: `otel-generic` is a lock member absent from every Dockerfile because nothing reaches it. Add the ten to `services/workers/pyproject.toml` and copy them into all five images (safe superset); run the image builds if Docker is available, otherwise report the images unverified.
- `ConnectorConfig.settings` refuses names matching `secret|passw|pwd|token|key|sas|signature|credential|connection` (schema `propertyNames`); a `SettingSpec` key such as `api_key` or `tenant_token` is therefore impossible. Use `tenant_id`, `organization_id`, `enterprise_slug`, `workspace_id`.
- `services/workers/tests/worker_roles/test_roles.py:20` pins the role tuple, and `parse_roles("all")` is compared with `ROLE_NAMES`; update both. Hosted and Helm role lists (`infra/demo/main.bicep`, `infra/helm/values.yaml:200-202`) are not edited here; PRP-109 and PRP-63 own them.
- Helm egress is by CIDR only (`infra/helm/values.yaml:147-183`, `egressAllowlist: []`); the runner's host allowlist is an application control and does not open the network. Operators must allow vendor egress separately; this is documented in the runbook and is not a claim of connectivity.
- `ConnectorConfigAdmin` allows one active config per kind. A second tenant for the same vendor is refused with `connector_kind_exists`; say so in the runbook.
- Adding `connector_runner` to the API's component set is not needed (the role lives in the worker); the API only gains the optional `admin_coverage` component, which breaks tests pinning `default_builders` and the component set (`services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`): update the expected lists.
- The conformance factories must build with fakes only; the socket guard fails any non-loopback connect.
- Shared-file rules for the connector wave (binding on PRP-118, 120 to 126, 133): they may edit only `connectors/reference/<their dir>/**` (including `tests/fixtures/**`), their own `docs/connectors/verification/<package-dir>.md`, and a changelog fragment. A connector that needs a target list, entity-field updates or edge upserts provides the `ConnectorBinding` module that an entry point in the `neurosphere.connector_bindings` group already names (Clarification 13) and never edits `connector_runner/**`. They must not touch `pyproject.toml`, `uv.lock`, `services/workers/pyproject.toml`, any Dockerfile, `docs/licenses.md`, `docs/adr/0002-stack-pins.md`, `tests/unit/connector_conformance/**`, `docs/connectors/coverage.md`, `docs/connectors/estate-coverage.md` (regenerated at merge), `connector_config/**`, `runtime/**`, `packages/contracts/**` or another connector's directory. A connector that needs a vendor SDK takes the lockfile for its wave by a `[serial-after]` item and the orchestrator sequences it. Their descriptor changes `status` from `not_built` to `built` only together with the verification file.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/workers/neurosphere_workers/connector_runner/**
  - services/workers/neurosphere_workers/connector_config/estate_validators.py
  - services/workers/tests/connector_runner_role/**
  - connectors/sdk-python/neurosphere_connector/descriptor.py
  - connectors/sdk-python/neurosphere_connector/estate.py
  - connectors/sdk-python/neurosphere_connector/sinks.py
  - connectors/sdk-python/neurosphere_connector/binding.py
  - connectors/sdk-python/tests/test_descriptor*.py
  - connectors/sdk-python/tests/test_binding*.py
  - connectors/reference/entra-identity/**
  - connectors/reference/purview/**
  - connectors/reference/unity-catalog/**
  - connectors/reference/m365-copilot/**
  - connectors/reference/github-copilot/**
  - connectors/reference/cursor/**
  - connectors/reference/openai-enterprise/**
  - connectors/reference/anthropic-claude/**
  - connectors/reference/entra-shadow-ai/**
  - connectors/reference/github-issues/**
  - tests/unit/connector_conformance/**
  - docs/connectors/verification/_TEMPLATE.md
  - docs/connectors/estate-coverage.md
  - docs/runbooks/connector-runner.md
  - scripts/connector_estate_check.py
  - packages/core/neurosphere_core/admin/estate/**
  - packages/core/tests/admin_estate/**
  - services/api/neurosphere_api/admin/sources/coverage/**
  - services/api/tests/admin_coverage_api/**
  - tests/security/authz/test_admin_coverage*.py
  - frontend/src/features/admin/sources/CoveragePage.tsx
  - frontend/src/features/admin/sources/coverage.test.tsx
tier1:
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
  - services/api/Dockerfile
  - services/api/Dockerfile.dev
  - services/workers/Dockerfile
  - services/workers/Dockerfile.dev
  - scripts/sandbox/Dockerfile.seed
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
tier2_appends:
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/workers/neurosphere_workers/connector_config/validators.py
  - packages/core/neurosphere_core/admin/connectors/service.py
  - services/workers/tests/worker_roles/test_roles.py
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - services/api/tests/runtime_api/test_readiness.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - docs/connectors/coverage.md
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/neurosphere_workers/connector_config/stored.py
  - connectors/reference/azure-billing/**
  - connectors/reference/azure-monitor/**
  - connectors/reference/foundry/**
  - connectors/reference/apim-gateway/**
  - connectors/reference/otel-generic/**
  - docs/connectors/verification/m365-copilot.md
  - docs/connectors/verification/github-copilot.md
  - docs/connectors/verification/cursor.md
  - docs/connectors/verification/openai-enterprise.md
  - docs/connectors/verification/anthropic-claude.md
  - docs/connectors/verification/entra-identity.md
  - docs/connectors/verification/purview.md
  - docs/connectors/verification/unity-catalog.md
  - docs/connectors/verification/entra-shadow-ai.md
  - docs/connectors/verification/github-issues.md
```
The per-connector verification files in `must_not_touch` belong to each connector PRP (the file name is the package directory name plus `.md`). A new `runtime/builders/estate.py` module (new file, API) is created here and registered with one `default_builders` line.

## Implementation blueprint

Parallelization: item 1 first (it is the Tier-1 pass). Items 2 and 5 [P] after it. Item 3 after 2. Item 4 after 2 (needs the status model). Item 6 after 4. Items 7 and 8 last.

### Item 1 - Scaffold packages, descriptor and the Tier-1 pass
- Deliverable: SDK `descriptor.py`, `estate.py` (with `NotBuiltConnector`), `sinks.py`; ten packages under `connectors/reference/<dir>/` each with `pyproject.toml` (depends on `neurosphere-connector` only, entry point, hatch wheel), `neurosphere_connector_<name>/__init__.py` exposing `DESCRIPTOR` with status `not_built`, a one-line reason naming the owning PRP, `supported_clouds`, empty `allowed_hosts`, and a valid manifest built with `build_manifest`; root and workers `pyproject.toml` members and sources, plus the three `neurosphere.connector_bindings` entries (Clarification 13); regenerated `uv.lock` and `docs/licenses.md`; ADR-0002 first-party rows; the ten `COPY` lines in all five Dockerfiles.
- Owned files: the SDK files, `connectors/reference/{ten dirs}/**` (scaffold), Tier-1 files above.
- Must NOT touch: existing reference connectors, `packages/contracts/**`.
- Depends on: PRP-99 merged (for kind names only; scaffolds do not import them).
- Acceptance criteria: the packages and Dockerfile criteria; `import` of every module succeeds; a scaffold's `NotBuiltConnector.collect` returns a result with `reason` and calls no sink.
- Tests: `connectors/sdk-python/tests/test_descriptor.py`, `uv lock --check`, `uv run pytest -q tests/release tests/unit/infra`, `python scripts/licenses_report.py` (then `git diff --stat docs/licenses.md`).
- Pattern references: `connectors/reference/azure-billing/pyproject.toml`, `docs/adr/0002-stack-pins.md:184`.

### Item 2 - Runner core  [P]
- Deliverable: `connector_runner/` with descriptor discovery (fail closed when an entry name differs from the descriptor kind), binding discovery for the `neurosphere.connector_bindings` group (same fail-closed rule; the SDK `binding.py` types; runner-built `EntityFieldSink` and `EdgeUpsertSink` beside the create-only `InventorySink`, each tenancy-checked and audited; a test binding in a tmp path proves a kind receives its targets and sinks with no edit under `connector_runner/`), the scheduler (interval from config `interval_seconds` bounded by the descriptor minimum, jitter, backoff per config), the lease, `EgressGuardedTransport`, `RunContext` assembly, `Pseudonymizer`, in-memory and store-backed sinks, status writer.
- Owned files: `services/workers/neurosphere_workers/connector_runner/**`, `packages/core/neurosphere_core/admin/estate/**`, `packages/core/tests/admin_estate/**`, `services/workers/tests/connector_runner_role/**`.
- Must NOT touch: `runtime/factories.py` bodies, `connector_config/stored.py`.
- Depends on: item 1.
- Acceptance criteria: lease, isolation, egress, cloud-refusal and status criteria; reason codes only, no exception text; nothing logged but kind, config id and reason.
- Tests: `services/workers/tests/connector_runner_role/test_scheduler.py`, `test_lease.py`, `test_egress.py`, `test_status_leak.py`, `test_binding_hook.py`; `connectors/sdk-python/tests/test_binding.py`.
- Pattern references: `workers/actions/executor.py:185`, `ssrf.py` `vet_target`, `ingestion/gateway_poll` ticking.

### Item 3 - Role wiring and generic validators
- Deliverable: `roles.py` gains `connector_runner` in `ROLE_NAMES`; `factories.py` gains one import and one `BUILDERS` line (the builder lives in `connector_runner/build.py`); `connector_config/estate_validators.py` builds a `ConnectorKindValidator` per discovered descriptor from its `SettingSpec` map, refusing unknown keys, unsupported cloud, a credential kind the descriptor does not allow, and a missing `producer_id`/`source_id` when `emits_events`; `VALIDATORS` gains one `**ESTATE_VALIDATORS` entry; `service.py` `OBSERVATION_KINDS` gains the five SaaS kinds mapped to `application`.
- Owned files: `connector_config/estate_validators.py`, `connector_runner/build.py`; Tier-2 lines in `roles.py`, `factories.py`, `validators.py`, `service.py`, `test_roles.py`.
- Must NOT touch: any existing builder body in `factories.py`, `stored.py`.
- Depends on: item 2.
- Acceptance criteria: idle, `all` and role-tuple criteria; an API create of a `not_built` kind succeeds, an unknown setting is a 422 with a pointer, a secret-shaped value is refused; existing `services/workers/tests/{gateway_poll,billing_export_role,foundry_discovery_role,worker_roles,connector_config_worker}` and `packages/core/tests/admin_connectors` pass unchanged.
- Tests: `services/workers/tests/connector_runner_role/test_role_wiring.py`, `test_estate_validators.py`, plus the suites above.
- Pattern references: `connector_config/validators.py:49-93`, `factories.py:1867-1879`.

### Item 4 - Status store and coverage API
- Deliverable: containers `connector_status` and `estate_usage` declared in `stores/containers.py`, `cosmos-containers.json`, `cosmos-data.bicep`; Cosmos and in-memory repositories; `runtime/builders/estate.py` (new) and `admin_coverage` component; `admin/sources/coverage/{router,models}.py`; route inventory lines.
- Owned files: `packages/core/neurosphere_core/admin/estate/**` (store part), `services/api/neurosphere_api/admin/sources/coverage/**`, `runtime/builders/estate.py` (new), `services/api/tests/admin_coverage_api/**`, `tests/security/authz/test_admin_coverage*.py`, the stores Tier-1 files (this PRP owns them in W26).
- Must NOT touch: `builders/data.py`, other stores.
- Depends on: item 2.
- Acceptance criteria: the coverage API, leak and authorization criteria; the container export test and `cosmos-containers.json` match.
- Tests: `services/api/tests/admin_coverage_api`, `tests/security/authz/test_admin_coverage.py`, `packages/core/tests/admin_estate`, the stores export test, `services/api/tests/{runtime_api,runtime_routes,runtime_data,authz}`.
- Pattern references: `admin/sources/producers/router.py`, `runtime/builders/edge.py:17-27`.

### Item 5 - Conformance by discovery, verification gate and generated coverage  [P]
- Deliverable: `tests/unit/connector_conformance/test_discovered_connectors_conformance.py` parametrizes over discovered descriptors (kit run on `conformance_factory()`, socket guard, a broken-variant negative case); the equality test at `:235-238` becomes "on-disk packages equal hand-written case ids plus discovered kinds" with the case lists untouched; `_TEMPLATE.md`; `scripts/connector_estate_check.py` (+ pytest wrapper) enforcing headings and file presence for non-`not_built` descriptors; generator for `docs/connectors/estate-coverage.md`; one pointer line in `docs/connectors/coverage.md`.
- Owned files: `tests/unit/connector_conformance/**`, `docs/connectors/verification/_TEMPLATE.md`, `scripts/connector_estate_check.py`, `docs/connectors/estate-coverage.md`.
- Must NOT touch: the six existing case factories' behaviour.
- Depends on: item 1.
- Acceptance criteria: conformance and verification-gate criteria; adding a package with a descriptor requires no test edit (proved by a temporary package fixture in a tmp path entry point).
- Tests: `tests/unit/connector_conformance`, `tests/unit/estate_check/test_connector_estate_check.py` (new dir `estate_check`).
- Pattern references: `test_reference_connectors_conformance.py:53-74,175-238`.

### Item 6 - Coverage page
- Deliverable: `CoveragePage.tsx`, hooks and strings, route entry, mock-api feature; plain labels for `not_built`, unknown lag and unknown coverage; link to the verification file.
- Owned files: `frontend/src/features/admin/sources/CoveragePage.tsx`, `coverage.test.tsx`; Tier-2 route lines.
- Must NOT touch: `ConnectorsPage.tsx`, Shell files.
- Depends on: item 4.
- Acceptance criteria: page criterion; keyboard and axe checks pass.
- Tests: `pnpm --filter @neurosphere/frontend test`, route-sample a11y spec.
- Pattern references: `ConnectorsPage.tsx`, `ProducersPage.tsx`.

### Item 7 - Runbook and PRP-62 hand-off
- Deliverable: `docs/runbooks/connector-runner.md` (enable the role, restart-to-apply, egress, one config per kind, reading the coverage page, how a connector PRP registers); a note in the completion record that PRP-62 now only adds its package and descriptor and must list this PRP in `depends_on`.
- Owned files: the runbook.
- Depends on: items 3 to 5.
- Acceptance criteria: the runbook states what the runner cannot do (no hot reload, no write connectors, no content).

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends (routers, builders `__init__`, status, route inventories, `test_readiness.py` expectations, frontend registries, `mkdocs.yml`), Tier-3 regeneration after rebase (`openapi.json`, `docs/reference/**`, `prp_status.py --write`, `PRPs/INDEX.md`, `prp_execution_plan.py --write`, `estate-coverage.md`), changelog fragment `changelog.d/PRP-117-connector-runner-and-estate-foundation.md`, completion note.
- Owned files: Tier-2 lines, this PRP file, Tier-3 outputs per reference section 2.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
If the session overruns, items 1, 2, 3, 5 and 7 still merge safely: the runner then keeps status in memory and logs it, the Coverage page and API (items 4 and 6) become a follow-up PRP, and the connector PRPs are unaffected because they depend on the descriptor, sinks and conformance, not on the status store.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/sdk-python/tests services/workers/tests/connector_runner_role services/workers/tests/worker_roles services/workers/tests/connector_config_worker services/workers/tests/gateway_poll services/workers/tests/billing_export_role services/workers/tests/foundry_discovery_role packages/core/tests/admin_estate packages/core/tests/admin_connectors services/api/tests/admin_coverage_api services/api/tests/admin_connectors_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/authz tests/security/authz tests/unit/connector_conformance tests/unit/estate_check tests/release tests/unit/infra services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
python scripts/connector_estate_check.py
python scripts/licenses_report.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Two new Cosmos containers (additive, empty at start) and no change to existing documents; stored configs of the four shipped kinds are untouched. Rollback: leave `connector_runner` out of `NS_WORKER_ROLES` (the role then never starts; `all` is the only way it joins by default and it idles with no estate config), or revert the PR. The ten scaffold packages are inert (`not_built`) and can stay installed. Removing a scaffold later means removing its Tier-1 lines in one PR.

## Live and open gates
None run here: scaffolds call no vendor and the runner is proven with fakes, the in-memory twins and, locally, the Cosmos emulator. Hosted enabling of the role and Key Vault grants are PRP-109 and PRP-63; each connector's live run is its own PRP and is collected by PRP-136. No `NS_LIVE_APPROVED` step is needed.

## NOT building
Any vendor connector body or API call; hot reload of configuration; several configs per kind; a scheduler for write connectors or for the three existing roles; a plugin marketplace or third-party code loading from outside installed packages (entry points only, from the image); capture of content; Government parity claims; vendor egress opening in Helm or Bicep; a claim that any `not_built` target is covered.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4, 5, 9 and 10 are ASSUMPTIONS for plan approval; row 4 uses the stores Tier-1 files this PRP owns in W26)

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
- Follow-up issues:
- Product check (can an operator see estate coverage without reading code):
