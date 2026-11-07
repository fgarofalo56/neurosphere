# Lane 1 validation: NS-01 telemetry and cost ledger, NS-07 deployment intelligence and analytics options

Date: 2026-11-06. Branch main at 7d6039b. Method: `docs/validation/RUBRIC.md`. Static trace plus targeted tests.
No `az`, no docker compose, no Azure calls. Nothing in this lane could be run against a real Azure source, so
no capability here is WORKS against real data; WORKS is only awarded where I ran a test on the real code path.

## Tests I ran (all pass; none touched real Azure or the compose emulators)

| Command | Result | Store used |
|---|---|---|
| `uv run pytest tests/integration/dashboards/test_registration.py services/workers/tests/gateway_poll services/workers/tests/worker_roles services/workers/tests/ingestion -q` | 167 passed | in-memory fakes / fake HTTP; `test_registration` builds the default app and checks routes + 503 fail-closed |
| `uv run pytest services/api/tests/ingest services/api/tests/finops_api services/api/tests/federation_api services/api/tests/deployment services/api/tests/gateway_api services/api/tests/runtime_data -q` | 257 passed | in-memory twins (`InMemoryPublisher`, in-memory ledger/gateway stores, fake ARM) |

Not run (need compose, orchestrator owns it): `tests/integration/dashboards/test_vertical_slice.py` (sandbox -> ingest edge ->
Event Hubs emulator -> normalizer -> Cosmos ledger/outbox -> aggregates -> dashboards API) and `tests/integration/real_stack/*`.
Those are the tests that would justify WORKS for the ingest-to-dashboard chain; the PRP-14 evidence says they passed in
2026-10, but I did not re-run them, so the chain is UNVERIFIED by me.

## 1. Summary table

