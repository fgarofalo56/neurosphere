---
name: prp-32-hosted-azure-environment
status: active
started: 2026-10-26
branch: prp-32-hosted-azure
review: required
priority: P0
created: 2026-10-24
model: sonnet
phase: 5
ns: NS-07, NS-08, NS-10
depends_on: PRP-29, live approval (NS_LIVE_APPROVED=1 and per-step operator approval)
wave: W9
absorbs: new
---

# PRP-32: Hosted Azure environment (persistent demo)

## Goal
Stand up a persistent, right-sized NeuroSphere environment in Azure that the operator and invited evaluators can click through over public HTTPS with real Entra sign-in. It runs the real API, the real workers and a real Cosmos DB account seeded with synthetic sandbox data, not the mock API. It ships:
- A `demo` Bicep composition (`infra/demo/`) that reuses the core modules and the App Service profile. It adds a frontend web app, regional VNet integration, private endpoints with DNS records in the enterprise hub zones, Cosmos databases and containers provisioned in Bicep, data-plane RBAC for the app identities and a Cost Management budget.
- An App Service profile that can pull the public, cosign-signed GHCR images anonymously. Today `acrUseManagedIdentityCreds: true` points it at an ACR that does not exist.
- A gated deploy script with what-if first, an ownership register, persistent-by-default (`--keep`) behaviour and a separate `teardown` subcommand, plus unit tests.
- Hosted seeding of synthetic data only, through an explicit, tested allow in `sbx_guard` for the one registered hosted environment.
- A post-deploy smoke: automated unauthenticated checks, plus a Playwright spec against the hosted URL that needs the operator's sign-in (manual gate).
- A runbook (`docs/deploy/hosted-demo.md`) covering deploy, update, seed, sign-in and role assignment, cost and teardown, and evidence under `docs/evidence/PRP-32/`.

The target is the Limitlessdata tenant, subscription **Limitlessdata - DMLZ**, region **centralus**, new resource group `rg-neurosphere-demo`. It is designed for that landing zone's strict policy, not around it. A management-group Modify policy forces Cosmos `publicNetworkAccess=Disabled`, and the enterprise private DNS zones live centrally in the Loom hub.

Why now: on 2026-10-24 the operator asked to test a hosted UI. None exists; only `pnpm demo` against the mock API runs locally. The default SKUs of the existing modules cost about $600/month (APIM Developer, AI Search standard, P1v3 x2), which is too much for a standing demo.

## Acceptance criteria
- [ ] Item 1: new modules under `infra/demo/modules/` build with `az bicep build`:
  - Hub-attached private endpoints: the PE resource lives in the NeuroSphere resource group, its NIC sits in a caller-supplied subnet id, and its zone group points at an existing zone id in another resource group.
  - Cosmos data: database plus every container the hosted API and workers read, with partition keys matching the code constants.
  - Messaging data: event hub, consumer group and checkpoint blob container.
  - Data-plane role assignments.
  - An RG-scope budget.
  - `cosmos.bicep` gains `capacityMode` (default `Provisioned`) and `loganalytics.bicep` gains `dailyQuotaGb` (default `-1`). The compiled core `main.bicep` ARM is byte-identical before and after for default parameters (test).
- [ ] Item 1: a drift test fails if any Cosmos store's container name or partition key path in `packages/**`/`services/**` is missing from, or differs from, the demo container list.
- [ ] Item 2: `infra/appservice/main.bicep` gains these features without changing what its defaults compile to:
  - an optional frontend app (8080, health `/`);
  - optional regional VNet integration (`virtualNetworkSubnetId`);
  - per-app `publicNetworkAccess`;
  - `registryAuth: managedIdentity|anonymous`;
  - per-app settings.

  `main.bicepparam` is unchanged, so the Helm/App Service image-equality test stays green. With `registryAuth=anonymous`, no app has `acrUseManagedIdentityCreds: true` (test). The workers app gets `NS_WORKER_HEALTH_HOST=0.0.0.0` (test).
- [ ] Item 3: `infra/demo/main.bicep` composes items 1 and 2.
  - It declares no APIM, no AI Search, no Key Vault unless `deployKeyVault=true`, no VNet, no private DNS zone and no subnet (tests over compiled ARM).
  - Data services take `publicNetworkAccess: 'Disabled'`. The frontend is the only site with public network access; the API and workers sites are `Disabled`.
  - Every created resource carries the tags `owner`, `project=neurosphere`, `env=demo` and `delete-after`, plus `neurosphere:created-by` and `neurosphere:deployment-id`.
  - No secret material appears in outputs or parameters (`SECRET_MARKERS` test).
  - `infra/demo/main.bicepparam` contains no subscription id, tenant id, email or hub resource id. Those arrive at deploy time.
- [ ] Item 4: `scripts/gates/hosted_demo.py` subcommands `preflight | plan | deploy | grant-model-access | entra-redirect | seed-access | smoke | teardown | status`.
  - It refuses with exit 2 and runs no `az` unless `NS_LIVE_APPROVED=1`. It refuses unless `az cloud show` is `AzureCloud` and `az account show` matches `--subscription`, and it never calls `az account set` itself.
  - `deploy` always runs `what-if` first, prints the change list and requires `--approve-plan <sha256 of the what-if change list>`.
  - Every shared-resource touch needs its own `--approve-shared <token>`: `hub-subnet`, `hub-pe`, `hub-dns`, `foundry-role`, `entra-app` and `budget`. Each approval is recorded in the evidence with operator name and UTC time.
  - The default is to keep the environment. `teardown` is the only removal path, and it is register-guarded.
  - All behaviour is unit-tested through a fake `az` runner: approval ordering, refusals, the plan-hash mismatch, teardown that refuses foreign resources, and the evidence scrubber.
- [ ] Item 5: `sbx_guard.require_hosted_endpoint()` allows exactly the Cosmos and Event Hubs hosts recorded in the local hosted registration, and only when all of these hold:
  - `NS_LIVE_APPROVED=1`;
  - `NS_SANDBOX_HOSTED_DEPLOYMENT_ID` equals the registration id;
  - the host ends in the Commercial `CloudProfile` suffix;
  - no key or connection string is set.

  Any other host, a key, a mismatched id or a missing registration is refused (unit tests). `require_local_endpoint` keeps "no override" unchanged. `scripts/gates/hosted_demo_seed.py` loads only synthetic sandbox output through the PRP-29 seeder contract (C4), with Entra auth and no container creation.
- [ ] Item 6: `hosted_demo.py smoke` checks the following with no sign-in and writes evidence:
  - the frontend `/` returns 200;
  - `/config.json` returns 200 with `no-store`, the expected keys, non-zero ids and a same-origin `apiBaseUrl`;
  - an unauthenticated `GET /api/v1/me/domains` through the frontend returns 401 (the proxy reaches the API and auth is enforced);
  - the API's own public hostname is refused (403 or no route);
  - all three apps report `Running` and the App Service `HealthCheckStatus` metric is healthy.

  `frontend/tests/hosted/hosted-smoke.spec.ts` (config `frontend/playwright.hosted.config.ts`) is excluded from CI, needs `NS_HOSTED_URL` plus an operator storage state under `temp/`, and checks the shell, the domain switcher with synthetic domains, overview tiles with data, the map, and the copilot (answer or disabled reason).
- [ ] Item 7: a release candidate tag `v0.1.0-rc.2` is cut by `docs/release/release-process.md`, only after PRP-29 (and PRP-30/31 if they are in flight) merge. Cosign signatures and SBOM attestations are verified per `docs/release/verify.md`. `infra/demo/main.bicepparam` pins `imageTag = '0.1.0-rc.2'` and the evidence records each image digest.
- [ ] Item 8: `docs/deploy/hosted-demo.md` documents prerequisites (P2S VPN and resolver DNS 10.0.9.4, roles), every operator-approval step, update (new tag), seed, user and app-role assignment, a cost table with an "estimate; verify with the Azure pricing calculator" label, the monthly `delete-after` review and teardown. `docs/evidence/PRP-32/README.md` indexes the evidence. `docs/RESEARCH-AND-GATES.md` gains dated PRP-32 notes on G01, G07 and G12, without changing any gate's status unless live evidence exists.
- [ ] Item 9 (live, operator-gated): each live step S1-S10 below either runs with evidence or is reported OPEN. The environment is reachable at `https://<prefix>-web.azurewebsites.net` and the operator signs in, sees seeded synthetic domains and gets 403 on a hidden route.
- [ ] PRP exit: all offline items green under `verify-gates -Mode full`. The reviewer confirms three things:
  - no shared enterprise resource is changed without a recorded per-step approval;
  - the data plane has no public path;
  - the hosted guard allow cannot reach an unregistered host.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | What runs hosted | mock API; real API + workers + Cosmos | Real Entra, real API, real workers and real Cosmos, seeded with synthetic sandbox data only. There is no hosted mock (user decision 1) |
