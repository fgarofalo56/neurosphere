# NeuroSphere Azure Monitor connector (PRP-09 item 4)

Read-only, advisory polling connector for Log Analytics workspaces and Application Insights apps.
Query text is fixed (templates in `queries.py`); the time window is passed through the API's
`timespan` parameter. Each poll is bounded by a time window, a page budget (a page is one time
slice, because the query APIs have no cursor paging) and a watermark. Every result carries
`freshness` (lag, `None` when unknown) and `coverage` (answered / expected sources).

## Truncation, halving and stalls

`truncated_pages` counts truncated source queries (a query that hit the row cap or came back
with `PartialError`), not time slices: one slice read from three sources can add up to three.
A truncated slice is discarded and retried at half of the span actually read (a final slice
clipped by the window end is halved from its clipped length, not from `slice_length`), down to a
30 second floor. A slice still truncated at the floor sets `stalled_slice_start`; the watermark
stays at that instant and the gateway poller records `poll_status = "stalled"`.

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

### Cost-center attribution (PRP-33 audit, PRP-34 item 4)

The grant fragment's `llm-emit-token-metric` writes the `x-ns-cost-center`, `API ID` and `Subscription ID` dimensions to Application Insights `customMetrics`, not to the gateway log tables, so the joined gateway KQL never sees the cost center.

- `SourceKind.APIM_USAGE_METRICS` queries `customMetrics` (names `Prompt Tokens`, `Completion Tokens`, `Total Tokens`) through the Application Insights query API (`GET {host}/v1/apps/{app id}/query`; the source id is the App Insights app id, Commercial only: no Government App Insights host is configured). Projected columns: `timestamp, name, value, valueSum, valueCount, ApiId, SubscriptionId, ['x-ns-cost-center']`. `customDimensions` is read per key and never projected whole. Fixed KQL, window in `timespan`, no body or header column.
- The metric has no `CorrelationId`, so attribution is by dimension, not per request. `CostCenterIndex(metric_rows)` maps a gateway row by (`ApiId`, `ApimSubscriptionId`), then `ApimSubscriptionId` alone. A key with more than one distinct valid cost center is ambiguous and yields no tag. `N/A`, empty and out-of-pattern values are never indexed. Pass it as `map_gateway_row(..., cost_centers=index)`; a cost-center dimension on the row itself wins.
- The gateway poll worker (`GatewayPoller(metrics_app_id=...)`) runs the metrics query as a separate best-effort call and puts the result on the posted CloudEvent as the `nscostcenter` extension (`TelemetryEvent` has no tags field). A metrics failure drops only the tag.
- Gaps: not live-tested; the `Subscription ID` metric dimension is assumed to equal `ApimSubscriptionId`; attribution ignores time within the window, so a subscription that changes cost-center header mid-window is ambiguous. Source: https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy

### Unpriced gateway cost

Gateway rows carry token counts but no price, so the cost side has `amount = null`, `observation_source = "gateway"`, and no currency or price version; this module never computes a price. The shipped `CostRecord` contract requires a non-null `amount` and `currency`, so the cost side is the connector-local `GatewayCostObservation` (same field names, `amount: None`) rather than a `CostRecord`. Turning it into a ledger-bound `CostRecord` needs a contract decision (nullable amount for unpriced gateway observations); that is open and outside this connector.

### Gaps (APIM kinds)

- Token counts come from the model response, so a broken stream may log no tokens (null, not 0).
- `GatewayLlmLogs` is a separate diagnostic category from `GatewayLogs`; both must be enabled or the join yields null LLM columns.
- Counts are a lower bound when sampling is enabled on the diagnostic.
- Government remains unverified, as above. Not live-tested against a real workspace.
- Sources (retrieved 2026-10-29): https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaylogs#columns , https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog#columns , https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaymcplog#columns , https://learn.microsoft.com/azure/api-management/monitor-api-management-reference#resource-logs

## GenAI span kinds (PRP-141 item 1)

Two more `SourceKind`s read GenAI spans (model calls, tool calls, agent runs) from a Log Analytics workspace behind workspace-based Application Insights. They use the workspace query API (not the app-id API), the `timespan` window, freshness, 429 handling and the Government opt-in unchanged.