| Capability | PRD | PRP(s) and tracker status | Class | Operator-configurable? | Evidence |
|---|---|---|---|---|---|
| Ingest edge: OTLP traces/metrics and CloudEvents push, producer auth, rate/size limits | NS-01 | PRP-07 shipped; PRP-05 backlog (but code merged) | PARTIAL | file or env only (`NS_INGEST_PRODUCERS_FILE`, hashes JSON) | `services/api/neurosphere_api/ingest/router.py:97-110`, `ingest/bootstrap.py:55-60`; 503 until file set; 257+167 tests pass on in-memory publisher |
| Producer registration (who may push, which source_ids) | NS-01 | PRP-07 | MISSING as UI/API | file only | `ingest/auth.py:58-72` `StaticProducerRegistry.from_file`; no router, no frontend feature |
| Ingestion worker role (Event Hubs -> normalize -> ledger/archive/outbox/quarantine) | NS-01 | PRP-07 shipped | PARTIAL | env only (`NS_WORKER_ROLES`, `NS_INGESTION_*`) | `services/workers/neurosphere_workers/runtime/roles.py:21-31`, `factories.py:326`; compose `docker-compose.yml:198`; hosted demo `infra/demo/main.bicep:242` |
| Real-source connector: Azure Monitor / APIM gateway logs (`gateway_poll` role) | NS-01 | PRP-09, PRP-33 (PRP-09 backlog, PRP-33 shipped) | PARTIAL | API only for gateway registration, env + file for the rest | `ingestion/gateway_poll/poller.py`, `settings.py:30-52`; never run live (G17 OPEN, `docs/RESEARCH-AND-GATES.md:39`) |
| Gateway registration (so gateway_poll has something to poll) | NS-01 | PRP-33 shipped | PARTIAL | API only (`POST /api/v1/gateways/domains/{d}/gateways`) | `gateway/router.py:205-217`; UI hooks have only the mode switch, no register form (`frontend/src/features/gateways/hooks.ts`) |
| Azure billing connector (invoiced spend) | NS-01 | PRP-09 backlog (merged) | MISSING as a running thing | none | Library only; no import outside its own tests (grep of services/packages/scripts: zero hits for `neurosphere_connector_azure_billing`) |
| Foundry discovery/usage connector (observe) | NS-01, NS-07 | PRP-09 backlog (merged) | MISSING as a running thing | none | Not imported by any service/worker/script (only `foundry_actions` is wired, for swaps) |
| Generic OTel push (collector example) | NS-01 | PRP-09 | PARTIAL | file (collector YAML) + producers file | `connectors/reference/otel-generic/collector/otel-collector.example.yaml`; tested only via `tests/integration/connectors/test_otel_generic_ingest.py` (emulators, not run) |
| Cost ledger (estimated vs invoiced, price version, null-not-zero) | NS-01 | PRP-07 shipped | PARTIAL | n/a (internal) | `ingest/service.py:345` invoiced-only-from-billing; ledger store `app.state.ledger_store` built in `runtime/builders/data.py:~245`; real Cosmos path not re-run by me |
| Price sheets / pricing | NS-01 | PRP-07 | PARTIAL | file or env only; Cosmos snapshots seed-script only | `ingestion/wiring.py:17,86` `NS_LEDGER_PRICE_TABLE_FILE`; aggregates role reads Cosmos snapshots `runtime/factories.py:300-318`, written only by `scripts/sandbox/sbx_seed_stack.py`; no API, no UI. Hosted demo bicep sets neither: estimates would be `price_unresolved` |
| Hot aggregates + Cost/Latency/Coverage dashboards | NS-01, NS-07 | PRP-14 shipped | PARTIAL | n/a | Real route `dashboards/router.py:98` reads Cosmos `aggregate_reader` (`runtime/builders/data.py:7-8`); fails closed 503 when unset (`test_registration.py`); fed only by whatever the ingest/aggregates roles processed. Playwright CI uses the mock (`frontend/tests/mock-api/server.ts:169-181`) |
| Reconciliation (coverage and variance by source) | NS-01 | PRP-14 shipped | PARTIAL | n/a | `reconciliation/router.py:39`; needs `billing`-kind observations that nothing produces in a real deployment (no billing runner) so the billing column is empty outside the sandbox |
| FinOps forecast | NS-01 | PRP-21 backlog (merged, PR 103) | PARTIAL | n/a | `finops/router.py:55`, reads `ledger_store`; `finops_api` tests pass (in-memory); `finops/sandbox_source.py` is an evidence generator |
| Federation summaries | NS-07/NS-08 | PRP-21 backlog (merged) | PARTIAL | env only (`FederationSettings`, cell_id/boundary_id) | `runtime/builders/data.py:251-290`: a single in-process local cell, endpoint `https://local-cell.invalid/` is never contacted; no way to register a remote cell |
| Deployment scan (Resource Graph) | NS-07 | PRP-08 backlog (merged, PR 43) | PARTIAL | env only (`NS_SCAN_ENABLED`) | `deploy/scan/bootstrap.py`, `settings.py:11`; default OFF and not set in `docker-compose.yml`, helm, or `infra/demo`; route 503 `scan_not_configured` (`scan/router.py:26-32`); live use only via Limitlessdata gate run |
| Deployment plan (reuse/create/skip, cost, manifest) | NS-07 | PRP-08 | PARTIAL | UI (`/deploy`) and API | `deploy/plan/router.py:34-39`, pure function over body; UI says "advisory, nothing is provisioned" (`PlanStep.tsx:128`, `strings.ts:74`) |
| IaC provisioning after plan approval | NS-07 | PRP-08 | PARTIAL | IaC only (Bicep/Helm by CLI) | `infra/bicep`, `infra/helm`, `infra/scripts/uninstall.py`; no API/UI executes IaC; manifest download only (`PlanStep.tsx:111`) |
| Capabilities matrix page | NS-07 | PRP-02/PRP-31 (31 backlog) | WORKS (static data) | n/a, read-only | `ui_adapters/capabilities.py:39` serves shipped matrix from `neurosphere_core.capabilities`; real, not mock, but is static repo data |
| Fabric/Synapse/Databricks adapters | NS-07 | PRP-11 backlog (merged, PR 63) | PARTIAL (library only, stub-tested) | none | `packages/core/neurosphere_core/analytics/{fabric,synapse,databricks}`; zero imports from `services/`; `app.state.analytics_adapter` is read (`dashboards/dependencies.py:40`) but never set anywhere; G12 OPEN (sqlite stub shims `databricks/adapter.py:23-44`) |
| Fabric lifecycle provisioner | NS-07 | PRP-08 item 6 | PARTIAL | none | `packages/core/neurosphere_core/deploy/fabric/provisioner.py`; library, no service caller found |
| Deployment registration / consent / ownership store | NS-07 | PRP-08 item 5 | PARTIAL | none | `packages/core/neurosphere_core/deploy/register/*`; no router in `services/api/neurosphere_api/deploy/` (only `scan`, `plan`) |

## 2. Per-capability notes

### 2.1 How real telemetry gets in (key question 1 and 4)

Chain, with hops:
1. Producer pushes to `POST /v1/ingest/otlp/traces`, `/otlp/metrics` or `/events` (`ingest/router.py:97-110`), bearer
   `<producer_id>.<secret>`, SHA-256 compared to a registry (`ingest/auth.py:1-12,58-72`).