| 2 | Lifetime and budget | throwaway per session; persistent right-sized | Persistent, right-sized to about $150-250/month. Tags `owner`, `project=neurosphere`, `env=demo`, `delete-after` (reviewed monthly) (user decision 2) |
| 3 | Target | House Garofalo; Limitlessdata DMLZ | Limitlessdata tenant `d1fc0498-...`, subscription Limitlessdata - DMLZ, region `centralus` (AI Search had no capacity in eastus2 on 2026-10-16), new RG `rg-neurosphere-demo` (user decision 3). The GUIDs are passed as arguments, not committed |
| 4 | Network topology | own VNet + own private DNS zones; spoke VNet peered to hub; attach to hub | **Attach to the Loom hub** (`vnet-csa-loom-hub-centralus`, 10.0.0.0/16, no route table on the subnets used). App Service regional VNet integration goes into the existing, empty hub subnet `snet-functions` (10.0.3.0/24, already delegated to `Microsoft.Web/serverFarms`, no service association link on 2026-10-24). Private endpoints go into the hub `snet-private-endpoints` (the G03 pattern), with zone groups on the existing hub zones in `rg-csa-loom-admin-centralus`. No subnet, peering, VNet or zone is created. Rationale: the fewest shared-resource changes (one subnet join plus A records), enterprise DNS reused, and the P2S operator path already proven. Alternatives are kept under "Decisions to confirm" |
| 5 | Public surface | frontend + API public with Entra; private-only behind P2S | **Frontend public over HTTPS with Entra sign-in in the SPA. The API is public only through the frontend's same-origin `/api` proxy** (PRP-29), and the API's own hostname is private (inbound PE, `publicNetworkAccess: Disabled`). The workers have no inbound path. The data plane is private. This meets the "public frontend + API with Entra" recommendation through one origin. The API has no CORS middleware, so a cross-origin public API would not work from the SPA anyway |
| 6 | Hosting SKU | P1v3 x2; P0v3 x1; B2 x1 | One Linux App Service plan, **B2 x1**, hosting three apps (`-web`, `-api`, `-workers`). B2 supports VNet integration and inbound private endpoints. P0v3 is the documented upgrade if B-series performance disappoints |
| 7 | Cosmos mode | provisioned; serverless | **Serverless**. Single region, no throughput set on any container. Hierarchical keys and per-document TTL are unaffected. The catalog container is flat `/domain` while the HPK matrix row is `unverified` (gotcha) |
| 8 | Event Hubs tier | Basic; Standard | **Standard, 1 TU**. Basic has no Private Link and only one consumer group, and the workers use consumer group `normalizer` |
| 9 | AI Search | standard; basic; omit | **Omit**. The search client is lexical only, with a fixture fallback (`FallbackAuthorizedSearch`), and nothing provisions an index. The UI shows "azure search is not configured" (disabled with reason). Basic is a documented add-on, about $75/month plus a PE |
| 10 | APIM | create Developer; reuse Loom APIM; omit | **Omit**. Nothing at runtime depends on APIM; only the deploy scan/planner discover it as a resource |
| 11 | Key Vault | always; only if a secret exists | `deployKeyVault=false` by default. With managed identity everywhere the hosted settings contain no secret. The flag and Key Vault references stay supported |
| 12 | Log Analytics | default; capped | Created, retention 30 days, `dailyQuotaGb=0.1`, App Service diagnostic settings only |
| 13 | Copilot LLM | new AOAI; reuse Loom Foundry | Reuse `aifndry-loom-centralus` (kind AIServices, endpoint `*.cognitiveservices.azure.com`, public network Enabled). Deployment `mini` (gpt-4.1-mini, GlobalStandard). API managed identity gets **Cognitive Services OpenAI User** (`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) on that account only. No keys (the account reports `disableLocalAuth: true`, and we never call `listKeys`). This is a shared-resource change with its own approval |
| 14 | Entra | new app; existing `neurosphere-api-dev` | Existing app `ace128f6-...`, scope `access_as_user`, v2 tokens (aud = bare GUID). PRP-29 adds the local SPA redirect and app roles. PRP-32 adds the hosted SPA redirect with a Graph PATCH from a body file, after a GET-and-merge, and documents user and app-role assignment |
| 15 | Images | ACR; GHCR public | GHCR `ghcr.io/fgarofalo56/neurosphere/{api,workers,frontend}`, public, anonymous pull, pinned tag `0.1.0-rc.2` (item 7), digests recorded, cosign verified before deploy |
| 16 | Frontend runtime config | Azure Files mount; env-rendered; API-served | Env-rendered at container start (PRP-29 contract C2). App Service cannot bind-mount a single file over `/usr/share/nginx/html/config.json` without a storage mount |
| 17 | Seeding location | operator workstation over P2S; one-off Container Apps job; App Service | **Operator workstation over the P2S VPN** (proven by G03), with the operator's Entra identity and a time-boxed data-plane role on the NeuroSphere-owned account only (`seed-access` grants, the seeder revokes). It needs no extra compute and no second shared subnet. The Container Apps job (hub `snet-container-platform`) is the documented alternative |
| 18 | Cosmos data-plane roles | built-in Data Contributor `...0002`; custom roles | **Custom SQL role definitions** that keep the PRP-06 posture (`prp06_cosmos_live.py:12-17`): read, create and query on the database; replace and upsert on every container except the audit records container. The built-in Data Contributor (`00000000-0000-0000-0000-000000000002`) is used only for the time-boxed seeder grant, at database scope |
| 19 | Ownership register | in-memory (G01); persisted | Persisted in the hosted Cosmos `deploy_register` container (`/deployment_id`) and exported to `temp/hosted-demo/register-<id>.json`. Teardown refuses if neither is readable |
| 20 | Budget | none; RG budget | RG budget $200/month, alerts at 50/80/100% actual and 100% forecast, operator email passed at deploy time. A budget is a notification, not a policy (not a "standing rule"), but it is still recorded as an approved step (`--approve-shared budget`). Foundry token spend lands on the shared Foundry account and is **not** in this budget's scope |
| 21 | Release tag | reuse rc.1; cut rc.2 | Cut `v0.1.0-rc.2` after PRP-29 merges, so the images contain the `/api` proxy and the real bootstrap |
| 22 | Review | required; none | `review: required` (shared enterprise resources, public ingress, guard policy change) |

### Decisions to confirm at plan approval
Each defaults as above. Every shared-resource change is listed, and none happens without its own `--approve-shared` token at run time.
1. **Hub subnet join**: integrate the plan into `snet-functions` (hub, shared). It may be earmarked for Loom Functions. Options: (a) default, use it (multi-plan subnet join needs /26+; it is /24); (b) a new /26 delegated subnet in the hub (a larger shared change); (c) a NeuroSphere spoke VNet peered to the hub, which needs a hub-side peering (shared) and spoke DNS pointed at the resolver 10.0.9.4; (d) an isolated NeuroSphere VNet with its own `privatelink.*` zones (no shared change, but duplicates enterprise zones, may be policy-denied, and the P2S path cannot reach it).
2. **Hub private endpoints**: four PE NICs in `snet-private-endpoints` (16 PEs there today) for Cosmos, Event Hubs, blob and the API site.
3. **Hub DNS records**: zone-group A records in `privatelink.documents.azure.com`, `privatelink.servicebus.windows.net`, `privatelink.blob.core.windows.net` and `privatelink.azurewebsites.net` (all present on 2026-10-24). Removed when the PEs are deleted.
4. **Foundry role assignment**: Cognitive Services OpenAI User on `aifndry-loom-centralus` for the API identity. Confirm deployment `mini` (GlobalStandard may process prompts outside the region; data is synthetic). Alternative: a `DataZoneStandard` deployment.
5. **Copilot capability row**: on the shipped matrix every Commercial Foundry row is `unverified` (`foundry.yaml:452-458`), so the hosted copilot shows "disabled" until a dated Commercial `centralus` row for the chosen model is added. Decided (orchestrator, 2026-10-24): the row is evidence-backed, so item 9 adds it after S4 and a live answer from the chosen deployment prove it works (PRP-29 has shipped by then, so `packages/**` is free). Item 9 owns `packages/core/neurosphere_core/capabilities/data/foundry.yaml` for that one dated row. Without S4 the copilot stays disabled with its reason (acceptable, reported).
6. **Entra app change**: add the hosted SPA redirect to `neurosphere-api-dev` and assign users to app roles.
7. **Budget**: amount $200, alert contacts.
8. **API private (inbound PE) vs public API hostname**: default private. A public API hostname would need CORS (not present) or remain unused.
9. **SKU**: B2 (default) or P0v3. `delete-after` initial date: deploy date + 30 days.
10. **Seeding path**: operator workstation over P2S (default) or a Container Apps job (a second shared subnet join).

### Plan deltas (approved by the operator at plan approval, 2026-10-26)
PRP-29 shipped with names and behaviour that differ from the C1-C4 proposals, and a Learn check overturned one gotcha. These deltas override the text below where they conflict.
- **D1 Frontend env names.** The frontend container takes `NS_UI_CLOUD`, `NS_UI_TENANT_ID`, `NS_UI_CLIENT_ID`, `NS_UI_API_SCOPE` and `NS_UI_API_UPSTREAM` (not `NS_FRONTEND_*`). The rendered `config.json` always has `apiBaseUrl: "/"`; the smoke check asserts exactly `/`.
- **D2 nginx Host and SNI.** `frontend/nginx/templates/default.conf.template` sends `Host $host` and no SNI, so an App Service upstream (which routes by host) never matches. Item 6 changes the `/api/` proxy to `proxy_set_header Host $proxy_host` and `proxy_ssl_server_name on` (local compose unchanged in behaviour) and owns that template plus `frontend/tests/edge/**`. It must merge before the item 7 tag.
- **D3 `/readyz` not proxied when hosted** (#131, operator decision). The frontend proxies `/readyz` and `/healthz` only when an opt-in env (proposed `NS_UI_PROXY_HEALTH=1`) is set; compose sets it, the hosted demo does not, so hosted `/readyz` is 404 at the frontend. Item 6 owns `frontend/docker/render-config.sh`, `frontend/Dockerfile` (only if the opt-in needs it) and the one `docker-compose.yml` env line. The smoke asserts hosted `/readyz` is not 200.
- **D4 Key Vault is required.** Under `NS_ENV=prod` the API refuses to start without `NS_AUTH_PSEUDONYM_KEY` plus `NS_AUTH_PSEUDONYM_KEY_REFERENCE` (`services/api/neurosphere_api/runtime/pseudonym.py`). `deployKeyVault` defaults to **true** in the demo. That adds a fifth hub PE (`vault`, zone `privatelink.vaultcore.azure.net`, presence checked in preflight; about +$8/month), Key Vault Secrets User for the API (and the workers if they resolve the key) at vault scope, and Key Vault reference app settings. The secret is created once by `hosted_demo.py deploy` only when absent, from a locally generated value written to a temp file passed with `--file` and deleted (never on a command line, never printed, never regenerated, since a new key orphans every policy grant). The operator is on the P2S VPN for this step.
- **D5 Route-all is on.** Learn (app-service-key-vault-references, "Access network-restricted vaults"): Linux apps that connect to private endpoints must set `vnetRouteAllEnabled: true`. This replaces the "keep route-all false" gotcha. The demo sets it on all three sites. Preflight checks that `snet-functions` still has internet egress (no route table, `defaultOutboundAccess` not false, NSG has no outbound Internet deny), so Entra, Foundry and GHCR stay reachable without transiting the hub firewall. Image pulls stay on the public route (`WEBSITE_PULL_IMAGE_OVER_VNET` unset).
- **D6 Registry-driven containers.** PRP-29 ships `neurosphere_core.stores.containers` and its export `infra/compose/cosmos-containers.json` (27 containers, catalog flat `/domain`). `cosmos-data.bicep` builds its containers from that file with `loadJsonContent`. The item 1 drift test compares the compiled ARM to the export (the registry-to-store parity is already PRP-29's test).
- **D7 Hosted seeding extends `sbx_seed_stack.py`.** The shipped seeder is local-only (loopback guard, connection strings, `NS_ENV=local`). Item 5 owns `scripts/sandbox/sbx_seed_stack.py` and `scripts/sandbox/sbx_grant_operator.py` for a hosted mode only: Entra (`DefaultAzureCredential`) clients for Cosmos, Event Hubs and Blob, every endpoint passed through `require_hosted_endpoint`, no key or connection string accepted, no container creation. The local path is unchanged. Telemetry is sent to the hosted hub and processed by the hosted workers. `seed-access --grant` gives the operator time-boxed Cosmos Data Contributor (database scope), Event Hubs Data Sender (hub scope), Storage Blob Data Contributor (archive container) and Key Vault Secrets User (the pseudonym secret) on NeuroSphere-owned resources only; `--revoke` removes all four.
- **D8 Worker identity settings.** `NS_WORKER_OBJECT_ID` and `NS_WORKER_TENANT_ID` are the workers' managed identity (C3 wiring in item 3).
- **D9 Interface contracts between lanes** (items code against these names; a rename is a plan delta):
  - `infra/demo/main.bicep` parameters (item 3 declares, item 4 generates the params file): `prefix` (default `nsdemo`), `location` (default RG location), `imageRegistry` (default `ghcr.io/fgarofalo56/neurosphere`), `imageTag`, `appServiceSkuName` (default `B2`), `deployKeyVault` (default `true`), `integrationSubnetId`, `privateEndpointSubnetId`, `cosmosDnsZoneId`, `eventHubsDnsZoneId`, `blobDnsZoneId`, `webAppsDnsZoneId`, `keyVaultDnsZoneId`, `entraTenantId`, `entraClientId`, `copilotEndpoint`, `copilotDeployment` (default `mini`), `budgetAmount` (default `200`), `budgetStartDate`, `budgetContactEmails` (array), `tagOwner`, `tagDeleteAfter`, `deploymentId`, `createdBy`. Every id, email, tenant/client and endpoint parameter has no default.
  - `infra/demo/main.bicep` outputs: `apiSiteName`, `workersSiteName`, `frontendSiteName`, `frontendHostName`, `apiHostName`, `apiPrincipalId`, `workersPrincipalId`, `cosmosAccountName`, `cosmosEndpoint`, `cosmosDatabaseName`, `eventHubsNamespaceName`, `eventHubsFqdn`, `eventHubName`, `storageAccountName`, `archiveContainerName`, `keyVaultName` (empty when not deployed), `pseudonymSecretName`, `privateEndpointIds` (array).
  - `temp/hosted-demo/registration.json` (item 4 writes after deploy, item 5 reads; gitignored, never committed): `{"schema": 1, "deployment_id", "cloud": "AzureCloud", "cosmos_host", "eventhubs_host", "blob_host", "key_vault_host", "database", "event_hub", "archive_container", "pseudonym_secret_uri", "workers_object_id", "customer_id"}`. Hosts are bare hostnames, no scheme, port, path or userinfo.
- **#131** stays out of scope (operator decision), apart from D3.
- **Hub subnet**: `snet-functions` (option a). Decisions 2-10 keep their defaults.

## Context manifest

### Files that matter
- `infra/appservice/main.bicep`:
  - `:29-34`: `skuName` `P1v3`, `capacity` 2.
  - `:42-61`: user- or system-assigned identity.
  - `:63-73`: Key Vault reference rendering.
  - `:89-117`: `<prefix>-api`, `WEBSITES_PORT` 8000, `healthCheckPath /readyz`.
  - `:105-106` and `:135-136`: `acrUseManagedIdentityCreds: true` (breaks anonymous GHCR pulls).
  - `:119-147`: `<prefix>-workers`, 8090, `/healthz`.
  - `:151-152`: principal id outputs.
  - No frontend app, no `virtualNetworkSubnetId`, no `publicNetworkAccess`.
- `infra/appservice/main.bicepparam:5-9`: `registry.example.invalid`, tag `0.1.0`. It must stay equal to Helm values (`tests/unit/infra/test_helm_render.py:140-158`). Do not edit; the demo has its own param file.
- `infra/bicep/modules/main.bicep`:
  - `:17-19`: root `publicNetworkAccess` switch, default `Disabled`.
  - `:95-104`: search.
  - `:117-127`: APIM.
  - `:129-142`: the network module creates its own VNet and zones.

  Do not compose this file into the demo; compose the service modules directly.
- `infra/bicep/modules/cosmos.bicep:20-41`: no capacity mode (provisioned only), `disableLocalAuth: true` `:27`. `eventhubs.bicep:20-22`: SKU `Standard|Premium`. `search.bicep:20-22`. `loganalytics.bicep:20-23`: retention, no daily cap. `keyvault.bicep:35-38`: purge protection on. `storage.bicep:34-41`: shared key off.
- `infra/bicep/modules/network/main.bicep:174-190`: the `app` subnet has no `Microsoft.Web/serverFarms` delegation. `:194-200` creates private DNS zones in the NeuroSphere RG, which is wrong for the hub pattern. Not used by the demo.
- Live hub facts, read-only `az` on 2026-10-24:
  - `vnet-csa-loom-hub-centralus` (rg-csa-loom-admin-centralus) uses Azure DNS (no custom servers) and has the firewall `fw-csa-loom-centralus` 10.0.0.4.
  - `snet-functions` 10.0.3.0/24 is delegated `Microsoft.Web/serverFarms`, has NSG `nsg-snet-functions` (inbound VNet allow / Internet deny, no outbound rules), no route table, 0 IP configurations and no service association link.
  - `snet-private-endpoints` 10.0.5.0/24 has 16 PEs and `privateEndpointNetworkPolicies: Disabled`.
  - `snet-container-platform` 10.0.2.0/24 is delegated `Microsoft.App/environments`.
  - All needed `privatelink.*` zones exist in rg-csa-loom-admin-centralus.
- Live Foundry facts, read-only, 2026-10-24: `aifndry-loom-centralus`, kind `AIServices`, endpoint `https://aifndry-loom-centralus.cognitiveservices.azure.com/`, public network Enabled, network ACL default Allow, `disableLocalAuth: true` (key auth is off; Entra only). Deployments: `mini` gpt-4.1-mini, `strong` gpt-4.1, `gpt-5.4-mini`, `gpt-6.1-sol`, `embed` text-embedding-3-large, plus others.
- `scripts/gates/g01_deploy_smoke.py`:
  - `:1-18`: contract and exit codes.
  - `:45-51`: template, params, tags.
  - `:120-197`: `scrub`, `subscription_token`, `redact_subscriptions`, `safe_text`.
  - `:238-247`: parser; `--keep` defaults to tear down.
  - `:287-312`: preflight (cloud, account, RG must not exist).
  - `:352-367`: what-if.
  - `:466-520`: register-guarded teardown (`plan_removal`, foreign-resource refusal).
  - `:798-833`: approval first, then the `neurosphere_core` import check (the 2026-10-16 stranded-RG lesson).
- `scripts/gates/g02_profile_appservice.py:1-30,46-48,133-143` and `_g02_profile_common.py:43-48`: Government-only App Service gate; always tears down. Reuse its helper-module import pattern (`_common()` `:51-55`), not its cloud.
- `infra/scripts/uninstall.py:1-14,41-50`: register-guarded removal, never run live. `_API_VERSIONS` has no `Microsoft.Web/*`, `Microsoft.Network/privateEndpoints` or `Microsoft.Consumption/budgets`, so it cannot remove the demo as-is. Teardown lives in item 4.
- `packages/core/neurosphere_core/deploy/register/` (`cosmos_store.py:28` `/deployment_id`, `guard.py:42-121`): `ResourceRow`, `plan_removal`, `assert_resource_group_empty_of_foreign`.
- `scripts/sandbox/sbx_guard.py`:
  - `:1-5`: "There is deliberately no override".
  - `:44-52`: `require_local_endpoint`.
  - `:73-78`: `cosmos_settings` returns a key.
- `scripts/sandbox/sbx_seam.py`:
  - `:25-26`: `HUB=telemetry`, `DATABASE=sandbox-neurosphere`.
  - `:45-55`: key-based client, data-plane `create_container_if_not_exists`. This fails under Entra (403 substatus 5300).
- `scripts/sandbox/sbx_cli.py:26-40`: entity and relation files.
- Runtime config:
  - `packages/core/neurosphere_core/cloud/settings.py:13-25`: `NS_ENV`, `NS_CLOUD` required outside local.
  - `packages/core/neurosphere_core/clients/factories.py:1-11,47-59`: keys refused outside `NS_ENV=local`; `DefaultAzureCredential` with the profile authority.
  - `services/workers/neurosphere_workers/runtime/__main__.py:16-17`: health host defaults to `127.0.0.1`. App Service needs `0.0.0.0`.
  - `services/workers/neurosphere_workers/ingestion/settings.py:25`: consumer group `normalizer`.
- Images:
  - `services/api/Dockerfile:28,37-38` (`NS_ENV=prod`, 8000).
  - `services/workers/Dockerfile:37-38` (8090).
  - `frontend/Dockerfile:3-4,32` (8080, config by mount).
  - `frontend/nginx.conf:31-36`: `/config.json` no-store; there is no `/api` location today (PRP-29 adds it).
  - `frontend/public/config.json`: `apiBaseUrl` `http://localhost:8000`, zero GUIDs.
- `.github/workflows/release.yml:18-20` (trigger `v*.*.*`), `:76` (tag regex accepts `-rc.N`), `:96` (version = tag without `v`), `:166` (`ghcr.io/<owner>/neurosphere/<service>:<version>`). Only tag: `v0.1.0-rc.1`. `docs/release/release-process.md:8-62` (branch, CHANGELOG, Chart version, tag, verify); `infra/helm/Chart.yaml:5`.
- Cosmos stores (container, partition key), the source for the item 1 drift test:
  - `packages/core/neurosphere_core/actions/cosmos_store.py:84-87` (`action_intents` MultiHash `/customer_id`,`/domain_id`; `action_execution_control` `/customer_id`).
  - `audit/cosmos_store.py:47` (`/chain_id`).
  - `auth/revocation/cosmos_store.py:47-48` (`revocations` `/principal_id`).
  - `auth/scope/cosmos_repository.py:30` (`policy`).
  - `deploy/register/cosmos_store.py:28`.
  - `mcp/cosmos_store.py:47-48` (`mcp_servers` `/id`).
  - `aggregates/cosmos.py:41`.
  - `services/api/neurosphere_api/copilot/cosmos_store.py:45-55` (`copilot_conversations` `/owner`, `default_ttl=-1`).
  - `services/api/neurosphere_api/reports/cosmos_store.py:49-61` (`reports` MultiHash).
  - `services/workers/neurosphere_workers/ingestion/cosmos_stores.py:27`.
  - `services/api/neurosphere_api/sandbox/repository.py:38-40`.
  - `catalog/repo/cosmos.py:51-55` (shape resolved at runtime).
- Copilot: `packages/core/neurosphere_core/copilot/models/endpoints.py:24-32` (allowed suffixes include `.cognitiveservices.azure.com`; Commercial scope `https://cognitiveservices.azure.com/.default`); `gating.py:130` `resolve_adapters`; `capabilities/data/foundry.yaml:452-472` (Commercial rows `unverified`).
- Search: `packages/core/neurosphere_core/search/azure/client.py:1-9` (lexical only) and `fallback.py:36-100` (fixture fallback with disabled reason).
- PRP-06 data-plane role posture: `scripts/gates/prp06_cosmos_live.py:12-17`. G03 control-plane provisioning: `scripts/gates/g03_live.py:15-21`.
- Tests that pin current behaviour:
  - `tests/unit/infra/test_helm_render.py:160-166` asserts `httpsOnly: true` occurs exactly 2 times. Item 2 must update it to "once per declared site".
  - `:169-182`: no literal Azure hosts in `infra/appservice/*`.
  - `tests/unit/infra/test_bicep_build.py:28-37,92-95`: the service-module set is a subset check, so new demo modules outside `infra/bicep/modules` are fine.
  - `tests/security/network/test_bicep_network.py:312-345`: `checked == 6`, `without == {ns-apim, ns-network}`, over core `main.bicep` only. Do not add modules to core `main.bicep`.
  - `:348-354`: no literal `publicNetworkAccess: 'Enabled'` under `infra/bicep/modules`.
- `.github/workflows/ci.yml:122-140`: the bicep job builds every `infra/**/*.bicep` and `*.bicepparam` but lints only core `main.bicep`.
- `scripts/prp_status.py:68-76`: non-PRP `depends_on` tokens become manual gates, split on `,`, `+` and `;`.
- `.claude/settings.json`: denies `Bash(az deployment:*)` for agents. Deploys run only through the gated script's subprocess, run by the operator.

### Patterns to match
- Gated live script: approval check before argparse or any import (`g01_deploy_smoke.py:798-812`), the `neurosphere_core` import proof (`:813-823`), injectable `AzRunner` and a fake runner in tests (`tests/unit/gates/test_g01_refuses_without_approval.py:1-40`), whitelisted evidence plus `scrub` plus `redact_subscriptions`, exit codes 0/1/2.
- Reuse-or-create service modules with a `created` output (`cosmos.bicep:43-47`). The demo composition calls them as modules with demo parameter values.
- Private endpoint plus zone group shape: `network/main.bicep:215-248`. The new module takes `subnetId` and `privateDnsZoneId` instead of creating them.
- Helper-module import for shared script code: `g02_profile_appservice.py:51-55`.
- Evidence layout: `docs/evidence/G01/README.md` and dated `.json`+`.md` pairs.

### Conventions
- Python `python` (never `python3`); run gate scripts with `uv run python`. ruff (line 100, py312, S rules), pyright standard, conventional commits, owned-file discipline.
- Bicep: `targetScope = 'resourceGroup'`, `@description` on every param and output, hostnames from `environment()`, no literal Azure hosts in `infra/appservice/*` or `infra/demo/*`, no `listKeys`, no secret outputs.
- Test package names must be unique across the repo: use `tests/unit/hosted_demo/` and `tests/unit/hosted_sandbox_guard/`, never a second `sandbox/` package (memory: package name clash).
- **No new dependencies** (Python or npm). Playwright is already present.
- Run Snyk code scan on new first-party Python (`scripts/gates/hosted_demo*.py`, guard change) and fix findings before review.

### Gotchas
- Run gate scripts with `uv run python`, not plain `python`. A plain run once crashed mid-teardown and stranded billable resources; the script must prove `neurosphere_core` imports before any `az` call.
- Prefix `MSYS_NO_PATHCONV=1` on any argument starting with `/subscriptions/...` or a Cosmos path such as `/chain_id`; Git Bash rewrites them. Put it in the runbook commands.
- The script checks `az account show` against `--subscription` and never calls `az account set`. The operator runs `az account set --subscription "Limitlessdata - DMLZ"` before and restores their default (currently Limitlessdata - Main) after. The runbook says so.
- `cmd | tail` masks exit codes. Redirect to a log and `echo $?`. Read failed deployments with `az monitor activity-log list --resource-group <rg> --offset 2h --status Failed`; agents cannot run `az deployment`.
- The Modify policy shows up only as `policies/modify/action` in the activity log. Another management-group policy (for example on App Service public access) could silently flip the frontend private. The script's post-deploy check re-reads each site's `publicNetworkAccess` and fails loudly on a mismatch. Subscription-level `az policy assignment list` shows only Defender/ASC assignments; management-group assignments were not readable on 2026-10-24.
- Entra data-plane tokens cannot create databases or containers (403 substatus 5300), so every database and container is in Bicep (`Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers`). A serverless container must not carry `options.throughput`. Hierarchical keys use `partitionKey.kind: 'MultiHash'`, `version: 2`.
- The catalog container shape is resolved at runtime and falls back to flat `/domain` while `cosmos_db.hierarchical_partition_keys.commercial` is `unverified`. Bicep must match the resolved shape, not the requested one, or the app fails on first write. Partition keys are immutable, so a mismatch means delete and recreate.
- Serverless: `az` uses `--capacity-mode Serverless` (`--capabilities EnableServerless` is rejected on the new API). In ARM, confirm whether `properties.capacityMode: 'Serverless'` or `capabilities: [{name: 'EnableServerless'}]` is accepted on `2024-11-15` (verify at plan approval with `az bicep build` plus what-if).
- `az cosmosdb` is slow and memory-heavy: run it sequentially, in the background, with a bounded wait.
- P2S DNS: the generated profile needs `<dnsservers><dnsserver>10.0.9.4</dnsserver></dnsservers>` and the `.documents.azure.com` suffix (plus `.servicebus.windows.net` and `.blob.core.windows.net` for seeding). Verify with `Resolve-DnsName` in a `.ps1`; `nslookup` ignores NRPT.
- App Service and the hub subnet: disconnect VNet integration before deleting apps or the plan, or the service association link can linger on the shared subnet and block it. Teardown order is fixed in item 4.
- App Service resolves names through VNet DNS when integrated. The hub uses Azure DNS with hub-linked zones, so the API PE resolves for the frontend's nginx proxy. nginx resolves a static upstream once at start, so restart the frontend after the API PE is created. The proxy must send SNI and `Host` equal to the API hostname (App Service routes by host).
- `WEBSITES_PORT` per app (8000/8090/8080). The workers bind `127.0.0.1` by default, so set `NS_WORKER_HEALTH_HOST=0.0.0.0` or the container never reports healthy. The API and workers have `publicNetworkAccess: Disabled`; confirm the platform health check still reaches them (verify at plan approval). The fallback is access restrictions with default deny.
- GHCR packages are public: pull anonymously with `DOCKER|ghcr.io/...:<tag>` and `acrUseManagedIdentityCreds: false`, and no registry credentials anywhere. Releasing a tag publishes public images. The demo has no route table, so egress to GHCR and Entra uses App Service default outbound. Keep `outboundVnetRouting.allTraffic` (`vnetRouteAllEnabled`) **false**, so only RFC1918 traffic (the PEs) enters the hub and nothing transits the hub firewall unintentionally.
- Private endpoints cost about $7.30/month each plus data, so four PEs are about 30% of the bill. Event Hubs Basic cannot take a PE.
- Key Vault purge protection blocks purge at teardown (expected; only relevant if `deployKeyVault=true`). The name stays reserved for 90 days.
- Graph `PATCH /applications/{id}` with `spa.redirectUris` **replaces** the array. GET first, merge, PATCH from a body file (`az rest --body @temp/...json`), and record the prior list for teardown restore. `az ad app update` cannot set nested `api` properties.
- v2 tokens: `aud` is the bare app GUID, so the API's configured audiences must include it (PRP-29 settings contract).
- Foundry token spend is billed to the shared Foundry account and is invisible to the RG budget. The runbook says so, and the copilot uses `mini`.
- The repo is **public**. Commit no subscription, tenant, principal or app GUIDs, emails, hostnames with suffix hashes or hub resource ids in params or docs. The script takes them as arguments; evidence goes through `redact_subscriptions` and the scrubber.
- After any live run, check for leftover `rg-ns-*` groups and orphaned PEs in the hub subnet (`az network private-endpoint list` filtered by tag).
- CodeQL and gitleaks: split credential-shaped literals in tests (fake keys in guard tests), no `py/side-effect-in-assert`, no PEP 695 generics in nested defs.
- `integration`-marked tests never run in CI. Every test this PRP needs is a unit test with fakes.
- Playwright: the hosted spec has its own config, with no `webServer` and no `reuseExistingServer`. It is excluded from the default config's `testDir` so CI never runs it. The storage state lives under `temp/` and is never committed.

### External references
Verified with Microsoft Learn MCP on 2026-10-24 unless marked otherwise.
- App Service regional VNet integration: Basic and up; subnet delegated to `Microsoft.Web/serverFarms`; multi-plan subnet join needs /26 or larger; only RFC1918 is routed unless route-all is set; up to two integrations per plan. https://learn.microsoft.com/azure/app-service/overview-vnet-integration
- App Service inbound private endpoints: Basic, Standard, PremiumV2/V3/V4; the integration subnet cannot also host the PE. https://learn.microsoft.com/azure/app-service/overview-private-endpoint
- Disconnect VNet integration before deleting an app on a delegated subnet: https://learn.microsoft.com/troubleshoot/azure/virtual-network/virtual-network-troubleshoot-cannot-delete-modify-subnet
- Event Hubs tiers: Basic has no Private Link and 1 consumer group; Standard has 20. https://learn.microsoft.com/azure/event-hubs/compare-tiers, https://learn.microsoft.com/azure/event-hubs/private-link-service
- Cosmos serverless: single region, no throughput on containers, 5,000 RU/s per physical partition. https://learn.microsoft.com/azure/cosmos-db/serverless
- Hierarchical partition keys: up to 3 levels, new containers only, Python SDK >= 4.6. https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys
- Keyless Azure OpenAI: chat completions role Cognitive Services OpenAI User `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`. https://learn.microsoft.com/azure/developer/ai/keyless-connections
- Custom containers on App Service (`acrUseManagedIdentityCreds` is for ACR only): https://learn.microsoft.com/azure/app-service/configure-custom-container
- Verify at plan approval (not confirmed in this session): Cosmos ARM `capacityMode` vs `EnableServerless` on `2024-11-15`; whether App Service health check reaches sites with `publicNetworkAccess: Disabled`; whether Log Analytics `publicNetworkAccessForIngestion: Disabled` blocks App Service diagnostic settings; the `Microsoft.Consumption/budgets` RG-scope schema; whether App Service accepts digest-pinned `DOCKER|image@sha256:` references; current list prices (Azure pricing calculator).

### Cross-PRP contracts (PRP-29 delivers; PRP-32 consumes)
- **C1 frontend `/api` proxy**: nginx proxies `/api/` to an upstream taken from an environment variable (proposed `NS_API_UPSTREAM`, an HTTPS origin) with `proxy_ssl_server_name on` and `Host` set to the upstream host. Default unset means local behaviour.
- **C2 runtime config**: the frontend container renders `/config.json` from environment variables at start (proposed `NS_FRONTEND_CLOUD`, `NS_FRONTEND_TENANT_ID`, `NS_FRONTEND_CLIENT_ID`, `NS_FRONTEND_API_BASE_URL`, `NS_FRONTEND_API_SCOPE`) when set, else serves the baked default. It is still served `no-store`.
- **C3 API/worker settings**: a documented environment-variable list for the real bootstrap (Cosmos endpoint and database, Event Hubs FQDN and hub, blob account, JWT tenant and audiences, copilot adapter endpoint and deployment), with no secret-valued setting under `NS_ENV=prod`.
- **C4 seeder**: an entry point that loads `sbx_cli` output into the stores the real API reads (catalog, ledger and aggregates, policy grants for a given principal), takes an `AsyncTokenCredential` and an endpoint, and creates no database or container when `NS_ENV` is not `local`.

If PRP-29 ships different names, item 2/3 maps them in app settings only. If a contract is missing, that is a blocking plan delta raised before wave B, not a silent workaround in PRP-29-owned files.

### Cost (estimate; verify with the Azure pricing calculator at plan approval)
| Resource | SKU / setting | Est. USD/month |
|---|---|---|
| App Service plan (Linux) | B2 x1 (api, workers, web) | ~26 (P0v3 option ~62) |
| Cosmos DB | Serverless, single region, <1 GB, low RU | ~1-10 |
| Event Hubs | Standard, 1 TU, 1 hub, 1 extra consumer group | ~22 |
| Storage | StorageV2 LRS (checkpoints, quarantine) | ~1-2 |
| Private endpoints | 4 (Cosmos, Event Hubs, blob, API site) | ~29 + data |
| Log Analytics | PerGB2018, 30 d, 0.1 GB/day cap | <=7 |
| Key Vault | not deployed (`deployKeyVault=false`) | 0 (+~8 with PE if enabled) |
| AI Search | not deployed | 0 (Basic add-on ~75 + PE) |
| APIM | not deployed | 0 |
| Cost Management budget | RG budget | 0 |
| **Subtotal in RG** | | **~90-105** |
| Foundry tokens (`mini`) | usage-based, shared account, outside RG budget | ~<5 at demo usage |

## Implementation blueprint

### Item 1 - demo-data-and-network-modules  [P]
- Deliverable:
  - New modules under `infra/demo/modules/`:
    - `hub-private-endpoint.bicep`: PE in this RG, NIC in a given subnet id, zone group to a given existing zone id; `groupId` param.
    - `cosmos-data.bicep`: `existing` account, `sqlDatabases` `neurosphere`, every container with partition key, TTL and kind, and no throughput.
    - `cosmos-rbac.bicep`: custom SQL role definitions (app read-create-query at database scope; replace/upsert on the non-audit containers) and assignments for the api and workers principals. An optional time-boxed seeder assignment of the built-in `...0002` at database scope, driven by `seederPrincipalId`, empty by default.
    - `messaging-data.bicep`: event hub `telemetry`, consumer group `normalizer`, blob containers for checkpoints and quarantine, and role assignments (Event Hubs Data Sender for api, Data Receiver for workers, Storage Blob Data Contributor scoped to the containers).
    - `budget.bicep`: `Microsoft.Consumption/budgets` at RG scope with an amount, start date, contact emails and the 50/80/100/forecast-100 notifications.
  - Additive params: `capacityMode` in `infra/bicep/modules/cosmos.bicep` (`Provisioned|Serverless`, default `Provisioned`) and `dailyQuotaGb` in `infra/bicep/modules/loganalytics.bicep` (default `-1`).
- Owned files (may edit): `infra/demo/modules/**` (new), `infra/bicep/modules/cosmos.bicep` (one param + its use), `infra/bicep/modules/loganalytics.bicep` (one param + its use), `tests/unit/hosted_demo/test_demo_modules.py` (new), `tests/unit/hosted_demo/test_cosmos_container_drift.py` (new), `tests/unit/hosted_demo/__init__.py`, `tests/unit/hosted_demo/conftest.py`.
- Must NOT touch: `infra/bicep/modules/main.bicep`, `infra/bicep/modules/network/**`, other core modules, `infra/bicep/params/**`, `infra/appservice/**` (item 2), `packages/**`, `services/**`.
- Depends on: none.
- Acceptance criteria:
  - Every new module builds with `az bicep build` and lints clean.
  - Core `main.bicep` compiled ARM with default params equals the pre-change build (golden comparison in test).
  - `hub-private-endpoint.bicep` declares no `privateDnsZones`, `virtualNetworks` or `subnets` resource (only `existing` references).
  - The drift test parses container constants and partition key paths from the store modules listed in "Files that matter" and asserts set equality with `cosmos-data.bicep`. MultiHash containers declare `kind: 'MultiHash'`, `version: 2`, and `copilot_conversations` has `defaultTtl: -1`. Where the shape is resolved at runtime (catalog), the test pins the shape the shipped matrix resolves to today, and the comment cites the gotcha.
  - No container carries `throughput`. RBAC has no account-wide data contributor for the app identities, and the audit records container is not covered by any role with replace/upsert/delete.
  - No `listKeys` and no secret-named outputs.
- Pattern references: `network/main.bicep:215-248`; `cosmos.bicep:20-47`; `prp06_cosmos_live.py:12-17`; `tests/unit/infra/test_bicep_build.py:41-95`.
- Tests to write: `tests/unit/hosted_demo/test_demo_modules.py`, `tests/unit/hosted_demo/test_cosmos_container_drift.py`.

### Item 2 - appservice-profile-extension  [P]
- Deliverable: additive features in `infra/appservice/main.bicep`. Defaults compile to today's two-app ACR-MI profile; `main.bicepparam` is untouched.
  - `frontendRepository` (default `''`; non-empty declares `<prefix>-web` on 8080, `healthCheckPath /`).
  - `registryAuth` (`managedIdentity` default | `anonymous`).
  - `virtualNetworkSubnetId` (default `''`), with `vnetRouteAllEnabled: false`.
  - `apiPublicNetworkAccess`, `workersPublicNetworkAccess`, `frontendPublicNetworkAccess` (default `Enabled`, today's behaviour).
  - `apiAppSettings`, `workersAppSettings`, `frontendAppSettings`, merged after `commonAppSettings`.
  - Workers always get `NS_WORKER_HEALTH_HOST=0.0.0.0`.
  - Outputs add `apiSiteId`, `frontendHostName`, `apiHostName` and `frontendPrincipalId`.
- Owned files (may edit): `infra/appservice/main.bicep`, `tests/unit/infra/test_helm_render.py` (only `test_app_service_security_posture`: counts become per declared site), `tests/unit/hosted_demo/test_appservice_profile.py` (new).
- Must NOT touch: `infra/appservice/main.bicepparam`, `infra/helm/**`, `scripts/gates/g02_*` (the Government gate keeps its default behaviour), `frontend/**`.
- Depends on: none.
- Acceptance criteria:
  - With defaults, the compiled ARM has the same resources and site properties as before (test against a golden build). `test_images_match_app_service_profile` and `test_no_literal_azure_endpoints` stay green.
  - With `registryAuth=anonymous`, `acrUseManagedIdentityCreds` is false and `acrUserManagedIdentityID` is null on all sites.
  - With `frontendRepository` set, there are 3 sites, each `httpsOnly`, TLS 1.2, FTPS disabled.
  - `virtualNetworkSubnetId` is set on all sites when given.
  - `publicNetworkAccess` follows the params. `NS_WORKER_HEALTH_HOST=0.0.0.0` is present on workers.
- Pattern references: `infra/appservice/main.bicep:89-147`; `tests/unit/infra/test_helm_render.py:140-182`.
- Tests to write: `tests/unit/hosted_demo/test_appservice_profile.py`; update `test_app_service_security_posture`.

### Item 3 - demo-composition
- Deliverable: `infra/demo/main.bicep` composes these:
  - core `cosmos.bicep` (Serverless), `eventhubs.bicep` (Standard), `storage.bicep`, `loganalytics.bicep` (30 d, 0.1 GB/day) and, if `deployKeyVault`, `keyvault.bicep`;
  - `infra/appservice/main.bicep` (B2 x1, `registryAuth=anonymous`, GHCR images, frontend on, VNet integration subnet id param, API and workers private);
  - item 1 modules: four hub PEs (Cosmos `Sql`, Event Hubs `namespace`, blob `blob`, API `sites`), Cosmos data and RBAC, messaging data, budget;
  - diagnostic settings for the three sites into Log Analytics.

  App settings implement contracts C1-C3 with endpoints derived from module outputs and `environment()`. `infra/demo/main.bicepparam` holds placeholders and non-sensitive defaults only (prefix `nsdemo`, `centralus`, SKU, tag, budget amount). One `az bicep lint` line for `infra/demo/main.bicep` is added to the CI bicep job.
- Owned files (may edit): `infra/demo/main.bicep`, `infra/demo/main.bicepparam`, `tests/unit/hosted_demo/test_demo_composition.py` (new), `.github/workflows/ci.yml` (bicep job: one lint line only).
- Must NOT touch: `infra/demo/modules/**` (item 1), `infra/appservice/**` (item 2), `infra/bicep/**`.
- Depends on: Items 1 and 2.
- Acceptance criteria:
  - Compiled-ARM tests: no APIM, Search, VNet, subnet or `privateDnsZones` resource; Key Vault only when the flag is set.
  - Data services `Disabled`; only `<prefix>-web` has `publicNetworkAccess: Enabled`.
  - Required tags on every created resource.
  - Hub subnet ids, zone ids, Foundry endpoint, tenant/client ids and budget emails are parameters without defaults, so `main.bicepparam` holds no GUID, email or resource id (test greps the param file).
  - No secret markers; `az bicep build-params` succeeds; CI lints the demo template.
- Pattern references: `infra/bicep/modules/main.bicep:51-127` (module wiring); `tests/security/network/test_bicep_network.py:300-354` (public-access assertions).
- Tests to write: `tests/unit/hosted_demo/test_demo_composition.py`.

### Item 4 - gated-deploy-script  [P]
- Deliverable: `scripts/gates/hosted_demo.py` (and `scripts/gates/_hosted_demo_common.py` if it grows) with these subcommands:
  - `preflight`: read-only. Cloud, account, providers registered, hub subnet delegation and emptiness, zone presence, Foundry deployment present, region capacity hints.
  - `plan`: create the RG if absent (tagged), generate the params file in a temp dir from args, run what-if, print a change summary and the sha256 of the normalized change list.
  - `deploy`: requires `--approve-plan <hash>` plus `--approve-shared hub-subnet,hub-pe,hub-dns[,budget]`; re-runs what-if and refuses on a hash change; deploys; writes the ownership register to Cosmos `deploy_register` and to `temp/hosted-demo/register-<id>.json`; writes `temp/hosted-demo/registration.json` for item 5; post-checks each site's `publicNetworkAccess` and image reference.
  - `grant-model-access`: `--approve-shared foundry-role`. Role assignment on the Foundry account for the API principal, recorded in the register as created-on-reused-parent.
  - `entra-redirect`: `--approve-shared entra-app`. Graph GET, merge, PATCH from a body file; the prior list is saved for restore.
  - `seed-access --grant|--revoke`: time-boxed seeder role on the NeuroSphere-owned Cosmos account only.
  - `smoke`: item 6.
  - `teardown`: `--confirm <deployment-id>`, register-guarded, in this order: Entra redirect restore, Foundry role removal, seeder role removal, VNet integration disconnect, API PE and data PEs, sites and plan, data services, budget, RG only when the register shows no foreign resource.
  - `status`: read-only drift (what-if) and `delete-after` date.

  Evidence goes to `docs/evidence/PRP-32/`.
- Owned files (may edit): `scripts/gates/hosted_demo.py` (new), `scripts/gates/_hosted_demo_common.py` (new, optional), `tests/unit/gates/test_hosted_demo_refuses.py` (new), `tests/unit/gates/test_hosted_demo_flow.py` (new), `tests/unit/gates/test_hosted_demo_teardown.py` (new).
- Must NOT touch: `scripts/gates/g01_*`, `scripts/gates/g02_*`, `_g02_profile_common.py` (import helpers from g01 through `importlib`, don't edit), `infra/scripts/uninstall.py`, `packages/**`, `.claude/settings.json`.
- Depends on: none. It codes against the item 3 parameter names, listed in its module docstring and checked by a test that reads `infra/demo/main.bicep` param names once item 3 lands (skips with a reason before).
- Acceptance criteria:
  - With `NS_LIVE_APPROVED` unset: exit 2, zero runner calls (test).
  - Wrong cloud, account mismatch, Government region, missing `neurosphere_core`: exit 2 before any mutating call.
  - `deploy` without `--approve-plan`, or with a stale hash, refuses after what-if with no create call.
  - Each shared step refuses without its token. Approvals land in the evidence with operator and UTC time.
  - The default path keeps the environment. `teardown` without `--confirm` or with a wrong id refuses. Teardown refuses when the RG holds an unregistered resource and never deletes a shared resource (the hub subnet, zones, Foundry account or Entra app object).
  - The VNet disconnect happens before site deletion (call-order test).
  - The evidence scrubber fails on a fake key or JWT. Subscription and tenant GUIDs are redacted in written evidence.
- Pattern references: `g01_deploy_smoke.py:61-120,238-312,352-367,466-520,676-833`; `g02_profile_appservice.py:51-55`; `packages/core/neurosphere_core/deploy/register/guard.py:42-121`.
- Tests to write: the three `tests/unit/gates/test_hosted_demo_*.py` files, with a fake `AzRunner` only.

### Item 5 - hosted-seeding-and-guard  [P]
- Deliverable:
  - `sbx_guard.require_hosted_endpoint(url, *, kind, env, registration_path)`: allows exactly the registered Cosmos or Event Hubs host under the conditions in the acceptance criteria. It returns no key; the hosted path uses `DefaultAzureCredential`. The module docstring keeps "no override" for the local path and documents the single registered-environment exception.
  - `scripts/gates/hosted_demo_seed.py`:
    - `NS_LIVE_APPROVED=1` first;
    - verifies the registration and the guard;
    - generates synthetic data with the existing generator (deterministic seed);
    - calls the PRP-29 seeder (contract C4) with Entra auth, writing policy grants for `--grant-principal` (the operator's object id) on the synthetic domains;
    - optionally replays telemetry to the hosted hub;
    - writes counts-only evidence.

    It never accepts a key or connection string and never creates a database or container.
- Owned files (may edit): `scripts/sandbox/sbx_guard.py` (new function and docstring only; existing functions unchanged), `scripts/gates/hosted_demo_seed.py` (new), `tests/unit/hosted_sandbox_guard/__init__.py`, `tests/unit/hosted_sandbox_guard/test_hosted_allow.py` (new), `tests/unit/gates/test_hosted_demo_seed_refuses.py` (new).
- Must NOT touch: `scripts/sandbox/sbx_cli.py`, `scripts/sandbox/sbx_seam.py`, `scripts/sandbox/sandbox.mk` (PRP-29 local seeding), `tests/integration/sandbox/**`, `packages/**`, `services/**`.
- Depends on: none for the guard. The seeder call codes against C4 and is exercised with a fake until PRP-29 merges.
- Acceptance criteria:
  - Allowed: the exact registered host, approval set, id match, no key.
  - Refused (each a test): another `*.documents.azure.com` host, a Government suffix, loopback through the hosted function, missing or garbled registration, id mismatch, `NS_SANDBOX_COSMOS_KEY` or an Event Hubs connection string present, approval unset, a URL with userinfo or query.
  - Error messages echo no secret or userinfo. The existing `tests/integration/sandbox/test_prefix_guard.py` semantics are unchanged.
  - The seed script refuses without approval and runs no network call (test). Seeded data comes only from the synthetic generator (the test asserts the input directory is the generator output).
- Pattern references: `sbx_guard.py:26-70`; `g03_live.py:39-80`; `packages/core/neurosphere_core/clients/factories.py:47-71`.
- Tests to write: `tests/unit/hosted_sandbox_guard/test_hosted_allow.py`, `tests/unit/gates/test_hosted_demo_seed_refuses.py`.

### Item 6 - post-deploy-smoke  [P]
- Deliverable: the `smoke` subcommand logic as a pure module (`scripts/gates/_hosted_demo_smoke.py`) using `httpx` (already a dependency) with an injectable transport. It runs the unauthenticated checks in the acceptance criteria and gets app state and the `HealthCheckStatus` metric through the `az` runner. Also `frontend/tests/hosted/hosted-smoke.spec.ts` and `frontend/playwright.hosted.config.ts`: no webServer, `baseURL` from `NS_HOSTED_URL`, `storageState` from `temp/hosted-demo/auth.json`, refuses to run when either is missing, one spec with axe on the shell and overview (with the documented tabster exclusion).
- Owned files (may edit): `scripts/gates/_hosted_demo_smoke.py` (new), `tests/unit/gates/test_hosted_demo_smoke.py` (new), `frontend/tests/hosted/**` (new), `frontend/playwright.hosted.config.ts` (new).
- Must NOT touch: `frontend/src/**` (PRP-30/31), `frontend/playwright.config.ts` (except that its `testDir` must already exclude `tests/hosted`; if it does not, raise a plan delta), `frontend/package.json`, `frontend/nginx.conf`, `frontend/Dockerfile`.
- Depends on: none (`hosted_demo.py` imports it; item 4 wires the subcommand).
- Acceptance criteria:
  - Unit tests with `httpx.MockTransport` show that each check passes on the expected response and fails on: 200 from the API's own hostname, a `config.json` with zero GUIDs, a cross-origin `apiBaseUrl`, a missing `no-store`, 200 instead of 401 on the unauthenticated API call.
  - `pnpm --filter @neurosphere/frontend exec playwright test -c playwright.hosted.config.ts --list` lists the spec offline.
  - The default Playwright run does not include it.
- Pattern references: `frontend/tests/helpers/axe.ts:15-18`; `frontend/tests/e2e/copilot.spec.ts:8-12`; `frontend/tests/e2e/hidden-route.spec.ts`.
- Tests to write: `tests/unit/gates/test_hosted_demo_smoke.py`; the hosted spec (manual run only).

### Item 7 - release-candidate-and-image-pin
- Deliverable: following `docs/release/release-process.md`, a `release/v0.1` branch commit with the CHANGELOG section and Chart `version`/`appVersion` `0.1.0-rc.2`, and `imageTag = '0.1.0-rc.2'` in `infra/demo/main.bicepparam`. After operator approval (S8), the tag `v0.1.0-rc.2` is pushed, `release.yml` publishes, the operator verifies signatures and attestations per `docs/release/verify.md`, and the digests are recorded in `docs/evidence/PRP-32/release-v0.1.0-rc.2.md`. `release.yml` is **not** modified.
- Owned files (may edit): `CHANGELOG.md` (new section only), `infra/helm/Chart.yaml` (`version`, `appVersion` only), `infra/demo/main.bicepparam` (`imageTag` line only), `docs/evidence/PRP-32/release-v0.1.0-rc.2.md` (new).
- Must NOT touch: `.github/workflows/release.yml`, `infra/helm/values.yaml`, `infra/appservice/main.bicepparam`.
- Depends on: Item 3 (owns `main.bicepparam` until merged) and PRP-29 merged (PRP-30/31 too if in flight).
- Acceptance criteria:
  - The release workflow run is green.
  - Three images exist at `ghcr.io/fgarofalo56/neurosphere/{api,workers,frontend}:0.1.0-rc.2`.
  - `cosign verify` and `verify-attestation` outputs are recorded (identity and issuer only).
  - `test_helm_render` stays green.
- Pattern references: `docs/release/release-process.md:8-62`; `docs/evidence/PRP-13/release-v0.1.0-rc.1.md`.

### Item 8 - runbook-cost-and-gates-register
- Deliverable: `docs/deploy/hosted-demo.md` (architecture sketch in text plus one Mermaid diagram rendered through `scripts/render_mermaid.py` if added, prerequisites, every step S1-S10 with exact `uv run python` and `MSYS_NO_PATHCONV=1` commands and the approval it needs, update path, seeding, user and role assignment, the cost table, the `delete-after` monthly review, teardown and orphan checks, troubleshooting from the Gotchas). Also `docs/evidence/PRP-32/README.md` and dated PRP-32 notes in `docs/RESEARCH-AND-GATES.md` for G01 (App Service/Cosmos serverless/Event Hubs Standard in centralus observed), G07 (cost estimate, not a measurement) and G12 (live-vs-emulator deltas found).
- Owned files (may edit): `docs/deploy/**` (new), `docs/evidence/PRP-32/README.md` (new), `docs/RESEARCH-AND-GATES.md` (append dated PRP-32 notes only), `docs/diagrams/` (only the rendered SVG for this runbook, if any).
- Must NOT touch: other docs, `PRPs/**` (the orchestrator updates the index and execution state).
- Depends on: Items 3-6 (the commands must match the shipped CLI).
- Acceptance criteria:
  - Every command in the runbook exists in the shipped CLI (a test parses the fenced commands and checks subcommand names against `hosted_demo.py --help`).
  - No GUID, email or hub resource id is in the docs (gitleaks plus a grep test).
  - The cost table carries the "estimate; verify" label. Gate rows change status only where item 9 evidence exists.
- Pattern references: `docs/ops/dr-runbook.md`; `docs/evidence/G01/README.md`.
- Tests to write: `tests/unit/hosted_demo/test_runbook_commands.py`.

### Item 9 - live-deploy-seed-and-smoke (operator-gated)
- Deliverable: the operator runs S1-S10 (see "Live and open gates") with `NS_LIVE_APPROVED=1` and explicit approval per step. Evidence goes to `docs/evidence/PRP-32/` (`<date>-preflight`, `-plan`, `-deploy`, `-grant`, `-entra`, `-seed`, `-smoke`, plus `-teardown` only if run). Anything not run is reported OPEN. Agents never run these steps (`az deployment` is denied to agents).
- Owned files (may edit): `docs/evidence/PRP-32/**` (generated), `packages/core/neurosphere_core/capabilities/data/foundry.yaml` (one dated Commercial `centralus` row for the verified copilot deployment, decision 5, only after S4 plus a live answer), plus the item 8 docs if a live finding needs a correction (sequenced after item 8).
- Must NOT touch: code. A live failure becomes a plan delta or follow-up issue, not a hot fix inside this item.
- Depends on: Items 1-8 merged, PRP-29 merged, the release from item 7.
- Acceptance criteria: as the item 9 PRP acceptance criterion; leftover-resource check recorded (`rg-ns-*`, hub PEs by tag).

### Item 10 - s3-recovery-fix (plan delta, operator-approved 2026-10-27)
- Why: S3 on 2026-10-27 created every planned resource (all 17 nested module deployments Succeeded), but the top-level `hosted-demo` deployment failed with `ResourceNotFound` on `nsdemo-cosmos-*` and `nsdemo-ehns-*`. `infra/demo/main.bicep` declares `cosmosAccount` and `eventHubsNamespace` as `existing` to feed the `cosmosEndpoint` and `eventHubsFqdn` outputs. Those compile to out-of-template `reference(resourceId(...))` calls. Learn (template-functions-resource#reference): the reference is deferred until the referenced resource completes only when that resource is in the same template, and these are created inside nested modules. Because `deploy` stopped at `deployment-create`, the ownership register, registration file, pseudonym key and site post-checks never ran. A plain re-run would register every resource (and the budget) as pre-existing and not ours, so teardown would refuse. Key Vault purge protection (90 days) rules out teardown and redeploy under the same name.
- Deliverable:
  1. Template: `infra/bicep/modules/cosmos.bicep` outputs `documentEndpoint`, and `infra/bicep/modules/eventhubs.bicep` outputs the service bus endpoint. Each uses `empty(reuse) ? <declared resource>.properties.x : <existing by reuse id>.properties.x`; ARM `if()` evaluates only the branch it takes when the condition can be evaluated at the start (Learn, template-functions-logical#if). `main.bicep` drops both `existing` declarations and builds the outputs from module outputs and the name variables. Regression test: in the compiled `main.bicep`, every `reference(` in `outputs` targets `Microsoft.Resources/deployments`.
  2. Script: `hosted_demo.py deploy --resume-failed <failed deploy evidence .json>`. Refuse with exit 2, before any az write, unless all of these hold: `rg_is_ours`; the file has `command == deploy`, `result == FAIL`, a matching `deployment_id` and a `plan-hash` approval; a plan evidence file in `--evidence-dir` has the same `plan_sha256` and carries `details.changes`; and the local register has no `created_by == neurosphere` rows. Ownership is decided by the existing rule, plus: a live resource or budget whose scrubbed, lower-cased id (the same scrubber used by `finalize_evidence`) is in that prior plan's Create ids, or a PE NIC whose PE was Create'd there, is ours. Everything else stays not ours. Evidence records `resumed_from` (file name) and how many resources the resume registered. Without the flag, behaviour is unchanged.
  3. Evidence keeps the whole az error: the hosted_demo `AzError` call sites pass a larger `safe_text` limit (4000). The secret-pattern redaction and the evidence scrubber still apply.
  4. The runbook (`docs/deploy/hosted-demo.md`) S3 section gains "Recovering from a failed deploy" (`plan`, then `deploy --resume-failed`).
- Owned files (may edit): `infra/bicep/modules/cosmos.bicep`, `infra/bicep/modules/eventhubs.bicep`, `infra/demo/main.bicep`, `scripts/gates/hosted_demo.py`, `tests/unit/gates/test_hosted_demo_flow.py` (or a new `tests/unit/gates/test_hosted_demo_resume.py`), `tests/unit/infra/test_demo_composition.py`, `tests/unit/infra/core_main_resources.golden.json` (only if a golden assertion requires it), `docs/deploy/hosted-demo.md` (S3 section only).
- Must NOT touch: `docs/evidence/**`, `PRPs/**`, `scripts/gates/_hosted_demo_common.py` (unless the scrubber must be exported; then say so), other gate scripts, `services/**`, `packages/**`, `frontend/**`.
- Depends on: items 1-8 merged. Live follow-on: the operator re-runs S2 `plan` and then S3 `deploy --resume-failed docs/evidence/PRP-32/2026-10-27-deploy.json` with the new hash and the same shared tokens.
- Acceptance criteria: the item gates below pass, plus `NS_LIVE_APPROVED= ... deploy --resume-failed x` refuses with exit 2; a fake-runner test shows resume registering the prior-plan resources and budget as ours and leaving a foreign resource not ours; one test per precondition shows a refusal; without the flag, behaviour is unchanged (existing tests pass).
- review: required (one independent pass).

### Item 11 - live-run-fixes (plan delta, operator-approved 2026-10-28)
- Why: three script defects found live.
  - (a) The S6 `seed-access --grant` passes bare role GUIDs to `az role assignment create/list --role`. At a blob-container scope az could not resolve the GUID and failed with `RoleDefinitionDoesNotExist` for Storage Blob Data Contributor, so the Key Vault grant was never reached.
  - (b) `deploy` creates the pseudonym secret after the sites have already started. App Service had cached `SecretNotFound` for the Key Vault references, so the workers read all 2,521 seeded events but landed none (LandingTimeout). A plain restart did not refetch. Learn (app-service-key-vault-references#understand-rotation): references are cached for 24 h; force resolution with `POST <site id>/config/configreferences/appsettings/refresh?api-version=2022-03-01`. Live, that turned all four references to `Resolved`.
  - (c) `seed-access --revoke` deletes every live assignment matching principal/role/scope instead of only the ones the register recorded. It also prints "role assignment removed" even when it deleted nothing. Live it deleted only what it had granted, but the safety rests on the scope.
- Deliverable:
  1. Seed grants and revokes pass the full role-definition id `/subscriptions/<sub>/providers/Microsoft.Authorization/roleDefinitions/<guid>` to `--role`.
  2. After `ensure_pseudonym_secret` creates the secret, `deploy` POSTs the refresh for the API and workers sites. It then restarts them, re-reads `configreferences/appsettings` (GET, api-version 2023-12-01), and records a failed step if any reference is not `Resolved`, naming the setting and status, never a value.
  3. Revoke deletes only assignment ids that both exist live and are registered as created by `seed-access`. Each delete removes the matching register row. Logging reports the count actually removed, including 0. Cosmos follows the same rule.
  4. The runbook S3 and S6/S7 sections mention the refresh and the register-bound revoke.
- Owned files (may edit): `scripts/gates/hosted_demo.py`, `tests/unit/gates/test_hosted_demo_flow.py`, `tests/unit/gates/test_hosted_demo_refuses.py` (the shared fake `az`, only to add fake responses), a new `tests/unit/gates/test_hosted_demo_live_fixes.py`, `docs/deploy/hosted-demo.md` (S3 and S6/S7 sections only).
- Must NOT touch: `docs/evidence/**`, `PRPs/**`, `infra/**`, `scripts/gates/_hosted_demo_common.py` (unless the register needs a remove method; then say so), `hosted_demo_seed.py`, `services/**`, `packages/**`, `frontend/**`.
- Acceptance criteria: one fake-runner test per fix. The role arg is the full id at a container scope. A deploy that creates the secret calls refresh then restart for both sites, and fails the step on a non-`Resolved` status. A deploy that finds the secret present makes no refresh call. Revoke leaves an unregistered matching assignment in place, deletes the registered one, drops its row, and reports the true count. Existing tests still pass; the PRP-32 gates are green.
- review: required (one independent pass).

### Item 12 - s9-readiness-fixes (plan delta, operator-approved 2026-10-28)
- Why: S9 found two defects.
  - (a) `nsdemo-api` `/readyz` was 0% healthy. `infra/demo/main.bicep` hard-codes `NS_COPILOT_MODE: 'approved_endpoint'`, but the capability matrix has no Commercial `centralus` row for `model_gpt_4_1_mini` (decision 5 not yet approved). The copilot builder therefore marks the copilot failed, and a failed optional component blocks readiness (`runtime/builders/copilot.py`; only `disabled` does not). The PRP says the copilot is "disabled with reason" until decision 5. Live, `NS_COPILOT_MODE=disabled` was set on the API as an operator-approved interim fix, so the template must match it or the next deploy reverts it.
  - (b) The smoke's HealthCheckStatus check asks for `--interval PT1M`. Azure Monitor rejects that (`BadRequest`: allowed grains for HealthCheckStatus are 5 minutes, 1 hour and 1 day), and the smoke reports the failed call as "no HealthCheckStatus datapoints". It also passes `--metric` where the az flag is `--metrics`.
- Deliverable:
  1. `infra/demo/main.bicep`: `@allowed(['disabled', 'approved_endpoint', 'foundry_agent']) param copilotMode string = 'disabled'`, feeding `NS_COPILOT_MODE`. A test asserts that the compiled default is `disabled`.
  2. `scripts/gates/_hosted_demo_smoke.py`: `--metrics`, `--interval PT5M`, and an offset of `1h` (az's `##d##h` format). A non-zero az result fails the check with the az error's first line, scrubbed, instead of "no datapoints". Tests cover both.
  3. Runbook: the copilot stays disabled until the decision 5 row exists, then the operator sets `copilotMode` and re-plans. S9 notes the 5-minute metric grain.
  4. Added after the first fix (2026-10-28): with the copilot disabled, `/readyz` was still 503. A direct call over the API private endpoint (P2S VPN) showed `cosmos`, `eventhubs` and `blob` `unavailable` while every composition component was `ok`. The cause: `NS_PROBE_*` were unset, so the probes fell back to the localhost emulator defaults (`health/probes.py`). The final site pass now sets them from the cosmos/eventHubs module outputs and the storage suffix. Live interim values gave `/readyz` 200 "ready".
- Owned files (may edit): `infra/demo/main.bicep`, `infra/demo/main.bicepparam`, `scripts/gates/_hosted_demo_smoke.py`, `tests/unit/gates/test_hosted_demo_smoke.py`, `tests/unit/hosted_demo/test_demo_composition.py`, `docs/deploy/hosted-demo.md` (S9 and copilot notes only).
- Must NOT touch: `docs/evidence/**`, `PRPs/**`, `packages/core/**` (no capability row; that is decision 5), `services/**`, `frontend/**`.
- Acceptance criteria: the item gates are green; `az bicep build` and `build-params` succeed; the copilot-mode default test passes; the smoke tests fail on the old code.
- review: required (one independent pass).

### Waves
- A = items 1, 2, 4 and 5 [P] (WIP 4). Owned files are disjoint: `infra/demo/modules` plus two core params; `infra/appservice` plus the posture test; the deploy script; the guard plus seed script.
- B = items 3 and 6 [P]. Item 3 needs 1 and 2; item 6 shares no file with item 3.
- C = items 7 and 8 [P]. Item 7 needs item 3 merged and PRP-29 merged; item 8 needs items 3-6.
- D = item 9, live, strictly sequential S1-S10 with per-step approval.
- E = item 10 (plan delta from the S3 failure), then item 9 resumes at S2/S3.
- F = item 11 (live-run fixes from S3/S6/S7), in parallel with the S7 re-seed (the re-seed does not depend on it).

Shared files are sequenced: `infra/demo/main.bicepparam` (item 3, then the item 7 `imageTag` line), `tests/unit/infra/test_helm_render.py` (item 2 only), `.github/workflows/ci.yml` (item 3 only).

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
az bicep build --file infra/demo/main.bicep --stdout > /dev/null
az bicep build-params --file infra/demo/main.bicepparam --stdout > /dev/null
az bicep lint --file infra/demo/main.bicep
az bicep lint --file infra/appservice/main.bicep
for f in infra/demo/modules/*.bicep; do az bicep build --file "$f" --stdout > /dev/null || echo "FAIL $f"; done
uv run pytest -q tests/unit/hosted_demo tests/unit/hosted_sandbox_guard tests/unit/gates tests/unit/infra tests/security/network
uv run ruff check scripts/gates scripts/sandbox tests/unit
uv run ruff format --check scripts/gates scripts/sandbox tests/unit
uv run pyright scripts/gates/hosted_demo.py scripts/gates/hosted_demo_seed.py scripts/gates/_hosted_demo_smoke.py scripts/sandbox/sbx_guard.py
NS_LIVE_APPROVED= uv run python scripts/gates/hosted_demo.py preflight --subscription 00000000-0000-0000-0000-000000000000; echo "exit=$?"   # must print REFUSED, exit=2
pnpm --filter @neurosphere/frontend exec playwright test -c playwright.hosted.config.ts --list
python scripts/licenses_report.py --check
gitleaks detect --no-git --source infra/demo --source docs/deploy --source scripts/gates
```
Snyk code scan (MCP `snyk_code_scan`) on the new Python files; fix and rescan until no new issues.

The live steps are not validation gates. They are under "Live and open gates" and never run in CI or by an agent.

## Live and open gates
Every step needs `NS_LIVE_APPROVED=1` **and** the operator's explicit approval for that step in the session, recorded in the evidence (operator, UTC time, step, approval token). The operator runs `az account set --subscription "Limitlessdata - DMLZ"` first and restores their default afterwards. A step that did not run is reported **OPEN** in the completion note and in `docs/evidence/PRP-32/README.md`, never as a skipped green.
- **S1 preflight** (read-only): cloud, account, providers, hub subnet `snet-functions` empty and delegated, the hub zones present, Foundry `mini` present.
- **S2 plan**: create `rg-neurosphere-demo` (tagged) and run what-if. Approval: RG creation.
- **S3 deploy**: billable resources, plus the shared changes `hub-subnet` (join `snet-functions`), `hub-pe` (4 NICs in `snet-private-endpoints`), `hub-dns` (A records in 4 hub zones) and `budget`. Approval: the plan hash plus each shared token.
- **S4 grant-model-access**: role assignment on the shared `aifndry-loom-centralus`. Approval: `foundry-role`.
- **S5 entra-redirect and user/app-role assignment**: tenant change on `neurosphere-api-dev`. Approval: `entra-app`.
- **S6 seed-access --grant**: time-boxed seeder role on the NeuroSphere-owned Cosmos account. The operator is connected to the P2S VPN with resolver DNS.
- **S7 seed**: synthetic data only, through the hosted guard allow, then `seed-access --revoke`.
- **S8 release tag push** `v0.1.0-rc.2`: publishes public images. Approval: release (item 7).
- **S9 smoke**: the automated unauthenticated checks, then the manual Playwright hosted spec with the operator's sign-in (a manual gate; storage state stays in `temp/`).
- **S10 teardown**: only when the operator decides (the environment is persistent by default). Run the leftover check afterwards.

Gate interplay:
- G01 is narrowed only by observed resource availability in centralus with dated evidence.
- G07 gets a cost estimate and any measured hosted latency, labelled as a single small environment and not a sizing claim.
- G12 gets the live-vs-emulator deltas found (Entra-only container creation, RBAC, private networking, RU).
- G02 and Government stay OPEN: this is Commercial only and never bridges Government data.
- G16 (live judge) and G05 (model swap) are untouched. A copilot answer from the hosted environment is not a G16 judge run.
- If S4 or the capability row (decision 5) is not approved, the copilot is reported "disabled with reason" and that is recorded, not hidden.

## NOT building
- An AKS profile, Government deployment, multi-region, DR or failover for the demo.
- APIM, AI Search, Front Door, Application Gateway, WAF or a custom domain and certificate (documented as add-ons with costs).
- Any change to the shared hub beyond the approved subnet join, PE NICs and DNS records: no new subnets, peerings, route tables, NSG rules, zone links or firewall rules.
- Any change to `services/**`, `packages/**`, `frontend/src/**`, `frontend/nginx.conf`, `frontend/Dockerfile`, compose or local seeding (PRP-29/30/31). Contracts C1-C4 are requested, not implemented here.
- Hosted mock API or demo mode. Production data or a real connector ingestion: synthetic sandbox data only.
- CI-driven deployment (no OIDC federated credential, no deploy workflow). Deploys are operator-run.
- Key-based auth anywhere (Cosmos, Event Hubs, Storage and Foundry are Entra-only).
- Any FedRAMP, ATO, compliance or SLA claim about the hosted environment.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (open items are listed under "Decisions to confirm at plan approval", each with a default)

## Execution state

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 demo-data-and-network-modules | merged | worktree-agent-a347487e5a530c841 | sonnet | fb44b04: 6 modules build+lint; 98 passed; review APPROVED (audit_tail replace-only justified by AuditStore ETag replace); fix-forward 01f8ee8 EnableServerless capability (2024-11-15 has no capacityMode, Learn); merge 4b83862 | 2026-10-26 |
| 2 appservice-profile-extension | merged | worktree-agent-aab791ea460f62961 | sonnet | ecc5d04: build+params OK; 82 passed; review APPROVED; merge 6a00fa1 | 2026-10-26 |
| 3 demo-composition | merged | worktree-agent-a755e106ea8d0c544 | sonnet | 6b35a34 + orchestrator fix 4cb5a86 (worker roles: rec/eval need compose-mounted data); build+params+lint OK; with integration merged 413 passed (param-name contract test now runs) ; review APPROVED (two-pass app service acceptable); merge 346af83 | 2026-10-26 |
| 4 gated-deploy-script | merged | worktree-agent-aba7892f197f40ff6 | sonnet | 5464e02; review CHANGES REQUIRED (pre-existing RG resources registered as created); rework 7964c19 (ownership snapshot, Entra restore removes only our URI, plan hash binds shared ids, GUID/resource-id validation, typed smoke wiring); Haiku confirm found budget-snapshot hole, orchestrator fix da3b0d0 + test; 291 passed 1 skipped, refuses exit 2; merge f26ed1a | 2026-10-26 |
| 5 hosted-seeding-and-guard | merged | worktree-agent-a7737e1f8401ae772 | sonnet | 1109aaa: 88 passed, refuses exit 2; review APPROVED; test_prefix_guard::test_cli_never_touches_non_sandbox_databases fails on base too (pre-existing, emulator); merge 7a069a1 | 2026-10-26 |
| 6 post-deploy-smoke (+ D2/D3 nginx) | merged | worktree-agent-a44d0d7e479f50df3 | sonnet | 34ef253: smoke 19 passed, edge vitest 26, hosted --list 1 test, default list excludes hosted; review APPROVED; merge 45d445f; on integration 369+26 passed | 2026-10-26 |
| 7 release-candidate-and-image-pin | merged | worktree-agent-acfa8c0d4b669b038 | sonnet | files in PR #135 (66f18d9); S8: tag v0.1.0-rc.2 on 66f18d9 operator-approved, release run 40417878914 success, api/workers/frontend cosign verify + verify-attestation exit 0, digests in docs/evidence/PRP-32/release-v0.1.0-rc.2.md; draft release unpublished | 2026-10-26 |
| 8 runbook-cost-and-gates-register | merged | worktree-agent-a99547580be06eca4 | sonnet | 3520fde: runbook + evidence index (S1-S10 OPEN) + G01/G07/G12 dated notes (no status change); runbook test 7 passed; gitleaks docs clean; Mermaid source only (not rendered); covered by final PRP review APPROVED; merge 9879b18 | 2026-10-26 |
| 9 live-deploy-seed-and-smoke (operator) | in-progress | | operator | S1 preflight PASS 21/21, exit 0, docs/evidence/PRP-32/2026-10-27-preflight.{json,md} (scrubbed, no GUIDs); S2 plan PASS, RG created, what-if 59 Create + 62 Unsupported (reference()-named role assignments), all in demo RG, 5 PEs (runbook count; PRP text said 4 before Key Vault PE), sha256 25ac6ba2...bbeb7, 2026-10-27-plan.{json,md}; S3 deploy FAILED exit 1 (all 17 nested modules Succeeded, every planned resource exists; top-level hosted-demo ResourceNotFound on main.bicep `existing` cosmosAccount/eventHubsNamespace output references; post-deploy steps register/registration/pseudonym-key/site post-checks did not run; KV purge protection 90d rules out teardown+redeploy; needs plan delta; evidence error truncated at 300 chars); S3 resume (after item 10) 2026-10-27-115918-deploy: deployment Succeeded, register 21 created/7 shared/0 not ours locally, site post-checks ok; pseudonym key OPEN (KV ForbiddenByConnection, not on VPN), Cosmos register mirror OPEN (no operator Cosmos data role; S6 re-saves); S3 third run 2026-10-27-233226-deploy on VPN (run by Claude on operator instruction): deployment Succeeded, pseudonym key created, 21 created/7 shared/1 not ours (Defender for Storage auto-created Event Grid system topic; untouched; S10 teardown follow-up), exit 1 only for the Cosmos mirror -> S3 DONE; S4 DONE 2026-10-27-grant-model-access (operator-run, foundry-role, OpenAI User verified on aifndry-loom-centralus, registered as ours); S5 redirect DONE 2026-10-27-entra-redirect (entra-app, run by Claude on operator approval, nsdemo-web URI added, 2 prior kept, Graph-verified), user/app-role assignment OPEN (operator); S6 PARTIAL (blob/KV grant bug -> item 11), S7 DONE 2026-10-28-seed (second run PASS after KV reference refresh+restart; operator access revoked, verified 0); S8 done (item 7); S9 PARTIAL 2026-10-28-smoke (8/11; the 3 health failures are a smoke query bug, but the metric shows nsdemo-api /readyz 0% healthy, cause open: LAW shows no App Service logs, API PE unreachable from VPN); S9 manual DONE (operator Entra sign-in, hosted-smoke.spec 1/1 passed: shell, synthetic domains, overview, map, copilot, axe); 403-on-hidden-route OPEN (no viewer user, not in spec); S10 OPEN | 2026-10-27 |
| 10 s3-recovery-fix (plan delta) | merged | prp-32-item10-s3-recovery | sonnet | 4c18d64 template + f5fb274 resume/error-limit/runbook; bicep builds+lint clean, 471 passed, ruff/pyright clean, refuses exit 2, gitleaks clean, Snyk no new issues; review CHANGES REQUIRED (NIC bare-prefix match could claim a sibling `<pe>2.nic.` NIC) -> orchestrator rework 49bd037 (`<pe>.nic.` exact prefix, real-shape fixture, sibling test verified failing on old rule), 472 passed; PR #140 CI 24/24 green, merge d799314 | 2026-10-27 |
| 11 live-run-fixes (plan delta) | merged | prp-32-item11-live-run-fixes | sonnet | 4a1b1db fixes+tests, 86a8921 runbook; 478 passed (6 new, 5 fail on old code), ruff/format/repo-wide pyright clean, revoke refuses exit 2, gitleaks clean, Snyk no new issues; `_hosted_demo_common.py` touched for `RegisterBook.remove` (allowed by the item); review APPROVED (follow-ups: Cosmos backend row delete, re-verify api-versions before next live run); PR #141 CI 24/24 green, merge c726b42 | 2026-10-28 |
| 12 s9-readiness-fixes (plan delta) | verifying | prp-32-item12-s9-readiness-fixes | sonnet | 64d0a46 copilotMode param (default disabled) + smoke PT5M/--metrics/scrubbed az error + runbook; orchestrator ab0f957 `--copilot-mode` flag + GENERATED_PARAMS (contract test; touched hosted_demo.py, _hosted_demo_common.py, test_hosted_demo_refuses.py beyond the owned list); 481 passed, smoke tests fail on old code, ruff/repo-wide pyright clean, bicep build/build-params/lint clean, Snyk no new issues; review APPROVED; live interim NS_COPILOT_MODE=disabled on nsdemo-api 04:13Z; probes fix 24fceb6 (NS_PROBE_* from module outputs, after a direct /readyz showed localhost-default probes failing; live interim NS_PROBE_* 04:54Z -> /readyz 200 ready; probe test fails on old template; 481 passed, lint clean; orchestrator change after review, not re-reviewed); PR #142 | 2026-10-28 |

## Completion note (filled at ship)
- Date:
- Merged commits:
- Live steps run (S1-S10) and evidence paths; steps not run reported OPEN:
- Deviations from blueprint and why:
- Descoped items:
- Follow-ups:
