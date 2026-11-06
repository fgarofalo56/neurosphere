# Lane 3 validation: map and replay (NS-05), copilot and action plane (NS-06), APIs, MCP and integration (NS-09)

Date: 2026-11-06. Branch main at 7d6039b. Read-only on source; this is the only file written.
Method per `docs/validation/RUBRIC.md`. No docker compose, no az, no Azure calls. The compose emulators were
not started by me, so every test I ran used in-memory twins or fakes (stated per row). Anything that needs the
Cosmos emulator or a real Azure resource is marked UNVERIFIED by me, and I cite existing evidence files instead.

## Tests I ran (all against in-memory stores and fakes, not Cosmos, not Azure)

| Command | Result | What it proves |
|---|---|---|
| `uv run pytest services/api/tests/map services/api/tests/replay services/api/tests/realtime services/api/tests/copilot_api services/api/tests/reports -q` | 224 passed, 4 deselected (3m29s) | Routers, scope filtering, copilot tool loop and the 78-case injection corpus (78/78, `overscoped_retrievals=0`) run through the real FastAPI routers with a fixture/recorded model adapter and in-memory stores. No real model was called. |
| `uv run pytest services/api/tests/mcp_api services/api/tests/actions_api services/api/tests/gateway_api -q` | 304 passed (2m42s) | MCP server and admin routes, action routes, gateway routes, in-memory stores, fake ARM. |
| `uv run pytest tests/integration/actions -q` | 17 passed, 8 deselected | In-process vertical slice: draft, confirm, approve, execute, verify, rollback against a scripted `httpx.MockTransport` ARM. The 8 deselected are Cosmos-emulator tests (`integration` marker); I did not run them. |

None of this is a run against real Azure. The only real-Azure evidence is the files cited under "Key question 2".

## 1. Summary table

