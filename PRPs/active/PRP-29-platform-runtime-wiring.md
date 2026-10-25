---
name: prp-29-platform-runtime-wiring
status: active
started: 2026-10-24
branch: prp-29-platform-runtime-wiring
review: required
priority: P0
created: 2026-10-24
model: opus
phase: 5
ns: NS-01, NS-02, NS-03, NS-05, NS-08
depends_on: PRP-28
wave: W9
absorbs: new
---

# PRP-29: Platform runtime wiring

## Goal
Make the real stack run end to end, locally first. One command (`docker compose --profile app up -d --wait`) should bring up five things:
- the emulators;
- the real API;
- the real workers;
- the frontend in real mode, served same-origin;
- a synthetic seed.

An operator then signs in with real Entra (`neurosphere-api-dev`, Limitlessdata tenant), and every page in `frontend/src/app/route-manifest.json` shows real data from the real API. No mock is involved.

The PRP ships nine things:
- A settings-driven production composition root in the API. It calls `configure_authz` with the real JWT validator and `ScopeDeriver`, and builds every store and service from settings. When a required component is missing, `/readyz` fails and names it; nothing degrades silently. This closes #104 fully.
- Durable Cosmos implementations for every store that is in-memory today, plus a Blob-backed replay source.
- A workers runtime that actually runs ingestion, projections, the action executor, HITL timers, lifecycle, recommendations and evaluation.
- Copilot adapters built from settings with managed identity (no keys), and the MCP server and admin plane wired per PRP-22.
- Same-origin serving: a Vite proxy and an nginx `/api` proxy, with a strict CORS allow-list as fallback.
- `/catalog`, `/audit` and `/v1/*` moved under `/api/v1`, with deprecated aliases.
- Real Entra sign-in for local runs, with a policy-store bootstrap for the operator.
- A synthetic seed that writes through the real ingestion path and services.
- A compose `app` profile that includes the frontend and the seed, plus real-stack smoke tests.

Evidence for the gap (audit 2026-10-24, verified against `main` at `ec8903d`):
- **No production wiring.** `main.create()` sets only `app.state.settings` plus two opt-in bootstraps (`services/api/neurosphere_api/main.py:16-21`, `app.py:91`). Nothing outside tests calls `configure_authz` (`authz/state.py:67-101`), so every protected route returns 503 `authz_unconfigured` (`authz/state.py:115-122`).
- **Twenty-five routers are mounted but most cannot serve.** The routers are listed at `routers.py:208-234`, but `configure_action_plane`, `configure_copilot`, `configure_realtime`, `configure_reports`, `configure_mcp_admin` and `create_mcp_server` are called only from tests.
- **No production store wiring.** Nothing in production sets the catalog, aggregate, ledger, evaluation, recommendation, review, trace or map state.
- **Idle workers.** The workers run `IdleWorker` (`services/workers/neurosphere_workers/runtime/__main__.py:15-27`). The executor, HITL timer, lifecycle and projection classes have no entrypoint.
- **In-memory only.** Six stores and the review-router stub exist only in memory, and Bicep creates no Cosmos containers (`infra/bicep/modules/cosmos.bicep:20-41`).
- **Frontend cannot reach the real API.** There is no CORS middleware (`app.py:99-100`), no Vite proxy (`frontend/vite.config.ts:111-118`), no nginx `/api` location (`frontend/nginx.conf:24-55`), and compose has no frontend or seed service (`docker-compose.yml:96-153`).

## Acceptance criteria
- [ ] Item 1: `neurosphere_api.main:create()` builds a fully composed app from settings through `neurosphere_api.runtime.compose_app`.
  - `configure_authz` gets a `JwtValidator` (`create_jwt_validator`, real Entra JWKS) and a `ScopeDeriver` backed by `CosmosPolicyRepository`, a `CosmosRevocationStore` checker and a `PrincipalPseudonymizer`.
  - No dev issuer, stand-in JWKS or bypass is reachable from `main` in any `NS_ENV`. A test greps the composition modules for `DevIssuer`/`dev_issuer` and finds none.
- [ ] Item 1: `/readyz` includes a `composition` probe. It returns 503 and names every required component that failed to build (names and reason codes only, never config values). Optional components (`copilot`, `mcp_server`, `ingest`, `scan`) report `disabled` without failing.
  - Tests cover: missing tenant gives 503 naming `authz`; missing Cosmos gives 503 naming the store components; a fully configured app gives 200.
- [ ] Item 1: `NS_CORS_ALLOWED_ORIGINS` (comma list, default empty) installs `CORSMiddleware` only when set.
  - Exact origins only; `*` or a wildcard is refused at startup.
  - `allow_credentials=False` (bearer tokens, not cookies); methods and headers are allow-listed.
  - A preflight from an unlisted origin gets no `Access-Control-Allow-Origin` (test).
- [ ] Item 1: `neurosphere_core.stores.containers` declares every Cosmos container (name, partition key paths, kind, TTL) in one registry matching the wire contract.
  - When `NS_ENV=local` only, startup runs `ensure_local_containers` against the emulator; outside local it never creates containers.
  - `infra/compose/cosmos-containers.json` is generated from the registry. A drift test pins it, and PRP-32 consumes it for Bicep.
- [ ] Items 2-3: Cosmos implementations pass the existing protocol test suites, parametrized over in-memory and Cosmos:
  - `RecommendationStore`, `EvaluationStore`, `PriceSnapshotStore`, `HitlStore`, `DecisionStore`, catalog `ReviewQueue`, and the lifecycle hold registry, request queue and mapping store.
  - The Cosmos legs run under the `integration` marker against the emulator; the protocol-conformance legs run in CI against an in-process fake container.
  - `ReviewRouter` gets a HITL-backed implementation (routing creates or returns one HITL review item, idempotently), replacing `InMemoryReviewRouter` in production.
- [ ] Item 4: `/catalog/**`, `/catalog/curation/**`, `/audit/**`, `/v1/ingest/**`, `/v1/deploy/scan` and `/v1/deploy/plan` are served under `/api/v1/...`. The old paths stay as deprecated aliases for one release:
  - the same handlers and permissions;
  - `deprecated: true` in OpenAPI;
  - `Deprecation` and `Sunset` response headers, and a `Link` to the successor.
- [ ] Item 4: the route inventory stays green with both forms, and `PRODUCER_AUTHENTICATED_PATHS` lists both ingest forms.
  - `openapi.json` is regenerated and `test_openapi_drift` is green. The report states the component diff (rename precedent).
  - The curation decision route stamps `actor` from the authenticated principal and rejects a mismatched client value with 403. This is the PRP-31 Clarification 4 follow-up.
- [ ] Item 5: same-origin serving.
  - In Vite dev, `/api` (including the `ws` upgrade for `/api/v1/realtime/ws`), `/readyz` and `/healthz` proxy to `NS_DEV_API_TARGET` (default `http://127.0.0.1:8000`).
  - In the frontend image, nginx proxies `/api/` with WebSocket upgrade headers to `NS_UI_API_UPSTREAM`.
  - The image renders `/config.json` at start from `NS_UI_*` env, with `apiBaseUrl: "/"` and no IDs baked into the image. The deploy-time mount-over still works.
  - `frontend/public/config.json` defaults to `apiBaseUrl: "/"`.
  - Existing Vitest and the mock Playwright suite stay green. The PRP-28 no-demo-in-prod tests stay green.
- [ ] Item 6: `scripts/gates/p29_entra_local.py` adds the local SPA redirect URIs and the five app roles to `neurosphere-api-dev`.
  - Dry-run is the default. Applying requires `NS_LIVE_APPROVED=1` and `--apply`.
  - It merges and never removes existing URIs or roles. It is idempotent.
  - It never reads, prints or writes a secret.
  - `--assign-self` optionally assigns a role to the signed-in operator.
- [ ] Item 6: `scripts/sandbox/sbx_grant_operator.py --object-id <oid> --role <role>` writes `PolicyHead`/`PrincipalPolicy` for the operator through `CosmosPolicyRepository`.
  - It is loopback-guarded by `sbx_guard`.
  - It uses the same pseudonym key resolution as the API, and its domains are the sandbox domains.
  - The signed-in operator's `/api/v1/me/domains` then lists the sandbox domains (integration test with a stand-in token through the same deriver).
- [ ] Item 7: data-plane builders populate:
  - `catalog_repository`, `catalog_graph`, `catalog_review_queue`;
  - `aggregate_reader`, `ledger_store`, `federation`;
  - `evaluation_store` (+ pilot dataset ids), `recommendation_store`, `review_router`;
  - `trace_reader`, an `ArchiveTraceReader` over an aio `ContainerClient` on the archive container (Azurite locally, managed identity outside local);
  - `map_pseudonymizer` (+ viewport limits), `audit_repository`, `realtime` and `sandbox_repository`.

  Each missing piece fails readiness by name. Item 1's route-coverage test reports 0 `*_unconfigured` 503s for these routes.
- [ ] Item 8: plane builders.
  - **Action plane:** `configure_action_plane` gets Cosmos intents and execution control, HITL service, audit, review policies, supported write targets and a permission rechecker.
  - **Reports:** `configure_reports` gets Cosmos reports and the bounded tool registry.
  - **MCP:** `configure_mcp_admin` gets Cosmos MCP servers. `create_mcp_server` is mounted only when `NS_MCP_RESOURCE_SERVER_URL` is set, after `configure_authz`, per `mcp/server/__init__.py:6-29`.
- [ ] Item 8: copilot.
  - `NS_COPILOT_MODE=disabled|approved_endpoint|foundry_agent`, default `disabled`, which leaves copilot routes on 503 `copilot_unconfigured` and readiness on `copilot: disabled`.
  - `approved_endpoint`/`foundry_agent` build `ApprovedEndpointAdapter`/`FoundryAgentAdapter` from `NS_COPILOT_ENDPOINT`/`NS_COPILOT_DEPLOYMENT` with `DefaultAzureCredential` through the existing `resolve_adapters` gating, plus a `CosmosConversationStore`.
  - Any key-shaped copilot env var refuses startup (test). No live call in CI.
- [ ] Item 9: `python -m neurosphere_workers.runtime` runs the roles listed in `NS_WORKER_ROLES` (the wire contract roles, or `all`) in one process: ingestion, projections, aggregates, actions, hitl_timers, lifecycle, recommendations and evaluation.
  - The health server reports per-role liveness and readiness.
  - Unset roles keep today's idle behaviour, reported as `roles: []`.
  - `python -m neurosphere_workers.ingestion` still works as an alias for `NS_WORKER_ROLES=ingestion`.
  - A crashed role marks readiness failed and is restarted with the existing `WorkerRunner` backoff; one role crashing never kills the others (test).
- [ ] Item 10: `python scripts/sandbox/sbx_seed_stack.py` (and `make seed-stack`) seeds the local stack idempotently through the real paths:
  - telemetry and cost via Event Hubs to the ingestion worker (ledger, aggregates, outbox to catalog, archive blobs for replay);
  - a synthetic price sheet;
  - recommendations through the pipeline into the Cosmos store;
  - offline evaluation runs with `RecordedFixtureJudge`;
  - HITL review items through the review router;
  - action intents through `ActionService`, only in drafted, validated or awaiting states and never executed;
  - reports through the report store;
  - synthetic MCP server registrations through the admin plane store;
  - policy grants for the synthetic personas.

  It prints a JSON count summary per page category and keeps the `sbx_guard` loopback rule.
- [ ] Item 11: compose `--profile app` adds a `frontend` service (real mode, same-origin, port 8080).
  - **Delta (user, 2026-10-25):** there is no compose `seed` job. `sbx_guard` accepts loopback hosts only, and a container reaches the emulators by service name. `make stack-up` runs `docker compose --profile app up -d --wait` and then `sbx_seed_stack.py` from the host against `127.0.0.1`.
  - `api` and `workers` get the emulator, auth and roles env.
  - `docker compose --profile app up -d --wait` completes with every service healthy, and the host seed step then exits 0.
  - `tests/integration/compose/test_app_profile.py` and a new `tests/integration/real_stack/` suite (integration marker) assert that every manifest route's API calls return 200 with non-empty data, using an operator-minted stand-in token routed through the composed deriver in-process, not through the container.
- [ ] Item 11: a CI-safe route-coverage test builds the composed app with `CompositionOverrides` and asserts that no route backing a `route-manifest.json` page returns a `*_unconfigured` 503.
  - The overrides are in-memory backends plus test-only dev-issuer authz, supplied from test code only.
- [ ] Item 11: `frontend/playwright.real-stack.config.ts` plus `frontend/tests/real-stack/**` visit every manifest route against the compose stack after a headed real-Entra sign-in. Each page must render data, show no demo banner and produce no 4xx/5xx except expected 403s. This is a manual gate, not part of the PR job.
- [ ] PRP exit:
  - All items are green under `verify-gates -Mode full`.
  - The integration suites (`compose`, `real_stack`, `stores_cosmos`) are green locally, run in sequence.
  - The manual real-Entra Playwright run is recorded with evidence, or reported OPEN.
  - The reviewer confirms: authorization at every path; no unrestricted bypass; buttons, chat and MCP share one executor; no keys or secrets in files; no dev issuer reachable from `main`.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Hosted mock vs real API | hosted mock; real API + real Entra | Real Entra and the real API everywhere; the mock stays a dev/test tool only (user) |