2. The registry is `StaticProducerRegistry.from_file(NS_INGEST_PRODUCERS_FILE)` (`ingest/bootstrap.py:50-57`). Unset means every route
   is 503 `ingest_not_configured` (`ingest/bootstrap.py:3-5`, `docs/runbooks/ingest.md:3-9`). A producer is bound to
   customer, cloud, and a map `source_id -> gateway|application|billing`; `invoiced` cost is accepted only from `billing` sources.
3. The API publishes to Event Hubs (`ingest/publisher.py`, hub `telemetry`), the `ingestion` worker role consumes
   (`workers/.../runtime/roles.py:21`, `factories.py:326 build_ingestion`) and writes ledger/archive/outbox/quarantine.
4. `projections` and `aggregates` roles drain the outbox into catalog and hot aggregates; dashboards and reconciliation read the
   aggregates (`runtime/builders/data.py:7-14`).

What an admin can do with only the UI: nothing to start ingestion. There is no frontend feature for producers, connectors,
price sheets, or ingest status (route list in `frontend/src/app/route-manifest.json`: no ingest, connectors, pricing or admin/ingest
route; the only admin pages are `/admin/execution-control`, `/mcp-admin`, `/workspaces/admin`). The first real step is hand-writing a
producers JSON with a SHA-256 of a secret and mounting it into the api container (`docs/runbooks/ingest.md:14-20`). The compose dev stack
ships a throwaway dev producer (`infra/dev/ingest-producers.dev.json`, `docker-compose.yml:155`); Helm supports `ingest.producersFile` or
`ingest.producersConfigMap` (`infra/helm/templates/deployment.yaml:46-63`); the hosted demo bicep sets no producers file at all
(grep of `infra/demo`: no `NS_INGEST_PRODUCERS_FILE`), so ingest in the hosted demo is 503 until someone adds one. UNVERIFIED against
the deployed environment: I read Bicep only.

### 2.2 Worker roles (key question 3)

Defined in `runtime/roles.py:21-31`: `ingestion, projections, aggregates, actions, hitl_timers, lifecycle, recommendations, evaluation, gateway_poll`.
`NS_WORKER_ROLES` blank means idle (`roles.py` `parse_roles`); `all` expands to all nine (`OPT_IN_ROLES` is empty).
- Compose runs `all` (`docker-compose.yml:198`) with `NS_LEDGER_PRICE_TABLE_FILE` pointing at a synthetic price file (`:236`) and
  `NS_FOUNDRY_ENABLED/NS_APIM_ENABLED=false`. `recommendations` and `evaluation` read the sandbox directories (`NS_WORKER_REC_DATA_DIR`,
  `NS_WORKER_EVAL_DATA_DIR`), i.e. synthetic data.
- Hosted demo runs only `ingestion,projections,aggregates,actions,hitl_timers,lifecycle` (`infra/demo/main.bicep:242`): no
  `gateway_poll`, no `recommendations`, no `evaluation`. So in the hosted environment nothing polls any source.
- `gateway_poll` needs: `NS_GATEWAY_POLL_DOMAIN_IDS`, `NS_GATEWAY_POLL_PRODUCER_SECRET`, `NS_API_BASE_URL`, a producer registered in the
  api's producers file with source `apim-gateway-poll` kind `gateway` (`gateway_poll/producers.example.json`), at least one registered gateway
  (API POST), and workload identity with Log Analytics read. With none of that set it logs and idles (`factories.py:748-760`).
  Optional `NS_GATEWAY_POLL_METRICS_APP_ID` for cost-center attribution. Default interval 900 s (`settings.py:30`).
- Evidence: `services/workers/tests/gateway_poll` and `worker_roles` pass (fake HTTP/ports). No live run: G17 observe is OPEN and "live
  run NOT RUN" (`docs/RESEARCH-AND-GATES.md:39`).

### 2.3 Connectors (key question 4)

`connectors/reference/`: `apim-gateway`, `azure-billing`, `azure-monitor`, `foundry`, `foundry-actions`, `otel-generic`.
Import audit of runtime code (services, packages, scripts, infra):
- `azure_monitor`: used by `gateway_poll/poller.py` and `actions/apim_canary.py`. The only observe connector with a runtime caller.
- `apim_gateway`, `foundry_actions`: wired into the action executor (write path), not telemetry.
- `azure_billing`, `foundry` (observe), `otel_generic` (package): no runtime importer. They are libraries with unit tests; nothing
  schedules them, nothing feeds their output to the ingest API. `docs/connectors/coverage.md:24` honestly says "built" but the product has no runner.
