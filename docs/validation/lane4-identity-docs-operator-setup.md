# Lane 4: identity, docs, enablement and the operator setup experience (2026-11-06)

Scope: PRD NS-08 and NS-10, plus the cross-cutting question "how does an administrator stand the
system up". Method: read-only static trace per `RUBRIC.md`, plus targeted test runs. No docker, no az.

Tests I ran (all in-memory twins: dev-issuer tokens, in-memory policy store, in-memory audit
repository; none hit Cosmos):

- `uv run pytest services/api/tests/authz services/api/tests/audit -q` -> 195 passed (98 s).
- `uv run pytest services/api/tests/workspaces_api services/api/tests/auditor_access services/api/tests/sandbox_api services/api/tests/me_api -q` -> 85 passed (65 s).

Nothing below is classed WORKS on the strength of static reading. WORKS appears only where one of
those runs exercised the real router path, and even then the store was an in-memory twin, which I
state in each row.

## 0. Headline findings

1. There is no admin console and no first-run wizard. `grep` over `frontend/src` finds no
   settings, onboarding or setup feature. Setup is: Bicep/Helm params, about 60 `NS_*` env vars, JSON
   files on disk, and operator scripts under `scripts/gates/` and `scripts/sandbox/`.
2. Nobody can assign a role to a user through the product. Authority is the Cosmos policy
   container (`auth/scope/policy.py:108-114`: "Read side of the policy store. Writes belong to the
   (audited) admin path"). That admin path does not exist: no router, no UI. The only writer is the
   operator script `scripts/sandbox/sbx_grant_operator.py` (one principal, one role, emulator or
   `--hosted`). `hosted-demo.md:297-303` says "other users need their own grants through the
   product"; the product has no such feature. Entra app roles are display-only (derivation.py:5-7).
3. `/workspaces/*` pages are placeholders. The backend returns `items=[]` after a role check
   (`workspaces/router.py:92`), and the page prints "Placeholder: this workspace is built out in
   later work" (`WorkspacePage.tsx`). `/workspaces/admin` ("Deployment, connectors and policy
   administration", `personas.ts`) administers nothing.
4. `main` is not deployed by any pipeline. Workflows: ci, codeql, contracts, dependabot-licences,
   docs, release, secret-scan, security. None logs in to Azure. The hosted env is created by the
   operator running `scripts/gates/hosted_demo.py` (preflight/plan/deploy/seed-access/smoke) by hand.
   `release.yml` only runs on `v*.*.*` tags or manual dispatch; both GitHub releases (`v0.1.0-rc.1`,
   `rc.2`) are Drafts. GitHub Pages returns 404 (docs site never published).
5. Several pillars the PRD calls foundational have no UI or API at all: revocation (service exists,
   no route), policy/role admin, retention/legal-hold/erasure (worker + core only), budgets and
   price sheets (file or Azure Budget only), ingest-producer registration (JSON file of hashes),
   domain creation (implicit strings in the policy store), connector credentials, agency theme/logo
   (compile-time `packs.ts`).

## 1. Summary table

Classes: WORKS / PARTIAL / MOCK-ONLY / MISSING. "Op-config" = how an admin changes it today.

| Capability | PRD | PRP(s), tracker | Class | Op-config | Evidence |
|---|---|---|---|---|---|
| Entra sign-in (SPA, MSAL) and API JWT validation | NS-08 | 04 shipped; 06 shipped; 29 shipped | PARTIAL | env + script | 195 authz tests pass with dev issuer; real Entra proven only by operator gate scripts (`prp06_entra_live.py`, `p29_entra_local.py`), not run by me: UNVERIFIED live |
| Entra app registration and app-role creation | NS-08 | 29 | PARTIAL | script only | `scripts/gates/p29_entra_local.py` (dry-run default, `--apply` needs `NS_LIVE_APPROVED=1`); app roles are not authority |
| Role/scope derivation, fail-closed, no god-mode | NS-08 | 06 shipped | WORKS (in-memory) | env (`NS_AUTH_*`) | `authz` tests 195 pass; `derivation.py:1-24`; `authz/routes.py` boots-fails on undeclared route |
| Assign roles / domains / grants to users | NS-08 | 06 shipped | MISSING (UI+API); PARTIAL (script) | script only | no write route; `policy.py:108-114`; `sbx_grant_operator.py` one principal at a time |
| Time-bound privileged access | NS-08 | 06 | PARTIAL | script only | enforced by model (`policy.py:75`, `PRIVILEGED_ROLES`); grant script hardcodes 30-day expiry, renews at under 7 days |
| Principal revocation | NS-08 | 06 | PARTIAL | not configurable | `auth/revocation/service.py` exists, no HTTP router; only used in `tests/runtime_data/test_revocation_push_closer.py` |
| Audit log recording (hash chain, per domain) | NS-08 | 06, 17 | WORKS (in-memory) | env for SIEM sink | `audit` tests pass; chain per `<customer>.<domain>` (`ui_adapters/audit.py:14`) |
| Audit log query/verify in UI | NS-08 | 31 item 5 merged | PARTIAL | UI | `/audit` -> `GET /api/v1/audit/domains/{d}/records,/verify` (`ui_adapters/audit.py`); auditor_access tests pass (in-memory). No search, no filter, no export button (`AuditPage.tsx:253` "nothing is enriched, joined or exported here") |
| Audit export to SIEM | NS-08 | 06 | PARTIAL | env only | `NS_AUDIT_SIEM_SINK=none|stdout|file`, `NS_AUDIT_SIEM_FILE_PATH` (`runtime/settings.py`); no Sentinel/Splunk/Event Hub sink |
| Self-observability (logs, metrics, OTel) | NS-08/NS-03 | 05 (tracker: backlog, no exec table) | PARTIAL | env | `/healthz`, `/readyz` w/ composition reasons; `observability/{jsonlog,metrics,telemetry}.py`; App Insights exporter only when `env != local` and a connection string is passed (`telemetry.py:67`); no doc of how to set it: UNVERIFIED who passes the string |
| Workspaces per persona | NS-10 | 28 shipped | MOCK-ONLY (content) / WORKS (gate) | not configurable | role check works (`workspaces_api` tests pass); body is `items=[]`, page says "Placeholder" |
| Theme packs (light/dark/HC, tokens) | NS-10 | 24, 30 shipped | WORKS (client) | UI per-user (localStorage `ns.theme`) | `design-system/themes/*`, `theme-store.ts:11`; vitest not run by me: UNVERIFIED run |
| Agency branding/logo | NS-10 | 24 | PARTIAL | code only | add `ThemePack` to `packs.ts`, rebuild; `LogoSlot.tsx` is an empty slot; no config.json field for packs, only deployment default UI style |
| Accessibility gates (axe, keyboard) | NS-10 | 24 shipped | PARTIAL | CI | axe e2e on mocked API (`frontend/tests/e2e/a11y/`); manual sections all "OPEN (unsigned)" (`docs/accessibility/README.md:56`); no conformance claim |
| Docs site (MkDocs) | NS-10 | 25 (tracker: backlog; note says shipped 2026-11-02, PR 154) | PARTIAL | repo | `mkdocs.yml`, `.github/workflows/docs.yml`; Pages API 404: never published |
| Public docs assistant | NS-10 | 25 | PARTIAL | operator hosts | `services/docs-assistant` (BM25 over built HTML, `StubModel` default, no model); not in any IaC (`grep` of `infra/` finds nothing); README: "hosting it is not done by this repository" |
| Runbooks | NS-10 | 25 | PARTIAL | n/a | all labelled DRAFT; `new-user-test.md` is an unfilled template; no independent tester followed `install.md` |
| Sandbox mode and synthetic data | NS-10 | 03, 24, 35 | PARTIAL | UI toggle + make/script | `/sandbox` UI + `GET /sandbox/status,entities`, `POST /sandbox/reset`; sandbox repository installed only when `NS_ENV=local` (`runtime/builders/data.py` doc); hosted returns 503. sandbox_api tests pass (in-memory) |
| ATO evidence accelerator | NS-08 | 23 (tracker: backlog; note says done) | PARTIAL | scripts | `scripts/compliance/collect_evidence.py`, `check_statements.py`, `docs/compliance/{ssp,plans,poam.md,responsibility-matrix.md}`; no UI, no API; G02/G06 OPEN by design |
| Data lifecycle: retention, erasure, legal hold | NS-03/08 | 23 | PARTIAL | worker/core only | `services/workers/neurosphere_workers/lifecycle/`, `packages/core/neurosphere_core/lifecycle/`; no API route in `neurosphere_api` references lifecycle policy; no UI; hosted worker role `lifecycle` runs |
| Government deployment | NS-08 | 20 (tracker: backlog, reopened by audit 2026-11-04) | PARTIAL / OPEN | IaC + params | `infra/bicep/params/government/*`, `infra/helm/values-government.yaml`; `sovereign-profile.yaml` read by no running code (PRP-20 audit); no Government evidence in `docs/evidence/G02/` besides register |
| Release and container publishing | NS-10 | 13 shipped | PARTIAL | tag/dispatch | `release.yml` (GHCR + cosign + SBOM + Helm OCI); only 2 rc Drafts exist; no published release; image publish never observed live by me: UNVERIFIED |
| Platform deployment (Bicep/Helm/hosted env) | NS-04/10 | 08, 21, 32 shipped | PARTIAL | IaC + operator script | `infra/demo` (App Service), `infra/bicep` (AKS-style modules), `infra/helm`; deployed by `hosted_demo.py` by hand; no CD; hosted runbook says all S1-S10 are OPEN until operator evidence (note: PRP-32 shipped 2026-10-28) |
| Operator setup experience (wizard/console) | all | none specifically | MISSING | n/a | section 2 |
| Admin pages: execution-control, mcp-admin, gateways, workspaces/admin | NS-07/09 | 17, 22, 31, 33 | see section 3 | UI | section 3 |

## 2. Everything an admin must configure and where

Columns: item | where configured today | documented in a runbook | wizard/admin page exists.
"Env" means an environment variable on the api or workers app (App Service settings, Helm env,
compose). Sources: `runtime/settings.py`, `runtime/builders/*.py`, `docs/runbooks/runtime-composition.md`,
`docs/runbooks/ingest.md`, `docs/deploy/hosted-demo.md`, `infra/helm/values.yaml`,
`frontend/src/app/config.ts`.

### 2.1 Platform and infrastructure

| Item | Where today | Runbook | UI |
|---|---|---|---|
| Azure resources (Cosmos, Event Hubs, Storage, Key Vault, optionally Search, APIM, Log Analytics) | Bicep `infra/bicep/modules/*`, `infra/demo/*`, params `infra/bicep/params/{commercial,government}/main.bicepparam`, `infra/appservice/main.bicepparam` | yes, `docs/AZURE-DEPLOYMENT.md` (requirements doc, v1.1), `docs/deploy/hosted-demo.md` (Commercial demo only) | no |
| Hosted deploy of the three sites (web, api, workers) | `scripts/gates/hosted_demo.py preflight/plan/deploy/smoke/teardown`; manual, needs `NS_LIVE_APPROVED=1` | yes, hosted-demo.md (status: every live step OPEN) | no |
| Kubernetes install (Helm) | `infra/helm/values.yaml`, `values-government.yaml` | partial: install.md "Hosted" pointer; ingest.md Helm section | no |
| Container images | `release.yml` tag push -> GHCR | yes, `docs/release/release-process.md`, `verify.md` | no |
| Cloud profile | env `NS_CLOUD` (commercial/government), `NS_ENV` | partial | no |
| Cosmos account and database | env `NS_STORE_COSMOS_ACCOUNT` (non-local, managed identity), `NS_STORE_DATABASE`; local `NS_COSMOS_ENDPOINT`/`NS_COSMOS_KEY` | yes (runtime-composition) | no |
| Cosmos containers | provisioned by compose locally (`infra/compose/cosmos-containers.json`) or IaC; builders never create them | partly | no |
| Event Hubs | `NS_EVENTHUBS_CONNECTION_STRING` (local), hub/consumer-group env `NS_INGESTION_EVENTHUB_NAME`, `NS_INGESTION_CONSUMER_GROUP` | yes (ingest.md) | no |
| Blob/archive | env `NS_ARCHIVE_STORAGE_ACCOUNT`, `NS_ARCHIVE_CONTAINER`, `NS_BLOB_CONNECTION_STRING` (local) | thin | no |
| Network (private endpoints, VPN, DNS, egress default-deny) | Bicep `infra/bicep/modules/network`, hub PE module, Helm `networkpolicy.yaml` | hosted-demo.md only | no |
| Azure budget | Bicep param `budgetAmount` (`infra/demo/modules/budget.bicep`, default 200) | hosted-demo.md | no |

### 2.2 Identity and access

| Item | Where today | Runbook | UI |
|---|---|---|---|
| Entra API app registration, SPA redirect URIs, app roles (`viewer, analyst, domain_steward, admin, security_auditor`) | `scripts/gates/p29_entra_local.py` (`--apply`) or hand in Entra portal; hosted: `hosted_demo.py entra-redirect` | yes (local-setup.md, hosted-demo.md) | no |
| Tenant/audience binding of the API | env `NS_AUTH_TENANT_ID`, `NS_AUTH_AUDIENCES` (comma list), `NS_AUTH_CUSTOMER_ID` | partial | no |
| Principal pseudonym key | Key Vault ref -> env `NS_AUTH_PSEUDONYM_KEY` + `NS_AUTH_PSEUDONYM_KEY_REFERENCE`; required outside local | `docs/security/runbooks/key-vault-references.md` | no |
| Policy container name | env `NS_AUTH_POLICY_CONTAINER` | no | no |
| Frontend runtime config (`/config.json`: cloud, tenantId, clientId, apiBaseUrl, apiScope, default UI style) | static file served beside the SPA; dev uses `VITE_NS_*` | `config.ts` header only; unverified which IaC writes it in hosted: UNVERIFIED | no |
| User -> app role assignment in Entra | Entra admin center (Enterprise applications, Users and groups) | yes, hosted-demo.md:297 | no (Entra) |
| User -> NeuroSphere role, domain membership, resource grants (the real authority) | Cosmos policy docs, written only by `scripts/sandbox/sbx_grant_operator.py` (`make grant-operator OPERATOR_OID=... OPERATOR_ROLE=admin`) for ONE operator; `--hosted <registration.json>` mode | yes for the operator only (operations.md:40) | no route, no page |
| Revoke a principal | no entry point (service exists in `neurosphere_core/auth/revocation`); settings `NS_REVOCATION_*` | no | no |
| CORS origins | env `NS_CORS_ALLOWED_ORIGINS` | runtime-composition | no |
| MCP server auth (resource URL, audiences, scope) | env `NS_MCP_RESOURCE_SERVER_URL`, `NS_MCP_AUDIENCES`, `NS_MCP_REQUIRED_SCOPE`; MCP audiences must differ from REST ones | partial | no |

### 2.3 Data in: ingest, connectors, workers

| Item | Where today | Runbook | UI |
|---|---|---|---|
| Ingest producers (id, SHA-256 secret digest, customer, cloud, source map) | JSON file named by env `NS_INGEST_PRODUCERS_FILE` (Helm `ingest.producersFile` or `ingest.producersConfigMap`); unset -> `503 ingest_not_configured` | yes, ingest.md | no |
| Producer secrets handed to agents | out of band by the operator | yes (ingest.md: "secret channel") | no |
| Ingest limits | env `NS_INGEST_RATE_LIMIT_RPS`, `NS_INGEST_RATE_LIMIT_BURST`, `NS_INGEST_MAX_BODY_BYTES` | partial | no |
| Worker roles to run | env `NS_WORKER_ROLES` (six roles hosted: ingestion, projections, aggregates, actions, hitl_timers, lifecycle; `all` locally) plus `NS_WORKER_TENANT_ID`, `NS_WORKER_OBJECT_ID` (worker principal must be granted in the policy store: the seeder does it locally) | hosted-demo.md, runtime-composition.md | no |
| Recommendations and evaluation worker roles | exist (`NS_WORKER_REC_DATA_DIR`, `NS_WORKER_EVAL_DATA_DIR`, read compose-mounted data); NOT run hosted, the seeder writes their output | hosted-demo.md:484 | no |
| Azure Monitor / APIM gateway polling | env `NS_GATEWAY_POLL_*` (`DOMAIN_IDS`, `METRICS_APP_ID`, `API_BASE_URL`, interval, window...), `NS_GATEWAY_POLL_PRODUCER_SECRET` | partial (g17 gate docs); UNVERIFIED a runbook | no |
| Connectors for external providers (Anthropic, Google, Graph, GitHub Copilot...) | `connectors/` SDK and reference connectors; credentials: nowhere in product; PRP-09 is backlog | `docs/connectors/` | no |
| Price sheet / model prices | JSON file env `NS_LEDGER_PRICE_TABLE_FILE` (worker); dev file is synthetic | ingest.md | no |
| Budgets and alerts | Azure budget in Bicep only; no product budget object, no alert rule route (only `finops/domains/{d}/forecast` GET) | no | no |
| Pricing/cost attribution rules | `docs/runbooks/ingest-cost-attribution.md` (behaviour, not config) | yes | no |

### 2.4 Product features that need a backend

| Item | Where today | Runbook | UI |
|---|---|---|---|
| Copilot model endpoint | env `NS_COPILOT_MODE` (`disabled|approved_endpoint|foundry_agent`), `NS_COPILOT_ENDPOINT`, `NS_COPILOT_DEPLOYMENT`, `NS_COPILOT_API_VERSION`, `NS_COPILOT_REGION`, `NS_COPILOT_MODEL_FEATURE`, `NS_COPILOT_SKU`, `NS_COPILOT_OAUTH_SCOPE`; any `NS_COPILOT_*KEY|SECRET|PASSWORD` var refuses startup; auth = managed identity. A failed optional component blocks `/readyz` | builder docstring; install.md: "503 copilot_unconfigured until a model endpoint is configured" | no |
| Evaluator / judge model | `scripts/gates/g16_judge_live.py` only; no runtime setting found for a judge endpoint: UNVERIFIED | no | no |
| Search | env `NS_SEARCH_PROVIDER=fixture|azure`, `NS_SEARCH_SERVICE`, `NS_SEARCH_INDEX`, `NS_SEARCH_REGION`, `NS_SEARCH_REFRESH_SECONDS`; unset -> `503 search_unavailable` | runtime-composition | no |
| Action write targets (Foundry model swap, APIM) | env `NS_FOUNDRY_ENABLED` + 4 `NS_FOUNDRY_*` ids; `NS_APIM_ENABLED` + `NS_APIM_GATEWAY_ID`, `NS_APIM_DOMAIN_ID`. Empty registry means dry-run says "no write target" | runtime-composition | no |
| Emergency-disable kill switch | UI `/admin/execution-control` (needs `config.manage` AND on the customer control domain) | `docs/runbooks/action-plane-kill-switch.md` | yes |
| MCP servers (external, client side) | UI `/mcp-admin` (register URL + name, sync, approve/revoke tools) and API `POST/PATCH /mcp-admin/servers...`; allow-list env `NS_MCP_ALLOWED_HOSTS` | `docs/` UNVERIFIED runbook | yes (partial) |
| MCP server (NeuroSphere as server) | env only, above | no | no |
| APIM gateways (register, sync, mode) | register: API `POST /domains/{d}/gateways` only (no register control in `gateways/*.tsx`); sync API; mode UI (observe/manage switch) | no runbook | partial |
| Federation cell | env `NS_FEDERATION_CELL_ID`, `NS_FEDERATION_BOUNDARY_ID`, `NS_FEDERATION_CACHE_TTL_SECONDS` | no | no |
| Evaluation pilot datasets | env `NS_EVALUATION_PILOT_DATASET_IDS` | no | no |
| Domains / tenants | no object; "domain" is a string in policy `domain_memberships` and in each data record. Seeder/grant script decide the set | no | no |
| Policies (action approval policy, maker-checker) | UNVERIFIED location; HITL service built in data/planes builders; no admin policy editor found | no | no |
| Retention periods, legal holds, erasure | lifecycle worker + core; settings/policy source not exposed by API or UI (UNVERIFIED file/env name) | G06 inputs OPEN in PRP-23 note | no |
| Realtime (WebSocket) | env `NS_REALTIME_*` (poll interval, max subscriptions) | no | no |
| Self-observability sinks | env `NS_LOG_LEVEL`; App Insights string passed to `telemetry.py` when not local | `docs/ops/slo.md`, `infra/observability/*` dashboards | no |
| UI style / theme default | `/config.json` default style id; user theme in localStorage; agency pack = code in `packs.ts` | `design-system/themes/README.md` | per-user picker only |
| Sandbox | UI toggle (client only); seeded data via `make seed` / `sbx_seed_stack.py`; `POST /sandbox/reset` needs `config.manage` | seeding.md | yes (toggle + reset) |

Short answer to "what must an admin do to get a useful system from nothing": (1) deploy infra
with Bicep/Helm or the hosted script; (2) create the Entra app registration and app roles; (3) set
~25 env vars on api and workers (auth, store, ingest file, search, copilot, write targets, MCP,
CORS, SIEM); (4) author the ingest producers file and price table; (5) run the seeder or point
producers at the ingest edge; (6) run the grant script for each person (one at a time, by object
id) because no product screen can; (7) assign Entra app roles in the portal; (8) put the `config.json`
beside the SPA. Steps 3, 4, 6 and 8 are only partially documented, and no screen shows which of
them is still missing (the only aggregate view is `/readyz`, which lists `composition.<x>.disabled`
reasons, `health/probes.py`).

## 3. Existing admin-ish pages: what each can and cannot do

| Page | Can | Cannot |
|---|---|---|
| `/admin/execution-control` (`features/execution-control`, `PUT /api/v1/actions/emergency-disable`) | Read and set the customer-wide emergency-disable of the action plane. Requires `config.manage` in some domain and on the reserved control domain (`actions/customer_control.py`). | Anything else: no per-connector toggles, no policies. Operator must already hold `config.manage` on the control domain, which only the grant script can give. |
| `/mcp-admin`, `/mcp-admin/server` (`features/mcp-admin`, `/mcp-admin/servers...`) | Register an external MCP server by URL and name, sync its tool manifest, approve or revoke individual tools, patch the server. Real router (`mcp/admin/router.py:96-198`). | Credentials for the server, OAuth client setup, allow-list host editing (env `NS_MCP_ALLOWED_HOSTS`), configuring the NeuroSphere MCP server. Mock exists (`tests/mock-api/mcpAdmin.ts`); I did not run its real-store tests: UNVERIFIED. |
| `/workspaces/admin` | Shows a role-gated page (403 if the Admin role is not held). | Everything it promises. Body is empty (`WorkspaceBody(items=[])`). |
| `/gateways`, `/gateways/detail` (`features/gateways`) | List registered gateways, show observe summary, switch observe/manage mode through the audited action executor. | Register a gateway (API only), edit domain/gateway ids, configure the poller (env). |
| `/deploy`, `/deploy/capabilities` | Scan input and produce a deployment plan (pure function); no apply control (PRP-31 item 7 evidence: "no apply control"). | Deploy anything. |
| `/sandbox` | Toggle sandbox, view synthetic entity counts and rows, reset sandbox data. | Anything hosted (503 outside `NS_ENV=local`). |
| `/audit` | Pick a domain, page records, verify the hash chain. | Search, filter by actor/action/time, export, list all chains. |
| `/review`, `/actions` | HITL queue and action proposals/decisions (NS-07 lane, not mine). | n/a |

Not present anywhere: users/roles page, domains page, ingest producers page, connectors page,
models/copilot settings page, budgets page, retention page, branding page, system status page
(`/readyz` is JSON only), a setup checklist or first-run wizard.

## 4. Per-capability notes (chains)

### 4.1 Identity
Chain: SPA MSAL (`frontend/src/auth/msal.ts`, `AuthProvider.tsx`; config from `/config.json`,
`app/config.ts:116`) -> bearer token -> `authz` dependency (`services/api/neurosphere_api/authz/dependencies.py`)
-> `JwtValidator` (`neurosphere_core/auth/jwt/validator.py`, cloud/tenant/audience pinned) ->
`ScopeDeriver.from_verified_claims` (`auth/scope/derivation.py`) -> policy store
(`CosmosPolicyRepository`, container `NS_AUTH_POLICY_CONTAINER`) -> `IdentityScope`.
Evidence: 195 tests pass (authz+audit) including fail-closed and the route inventory that refuses
boot if any route lacks `require(...)` (`authz/routes.py:1-20`). All in-memory. Live Entra was
proven by operator gates per the PRP-06 and PRP-29 notes; not re-run.
Design is sound: Entra role/group claims are never authority (`derivation.py:5-7`), admin does not
hold audit.read or data.export (`permissions.py` `_ADMIN`), auditor holds only audit.read and
evidence.read, privileged roles are time-bound.
Gap: the write side. `Permission.POLICY_MANAGE` and `GRANT_WRITE` are defined and given to roles
(`permissions.py:74,79,88,97`) but no route requires `POLICY_MANAGE` (grep of
`neurosphere_api` returns no use). Steward holds `GRANT_WRITE` but there is no grant route. So the
permission model promises role assignment and nothing implements it. Additional consequence: the
hosted demo user with an Entra role but no policy document "can sign in but sees nothing"
(hosted-demo.md:299) and no one except the operator-with-Cosmos-access can fix that.
Operator-configurable: script only (`make grant-operator`).

### 4.2 Audit
Records are written by the action executor and authz decisions (`authz/audit_mount.py`,
`authz/recorder.py`, `neurosphere_core/audit/`). Read chain: `/audit` page ->
`features/audit/data.ts` -> `GET /api/v1/audit/domains` and `/{domain}/records|verify`
(`ui_adapters/audit.py`) -> `AuditRepository.read_range/verify`. The domain list comes from the
auditor's scope. SIEM sink: `NS_AUDIT_SIEM_SINK`. Auditor-screen access tests pass
(`services/api/tests/auditor_access`, 85-test run, in-memory). Missing: free-text/time/actor
filtering, CSV/JSON export in the UI, retention/legal-hold controls for the audit store (PRD NS-03:
"immutable audit retention with documented conflict rules").

### 4.3 Self-observability
`/healthz` and `/readyz` (`health/router.py:48-52`) with composition readiness reasons. JSON log
formatter, metrics and OTel setup in `neurosphere_core/observability/`. SLO docs and dashboards in
`docs/ops/slo.md`, `infra/observability/`. PRP-05 sits in `backlog` with no execution table yet its
runtime is used everywhere (shipped under PRP-29/35). No page in the UI shows platform health
beyond the per-page ForbiddenState/health pill.

### 4.4 Workspaces per persona
Chain: `features/workspaces/WorkspacePage.tsx` -> `GET /api/v1/workspaces/{role}`
(`workspaces/router.py:73-92`) -> role held check -> `WorkspaceBody(items=[])`. The
`WORKSPACE_PROBE_BASE` comment in `personas.ts` reads "Placeholder until PRP-06 defines the real
endpoints". Navigation per persona (`app/workspaceNav.ts`) works. Class: gate works, content
absent.

### 4.5 Theme, branding, accessibility
Theme packs are typed data compiled into the bundle; a sample agency pack ships; logos limited to
PNG/WebP up to 256 KiB (`themes/README.md`). User choice persists in localStorage; deployment
default only for UI style (`theme-store.ts`). To brand for an agency: edit `packs.ts`, run vitest
contrast checks, rebuild and redeploy. No runtime upload. Accessibility: automated axe over every
manifest route runs against the mock API (`frontend/tests/e2e/a11y/`); manual keyboard and
screen-reader sheets unsigned. The docs say explicitly there is no conformance claim, which is
accurate. Sign-off is parked per memory notes.

### 4.6 Docs site and public assistant
MkDocs Material config and a Pages workflow exist; `gh api .../pages` returns 404, so no public
site. Docs assistant service is a standalone FastAPI app with BM25 retrieval and a stub model;
no IaC, no deployment, no model wired. Runbooks are DRAFT. Walkthroughs for five personas exist in
`docs/walkthroughs/`.

### 4.7 Sandbox
Backend routes real but gated to `NS_ENV=local` (`runtime/builders/data.py` docstring). UI toggle
is client-only state (`features/sandbox/store.ts`). Hosted environment is seeded by
`hosted_demo_seed.py`, which is an operator script. Isolation rule from CLAUDE.md is respected
(seeder refuses non-local, hosted guard in `sbx_guard`).

### 4.8 ATO evidence and data lifecycle
Compliance docs and the evidence collector/statement checker are real scripts (`scripts/compliance`).
They produce markdown, there is no product surface and none is required by the PRD wording.
Lifecycle (retention, erasure with legal hold, D7 rule) is implemented in core and a worker role;
there is no API/UI to set retention periods or place legal holds, and the customer inputs
(G06 classification, retention, legal hold process) are explicitly OPEN. So an admin cannot
configure retention today except through whatever the worker reads (UNVERIFIED which file/env).

### 4.9 Government deployment
Params, a Helm values file and the sovereign profile exist, but the PRP-20 audit (2026-11-04)
states the profile YAML is read by no running code and there is no live Government evidence.
Treat as DESIGN ONLY.

### 4.10 Release and publishing
`release.yml` is thorough (GHCR push, syft SBOM, cosign keyless sign/attest/verify, Helm OCI,
drafted GitHub Release; dry-run default for dispatch). Two Draft rc releases; no published release,
so "customer-hosted install from published images" has not been exercised.

### 4.11 Platform deployment
No workflow deploys to Azure. `ci.yml`/`docs.yml` are the only ones with "deploy" strings
(docs to Pages). The hosted demo is rebuilt by hand with `hosted_demo.py` and its evidence goes to
`docs/evidence/PRP-32/`; whether main is currently running there is UNVERIFIED (I made no az calls
by rule). Nothing continuously pushes main to it.

## 5. What an operator cannot do today (plain words)

- Cannot sign in as a new person and be given access without someone running a Python script
  against Cosmos with Azure credentials.
- Cannot see or edit who holds which role, in which domain, until when.
- Cannot revoke a compromised user through the product.
- Cannot create a domain or tenant, or see the list of them.
- Cannot register an ingest producer or rotate its secret from the product; must edit a JSON file
  and restart or redeploy.
- Cannot enter connector credentials or set up a source from the UI; the connectors are SDK code.
- Cannot choose or change the copilot model, evaluator model, search provider, or write targets
  from the UI; env vars and a restart.
- Cannot set budgets, alert thresholds or price sheets in the product.
- Cannot set retention, legal hold or erase a subject.
- Cannot brand the product for an agency without a code change and rebuild.
- Cannot see a single "system status / what is not configured" screen; only `/readyz` JSON.
- Cannot search or export the audit log in the UI.
- Cannot get the docs site or the docs assistant publicly; neither is published.
- Cannot deploy main to Azure by pushing; there is no CD.

## 6. Contradictions between tracker and reality

| PRP | Tracker says | Reality |
|---|---|---|
| PRP-06 identity/authz/audit | shipped | Read side and enforcement real. The "audited admin path" the code comment refers to for policy writes does not exist; role assignment cannot be done in-product. |
| PRP-25 docs site and assistant | `status: backlog` in INDEX, in the file header it also says `pr: 154` and the completion note says shipped 2026-11-02 | Tracker stale (code merged). But Pages was never deployed (404) and the assistant is not hosted. |
| PRP-23 ATO evidence/lifecycle | backlog in INDEX | Completion note filled, items merged; tracker stale. Retention/legal hold have no admin surface; customer inputs OPEN. |
| PRP-31 missing UI surfaces | backlog in INDEX | all 8 items + 2b/4b marked merged: tracker stale. The "admin" page it lists (item 8) is the execution-control page, not a setup console. |
| PRP-05 runtime + self-observability | backlog, no execution table | Runtime exists and is relied on by 29/35. Tracker stale. |
| PRP-20 Government | backlog (reopened by audit) | Consistent; static design only. |
| PRP-28 shell/usability | shipped | `/workspaces/*` are placeholders ("built out in later work"). |
| PRP-32 hosted env | shipped 2026-10-28 | runbook header says "No live step has run. Every step S1-S10 is OPEN"; later live runs recorded elsewhere (memory notes mention S3). Whether it is up now: UNVERIFIED. |
| PRP-13 release | shipped | Only Draft rc releases; no published image/release. |
| PRP-24 themes/a11y | shipped | Manual a11y sign-off unsigned; agency theme is compile-time only. |

## 7. Open questions I could not answer

1. Is `NS_APIM_*`/`NS_GATEWAY_POLL_*` documented in a runbook? I found only code references.
2. Where does the lifecycle worker read retention periods and legal holds from (file, env, Cosmos)?
3. Where does an evaluator/judge model endpoint get configured at runtime (only `g16_judge_live.py` found)?
4. Which IaC writes the SPA `/config.json` in the hosted App Service web site?
5. Is the hosted demo currently up and on which commit of main (no az allowed)?
6. Who passes the Application Insights connection string to `telemetry.py`?
7. Do the mcp-admin and gateway routes work against Cosmos (real store)? I ran only in-memory API tests.
8. Whether the PRD intends an in-product policy admin (NS-08 says "custom resource-scoped
   permissions"); the code comment implies yes. Needs an owner decision and likely a new PRP
   (see recommendation below).

## 8. Recommendation (for the orchestrator)

A single new PRP "Operator console and first-run setup" would close the central complaint. Minimum
slice, in order of value: (a) policy admin API + UI (list principals, assign role/domain with
expiry, grant, revoke; permission `policy.manage`, audited; this removes the Cosmos-script
dependency), (b) a Setup/System status page backed by `/readyz` composition components, listing
each `composition.<x>.disabled` reason with the exact env var and runbook link, (c) ingest
producer registry in Cosmos with generate-secret-once UX, (d) read-only settings view of
effective config (names only, never values), (e) CD workflow with OIDC to the hosted env behind an
approval environment. Each item needs the executor, authz and audit conventions already in place.