- `SourceKind.APP_GENAI_DEPENDENCIES`: `AppDependencies` rows (client, internal and other span kinds) that carry `gen_ai.operation.name`.
- `SourceKind.APP_GENAI_REQUESTS`: `AppRequests` rows (server spans, for example agent runs) that carry it.
- `map_genai_row(row, *, cloud, customer_id, source_id, domain_id, app_role_names=None)` maps one row to one `TelemetryEvent` (`event_id = "<OperationId>:<Id>"`, the edge's rule). An unusable row raises `GenAiRowSkipped` with a `reason` (`bad_ids`, `no_operation`, `bad_time`, `role_filtered`, `invalid_event`) so the caller can count by reason. `canonical_agent_id` is never set; `gen_ai.agent.id` goes to `external_agent_id` and the resolver (PRP-137) does the rest. When `ItemCount` is above 1 the event records `sampling.rate = 1/ItemCount`, method `unknown`; counts are never multiplied up.

### Read and never read

Read (`GENAI_COLUMNS`): `TimeGenerated, Id, OperationId, ParentId, Success, DurationMs, ItemCount, AppRoleName`. Read from `Properties`, one key at a time (`GENAI_ATTRIBUTE_KEYS`): `gen_ai.operation.name`, `gen_ai.agent.id`, the provider, model, and input, output, cached and reasoning token attributes of the OTLP edge (the tuples are copied into `queries.py`; the connector never imports the API package).

Never read (`CONTENT_DENYLIST`, tested against both templates): prompt, completion, input and output messages, system instructions, tool definitions, tool call arguments and results, evaluation explanations, conversation id, user and client identity attributes, `Status.message`, command text and URLs; the columns `Properties` (as a whole bag), `Measurements`, `Data`, `Target`, `Url`, `Name`, `ClientIP`, `UserId`, `UserAuthenticatedId`, `UserAccountId`, `SessionId`, `OperationName`, `_ResourceId`; and the tables `AppTraces`, `AppExceptions`, `AppEvents`. Content is never selected; `drop_body_fields` and the edge are second nets.

### Learn verification (2026-11-22)

| # | Result | Source |
|---|---|---|
| 1 | CONFIRMED. `AppDependencies` and `AppRequests` carry `TimeGenerated` datetime, `Id` string, `OperationId` string, `ParentId` string, `Success` bool, `DurationMs` real, `Properties` dynamic, `AppRoleName` string, `ItemCount` int, `_ResourceId` string. Analytics plan only | https://learn.microsoft.com/azure/azure-monitor/reference/tables/appdependencies , https://learn.microsoft.com/azure/azure-monitor/reference/tables/apprequests |
| 2 | CONFIRMED. Server spans land in requests; client, internal and other kinds land in dependencies | https://learn.microsoft.com/azure/azure-monitor/app/migrate-to-opentelemetry , https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify |
| 3 | CONFIRMED. Span attributes are custom properties (`Properties` in workspace tables); dotted keys are kept; non-string values are serialized to strings | https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify |
| 4 | CONFIRMED (semantic conventions are in Development status). `gen_ai.operation.name` values `chat`, `text_completion`, `invoke_agent`, `execute_tool`; `gen_ai.provider.name`; `gen_ai.request.model`; `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`; `gen_ai.agent.id` | https://learn.microsoft.com/azure/foundry/how-to/develop/langchain-traces , https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept |
| 5 | CONFIRMED. Content attributes: `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `gen_ai.evaluation.explanation`; content recording is off by default. Personal data seen in attributes: `user.id`, `user.email`, `user.name`, `client.address`, `enduser.id`, `enduser.pseudo.id`, `gen_ai.conversation.id`, `Status.message` | https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-client-side |
| 6 | PARTLY CONFIRMED. OpenTelemetry trace id is Operation ID and span id is ID (32 and 16 hex). GAP: Copilot Studio environment telemetry writes GUID-form ids, which are skipped as `bad_ids` | https://learn.microsoft.com/azure/azure-monitor/app/migrate-to-opentelemetry |
| 7 | CONFIRMED. `ItemCount` is the number of telemetry items represented by one sample item | https://learn.microsoft.com/azure/azure-monitor/reference/tables/appdependencies |
| 8 | CONFIRMED. Log Analytics Reader at the workspace; Privileged Monitoring Data Reader when tables are protected; table-level access exists | https://learn.microsoft.com/azure/azure-monitor/logs/api/register-app-for-token |
| 9 | CONFIRMED. 500,000 records, about 104 MB, 10 minutes, 200 requests per 30 s; 5 concurrent queries per user. Query charges on the Analytics plan UNVERIFIED | https://learn.microsoft.com/azure/azure-monitor/fundamentals/service-limits |
| 10 | CONFIRMED. Typically under 5 minutes latency | https://learn.microsoft.com/azure/azure-monitor/app/application-insights-faq |

### Gaps (GenAI kinds)

- Copilot Studio GUID-form ids are skipped and counted (`bad_ids`); they are not mapped.
- The newer `OTelSpans` table (attributes in `Attributes`) is not read.
- Government is unverified: the `api.loganalytics.us` token audience and Foundry tracing to Application Insights in Government are not confirmed.
- Whether the Foundry agent id equals the `gen_ai.agent.id` attribute is UNVERIFIED (Foundry documents the attribute as `agent-name:version`).
- The fixtures (`tests/fixtures/genai_*_response.json`) are HAND-BUILT from the documented schema, not a real response; the live gate replaces them with a scrubbed real one.
