---
name: PRP-139-hosted-environment-real-tenant-data
status: shipped
priority: P0
order: 58
review: required
created: 2026-11-17
started: 2026-11-21
shipped: 2026-11-21
pr: 369
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-02, NS-08, NS-09
depends_on: []
wave: W18b
branch: prp-139-hosted-real-tenant-data
allow_parallel: true
issues: []
---

# PRP-139: Hosted environment shows the tenant it is deployed to (real sources on, synthetic data out)

## Goal
Make a hosted NeuroSphere deployment show the Azure tenant it runs in, and nothing else. Today the hosted environment (`rg-neurosphere-demo`, release `0.1.0-rc.4`) holds the synthetic world loaded on 2026-10-28 under the customer id `synthco`, and no connector reads the owner's tenant. This PRP adds a "real tenant" hosted mode: the customer id becomes a deployment parameter instead of a hard-coded `synthco`; the connector worker roles are on; each of the four first sources (Azure AI Foundry, Azure Monitor and Application Insights, cost and billing, API Management AI gateways) is configured through the shipped admin console with managed identity only; the read access NeuroSphere's identities need is listed role by role and applied only in an operator-run, approval-gated step; the hosted seed is refused unless a demo-environment flag is set; the synthetic data is removed by a dry-run-first, confirmed purge in the same operator run that turns real data on; every page reachable from the navigation says what is missing and links to the admin page that connects a source; and one operator live gate proves real records per source and no synthetic ones. It is for the owner, who opened the deployed app and saw demo data (decision D20, `docs/DECISIONS-LOG.md:18`). It runs in W18b and merges after PRP-138 and PRP-140.

This PRP is the first shippable slice. It ends with Foundry discovery showing real agents and model deployments in the catalog. API Management gateway logs and billing export run on shipped code and need only access, a producer secret and configuration, so they are operator steps here. Application Insights "AI call telemetry" has no shipped reader that produces telemetry events (see Why); that reader is a follow-up PRP (see "Split and follow-up"), and its live-gate row stays OPEN here.

Out of scope: mapping Entra app roles and groups to NeuroSphere roles and the first admin (PRP-138, which makes a re-grant of people unnecessary); navigation grouping and any navigation file (PRP-140); a generic connector runner, the connector status store for the estate and the Coverage page (PRP-117); probe defaults, teardown, the budget start date bug and the other hosted script hardening (PRP-67); the hosted "everything on" profile, the signed-in navigation walk and the evidence validator (PRP-82); the demo world (PRP-71, local and CI only); content capture (PRP-103, stays off); Government (Commercial only here); creating Foundry accounts, Cost Management exports, Log Analytics workspaces or API Management services; any write to a governed resource.

## Why
- The owner's words after the rc.4 deploy: "why is it demo data, i want it to able be pulling in and work in the tenant it is deployed to. right now it should [show] no data". Decision D20 makes this binding and names this PRP (`docs/DECISIONS-LOG.md:18`).
- The hosted customer id is a constant: `var customerId = 'synthco'` (`infra/demo/main.bicep:142`), set as `NS_AUTH_CUSTOMER_ID` (`infra/demo/main.bicep:247`). `hosted_demo.py deploy` has a `--customer-id` flag (`scripts/gates/hosted_demo.py:315`) that only reaches the registration file (`scripts/gates/hosted_demo.py:1145`); `customerId` is not in `GENERATED_PARAMS` (`scripts/gates/_hosted_demo_common.py:53-86`), so the flag cannot change what the sites use.
- The hosted data is synthetic by construction: the seed driver states "Seed the registered hosted demo with synthetic data" and offers only the profiles `small` and `demo` (`scripts/gates/hosted_demo_seed.py:1,62`); the committed evidence shows the `small` world, 119 entities seeded and 5707 records already present (`docs/evidence/PRP-32/2026-10-28-seed.json`); the runbook step says "Synthetic data only" (`docs/deploy/hosted-demo.md:325`). The only guard on the seed is `NS_LIVE_APPROVED=1` (`scripts/gates/hosted_demo_seed.py:107`), so nothing stops a re-seed of a real environment.
- No connector role runs hosted by default: `connectorRoles` defaults to an empty list (`infra/demo/main.bicep:88`) and the runbook says "No profile turns a connector role on by default" (`docs/deploy/hosted-demo.md:562`); `docs/runbooks/connector-config.md:89` still lists hosted connector roles as a known limit. The roles themselves ship (`services/workers/neurosphere_workers/runtime/roles.py:18-31`: `gateway_poll`, `foundry_discovery`, `billing_export`) and idle safely when not configured (`services/workers/neurosphere_workers/runtime/factories.py:1281-1297,1337-1349,1406-1418`).
- Access is half declared. `infra/demo/modules/connector-rbac.bicep:26-56` assigns Foundry User on one Foundry account and Storage Blob Data Reader on one storage account to the workers identity. Nothing declares the read access the gateway path needs: the workers query the gateway's Log Analytics workspace (`services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:283-284`) and the API reads the API Management service through ARM at registration (`services/api/neurosphere_api/gateway/service.py:132-139`).
- "Azure Monitor and Application Insights (AI call telemetry)" is not runnable as the owner means it. The Azure Monitor connector's generic kinds only count requests per five minutes (`connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/queries.py:45-57`), no worker role calls them (the role list has no such role, `runtime/roles.py:18-31`), and the only caller of the connector is `gateway_poll` for API Management tables (`docs/connectors/coverage.md:68`). Model and agent calls reach the product today through API Management logs or through producers that push OpenTelemetry to the ingest edge (`docs/connectors/coverage.md:69`).
- An admin cannot see whether Foundry discovery or billing export works. Both keep their last result in memory only (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:138-146`, `ingestion/billing_export/runner.py:217-221`); only the gateway poller stores a status (`gateway_poll/poller.py:454-466`). The Connectors page shows `enabled` and `status` of the configuration, not of a run (`frontend/src/features/admin/sources/types.ts:59-60`).
- The worker has no authority in a fresh customer. Its scope comes only from the policy store (`services/workers/neurosphere_workers/runtime/identity.py:3-11`), and the only thing that ever granted it was the synthetic seed (`scripts/sandbox/sbx_seed_stack.py:711-722`).
- Empty pages do not help. The shared `EmptyState` has an `action` slot (`frontend/src/design-system/components/states.tsx:38-57`) that no page passes. Pages say "No nodes in this domain yet." (`frontend/src/features/map/MapPage.tsx:428`), "No data in this window" (`features/dashboards/DashboardPage.tsx:181`) or "No gateways are registered in this domain." (`features/gateways/GatewaysPage.tsx:31`) with no pointer to Sources. Five role workspace pages render "Placeholder: this workspace is built out in later work." (`features/workspaces/WorkspacePage.tsx:74`). Three pages treat "nothing yet" as an error (`features/audit/AuditPage.tsx:52-59`, `features/admin/gateways/RegisterGatewayPage.tsx:77-78`, and the admin 404 rule in `features/admin/shared/AdminStates.tsx:15-57`).

## Acceptance criteria
- [ ] Given `infra/demo/main.bicep` built with `dataMode = 'real-tenant'` and `customerId = 'contoso'`, When the settings are rendered, Then `NS_AUTH_CUSTOMER_ID` is `contoso`, `NS_WORKER_ROLES` contains `foundry_discovery`, `gateway_poll` and `billing_export`, `NS_API_BASE_URL` is set on the workers, and `NS_HOSTED_DATA_MODE=real-tenant` is set on the API and workers; Given the defaults (`dataMode = 'demo'`, `customerId = 'synthco'`), Then the rendered resources equal today's golden (`tests/unit/hosted_demo/core_main_resources.golden.json`) except the one documented new setting.
- [ ] Given `dataMode = 'real-tenant'` with `customerId = 'synthco'` or an id that is not a canonical id segment, When `hosted_demo.py plan` runs, Then it refuses before any Azure call with a message naming the parameter; `--customer-id` now reaches both the generated parameter file and the registration, and the two can no longer differ.
- [ ] Given a registration whose `data_mode` is `real-tenant`, When `hosted_demo_seed.py` runs with `NS_LIVE_APPROVED=1`, Then it refuses (exit 2, nothing contacted); Given any registration without `--demo-environment <deployment id>` matching the registered deployment, Then it also refuses. The refusal happens before any network client is imported.
- [ ] Given a hosted environment holding the synthetic estate, When `hosted_purge_synthetic.py plan` runs, Then it writes per-container counts of what it would delete and deletes nothing; it selects only documents of the synthetic customer (`synthco` unless the registration's `previous_customer_id` says otherwise) whose ids or source are in the `sandbox` source, plus the seed's own fixed records (grants, price snapshot, gateway, reports, intents, recommendations, evaluations) listed in clarification 4.
- [ ] Given the same environment, When `hosted_purge_synthetic.py apply` runs, Then it requires `NS_LIVE_APPROVED=1`, `--confirm <deployment id>`, a plan file written less than 24 hours earlier whose counts still match, and it refuses when: the endpoint is local or not the registered host (`sbx_guard.require_hosted_endpoint`), the purge customer equals the deployment's active customer id, the active data mode is not `real-tenant`, or any selected document fails the synthetic test on re-read. It writes counts-only evidence under `docs/evidence/PRP-139/`.
- [ ] Given a store that holds one real record beside the synthetic ones (another customer id, or the same customer with a non-sandbox source), When plan and apply run against in-memory stores, Then the real record is never selected, never deleted and is counted as `kept`; a property test with random mixed stores proves it.
- [ ] Given each connector role, When a tick ends, Then a run status (connector kind, state `ok | partial | failed | idle | not_configured`, a reason code, last success time, counts) is stored for the customer; Given a missing Azure role (the provider answers 401 or 403), Then the state is `failed` with reason `source_access_denied`, the role keeps running, no other source is affected and no token, host or resource id is stored.
- [ ] Given a signed-in user who can read at least one domain, When they call `GET /api/v1/sources/status`, Then they get, for each of the four sources, `not_connected | connected_no_data | connected | failing` and the last success time, with no id, name or host; Given a customer-level `config.manage` holder calling `GET /api/v1/admin/sources/status`, Then they also get the reason code and counts per connector kind. Viewers of no domain and expired users get 403 and a denial record.
- [ ] Given the Connectors admin page, When a run status exists for a configuration's kind, Then the row shows the state, the last success time and the reason in words (for `source_access_denied`: which role on which kind of resource is missing and that the owner must approve it), and the page shows the four first sources with a "Connect" action each when none is configured.
- [ ] Given no data and `not_connected` sources, When a user opens each page in the inventory table below, Then the page shows an empty state that says what is missing and has a link to `/admin/sources/connectors` (admins) or the text "Ask an administrator to connect a source" (others), never an error panel or a blank chart; Given sources `connected` but a page still empty, Then the text says data has not arrived yet and shows the last success time. A test per page asserts the link target.
- [ ] Given `hosted_real_tenant.py access-plan`, When the operator names the Foundry accounts, the gateway and its workspace, and the export storage account, Then it prints and writes the exact role assignments (identity, role name, role definition id, scope) and changes nothing; `access-apply` needs `NS_LIVE_APPROVED=1` and one `--approve-assignment` token per assignment, refuses any scope wider than a single resource, refuses a resource that is not in the plan, and never creates, edits or deletes the governed resource.
- [ ] Given `hosted_real_tenant.py verify` after the cut-over, Then per source it reads counts through the API with the operator's token and records `PASS`, `FAIL` or `OPEN` with a reason; synthetic counts must be zero; a source that was not connected is `OPEN`, never `PASS`.
- [ ] Privacy: no code path added here reads or stores prompt, response, header or body content; content capture stays off; the Foundry reader, the gateway query allowlist and the billing reader are unchanged; a test asserts `NS_HOSTED_DATA_MODE=real-tenant` cannot be combined with `NS_CLOUD=government` in these templates and scripts (refused, not bridged).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend lint, typecheck and tests, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated; the runbook `docs/deploy/hosted-real-tenant.md` lists every operator command in order; the live gate is written OPEN with its commands.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Which customer id holds real data | Keep `synthco` and purge first; a new real customer id, purge the old one after | ASSUMPTION: a new real customer id, supplied by the operator as `--customer-id` (a lowercase slug of the organisation, for example the tenant's short name; the owner picks the value). Evidence: the customer id is the partition key of most containers (`packages/core/neurosphere_core/stores/containers.py:94-95,118-123`), a segment of every canonical id and of the catalog partition value (`services/workers/neurosphere_workers/ingestion/foundry_discovery/settings.py:20`), part of every principal id (`packages/core/neurosphere_core/auth/scope/pseudonym.py:87-100`) and the first path segment of the archive (`services/workers/neurosphere_workers/archive/serialize.py:35-38`). A new id makes the synthetic estate invisible at the restart that turns real data on (so the app is never a mix and never shows synthetic data as real), and lets the purge be scoped by a customer id that the running product does not use, which is what makes "can never touch real records" provable. Keeping `synthco` would need a purge before real data and a per-record synthetic test for stores that carry no source field (grants, prices, reports). |
| 2 | What happens to existing role grants | Carry over; re-grant by script; rely on PRP-138 | Grants under `synthco` stop applying because principal ids contain the customer id. People: PRP-138 (merges first) maps Entra app roles and groups to NeuroSphere roles, so the owner is an administrator at first sign-in and no re-grant is needed. If PRP-138 is not deployed, the stopgap of D20 (`sbx_grant_operator.py --hosted`) applies and the runbook says so. The workers' own principal is not a person and PRP-138 does not cover it: `hosted_real_tenant.py bootstrap-worker` grants it `viewer` on the named domains, the same grant the seed made (`sbx_seed_stack.py:722`). Stored producers, connector configurations and feature settings under `synthco` are not copied; they were synthetic or defaults and are re-created in the console. |
| 3 | How "real tenant" is expressed | New template; parameters on the existing templates | Two parameters on `infra/demo/main.bicep` and `infra/appservice/main.bicep`: `dataMode` (`demo` default, `real-tenant`) and `customerId` (`synthco` default). Defaults keep existing goldens. `real-tenant` adds the three connector roles to `NS_WORKER_ROLES` whatever `connectorRoles` says. The owner decision is carried by the deploy script: `hosted_demo.py` requires `--data-mode` explicitly from now on and the runbook uses `real-tenant`. |
| 4 | What the purge deletes | Whole database; by customer partition; by customer and source | By customer and source, with a closed list of the seed's sourceless records. Catalog, telemetry-derived aggregates, ledger, outbox, accepted-event and watermark rows: customer `synthco` and source `sandbox` (ids of the form `commercial:synthco:sandbox:...`). Sourceless records the seed wrote (`sbx_seed_stack.py:711-1110`: grants of the personas, worker and operator; the synthetic price snapshot `synthetic_snapshot()` at `:753`; recommendations; evaluation runs and results; action intents; reports; MCP servers; the seed gateway): selected by customer `synthco` and by the deterministic ids the seed computes, recomputed by importing the seed's own functions read-only. Archive blobs: prefix `synthco/`. ASSUMPTION: audit chains of `synthco` are kept (an audit record is not deleted by a data purge; they are invisible under the new customer) unless the operator passes `--include-audit`. Event Hubs is not purged; retention ages it out. |
| 5 | Order of the cut-over | Purge then deploy; deploy then purge | Owner decision 2: one operator run, in this order: access plan and approval, redeploy with `real-tenant` and the new customer id (the synthetic estate becomes invisible and the pages show the new empty states), bootstrap the worker grant, connect sources in the console, purge plan, purge apply, verify. The purge refuses unless the active mode is already `real-tenant`, so the app is never blank with nothing behind it and never deleted before the switch. |
| 6 | How connectors are configured | App settings; stored configuration | Stored connector configuration through the admin console (`/admin/sources/connectors`, PRP-42 and PRP-57), as PRP-58 decided ("what each connector polls lives in stored connector configuration, never in app settings", `infra/demo/main.bicep:254-255`). Managed identity only: `foundry_discovery` takes a `managed_identity` credential; `gateway_poll` and `billing_export` post to the ingest edge with a producer secret that lives in Key Vault and is read by the workers identity (`docs/runbooks/connector-config.md:8-11,35-37`). No key or connection string is accepted anywhere. |
| 7 | Where the role assignments are declared | Bicep only; script only; both | Foundry User and Storage Blob Data Reader stay in `connector-rbac.bicep` (shipped). The gateway path's two read roles are added to the same module behind new id-list parameters, each at the scope of one resource. Because the governed resources can sit in subscriptions where the deploying principal cannot write role assignments, `hosted_real_tenant.py access-plan` prints the same assignments as `az role assignment create` lines, and `access-apply` runs only the approved ones. Nothing is assigned at resource-group or subscription scope by this PRP. |
| 8 | Discovery scope for Foundry | Use the copilot's account; owner names accounts | The owner names them. The account the copilot uses (`aifndry-loom-centralus`, in the shared hub resource group) belongs to another workload; it is not assumed, not defaulted and never appears in a parameter file. ASSUMPTION for the first run: the owner names at least one Foundry account and project that belongs to NeuroSphere's own subscription scope; reading another team's account needs that team's agreement recorded in the approval note. |
| 9 | Where connector run status is stored | New container; the existing `admin_config` container; memory | The existing `admin_config` container (partition `/customer_id`, one row per kind and id, `stores/containers.py:199-204`), record kind `connector_run_status`, written by the workers and read by the API. No new container and no contract change in this wave. PRP-117 (W26) builds the estate status store and Coverage page; its item 4 reads these rows as the status of the three built-in kinds or migrates them, and this PRP names the record shape for it. |
| 10 | Who may read the source summary | Admins only; any domain reader | ASSUMPTION: any principal that can read at least one domain (`require(Permission.DATA_READ)`, the rule of `GET /api/v1/me/domains`, `services/api/neurosphere_api/me/router.py:51`) gets the four states and last success times only. The empty states need it for non-admins. Reason codes and counts need customer-level `config.manage`. |
| 11 | Application Insights AI call telemetry | Build here; follow-up | Follow-up PRP (see "Split and follow-up"). Here the row is OPEN and the runbook offers the two shipped paths for call telemetry: API Management gateway logs, and OpenTelemetry pushed by the workload to the ingest edge with a producer credential. |

## Sources: what is read, with what access, and what an admin sees
| Source | Shipped | Reads (metadata only) | Identity, role and scope | Declared in | When the role is missing | Health an admin sees |
|---|---|---|---|---|---|---|
| Azure AI Foundry | Yes: role `foundry_discovery`, connector `connectors/reference/foundry`, stored config kind `foundry_discovery` | Agents and model deployments of the named projects (`GET {endpoint}/agents`, `/deployments`, scope `https://ai.azure.com/.default`, `docs/connectors/coverage.md:31`); written as draft catalog entities marked `discovered_from = foundry`, create if absent (`coverage.md:70`). Projects become domains only by the admin's choice of `domain_ids` | Workers identity; Foundry User (formerly Azure AI User), role definition id `53ca6127-db72-4b80-b1b0-d745d6d5456d`, on each named Foundry account only (`connector-rbac.bicep:26,38-46`; verified against Learn 2026-11-16 per `docs/deploy/hosted-demo.md:566-567`) | `infra/demo/main.bicep:475-484` via `foundryAccountIds`; `access-plan` prints the same | Discovery of that project fails; state `failed`, reason `source_access_denied`; catalog stays empty for it; nothing else stops | Run status row on the Connectors page (new); catalog entities with the Foundry marker |
| API Management AI gateways | Yes: role `gateway_poll`, connector kinds `apim_gateway`, `apim_mcp`, gateway registry (PRP-33), stored config kind `gateway_poll` | Gateway and LLM log rows from the gateway's Log Analytics workspace, a fixed column allowlist with no body or header column (`connectors/reference/azure-monitor/README.md`, "Privacy rule"); token counts, model, status, latency. The API reads tier and diagnostic settings of the gateway through ARM at registration (`gateway/service.py:132-139`) | Workers identity: read on the one Log Analytics workspace. API identity: read on the one API Management service. Both role names are UNVERIFIED (see below). Workers identity: Key Vault Secrets User on the deployment's vault for the producer secret (shipped, `connector-config.md:58`) | New id-list parameters on `connector-rbac.bicep` and `main.bicep` (item 1); `access-plan` | Registration fails with the ARM error mapped to a reason, or the poll records `poll_status` failed; no gateway traffic appears; other sources unaffected | `poll_status`, `freshness_seconds` and `coverage` on the gateway registration (shipped, `gateway_poll/poller.py:454-466`), plus the run status row (new) |
| Cost and billing | Yes: role `billing_export`, connector `connectors/reference/azure-billing`, stored config kind `billing_export`; Commercial only (`factories.py:1437`) | CSV files of a Cost Management export the owner already created, from one blob container (`billing_export/settings.py:33-37`); posted as invoiced cost for closed months only (`coverage.md:73-77`) | Workers identity: Storage Blob Data Reader, role definition id `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`, on that storage account only (`connector-rbac.bicep:28,48-56`); Key Vault Secrets User for the producer secret (shipped) | `infra/demo/main.bicep:486-493` via `billingExportStorageAccountId`; `access-plan` | The read fails (`read_failed`); state `failed`, reason `source_access_denied`; reconciliation shows no billing source | Run status row (new); the reconciliation view's `billing` source |
| Azure Monitor and Application Insights (AI call telemetry) | Partly. The connector is built (`coverage.md:28`) but its generic kinds return request counts only (`queries.py:45-57`), map to no telemetry event and have no worker role | Nothing in this PRP beyond the gateway tables above and the optional `customMetrics` cost-center query of `gateway_poll` (`gateway_poll/settings.py:48-50`) | UNVERIFIED read role on the workspace or component; decided in the follow-up | Follow-up PRP | Not applicable here | Shown as `not_connected` with the text "not available in this release; use the gateway or OpenTelemetry path" |

UNVERIFIED (no Microsoft Learn access in the planning session; each must be checked against Learn at session start and the role definition id, not the name, written into the module):
1. The least-privilege built-in role that lets the workers identity run Log Analytics queries on one workspace (candidates to check: Log Analytics Reader, Log Analytics Data Reader, Monitoring Reader) and whether table-level access can narrow it to the three `ApiManagementGateway*` tables.
2. The least-privilege built-in role that lets the API identity read one API Management service and its diagnostic settings through ARM (candidates: API Management Service Reader Role, Reader), and whether reading diagnostic settings needs a second role.
3. The role needed to query Application Insights `customMetrics` by application id for the optional cost-center tag (`metrics_app_id`).
4. Whether a Cost Management export can be scoped to AI spend at creation, and which role the owner (not NeuroSphere) needs to create one; the product only reads the export's container.
5. Whether Foundry User on the account is enough to list agents and deployments of every project of that account, or whether a project-scope assignment is needed (PRP-58 verified the role id, not this behaviour; the G04 `foundry-discovery` step is still OPEN, `docs/connectors/coverage.md:9-19`).
6. Role-assignment propagation time (the G17 run saw a 401 until the assignment propagated, `docs/evidence/G17/README.md:63`); `verify` retries within a stated bound instead of assuming a number.

## Empty-state inventory (read 2026-11-17)
Classes: B = has text but no pointer to a source; C = placeholder or blank; D = shows an error for "nothing yet". No page links an empty state to the Sources pages today.

| Page (route) | File and line | Today | Change here |
|---|---|---|---|
| Home (`/`) | `features/overview/OverviewPage.tsx:330,370-372` | B | source-aware empty state for tiles and reports |
| Role workspaces (`/workspaces/*`) | `features/workspaces/WorkspacePage.tsx:62-76` | C | replace the placeholder text with the shared empty state and links to the pages of that role |
| Cost, latency, coverage dashboards | `features/dashboards/DashboardPage.tsx:98,181`, `components.tsx:302` | B | source-aware |
| Reconciliation | `features/reconciliation/ReconciliationPage.tsx:176,314` | B | source-aware (billing and gateway named) |
| Forecast | `features/finops/ForecastPage.tsx:355` | B | link to Admin Pricing and to Sources |
| Map, Map table | `features/map/MapPage.tsx:428`, `features/map-table/MapTablePage.tsx:130,274` | B | source-aware |
| Trace replay | `features/replay/ReplayPage.tsx:148` | B | source-aware |
| Catalog, Stale agents | `features/catalog/CatalogExplorerPage.tsx:213,258`, `StaleAgentsPage.tsx:167` | B | source-aware (Foundry named) |
| Quality, Evaluation results | `features/quality/QualityPage.tsx:54,156,225`, `features/evaluations/EvaluationsPage.tsx:158` | B | source-aware |
| Recommendations | `features/recommendations/RecommendationListPage.tsx:70` | B | source-aware |
| Gateways | `features/gateways/GatewaysPage.tsx:31` | B | link to Admin Gateways |
| Audit log | `features/audit/AuditPage.tsx:52-59` | D for an unconfigured store | keep the warning; no change to error semantics, add the link to Admin System |
| Admin Gateways | `features/admin/gateways/RegisterGatewayPage.tsx:77-78` | D | empty state with a link to Admin Domains |
| Admin Connectors, Producers | `features/admin/sources/ConnectorsPage.tsx:273`, `ProducersPage.tsx:208-211` | B | the four-source "Connect" panel and run status (item 4) |
| Federation, Review, Actions, Publication, Recertifications, Relationship review, Compliance, Deployment, Capabilities, MCP servers, Reports | `features/federation/FederationPage.tsx:155`, `review/ReviewQueuePage.tsx:78`, `actions/ActionsPage.tsx:87`, `catalog/CatalogPublicationPage.tsx:38`, `catalog/RecertificationsPage.tsx:59`, `curation/ReviewQueuePage.tsx:203`, `compliance/CompliancePage.tsx:224`, `deploy/ScanStep.tsx:85`, `deploy/CapabilitiesPage.tsx:156`, `mcp-admin/McpServersPage.tsx:49`, `reports/ReportsListPage.tsx:95` | B, and the cause is not a missing source | no change: the text already names the missing thing; listed so the reviewer can see they were checked |
| Admin Identity, Domains, System, Audit search, Pricing, Features, Review policy | `features/admin/identity/PrincipalsPage.tsx:40`, `admin/domains/DomainsPage.tsx:118`, `admin/system/SystemPage.tsx:82`, `admin/audit/AdminAuditPage.tsx:177`, `admin/pricing/PriceSheetsPanel.tsx:126`, `admin/features/FeatureSettingsPage.tsx:134`, `admin/review-policy/ReviewPolicyPage.tsx:279` | B (these are the pages where things get connected) | no change; the identity pages belong to PRP-138 |

`frontend/src/features/execution-control/ExecutionControlPage.tsx` has no empty branch and an error branch at `:147-155`; it shows a control, not data, and is left unchanged. The 404-as-error rule of the admin pages (`AdminStates.tsx:15-57`) is deliberate ("Never rendered as an empty list") and is not changed.

## Context manifest

### Files to read first
- `docs/DECISIONS-LOG.md:18` (D20) and `CLAUDE.md` hard constraints.
- `infra/demo/main.bicep:84-97,136-149,236-322,465-493`, `infra/demo/main.bicepparam`, `infra/demo/modules/connector-rbac.bicep`, `infra/appservice/main.bicep` (the twin).
- `scripts/gates/_hosted_demo_common.py:53-86` (`GENERATED_PARAMS`), `scripts/gates/hosted_demo.py:215-335,440-505,1125-1150,2045-2060` (flags, parameter build, registration, approval check).
- `scripts/gates/hosted_demo_seed.py` (whole file, 175 lines) and `tests/unit/gates/test_hosted_demo_seed_refuses.py`.
- `scripts/sandbox/sbx_guard.py:108-243` (`require_hosted_endpoint`, `load_registration`) and `scripts/sandbox/sbx_seed_stack.py:434-500,686-760,1079-1175,1637-1665` (hosted config, grants, what the seed writes, hosted backends). Read only; these files are not edited.
- `packages/core/neurosphere_core/stores/containers.py:94-204` (partition keys per container).
- `services/workers/neurosphere_workers/runtime/factories.py:1281-1479` (the three connector builders), `connector_config/resolve.py` (stored configuration wins), `ingestion/foundry_discovery/poller.py:130-195`, `ingestion/billing_export/runner.py:210-295`, `ingestion/gateway_poll/poller.py:225-345,440-467`.
- `services/workers/neurosphere_workers/runtime/identity.py:1-20` (the worker's scope comes from the policy store).
- `services/api/neurosphere_api/admin/sources/connectors/{router,service,models}.py`, `services/api/neurosphere_api/me/router.py`, `services/api/neurosphere_api/admin/system/checklist.py`.
- `docs/runbooks/connector-config.md`, `docs/connectors/coverage.md:24-33,62-77`, `docs/deploy/hosted-demo.md:321-352,544-597`.
- `frontend/src/design-system/components/states.tsx:38-125`, `frontend/src/features/admin/sources/{ConnectorsPage.tsx,hooks.ts,apiPaths.ts,types.ts,strings.ts}`, `frontend/src/features/admin/shared/AdminStates.tsx`, and the page lines in the inventory table.
- `PRPs/shipped/PRP-138-entra-admin-role-mapping-and-first-admin.md` (ownership block, clarification 16, item 9; shipped 2026-11-19, and item 9 already merged in PR #341, so `entraRoleMappings` in `infra/demo/main.bicep`, `--entra-role-mappings-file` in `hosted_demo.py` and the `NS_HOSTED_ENTRA_ADMIN_APP_ROLE` variable in `deploy-hosted.yml` exist: build on them, do not add them again) and `PRP-140-navigation-grouping.md` ownership blocks (siblings), `PRP-67`, `PRP-82`, `PRP-117` ownership blocks (later waves).

### Interfaces consumed
- Shipped: worker roles and builders, `resolve_*_settings`, `ConnectorConfig` (admin/v1), `AdminConfigRepository`, `CosmosAdminConfigRepository`, connector admin routes, gateway registry and `poll_status`, `require(Permission.DATA_READ)`, `require` with customer-level `config.manage`, `EmptyState`, `sbx_guard.require_hosted_endpoint`, `sbx_grant_operator.grant_operator`, `connector-rbac.bicep`, `hosted_demo.py` plan and deploy.
- PRP-138 (same wave, merges first): the owner is an administrator through Entra, so the console steps of the runbook need no script grant. Until PRP-138's item 9 (its hosted parameter, a second pull request after this PRP) is deployed, the mapping is set by hand as an app setting or the D20 stopgap grant is used; the runbook says which. This PRP edits no file PRP-138 owns.
- PRP-140 (same wave, merges second): navigation files. This PRP adds no navigation entry and no route.

### Interfaces provided
- Bicep parameters `dataMode` (`demo | real-tenant`), `customerId`, `logAnalyticsWorkspaceIds`, `apimServiceIds` on `infra/demo/main.bicep`; `dataMode` and `customerId` on `infra/appservice/main.bicep`. App setting `NS_HOSTED_DATA_MODE`. Registration fields `data_mode` and `previous_customer_id` (additive; `schema` stays 1).
- `hosted_demo.py` flags `--data-mode`, `--log-analytics-workspace-ids`, `--apim-service-ids`; `--customer-id` moved to the shared infrastructure flags.
- `scripts/gates/hosted_demo_seed.py --demo-environment <deployment id>` (required from now on).
- `scripts/gates/hosted_purge_synthetic.py plan | apply`; evidence `docs/evidence/PRP-139/<date>-purge-plan.json` and `<date>-purge.json` (counts only).
- `scripts/gates/hosted_real_tenant.py access-plan | access-apply | bootstrap-worker | verify`; evidence `docs/evidence/PRP-139/<date>-access.json`, `<date>-verify.json`.
- Core `neurosphere_core.sources_status` (new): `ConnectorRunStatus` (kind, state, reason, last_success_at, last_attempt_at, counts), `SourceStatusRepository` over the admin config store, `summarize(statuses, configs, gateways) -> SourceSummary` for the four sources, reason codes including `source_access_denied`.
- Worker `neurosphere_workers.sources_status` (new): `StatusRecordingTick` wrapping a role tick and its `last_status`.
- API `neurosphere_api.sources_status` (new): `GET /api/v1/sources/status`, `GET /api/v1/admin/sources/status`.
- Frontend `features/source-status` (new): `useSourceStatus()`, `NoDataEmptyState` (props: `what`, `sources`, `adminHref`), strings.
- Consumers: PRP-82 (turns features on against this mode and walks the pages; its walk treats the new empty states with a `not_connected` reason as allowed only for sources recorded OPEN); PRP-117 (reads or migrates `connector_run_status`, adds estate kinds and the Coverage page); PRP-67 (rebases its hosted script hardening on the new flags); the follow-up PRP for Application Insights telemetry; PRP-109 (the deployed scenario runs in this mode).

### Patterns to match
- Parameter to settings composition and per-resource role modules: `infra/demo/main.bicep:254-262,465-493`.
- Refusal order of a gate script (approval first, exit 2, nothing imported): `scripts/gates/hosted_demo_seed.py:105-123`; counts-only evidence: `:86-102`.
- Hosted endpoint guard: `scripts/sandbox/sbx_guard.py:171-243`.
- Per-step approval tokens: `scripts/gates/g04_connectors_live.py` (`--approve-step`) and `hosted_demo.py --approve-shared`.
- Customer-level admin read with audit of denials: `services/api/neurosphere_api/admin/sources/connectors/router.py`.
- Read-anywhere route: `services/api/neurosphere_api/me/router.py:51`.
- Storing a status from a tick: `services/workers/neurosphere_workers/ingestion/gateway_poll/poller.py:440-467`.
- Empty state tests: `frontend/src/features/map/map.test.tsx:804-805`.

### Gotchas
- Data services are private. Cosmos, Blob and Key Vault writes from the operator machine (purge, worker bootstrap, the producer secret) need the point-to-site VPN with name resolution through the vault and store suffixes (`docs/deploy/hosted-demo.md:80-98`).
- Every redeploy currently needs `--budget-start-date 2026-10-01`; without it the budget module fails on a past start date. The bug belongs to PRP-67; the runbook carries the flag and this PRP does not fix it.
- Do not touch other teams' Foundry accounts or shared hub resources beyond reading. The Foundry account wired for the copilot is `aifndry-loom-centralus` in the shared hub resource group and belongs to another workload: it is never a default, and discovery scope is chosen by the owner.
- `union()` in Bicep hides schema errors; build with `az bicep build` in the test where `az` exists.
- A stored configuration is read when a role starts; there is no hot reload (`docs/runbooks/connector-config.md:65-68`). The runbook restarts the workers site after each console change.
- The stored credential must be non-null (`connector-config.md:93-94`), and `foundry_discovery` records a `managed_identity` credential but does not apply a client id (`connector-config.md:91-92`): hosted uses the system-assigned identity.
- Discovery needs a domain that exists and that the workers principal can see. In a fresh customer there is none: the admin creates a domain first (`/admin/domains`), then `bootstrap-worker` grants the workers principal on it, then the connector is configured.
- Changing `NS_AUTH_CUSTOMER_ID` while synthetic events are still in Event Hubs or the outbox: read `ingestion/pipeline.py:160-185` first and write a test for what the workers do with an event of another customer (expected: not stored under the new customer); the runbook waits for the hub to drain or the retention to pass before `verify`.
- The price snapshot container is keyed by snapshot id, not customer (`stores/containers.py:154-162`): the purge selects the synthetic snapshot by the id the seed computes, never by partition scan.
- `hosted_demo.py`, `_hosted_demo_common.py` and `scripts/sandbox/**` are PRP-67's in W19 and `hosted_demo_seed.py` is PRP-82's in W21. W18b merges first, so there is no parallel edit, but both PRPs must rebase; keep the edits small and additive. `scripts/sandbox/**` is not edited at all here (imported read-only).
- Evidence holds counts, states and reason codes only: no subscription id, tenant id, host, resource id, object id or token. Subscription ids print as a short hash, as G17 does.
- Agents cannot edit `.env.example`; new variables go in the completion note and the runbook.
- Visual baselines belong to PRP-140 in this wave. Empty states appear only without data; if a baseline still moves, do not regenerate it here: report it and let the merge step do it after PRP-140.
- Test directories need unique names (`tests/unit/hosted_real_tenant`, `packages/core/tests/sources_status_core`, `services/workers/tests/sources_status_worker`, `services/api/tests/sources_status_api`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - scripts/gates/hosted_purge_synthetic.py
  - scripts/gates/hosted_real_tenant.py
  - scripts/gates/hosted_demo_seed.py
  - tests/unit/hosted_real_tenant/**
  - tests/unit/gates/test_hosted_demo_seed_refuses.py
  - packages/core/neurosphere_core/sources_status/**
  - packages/core/tests/sources_status_core/**
  - services/workers/neurosphere_workers/sources_status/**
  - services/workers/tests/sources_status_worker/**
  - services/api/neurosphere_api/sources_status/**
  - services/api/neurosphere_api/runtime/builders/sources_status.py
  - services/api/tests/sources_status_api/**
  - tests/security/authz/test_sources_status.py
  - frontend/src/features/source-status/**
  - frontend/src/features/admin/sources/ConnectorsPage.tsx
  - frontend/src/features/admin/sources/ProducersPage.tsx
  - frontend/src/features/admin/sources/hooks.ts
  - frontend/src/features/admin/sources/apiPaths.ts
  - frontend/src/features/admin/sources/types.ts
  - frontend/src/features/admin/sources/strings.ts
  - frontend/src/features/admin/sources/sources.test.tsx
  - frontend/src/features/admin/gateways/RegisterGatewayPage.tsx
  - frontend/src/features/overview/OverviewPage.tsx
  - frontend/src/features/workspaces/WorkspacePage.tsx
  - frontend/src/features/dashboards/DashboardPage.tsx
  - frontend/src/features/dashboards/components.tsx
  - frontend/src/features/reconciliation/ReconciliationPage.tsx
  - frontend/src/features/finops/ForecastPage.tsx
  - frontend/src/features/map/MapPage.tsx
  - frontend/src/features/map-table/MapTablePage.tsx
  - frontend/src/features/replay/ReplayPage.tsx
  - frontend/src/features/catalog/CatalogExplorerPage.tsx
  - frontend/src/features/catalog/StaleAgentsPage.tsx
  - frontend/src/features/quality/QualityPage.tsx
  - frontend/src/features/evaluations/EvaluationsPage.tsx
  - frontend/src/features/recommendations/RecommendationListPage.tsx
  - frontend/src/features/gateways/GatewaysPage.tsx
  - frontend/src/features/audit/AuditPage.tsx
  - frontend/tests/mock-api/features/sourceStatus.ts
  - infra/demo/main.bicepparam
  - infra/appservice/main.bicepparam
  - infra/demo/modules/connector-rbac.bicep
  - scripts/gates/hosted_demo.py
  - scripts/gates/_hosted_demo_common.py
  - tests/unit/hosted_demo/**
  - tests/unit/gates/test_hosted_demo_refuses.py
  - tests/unit/gates/test_hosted_demo_flow.py
  - tests/unit/gates/test_hosted_demo_resume.py
  - tests/unit/gates/test_hosted_demo_teardown.py
  - tests/unit/gates/test_hosted_demo_live_fixes.py
  - tests/unit/hosted_data_path/test_demo_data_path.py
  - tests/unit/delivery_pipeline/test_deploy_hosted_workflow.py
  - docs/deploy/hosted-real-tenant.md
  - docs/evidence/PRP-139/**
tier1:
  - infra/demo/main.bicep
  - infra/appservice/main.bicep
  - services/workers/neurosphere_workers/runtime/factories.py
  - .github/workflows/deploy-hosted.yml
tier2_appends:
  - services/api/tests/runtime_api/test_readiness.py
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/tests/mock-api/features/index.ts
  - docs/runbooks/connector-config.md
  - docs/deploy/hosted-demo.md
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/auth/**
  - packages/core/neurosphere_core/stores/containers.py
  - services/api/neurosphere_api/admin/identity/**
  - frontend/src/features/admin/identity/**
  - frontend/src/app/Shell.tsx
  - frontend/src/app/navigation.ts
  - frontend/src/app/workspaceNav.ts
  - frontend/src/features/**/routes.tsx
  - frontend/tests/e2e/visual/__screenshots__/**
  - scripts/sandbox/**
  - scripts/gates/_hosted_demo_smoke.py
  - scripts/gates/hosted_smoke.py
  - scripts/gates/g04_connectors_live.py
  - services/workers/neurosphere_workers/ingestion/**
  - services/workers/neurosphere_workers/connector_config/**
  - connectors/**
  - infra/helm/**
  - infra/bicep/modules/**
  - .github/workflows/**
```
Plan delta approved by the owner on 2026-11-21 (during execution): making `--data-mode` required breaks every caller that does not pass it, so item 1 also owns the five `tests/unit/gates/test_hosted_demo_*.py` files, `tests/unit/hosted_data_path/test_demo_data_path.py` and `tests/unit/delivery_pipeline/test_deploy_hosted_workflow.py` (argv and assertion updates only), and edits `.github/workflows/deploy-hosted.yml` to pass `--data-mode` and `--customer-id` from two repository variables, failing loudly when the mode variable is unset. Every other workflow file stays must-not-touch. `services/api/tests/runtime_api/test_readiness.py` pins the builder and component lists and gets the one new component name (item 3). Second delta approved by the owner on 2026-11-21: because PRP-140 has not run, the four `admin-connectors` visual baselines moved by item 4 were regenerated in this PR with the Docker baseline script (only the screenshots that changed were kept; the folder stays must-not-touch otherwise). `frontend/tests/mock-api/features/registry.test.ts` pins the mock handler list and gets the one new handler name; `docs/security/snyk-justifications.md` gets one added section.
`infra/demo/main.bicep` and `infra/appservice/main.bicep` are Tier-1 files and this PRP is their single owner in W18b. PRP-138 needs one mapping parameter in `infra/demo/main.bicep`, `infra/demo/main.bicepparam` and `scripts/gates/hosted_demo.py`; it lists those three under `deferred_after_prp_139` and adds its lines in a second small pull request after this PRP has merged (PRP-138 clarification 16 and item 9), so no item here needs a `[serial-after]` tag and none is written. PRP-138 is the Tier-1 owner of `services/api/neurosphere_api/authz/routes.py` in this wave and merges first; this PRP only adds allowlist lines there after rebasing (PRP-138's ownership note says those additions rebase cleanly). PRP-138 also owns `services/api/neurosphere_api/me/**` and `frontend/src/features/admin/shared/AdminStates.tsx`: both are read here as patterns and not edited. `services/workers/neurosphere_workers/runtime/factories.py` is a Tier-1 file with no other owner in W18b; item 3 edits three wrapping lines in the connector builders and nothing else (PRP-137 owns the file in W19 and rebases). `docs/runbooks/connector-config.md` and `docs/deploy/hosted-demo.md` get added lines only (a pointer to the new runbook and the removal of the stale "hosted does not run connector roles" limit is a one-line replacement recorded in the completion note). No file owned by PRP-140 is touched: the empty states live in page files and a new feature folder, and no navigation entry or route is added.

## Implementation blueprint

Parallelization: start items 2, 3, 5 and 6 together (four lanes, no common file). Item 1 takes the first free lane (it shares no file with the others). Item 4 needs item 3 (the API it reads). Item 7 needs 1, 2 and 6. Item 8 last. The branch is cut after PRP-138 and PRP-140 have merged.

### Item 1 - Real-tenant mode and customer id in the hosted templates and deploy script
- Deliverable: parameters `dataMode` and `customerId` replacing the `customerId` variable in `infra/demo/main.bicep` (and the twin); `real-tenant` adds the three connector roles and `NS_API_BASE_URL`, and sets `NS_HOSTED_DATA_MODE` on both sites; parameters `logAnalyticsWorkspaceIds` and `apimServiceIds` with one `connector-rbac.bicep` deployment per id at that resource's scope (workers identity for workspaces, API identity for gateways), role definition ids verified against Learn first (UNVERIFIED items 1 and 2; if an id cannot be verified, ship the parameters with the assignment disabled and say so); `GENERATED_PARAMS` gains the four names; `hosted_demo.py` gains `--data-mode` (required for plan and deploy), the two id-list flags, moves `--customer-id` to the shared flags, refuses `real-tenant` with `synthco` or an invalid segment, refuses `real-tenant` outside `AzureCloud`, and writes `data_mode` and `previous_customer_id` (read from the existing registration when the id changes) to the registration.
- Owned files: `infra/demo/main.bicep`, `infra/demo/main.bicepparam`, `infra/appservice/main.bicep`, `infra/appservice/main.bicepparam`, `infra/demo/modules/connector-rbac.bicep`, `scripts/gates/hosted_demo.py`, `scripts/gates/_hosted_demo_common.py`, `tests/unit/hosted_demo/**` (goldens and composition tests), `tests/unit/hosted_real_tenant/test_mode_params.py`, `test_deploy_flags.py`.
- Must NOT touch: `infra/bicep/modules/**`, `infra/helm/**`, `_hosted_demo_smoke.py`, any teardown or budget logic in `hosted_demo.py` (PRP-67).
- Depends on: nothing. Leave room for PRP-138's later parameter: add new parameters at the end of each parameter group and do not reorder existing ones.
- Acceptance criteria: the first two acceptance criteria; the demo-mode render equals the golden apart from `NS_HOSTED_DATA_MODE=demo`; no parameter, output or setting holds a key, secret or connection string; role assignments exist only at single-resource scope (a test walks the compiled template and fails on a group or subscription scope).
- Tests: `tests/unit/hosted_real_tenant/test_mode_params.py`, `test_deploy_flags.py`; existing `tests/unit/hosted_demo`, `tests/unit/gates/test_hosted_demo_flow.py`, `test_hosted_demo_refuses.py`, `tests/unit/hosted_data_path` pass (update goldens only for the documented additions).
- Pattern references: `infra/demo/main.bicep:254-262,465-493`, `scripts/gates/hosted_demo.py:440-505`, `tests/unit/hosted_demo/test_demo_composition.py`.

### Item 2 - Seed refused by default and the synthetic purge  [P]
- Deliverable: `hosted_demo_seed.py` requires `--demo-environment <deployment id>` equal to the registered deployment id and refuses a registration whose `data_mode` is `real-tenant`, both before any network import. `hosted_purge_synthetic.py` with `plan` (read-only counts per container and for the archive prefix, a plan file under `temp/hosted-demo/` with a content hash, counts-only evidence) and `apply` (checks of the acceptance criteria, re-reads each selected document and re-applies the synthetic test before deleting, deletes in bounded batches, stops at the first unexpected document, writes evidence with `deleted`, `kept` and `skipped` counts). Selection rules live in one pure module function `is_synthetic(container, document, purge_customer) -> bool` with the closed rule table of clarification 4; stores are reached through small protocols so tests use in-memory twins.
- Owned files: `scripts/gates/hosted_demo_seed.py`, `scripts/gates/hosted_purge_synthetic.py`, `tests/unit/gates/test_hosted_demo_seed_refuses.py`, `tests/unit/hosted_real_tenant/test_purge_selection.py`, `test_purge_refusals.py`, `test_purge_property.py`, `test_purge_evidence.py`.
- Must NOT touch: `scripts/sandbox/**` (import `sbx_guard` and the seed's id helpers read-only, as `hosted_demo_seed.py:68-72` does).
- Depends on: nothing (reads `data_mode` with a default of `demo` when the field is absent).
- Acceptance criteria: the seed and the three purge criteria; `apply` without `NS_LIVE_APPROVED=1` exits 2 before importing an Azure client; a plan older than 24 hours or with changed counts is refused; a container the rule table does not name is never opened; evidence passes the repository's redaction test (no GUID, no host).
- Tests: the files above; the property test builds random stores mixing synthetic, real-customer and same-customer non-sandbox documents and asserts no real document is ever in the delete set.
- Pattern references: `scripts/gates/hosted_demo_seed.py:86-123`, `scripts/sandbox/sbx_guard.py:171-243`, `scripts/gates/hosted_demo.py:329-330` (`teardown --confirm <deployment id>`, the confirmation value style).

### Item 3 - Connector run status and the source status API  [P]
- Deliverable: core `sources_status` package (model, repository over the admin config store with record kind `connector_run_status`, `summarize`, reason codes, mapping of provider 401 and 403 to `source_access_denied`); worker `StatusRecordingTick` that runs the wrapped tick, reads the poller's `last_status`, maps it to a `ConnectorRunStatus` and stores it (a store failure is logged once and never fails the tick); three wrapping lines in `build_gateway_poll`, `build_foundry_discovery` and `build_billing_export` plus an `idle` or `not_configured` write on the idle branches; API package with the two routes and a builder `runtime/builders/sources_status.py` (optional component).
- Owned files: `packages/core/neurosphere_core/sources_status/**`, `packages/core/tests/sources_status_core/**`, `services/workers/neurosphere_workers/sources_status/**`, `services/workers/tests/sources_status_worker/**`, `services/workers/neurosphere_workers/runtime/factories.py` (wrapping lines only), `services/api/neurosphere_api/sources_status/**`, `services/api/neurosphere_api/runtime/builders/sources_status.py`, `services/api/tests/sources_status_api/**`, `tests/security/authz/test_sources_status.py`, Tier-2 lines.
- Must NOT touch: `ingestion/**` pollers, `connector_config/**`, contracts, `stores/containers.py`.
- Depends on: nothing.
- Acceptance criteria: the run status and the API criteria; the summary for Application Insights telemetry is always `not_connected` with reason `not_available_in_release`; no id, host or token in any stored status or response (a test scans serialized output for GUIDs and URLs); existing `services/workers/tests/{worker_roles,foundry_discovery_role,gateway_poll,billing_export_role}` suites pass unchanged; routes are in the inventories and boot under `verify_route_permissions`.
- Tests: the new suites; `tests/security/authz/test_sources_status.py` (viewer of one domain reads the summary, no-domain and expired users get 403, only customer-level `config.manage` reads the admin view, a domain admin gets 403 `customer_scope_required`).
- Pattern references: `gateway_poll/poller.py:440-467`, `connector_config/resolve.py:89-108` (bounded store read, a failure is one log line), `services/api/neurosphere_api/admin/sources/connectors/router.py`, `me/router.py:51`.

### Item 4 - Connect and health on the admin Sources pages
- Deliverable: the Connectors page gets a "First sources" panel listing the four sources with state, last success and a "Connect" action that opens the existing create form pre-set to the kind (Foundry, gateway poll, billing export; Application Insights shown as not available with the reason), a run status column with reason text, and a short "what access this needs" note per kind taken from the table in this PRP; the Producers page empty state links to the Connectors panel. No new route and no navigation change.
- Owned files: `frontend/src/features/admin/sources/{ConnectorsPage.tsx,ProducersPage.tsx,hooks.ts,apiPaths.ts,types.ts,strings.ts,sources.test.tsx}`, `frontend/tests/mock-api/features/sourceStatus.ts`, one line in `frontend/tests/mock-api/features/index.ts`.
- Must NOT touch: `frontend/src/features/admin/sources/routes.tsx`, `frontend/src/features/admin/identity/**`, `frontend/tests/mock-api/server.ts`.
- Depends on: item 3 (response shape).
- Acceptance criteria: the Connectors page criterion; `source_access_denied` renders the role and resource kind and the sentence that the owner approves access; axe passes on the page in the three themes the suite uses; no secret field is added.
- Tests: `sources.test.tsx` additions; frontend lint, typecheck, unit tests.
- Pattern references: `ConnectorsPage.tsx:273` (the empty branch the panel replaces), `frontend/src/features/admin/system/SystemPage.tsx:67-114` (state table).

### Item 5 - Source-aware empty states on the pages  [P]
- Deliverable: `features/source-status/` with `useSourceStatus` (one cached query of `GET /api/v1/sources/status`; on error the pages fall back to their current text), `NoDataEmptyState` (wraps the shared `EmptyState` and passes `action`: a link to `/admin/sources/connectors` for users whose roles show Admin, otherwise the "ask an administrator" text; variant text for `connected_no_data` with the last success time), strings; each page in the inventory table marked "source-aware" or with a named change swaps its empty branch for it, keeping existing test ids.
- Owned files: `frontend/src/features/source-status/**` and the page files listed in the ownership block from `overview/OverviewPage.tsx` to `audit/AuditPage.tsx`, plus `admin/gateways/RegisterGatewayPage.tsx`; a test file beside each page or additions to the page's existing test.
- Must NOT touch: `frontend/src/app/**`, any `routes.tsx`, `frontend/src/design-system/**` (the shared component already has the `action` slot), visual baselines.
- Depends on: nothing at build time (mock API handler from item 4's file; if item 4 is not merged in the lane, a local handler in the test).
- Acceptance criteria: the empty-state criterion for every listed page; no page shows an error panel for an empty list; pages keep their current behaviour when data exists; the role workspace pages no longer show the placeholder sentence; `frontend/tests/e2e/demo-audit.spec.ts` still passes (demo mode has data).
- Tests: one assertion per page for the link target and one for the non-admin text; `pnpm --filter @neurosphere/frontend test`, lint, typecheck, `test:e2e`.
- Pattern references: `frontend/src/design-system/components/states.tsx:38-57`, `features/map/map.test.tsx:804-805`.

### Item 6 - Access plan, approved apply, worker bootstrap and verify  [P]
- Deliverable: `hosted_real_tenant.py`. `access-plan` (no approval needed, no Azure write): from `--foundry-account-ids`, `--log-analytics-workspace-ids`, `--apim-service-ids`, `--billing-export-storage-account-id` and the registration it writes a table of assignments (identity: workers or API; role name and definition id; scope: the one resource), the equivalent `az role assignment create` lines and a plan file with a hash. `access-apply`: `NS_LIVE_APPROVED=1`, `--approve-plan <hash>`, one `--approve-assignment <token>` per row, refuses anything not in the plan and any scope that is not a single resource id, records applied, already present and skipped. `bootstrap-worker`: grants the workers principal `viewer` on `--domain-ids` under the active customer through `sbx_grant_operator.grant_operator` (hosted guard, Entra only). `verify`: calls the hosted API with the operator's token for per-source counts (catalog entities marked Foundry, gateway registrations and their `poll_status`, billing source in reconciliation, source status summary) and for zero synthetic records, with a bounded retry for role propagation; writes `PASS | FAIL | OPEN` per source.
- Owned files: `scripts/gates/hosted_real_tenant.py`, `tests/unit/hosted_real_tenant/test_access_plan.py`, `test_access_apply_refusals.py`, `test_bootstrap_worker.py`, `test_verify_report.py`.
- Must NOT touch: `scripts/sandbox/**`, `hosted_demo.py` (item 1 owns it).
- Depends on: nothing (reads the registration; the two new fields default when absent).
- Acceptance criteria: the access and verify criteria; every `az` call goes through one injectable function so tests run with a fake; a role whose definition id is still UNVERIFIED is printed with the word UNVERIFIED and cannot be applied; no command writes to a governed resource other than a role assignment on it.
- Tests: the files above (argument parsing, refusal order, plan hash, scope check, redaction of ids in evidence).
- Pattern references: `scripts/gates/g04_connectors_live.py` (per-step approval), `scripts/gates/hosted_demo.py:1538-1600` (`seed-access` grant and register), `docs/evidence/G17/README.md` (hashing subscription ids).

### Item 7 - Runbook and the live gate definition
- Deliverable: `docs/deploy/hosted-real-tenant.md`: prerequisites (VPN, PRP-138 deployed or the D20 stopgap, the owner's list of resources to govern, an existing Cost Management export, gateway diagnostics `GatewayLogs` and `GatewayLlmLogs` sent to the workspace, a producer secret placed in Key Vault by the operator); the cut-over in the order of clarification 5 with exact commands, including `--budget-start-date 2026-10-01`; what each source reads and does not read (metadata only, capture off); what is disabled when access is missing; rollback; a section "not run by this PRP". `docs/evidence/PRP-139/README.md`: the gate rows, what PASS needs and that real evidence files are added only by operator runs. Added lines in `docs/deploy/hosted-demo.md` (pointer; seed step marked demo environments only) and `docs/runbooks/connector-config.md` (limit updated).
- Owned files: `docs/deploy/hosted-real-tenant.md`, `docs/evidence/PRP-139/README.md`, `tests/unit/hosted_real_tenant/test_runbook_commands.py`, the two added-line edits.
- Must NOT touch: other `docs/evidence/**`, `docs/deploy/delivery.md`.
- Depends on: items 1, 2 and 6.
- Acceptance criteria: every command in the runbook parses against the real parsers in an offline test; no placeholder looks like a real id; the runbook names `aifndry-loom-centralus` only in the sentence that says it is not a default target.
- Tests: `tests/unit/hosted_real_tenant/test_runbook_commands.py`, `tests/docs`.
- Pattern references: `tests/unit/hosted_demo/test_runbook_commands.py`, `docs/deploy/hosted-demo.md:544-597`.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends, `mkdocs.yml` nav line, regenerate Tier 3 (`openapi.json`, `docs/reference/**`, PRP index, status table, execution plan), changelog fragment `changelog.d/PRP-139-hosted-environment-real-tenant-data.md`, the G04 row note in `docs/RESEARCH-AND-GATES.md` (still OPEN, now with the hosted path), completion note with the OPEN live gate, the env vars for the operator and the product check: can the owner connect Foundry from the console and see their own agents without editing a file?
- Owned files: Tier-2 lines, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/hosted_real_tenant tests/unit/hosted_demo tests/unit/gates tests/unit/hosted_data_path packages/core/tests/sources_status_core services/workers/tests/sources_status_worker services/workers/tests/worker_roles services/workers/tests/foundry_discovery_role services/workers/tests/gateway_poll services/workers/tests/billing_export_role services/api/tests/sources_status_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz services/api/tests/test_openapi_drift.py tests/docs
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No emulator run is needed; if one is wanted for the status store, hold the compose stack alone in the wave (use 127.0.0.1 endpoints).

## Migration and rollback
No schema change and no new container. `dataMode` defaults to `demo` and `customerId` to `synthco`, so an existing deployment redeploys unchanged until the operator passes `real-tenant`. The cut-over changes app settings and role lists (a restart) and, if approved, adds role assignments. Rollback before the purge: redeploy with `--data-mode demo --customer-id synthco`; the synthetic estate is visible again and nothing was lost. Rollback after the purge: the synthetic data is gone on purpose; a demo environment is rebuilt with the seed and `--demo-environment`. Role assignments are removed with the `az role assignment delete` lines the access evidence lists. `connector_run_status` rows are inert without the API route; revert the PR to remove the code.

## Live and open gates
Gate "hosted real tenant" (operator-run, `NS_LIVE_APPROVED=1`, owner approval of each role assignment, point-to-site VPN). OPEN: nothing here was run by this PRP. It is PASS only when `docs/evidence/PRP-139/` holds, from one environment after the cut-over:
1. Foundry: at least one real agent or model deployment from an owner-named project is visible in the catalog UI. OPEN.
2. API Management gateway: at least one registered real gateway with `poll_status` ok and gateway traffic on a dashboard. OPEN (needs a gateway with LLM logs to a workspace).
3. Cost and billing: invoiced spend of a closed month from the owner's export in the reconciliation view. OPEN (needs an existing export and a closed month).
4. Azure Monitor and Application Insights AI call telemetry. OPEN, owned by the follow-up PRP.
5. Synthetic records: purge evidence with deleted counts, and `verify` showing zero records of the synthetic customer and source. OPEN.
6. Access: the access evidence lists exactly the approved assignments, each at single-resource scope. OPEN.
The G04 connector gate (`docs/connectors/coverage.md:9-19`) stays OPEN and is not replaced by this gate.

## Split and follow-up
This PRP is sized for one session with four parallel lanes because three of the four sources run on shipped code. One piece does not fit and is proposed as a separate PRP (number assigned by the planner, wave after W18b): "Application Insights and Log Analytics AI call telemetry reader": a verified query for model and agent call records in workspace-based Application Insights, a mapping to `TelemetryEvent` with the same column-allowlist privacy rule as the gateway tables, a worker role or a `connector_runner` connector (decide against PRP-117's timing), the read role and scope, and row 4 of the live gate. If the wave is short of capacity, item 5 (empty states, 17 page files) is the second candidate to split out; it has no dependency on the other items except the status route.

## NOT building
A demo world in a hosted environment; a copy of grants or stored configuration from `synthco` to the new customer; deletion of audit chains by default; a hot reload of connector configuration; a generic connector runner, estate connectors or the Coverage page (PRP-117); the Application Insights telemetry reader (follow-up); content capture or any body or header column; Government or a Commercial bridge for Government data; role assignments at resource-group or subscription scope; creation of exports, workspaces, gateways or Foundry resources; a fix for the budget start date (PRP-67); navigation entries or routes (PRP-140); Entra role mapping (PRP-138); the signed-in navigation walk (PRP-82).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 4, 8 and 10 are ASSUMPTIONS for plan approval; six Azure facts are UNVERIFIED and are checked against Learn at session start)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-ad803c20d47ee4848 | sonnet; commits bc59a6a0 + rework 3ad6b510; review APPROVE; merge e431c66b 2026-11-21; 821 passed after merge, ruff clean, validate_planning PASS; PRP-138 item 9 follows this in a second PR |
| 2 | merged | worktree-agent-ac77cef87f7e57b4c | sonnet; verify PASS (ruff, format, pyright clean; 494 passed); review APPROVE; merge bbd7548d 2026-11-21 (603 passed after merge); fix-forward merged 5830df4b (no customer_id refused; delete failure writes counts-only evidence) |
| 3 | merged | worktree-agent-a470d8a5dac59dee8 | sonnet; review APPROVE; merge 67d30ce2 2026-11-21; test_readiness component list updated; 664 passed after merge, ruff and pyright clean; follow-ups: billing read_failed reads as access denied, status write timeout, observer outside try |
| 4 | merged | worktree-agent-addea16bafbf68e19 | sonnet; commit 64da8a20; review APPROVE (combined with item 5); merged 2026-11-21; mock registry list updated; full frontend unit run 1343 passed, 11 failed in two untouched files (render-config.test.ts 5 s shell timeouts on Windows; admin-audit passes alone); lint, typecheck clean |
| 5 | merged | worktree-agent-a2b7f4c41d263947b | sonnet; commit d49044a4; review APPROVE (combined with item 4); merge 9419ea87 2026-11-21; 389 passed in touched features after merge |
| 6 | merged | worktree-agent-a1b622567415a0fac | sonnet; verify PASS (ruff, pyright clean; 492 passed); review APPROVE; merge 20e0bb5a 2026-11-21; fix-forward merged 5830df4b (truncated scan reports OPEN; 552 passed) |
| 7 | merged | worktree-agent-ada3d1f4bae24870e | sonnet; commit 8b08154b; merged 2026-11-21; mkdocs nav line added; docs review not required (parser test covers every runbook command) |
| 8 | merged | prp-139-hosted-real-tenant-data | orchestrator; Tier-3 regenerated, changelog fragment, G04 note, 4 admin-connectors baselines regenerated (owner-approved), Snyk scan (3 new packages clean, 2 low findings justified); PR 369 CI 33 passed, squash merge dc6fbdac 2026-11-21 |

## Completion note (filled at ship)
- Date, PR: 2026-11-21, PR #369, squash merge `dc6fbdac`. CI on the merged head: 33 checks passed, 1 skipped (Pages deploy does not run on a pull request). Item merges on the integration branch: 6 `20e0bb5a`, 2 `bbd7548d`, fix-forward `5830df4b`, 3 (merge before `0d17b6b3`), 1 `e431c66b`, 5 `9419ea87`, 4 and 7 (before `787ba239`).
- Deviations:
  - Ran before PRP-140 (the order was moved up on 2026-11-21); no file is shared with it. The four `admin-connectors` visual baselines moved by item 4 were regenerated here with owner approval; no other baseline moved.
  - `--data-mode` being required broke every caller that did not pass it. With owner approval item 1 also edited six test files and `.github/workflows/deploy-hosted.yml`, which now fails when the repository variable `NS_HOSTED_DATA_MODE` is unset.
  - Additive lines outside the original ownership block: `services/api/tests/runtime_api/test_readiness.py`, `frontend/tests/mock-api/features/registry.test.ts` (pinned lists), `docs/runbooks/system-settings.md` (checklist item `optional.sources_status`), `docs/security/snyk-justifications.md`, `.gitleaksignore`.
  - Item 1: the twin's `customerId` defaults to an empty string, not `synthco`, so the setting is not duplicated; the demo template still defaults to `synthco`. The registration also gains `api_principal_id`.
  - Item 2: the seed's recommendations, evaluation runs and intents are selected by observed fields (fixed `created_at` stamp, `seed-offline-` run id prefix, seed intent keys) under the purge customer, not by ids recomputed from the seed's functions; MCP servers by the three fixture host names. `plan` refuses on the same registration checks as `apply`.
  - Item 3: the gateway poller has no `last_status`, so its store is wrapped to observe each tick; status rows are written with `doc_type: connector_run_status` into the admin config container without going through `AdminConfigRepository`; the builder is registered before `admin` (two existing tests pin `admin` and `analytics` as the last two); `authz/routes.py` needed no line.
  - Item 5: role workspace pages show the shared empty state only when an available source is not connected, otherwise the role's page links; page assertions live in one file `source-status/pages.test.tsx`; the Quality "no drift alerts" text is unchanged.
  - Item 7: the runbook holds no GUID (an existing docs test rejects them under `docs/deploy/`); the role definition ids are in `docs/evidence/PRP-139/README.md`. The test file is `test_real_tenant_runbook_commands.py`.
  - Review: one reviewer each for items 1, 2, 3 and 6, one combined pass for items 4 and 5, none for item 7 (owner's choice). All approved with no blocker. Three review findings were fixed forward (truncated catalog scan reports OPEN; purge refuses a registration without `customer_id`; a failed delete writes counts-only evidence). Two defects found by the local Playwright run after the merges were fixed before the PR went green (a button-role link in the empty state; link target size on workspace pages).
  - The orchestrator ran on Fable, not Sonnet as the frontmatter says; implementers ran on Sonnet.
- Descoped items: none.
- OPEN gates: "hosted real tenant", all six rows OPEN; nothing was run against Azure by this PRP (`docs/evidence/PRP-139/README.md`). G04 stays OPEN. Also unverified: whether API Management Service Reader alone can read the service's diagnostic settings (the Monitoring Reader row cannot be applied); the role for the optional `customMetrics` query; Foundry User at account scope listing every project's agents in practice; the purge's real Cosmos and Blob adapters (in-memory twins only); the `bootstrap-worker` grant path (type-checked only).
- Env vars for the operator: app setting `NS_HOSTED_DATA_MODE` (`demo` or `real-tenant`, set by the template). Repository variables for `deploy-hosted.yml`: `NS_HOSTED_DATA_MODE` (required), `NS_HOSTED_CUSTOMER_ID`, `NS_HOSTED_LOG_ANALYTICS_WORKSPACE_IDS`, `NS_HOSTED_APIM_SERVICE_IDS`. Operator runs need `NS_LIVE_APPROVED=1`, and `bootstrap-worker` and `verify` need `NS_SANDBOX_HOSTED_DEPLOYMENT_ID`.
- Follow-up issues: #370 (gate script hardening), #371 (connector run status robustness), #372 (source status UI polish), #373 (settle the gateway read roles in a live run). Existing #329 (flaky G01 scrubber test) failed twice on this PR and passed on the third run. Application Insights AI call telemetry is PRP-141.
- Product check (can the owner connect a source and see their own tenant without editing files): built, not proven. The path exists end to end in code: redeploy in real-tenant mode, approve the access plan, create a domain, then use Connect on the Connectors page for Foundry, and the page shows the run state and the reason when access is missing. It has not been run against a real tenant, so the answer stays "unverified" until the operator gate has evidence.
