---
name: prp-33-apim-gateway-observe
status: active
started: 2026-10-29
branch: prp-33-apim-gateway-observe
pr: 146
review: required
priority: P1
order: 1
created: 2026-10-29
model: sonnet
phase: 6
ns: NS-01, NS-02, NS-07, NS-08, NS-09
depends_on: PRP-02, PRP-07, PRP-09, PRP-10, PRP-22, PRP-29, PRP-31
wave: W10
absorbs: new (APIM AI gateway observe side; patterns from microsoft/mosaic-apim, MIT, patterns only)
---

# PRP-33: APIM AI gateway, observe side

## Goal
Make Azure API Management (APIM) a first-class, read-only governed surface in NeuroSphere: the capability matrix knows which APIM tiers carry the LLM gateway features, the telemetry pipeline ingests APIM gateway and LLM token logs into the existing `gateway` observation kind, a registered gateway can be inventoried in observe mode without any write, and the catalog gains two contracts (Grant, McpServer) that PRP-34 later enforces through the gateway. It is for platform owners, FinOps analysts and stewards who need per-caller token usage from the gateway and a reviewed picture of what the gateway already serves. It lands in W10 after the UI surfaces (PRP-31) so its two pages slot into the shipped navigation. PRP-34 (manage side) consumes everything here and must not start before this ships.

Patterns are borrowed from microsoft/mosaic-apim (MIT) as patterns only (clarification 6): observe mode before manage mode, desired state separate from observed state rebuilt on every sync, usage read from `ApiManagementGatewayLogs` joined to `ApiManagementGatewayLlmLog` on `CorrelationId`, never from request or response bodies. No MOSAIC code, Cosmos layout or Entra app layout is vendored.

> NS-01: telemetry and cost ledger. NS-02: versioned catalog. NS-07: reuse of enterprise APIM after validation. NS-08: authorization at every query path; no credential in files or logs. NS-09: MCP servers as governed, discoverable tools.

## Acceptance criteria
- [ ] Item 1: Every APIM tier row (Consumption, Developer, Basic, Standard, Premium, Basic v2, Standard v2, Premium v2) has `llm_token_limit`, `llm_emit_token_metric`, `gateway_llm_logs`, `gateway_mcp_logs`, `mcp_server`, `backend_pool` and `anthropic_messages_schema` feature rows with a Learn source URL and observed date; Consumption rows say the LLM limit and metric policies are unavailable and Consumption is unavailable in Government; `anthropic_messages_schema` is `available` only on v2 tiers; all Government v2 rows are `unverified`; `validate_profile()` returns `capability_unavailable` with the row id for a Consumption tier + token-limit profile.
- [ ] Item 2: `CloudProfile` exposes an APIM gateway suffix per cloud (`.azure-api.net`, `.azure-api.us`) and `clients.factories` exposes an ARM client bound to the profile's management host and `DefaultAzureCredential(authority=login_host)`; a Government profile never resolves a `.net` host (tested); no new PyPI dependency is added.
- [ ] Item 3: The Azure Monitor connector gains two source kinds whose fixed KQL selects only the columns listed in the item; the recorded-fixture test proves `RequestMessages`, `ResponseMessages`, `RequestBody`, `ResponseBody`, `RequestHeaders`, `ResponseHeaders` and `TraceRecords` bodies are never projected; a gateway log row and its LLM log row join on `CorrelationId` into one `TelemetryEvent` plus one `CostRecord` (`observation_source: gateway`, amount null) with prompt, completion and total tokens, model, deployment, API id, product id, subscription id (hashed), backend id, response code and region.
- [ ] Item 4: The `gateway_poll` worker role runs the connector against a registered gateway's workspace on a bounded window, posts through the ingest API under a registered producer with `sources: ["gateway"]`, and a replayed window produces zero duplicate ledger entries (dedupe on `CorrelationId` as the request id); freshness and coverage are reported per poll; Government workspaces are refused without the existing `allow_unverified_government` opt-in.
- [ ] Item 5: `grant.schema.json` and `mcp_server.schema.json` exist with generated Python and TypeScript models, canonical ids, golden fixtures and round-trip tests; `EntityType` gains `grant` and `mcp_server`, `RelationType` gains `grants_access_to`; the core protocol list caps are updated; `packages/contracts/scripts/generate.py --check` is clean; the permission enum gains `grant.read` and `grant.write` and the route inventory test still passes.
- [ ] Item 6: A gateway can be registered by ARM resource id in observe mode; registration performs a read-only preflight (GET service, tier from `sku.name`, diagnostic settings categories) and stores an inventory snapshot of APIs, operations, products, backends including pool members and circuit-breaker rules, policy fragment names, subscription ids (never keys, never named-value secrets); the inventory is rebuilt on every sync and never edited by hand; the snapshot records whether `GatewayLlmLogs` and `GatewayMCPLogs` diagnostics are enabled; every route declares a permission and the inventory is scoped to the caller's domains.
- [ ] Item 7: A Gateways page lists registered gateways with tier, mode, diagnostics state and last sync; a gateway detail shows the inventory; the catalog UI renders Grant and McpServer entities and the `grants_access_to` relationship; both pages pass the existing a11y and visual gates; the mock API carries fixtures for both.
- [ ] Item 8: `scripts/gates/g17_apim_observe_live.py` refuses without `NS_LIVE_APPROVED=1` (exit 2, no `az` call), and when approved provisions a throwaway Standard v2 APIM in the Limitlessdata subscription, enables `GatewayLogs` and `GatewayLlmLogs` to a throwaway workspace, imports one LLM API pointed at the approved Foundry endpoint, sends one request, polls until the joined row appears, writes `docs/evidence/G17/observe-<date>.{md,json}` with the subscription tokenised, and tears everything down; G17 is reported OPEN in `docs/RESEARCH-AND-GATES.md` when the run did not happen.
- [ ] PRP exit: items 1-8 green under `verify-gates -Mode full`; reviewer verifies no code path writes to a registered gateway; G17 observe status recorded.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Split | two PRPs; one; three | Two: PRP-33 observe (this), PRP-34 manage. Grant and McpServer contracts live here so PRP-34 consumes shipped contracts |
| 2 | Priority and sequencing | P1 W10 after PRP-31; P2 after PRP-25/26; P0 parallel with PRP-31 | P1, wave W10, after PRP-31 ships (shared navigation and route manifest) and ahead of PRP-25/26 |
| 3 | Live gate target | throwaway Standard v2; reuse Loom APIM observe only; none | Throwaway Standard v2 in Limitlessdata, created and torn down by the gate script, behind `NS_LIVE_APPROVED=1` plus per-step operator approval; OPEN when not run. Note (2026-10-29, Learn verified): `llm-token-limit` and `llm-emit-token-metric` apply to every tier except Consumption, so Developer is not blocked on policy availability; Standard v2 is chosen for an SLA-backed production-shaped run and for the Anthropic Messages schema which is v2-only |
| 4 | Grants model | no new entity; add a grant contract | Add a Grant catalog contract (principal user, app, agent or Entra group; target model API, deployment or MCP server; token-per-minute, token quota per period, request limit; cost center). Opus review as a PRP-01 style contract change |
| 5 | Own MCP server behind APIM | yes optional in Bicep and Helm; customer servers only | Yes, optional and off by default. The IaC lands in PRP-34; this PRP only models McpServer and reads MCP logs |
| 6 | Reuse from MOSAIC | patterns only; vendor code with attribution | Patterns only; policy XML and KQL are written against Microsoft Learn with citations |
| 7 | Grant contract home | PRP-33; PRP-34 | PRP-33 (item 5), so enforcement in PRP-34 codes against a shipped schema |
| 8 | Government pricing | inherit MOSAIC Retail Prices for Gov; keep NS rule | Keep the NS rule: the Azure Retail Prices API is Commercial-only (G01, verified 2026-10-19). Gateway token rows for Government stay unpriced until a Government-applicable sheet exists; never a Commercial fallback |
| 9 | Where connector output enters the system | direct ledger write; through ingest API | Through the ingest API under a registered producer, so authorization, kinds and audit are the ones every other source uses |

## Context manifest

### Files that matter
- `PRP.md` sections 1-3; `docs/PRD.md` NS-01, NS-02, NS-07, NS-08, NS-09; `docs/ARCHITECTURE.md` line 18 (APIM reused or provisioned, before API authorization and policy).
- `docs/RESEARCH-AND-GATES.md` line 26 (G01: APIM rows, Retail Prices Commercial-only), line 27 (G02: Government audiences unverified), line 29 (G04: no live Azure Monitor contract run; Government endpoints are configuration only), line 33 (G08: Government MCP OPEN).
- `docs/security/threat-model.md` lines 62-63 (boundaries B2/B3), 96 (APIM is the only public ingress), 100 and 347 (gap: no rate-limit or quota policy in `apim.bicep`; PRP-34 closes it), 231 (reuse never writes to reused ids).
- Capability matrix: `packages/core/neurosphere_core/capabilities/data/apim.yaml` (4 base rows, no `sku` dimension), `commercial_regions.yaml:3184+` (regional rows), `capabilities/loader.py` (`load_matrix`, `_check_row`), `capabilities/validate.py:174` (`default_matrix`), `:196` (`_resolve`), `:353` (`validate_profile`). Consumers to copy: `copilot/models/gating.py:130` (`resolve_adapters`), `evaluation/registry/policy.py:19` (`judge_availability`). Tests: `tests/unit/capabilities/`, `tests/contracts/test_capability_matrix.py`.
- Cloud profile and clients: `packages/core/neurosphere_core/cloud/profile.py:25-42` (hosts), `:47-54` (suffixes; no APIM), `:81-85` (`management_url`); `clients/factories.py:51-67` (secrets only when `NS_ENV=local`; `DefaultAzureCredential(authority=login_host)`; Cosmos, Event Hub and checkpoint factories only).
- Ingest: `services/api/neurosphere_api/ingest/auth.py:26` (`ObservationKind = gateway | application | billing`), `:35-50` (`ProducerRegistration.sources`), `ingest/settings.py:34-35` (producers file), `ingest/service.py:83-170` (flow) and `~315-335` (cost path). Worker dedupe: `services/workers/neurosphere_workers/ingestion/models.py:43` (event_id). Ledger: `packages/core/neurosphere_core/ledger/fold.py:52-62` (`dedupe_by_doc_id`), `:140-148` (`fold_entry` by request id); `services/api/neurosphere_api/finops/sandbox_source.py:49-71` (`dedupe_key` is the request id shared by gateway, application and billing views).
- Contracts: `packages/contracts/python/neurosphere_contracts/cost/v1/cost_record.py:146` (`kind`), `:238` (`observation_source`); `telemetry/v1/telemetry_event.py:143`; catalog schemas `packages/contracts/schemas/catalog/v1/*.schema.json` (source of truth), generated `catalog/v1/*.py` (header `GENERATED`; drift check `packages/contracts/scripts/generate.py --check`), TS mirror `packages/contracts/ts/src/catalog/v1/*.ts`; enumerations `catalog/v1/common.py:147-200` (`EntityType` 12 values at 178-192, `RelationType`); `alias.py:63-75`; canonical id grammar `tests/contracts/validators.py:36-42`; tests `tests/contracts/test_drift.py`, `test_schemas.py`, `test_roundtrip.py`, `test_golden_fixtures.py`, `test_canonical_ids.py`, `packages/contracts/ts/.../roundtrip.test.ts`.
- Core catalog protocol: `packages/core/neurosphere_core/catalog/protocol.py:68-92` (duplicated `EntityType` and `RelationType` literals), `:137` (12-entry cap), `:147` (9-entry cap).
- Azure Monitor connector: `connectors/reference/azure-monitor/.../queries.py:21-44` (`SourceKind` LOG_ANALYTICS, APP_INSIGHTS; KQL as constants, time window in `timespan` never in query text); `connectors/reference/azure-monitor/README.md` (documented limits 500,000 rows, 100 MB, 200 requests per 30 s; Government host `api.loganalytics.us` behind `allow_unverified_government`); `docs/connectors/coverage.md:20`. Nothing wires this connector into ingest today.
- Deploy scan: `services/api/neurosphere_api/deploy/scan/graph.py:27` (`microsoft.apimanagement/service -> apim`), `:79` (token scope); `scan/models.py:24`; `deploy/plan/planner.py:59`.
- Permissions and authz: `packages/core/neurosphere_core/auth/scope/permissions.py:59-72` (enum; no grant or MCP permission); route inventory test `services/api/tests/authz/test_route_inventory.py:33-44`; `require(permission, domain_from_path("domain"))` wire contract in `PRPs/shipped/PRP-17-action-executor-and-hitl.md:248-273`.
- Stores to copy: `packages/core/neurosphere_core/actions/cosmos_store.py` (ETag-conditional replace, hierarchical key `/customer_id`,`/domain_id`) and the in-memory twin in `actions/store.py`.
- MCP admin registry (external servers, admin plane, not catalog): `services/api/neurosphere_api/mcp/admin/router.py:93-214`; own server mount contract `mcp/server/__init__.py:1-21`.
- Frontend: `frontend/src/app/route-manifest.json`, `frontend/src/app/workspaceNav.ts`, `frontend/tests/mock-api/server.ts`, PRP-31 pages under `frontend/src/pages/` as the layout to copy; Playwright specs under `frontend/tests/e2e/<area>/`.
- Live gates: `scripts/gates/g01_deploy_smoke.py:3-17` (header, exit codes), `:143-188` (subscription tokenisation `<subscription:sha256-8>`), `:240` (`--subscription` required), `:804-807` (`NS_LIVE_APPROVED` refusal, exit 2, no `az` call); `g01_analytics_live.py:3,38,46,85,251`. Evidence layout `docs/evidence/G01/README.md`.
- Bicep: `infra/bicep/modules/apim.bicep:24-25` (`@allowed(['Developer','Standard','Premium'])`; v2 SKUs not allowed; PRP-34 changes this, PRP-33 must not); `tests/unit/infra/test_bicep_endpoints.py:20,110` (fails on literal Commercial hosts).

### Patterns to match
- Matrix rows: `capabilities/data/foundry.yaml` row shape (`id`, `service`, `feature`, `cloud`, `region`, `availability`, `ga_status`, `authorization_scope`, `source_url`, `observed`, `notes`); `availability`, `ga_status` and `authorization_scope` are separate columns; unknown is `unverified`, never `supported`.
- Gating consumers: `copilot/models/gating.py:130` reads the matrix only and records a reason when disabled.
- Connector source kind: `queries.py:21-44` constant KQL with `timespan` outside the query; result carries freshness and coverage; 429 maps to `rate_limited` with capped backoff.
- Ingest producer: `ingest/auth.py:35-50` registration with `sources`; secrets as sha256 only.
- Ledger fold: `ledger/fold.py:140-148` request-id fold; gateway and billing views reconcile on the same request id.
- Contract addition: schema JSON first, then `generate.py`, then TS mirror, then golden fixture under `tests/contracts/fixtures/`, then `test_canonical_ids.py` grammar row.
- Router: `services/api/neurosphere_api/<module>/router.py` with `require(permission, domain_from_path("domain"))`; lists are `{ "items": [...], "next_cursor": str | null }`; problem+json errors from `neurosphere_core.errors`.
- Worker role: `services/workers/neurosphere_workers/ingestion/` runtime base (graceful shutdown, checkpoints) and the PRP-09 Azure Monitor poll shape (bounded window split into slices; watermark advances only over fully answered slices).
- Live gate: `g01_deploy_smoke.py` structure (refusal first, create, verify, teardown with register-guarded deletes, evidence JSON + Markdown, tokenised subscription).

### Conventions
- Python 3.12, uv, Pydantic v2 `extra="forbid"`; ruff line 100 (`pyproject.toml:61-75`), pyright standard (`:77-84`); pytest excludes `integration` and `live` by default (`:85-92`).
- Test directory names must be unique across `packages/*/tests` and `services/*/tests` (PRP-17 D6; memory: same-named test dirs shadow each other).
- `python`, never `python3`; emulators on `127.0.0.1`.
- No `|| true` in CI; the planning validator fails on it.
- Frontend: TypeScript strict, Fluent UI v9, Vitest + Testing Library, Playwright with unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` per worktree.

### Gotchas
- `llm-token-limit` and `llm-emit-token-metric` apply to Developer, Basic, Standard, Premium and all v2 tiers; only Consumption lacks them (Learn, 2026-10-29). Do not copy MOSAIC's claim that classic tiers lack them. The Anthropic Messages schema is v2-only. Counters are per gateway (workspace or regional), never instance-wide; v2 tiers use a token bucket, classic tiers a sliding window.
- `ApiManagementGatewayLlmLog` is a separate category (`GatewayLlmLogs`) from `GatewayLogs`; both diagnostics must be enabled or the join is empty. Token usage is read from the model response; broken streams may log no tokens. The item 3 KQL must never project `RequestMessages`/`ResponseMessages`.
- The Azure Retail Prices API is Commercial-only; Government gateway rows stay unpriced (clarification 8).
- Consumption tier is unavailable in US Government; v2 tier availability in Government is not on the Learn region table, so rows are `unverified`.
- `tests/unit/infra/test_bicep_endpoints.py` fails on a literal `azure-api.net` in Bicep or params; the suffix lives in `CloudProfile` and `sovereign-profile.yaml:24`.
- `apim.bicep` stays untouched here (PRP-34 owns it); `reuse` never writes to a reused instance and this PRP adds no write path at all.
- The connector SDK depends on core; core must not import `neurosphere_connector` (PRP-17 D5). The worker role imports the connector; core gets only protocols.
- `azure-mgmt-apimanagement` is not added; ARM REST through the existing `httpx` host pattern (`connectors/reference/foundry-actions/.../endpoints.py:55-61`) keeps the licence gate and the Government host rule simple.
- Core `catalog/protocol.py` duplicates the contract literals and caps the list lengths (12 and 9); forgetting them breaks `tests/contracts` and the catalog store tests in one go.
- Subscription keys and named values are secrets: inventory stores subscription ids and named-value names only; `listSecrets` is never called.

### External references
- APIM policy reference, AI gateway table and tier columns: https://learn.microsoft.com/azure/api-management/api-management-policies#ai-gateway
- `llm-token-limit` (applies to all tiers except Consumption; per-gateway counters; v2 token bucket): https://learn.microsoft.com/azure/api-management/llm-token-limit-policy and https://learn.microsoft.com/azure/api-management/api-management-sample-flexible-throttling#rate-limits-and-quotas
- `llm-emit-token-metric` (up to 5 dimensions, inbound only, Application Insights custom metrics): https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy
- LLM logging and the `GatewayLlmLogs` category: https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs
- Resource log categories (`GatewayLogs`, `GatewayLlmLogs`, `GatewayMCPLogs`): https://learn.microsoft.com/azure/api-management/monitor-api-management-reference#resource-logs
- Table columns: https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaylogs#columns, https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog#columns, https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaymcplog#columns
- Backends, pools, circuit breakers (up to 30 members; approximate balancing): https://learn.microsoft.com/azure/api-management/backends#load-balanced-pool
- MCP servers in APIM (tiers, transports, governance): https://learn.microsoft.com/azure/api-management/mcp-server-overview
- v2 tiers overview and region availability: https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview and https://learn.microsoft.com/azure/api-management/api-management-region-availability
- Tier feature comparison (Consumption not in US Government): https://learn.microsoft.com/azure/api-management/api-management-features
- Log Analytics query API request and response format (already cited by the connector README): https://learn.microsoft.com/azure/azure-monitor/logs/api/request-format
- MOSAIC pattern sources (read for shape, do not copy): https://github.com/microsoft/mosaic-apim README sections "Gateways" and "Data model and Cosmos layout"; `docs/adr/0019-usage-telemetry.md` (join on `CorrelationId`, trace-first attribution, rollups never lower a completed day).

## Implementation blueprint

### Item 1 - matrix-apim-tier-rows  [P]
- Deliverable: APIM tier and feature rows in the capability matrix (eight tiers, seven features, Commercial and Government) with Learn sources dated 2026-10-29; a `tier_capability(tier, feature, cloud)` helper in `capabilities/validate.py` that returns the row or `unverified`; Government v2 rows `unverified`; Consumption rows `capability_unavailable` for `llm_token_limit` and `llm_emit_token_metric` and unavailable in Government; `anthropic_messages_schema` available on v2 only. G01 row note appended.
- Owned files (may edit): `packages/core/neurosphere_core/capabilities/data/apim.yaml`, `packages/core/neurosphere_core/capabilities/validate.py` (additive helper only), `tests/unit/capabilities/test_apim_tiers.py` (new), `docs/RESEARCH-AND-GATES.md` (G01 row, one appended sentence).
- Must NOT touch: other matrix YAML files, `capabilities/loader.py`, `commercial_regions.yaml`, any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria: item 1 above; `tests/contracts/test_capability_matrix.py` still passes.
- Pattern references: `foundry.yaml` row shape; `gating.py:130` reason recording; PRP-02 clarification 10 (feature-specific page alone does not make a Government row `available`).

### Item 2 - cloud-profile-and-arm-client  [P]
- Deliverable: `CloudProfile.apim_gateway_suffix` per cloud; `clients/factories.py` gains `arm_client(profile)` returning an `httpx.AsyncClient` bound to `management_url` with a bearer from `DefaultAzureCredential(authority=login_host)` and the management scope, plus `log_analytics_client(profile)` for the resource-centric query host; both refuse a host that does not belong to the profile cloud.
- Owned files (may edit): `packages/core/neurosphere_core/cloud/profile.py`, `packages/core/neurosphere_core/clients/factories.py`, `packages/core/tests/cloud/test_apim_suffix.py` (new), `packages/core/tests/clients/test_arm_client.py` (new).
- Must NOT touch: `infra/`, connectors, services.
- Depends on: none.
- Acceptance criteria: item 2 above; Government profile tests assert no `.net` host.
- Pattern references: `factories.py:51-67`; `profile.py:81-85`; `foundry-actions/.../endpoints.py:55-61` host and scope table.

### Item 3 - gateway-log-source-kinds  [P]
- Deliverable: `SourceKind.APIM_GATEWAY` and `SourceKind.APIM_MCP` in the Azure Monitor connector. `APIM_GATEWAY` KQL: `ApiManagementGatewayLogs` projected to `TimeGenerated, CorrelationId, ApiId, ApiRevision, OperationId, ProductId, ApimSubscriptionId, BackendId, BackendResponseCode, ResponseCode, IsRequestSuccess, TotalTime, BackendTime, Region, _ResourceId` left-joined on `CorrelationId` to `ApiManagementGatewayLlmLog` projected to `ModelName, DeploymentName, PromptTokens, CompletionTokens, TotalTokens, IsStreamCompletion, ApiVersion`. `APIM_MCP` KQL: `ApiManagementGatewayMCPLog` projected to `TimeGenerated, CorrelationId, ToolName, ToolCount, TransportType, _ResourceId`. A mapper from a joined row to `TelemetryEvent` + `CostRecord` (`observation_source: gateway`, `amount: null`, `ApimSubscriptionId` sha256-hashed, request id = `CorrelationId`). Recorded fixtures for both kinds; coverage row in `docs/connectors/coverage.md`.
- Owned files (may edit): `connectors/reference/azure-monitor/` (package, tests, README), `docs/connectors/coverage.md` (one row).
- Must NOT touch: `services/`, `packages/core`, `packages/contracts`.
- Depends on: none.
- Acceptance criteria: item 3 above; a test asserts the KQL constants contain none of the body or header column names.
- Pattern references: `queries.py:21-44`; connector README limits; `cost_record.py:238` and `telemetry_event.py:143` field names.

### Item 4 - gateway-poll-worker-role
- Deliverable: `services/workers/neurosphere_workers/ingestion/gateway_poll/` worker role: reads registered gateways (item 6 store) with a workspace id, runs the connector (item 3) over a bounded window with the watermark rule, posts batches to the ingest API as producer `apim-gateway-poll` (`sources: ["gateway"]`), records freshness and coverage per poll on the gateway record, and refuses Government workspaces without `allow_unverified_government`. Replay test proves zero duplicate ledger entries.
- Owned files (may edit): `services/workers/neurosphere_workers/ingestion/gateway_poll/` (new), `services/workers/tests/gateway_poll/` (new), `services/workers/pyproject.toml` (connector dependency if missing), the producers fixture file named by `ingest/settings.py:34-35`.
- Must NOT touch: `ingest/service.py`, `ledger/`, connector package.
- Depends on: items 3, 6.
- Acceptance criteria: item 4 above.
- Pattern references: `ingestion/models.py:43` dedupe; PRP-09 Azure Monitor poll slice and watermark rules; `ingest/auth.py:35-50`.

### Item 5 - grant-and-mcp-server-contracts  (model: opus, review: required)
- Deliverable: `packages/contracts/schemas/catalog/v1/grant.schema.json` (fields: `id`, `principal` {`kind`: user | application | agent | entra_group, `object_id`, `display`}, `target` {`kind`: model_api | model_deployment | mcp_server, `ref`}, `limits` {`tokens_per_minute`, `token_quota`, `quota_period` minute | hour | day | week | month | year, `requests_per_minute`, `mcp_calls_per_minute`}, `cost_center`, `enabled`, `valid_from`, `valid_until`, `version`, `provenance`); `mcp_server.schema.json` (fields: `id`, `name`, `url` streamable-http ending in `/mcp`, `transport`, `protocol_versions`, `auth` {`kind`: entra | managed_identity | none, `audience`}, `tools` [{`name`, `description`, `annotations`}], `owner`, `domain`, `version`, `provenance`; API-key upstreams are representable but flagged `publishable: false`); `EntityType` + `grant`, `mcp_server`; `RelationType` + `grants_access_to`; generated Python and TS; canonical id grammar `grant:<domain>:<slug>`, `mcp_server:<domain>:<slug>`; golden fixtures; core protocol literals and caps (13 and 10); permissions `grant.read`, `grant.write`; a contract conformance test proving an MCP grant with token limits is invalid (MCP grants are call-limited only).
- Owned files (may edit): `packages/contracts/schemas/catalog/v1/grant.schema.json`, `.../mcp_server.schema.json`, `.../common.schema.json` (enum additions), generated `packages/contracts/python/neurosphere_contracts/catalog/v1/*.py`, `packages/contracts/ts/src/catalog/v1/*.ts`, `tests/contracts/fixtures/catalog/`, `tests/contracts/test_canonical_ids.py`, `tests/contracts/validators.py`, `packages/core/neurosphere_core/catalog/protocol.py` (literals and caps only), `packages/core/neurosphere_core/auth/scope/permissions.py`.
- Must NOT touch: any other contract family; catalog store implementations; routers.
- Depends on: none.
- Acceptance criteria: item 5 above.
- Pattern references: `catalog/v1/common.py:147-200`; `alias.py:63-75`; `validators.py:36-42`; `test_drift.py`; `permissions.py:59-72`.

### Item 6 - gateway-registry-observe
- Deliverable: `packages/core/neurosphere_core/gateway/` (models `GatewayRegistration` {arm id, cloud, tier, mode = observe, workspace id, diagnostics state, last sync, freshness, coverage}, `GatewayInventory` snapshot, store protocol, Cosmos + in-memory stores) and `services/api/neurosphere_api/gateway/` router: `POST /domains/{domain}/gateways` (register, read-only preflight, `deploy.write`), `GET` list/detail (`deploy.read`), `POST .../sync` (rebuild inventory). Inventory reads via item 2 ARM client: service (`sku.name` to tier, matrix lookup via item 1), diagnostic settings categories, APIs, operations, products, backends with `pool.services` and `circuitBreaker.rules`, policy fragment names, subscription ids. No `listSecrets`, no named-value values, no policy XML bodies stored. Route inventory and OpenAPI regenerated.
- Owned files (may edit): `packages/core/neurosphere_core/gateway/` (new), `packages/core/tests/gateway_core/` (new), `services/api/neurosphere_api/gateway/` (new), `services/api/tests/gateway_api/` (new), `services/api/neurosphere_api/routers.py` (one registration line), `services/api/openapi.json` (regenerated), `tests/integration/gateway/test_registry_cosmos.py` (new, emulator).
- Must NOT touch: `deploy/`, `actions/`, `mcp/`, frontend.
- Depends on: items 1, 2, 5.
- Acceptance criteria: item 6 above; a security test asserts the ARM client stub saw only GET calls.
- Pattern references: `actions/cosmos_store.py`; PRP-17 wire contract; `deploy/scan/graph.py:27,79`; `test_route_inventory.py:33-44`.

### Item 7 - gateway-and-catalog-ui
- Deliverable: Gateways list and detail pages (tier, mode badge, diagnostics state, last sync, freshness, inventory tables); Grant and McpServer entity renderers and the `grants_access_to` edge in the catalog pages shipped by PRP-31; route manifest and workspace nav entries; mock API fixtures; Vitest + one Playwright spec per page; a11y check.
- Owned files (may edit): `frontend/src/pages/gateways/` (new), `frontend/src/pages/catalog/` (renderers only, additive), `frontend/src/app/route-manifest.json`, `frontend/src/app/workspaceNav.ts`, `frontend/tests/mock-api/server.ts` (gateway and catalog fixtures), `frontend/tests/e2e/gateways/` (new), `frontend/src/api/gateway.ts` (new, generated from `openapi.json`).
- Must NOT touch: design system, other pages, backend.
- Depends on: items 5, 6 (OpenAPI).
- Acceptance criteria: item 7 above.
- Pattern references: PRP-31 page layout and its mock fixtures; Fluent dialog test note (use `hidden: true`, memory).

### Item 8 - g17-observe-live-gate
- Deliverable: `scripts/gates/g17_apim_observe_live.py` (refusal, create Standard v2 + Log Analytics workspace in a throwaway resource group tagged `neurosphere:created-by`, enable `GatewayLogs` and `GatewayLlmLogs`, import one LLM API against the approved Foundry endpoint using managed identity, send one chat completion, poll the connector (item 3) until the joined row appears or a 20-minute budget expires, register the gateway through item 6 and sync, write evidence, teardown through the register guard); `docs/evidence/G17/README.md`; G17 row added to `docs/RESEARCH-AND-GATES.md` (OPEN until run); unit tests for refusal and tokenisation.
- Owned files (may edit): `scripts/gates/g17_apim_observe_live.py` (new), `tests/unit/gates/test_g17_observe.py` (new), `docs/evidence/G17/` (new), `docs/RESEARCH-AND-GATES.md` (new G17 row only).
- Must NOT touch: `infra/bicep/` (the script uses ARM REST and `az` as `g01_deploy_smoke.py` does, not the Bicep module, because `apim.bicep` does not allow v2 SKUs until PRP-34).
- Depends on: items 3, 6.
- Acceptance criteria: item 8 above. The live run is operator-approved per step (D7); if not run, the completion note says OPEN with the reason.
- Pattern references: `g01_deploy_smoke.py:3-17, 143-188, 240, 804-807`; `g01_analytics_live.py:251` evidence dir; memory notes on `uv run` + `MSYS_NO_PATHCONV`, Limitlessdata-only targets and DMLZ private Cosmos.

## Validation gates
```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/run-tests.ps1 -Fast
uv run pytest tests/unit/capabilities tests/contracts packages/core/tests/cloud packages/core/tests/clients packages/core/tests/gateway_core services/api/tests/gateway_api services/api/tests/authz services/workers/tests/gateway_poll connectors/reference/azure-monitor tests/unit/gates -q
uv run python packages/contracts/scripts/generate.py --check
uv run ruff check . && uv run pyright
pnpm --filter contracts test && pnpm --filter frontend test && pnpm --filter frontend exec playwright test tests/e2e/gateways
docker compose up -d --wait && uv run pytest -m integration tests/integration/gateway -q
python scripts/validate_planning.py
# Live (operator-approved only): NS_LIVE_APPROVED=1 uv run python scripts/gates/g17_apim_observe_live.py --subscription <id> --location centralus
```
Full suite runs in CI. Live gate reported OPEN when it did not run.

## Live and open gates
- G17 (new): APIM gateway observe, Commercial. OPEN until item 8 runs with operator approval. Government: OPEN (no subscription, D7; v2 tiers `unverified` there).
- G01: narrowed by item 1 rows (documentation-derived); not closed.
- G04: narrowed if item 8 runs (first live Azure Monitor contract result for the APIM kinds); not closed for the other kinds.

## NOT building
- Any write to a gateway (PRP-34): no policy, product, backend, subscription or diagnostic-setting writes outside the throwaway live-gate script.
- Grant enforcement, MCP publication, budget enforcement, model swap through APIM (PRP-34).
- Prompt or completion logging; request or response body capture.
- Pricing of Government gateway rows; any Retail Prices fallback.
- A MOSAIC-style end-user portal or separate Entra app registration.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

Plan approved 2026-10-29 with one delta signed off by the operator:

- D2 (2026-10-29, item 3): `CostRecord.amount` and `currency` are required by the shipped cost contract, so an unpriced gateway row cannot be a `CostRecord`. Token counts already live on `TelemetryEvent`. Resolution: the APIM gateway source emits one `TelemetryEvent` per `CorrelationId` carrying tokens, model, deployment, latency and success; the connector-local `GatewayCostObservation` (CostRecord field names, amount null, `observation_source: gateway`) is the typed row for later pricing and is NOT posted to ingest. Item 3 acceptance "one TelemetryEvent plus one CostRecord" is replaced by "one TelemetryEvent plus one GatewayCostObservation". Item 4 posts telemetry only. Pricing of gateway tokens into estimated `CostRecord`s through the PRP-15 price sheets is a follow-up (not this PRP).
- D3 (2026-10-29, item 6): `deploy.read` / `deploy.write` named in item 6 do not exist in the permission enum; the deploy scan and plan routes use `config.manage` (writes) and `data.read` (reads), so the gateway routes do the same and no permission is added here. Item 6 also found that nothing in the runtime composition root builds the gateway plane (routes answer 503 `gateway_plane_unconfigured` until wired), so a new **item 9 api-runtime-gateway-builder** is added: `services/api/neurosphere_api/runtime/builders/gateway.py` plus registration in `default_builders`, the `gateways` container in the stores registry, and `services/api/tests/runtime_gateway_builder/`; depends on item 6; sonnet; review none.
- D1: PRP-31 (dependency) is active at 0 of 8 items. Items 1-6 and 8 run now; item 7 (Gateways page, catalog renderers; shares `route-manifest.json`, `workspaceNav.ts` and `mock-api/server.ts` with PRP-31) stays `todo` until PRP-31 ships. If PRP-31 has not shipped at close-out, item 7 is descoped to a follow-up issue and this PRP closes without the UI. Integration branch `prp-33-apim-gateway-observe` is cut from `main` (not from the PRP-31 branch).

| Item | Status | Branch / worktree | Model | Evidence | Updated |
|---|---|---|---|---|---|
| 1 | merged | worktree-agent-a69e4bd8b9d1b0abd | sonnet | 65 passed (capabilities + matrix contract), ruff/pyright clean on branch and post-merge; 112 rows (matrix 534 -> 646); 05fc8c3, merge 0859b97 | 2026-10-29 |
| 2 | merged | worktree-agent-ab24fd5690eaf7c0b | sonnet | 81 passed (cloud, clients, profile), 224 passed services -k cloud/profile/runtime post-merge; ruff/pyright clean; 6d5b26c, merge 11b009a | 2026-10-29 |
| 3 | merged | worktree-agent-a8a3ee10ace95fae5 | sonnet | 39 passed connector suite on branch, 140 passed post-merge; KQL body-column grep = 0; ruff/pyright clean; validate_planning PASS; 4e12cd9, merge 8fdbee3 | 2026-10-29 |
| 4 | merged | worktree-agent-a81699dd472bbbe1f | sonnet | 68 passed gateway_poll + worker_roles on branch; 405 passed full worker suite post-merge; drift + gateway_api + gateway_core 58 passed; ruff/pyright clean; gateway_poll is opt-in (not in `all`); openapi.json regenerated for poll fields; `.env.example` NOT updated (lane denied on that path, operator to add NS_GATEWAY_POLL_* names); 208d34c, merge (see git log) | 2026-10-29 |
| 5 | merged | worktree-agent-a09f858a868960b78 | opus | review APPROVE (one pass, no blockers; follow-up: structured-query contract enum still lists 12 entity types); merge + openapi regen: drift/authz/contracts/catalog/search 2185 passed; generate --check OK; tests/contracts + core catalog/auth 2306 passed; authz 150 passed; TS 118 passed; ruff/pyright clean; Snyk 0 issues; openapi.json regenerated at merge; ownership extended to search/protocol.py, catalog/router.py cap, CatalogEntity/CatalogEdge unions; a21d2bc | 2026-10-29 |
| 6 | merged | worktree-agent-abed72718b8c8e3ce | sonnet | 58 passed core+api+drift on branch, integration 5 passed (emulator), 221 passed post-merge incl. authz; repo-wide ruff clean; review APPROVE (follow-ups: ARM id regex allows `..` RG, single-document inventory size, log swallowed failures); 6879982, merge 46ecf33 | 2026-10-29 |
| 7 | descoped | | sonnet | per D1: PRP-31 still active at close-out; filed as follow-up issue #147 (other follow-ups in #148) | 2026-10-29 |
| 8 | merged | worktree-agent-ab13d387444352ac5 | sonnet | 6 new G17 tests, 322 passed tests/unit/gates post-merge; refusal verified exit 2 with no az call; ruff/pyright clean; validate_planning PASS; G17 row added; live run NOT RUN (G17 OPEN); 81440c2 | 2026-10-29 |
| 9 | merged | worktree-agent-a0a2d015cdc6f3029 | sonnet | added per D3; 744f497 + rework 911bd14 (`gateways` in stores CONTAINERS, cosmos-containers.json regenerated, container count 27 -> 28, NS_GATEWAY_STORE=auto always Cosmos); 113 passed builder/gateway_api/drift/hosted_demo/stores_registry on branch; ruff/pyright clean; builder order authz, data, planes, copilot, mcp, gateway, edge; merge faf4078; real-stack integration run recorded below | 2026-10-29 |

Waves: 1 = items 1, 2, 3, 5 in parallel; 2 = item 6 (after 1, 2, 5); 3 = items 4, 8, 9 in parallel (after 6; items 4 and 8 also after 3); item 7 parked per D1. Models: item 5 opus; all others sonnet; verify passes haiku. Review: one independent pass on items 5 and 6; other items need review only if the reviewer of 6 flags a shared concern.

## Completion note (filled at ship)