| Capability | PRD | PRP(s) and tracker status | Class | Operator-configurable? | Evidence |
|---|---|---|---|---|---|
| Live map (viewport API, sigma WebGL, table alternative) | NS-05 | PRP-18: tracker says backlog (PR #85 merged 2026-10-21, completion note filled, acceptance boxes unchecked) | PARTIAL | n/a for the map itself; its data comes from the catalog, which is API only (see below) | 224-test run above; `docs/evidence/G07/map/fps-run1.json` (41.8 fps mean at 2000 nodes, non-headless); `p95_emulator.json` |
| Map live updates (WebSocket deltas) | NS-05 | PRP-18 | PARTIAL | env only (`RealtimeSettings`) | Deltas are domain-level aggregate rollups, one cluster node per domain, `tokens`/`context_size` always null, `edges` empty (`realtime/source.py:1-20`). Not per-agent live activity. |
| Session replay (trace tree) | NS-05 | PRP-18 | PARTIAL | env only (`NS_ARCHIVE_*`, payload policy bodies off) | Reads the redacted ingestion archive blobs only (`replay/reader.py:1-30`). Works only after ingestion has archived real or synthetic events. Replay tests used `InMemoryTraceReader`. |
| Copilot chat (model answering) | NS-06 | PRP-19: tracker backlog (PR #87 merged 2026-10-22) | PARTIAL, and OFF by default | env only: `NS_COPILOT_MODE` etc. (`runtime/builders/copilot.py`); IaC param `copilotMode` (`infra/demo/main.bicep:224`) | With the default `disabled` every copilot route returns 503 `copilot_unconfigured`. Never run against a live model (G16 OPEN, `docs/evidence/G16/README.md`; `docs/evidence/G07/copilot/README.md` is recorded-fixture only). |
| Copilot evidence/citations tool | NS-06 | PRP-19 | MOCK-ONLY in the composed app | not configurable | The composed app never binds an evidence reader: `configure_copilot(...)` is called without one (`builders/copilot.py` `_install`), so `EmptyEvidenceReader` is used (`copilot/dependencies.py:41-50`) and evidence questions always abstain. |
| Report creation and saved dashboards | NS-06 | PRP-19 | PARTIAL | UI (save dialog from a chat turn, `/reports`) but needs a working copilot to originate; REST works without | 224-test run (in-memory report store). Cosmos store `reports/cosmos_store.py` exists; UNVERIFIED against the emulator by me. |
| Action executor (draft, confirm, approve, execute, verify, rollback) | NS-06, NS-04 | PRP-17: shipped #173 | PARTIAL | env only to enable a write target: `NS_FOUNDRY_ENABLED` + `NS_FOUNDRY_*`, `NS_APIM_ENABLED` + `NS_APIM_*` (`builders/write_targets.py:1-40`), and `actions` in `NS_WORKER_ROLES` | 17 + 304 tests (scripted ARM). One real run: `docs/evidence/G05/20261105T173214Z-foundry-swap-live.json` (PASS). With nothing configured every intent is advisory (`builders/planes.py` docstring). |
| Real Foundry model swap | NS-06 | PRP-17, G05 | WORKS once, narrowly | env only, off in compose and hosted demo (`docker-compose.yml:160,214` set `NS_FOUNDRY_ENABLED: "false"`; no `NS_FOUNDRY_*` in `infra/demo/main.bicep`) | G05 evidence JSON, one target, gpt-5-nano to gpt-5-mini, apply, read-back, rollback. I did not re-run it. |
| APIM manage (model swap via backend, budget cap, grant publish, MCP publish) | NS-06, NS-09 | PRP-34: tracker backlog (PR #149 merged); items unchecked | PARTIAL (built, never run live) | env only (`NS_APIM_ENABLED`, `NS_APIM_GATEWAY_ID`, `NS_APIM_DOMAIN_ID`); gateway registration API only | `docs/evidence/G17/` holds only `README.md`; no `manage-*.md`. G17 OPEN. 304-test run is against an in-memory APIM double. |
| APIM gateway observe (registry, inventory, usage ingestion) | NS-09, NS-01 | PRP-33: shipped #176, item 8 (live gate) unchecked | PARTIAL | Gateways page lists and switches mode (UI); registering a gateway is API only (`POST /api/v1/domains/{domain}/gateways`, `gateway/router.py:205`); no register button in `frontend/src/features/gateways/` | `docs/evidence/G17/README.md` says no observe run exists; G17 OPEN. |
| MCP server (`/mcp`) | NS-09 | PRP-22: shipped #175 | PARTIAL, OFF by default | env only: `NS_MCP_RESOURCE_SERVER_URL` plus `NS_MCP_AUDIENCES`, etc.; `/mcp` route does not exist when unset (`builders/mcp.py` docstring) | `docs/evidence/G08/prp-22-real-stack-2026-11-05.md`: composed app on emulators, local dev issuer, not a real Entra token. 304-test run. |
| MCP client / admin registry | NS-09 | PRP-22 | PARTIAL | UI + API: register, sync, approve/revoke tools (`mcp/admin/router.py:96-199`, `/mcp-admin` pages) | Registry and approval are real. Nothing consumes approved external tools: `call_tool` exists only on the connector (`mcp/client/connector.py:303`), and the copilot registry is the fixed five tools (`copilot/tools/builtin.py:418`). The client sends no outbound credentials (`builders/planes.py` docstring). |
| Connector SDK (Python, TypeScript) | NS-09 | PRP-09: tracker backlog (PR #45 merged 2026-10-17); all 6 items ticked `[x]` | PARTIAL | code only | `connectors/sdk-python`, `connectors/sdk-ts`, contract kit and manifest interop. No admin UI, no runtime plug-in loader. |
| Reference connectors | NS-09, NS-01 | PRP-09, PRP-33 | PARTIAL | see section 3 | Generic OTel push works through the ingest edge. Azure Monitor is wired only for the APIM `gateway_poll` role. Foundry discovery and billing export are libraries not called by any worker role or API route. G04 OPEN, no `docs/evidence/G04/`. |
| OpenAPI REST | NS-09 | PRP-01/29 | WORKS | n/a | `services/api/openapi.json`, drift test `services/api/tests/test_openapi_drift.py` (not re-run by me); `docs/reference/api.md`. Routes exercised by the test runs above. |
| SIEM export | NS-09 | PRP-06 (follow-up D3) | PARTIAL | env only: `NS_AUDIT_SIEM_SINK` (`none` default, `stdout`, `file`) plus `NS_AUDIT_SIEM_FILE_PATH` (`builders/data.py:321-333`) | Only stdout and a JSON-lines file. No Sentinel, Splunk or Event Hubs sink. |
| Analytics export (enterprise analytics) | NS-09 | none | MISSING | n/a | PRP-14 lists "Export to SIEM or enterprise analytics" as out of scope. Only catalog `GET /export` and `POST /import` exist (`catalog/router.py:287,303`). |
| CI/CD registration (GitHub Actions, Azure DevOps, Jenkins) | NS-09 | none; PRP-09 line 224: "not in this decomposition" | MISSING | n/a | No match for Jenkins or Azure DevOps in `services/`, `packages/`, `connectors/`, `frontend/src`. PRP-31 clarification 6 defers catalog create forms to "connectors, import and CI/CD policy checks", which do not exist. |
| Copilot page context / chat dock UI | NS-06 | PRP-19 | PARTIAL | UI exists; answers need the env config above | `frontend/src/features/copilot/`. With copilot off the dock shows "The assistant is not available in this deployment" or "unavailable right now" (`strings.ts:60-70`). |

## 2. Per-capability notes (chains)

### 2.1 Live map

Chain: route `/map`, `/map/table` (`frontend/src/app/route-manifest.json`) -> `frontend/src/features/map/MapPage.tsx` (needs a selected
domain; `domainRequired` text when none, line ~473) -> `GET /api/v1/map/domains/{domain_id}/viewport`
(`services/api/neurosphere_api/map/router.py:68`) -> `map/service.py` `build_viewport` -> `CatalogRepository` (entity scan, capped at
20 pages x 500) + `GraphQuery.neighbors` + hot aggregate status for coverage -> catalog store (Cosmos) -> entities only exist if
something wrote them. Live deltas: WebSocket `realtime/router.py:37` -> `AggregateDeltaSource` (`realtime/source.py`) reading
`AggregateReader` rollups.

What the data actually is:
- Nodes and edges are catalog entities and curated or inferred relationships. Runtime metrics per node are `null`/`unknown`
  because the aggregates are domain-level (`map/service.py` module docstring). Only `context_size` is populated.
- The "live" part is one cluster node per domain with request frequency, p95 latency and health from the latest hour bucket. It is not
  per-agent animation of observed calls. The PRD wording ("animate observed edges only", per-node size/colour for tokens, latency,
  frequency) is only partly met: per-node tokens, latency and frequency are not available.
- Seeded vs real: how entities get in. The only routes are `POST /api/v1/catalog/entities`, `POST /api/v1/catalog/import`
  (`catalog/router.py:182,287`), the catalog projection worker that infers edges from telemetry
  (`services/workers/neurosphere_workers/projections/catalog/`), and the sandbox seeder (`scripts/sandbox/sbx_seed_catalog.py`,
  `make stack-up`). No UI creates entities (PRP-31 clarification 6 defers the create/import forms). The Foundry discovery
  connector, which would populate the catalog from a customer's Foundry project, is not wired to the catalog (see 2.7).
- Mock/seed-only: `frontend/tests/mock-api/server.ts:792-1288` serves a deterministic 2000-node viewport and replay traces. That is what
  the Playwright and vitest suites use. The real API has no equivalent seed unless the sandbox seeder ran.

Answer to key question 4 (map with no seeded data): the API returns an empty node list and the page shows `No nodes in this domain yet.`
(`frontend/src/features/map/strings.ts:27`). If the user has no domain selected it shows the domain-required message. I did not load the
page in a browser (UNVERIFIED visually); this is from reading the service, the string table and the tests.

Perf evidence: `docs/evidence/G07/map/fps-run1.json` (non-headless Chromium, 41.84 mean fps, p5 29.94, 2000 nodes, 4000 edges) and
`p95_emulator.json` (event to WebSocket delta freshness against the Cosmos emulator, aggregate rollup path, Event Hubs and ingest edge
not in the loop per its README line 34). Both are sandbox/emulator numbers, labelled bounded feasibility.

Class: PARTIAL. The viewport, clustering, scope filter, WebSocket scoping and table alternative are real code with tests; the data
feeding it requires catalog population that an operator cannot do from the UI, and per-node live metrics do not exist.

### 2.2 Session replay

Chain: `/replay/traces` -> `frontend/src/features/replay/` -> `GET /api/v1/replay/domains/{domain}/traces[/{trace_id}]`
(`replay/router.py:54,74`) -> `ArchiveTraceReader` (`replay/reader.py`) -> redacted pseudonymized blobs in `ns-archive`
written by the ingestion worker's archive step (`runtime/builders/blob.py`, `data.py:402-407`). Payload bodies are off unless a
deployment opts in. No action capability on the endpoint (read only). Gaps, sampling, late spans are labelled in the assembler.
Class PARTIAL: real path exists end to end by design, but I only ran it with `InMemoryTraceReader`; blob-backed replay is UNVERIFIED by me.
Archive population needs the ingestion role to be running and fed.

### 2.3 Copilot

What happens when you open it today (key question 1): the dock renders (`frontend/src/features/copilot/CopilotDock.tsx`). Sending a
message calls `POST /api/v1/copilot/conversations`. Unless `NS_COPILOT_MODE` is `approved_endpoint` or `foundry_agent`, the builder reports
`copilot: disabled` (`runtime/builders/copilot.py` `build()`: `if settings.mode == "disabled": ctx.disabled("copilot")`), `app.state` has no
`copilot_model_adapter`, and `get_copilot` raises `DependencyTransientError(reason="copilot_unconfigured")` (`copilot/dependencies.py:103-110`),
i.e. HTTP 503. The dock then shows "The assistant is unavailable right now. This is not an answer." (`strings.ts:69`). Nothing answers and
nothing is faked in the product path. Default in compose, in `infra/demo/main.bicep` (`copilotMode` defaults `disabled`) and in the hosted-demo
doc (`docs/deploy/hosted-demo.md:487-492`: "Copilot shows disabled").

What must be configured for it to answer, all by environment variable or IaC parameter, no UI:
1. `NS_COPILOT_MODE=approved_endpoint` (or `foundry_agent`), `NS_COPILOT_ENDPOINT` (https URL in the deployment's own cloud),
   `NS_COPILOT_DEPLOYMENT`, `NS_COPILOT_REGION`, `NS_COPILOT_MODEL_FEATURE` (must match a row in the capability matrix, otherwise
   `failed(...)` and `/readyz` returns 503 naming `copilot`), optional `NS_COPILOT_API_VERSION`, `NS_COPILOT_SKU`, `NS_COPILOT_OAUTH_SCOPE`.
2. Managed or workload identity with permission on that endpoint (no key is read; any env var `NS_COPILOT_*` containing KEY, SECRET or PASSWORD
   refuses startup, `builders/copilot.py` `refuse_credential_shaped_env`).
3. Cosmos container `copilot_conversations`, catalog, aggregate reader and recommendation store composed (data builder).
Model adapters: `ApprovedEndpointAdapter` (generic Azure OpenAI-style endpoint) and `FoundryAgentAdapter`, plus a recorded/fixture adapter used
only by tests (`packages/core/neurosphere_core/copilot/models/`).
Tools (allowlist of five, `copilot/tools/builtin.py:62-72`): `search_catalog`, `get_cost_summary`, `get_evidence`, `list_recommendations`,
`propose_action`. Model-supplied scope arguments are ignored (injection corpus 78/78 passed in my run). `propose_action` only drafts an
intent through the same `ActionService`; it cannot execute.
Gaps even when configured: `get_evidence` abstains always in the composed app (no evidence reader bound, see table). Model answer
quality, groundedness and first-token latency against a real model are unmeasured (G16 OPEN; the 3 s target is measured only with recorded
fixtures: `docs/evidence/G07/copilot/`). The PRD's "knows the page, filters, time range" is implemented (`copilot/context.py`,
`frontend/src/features/copilot/requestContext.ts`) and tested with fixtures only.
Class PARTIAL (and effectively unavailable in every shipped deployment profile).

Report creation: `frontend/src/features/copilot/components.tsx:243` mounts `SaveReportDialog`; reports API `reports/router.py:83-187`
(create, list, get, update, delete, run, shares, publication and publication decision). Runs re-evaluate authorization through the tool
registry (`reports/service.py:365`). Chart plans go through the validator (no expr, signals or external URL, per PRP-19 item 4) and a
sandboxed iframe with vega-interpreter. Cosmos store `CosmosReportStore` is composed in `builders/planes.py`.

### 2.4 Action executor

Chain: UI `/actions/propose`, `/actions`, `/actions/detail`, `/review`, recommendation buttons -> `frontend/src/features/actions/` ->
`/api/v1/actions/*` (`actions/router.py:106-218`) -> the ONE `ActionService` published by `runtime/builders/planes.py` -> `CosmosIntentStore`
+ `CosmosExecutionControl` -> `HitlService` (maker-checker) -> executor worker role `actions` in `services/workers/neurosphere_workers/actions/`
-> write connector from `WriteTargetRegistry`. Chat (`propose_action`) and MCP (`draft_action`, `validate_action`,
`present_action_confirmation`, `get_action_status`, `mcp/server/tools.py:372-413`) enter via the same service, and PRP-17 item 6 requires the
identical intent hash across button, REST and chat (tests in `tests/integration/actions/test_button_fixture_hash.py`, ran in my 17-test pass).

Which actions change something real (`packages/core/neurosphere_core/actions/targets.py` table `ACTION_CONNECTORS`):
- `model_deployment_swap` -> Foundry deployment PUT through `connectors/reference/foundry-actions/` (real ARM write; run live once, G05).
- `budget_cap_change`, `grant_publish`, `grant_unpublish`, `mcp_server_publish`, `mcp_server_unpublish`, `gateway_mode_change`, and
  `model_deployment_swap` against an `apim_backend` target -> APIM connector `connectors/reference/apim-gateway/` (real ARM writes in
  design; never run against real APIM, G17 manage OPEN).
- Any other kind, or a kind whose connector is not registered, is advisory: drafted, validated, reviewed, never executed, and no catalog
  metadata is edited as a stand-in (`planes.py` docstring; this was a PRP-17/34 exit check). I did not find a code path that edits
  catalog metadata as a stand-in, but I did not audit exhaustively.
Enabling a target is env only and one connector per name per deployment: `NS_FOUNDRY_ENABLED=true` + subscription, resource group, account,
location; `NS_APIM_ENABLED=true` + gateway id + domain id; both in API and workers. Government accounts and gateways are skipped. Neither
compose (`docker-compose.yml:160,214`) nor the hosted-demo template enables them, so in every shipped profile all actions are advisory.
The hosted-demo worker role list is `ingestion,projections,aggregates,actions,hitl_timers,lifecycle` (`infra/demo/main.bicep:242`), so the
executor runs but has no write target.
Controls present: idempotency keys, confirmation bound to target/version/diff hash with expiry, maker-checker, kill switch
(`/admin/execution-control`, `actions/emergency.py`, runbook `docs/runbooks/action-plane-kill-switch.md`), customer-level control, audit.
Known limits recorded in the register: no traffic-split canary for in-place Foundry swaps (verify-only probe), TOCTOU on the etag re-GET,
context window and tool support reported `unknown`.

### 2.5 MCP server and admin

Server: `mcp/server/` builds only when `NS_MCP_RESOURCE_SERVER_URL` is set; audiences must not overlap REST audiences; tools are the copilot
registry plus four action tools; resources filtered by the server-derived scope. Real-stack evidence is composed app on emulators with a local
dev issuer (`docs/evidence/G08/prp-22-real-stack-2026-11-05.md`), not a real Entra token (UNVERIFIED with Entra). Helm has an off-by-default
switch (`infra/helm/values.yaml:124`).
Admin/client: UI `/mcp-admin`, `/mcp-admin/server`; REST `mcp/admin/router.py:96-199` (register, list, get, patch, sync, list tools,
approve, revoke approval). SSRF vetting, allowlist, new or changed tools disabled until approved. Gap: it registers and approves, but no
component calls an approved external tool; the registry is not connected to the copilot or to MCP server tools. The PRD says "MCP client
supports approved external servers", which is true for registration and listing only. Outbound credentials: none; external servers that
need auth cannot be used.
Class: server PARTIAL (off by default, env only), admin/client PARTIAL.

### 2.6 APIM gateway

Observe (PRP-33): `gateway/router.py:205-253` (register, list, detail, inventory, sync), builder `runtime/builders/gateway.py`, worker role
`gateway_poll` in `ROLE_NAMES` (`runtime/roles.py:18-34`), connector `connectors/reference/apim-gateway/`, UI `/gateways`, `/gateways/detail`.
Registration is by ARM resource id via POST only; the page has no register control. In hosted-demo `gateway_poll` is not in
`NS_WORKER_ROLES`. Never run live (G17 OPEN). Manage (PRP-34): see the table. UI has the observe/manage switch with preflight and plan
preview (`GatewayModePanel.tsx`, `PlanPreview.tsx`); the mock API serves `/api/v1/gateways/**` (`frontend/tests/mock-api/server.ts:2053`),
so the vitest/Playwright coverage of these pages is mock-backed.

### 2.7 Connectors: SDK, reference connectors, adding one (key question 3)

SDKs: `connectors/sdk-python/neurosphere_connector/` (manifest, contract kit `contract_kit.py`, health, vault, `write/` with
dry_run/apply/verify/rollback) and `connectors/sdk-ts/`; manifests interoperate (PRP-09 item 2). Reference connectors under
`connectors/reference/`: `otel-generic`, `azure-monitor`, `foundry`, `azure-billing`, `foundry-actions`, `apim-gateway`.

How each reaches the product:
- OTel generic: external collector or exporter POSTs to `/api/v1/ingest` (alias `/v1/ingest`) with a producer credential. Producers are
  registered from a JSON file of hashed credentials, `NS_INGEST_PRODUCERS_FILE` (`ingest/settings.py:35`, `docker-compose.yml:155`); with no
  file, no producer can authenticate. Collector example: `connectors/reference/otel-generic/collector/otel-collector.example.yaml`.
  This is the one connector path that works end to end for a customer, file-configured.
- Azure Monitor: library; only the APIM gateway/LLM-log source kinds are driven by the `gateway_poll` worker
  (`workers/ingestion/gateway_poll/poller.py`). General Application Insights/Log Analytics polling has no runner.
- Foundry discovery and Azure billing export: libraries and tests only; no worker role, route or CLI in the service tree imports them
  (grep of `services/` imports of `neurosphere_connector*` shows only `write`, `azure_monitor.SourceKind`, `apim_gateway` and
  `foundry_actions`). So there is no discovery-to-catalog or billing-to-ledger path (G04 OPEN).

A customer wanting to connect a new AI platform today must: write a connector with the Python or TypeScript SDK against the contract kit,
run it themselves (outside NeuroSphere) and make it push NeuroSphere envelopes to the ingest edge, after an administrator adds a hashed
producer credential to the producers JSON file and restarts the API. For a catalog-only connector they would call the catalog import API.
For a write connector (actions) they must add it in code: a row in `ACTION_CONNECTORS`, a factory in the workers' `register_write_targets`
and settings (the write registry is a closed set of two names, `SUPPORTED_WRITE_CONNECTORS`). There is no connector admin UI, no
plug-in loader, no connector registry API, no documentation page walking through this (only `docs/reference/sdk-python.md`,
`sdk-ts.md` and `docs/connectors/coverage.md`; the runbook `docs/runbooks/ingest.md` covers the ingest side). Coverage doc lists Palantir,
xAI, Cursor as gaps and Graph/M365, GitHub Copilot, Anthropic, Google, Claude Code as not built.

### 2.8 OpenAPI, SIEM, analytics export, CI/CD

OpenAPI: committed spec plus drift test, generated reference docs. WORKS as a documented API (read-only evidence plus the router test runs).
SIEM: `NS_AUDIT_SIEM_SINK` stdout or file only. Analytics export and CI/CD registration: absent (see table).

## 3. Live gates (key question 2)

Is there a real action that changes a deployment end to end, and has it run against real Azure? Yes, once: G05, 2026-11-05, Commercial,
one throwaway Azure AI Services account (Limitlessdata - Main, eastus2), swap gpt-5-nano to gpt-5-mini, apply, read-back verify, rollback,
restored model re-read, account deleted. Evidence `docs/evidence/G05/20261105T173214Z-foundry-swap-live.json` (statuses passed x5, unknown x2,
final `rolled_back`) and `docs/evidence/G05/README.md`. It ran the script `scripts/gates/g05_foundry_swap_live.py`, not the UI or the
composed API-plus-worker path, as far as the README states. No traffic-split canary, no quality-regression run, one pair, no Government.

Gate status per `docs/RESEARCH-AND-GATES.md` (rows 26-39), relevant to this lane:

| Gate | Status | Note |
|---|---|---|
| G01 service/feature/region matrix | OPEN | analytics live runs not done, Government unverified |
| G02 FedRAMP/DoD boundary | OPEN | customer-owned |
| G03 graph benchmark | NARROWED (emulator only) | live Commercial run required |
| G04 connector coverage | OPEN | no `docs/evidence/G04/`; no live contract run |
| G05 model swap | NARROWED | one live pass; production execution still gated by register owner |
| G06 privacy/retention | OPEN | |
| G07 workload/SLO/DR | OPEN | map, copilot and dashboard numbers are sandbox/emulator/recorded-fixture |
| G08 deps and MCP | NARROWED | MCP spec tests on emulators with dev issuer |
| G09 theme/brand | WAIVED (owner, demo scope) | |
| G12 emulator parity | OPEN | |
| G16 live judge run | OPEN | also means no live copilot model run has happened |
| G17 APIM observe and manage | OPEN | scripts exist; no `observe-*` or `manage-*` evidence files |
| G10, G11 | CLOSED | not in this lane |

Not run live at all: copilot against a real model, APIM observe, APIM manage, MCP with real Entra tokens, Foundry discovery, Azure Monitor
polling, billing export, blob-backed replay, any Government cloud.

## 4. What an operator cannot do today (this area)

- Turn on the copilot, or point it at a model, from the product. It is environment variables or Bicep parameters on the API, and ships off.
  Even when on, evidence questions always abstain.
- See per-agent live activity on the map. The map shows catalog entities and one domain-level aggregate cluster; node metrics are unknown.
- Put agents on the map without calling the catalog API, importing a file, or running the sandbox seeder. No UI create/import for catalog
  entities or domains.
- Register an APIM gateway from the UI (API only), or run any gateway change against a real APIM (never run live).
- Enable real actions from the UI. Foundry and APIM write targets need env on both API and workers, and are off in every shipped profile,
  so buttons only create advisory intents unless an engineer configures them.
- Add, enable, schedule or monitor a connector in the product. There is no connector admin page. Ingest producers are a JSON file. Foundry
  discovery and billing connectors are not run by anything.
- Make approved external MCP tools usable by the copilot or by anyone; or give the MCP client credentials.
- Turn on the NeuroSphere MCP server from the UI (env only).
- Export to Sentinel/Splunk/Event Hubs or to enterprise analytics; only a stdout or file audit sink exists.
- Register a repo or pipeline from GitHub Actions, Azure DevOps or Jenkins, or run policy checks from CI. Not built.
- Replay a trace unless the ingestion role has archived events into blob storage.

## 5. Contradictions between PRP "shipped" status and reality

1. Tracker staleness: PRP-09 (PR #45), PRP-18 (PR #85), PRP-19 (PR #87) and PRP-34 (PR #149) are all merged to main with completion notes
   or merge commits, yet `PRPs/INDEX.md` lists them under Backlog (front-matter `status: backlog`) and the ten non-merged ones, in the same
   section, are genuinely unstarted. PRP-18 and 19 acceptance checkboxes are all `[ ]`; PRP-34 and PRP-33 item 8 are `[ ]`. PRP-17 and PRP-22
   sit in `shipped/` with all their item checkboxes still `[ ]` while their notes say shipped. The checkbox state cannot be trusted in
   either direction.
2. PRP-17 item 5 says "a supported Foundry target is changed and verified in the operator-approved live gate": true for one target via
   the script, but G05 remains NARROWED and production action execution is still blocked by the register. Shipped does not mean usable: all
   shipped profiles register zero write targets.
3. PRP-22 / PRD NS-09 "MCP client supports approved external servers": registration, SSRF vetting and tool approval are built; calling an
   external tool is not wired to anything.
4. PRP-18 "map with live updates... drill down... legends for tokens, latency, frequency": tokens and context are never populated at
   map grain, per-node metrics are null (documented in the code, so honest, but the PRD claim is only partly delivered).
5. PRP-19 "answer citations carry data freshness / abstain when evidence unavailable": the abstention is real, but in the composed app the
   evidence reader is permanently empty, so the evidence capability is permanently the abstain path.
6. PRD NS-09 "CI/CD registration for GitHub Actions, Azure DevOps and Jenkins" has no PRP and no code (PRP-09 line 224 excludes it); the
   tracker shows no backlog item for it.
7. PRP-33 and PRP-34 are declared P1 features with live-gate items unchecked; the register and README files admit G17 is OPEN, which
   matches reality. This is consistent, not a contradiction, but the UI pages for gateways are exercised by the mock API in CI.

## 6. Open questions I could not answer

- Does the browser map page actually render the empty state and the domain-required state correctly against the real API? I read code and
  strings only; not run in a browser (the stack is the orchestrator's).
- Do the Cosmos-backed stores for reports, conversations, MCP servers, gateways and intents behave on the emulator? The 8 deselected
  `tests/integration/actions` tests and the real_stack suite (`tests/integration/real_stack/`) need the compose emulators; not run by me.
- Is the G05 run reproducible through the composed API plus executor worker (rather than the standalone script)? The README describes the
  script; I did not find evidence of a composed-path live run.
- Does the copilot's model adapter work against a real Azure OpenAI or Foundry endpoint (request shape, tool-call round trip, streaming)?
  Only recorded HTTP fixtures exist. G16 is OPEN.
- Where do domains come from in a fresh deployment (the app's domain selector)? I did not trace `frontend/src/app/domain.ts` to its API source.
- Whether any other module (outside `services/`) consumes the Foundry discovery or billing connectors (for example a script in `scripts/`
  or `sandbox/`). My grep covered `services/` and `scripts/gates` only.
