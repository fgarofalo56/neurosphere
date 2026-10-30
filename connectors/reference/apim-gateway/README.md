# NeuroSphere APIM gateway write connector (PRP-34 item 1)

Write connector for a registered Azure API Management AI gateway (PRP-33 registration). It turns an
action intent into a deterministic `PublishPlan`, applies it in dependency order with ownership
recorded per step, verifies by reading the gateway back and rolls back by running the reverse plan.
Only the worker executor calls `apply` and `rollback` (PRP-17 D5).

## Module layout

| Module | Holds |
|---|---|
| `models` | `ResourceType`, `DEPENDENCY_ORDER`, `ResourceSpec`, `PlanStep`, `PublishPlan`, `StepRecord`, `ApplyRecord`, `StepOwnership` |
| `digest` | canonical JSON, payload digest, plan digest (SHA-256 over intent facets) |
| `planner` | spec validation, canonical ordering, `build_plan`, `check_plan_integrity` |
| `applier` | `PlanApplier`: per-step re-read, If-Match, ownership records, reverse on failure, `reverse` for rollback |
| `arm` | `ApimArm` protocol and `HttpApimArm` over `neurosphere_core.clients.arm_client` |
| `inmemory` | `InMemoryApim`, the ARM resource-tree test double with ETags and failure injection |
| `records` | `ApplyRecordStore` protocol (append-only) and the in-memory store |
| `translate` | `IntentTranslator` seam per target kind; `GatewayResourcesTranslator` for target `apim_gateway` |
| `policies/` | XML templates (`templates/*.xml`) and renderers |
| `connector` | `ApimGatewayConnector`, `ApimGatewayAdvisoryConnector`, `create_apim_connector` |

Later items add translators (`apim_backend`, `grant`, `mcp_server`) in new modules and register them
with `ApimGatewayConnector.register_translator`; the planner and applier stay shared.

## Plan, digest and binding

- Write order: named value (only for a key-authenticated backend in the same plan), backend, policy
  fragment, API, operations, API policy, product, product policy, product-API link, subscription.
  Deletes run after all upserts, in reverse order, so a deny policy written in the same plan lands
  before anything is removed.
- Each step records `expected` (`create` when absent at plan time, `found` when present), `changes`
  (false when a found resource already contains the payload) and the payload digest. The plan holds
  no payload, so it can be shown and stored without policy XML.
- `dry_run` returns the diff with a leading `test /plan_digest` operation. The diff is part of the
  confirmation hash, so approving binds the exact plan. `apply` re-plans against the live gateway and
  refuses with `stale_version` reason `plan_digest_mismatch` if the digest differs, or
  `invalid_schema` reason `plan_digest_required` if the diff has no digest.
- Generic diff grammar (target `apim_gateway`, version = service ETag): `add`/`replace` at
  `/resources/{relative ARM path with / escaped as ~1}` with the `properties` object as value;
  `remove` at the same pointer deletes.

## Apply, rollback, verify

- Before each write the resource is read again. A resource the plan expected to create that now
  exists is never overwritten (`stale_version` reason `resource_appeared`). Updates and deletes
  carry `If-Match` from that read; `412` is `stale_version` reason `etag_mismatch`.
- After each write the resource is read back and a `StepRecord` (`created` or `found`, ETag after,
  prior properties for found resources) is appended to the record store.
- On failure, completed steps are reversed newest first: `created` resources are deleted using the
  ETag recorded after our write (a resource someone changed since is left and reported); `found`
  resources are restored to their prior properties and never deleted. Failed reversals raise
  `capability_unavailable` reason `rollback_failed` with the orphan list. A create whose response
  was lost and whose resource is present afterwards is reported as an orphan (ownership unknown).
- ARM `429` is retried after `Retry-After` (bounded) and then surfaces as `dependency_transient`
  with `retry_after_seconds`.
- `verify` reads every planned resource back. Observed state is `present`/`matched` booleans only.
  Policy XML is compared after C14N canonicalisation, because APIM re-indents on save.
- `rollback(ApplyResult)` loads the record named by `rollback_token` and runs the reverse plan.

## Secrets

The ARM layer has GET, PUT and DELETE only. `listSecrets`, `listValue`, `listKeys` and
`regenerate*` paths are refused before any request. Subscription keys and named-value values are
stripped from every response and refused in every request body. Named values must be secret Key
Vault references, and backend credentials must reference them as `{{name}}`. Errors carry status
codes, never bodies. Log lines carry step index, operation, type and ownership only.

## Policy templates

`grant-product.xml` (`llm-token-limit` plus `llm-emit-token-metric` with dimensions `API ID`,
`Subscription ID` and `x-ns-cost-center` from the header, default `N/A`), `mcp-enforcement.xml`
(`validate-azure-ad-token` with tenant and audience as named values, credential stripping of
`Authorization`, `Ocp-Apim-Subscription-Key`, `api-key` and `subscription-key`, optional
`authentication-managed-identity`, `rate-limit-by-key` on the token `oid`), `deny.xml`
(`return-response` 503) and `api-policy.xml` (`include-fragment` plus optional
`set-backend-service`). Fragments are submitted as `format: rawxml`. Expression attributes are
single-quoted so every rendered document parses as XML. A test renders every template variant and
parses it.

## MCP server publication (PRP-34 item 6)

`mcp.McpServerTranslator` handles target kind `mcp_server` (the catalog `McpServer`) for
`mcp_server_publish` and `mcp_server_unpublish`. The diff is one `replace /publication` whose
value names the stage (`publish`, `deny`, `change`, `remove`), the gateway and the upstream.
Deny first is a stage of its own, because the shared applier reverses every completed step on
failure: a change or removal is planned only against an API whose policy is the 503 deny
(`target_version` `mcp-denied`), so its reversal restores the deny and never the old enforcement.
Publish creates a backend (URL without `/mcp`), a policy fragment (`policies/templates/
mcp-server-enforcement.xml`: Entra validation with tenant and audience named values, credential
stripping, per-grant `rate-limit-by-key` by `oid` with 403 otherwise, `authentication-managed-identity`
for `managed_identity` servers), an MCP API (`type: mcp`, streamable) routed only by its API policy,
and a PRM operation on the shared blank-path `ns-mcp-metadata` API. It refuses SSE-only, API-key,
audience-less and query-string upstreams, missing named values, an already existing per-server
resource and a blank or API path owned by another API. The path checks need an `ApiPathIndex`
(`HttpApiPathIndex` over ARM, `InMemoryApiPathIndex` for tests); without one publication fails
closed. Not registered by default in this package: pass `translators=[McpServerTranslator(...)]`.
Unverified against a live gateway: the `type: mcp` / `mcpProperties` API shape at api-version
2024-05-01 and whether an MCP API is accepted without a `backendId` (G17 manage OPEN).

## References (Microsoft Learn; not re-fetched while writing this item)

- llm-token-limit: <https://learn.microsoft.com/azure/api-management/llm-token-limit-policy>
- llm-emit-token-metric and dimensions: <https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities#observability-and-governance>
- validate-azure-ad-token: <https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy>
- Secure MCP servers (header forwarding): <https://learn.microsoft.com/azure/api-management/secure-mcp-servers>
- Policy fragments (`rawxml`): <https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2024-05-01/service/policyfragments#resource-format>
- Backends: <https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2025-03-01-preview/service/backends#property-values>
- v2 tiers (api-version 2024-05-01 or later): <https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview>

## Gaps and open items

- The connector-manifest contract enum admits only `model_deployment_swap` of the six PRP-34 kinds;
  the manifest lists the kinds the contract admits (`manifest_actions`) and a strict xfail test
  flags the gap until the contract adds the other five.
- No `If-None-Match` on creates: the re-read before each write narrows, but does not close, a
  race in which someone creates the same resource between our read and our PUT.
- `products/{p}/apiLinks/{l}` (product API link resource) and `?format=rawxml` on GET are taken
  from the ARM reference as recalled, not re-verified for api-version 2024-05-01.
- Restoring a found resource PUTs the properties read before the change; read-only properties are
  expected to be ignored by ARM, which is not verified live.
- The apply-record store here is in memory; item 2 provides the durable gateway-store
  implementation. A cancelled apply leaves an `applying` record whose `created` steps are known.
- Government: manage is disabled (advisory connector) until the capability row
  `apim.backend_pool.government.any.standard_v2` is `available`; never rerouted to Commercial.
- G17 manage is OPEN: nothing here ran against a real gateway.
