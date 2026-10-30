---
name: prp-34-apim-gateway-manage
status: active
review: required
priority: P1
order: 2
created: 2026-10-29
started: 2026-10-29
branch: prp-34-apim-gateway-manage
model: opus
phase: 6
ns: NS-04, NS-06, NS-07, NS-08, NS-09
depends_on: PRP-08, PRP-17, PRP-22, PRP-33
wave: W10
absorbs: new (APIM AI gateway manage side; patterns from microsoft/mosaic-apim, MIT, patterns only)
---

# PRP-34: APIM AI gateway, manage side

## Goal
Give the action executor a real APIM write connector so that a model swap, a budget cap and an MCP publication are actual, audited, reversible changes on the gateway instead of advisory intents. A registered gateway (PRP-33) can be switched to manage mode only after a preflight proves write access; every change is a deterministic plan with a digest, applied in dependency order with existence re-read before each write, ownership recorded at write time, rollback that deletes only what the run created, and verification by reading the gateway back. Grants (PRP-33 contract) are enforced as APIM products, subscriptions or Entra-validated policy fragments carrying `llm-token-limit` and `llm-emit-token-metric`; catalog MCP servers are published as Entra-only passthrough MCP APIs with caller credentials stripped; NeuroSphere's own MCP server can optionally sit behind the same gateway in Bicep and Helm. It is Opus work with required review because it is a privileged write path against a shared enterprise resource. It lands in W10 after PRP-33.

> NS-04: maker-checker on executable change. NS-06: same executor for buttons, chat, REST and MCP; recheck permission, bind confirmation to target/version/diff, audit before and after, canary, rollback, emergency disable. NS-07: shared resources are never modified without owner consent; ownership recorded. NS-08: scoped privilege, no bypass. NS-09: MCP servers governed through the gateway.

Binding contract from `PRP.md` section 3 (action states and intent fields) applies unchanged; this PRP adds a connector, not a second executor.

## Acceptance criteria
- [ ] Item 1: `dry_run` on the APIM connector returns a `PublishPlan` with ordered steps (named value only for key-authenticated backends, backend, policy fragment, API, operations, API policy, product, product-API link, subscription) and a SHA-256 digest over intent facets; `apply` refuses a plan whose digest or step order no longer matches, re-reads existence before each write, refuses to overwrite a resource it expected to create, records `created` or `found` per step, and on failure reverses completed steps deleting only `created` resources; a failed rollback reports `rollback_failed` with the orphan list; `verify` reads every planned resource back; `rollback` of a succeeded apply runs the reverse plan; the connector never calls `listSecrets` and never logs policy XML containing named-value references.
- [ ] Item 2: Switching a gateway to `manage` requires a preflight that proves the service identity holds `Microsoft.ApiManagement/service/write` and child writes at the gateway scope (permissions API), is refused while an apply, rollback or unpublish is running, is audited, and leaves published resources serving when switched back to `observe`, after which plan, apply and unpublish are refused with `capability_unavailable` reason `gateway_observe_mode`; a reused instance from `apim.bicep` is registered in `observe` and never flips to `manage` without this explicit, audited switch.
- [ ] Item 3: `model_deployment_swap` against an `apim_backend` target changes the backend URL or shifts backend-pool weights; canary is a real weight shift (for example 10 percent) followed by a gateway read-back and, when diagnostics are enabled, one gateway log row for the new backend within the probe window; verify compares the backend document to the proposed diff; rollback restores the captured prior document; the Foundry connector mapping is unchanged; against a gateway in observe mode the intent is advisory and nothing is changed anywhere.
- [ ] Item 4: `budget_cap_change` against a `grant` target rewrites the grant's policy fragment `llm-token-limit` attributes (`tokens-per-minute`, `token-quota`, `token-quota-period`) and is otherwise identical in lifecycle to item 3 (dry-run diff of the fragment, apply, verify by read-back, rollback to prior fragment); `llm-emit-token-metric` carries dimensions `API ID`, `Subscription ID` and `x-ns-cost-center` (header, default `N/A`) so cost-center attribution shows up in the PRP-33 gateway observation; a grant whose target is an MCP server refuses token limits.
- [ ] Item 5: Publishing a Grant creates (through item 1) a product, a product policy fragment and either a subscription (key-authenticated principal, key never returned by NeuroSphere) or a `validate-azure-ad-token` block matching the principal `oid` or `groups` claim; counter keys are the subscription id or the `oid`; unpublish runs the reverse plan; the catalog Grant records the publication (gateway id, resource names, ownership) in `provenance`; publication is an action intent (maker-checker applies).
- [ ] Item 6: Publishing a catalog McpServer creates a backend (URL without the trailing `/mcp`), a passthrough MCP API, an enforcement fragment that validates Entra tokens for the configured audience, strips `Authorization`, `Ocp-Apim-Subscription-Key`, `api-key` and `subscription-key` before forwarding, attaches the gateway managed identity when the server auth kind is `managed_identity`, applies `rate-limit-by-key` per grant, and a protected-resource-metadata operation at `/.well-known/oauth-protected-resource/{path}/mcp`; backend changes and unpublish write a deny policy first and never auto-restore on failure; SSE-only and API-key upstreams are refused with reason; the policy never reads bodies (streaming unbuffered).
- [ ] Item 7: `apim.bicep` allows `BasicV2`, `StandardV2`, `PremiumV2` in addition to the classic SKUs; an optional `apim-diagnostics.bicep` module writes `GatewayLogs`, `GatewayLlmLogs` and `GatewayMCPLogs` to the deployment's Log Analytics workspace only for a created instance (never a reused one); an optional `apim-mcp-front.bicep` module and Helm value `mcp.apimFront.enabled` (default false) publish NeuroSphere's own MCP server through the gateway with the item 6 policy; `bicep build`, lint and the endpoint-literal test pass for both clouds.
- [ ] Item 8: The action confirmation dialog shows the APIM plan steps and per-step `create` or `found` expectations; the gateway page has an audited observe/manage switch with the preflight result; a Grant and an McpServer get Publish and Unpublish buttons that draft action intents through the existing action API (no new executor path); Playwright covers plan preview and the mode switch.
- [ ] Item 9: `scripts/gates/g17_apim_manage_live.py` refuses without `NS_LIVE_APPROVED=1`; when approved it provisions a throwaway Standard v2 APIM, registers it, switches to manage, publishes a Grant, performs a backend swap with canary, a cap change and an MCP publication against a throwaway streamable-HTTP MCP backend, unpublishes everything, confirms the gateway is back to the pre-run inventory, and tears down; evidence under `docs/evidence/G17/manage-<date>.{md,json}` with subscription tokenised; G17 manage reported OPEN when not run.
- [ ] PRP exit: items 1-9 green under `verify-gates -Mode full`; reviewer verifies no code path edits catalog metadata as a stand-in for a gateway change, that only the worker executor calls `apply` and `rollback` (PRP-17 D5 test extended), and that no secret is returned, stored or logged; G17 manage status recorded; threat-model gap at lines 100 and 347 closed or re-stated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Split | two; one; three | Second of two PRPs; depends on PRP-33 contracts, registry and ARM client |
| 2 | Priority | P1 W10; P2; P0 | P1, W10, after PRP-33 |
| 3 | Live gate target | throwaway Standard v2; reuse Loom observe only; none | Throwaway Standard v2 in Limitlessdata, created and destroyed by the gate script, `NS_LIVE_APPROVED=1` plus per-step approval. The reused Loom APIM is never a manage-mode target |
| 4 | Grants model | no new entity; grant contract | Grant contract (PRP-33 item 5) is the enforcement unit: product + subscription or Entra-validated fragment |
| 5 | Own MCP server behind APIM | yes optional; customers only | Yes, optional, off by default, item 7 |
| 6 | Reuse from MOSAIC | patterns only; vendor | Patterns only: plan digest, dependency order, existence re-read, ownership at write time, reverse rollback, deny-first on MCP changes, credential stripping. Policy XML is written against Learn |
| 7 | Model and review | sonnet; opus | opus, review required (D6: privileged write path, rollback correctness) |
| 8 | Canary | verify-only as PRP-17; real weight shift | Real weight shift through backend-pool weights when the target is a pool; a single backend swaps atomically with verify-only canary and says so in evidence |
| 9 | Who may switch to manage | any `deploy.write`; admin only | `deploy.write` plus the gateway's domain scope plus a successful preflight; the switch is itself an audited action with maker-checker when policy requires |
| 10 | Which action kinds | new kinds; reuse existing | Reuse `model_deployment_swap` (new target kind `apim_backend`) and `budget_cap_change` (target kind `grant`); add `grant_publish`, `grant_unpublish`, `mcp_server_publish`, `mcp_server_unpublish` |

## Context manifest

### Files that matter
- Everything in PRP-33's manifest, plus:
- Action executor: `packages/core/neurosphere_core/actions/state_machine.py:47-68` (allowlist), `models.py:69-84` (phases; `CanaryOutcome.verify_only` at 84), `hashing.py:97-127` (confirmation hash), `service.py:430` (`apply_approval`), `:655-680` (`finish_execution`), `:769-781` (`_refuse_advisory`), `:830` (`_check_enabled`), `control.py:38-57` (emergency state), `audit.py:44-60, 77, 138`, `recheck.py:65`, `targets.py:28-33` (`ACTION_CONNECTORS`, the one table from action kind to connector manifest name).
- Action API: `services/api/neurosphere_api/actions/router.py:67-79` (permissions), `:98-210` (routes), `dependencies.py:97` (`connector_for`), `emergency.py:37-74`.
- Action contract: `packages/contracts/python/neurosphere_contracts/actions/v1/action_intent.py:100-110` (evidence kinds), `:150-152` (`action_kind` free snake_case; advisory rule).
- Write connector SDK: `connectors/sdk-python/neurosphere_connector/write/write_protocol.py:23-46` (`manifest`, `advisory`, `dry_run`, `apply`, `verify`, `rollback`; no canary), `write_registry.py:29-57`. Reference connector: `connectors/reference/foundry-actions/.../connector.py:75-76, 89-100, 107-112` (Government refusal), `:127` (write class), `:276` (verify), `:295` (rollback), `:325-340` (`create_swap_connector`); `endpoints.py:55-61` (ARM hosts and scopes).
- PRP-17 execution deltas: `PRPs/shipped/PRP-17-action-executor-and-hitl.md:236-246` (D1 hash, D3 error reasons, D4 canary as executor phase with pluggable `CanaryProbe`, D5 only the worker calls `apply`/`rollback`, repo-wide test).
- Register and guard: `packages/core/neurosphere_core/deploy/register/models.py:23-27` (`Ownership`), `:58` (`ResourceRow`); `guard.py:73, 81-103, 151`; `infra/scripts/uninstall.py:182-186, 232-243`.
- MCP own server: `services/api/neurosphere_api/mcp/server/__init__.py:1-21` (mount `/mcp`; PRM at `/.well-known/oauth-protected-resource/mcp`), `factory.py:441-519` (`create_mcp_server`, issuer 464, `authorization_servers` 504), `settings.py:8-10, 61` (audiences); `client/connector.py:20, 131-136` (no credential passthrough).
- Bicep and Helm: `infra/bicep/modules/apim.bicep:6-53`, `main.bicep:40-46, 117-125, 163`; `infra/bicep/params/{commercial,government}/main.bicepparam`; `government/sovereign-profile.yaml:14-59, 24, 90`; `infra/helm/values.yaml` (no APIM key), `values-government.yaml:43, 60`; tests `tests/unit/infra/test_bicep_build.py` (skips without `az`), `test_bicep_endpoints.py:20,110`, `test_helm_render.py`, `tests/unit/government_profile/`.
- Threat model: `docs/security/threat-model.md:100, 231, 347`.
- Frontend action UI from PRP-17 item 6 and PRP-31 pages; `frontend/tests/mock-api/server.ts` action fixtures.

### Patterns to match
- Connector shape: `foundry-actions/.../connector.py` end to end (manifest, advisory flag mirrored from the matrix, Government refusal, `dry_run` returning a diff against `target_version`, `apply` returning an `ApplyResult` with captured prior state, `verify` via `build_verify_result` from a real read, `rollback` from `ApplyResult`).
- Executor phases: PRP-17 D4 (recheck, dry_run, audit before, apply, canary probe, verify, audit after). The APIM connector supplies a `CanaryProbe` that shifts pool weight and reads back; it does not add phases.
- Error reasons: PRP-17 D3 taxonomy; new reasons are strings under existing codes (`capability_unavailable` reason `gateway_observe_mode`, `stale_version` reason `plan_digest_mismatch`, `dependency_transient` for ARM 429 with `Retry-After`).
- Ownership: `deploy/register/models.py` rows with `Ownership` created vs found; the guard refuses deletes of anything not recorded `created`.
- Bicep optional module: `main.bicep:117-125` module wiring with `reuse` short-circuit; `output created bool`.
- Policy XML authored as string templates in a `policies/` package with a test that renders every fragment and parses it as XML; named values referenced as `{{name}}` only.

### Conventions
- As PRP-33, plus: only `services/workers` executor may call `apply` and `rollback` (extend the PRP-17 D5 repo-wide test to the new connector).
- Every ARM write carries `If-Match` from the preceding read when the resource exists; a `412` maps to `stale_version`.
- Plan and apply records are append-only in the gateway store; a plan is immutable once reviewed.

### Gotchas
- A reused APIM (`apim.bicep` `reuse` set) is enterprise-owned: registering it in observe mode is fine, but manage mode requires the explicit audited switch and a preflight that proves the service identity was granted write by the owner. Never assume the deployer's own rights.
- Creating the policy fragment before the backend fails on a real gateway (MOSAIC ADR-0010 finding); the step order in item 1 is load-bearing.
- New APIs require a subscription until their policy is in place; MCP backend changes and unpublish must write a deny policy first (fail-closed ordering, MOSAIC ADR-0017).
- `llm-token-limit` counters are per gateway and per `counter-key`; using the same key at product and API scope with different `tokens-per-minute` values is undefined on v2. One scope per grant.
- `llm-emit-token-metric` allows at most 5 dimensions and runs inbound only; custom metrics in Application Insights are a preview feature needing `"metrics": true` on the APIM diagnostic entity.
- `ApiManagementGatewayLlmLog` token counts come from the model response; refused (429, 403) calls log no tokens, so a cap change cannot be verified from tokens alone; verify by fragment read-back.
- MCP: only streamable-HTTP upstreams; backend URL must end in `/mcp` and have no query string; Entra `groups` overage omits the claim, so group grants fail closed and need a direct grant; the shared PRM API refuses publication if another API already owns the blank path.
- The PRM path for NeuroSphere's own server is already `/.well-known/oauth-protected-resource/mcp` (`mcp/server/__init__.py`); fronting it with APIM must keep the resource identifier equal to the gateway URL or MCP clients reject the metadata.
- The `budget_cap_change` kind exists only as a string in the contract description; no connector, no target kind. Item 4 adds both; nothing may edit the Grant document to "simulate" the cap.
- Government: `.azure-api.us` suffix from `CloudProfile` (PRP-33 item 2); v2 tiers `unverified` in Government, so manage mode in a Government profile is disabled with reason until the matrix row changes.
- Repo-wide pyright runs in CI; `union()` hides Bicep schema errors (memory); use `az bicep build` locally.
- Playwright: unique ports per worktree; Fluent dialogs need `hidden: true` in tests.

### External references
- Backends, pools, weights, priority groups, circuit breaker with `Retry-After` trip duration: https://learn.microsoft.com/azure/api-management/backends#load-balanced-pool and https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities#resiliency
- Backend ARM schema (`type: Pool | Single`, `pool.services[].weight|priority`, `circuitBreaker.rules`): https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2025-03-01-preview/service/backends#property-values
- `set-backend-service` policy: https://learn.microsoft.com/azure/api-management/set-backend-service-policy
- Policy fragments ARM schema (`format: rawxml | xml`): https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2024-05-01/service/policyfragments#resource-format
- `llm-token-limit` statement, attributes, usage notes 4-6: https://learn.microsoft.com/azure/api-management/llm-token-limit-policy
- `llm-emit-token-metric` dimensions and example with `x-user-id` header: https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities#observability-and-governance
- Custom metrics diagnostic entity `"metrics": true`: https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights#emit-custom-metrics
- `validate-azure-ad-token`: https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy
- Secure MCP servers in APIM (key and Entra inbound, header forwarding): https://learn.microsoft.com/azure/api-management/secure-mcp-servers
- Expose an existing MCP server and programmatic management: https://learn.microsoft.com/azure/api-management/mcp-server-overview#expose-mcp-servers-in-api-management
- Secure an MCP server with Entra and protected resource metadata (RFC 9728): https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id
- Import a language model API (what APIM creates: backend + `set-backend-service`, optional named value): https://learn.microsoft.com/azure/api-management/openai-compatible-llm-api
- Diagnostic settings for `GatewayLogs`, `GatewayLlmLogs`, `GatewayMCPLogs`: https://learn.microsoft.com/azure/api-management/monitor-api-management-reference#resource-logs
- v2 tiers (API version 2024-05-01 or later): https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview
- MOSAIC pattern sources (shape only): `docs/adr/0010-publishing-models-into-apim.md` (write order, digest, ownership, rollback, rejected alternatives), `docs/adr/0017-mcp-gateway-enforcement.md` (deny-first, credential stripping, PRM, limitations), README "Gateways" (observe and manage modes).

## Implementation blueprint

### Item 1 - apim-write-connector-core  [P]
- Deliverable: `connectors/reference/apim-gateway/` implementing `WriteConnector` with a `PublishPlan` model (`steps[]` {resource type, name, expected `create|found`, payload digest}, `digest`, `gateway_id`, `target_version`), a planner (dependency order from the acceptance criteria), an applier (existence re-read, `If-Match`, ownership record per step, reverse rollback on failure, orphan report), `verify` by read-back, `rollback` by reverse plan; a `policies/` package with fragment templates (grant product fragment with `llm-token-limit` + `llm-emit-token-metric`, MCP enforcement fragment, deny fragment) and an XML-parse test for each; an APIM test double (in-memory ARM resource tree with ETags) used by all unit tests; manifest declares `model_deployment_swap`, `budget_cap_change`, `grant_publish`, `grant_unpublish`, `mcp_server_publish`, `mcp_server_unpublish`.
- Owned files (may edit): `connectors/reference/apim-gateway/` (new, package + tests + README), `docs/connectors/coverage.md` (one row), root `pyproject.toml` uv source entry.
- Must NOT touch: `packages/core`, `services/`, `infra/`.
- Depends on: none (uses PRP-33 ARM client interface).
- Acceptance criteria: item 1 above.
- Pattern references: `foundry-actions/.../connector.py`; `write_protocol.py:23-46`; `deploy/register/models.py:23-27`.

### Item 2 - manage-mode-switch-and-preflight
- Deliverable: gateway store gains `mode`, `mode_changed_by`, `mode_changed_at`, `preflight` result; `POST /domains/{domain}/gateways/{id}/mode` drafts an action intent of kind `gateway_mode_change` (maker-checker per policy) whose connector step runs the permissions preflight (`Microsoft.Authorization/permissions` at the gateway scope, required actions listed in the item) and flips the mode; refusal while any plan is `applying`; `ACTION_CONNECTORS` gains the six kinds plus `gateway_mode_change` mapped to `apim-gateway`; a new target kind `apim_backend` and `grant` in `actions/targets.py` resolution; observe-mode refusal reason `gateway_observe_mode` in `dependencies.py:97` connector resolution.
- Owned files (may edit): `packages/core/neurosphere_core/gateway/` (models, store; additive), `packages/core/neurosphere_core/actions/targets.py`, `services/api/neurosphere_api/gateway/router.py` (mode route), `services/api/neurosphere_api/actions/dependencies.py` (observe-mode check), `packages/core/tests/gateway_core/`, `services/api/tests/gateway_api/`, `services/api/openapi.json` (regenerated).
- Must NOT touch: `actions/service.py`, `state_machine.py`, `hashing.py`, connector package.
- Depends on: item 1.
- Acceptance criteria: item 2 above; PRP-17 D5 repo-wide test extended to `apim-gateway`.
- Pattern references: `actions/targets.py:28-33`; `router.py:67-79`; `audit.py:44-60`; `control.py:38-57`.

### Item 3 - model-swap-via-backend
- Deliverable: `apim_backend` target handling in the connector: single backend URL swap (atomic; canary `verify_only`, stated) and pool weight shift (canary = configurable initial weight, probe reads pool back and, when the gateway has `GatewayLogs` enabled, queries PRP-33's connector for one row with the new `BackendId` within the probe window; absence is a canary failure); `CanaryProbe` implementation registered with the executor; prior backend document captured for rollback; `target_version` is the backend ETag.
- Owned files (may edit): `connectors/reference/apim-gateway/` (swap module + tests), `services/workers/neurosphere_workers/action_executor/` (probe registration only), `services/workers/tests/action_executor/test_apim_canary.py` (new).
- Must NOT touch: Foundry connector; executor phases.
- Depends on: items 1, 2.
- Acceptance criteria: item 3 above.
- Pattern references: PRP-17 D4; `foundry-actions/.../connector.py:276, 295`.

### Item 4 - budget-cap-change-connector
- Deliverable: `grant` target handling for `budget_cap_change`: dry-run renders the new fragment and diffs attributes; apply PUTs the fragment with `If-Match`; verify parses the fragment back and compares attributes; rollback restores the captured fragment; MCP-target grants refuse token limits (`invalid_schema` reason `mcp_grant_token_limit`); `x-ns-cost-center` dimension added to the metric template; PRP-33 mapper gains the cost-center dimension on the `CostRecord` when present (additive field already in contract `tags`).
- Owned files (may edit): `connectors/reference/apim-gateway/` (cap module, policy template, tests), `connectors/reference/azure-monitor/` (cost-center tag mapping, one function + test).
- Must NOT touch: pricing, ledger, Grant schema.
- Depends on: item 1.
- Acceptance criteria: item 4 above.
- Pattern references: item 1 planner; `llm-token-limit` usage notes 4-6.

### Item 5 - grant-publish-and-unpublish
- Deliverable: `grant_publish` and `grant_unpublish` kinds: plan builds product, product fragment, subscription (key principal) or Entra-validated fragment (`oid` or `groups`), product-API link to the target API; subscription keys are never read (`listSecrets` absent; the principal retrieves the key from the portal or the operator); unpublish reverse plan; Grant `provenance` records gateway id, resource names and ownership through the catalog store (a catalog write that records a real change, not a stand-in); catalog API exposes Publish and Unpublish as intent drafts.
- Owned files (may edit): `connectors/reference/apim-gateway/` (grant module + tests), `services/api/neurosphere_api/catalog/` (publish draft routes, additive), `services/api/tests/catalog_api/test_grant_publish.py` (new), `services/api/openapi.json`.
- Must NOT touch: Grant schema; executor.
- Depends on: items 1, 2.
- Acceptance criteria: item 5 above.
- Pattern references: PRP-17 wire contract; `actions/router.py:98-210` draft flow.

### Item 6 - mcp-server-publish
- Deliverable: `mcp_server_publish` and `mcp_server_unpublish`: backend (URL minus `/mcp`, managed-identity credential when configured), passthrough MCP API (type `mcp`, streamable HTTP), enforcement fragment (`validate-azure-ad-token` for the configured audience, credential stripping, `authentication-managed-identity` when applicable, `rate-limit-by-key` per matching grant by `oid`), deny fragment written first on change and unpublish, PRM operation on a shared `ns-mcp-metadata` API at `/.well-known/oauth-protected-resource/{path}/mcp` (refuse when the blank path is taken); refusals for SSE-only, API-key upstream, missing audience, query string in URL; catalog McpServer `provenance` records publication; diagnostics note that MCP APIs log zero body bytes.
- Owned files (may edit): `connectors/reference/apim-gateway/` (mcp module, templates, tests), `services/api/neurosphere_api/catalog/` (publish draft routes for McpServer, additive), `services/api/tests/catalog_api/test_mcp_publish.py` (new), `docs/security/threat-model.md` (MCP-through-gateway row and the lines 100/347 gap update).
- Must NOT touch: `mcp/server/`, `mcp/client/`; McpServer schema.
- Depends on: items 1, 2.
- Acceptance criteria: item 6 above.
- Pattern references: `mcp/server/__init__.py:1-21` PRM path; `client/connector.py:131-136` no passthrough; Learn secure-mcp-servers header forwarding.

### Item 7 - bicep-v2-skus-diagnostics-and-mcp-front  [P]
- Deliverable: `apim.bicep` `@allowed` adds `BasicV2`, `StandardV2`, `PremiumV2` with `sku.capacity` rules per tier; `apim-diagnostics.bicep` (created instance only; categories `GatewayLogs`, `GatewayLlmLogs`, `GatewayMCPLogs` to the deployment workspace); `apim-mcp-front.bicep` (off by default; backend to the NeuroSphere API MCP mount, passthrough MCP API, enforcement policy from the same template text as item 6 rendered at build time, PRM operation); Helm `mcp.apimFront.enabled|gatewayHost` values rendered into the API's `NS_MCP_RESOURCE_URL` so the PRM resource identifier equals the gateway URL; params for both clouds; `tests/unit/infra` extended; `docs/AZURE-DEPLOYMENT.md` one paragraph.
- Owned files (may edit): `infra/bicep/modules/apim.bicep`, `infra/bicep/modules/apim-diagnostics.bicep` (new), `infra/bicep/modules/apim-mcp-front.bicep` (new), `infra/bicep/modules/main.bicep` (two module blocks + params), `infra/bicep/params/commercial/main.bicepparam`, `infra/bicep/params/government/main.bicepparam`, `infra/helm/values.yaml`, `infra/helm/values-government.yaml`, `infra/helm/templates/` (API deployment env only), `tests/unit/infra/`, `docs/AZURE-DEPLOYMENT.md`.
- Must NOT touch: `infra/scripts/uninstall.py`, network module, connector, services.
- Depends on: none (template text is duplicated from item 1 by file reference at build time; a test asserts the two copies are byte-identical).
- Acceptance criteria: item 7 above.
- Pattern references: `main.bicep:117-125`; `test_bicep_endpoints.py:20,110`; `sovereign-profile.yaml:24, 90`.

### Item 8 - manage-ui
- Deliverable: plan step preview in the confirmation dialog (steps, expected create/found, digest prefix); gateway observe/manage switch with preflight result and refusal reasons; Publish and Unpublish buttons on Grant and McpServer catalog entities drafting intents; mock API fixtures; Vitest and Playwright specs.
- Owned files (may edit): `frontend/src/pages/gateways/` (manage panel), `frontend/src/pages/actions/` (plan preview component, additive), `frontend/src/pages/catalog/` (publish buttons, additive), `frontend/src/api/gateway.ts`, `frontend/tests/mock-api/server.ts` (fixtures), `frontend/tests/e2e/gateways/manage.spec.ts` (new).
- Must NOT touch: design system; other pages.
- Depends on: items 2, 5, 6 (OpenAPI).
- Acceptance criteria: item 8 above.
- Pattern references: PRP-17 item 6 confirmation dialog; PRP-33 item 7 pages.

### Item 9 - g17-manage-live-gate
- Deliverable: `scripts/gates/g17_apim_manage_live.py`: refusal; provision Standard v2 APIM, workspace, diagnostics, a throwaway MCP backend (Azure Functions or Container App running the sandbox MCP server from PRP-22 fixtures) and the approved Foundry endpoint API; register (PRP-33), switch to manage, publish a Grant, swap backend with pool canary, change a cap, publish the MCP server, call it with an Entra token and confirm credentials were stripped (backend echo of headers), unpublish all, assert the inventory equals the pre-run snapshot, teardown through the register guard; evidence files; G17 row updated (OPEN when not run); unit tests for refusal and tokenisation.
- Owned files (may edit): `scripts/gates/g17_apim_manage_live.py` (new), `tests/unit/gates/test_g17_manage.py` (new), `docs/evidence/G17/`, `docs/RESEARCH-AND-GATES.md` (G17 row only), `PRPs/PRP-MASTER-neurosphere.md` (phase-gate line for W10).
- Must NOT touch: anything else.
- Depends on: items 1-7.
- Acceptance criteria: item 9 above; operator approval per live step (D7).
- Pattern references: `g01_deploy_smoke.py`; PRP-33 item 8 script (shared helpers may be imported from it).

## Validation gates
```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/hooks/run-tests.ps1 -Fast
uv run pytest connectors/reference/apim-gateway packages/core/tests/gateway_core packages/core/tests/actions services/api/tests/gateway_api services/api/tests/actions_api services/api/tests/catalog_api services/api/tests/authz services/workers/tests/action_executor tests/unit/infra tests/unit/gates tests/security -q
uv run ruff check . && uv run pyright
az bicep build --file infra/bicep/modules/main.bicep && az bicep lint --file infra/bicep/modules/main.bicep && helm lint infra/helm && helm template infra/helm -f infra/helm/values-government.yaml > /dev/null
pnpm --filter frontend test && pnpm --filter frontend exec playwright test tests/e2e/gateways
docker compose up -d --wait && uv run pytest -m integration tests/integration/gateway tests/integration/actions -q
python scripts/validate_planning.py
# Live (operator-approved only): NS_LIVE_APPROVED=1 uv run python scripts/gates/g17_apim_manage_live.py --subscription <id> --location centralus
```
Full suite runs in CI. Live gate reported OPEN when it did not run.

## Live and open gates
- G17 manage: OPEN until item 9 runs with operator approval. Government: OPEN (no subscription; v2 tiers `unverified`; manage mode disabled with reason in a Government profile).
- G05: unchanged (Foundry swap); this PRP adds the APIM swap path alongside it.
- G08 (Government MCP): unchanged.

## NOT building
- Model pools as a catalog concept or recommendation (PRP-15 follow-up).
- Semantic caching, content-safety policies, unified model API.
- Cost-center budgets with email alerts (a `budget_cap_change` cap is the enforcement; notifications stay on the PRP-17 `Notifier` stubs).
- Application-owner delegation; dynamic client registration.
- Migration of an existing classic APIM to v2.
- Any write to a reused enterprise APIM outside an explicit, audited manage-mode switch.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

| Item | Status | Branch / worktree | Model | Evidence | Updated |
|---|---|---|---|---|---|
| 1 | merged | worktree-agent-a038917ecafd1995d | opus | merge ed25498; reviewed (1 rework: lost-response restore); connector+infra pytest 154 passed 1 xfailed (enum, item 1b), ruff, pyright | 2026-10-29 |
| 1b | merged | worktree-agent-a8c863d2a544d9dfd | opus | ff to 91af346; reviewed APPROVE (no rework); generate.py --check OK, sdk+apim+foundry-actions pytest 212 passed, licences PASS, pyright/ruff clean | 2026-10-29 |
| 2 | merged | worktree-agent-ab6806e01efffe7f0 | opus | ff to 1f1802b; reviewed APPROVE after 1 rework (permission amended to action.propose, 2 stale tests); 807 pytest passed, openapi drift OK, ruff, pyright. Scope beyond declared files, recorded: apim-gateway connector files (mode handler, arm permissions GET), D5 test, 2 stale tests | 2026-10-29 |
| 3 | merged | worktree-agent-a08e93812d526a67c | opus | merge after 0c0548e; reviewed (1 rework: canary judged within priority group, mode= in grant tests), blockers confirmed fixed by Haiku; worker wiring + 4 item-2 hand-offs done. Merged-head full run 2597 passed (incl. tests/security, tests/unit/infra), ruff, pyright. Unverified live: GatewayLogs BackendId (member vs pool; fails closed either way), weight bound 0..1000 | 2026-10-29 |
| 4 | merged | worktree-agent-ab474c9c3161f4138 | opus | ff to 0ead33d; reviewed APPROVE (no rework); connector+azure-monitor pytest 183 passed, ruff, pyright. OPEN: cost-center attribution in the PRP-33 observation is NOT met (customMetrics not queried, CostRecord has no tags); emit side only. Default translator registration deferred to wiring commit after items 3, 5, 6 | 2026-10-29 |
| 5 | merged | worktree-agent-a53043ceba434b959 | sonnet | merge b53f88e; reviewed APPROVE (no rework); connector+catalog_api+actions_api+authz+openapi drift 318 passed; route inventory test fixed inline (catalog+catalog_api 91 passed). OPEN for wiring step: provenance record endpoint has no caller (criterion not met end to end); `grant` entity type shared with item 4 needs a dispatcher routing by action kind; `app.state.apim_apply_records` unwired in prod | 2026-10-29 |
| 6 | merged | worktree-agent-a8a966c67c4f3e017 | opus | merge 0c0548e; reviewed APPROVE (no rework); deny-first is a separate intent (unpublish needs 2 approvals); merged-head full run 2597 passed. Unverified live: `type: mcp` API shape at 2024-05-01, MCP API with no backendId. OPEN for wiring: record endpoint has no caller | 2026-10-29 |
| 7 | merged | worktree-agent-a99aacda7f4e6981f | sonnet | ff to ee4c771; reviewed (1 rework: diag dependsOn, own-server keeps Authorization), confirmed; infra pytest 62 passed, ruff, bicep build/lint | 2026-10-29 |
| 8 | todo | | sonnet | | |
| 9 | todo | | sonnet | | |

Waves: 1 = items 1 and 7 in parallel; 2 = item 2 (after 1); 3 = items 3, 4, 5, 6 in parallel (after 2; 4 only needs 1); 4 = item 8 (after 2, 5, 6); 5 = item 9 (after 1-7). Models: items 1-4 and 6 opus; 5, 7, 8, 9 sonnet; verify passes haiku. Review: one independent pass on every item (`review: required`).

### Plan deltas (user-approved 2026-10-29)
- Item 1b (new, opus, review required): extend the connector-manifest contract `write_support.actions` enum in `packages/contracts` (regenerate models) and the SDK `WriteAction` type to admit `budget_cap_change`, `grant_publish`, `grant_unpublish`, `mcp_server_publish`, `mcp_server_unpublish`, and regenerate `docs/licenses.md` and `docs/adr/0002-stack-pins.md` for the new workspace member. Remove the strict xfail in item 1's manifest test. Sequenced after item 1, before item 2.
- Decision #9 amended (user, 2026-10-29): `deploy.write` does not exist and the PRP-06 role set is closed. The observe/manage mode switch requires `action.propose` scoped to the gateway domain; maker-checker (a different principal with `action.approve`/`action.execute`) and the Azure-write preflight are the safeguards. Item 2 also updates two tests outside its files that assert the old one-row `ACTION_CONNECTORS` table (`test_planes_builder.py`, `test_review_completion.py`).
- Item 2 review hand-offs (non-blocking, owned by item 3 worker wiring unless noted): when wiring the worker, assert `stored.domain_id == registration.domain_id` for every APIM kind (the generic intents route can name a gateway in another domain of the same customer; `WriteRequest` carries no domain); make `ApimGatewayConnector(mode=...)` required or refuse when absent (today `mode=None` skips the observe guard, fail-open); `PlanApplier.reverse` does not append `applying`, so `running()` misses a rollback; store `_put`/Cosmos create/replace should validate before write. Follow-up issues at close-out: sync audit state hard-codes `"mode": "observe"`; idempotent replay after the mode moved returns `gateway_mode_unchanged`.
- Open hand-off to item 3: the worker composition (durable `ApplyRecordStore`, `GatewayModeHandler`, observe guard) is not wired by item 2, and the worker `resolve_connector` still maps by action kind only, so `apim_backend` swaps would reach Foundry. Item 3 owns that wiring (`services/workers/.../action_executor/`).
- Item 7: the optional own-MCP-server APIM front keeps the `Authorization` header (NeuroSphere's MCP server needs the caller bearer token, `factory.py:283`); it still strips `Ocp-Apim-Subscription-Key`, `api-key`, `subscription-key`. It is therefore a separate policy from the item 6 customer-server template, which still strips `Authorization`. The byte-identity test in the item 7 criteria is replaced by a test of this policy. Env var is `NS_MCP_RESOURCE_SERVER_URL`.

## Completion note (filled at ship)