- Consequence: invoiced/billing spend never arrives in a real deployment, so "estimated vs invoiced" and billing variance in reconciliation
  are only exercised by the sandbox generator and tests.
- The PRD NS-01 phrase "bounded polling connectors" is therefore met for APIM/Azure Monitor via `gateway_poll` only; Foundry/Azure Monitor
  for non-APIM resources, and billing, are not scheduled by anything.

### 2.4 Cost ledger and pricing

Ledger store is Cosmos, created by `runtime/builders/data.py` (`ledger_store`). Idempotency, quarantine, null-not-zero are PRP-07 contract points; the
PRP-07 review blocker (fabricated 0 retries) was reworked per its Execution state (item 6). I confirmed `ingest/service.py:345` enforces invoiced-only-from-billing.
Price sheets: ingestion role reads a JSON file (`ingestion/wiring.py:17,86`), the aggregates role reads Cosmos price snapshots refreshed every 60 s
(`runtime/settings.py:63`, `price_refresh.py`). The only writer of snapshots in the repo is the seed script (`scripts/sandbox/sbx_seed_stack.py`); there is no
API, UI, or connector to load an Azure retail-prices sheet. Without a price table every estimate is `price_unresolved` (compose comment, line 235). Hosted demo bicep sets no
price table file (grep). Operator-configurable: file/env only.

### 2.5 Dashboards, reconciliation, forecast, federation (key question 2)

All five routes are real and Cosmos-backed (`dashboards/router.py:98`, `reconciliation/router.py:39`, `finops/router.py:55`,
`federation/router.py:66,85`) and fail closed 503 when the reader/store is unset. Which data they show depends only on what the roles processed.
The frontend pages (`features/dashboards`, `reconciliation`, `finops`, `federation`, `overview`) call these routes. The mock API (`frontend/tests/mock-api/server.ts:169-181, 351`,
`features/finops.ts`, `federation.ts`, `deploy.ts`) returns fixture shapes for every one of them; PRP-14 decision D2 states CI Playwright runs against that mock and never
starts compose (`PRPs/shipped/PRP-14...md` Execution state). So page-level E2E in CI proves rendering against the mock, not against the real backend.
Federation specifically: only one in-process cell, `endpoint https://local-cell.invalid/` never contacted (`data.py:268-276`); the PRD "authorized cross-cell federation" has the client/registry code
(`federation/client.py`, `workers/federation`) but no operator path to add a cell. Class PARTIAL.
FinOps forecast reads the ledger and carries backtest actuals; it will show data only when real cost records exist (see 2.4).

### 2.6 Deployment intelligence (NS-07)

- Scan: `POST /api/v1/deploy/scan` requires `config.manage` and `NS_SCAN_ENABLED=true` (`scan/router.py:26-39`, `scan/settings.py:11`). The flag is not set in
  `docker-compose.yml`, Helm, or `infra/demo` (grep), so on every shipped config the UI's scan step gets 503 `scan_not_configured`. The scan uses
  DefaultAzureCredential (environment credential excluded outside local), so it needs a managed identity with Reader on target subscriptions, an IaC/ops step.
- Plan: pure function, no ARM call (`plan/router.py:5-6`), returns plan + manifest. UI step 3 says advisory, no apply control. Provisioning is by running Bicep/Helm yourself.
  The PRD "provision missing approved services with idempotent IaC after plan approval" is not met in-product. The "IaC generation" the brief mentions is the downloadable manifest
  (`DeploymentManifest`), not generated Bicep.
- Consent/registration/ownership: `neurosphere_core/deploy/register` (consent, guard, Cosmos store) has no API router; the scan accepts a consent object in the request body (mock `deploy.ts:35-45`).
- Capabilities page: `/api/v1/capabilities` (`ui_adapters/capabilities.py`) serves the shipped PRP-02 matrix; disabled-with-reason logic is in `features/deploy/data.ts` `rowState`. Real, but static data; availability remains a repo-maintained document, and G01 (matrix) is OPEN.
- PRP-08 R1 review: CHANGES REQUIRED, 1 blocker (uninstall RG delete cascades to unregistered live resources); tracker row shows the item as merged but check the rework is reflected (see section 4).

### 2.7 Analytics adapters

Fabric, Synapse and Databricks adapters exist as a shared `AnalyticsAdapter` contract with dialects, plan, enforcement and equivalence tests (`tests/integration/analytics`, sqlite stub shims).
No service imports them (`grep neurosphere_core.analytics services/` hits only `dashboards/analytics.py:27`, which calls `list_backends` to render a badge). `app.state.analytics_adapter`
is read but never assigned, so the dashboard `analytics` field is always `disabled`. Dashboards are served from Cosmos hot aggregates "and never need the analytics adapter" (`dashboards/analytics.py:6`).
So the backend choice (Fabric/Synapse/Databricks) at deployment has no effect on the running product; no deployment profile selects one.

## 3. What an operator cannot do today (plain words)

- Cannot start ingesting real data from the UI. There is no page to register a producer, a connector, a data source, or a price sheet.
- Cannot create an ingest producer without hand-writing a hashed-secret JSON file and mounting it into the api (then restarting it).
- Cannot get invoiced/billing costs: the Azure billing connector has no runner and nothing posts its output.
- Cannot ingest Foundry usage or non-APIM Azure Monitor/App Insights signals through any scheduled worker; only APIM gateway logs have a poller.
- Cannot register an APIM gateway from the UI (list, inspect and mode-switch only); registration is `POST` to the API.
- Cannot turn on gateway polling in the hosted environment: the demo Bicep runs six of nine roles and omits `gateway_poll`, and no producers file or poll secret is provisioned there.
- Cannot load or refresh Azure pricing from the product; price tables come from a file or the seed script.
- Cannot use the deployment scan on any shipped config without setting `NS_SCAN_ENABLED` and granting Reader on subscriptions.
- Cannot apply a deployment plan from the product; the plan is advisory and you run Bicep/Helm yourself.
- Cannot choose Fabric, Synapse or Databricks as the analytics backend in a way that changes anything running.
- Cannot add a second federation cell; federation shows only the local in-process cell.
- Cannot verify any of the above against real Azure from this lane (none of it has been run live except the Limitlessdata gate runs recorded for other gates).

## 4. Contradictions between PRP "shipped" status and reality

1. Tracker drift: PRP-05, PRP-08, PRP-09, PRP-11, PRP-21 are still `status: backlog` in `PRPs/INDEX.md` although each has all items "merged", a completion note and a PR number (#43, #45, #63, #103). The tracker undercounts shipped work; conversely it hides that PRP-09 and PRP-11 have no runtime wiring.
2. PRP-07 "shipped" (telemetry ingestion and cost ledger) is true for the edge, normalizer, ledger and tests, but the operator cannot register a producer or schedule any source other than the APIM poller. NS-01's "bounded polling connectors" is not satisfied by a shipped runner for billing or Foundry.
3. PRP-09 (four reference connectors) is "complete" with no consumer for `azure-billing`, `foundry`, `otel-generic` (package) in any service.
4. PRP-11 (analytics adapters) is complete as a library; the product never instantiates an adapter. NS-07 "choose Fabric/Synapse/Databricks backend" is a capability-matrix filter in the UI only.
5. PRP-14 "shipped" dashboards: page-level Playwright runs against the Node mock API; real-stack coverage is the emulator-gated integration tests (`test_vertical_slice.py`), which are excluded from default CI (`pyproject.toml` addopts `-m "not integration and not live"`).
6. PRP-08 plan "Provision missing approved services with idempotent IaC after plan approval": the product explicitly refuses (advisory only, `strings.ts:74`). The PRP review R1 blocker (uninstall cascade) should be re-checked against `infra/scripts/uninstall.py`; I did not.
7. PRP-21 federation: "authorized cross-cell federation summaries" are built, but the runtime composes one in-process cell.

## 5. Open questions I could not answer

- Does the ingest-to-dashboard chain still work end to end on the emulators on today's main? `tests/integration/dashboards/test_vertical_slice.py` and `real_stack` need compose; not run by me.
- Does the hosted environment have a producers file, price table or `NS_SCAN_ENABLED` set outside `infra/demo` Bicep (for example in a container app env override or Key Vault ref)? I read only the repo.
- Is the aggregates role in hosted demo reading real price snapshots? Who populated Cosmos `price_snapshots` there (seed script is the only writer found)?
- Does `GatewayPoller` produce events the live APIM diagnostics tables actually satisfy (G17 live run NOT RUN)?
- Whether `docs/runbooks/seeding.md` flow is the intended "start" for an operator (it is synthetic data) or whether a real onboarding path was planned in PRP-31 (backlog) or PRP-25.
- Whether PRP-08 R1 blocker rework landed (tracker lists the review but I did not open the follow-up row or `uninstall.py`).