| 2 | Persistent Azure environment | this PRP; separate PRP | A persistent, right-sized env is PRP-32. PRP-29 is local-first and only makes hosting configurable (user) |
| 3 | Copilot endpoint | new resource; reuse existing | Reuse Foundry `aifndry-loom-centralus` (Limitlessdata - DMLZ, `rg-csa-loom-admin-centralus`, centralus; chat `gpt-5.4-mini`, `strong`=gpt-4.1, `mini`=gpt-4.1-mini, `gpt-6.1-sol`; embeddings `embed`). PRP-29 makes it configurable only. Granting a role on this shared resource is an explicit operator step in PRP-32 (user) |
| 4 | UI styles | here; PRP-30 | Two switchable styles are PRP-30; PRP-29 touches only the frontend edge files listed in item 5 (user) |
| 5 | Composition shape | wire inside `create_app`; separate composition root | New `neurosphere_api.runtime.compose_app(app, settings, overrides=None)` called from `main.create()`. `create_app` stays as it is, so `openapi_export` (`openapi_export.py:24-25`) and the route tests keep using a bare app. Each concern has its own builder module in a fixed ordered list (the `routers.py` hook pattern), so items never share a file |
| 6 | Missing dependency behaviour | degrade silently; fail readiness | Required components fail `/readyz` by name; routes keep their existing fail-closed 503s. Optional components (copilot, MCP server, ingest, scan) report `disabled` |
| 7 | Same-origin vs CORS | CORS only; reverse proxy; both | Reverse proxy is primary: Vite `server.proxy` locally, nginx `/api/` in the image, `apiBaseUrl: "/"`. CORS allow-list is the fallback, default off, never `*`, `allow_credentials=False`. Verified: `"/"` yields relative URLs in `client.ts:60-62`, `realtime.ts:41-45` and copilot `stream.ts:273`, so no `frontend/src/api|auth` edit is needed |
| 8 | Frontend health URL | add `/api/v1/health`; use `/readyz` | No new backend endpoint. App code never calls `/api/v1/health`; only the mock (`tests/mock-api/server.ts:2079`), `playwright.config.ts:24` and `scripts/demo.mjs:18` do. Real-stack checks wait on `/readyz` through the proxy |
| 9 | Path normalisation | move hard; move + aliases; leave | Move under `/api/v1` and keep the old paths for one release as deprecated aliases (OpenAPI `deprecated`, `Deprecation`/`Sunset`/`Link` headers). The frontend calls none of the old paths today; external producers (`connectors/reference/otel-generic/collector/otel-collector.example.yaml:63-64`) need the overlap. Alias removal becomes a follow-up issue |
| 10 | Workers process model | one process per role; one process with selectable roles | One process with `NS_WORKER_ROLES`. There is one image and CMD today (`services/workers/Dockerfile:38`). The App Service small profile runs the same image (PRP.md §2), and Helm or PRP-32 can scale by running several Deployments with different role lists. Ingestion's `__main__` stays as an alias |
| 11 | Durable `ReviewRouter` | own Cosmos store; HITL-backed adapter | HITL-backed adapter. `recommendations/review.py:1-5` states that PRP-17 replaces the stub with the HITL queue behind the same protocol |
| 12 | Local SPA client | new SPA app registration; SPA platform on `neurosphere-api-dev` | SPA platform redirect URIs (`http://localhost:5173`, `http://localhost:8080`) on the existing `neurosphere-api-dev` (appId and tenant supplied by the operator as arguments, not committed). One app acts as both SPA client and API. Scope `api://<appId>/access_as_user`; v2 tokens, so `aud` is the bare GUID. Applied only by the gated item 6 script. PRP-32 adds hosted URIs with the same script (`--redirect-uri`) |
| 13 | Where authority comes from | Entra app roles; policy store | Policy store. `ScopeDeriver` never treats `roles`/`groups` as authority (`derivation.py:6-7`, `policy.py:9-10`). App roles drive frontend nav display only (`useRoles.ts:14-19`; values equal backend names, normalised by `roles.ts:25-27`). The operator gets authority from `sbx_grant_operator.py` locally (PRP-32 hosted) |
| 14 | Pseudonym key | new Key Vault SDK; platform-resolved secret | No new dependency. `NS_AUTH_PSEUDONYM_KEY` (SecretStr) arrives through the platform's Key Vault reference (App Service/Helm CSI) together with `NS_AUTH_PSEUDONYM_KEY_REFERENCE` (the vault URI that `PseudonymKey` requires, `pseudonym.py:24-26`). `NS_ENV=local` falls back to a fixed, public, non-secret dev key, as in `archive/settings.py:11-13`, under a documented placeholder reference. Any other env without a key fails readiness |
| 15 | Customer id | from token; from config | From config, `NS_AUTH_CUSTOMER_ID` (local default `synthco` = `sandbox/config.py:10`), per `ScopeDerivationConfig` (`derivation.py:80-96`) |
| 16 | Container provisioning | per-store `create_if_not_exists`; registry | One declarative registry in `neurosphere_core.stores`. Emulator bootstrap only when `NS_ENV=local` (precedent `ingestion/wiring.py:109-117`). A JSON export goes to PRP-32's Bicep. Non-local never creates containers (Entra principals cannot create Cosmos databases in the DMLZ) |
| 17 | Real-stack smoke | Playwright in CI with a dev issuer; CI-safe in-process + manual Playwright | CI runs an in-process route-coverage test (test-only dev issuer plus in-memory overrides through `CompositionOverrides`). Local runs add integration suites against compose. The browser run uses real Entra, headed, as a manual gate. No dev issuer goes in compose or `main` |
| 18 | Seeding route | raw document writes; real paths | Real paths: telemetry through Event Hubs to the workers, everything else through core services and stores. Action intents never execute. Hosted seeding is PRP-32 |
| 19 | Compose Entra IDs | env only; tracked defaults | Env only (orchestrator, 2026-10-24, aligned with PRP-32's no-GUIDs-in-committed-files rule for this public repo). Compose reads `NS_ENTRA_TENANT_ID`/`NS_ENTRA_CLIENT_ID` with no tracked default and fails fast with a clear message when unset; `docs/dev/local-setup.md` says where the operator gets them. Not credentials, but kept out of tracked config |
| 20 | Curation `actor` and deploy `consented_by` (PRP-31 C4, C8) | fix both; fix actor; defer both | Item 4 stamps the curation actor server-side (authorization defect). Stamping `consented_by` is a follow-up issue |
| 21 | Item models | all opus; split | Opus for items 1 (authz and composition), 4 (route inventory and aliases) and 8 (action plane and MCP). Sonnet for the rest; Haiku for verify passes |

**Decisions to confirm at plan approval:** 5, 6, 9, 10, 12, 14, 16, 17, 19 and 20. Each is decided above with a recommended default. Plan approval confirms or changes them before wave A starts.

## Context manifest

### Files that matter
- API entry and app:
  - `services/api/neurosphere_api/main.py:16-21` (`create()`; opt-in ingest `:19`, scan `:20`).
  - `services/api/neurosphere_api/app.py`:
    - `:84-108`: `create_app`.
    - `:91`: only `app.state.settings`.
    - `:93-96`: exception handlers.
    - `:99-100`: size-limit and correlation middleware; no CORS.
    - `:67-81`: lifespan runs the MCP session manager only if `app.state.mcp_server` is an `McpServerMount`.
- `services/api/neurosphere_api/routers.py`: duplicate prefixes raise (`:34-40`); lazy hooks (`:55-205`); `REGISTERED` (`:208-234`, 25 hooks).
- Health:
  - `services/api/neurosphere_api/health/router.py`: probes overridable via `app.state.health_probes` (`:33-42`); `/healthz` (`:48-50`); `/readyz` (`:52-62`); prefix `""` (`:67-68`).
  - `health/probes.py`: `DependencyProbe` (`:33-41`); `probes_from_env` (`:107-117`); an empty set is not ready (`:134-135`).
- Settings precedent:
  - `packages/core/neurosphere_core/cloud/settings.py:13-35` (`NS_` prefix, `frozen`, `extra="forbid"`; `env`, `cloud`).
  - Per-concern classes: `ingest/settings.py:25-38` (`NS_INGEST_`); `deploy/scan/settings.py:9-20` (`NS_SCAN_`); `mcp/server/settings.py:46,57-79` (`NS_MCP_`); `realtime/settings.py:18-21` (`NS_REALTIME_`).
- Bootstrap precedent: `ingest/bootstrap.py:41-60`; `deploy/scan/bootstrap.py:37-73` (`DefaultAzureCredential` with the env credential excluded outside local).
- Authz wiring:
  - `services/api/neurosphere_api/authz/state.py`: `configure_authz(app, *, authenticator, scope_source, clock, timeout_seconds, denial_recorder, extra_public_paths)` (`:67-101`); cloud/tenant binding check (`:104-112`); `authz_unconfigured` (`:115-122`).
  - `authz/routes.py`: `PUBLIC_PATHS` (`:47`); `SELF_AUTHENTICATED_PATHS` (`:54`); `PRODUCER_AUTHENTICATED_PATHS` (`:61-63`).
- JWT:
  - `packages/core/neurosphere_core/auth/jwt/validator.py`: `JwtValidator` (`:73-76`); dev keys only if local (`:87-93`); `create_jwt_validator` (`:276-291`).
  - `auth/jwt/config.py`: `JwtConfig` (`:91-160`); `from_settings` (`:134-152`); a dev issuer is rejected outside local (`:116-123`); issuers (`:44-50`); JWKS URI (`:53-55`).
  - `auth/jwt/dev_issuer.py:34-38`.
- Scope:
  - `auth/scope/derivation.py`: `ScopeDeriver` (`:122-155`; `revocation_checker` mandatory `:134-137`); `ScopeDerivationConfig` (`:80-96`); principal pseudonym (`:175-182`); policy lookup (`:186-204`); clipping to memberships (`:275-302`).
  - `auth/scope/policy.py`: doc kinds (`:1-10`); `PolicyHead` (`:60-64`); `PrincipalPolicy` (`:91-97`); `PolicyRepository` (`:108`).
  - `auth/scope/cosmos_repository.py:30,38-48` (container `policy`). `auth/scope/memory.py:14` ("never a production store").
- Pseudonyms and revocation:
  - `auth/scope/pseudonym.py`: `MIN_KEY_BYTES` 32 (`:21`); vault URI regex (`:24-26`); `PseudonymKey` (`:37-55`); `PrincipalPseudonymizer` (`:72-84`).
  - `auth/revocation/cosmos_store.py:47-60`.
  - Local-key precedent: `services/workers/neurosphere_workers/archive/settings.py:11-13,30-41`.
- Cosmos client: `packages/core/neurosphere_core/clients/factories.py`:
  - `:28-29`: env names.
  - `:51-58`: keys refused outside local.
  - `:66`: `DefaultAzureCredential(authority=...)`.
  - `:76-92`: `create_cosmos_client`, async; local uses `NS_COSMOS_ENDPOINT`/`NS_COSMOS_KEY`.
  - Tests set a dummy key, e.g. `services/api/tests/reports/test_report_store_cosmos.py:39`; the vnext emulator ignores it.
- 503 sources the composition must satisfy (state key, then reason code):
  - `audit/router.py:57-60`: `audit_repository`.
  - `catalog/dependencies.py:53-56`: `catalog_graph`.
  - `catalog/curation/dependencies.py:52-74`: `catalog_repository`, `catalog_review_queue`, `catalog_clock`.
  - `map/dependencies.py:68-104`: graph, repository, `aggregate_reader`, `map_pseudonymizer`, `map_viewport_limits`.
  - `dashboards/dependencies.py:25-42`: `aggregate_reader`, plus an optional analytics probe.
  - `reconciliation/dependencies.py:22-27`.
  - `federation/router.py:42-54`: `federation`, `aggregate_reader`.
  - `finops/dependencies.py:23-26`: `ledger_store`.
  - `evaluation/dependencies.py:19-28`: store and pilot ids.
  - `recommendations/dependencies.py:21-33`: store and `review_router`.
  - `replay/dependencies.py:29-38`: `trace_reader`, `replay_payload_policy`.
  - `actions/dependencies.py:56,113-125`.
  - `copilot/dependencies.py:61,101-128`.
  - `reports/dependencies.py:27-39`.
  - `realtime/gateway.py:136`.
  - `mcp/admin/router.py:65-69`.
  - `mcp/server/router.py:30-34` and `tools.py:182-192`.
  - `me/router.py:73`: catalog repository.
  - `sandbox/router.py:51-67`: lazy and local-only today.
- Configure functions:
  - `actions/dependencies.py:141-168` (`configure_action_plane`).
  - `copilot/dependencies.py:142-161`.
  - `realtime/dependencies.py:46-90` (exactly one of `aggregate_reader`/`source`).
  - `reports/dependencies.py:45-57`.
  - `mcp/admin/router.py:60-62`.
  - `mcp/server/factory.py:441-519` (`create_mcp_server`; exact-path `Route("/mcp")` `:164-166`; MCP and REST audiences must not overlap `:456-462`; streamable HTTP, stateless, Host/Origin guard `:490-501`).
  - `mcp/server/settings.py:127-151` (None unless `NS_MCP_RESOURCE_SERVER_URL`; https and `/mcp` required).
  - Mount contract: `mcp/server/__init__.py:6-29`.
  - `federation/service.py:59,194` (`Federator`, `FederationState`).
- Copilot adapters (`packages/core/neurosphere_core/copilot/models/`):
  - `approved_endpoint.py:97-126` (`(config, *, cloud, credential: AsyncTokenCredential)`; `/openai/deployments/{d}/chat/completions`).
  - `foundry_agent.py:104-111`.
  - `endpoints.py:30-49` (`AdapterConfig`; no key field; token scopes).
  - `gating.py:130-185` (`resolve_adapters`, `create_adapter`).
  - `services/api/neurosphere_api/copilot/settings.py:38-58` (limits only).
  - `copilot/cosmos_store.py:45-77`.
- In-memory stores to replace (each protocol is in the same file):
  - `packages/core/neurosphere_core/recommendations/store.py:30,83`.
  - `evaluation/store.py:85,162`.
  - `evaluation/judge.py:80,92`.
  - `pricing/store.py:38,59`.
  - `hitl/store.py:37,114`.
  - `hitl/decisions.py:72,86`.
  - `catalog/review_queue.py:61,101`.
  - `lifecycle/memory.py:72,85,99` (mapping, holds, requests).
  - `services/api/neurosphere_api/recommendations/review.py:1-5,24-56`.
- Existing Cosmos stores to match:
  - `actions/cosmos_store.py:84-105,138,362`: in-module container constants with MultiHash `/customer_id,/domain_id`. The template.
  - `reports/cosmos_store.py:49-55,94`.
  - `mcp/cosmos_store.py:47-52,83`.
  - `aggregates/cosmos.py:41,50`.
  - `ledger/cosmos.py:32`.
  - `catalog/repo/cosmos.py:58,119,157`.
  - `catalog/partitioning.py:49-51`.
  - `audit/cosmos_store.py:47,59`.
- Replay:
  - `services/api/neurosphere_api/replay/reader.py`: `TraceReader` (`:80`); `BlobSource` (`:167`), which is exactly the aio `ContainerClient` slice; `ArchiveTraceReader` (`:230`).
  - Archive writer: `services/workers/neurosphere_workers/archive/factory.py:13-48` (`from_connection_string` locally, account URL + credential otherwise); `archive/settings.py:16-27` (`NS_ARCHIVE_`, container `ns-archive`).
  - Azurite string precedent: `infra/dr/ns_dr_emulator.py:35-37` (`UseDevelopmentStorage=true`, assembled by the SDK).
- Workers:
  - `runtime/__main__.py:15-27`; `runtime/worker.py:46,60-70,133`.
  - Ingestion: `ingestion/__main__.py:27-45`; `ingestion/consumer.py:75-142`; `ingestion/wiring.py:73-79,109-117,168-177`; `ingestion/settings.py:24-35`.
  - `actions/worker.py:37-47`; `hitl_timers/worker.py:60-68`; `lifecycle/worker.py:55-69`.
  - `aggregates/handler.py:80-91`; `projections/catalog/handler.py:106-118`; `projections/outbox/reader.py:36-38`.
  - `recommendations/pipeline.py:99,234`; `evaluation/service.py:90-112`.
  - `Dockerfile.dev:38` and `Dockerfile:38` (CMD `neurosphere_workers.runtime`).
- Compose: `docker-compose.yml`:
  - `:19`: `name: neurosphere`.
  - `:22-34`: cosmos.
  - `:36-49`: azurite.
  - `:51-80`: eventhubs and health.
  - `:98-128`: `api` (`NS_PROBE_*` only; no Cosmos, Blob or Event Hubs connection env).
  - `:130-153`: `workers` (on `isolated` only).
  - `:155-158`: networks.
  - Tests: `infra/compose/eventhubs.config.json`; `tests/integration/compose/test_app_profile.py:42-62`.
- Sandbox:
  - `sandbox/generate.py:35-43,218` (catalog, telemetry and cost only; no recommendations, review, intents, reports or MCP).
  - `sandbox/config.py:10`.
  - `scripts/sandbox/sbx_guard.py:32-52,73-78`; `sbx_cli.py:81-122`; `sbx_seam.py:44-52`; `sandbox.mk:15-21`.
  - `tests/integration/sandbox/`.
- Frontend edge:
  - `frontend/public/config.json:1-7` (zero GUIDs, `apiBaseUrl` `http://localhost:8000`).
  - `frontend/src/app/config.ts`: `:9-19`; `:42-83` (string fields non-empty); `:108-124`.
  - `frontend/vite.config.ts:111-118` (no proxy).
  - `frontend/nginx.conf`: `:24` (8080); `:28-29`; `:32-36` (`/config.json` no-store); `:39-55`.
  - `frontend/Dockerfile`: `:3-4` (config mount); `:7-17`; `:20-33` (nginx-unprivileged, uid 10001).
  - `frontend/src/auth/msal.ts:9-33` (redirect defaults to origin `:11-12`); `AuthProvider.tsx:40-44`.
  - `frontend/playwright.config.ts:3-4,20-34`.
  - `frontend/src/app/route-manifest.json:3-28` (26 routes).
- Path normalisation targets:
  - `catalog/router.py:93`, `catalog/curation/router.py:46`, `audit/router.py:37`, `ingest/router.py:27`, `deploy/scan/router.py:21`, `deploy/plan/router.py:21`.
  - Consumers: `connectors/reference/otel-generic/collector/otel-collector.example.yaml:62-64` and its `README.md`.
  - Curation actor: `packages/contracts/python/neurosphere_contracts/catalog/v1/edge_override.py:49-60`.
- OpenAPI: `services/api/neurosphere_api/openapi_export.py:17,24-25`; `services/api/tests/test_openapi_drift.py:6-25`.
- Test harnesses:
  - `services/api/tests/authz/authz_helpers.py:77-100,228-296` (in-memory `DevIssuer`, stand-in JWKS, `harness()`).
  - `tests/security/authz/world.py:656-747`.
  - `tests/integration/ingestion/support.py:97-103,163-174` (in-process app on emulators).
- Entra prior art: `scripts/gates/prp06_entra_live.py:6-10,40-52,126-151`; `docs/evidence/PRP-06/live-commercial-2026-10-13.md:3,9`.
- Sibling and predecessor references:
  - `PRPs/shipped/PRP-21-scale-federation-finops-and-dr.md:270-271` and `PRPs/shipped/PRP-22-mcp-server-and-client.md:223,238` (#104).
  - `PRPs/backlog/PRP-31-missing-ui-surfaces.md:101,105,231` (path, actor and consent expectations).

### Patterns to match
- Router module shape (`PREFIX`, `build_router`, `register(registry)`): `services/api/neurosphere_api/reconciliation/router.py:28-72`.
- Settings-driven bootstrap with opt-in and `DefaultAzureCredential`: `deploy/scan/bootstrap.py:37-73`.
- A Cosmos store with in-module container constants and `create_*_container` for the emulator: `packages/core/neurosphere_core/actions/cosmos_store.py:84-105`.
- A protocol suite parametrized over in-memory and Cosmos: `tests/integration/actions/test_intent_store_cosmos.py`, with the dummy emulator key at `:73`.
- Fail-closed `DependencyTransientError(reason=...)`: `dashboards/dependencies.py:25-31`.
- Live gate script shape (`NS_LIVE_APPROVED`, dry-run first, `az` subprocess, no secrets): `scripts/gates/prp06_entra_live.py`.
- Sandbox loopback guard: `scripts/sandbox/sbx_guard.py:44-52`.
- The PRP-28 placeholder pattern: item 1 creates every builder module as a placeholder returning `not_built`, so later items edit only their own module.

### Conventions
- Python 3.12, `uv`, FastAPI, Pydantic v2 (`ConfigDict(extra="forbid")`), pydantic-settings, one settings class per concern with its own `NS_<CONCERN>_` prefix. Do not add fields to the shared core `Settings`.
- Ruff (line 100, py312, S rules), pyright standard, conventional commits, owned-file discipline. Use `python`, never `python3`.
- No new dependencies are expected (`azure-identity`, `azure-storage-blob`, `azure-cosmos` and `httpx` are already present). Any new one needs licence review: `python scripts/licenses_report.py --check`.
- New test packages must have unique names: `services/api/tests/{runtime_api,runtime_data,runtime_planes,runtime_routes,path_aliases}`, `packages/core/tests/{stores_registry,recommendations_cosmos,evaluation_cosmos,pricing_cosmos,hitl_cosmos,review_queue_cosmos,lifecycle_cosmos}`, `services/workers/tests/worker_roles`, `tests/unit/{sandbox_stack,gates}` (the latter exists), and `tests/integration/{real_stack,stores_cosmos,stores_hitl,workers_runtime}`. All were checked free on 2026-10-24. Each integration package has exactly one owner of its `__init__.py`/`conftest.py`: item 1 for `real_stack`, item 2 for `stores_cosmos`, item 3 for `stores_hitl`, and item 9 for `workers_runtime`.
- Core must not import services (`packages/core/tests/test_import_boundaries.py`). The HITL-backed `ReviewRouter` lives in `services/api`.

### Gotchas
- **Test package shadowing.** Same-named test directories with `__init__.py` shadow each other in one pytest session. Use the unique names above and run touched suites together.
- **Hash-seed flakes.** `next(iter(set))` in tests flakes under hash seed. Sort before picking.
- **CodeQL rules that fail PRs.** `js/bad-tag-filter`, `py/side-effect-in-assert`, `py/uninitialized-local-variable` (match captures), `py/overwritten-inherited-attribute`, and PEP 695 generics in nested defs. Put these in every brief.
- **gitleaks.** Split every credential-shaped literal in tests, including emulator keys and connection strings; build them at runtime like `infra/dr/ns_dr_emulator.py:35-37`. Agents cannot run gitleaks against git; the orchestrator does.
- **`integration` never runs in CI** (`pyproject.toml:88-91` addopts `-m "not integration and not live"`). Every Cosmos and compose test needs a CI-runnable sibling: protocol conformance over a fake container, or the in-process route-coverage test. Otherwise the coverage is invisible in CI.
- **Compose is shared across worktrees.** `docker-compose.yml:19` fixes `name: neurosphere`, so only one lane may run compose at a time. Items 1-10 must not need compose for their CI tests; their integration legs run sequentially at merge (orchestrator). Item 11 owns compose.
- **Playwright ports cross worktrees.** `reuseExistingServer` picks up another worktree's server. Use a unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` per lane, and give the real-stack config its own port variables.
- **OpenAPI component renames.** Contract models used as `response_model` rename `openapi.json` components. Report the diff. Item 4 is the only item that regenerates `openapi.json`. `compose_app` must not add routes visible to `create_app`, so other items do not change the schema (the MCP `Route("/mcp")` is appended only at runtime and is not in the exported schema).
- **`az deployment` is denied** by `.claude/settings.json:54` (`azd up/deploy` at `:55-56`). Item 6 uses `az rest`/`az ad app` Graph calls through its gated script only, and never deploys.
- **WinError 10055** in the local full suite is TIME_WAIT churn from the Windows socketpair emulation, not a leak. Re-run the failing suite alone.
- **Worktrees branch from `main`.** Briefs must merge the integration branch first. The `prp_index` check is noisy; CI is path-filtered.
- **MSYS paths.** Prefix `MSYS_NO_PATHCONV=1` for `uv run` commands with absolute paths and for `az` calls with `/` arguments.
- **Policy vs app roles.** App roles in the ID token only drive nav. If the operator has app roles but no `PrincipalPolicy`, the nav shows pages the API answers with 403. That is correct (hiding is not authorization), but the docs must say to run `sbx_grant_operator.py`.
- **Pseudonym parity.** The principal id is `HMAC(tenant:oid)`. The grant script and the API must resolve the identical key, or the operator is unknown to the policy store. Both use item 1's resolver.
- **JWKS egress.** The API container needs outbound HTTPS to `login.microsoftonline.com` for JWKS. It is on `default` and `isolated` (`docker-compose.yml:121`). Workers stay on `isolated` only and need no egress locally.
- **Emulator database creation.** Cosmos containers are created only when `NS_ENV=local`. Outside local, missing containers are a readiness failure. The DMLZ forces Cosmos private, and Entra cannot create databases (memory).
- **`--wait` with one-shot jobs.** Verify how `docker compose up --wait` treats an exited `seed` container on the pinned Compose version. If it fails the wait, have `frontend` depend on `seed: service_completed_successfully` and document it.
- **The frontend parses config strictly.** `parseConfig` requires the four string fields to be non-empty (`config.ts:42-83`), so `apiBaseUrl` must be `"/"`, not `""`.
- **WebSocket proxying.** The Vite proxy needs `ws: true` and nginx needs `Upgrade`/`Connection` headers for `/api/v1/realtime/ws`. Otherwise the map's live updates fail silently.
- **No `|| true`.** CI and scripts may not suppress failures; the planning validator rejects it.

### External references
- FastAPI/Starlette `CORSMiddleware`: https://fastapi.tiangolo.com/tutorial/cors/ (no `*` with credentials).
- Vite `server.proxy` (including `ws`): https://vite.dev/config/server-options.html#server-proxy.
- nginx WebSocket proxying: https://nginx.org/en/docs/http/websocket.html. nginx-unprivileged `/etc/nginx/templates` envsubst: https://github.com/nginx/docker-nginx-unprivileged.
- MSAL SPA redirect URIs (`spa` platform, auth code + PKCE): https://learn.microsoft.com/entra/identity-platform/reply-url. Access token v2 `aud`: https://learn.microsoft.com/entra/identity-platform/access-tokens. App roles: https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps. The orchestrator verifies these with the Learn MCP and pastes the facts into briefs, because subagents lack it.
- HTTP `Deprecation` header (RFC 9745) and `Sunset` (RFC 8594).
- Azure Cosmos DB hierarchical partition keys: https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys.
- App Service Key Vault references: https://learn.microsoft.com/azure/app-service/app-service-key-vault-references (PRP-32 consumes this).

### Wire contract (all items code against it)

**API settings**
- Item 1, `NS_AUTH_`:
  - `NS_AUTH_TENANT_ID` (GUID)
  - `NS_AUTH_AUDIENCES` (comma list; v2 bare app GUID)
  - `NS_AUTH_CUSTOMER_ID` (local default `synthco`)
  - `NS_AUTH_PSEUDONYM_KEY` (SecretStr)
  - `NS_AUTH_PSEUDONYM_KEY_REFERENCE` (Key Vault secret URI)
  - `NS_AUTH_POLICY_CONTAINER` (default `policy`)
- Item 1, `NS_STORE_`: `NS_STORE_DATABASE` (default `neurosphere`). Cosmos endpoint and key keep `NS_COSMOS_ENDPOINT`/`NS_COSMOS_KEY` (local only).
- Item 1, `NS_CORS_`: `NS_CORS_ALLOWED_ORIGINS`.
- Item 7: the archive container reuses `NS_ARCHIVE_CONTAINER`/`NS_ARCHIVE_STORAGE_ACCOUNT`; local uses `NS_BLOB_CONNECTION_STRING`.
- Item 8, `NS_COPILOT_`: `NS_COPILOT_MODE`, `NS_COPILOT_ENDPOINT`, `NS_COPILOT_DEPLOYMENT`, `NS_COPILOT_API_VERSION`.
- Item 8: MCP keeps `NS_MCP_*`.

**Workers.** `NS_WORKER_ROLES`, a comma list from the roles below or `all`; unset means idle. Each role is built from the same `NS_STORE_`/`NS_COSMOS_*`/ingestion settings.
- `ingestion`: `IngestionConsumer`.
- `projections`: `OutboxReader` to `CatalogProjection`.
- `aggregates`: `AggregateProjection`, with prices from `PriceSnapshotStore`.
- `actions`: `ActionExecutorWorker`.
- `hitl_timers`: `HitlTimerWorker`.
- `lifecycle`: `LifecycleWorker`.
- `recommendations`: a periodic `run_pipeline`.
- `evaluation`: online `EvaluationService`, using the fixture judge unless configured.

**Frontend container.** `NS_UI_CLOUD`, `NS_UI_TENANT_ID`, `NS_UI_CLIENT_ID`, `NS_UI_API_SCOPE`, `NS_UI_API_UPSTREAM` (for example `http://api:8000`). The rendered `config.json` always has `apiBaseUrl: "/"`. Vite dev uses `NS_DEV_API_TARGET`.

**Readiness.** `/readyz` keeps its current body shape and adds a probe named `composition`. Its detail lists failed component names with reason codes. Components:
- required: `authz`, `policy_store`, `revocation`, `catalog`, `aggregates`, `ledger`, `federation`, `evaluation`, `recommendations`, `review_router`, `hitl`, `replay`, `map`, `audit`, `action_plane`, `reports`, `mcp_admin`, `realtime`;
- optional: `copilot`, `mcp_server`, `ingest`, `scan`.

**Cosmos containers** (database `neurosphere` unless noted). Item 1 confirms each partition key against its protocol's query patterns before wave B. Existing ones are not renamed.

| Container | Partition key |
|---|---|
| `policy` | `/customer_id` |
| `revocations` | `/principal_id` |
| `catalog` | `/domain`, or MultiHash `/tenant,/domain,/shard` |
| `aggregates` | `/customer_id` |
| `cost-ledger` | `/customer_id` |
| `outbox` | `/customer_id` |
| `outbox-checkpoints` | `/customer_id` |
| `ingestion-accepted` | `/customer_id` |
| `ingestion-watermarks` | `/customer_id` |
| `action_intents` | `/customer_id,/domain_id` |
| `action_execution_control` | `/customer_id` |
| `audit` | `/chain_id` |
| `audit_tail` | `/chain_id` |
| `copilot_conversations` | `/owner`, TTL -1 |
| `reports` | `/customer_id,/domain_id` |
| `mcp_servers` | `/id` |
| `deploy_register` | `/deployment_id` |

New containers:

| Container | Partition key |
|---|---|
| `recommendations` | `/customer_id,/domain_id` |
| `evaluation_runs` | `/customer_id,/domain_id` |
| `evaluation_results` | `/customer_id,/domain_id` |
| `price_snapshots` | `/snapshot_id` (item 1 confirmed 2026-10-25: ids are unique only within a partition, `/source` breaks the put-conflict rule) |
| `hitl_items` | `/customer_id,/domain_id` |
| `hitl_decisions` | `/review_item_id` (item 1 confirmed: decisions carry no customer or domain) |
| `catalog_review_queue` | `/customer_id,/domain_id` (item 1 confirmed: `ReviewItem` has `domain_id`, no `domain`) |
| `lifecycle_requests` | `/customer_id` |
| `lifecycle_holds` | `/customer_id` |
| `lifecycle_mappings` | `/customer_id` |

The sandbox keeps its own database, `sandbox-neurosphere` (`sandbox/repository.py:37-39`).

**Path aliases (item 4).**

| Old path (deprecated alias) | New path |
|---|---|
| `/catalog` | `/api/v1/catalog` |
| `/catalog/curation` | `/api/v1/catalog/curation` |
| `/audit` | `/api/v1/audit` |
| `/v1/ingest` | `/api/v1/ingest` |
| `/v1/deploy/scan` | `/api/v1/deploy/scan` |
| `/v1/deploy/plan` | `/api/v1/deploy/plan` |

Each alias answers with `Deprecation: true`, `Sunset: <one release, set at merge>` and `Link: <new>; rel="successor-version"`.

**Seed CLI (item 10).** `python scripts/sandbox/sbx_seed_stack.py [--profile small|demo] [--operator-object-id <oid>]` exits 0 and prints `{"seeded": {"<category>": n, ...}, "skipped_existing": n}` on stdout. The compose `seed` job (item 11) runs exactly this command.

**CompositionOverrides (item 1).** A frozen dataclass of optional prebuilt backends (authenticator, scope source, Cosmos client factory, blob client, model adapter). `main.create()` never passes it; only tests do.

## Implementation blueprint

### Item 1 - composition-root-authz-readiness-and-container-registry  [P]
- Model: opus.
- Deliverable:
  - `neurosphere_api.runtime`: settings (`NS_AUTH_`, `NS_STORE_`, `NS_CORS_`), `CompositionOverrides`, `compose_app`, and a component status registry with the `composition` readiness probe (it sets `app.state.health_probes` to the env probes plus composition).
  - Authz builder: `create_jwt_validator` with the Entra JWKS over `httpx`; `ScopeDeriver` with `CosmosPolicyRepository`, the `CosmosRevocationStore` checker and `PrincipalPseudonymizer`; the pseudonym key resolver per Clarification 14; `configure_authz`.
  - The CORS installer.
  - Placeholder builder modules `runtime/builders/{data,planes,copilot,mcp}.py`, each reporting its components `not_built`.
  - The container registry in `neurosphere_core.stores`, with `ensure_local_containers` and the JSON export.
  - `main.create()` calls `compose_app` after the existing bootstraps, which become optional components.
- Owned files (may edit):
  - `services/api/neurosphere_api/runtime/**` (new), except the bodies of `runtime/builders/data.py`, `planes.py`, `copilot.py` and `mcp.py`, which items 7 and 8 fill.
  - `services/api/neurosphere_api/main.py`.
  - `packages/core/neurosphere_core/stores/**` (new).
  - `infra/compose/cosmos-containers.json` (new, generated).
  - Tests: `services/api/tests/runtime_api/**`, `packages/core/tests/stores_registry/**`.
  - Scaffolding only: `tests/integration/real_stack/__init__.py` and `conftest.py` (emulator, compose-stack and stand-in-token fixtures), so items 6, 7, 8, 10 and 11 add only their own test files.
- Must NOT touch: `services/api/neurosphere_api/app.py`, `routers.py`, `authz/**`, `health/**`, `packages/core/neurosphere_core/auth/**` (consume only), `openapi.json`, `packages/contracts/**`, `frontend/**`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - The item 1 acceptance bullets.
  - Unit tests with an in-memory `DevIssuer` injected only through `CompositionOverrides` from test code.
  - The grep test proves no `DevIssuer`/`dev_issuer`/`StandIn` identifier appears under `runtime/` or `main.py`.
  - Missing `NS_AUTH_PSEUDONYM_KEY` outside local means not ready; local uses the public dev key.
  - `*` in CORS origins refuses startup.
  - The registry export is deterministic, and a drift test pins it.
  - Every registry entry for an existing store equals that store's in-module constant (a test imports them).
- Pattern references: `deploy/scan/bootstrap.py:37-73`; `authz/state.py:67-112`; `authz_helpers.py:237-296` (test-only shape); `derivation.py:122-155`; `health/router.py:33-42`; `actions/cosmos_store.py:84-105`; `ingestion/wiring.py:109-117`.
- Tests to write: `services/api/tests/runtime_api/{test_compose_authz.py,test_readiness.py,test_cors.py,test_no_dev_issuer.py,test_pseudonym_key.py}`; `packages/core/tests/stores_registry/{test_registry.py,test_export_drift.py}`.

### Item 2 - durable-stores-recommendations-evaluation-pricing  [P]
- Deliverable: `CosmosRecommendationStore`, `CosmosEvaluationStore` and `CosmosPriceSnapshotStore`, each implementing the existing protocol exactly (cursor paging, bounded queries, the scope filter in every query). Container constants come from the wire contract, and the store-to-registry parity check lands in item 7. A protocol-conformance suite runs over in-memory and a fake container in CI, and over the emulator under `integration`.
- Owned files (may edit): `packages/core/neurosphere_core/recommendations/cosmos_store.py`, `evaluation/cosmos_store.py`, `pricing/cosmos_store.py` (all new); the `__init__.py` exports of those three packages; `packages/core/tests/{recommendations_cosmos,evaluation_cosmos,pricing_cosmos}/**`; `tests/integration/stores_cosmos/**` (package owner).
- Must NOT touch: the existing `store.py` protocols (no protocol change; report a needed one to the orchestrator); `neurosphere_core/stores/**` (item 1); `services/**`.
- Depends on: none. It codes against the wire contract table.
- Acceptance criteria: conformance suites green for both backends; customer and domain isolation negative tests; the `RecordedFixtureJudge` stays the default judge (no judge change).
- Pattern references: `actions/cosmos_store.py:84-138`; `reports/cosmos_store.py:49-94`; `tests/integration/actions/test_intent_store_cosmos.py:73`.
- Tests to write: as owned.

### Item 3 - durable-stores-hitl-review-queue-lifecycle  [P]
- Deliverable:
  - `CosmosHitlStore` and `CosmosDecisionStore`.
  - A Cosmos catalog `ReviewQueue`.
  - Cosmos lifecycle hold registry, request queue and mapping store.
  - `HitlReviewRouter` in `services/api/neurosphere_api/recommendations/review_hitl.py`, which implements `ReviewRouter` over `HitlService`: idempotent per `(customer, recommendation)`, and the review item is created through the HITL service, never a raw write.
- Owned files (may edit): `packages/core/neurosphere_core/hitl/cosmos_store.py`, `catalog/review_queue_cosmos.py`, `lifecycle/cosmos.py` (all new) and the `__init__.py` exports of `hitl`, `catalog` and `lifecycle` (exports only); `services/api/neurosphere_api/recommendations/review_hitl.py` (new); `packages/core/tests/{hitl_cosmos,review_queue_cosmos,lifecycle_cosmos}/**`; `services/api/tests/runtime_planes/test_review_hitl.py`; `tests/integration/stores_hitl/**` (package owner).
- Must NOT touch: existing protocols; `recommendations/review.py` (the stub stays for tests); `neurosphere_core/stores/**`; `runtime/**`.
- Depends on: none.
- Acceptance criteria:
  - Conformance suites for both backends.
  - HITL timer queries (expiry scans) are bounded and partition-aware.
  - The decision store is append-only (no update path; test).
  - Routing the same recommendation twice returns the same review request.
- Pattern references: `hitl/store.py:37-114`; `hitl/decisions.py:72-86`; `catalog/review_queue.py:61-101`; `lifecycle/memory.py:72-99`; `recommendations/review.py:24-56`.
- Tests to write: as owned.

### Item 4 - path-normalisation-aliases-and-curation-actor  [P]
- Model: opus.
- Deliverable:
  - Each listed router module registers its router at the new `/api/v1` prefix and again at the old prefix as a deprecated alias (a shared helper in `services/api/neurosphere_api/deprecation.py`).
  - The `Deprecation`/`Sunset`/`Link` headers.
  - `PRODUCER_AUTHENTICATED_PATHS` gets both forms.
  - The curation decision route stamps `actor` from the principal and returns 403 on mismatch.
  - `openapi.json` is regenerated, and the OTel collector example and README move to the new paths.
- Owned files (may edit):
  - `services/api/neurosphere_api/catalog/router.py` and `catalog/curation/router.py` (plus `catalog/curation/service.py` only for the actor stamp).
  - `audit/router.py`, `ingest/router.py`, `deploy/scan/router.py`, `deploy/plan/router.py`, `deprecation.py` (new).
  - `authz/routes.py` (the producer path set only).
  - `services/api/openapi.json`.
  - `connectors/reference/otel-generic/collector/**`.
  - Tests: `services/api/tests/path_aliases/**`, plus existing tests under `services/api/tests/` only where they assert the producer path set or the inventory count.
- Must NOT touch: `routers.py` (the hook functions are unchanged; each module's `register` adds both prefixes); `authz/dependencies.py`; `packages/**`; `frontend/**`; `runtime/**`.
- Depends on: none.
- Acceptance criteria:
  - Both forms serve identical responses and permissions (parametrized test over every moved route).
  - Aliases carry the headers and `deprecated: true`.
  - Route inventory green.
  - `tests/ingest` producer-path equality holds and both forms return 401 without a credential.
  - Actor mismatch returns 403 and is audited as a denial.
  - Drift test green, with the component diff reported.
- Pattern references: `routers.py:34-40,55-205`; `authz/routes.py:40-70`; `catalog/curation/router.py:46`; `edge_override.py:49-60`.
- Tests to write: `services/api/tests/path_aliases/{test_aliases.py,test_deprecation_headers.py,test_curation_actor.py}`.

### Item 5 - same-origin-frontend-edge  [P]
- Deliverable:
  - A Vite `server.proxy` for `/api` (`ws: true`), `/readyz` and `/healthz` to `NS_DEV_API_TARGET`. Test and e2e modes are unaffected: the proxy is applied only in `serve` without the `e2e`/`demo` modes.
  - An nginx `/api/` proxy with WebSocket upgrade, `proxy_set_header Host`, no buffering on the copilot stream path, and the upstream from `NS_UI_API_UPSTREAM` through the nginx-unprivileged template mechanism.
  - A start-time `config.json` renderer driven by `NS_UI_*` env that writes to a writable path served at `= /config.json`. A mounted file still wins.
  - `frontend/public/config.json` defaults to `apiBaseUrl: "/"`.
- Owned files (may edit): `frontend/vite.config.ts` (`server` block only), `frontend/nginx.conf` (or `frontend/nginx/templates/default.conf.template`, new), `frontend/Dockerfile`, `frontend/docker/**` (new: config renderer), `frontend/public/config.json`, `frontend/tests/edge/**` (new).
- Must NOT touch: `frontend/src/**` (PRP-30, PRP-31), `frontend/tests/mock-api/**`, `frontend/playwright.config.ts`, `frontend/package.json`, `infra/helm/**`, `services/**`.
- Depends on: none.
- Acceptance criteria:
  - Vitest over `frontend/tests/edge/` asserts the proxy config (paths, `ws`, mode gating), and asserts that the nginx template contains the `/api/` location with upgrade headers and no `add_header Access-Control-Allow-Origin`.
  - Renderer unit test: env to JSON; a missing required var fails container start with a clear message; no value is logged except variable names.
  - `docker build` of the image succeeds (orchestrator).
  - The PRP-28 prod-exclusion tests and the full mock Playwright suite are green.
- Pattern references: `nginx.conf:24-55`; `Dockerfile:3-33`; `vite.config.ts:111-118`; `config.ts:42-83`.
- Tests to write: `frontend/tests/edge/{proxy.test.ts,nginx.test.ts,render-config.test.ts}`.

### Item 6 - entra-local-sign-in-and-operator-grant
- Deliverable:
  - `scripts/gates/p29_entra_local.py`:
    - dry-run by default;
    - `--apply` requires `NS_LIVE_APPROVED=1`;
    - `az rest` Graph GET then PATCH on application `ace128f6-...`: merges `spa.redirectUris` (default `http://localhost:5173`, `http://localhost:8080`; repeatable `--redirect-uri` for PRP-32) and adds five app roles (values `viewer`, `analyst`, `domain_steward`, `admin`, `security_auditor`; ids are deterministic uuid5) without removing anything;
    - ensures `api.requestedAccessTokenVersion = 2`;
    - optional `--assign-self ROLE` through `appRoleAssignedTo`;
    - prints a before/after diff of URIs and role values only.
  - `scripts/sandbox/sbx_grant_operator.py`: loopback-guarded; resolves the pseudonym key with item 1's resolver; writes `PolicyHead` (version bump) and `PrincipalPolicy` (role assignment plus sandbox domain memberships) through `CosmosPolicyRepository`.
  - A "Real local sign-in" section in `docs/dev/local-setup.md`: the operator gets their object id with `az ad signed-in-user show --query id -o tsv`, then runs the script, the grant, and the sign-in.
- Owned files (may edit): `scripts/gates/p29_entra_local.py` (new), `scripts/sandbox/sbx_grant_operator.py` (new), `scripts/sandbox/sandbox.mk` (a `grant-operator` target only), `docs/dev/local-setup.md` (new section only), `tests/unit/gates/test_p29_entra_local.py`, `tests/unit/sandbox_stack/test_grant_operator.py`, `tests/integration/real_stack/test_operator_grant.py`.
- Must NOT touch: `infra/**`, `services/**` (consume item 1), `scripts/gates/*` other than its own file (PRP-32 owns the hosted deploy script), `frontend/**`.
- Depends on: Item 1 (key resolver, policy container).
- Acceptance criteria:
  - Unit tests with a fake `az` runner: dry-run makes no PATCH; apply without `NS_LIVE_APPROVED=1` exits non-zero; the merge keeps foreign URIs and roles; a second apply is a no-op; no output line matches a secret pattern.
  - The grant script refuses a non-loopback endpoint.
  - Integration: after the grant, the composed deriver yields `allowed_domains` equal to the sandbox domains for that oid.
  - Running the script for real is a live gate (see Live and open gates).
- Pattern references: `scripts/gates/prp06_entra_live.py:6-52,126-151`; `sbx_guard.py:44-52`; `policy.py:60-97`.
- Tests to write: as owned.

### Item 7 - data-plane-builders-and-replay-blob  [P]
- Deliverable: fill `runtime/builders/data.py` (plus `runtime/builders/blob.py`, new) to build every component in the wire contract:
  - catalog repository, graph and review queue (Cosmos);
  - `CosmosAggregateStore` as `aggregate_reader`;
  - `CosmosLedgerStore`;
  - `FederationState` (local cell from settings, cache TTL);
  - evaluation and recommendation stores (item 2) and the `HitlReviewRouter` (item 3);
  - `ArchiveTraceReader` over an aio `ContainerClient` (Azurite via `NS_BLOB_CONNECTION_STRING`, or the `UseDevelopmentStorage` assembly locally; account URL plus `DefaultAzureCredential` otherwise) with the replay payload policy;
  - `map_pseudonymizer` and viewport limits;
  - `CosmosAuditStore`;
  - `configure_realtime(aggregate_reader=...)`;
  - `sandbox_repository` through the existing factory.

  Item 7 also adds the store-to-registry parity test for items 2 and 3.
- Owned files (may edit): `services/api/neurosphere_api/runtime/builders/data.py`, `runtime/builders/blob.py` (new), `services/api/tests/runtime_data/**`, `tests/integration/real_stack/test_data_plane.py`.
- Must NOT touch: other `runtime/**` files (item 1), router and dependency modules, `packages/core/**` (consume), `openapi.json`.
- Depends on: Items 1, 2, 3.
- Acceptance criteria:
  - With `CompositionOverrides` fakes, every data component reports `ok` and its routes return non-503 (unit).
  - With one dependency removed, readiness names exactly that component.
  - Integration against the emulators: dashboards, map, replay, federation and finops return 200 for a seeded domain.
- Pattern references: `replay/reader.py:167-230`; `archive/factory.py:27-48`; `realtime/dependencies.py:46-90`; `federation/service.py:194`; `sandbox/router.py:51-67`.
- Tests to write: as owned.

### Item 8 - action-reports-copilot-and-mcp-builders  [P]
- Model: opus.
- Deliverable:
  - `runtime/builders/planes.py`:
    - `configure_action_plane` with `CosmosIntentStore`, `CosmosExecutionControl`, a `HitlService` over item 3's stores, `CosmosAuditStore`, review policies from the existing defaults, write targets limited to the supported connector targets (the catalog target for model swaps uses the real connector path, never a metadata-only swap), the permission rechecker bound to the composed deriver, and the reviewer directory;
    - `configure_reports` with `CosmosReportStore` and the bounded tool registry;
    - `configure_mcp_admin` with `CosmosMcpServerStore`.
  - `runtime/builders/copilot.py`: `NS_COPILOT_` settings, `resolve_adapters` gating to `ApprovedEndpointAdapter`/`FoundryAgentAdapter` with `DefaultAzureCredential`, `CosmosConversationStore`, `configure_copilot`; `disabled` by default; refuses key-shaped env.
  - `runtime/builders/mcp.py`: `create_mcp_server` per the mount contract when `NS_MCP_RESOURCE_SERVER_URL` is set. MCP and REST audiences stay distinct.
  - Buttons, chat and MCP share the one composed `ActionService`/executor instance (asserted by identity in a test).
- Owned files (may edit): `services/api/neurosphere_api/runtime/builders/planes.py`, `copilot.py`, `mcp.py`; `services/api/tests/runtime_planes/**` (except item 3's `test_review_hitl.py`); `tests/integration/real_stack/test_planes.py`.
- Must NOT touch: `actions/**`, `copilot/**`, `mcp/**`, `reports/**` modules (consume their `configure_*`; report needed changes); `packages/core/**`; other `runtime/**` files.
- Depends on: Items 1, 3.
- Acceptance criteria:
  - Action plane, reports and MCP admin report `ok` with fakes.
  - The copilot, REST action route and MCP tool resolve the same executor object.
  - `NS_COPILOT_MODE=approved_endpoint` without an endpoint fails readiness as `copilot: misconfigured`, not `disabled`.
  - An endpoint for the wrong cloud is refused by `require_endpoint`.
  - Copilot env names containing `KEY`/`SECRET` refuse startup.
  - The MCP mount is present only when configured, and the existing `tests/security/mcp` suite is green against the composed app.
  - No live model call in tests.
- Pattern references: `actions/dependencies.py:141-168`; `copilot/dependencies.py:142-161`; `copilot/models/gating.py:130-185`; `approved_endpoint.py:97-126`; `mcp/server/__init__.py:6-29`; `mcp/server/factory.py:441-519`.
- Tests to write: as owned.

### Item 9 - workers-runtime-roles  [P]
- Deliverable:
  - `NS_WORKER_ROLES` parsing and a role registry in `neurosphere_workers.runtime`.
  - Each role is built from settings against the Cosmos, Blob and Event Hubs factories, using items 2 and 3's stores.
  - Every role is supervised by `WorkerRunner`, with backoff and isolation between roles.
  - Ingestion's consumer loop runs as a supervised task.
  - The health server exposes `/healthz` (process) and `/readyz` (every configured role started and not crash-looping).
  - `ingestion/__main__.py` becomes an alias.
- Owned files (may edit): `services/workers/neurosphere_workers/runtime/**`, `services/workers/neurosphere_workers/ingestion/__main__.py`, `services/workers/tests/worker_roles/**`, `tests/integration/workers_runtime/**` (package owner).
- Must NOT touch: the worker classes themselves (`actions/`, `hitl_timers/`, `lifecycle/`, `aggregates/`, `projections/`, `recommendations/`, `evaluation/`); report needed changes. Also `Dockerfile*` (CMD unchanged), `docker-compose.yml`, `packages/**`.
- Depends on: Items 1 (registry), 2, 3.
- Acceptance criteria:
  - An unknown role refuses start.
  - `all` expands to the wire contract list.
  - Unset roles mean idle, with health reporting `roles: []`.
  - Killing one fake role leaves the others running and readiness reports it.
  - The executor role never executes an intent that is not in `executing` per the PRP-17 state machine (existing tests reused).
  - Integration: with `ingestion,aggregates,projections`, a pushed sandbox event reaches the ledger, aggregates and catalog.
- Pattern references: `runtime/worker.py:46-133`; `ingestion/__main__.py:27-45`; `actions/worker.py:37-47`; `hitl_timers/worker.py:60-68`; `lifecycle/worker.py:55-69`; `aggregates/handler.py:80-91`.
- Tests to write: as owned.

### Item 10 - real-stack-synthetic-seed
- Deliverable: `scripts/sandbox/sbx_seed_stack.py` per the wire contract:
  1. Generate the world with `sandbox.generate`.
  2. Push telemetry and cost through `HubSeam` to Event Hubs, then wait (bounded, no tight polling; one timeout) for the workers to land ledger, aggregates, catalog and archive blobs.
  3. Write the synthetic price sheet.
  4. Run the recommendations pipeline into the Cosmos store and route a subset to review through `HitlReviewRouter`.
  5. Run offline evaluation over `sandbox/evaluation` fixtures.
  6. Draft intents through `ActionService` up to the awaiting states.
  7. Save reports.
  8. Register synthetic MCP servers (`.invalid` hosts, never contacted).
  9. Grant the synthetic personas (and `--operator-object-id` through item 6's module).

  The script is idempotent and loopback-guarded, and `make seed-stack` runs it. New fixtures go under `sandbox/stack/**`.
- Owned files (may edit): `scripts/sandbox/sbx_seed_stack.py` (new), `scripts/sandbox/sandbox.mk` (a `seed-stack` target only), `sandbox/stack/**` (new fixtures), `tests/unit/sandbox_stack/**` (except item 6's test file), `tests/integration/real_stack/test_seed.py`.
- Must NOT touch: `sandbox/generate.py` and existing `sandbox/*.py` (consume), `scripts/sandbox/sbx_guard.py` (the loopback rule stays), `services/**`, `packages/**`.
- Depends on: Items 6, 7, 8, 9.
- Acceptance criteria:
  - The unit test (fake seams) shows every category written through a service or store API, never raw container upserts except where the store API is the container.
  - A second run reports `skipped_existing` and creates no duplicates.
  - No intent reaches `executing`.
  - Integration: every page category count is greater than 0.
  - Seeding a non-loopback endpoint exits non-zero.
- Pattern references: `scripts/sandbox/sbx_cli.py:81-122`; `sbx_seam.py:44-52`; `recommendations/pipeline.py:99-234`; `evaluation/service.py:90-112`.
- Tests to write: as owned.

### Item 11 - compose-app-profile-and-real-stack-smoke
- Deliverable:
  - `docker-compose.yml` profile `app`:
    - `api` gets env for `NS_AUTH_*` (defaults to the dev GUIDs, Clarification 19), `NS_COSMOS_ENDPOINT` plus a placeholder emulator key built without a credential-shaped literal, `NS_BLOB_CONNECTION_STRING` for Azurite, Event Hubs, and `NS_CORS_ALLOWED_ORIGINS` empty.
    - `workers` gets `NS_WORKER_ROLES=all` and the same store env.
    - New `frontend` service: builds `frontend/Dockerfile`, `8080:8080`, `NS_UI_*`, `NS_UI_API_UPSTREAM=http://api:8000`, healthcheck on `/config.json`.
    - New `seed` one-shot job running the item 10 command after `api` and `workers` are healthy.
  - Integration suites: `tests/integration/compose/test_app_profile.py` updated; `tests/integration/real_stack/test_manifest_routes.py`, a route-to-endpoint map covering all 26 manifest routes.
  - The CI-safe test `services/api/tests/runtime_routes/test_manifest_routes_serve.py`.
  - `frontend/playwright.real-stack.config.ts`, with its own `NS_REAL_STACK_PORT` and no webServer (the compose stack), plus `frontend/tests/real-stack/**` (global setup waits for a headed sign-in).
  - Makefile targets `stack-up`/`stack-down`.
  - The "Real stack" section in `docs/dev/local-setup.md`.
- Owned files (may edit): `docker-compose.yml`, `Makefile` (two targets only), `tests/integration/compose/**`, `tests/integration/real_stack/test_manifest_routes.py`, `services/api/tests/runtime_routes/**`, `frontend/playwright.real-stack.config.ts` (new), `frontend/tests/real-stack/**` (new), `docs/dev/local-setup.md` ("Real stack" section only).
- Must NOT touch: `frontend/src/**`, `frontend/playwright.config.ts`, `frontend/package.json` (run with `exec playwright test -c ...`), `.github/workflows/**` (the real-stack config never runs in the PR job), `services/**` other than its own tests.
- Depends on: Items 5, 6, 7, 8, 9, 10.
- Acceptance criteria:
  - `docker compose --profile app up -d --wait` exits 0 from a clean state.
  - `curl http://localhost:8080/readyz` returns 200 through nginx.
  - The integration suites are green.
  - The CI-safe test is green in the normal `python` CI job.
  - The manual Playwright run evidence (or OPEN) is recorded in the PRP execution state.
  - `docker compose --profile app down` leaves no orphans (existing test).
- Pattern references: `docker-compose.yml:96-158`; `tests/integration/compose/test_app_profile.py:42-62`; `frontend/playwright.config.ts:3-34`; `authz_helpers.py:228-296` (test-only token for the in-process test).
- Tests to write: as owned.

### Waves
- A = items 1, 2, 3 and 4 [P] (WIP 4). Item 1 owns `runtime/**`, `main.py` and `neurosphere_core/stores/**`. Items 2 and 3 own new store modules in disjoint packages. Item 4 owns the moved routers, `authz/routes.py` and `openapi.json`.
- B = items 5, 6 and 7 [P]. Item 5 owns only frontend edge files. Item 6 owns its scripts and the first `sandbox.mk`/`local-setup.md` edits. Item 7 owns `runtime/builders/data.py` and `blob.py`.
- C = items 8 and 9 [P]. Item 8 owns `runtime/builders/{planes,copilot,mcp}.py`; item 9 owns the workers runtime.
- D = item 10, then item 11, sequenced. Both touch `sandbox.mk`/`local-setup.md` lineage and compose, and compose is shared across worktrees.

No shared file is edited by two items in the same wave. Integration (`-m integration`) legs of items 2, 3, 7, 8 and 9 run sequentially on the integration branch after each wave, because compose is shared.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
uv run pytest -q services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_planes services/api/tests/runtime_routes services/api/tests/path_aliases services/api/tests/authz services/api/tests/test_openapi_drift.py
uv run pytest -q packages/core/tests/stores_registry packages/core/tests/recommendations_cosmos packages/core/tests/evaluation_cosmos packages/core/tests/pricing_cosmos packages/core/tests/hitl_cosmos packages/core/tests/review_queue_cosmos packages/core/tests/lifecycle_cosmos
uv run pytest -q services/workers/tests/worker_roles tests/unit/gates/test_p29_entra_local.py tests/unit/sandbox_stack tests/security/authz tests/security/mcp
uv run ruff check . && uv run pyright
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend exec vitest run
pnpm --filter @neurosphere/frontend build
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test
python scripts/licenses_report.py --check
# sequenced, one lane at a time (fixed compose project name):
docker compose --profile app up -d --wait
MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/compose tests/integration/stores_cosmos tests/integration/stores_hitl tests/integration/workers_runtime tests/integration/real_stack
curl -fsS http://localhost:8080/readyz
docker compose --profile app down
# manual, real Entra (operator):
NS_LIVE_APPROVED=1 python scripts/gates/p29_entra_local.py --apply --assign-self admin
python scripts/sandbox/sbx_grant_operator.py --object-id <oid> --role admin
NS_REAL_STACK_PORT=8080 pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts --headed
```

## Live and open gates
- **Entra app change.** Running `p29_entra_local.py --apply` against `neurosphere-api-dev` modifies a shared tenant resource. It needs `NS_LIVE_APPROVED=1` and operator approval at execution, and it adds redirect URIs and roles only. It is reported OPEN until it runs.
- **Real-Entra browser run.** The headed real-stack Playwright run is a manual gate. Evidence is the run output plus screenshots in `temp/`, not committed. It is OPEN until it runs.
- **Copilot live call.** A live call against `aifndry-loom-centralus` is a paid call and needs a role grant on a shared resource (PRP-32, operator-approved). It stays OPEN in this PRP, and G05's existing evidence is not re-claimed. Locally, copilot defaults to `disabled`.
- **Hosted stack.** Hosted readiness, Bicep containers from `cosmos-containers.json`, Key Vault references and hosted redirect URIs are PRP-32.
- This PRP runs no `az deployment` and creates no Azure resource.

## NOT building
- Hosted deployment, App Service and Bicep changes (including Cosmos `sqlDatabases`/containers), hosted seeding, hosted redirect URIs and the copilot role grant (PRP-32). `sbx_guard`'s loopback rule stays.
- The visual redesign, style switcher, shell or feature styling, and mock API changes (PRP-30).
- New UI pages for the catalog, audit, finops, federation and deploy (PRP-31). PRP-29 only provides the `/api/v1` API forms.
- A dev bypass, fake issuer or stub sign-in in any production code path. The dev issuer exists only in test code.
- Alias removal (a follow-up issue after one release) and server-side stamping of deploy `consented_by` (follow-up issue).
- Changes to authorization semantics, permissions or the route-inventory model beyond the producer path set.
- Analytics adapters for dashboards (the probe stays optional), a live LLM judge, and real third-party connectors.
- Production data. Seeding is synthetic only.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (the confirm-at-approval list is explicit)

## Execution state

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 composition-root-authz-readiness-and-container-registry | merged | worktree-agent-a3643f6b5a46538c7 | opus | 283 passed (runtime_api, stores_registry, authz, openapi drift, health, me_api); review APPROVED; merge 3754d76 | 2026-10-25 |
| 2 durable-stores-recommendations-evaluation-pricing | merged | worktree-agent-a5a5b2d2de54d8cb6 | sonnet | rework 15ed7b9 (price key=/snapshot_id, cross-domain id parity); on integration 269 unit + 36 emulator (stores_cosmos); gitleaks FP fingerprinted f855aee; merge d3a92bd | 2026-10-25 |
| 3 durable-stores-hitl-review-queue-lifecycle | merged | worktree-agent-ab490c10a817e4b3b | sonnet | rework f5020a5 (store moved to hitl_cosmos per user; keys = registry); on integration: 424 unit + 36 emulator (stores_hitl) passed; merge c84d145 | 2026-10-25 |
| 4 path-normalisation-aliases-and-curation-actor | merged | worktree-agent-af6d1108b708e36e6 | opus | rework 3cfa128 (helper actor); 1405 passed on integration; OpenAPI components unchanged (305), +23 paths; review APPROVED; merge 0201fbd | 2026-10-25 |
| 5 same-origin-frontend-edge | merged | worktree-agent-a6e22c49f54f73ca9 | sonnet | 214669a: vitest 603, playwright 334, docker build+run OK (missing var fails named); WS/stream vs live upstream untested; on integration typecheck + edge 22 passed; merge 61968b3 | 2026-10-25 |
| 6 entra-local-sign-in-and-operator-grant | merged | worktree-agent-aee9edfa34aa24239 | sonnet | 9aee7ab; 160 unit + operator-grant emulator passed; live --apply OPEN; merge 2b37022 | 2026-10-25 |
| 7 data-plane-builders-and-replay-blob | merged | worktree-agent-a112a65db205d6723 | sonnet | 0b9181d; item-1 readiness test fixed forward 437b6ab (placeholder codes); on integration 312 unit + runtime_api 71 + real_stack data/grant emulator passed; catalog search fails closed (no search backend); merge 06b6cc3 | 2026-10-25 |
| 8 action-reports-copilot-and-mcp-builders | merged | worktree-agent-a747f85cb9b49701e | opus | 4a520fa; review APPROVED; readiness expectations fixed forward; gitleaks FP fingerprinted 31f448b; on integration 1400 passed + real_stack 3 emulator; prod write targets empty (advisory); Commercial copilot gated off (no matrix rows); merge 5c60b54 | 2026-10-25 |
| 9 workers-runtime-roles | merged | worktree-agent-a848c517ea8dd521c | sonnet | c9b45b7; 377 workers passed; hub endpoint fixed to 127.0.0.1 (2dfd666) -> workers_runtime 2 passed (hub + seeded); merge 3a10c2b | 2026-10-25 |
| 10 real-stack-synthetic-seed | merged | worktree-agent-a64461014aaf78c41 | sonnet | 51ba6be; on integration 209 unit + test_seed emulator passed (12 categories >0; re-run skipped_existing 1041); worker/API pseudonym parity proven; merge 0b6da0c | 2026-10-25 |
| 9b aggregates-price-refresh (fix-forward) | merged | worktree-agent-ab6f3c341b00ba8fa | sonnet | 30c8820: periodic PriceTableRefresher (NS_WORKER_PRICE_REFRESH_SECONDS, default 60); 381 workers passed on integration; merge 25db405 | 2026-10-25 |
| 11 compose-app-profile-and-real-stack-smoke | merged | worktree-agent-af183ac3682cc98c6 | sonnet | fc149d8: up --wait OK, /readyz 200 via nginx, host seed exit 0, real_stack+compose 45 passed, default Playwright 334 unchanged; strict expected-gap list (sandbox db, dated seed, map empty, reports persona-private); workarounds: inline api build (api pkg lacks workers dep since PRP-21), cosmos-init (ensure_local_containers race); manual real-Entra Playwright OPEN; merge c194e1d | 2026-10-25 |
| E1 platform-fix-forward (api workers dep, container race, worker data mounts, sandbox db) | in-progress | - | sonnet | user approved 2026-10-25 | 2026-10-25 |
| E2 seed-data-fix-forward (recent dates, map entities, operator reports, hard route asserts) | todo | - | sonnet | user approved 2026-10-25; after E1 | 2026-10-25 |

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Follow-ups:
