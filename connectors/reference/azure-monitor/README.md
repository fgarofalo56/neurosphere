# NeuroSphere Azure Monitor connector (PRP-09 item 4)

Read-only, advisory polling connector for Log Analytics workspaces and Application Insights apps.
Query text is fixed (templates in `queries.py`); the time window is passed through the API's
`timespan` parameter. Each poll is bounded by a time window, a page budget (a page is one time
slice, because the query APIs have no cursor paging) and a watermark. Every result carries
`freshness` (lag, `None` when unknown) and `coverage` (answered / expected sources).

## APIs used (observed 2026-10-17)

- Log Analytics query, request format (`POST https://api.loganalytics.azure.com/v1/workspaces/{id}/query`, JSON body `query` + `timespan` as `start/end`, bearer token): https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/request-format
- Response format (`tables[].columns/rows`; non-fatal errors come back as `200` with `error.code = PartialError`): https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/response-format
- Access and auth (Microsoft Entra; scope `https://api.loganalytics.io/.default`; `api.loganalytics.azure.com` replaces `api.loganalytics.io`): https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api
- Limits (500,000 rows, ~100 MB, 10 min, 200 requests / 30 s per user; queued query over 3 min or queue of 200 returns 429): https://learn.microsoft.com/en-us/azure/azure-monitor/service-limits
- Application Insights query (`GET https://api.applicationinsights.io/v1/apps/{appId}/query?query=&timespan=`): https://learn.microsoft.com/en-us/rest/api/application-insights/query/get
- Workspace-based table `AppRequests` columns used (`TimeGenerated`, `Success`, `AppRoleName`): https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apprequests
- Government endpoint list (`api.loganalytics.us`): https://learn.microsoft.com/en-us/azure/azure-government/compare-azure-government-global-azure

## Gaps (documented, not built)

- Azure Government is configuration only and unverified: the `api.loganalytics.us` host is listed, but its token scope is assumed by analogy and nothing was live-tested. It needs `allow_unverified_government=True`, never falls back to Commercial, and the manifest lists Commercial only until verified.
- No Government host for the Application Insights query API was found, so it is disabled there.
- `Retry-After` on query 429 responses is not documented for the query API; it is honored when present, otherwise bounded exponential backoff is used.
- The classic `requests` table name used for Application Insights is from the legacy query API; classic resources are being retired in favor of workspace-based ones (queried via their workspace).
- Ingestion delay (default 5 min safety margin) is a configured choice, not a documented SLA.
- Live runs (gate G04) require `NS_LIVE_APPROVED=1` and a real workspace; none was run.

## APIM gateway and MCP source kinds (PRP-33 item 3)

Two more `SourceKind`s query a Log Analytics workspace that receives API Management resource logs (resource-specific tables). Both reuse the workspace query path, the `timespan` window, freshness and coverage, 429 handling and the Government opt-in (`allow_unverified_government`) unchanged.

- `SourceKind.APIM_GATEWAY`: `ApiManagementGatewayLogs` left-joined on `CorrelationId` to `ApiManagementGatewayLlmLog`. Gateway columns: `TimeGenerated, CorrelationId, ApiId, ApiRevision, OperationId, ProductId, ApimSubscriptionId, BackendId, BackendResponseCode, ResponseCode, IsRequestSuccess, TotalTime, BackendTime, Region, _ResourceId`. LLM columns: `ModelName, DeploymentName, PromptTokens, CompletionTokens, TotalTokens, IsStreamCompletion, ApiVersion`.
- `SourceKind.APIM_MCP`: `ApiManagementGatewayMCPLog` projecting `TimeGenerated, CorrelationId, ToolName, ToolCount, TransportType, _ResourceId`.

Privacy rule: the column lists above are an allowlist. Request and response bodies, headers and trace records (`RequestMessages`, `ResponseMessages`, `RequestBody`, `ResponseBody`, `BackendRequestBody`, `BackendResponseBody`, `RequestHeaders`, `ResponseHeaders`, `BackendRequestHeaders`, `BackendResponseHeaders`, `TraceRecords`) are never projected; a test asserts none of those names appears in the KQL.

Mapping (`gateway_mapping.py`): `map_gateway_row` turns one joined row into one `TelemetryEvent` plus one `GatewayCostObservation`; `map_mcp_row` turns one MCP row into a `tool_call` `TelemetryEvent` plus tool name and transport. The request id and cost `dedupe_key` are the `CorrelationId`. `ApimSubscriptionId` is stored only as a sha256 hex digest. Rows with no LLM side (non-LLM APIs) still map, with token fields null.

### Unpriced gateway cost

Gateway rows carry token counts but no price, so the cost side has `amount = null`, `observation_source = "gateway"`, and no currency or price version; this module never computes a price. The shipped `CostRecord` contract requires a non-null `amount` and `currency`, so the cost side is the connector-local `GatewayCostObservation` (same field names, `amount: None`) rather than a `CostRecord`. Turning it into a ledger-bound `CostRecord` needs a contract decision (nullable amount for unpriced gateway observations); that is open and outside this connector.

### Gaps (APIM kinds)

- Token counts come from the model response, so a broken stream may log no tokens (null, not 0).
- `GatewayLlmLogs` is a separate diagnostic category from `GatewayLogs`; both must be enabled or the join yields null LLM columns.
- Counts are a lower bound when sampling is enabled on the diagnostic.
- Government remains unverified, as above. Not live-tested against a real workspace.
- Sources (retrieved 2026-10-29): https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaylogs#columns , https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog#columns , https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaymcplog#columns , https://learn.microsoft.com/azure/api-management/monitor-api-management-reference#resource-logs
