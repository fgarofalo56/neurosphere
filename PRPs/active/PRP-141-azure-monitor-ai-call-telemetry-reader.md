---
name: PRP-141-azure-monitor-ai-call-telemetry-reader
status: active
started: 2026-11-22
priority: P0
order: 60
review: required
created: 2026-11-17
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01, NS-02, NS-09
depends_on: [PRP-139-hosted-environment-real-tenant-data, PRP-137-telemetry-agent-identity-resolution]
wave: W20
branch: prp-141-azure-monitor-ai-telemetry
allow_parallel: true
issues: []
---

# PRP-141: Azure Monitor AI call telemetry reader (Log Analytics and workspace-based Application Insights)

## Goal
Make a hosted NeuroSphere deployment show real AI call telemetry (latency, errors, tokens, per agent and per model) from the Azure Monitor data of the tenant it is deployed to. Today the Azure Monitor connector can only count web requests, its output maps to no telemetry event and no worker role runs it, so the fourth source of decision D20 is not runnable and PRP-139 leaves its live-gate row OPEN. This PRP adds a worker role, `azure_monitor_ai`, that reads GenAI spans (model calls, tool calls, agent runs) from a Log Analytics workspace that backs a workspace-based Application Insights resource, with the deployment's managed identity, through two fixed pre-written queries; maps each row to a `TelemetryEvent` with metadata only; and posts the events to the ingest edge as a registered producer, exactly as the gateway poller does, so authorization, body dropping, dedupe, the archive, the outbox and the workers are the ones every other source uses. Agent identity is left to the PRP-137 resolver. The source is configured in the shipped admin Connectors page, its run status is visible to an admin through PRP-139's status rows, query volume is capped, Commercial and Government stay separate, tests run on recorded fixtures with no cloud call, and an operator live gate closes row 4 of PRP-139's gate. It is for the owner, who wants the deployed app to show their own tenant's AI calls (D20, `docs/DECISIONS-LOG.md:18`). It runs in W20 beside PRP-71, PRP-72, PRP-73 and PRP-99; its one contract line is added by item 6 itself (amended 2026-11-22).

Out of scope: prompt, response, tool argument or tool result content (content capture is a separate opt-in feature, `docs/PRD.md:66`, PRP-101 to PRP-104); classic (non workspace-based) Application Insights and the app-id query API; Azure Monitor metrics; diagnostic settings or instrumentation of the customer's workloads (the workload must already send GenAI spans to Application Insights); cost records (spans carry tokens, not prices; pricing stays with the price sheet); the generic connector runner and Coverage page (PRP-117); the resolver itself (PRP-137); the hosted real-tenant mode, access plan and purge (PRP-139); API Management gateway tables (shipped, PRP-33); creating workspaces or Application Insights resources; any write to a governed resource.

## Why
- D20 names Azure Monitor as one of four sources the hosted deployment reads with its managed identity (`docs/DECISIONS-LOG.md:18`). PRP-139 found the path not runnable, left the row OPEN and named this follow-up (`PRPs/backlog/PRP-139-hosted-environment-real-tenant-data.md:35,69,77,359,365`).
- The finding is confirmed. The connector's two generic kinds are request counters: `AppRequests | summarize requests=count(), failed=countif(Success == false) by bin(TimeGenerated, 5m), AppRoleName` and the classic `requests` twin (`connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/queries.py:44-57`). No model, token, agent, trace or span column is selected.
- Nothing maps those rows to a telemetry event. The package's only mappers are `map_gateway_row` and `map_mcp_row` for API Management tables (`neurosphere_connector_azure_monitor/__init__.py:10-19`, `gateway_mapping.py:250,326`).
- No worker role runs them. The role tuple is twelve names with no Azure Monitor role (`services/workers/neurosphere_workers/runtime/roles.py:18-31`), `BUILDERS` has the same twelve (`runtime/factories.py:1934-1947`), and the only caller of the connector polls `SourceKind.APIM_GATEWAY` and `APIM_MCP` plus the optional `APIM_USAGE_METRICS` (`ingestion/gateway_poll/poller.py:281-287,358-361`). `docs/connectors/coverage.md:68` lists the Azure Monitor caller as "(APIM logs)" only.
- The shipped PRPs never promised more: PRP-09 item 4 delivered "bounded polling ... with window, page budget and watermark" and freshness and coverage (`PRPs/shipped/PRP-09-connector-sdk-and-reference-connectors.md:39,162-163`); PRP-33 added the gateway kinds and the `gateway_poll` role (`PRPs/shipped/PRP-33-apim-gateway-observe.md:34-35,146`).
- The stored configuration cannot name the source either: `connector_kind` is a closed enum of `gateway_poll`, `foundry_discovery`, `billing_export`, `otel` (`packages/contracts/schemas/admin/v1/connector-config.schema.json:23-26`), the worker validators and allowed settings have the same four (`connector_config/validators.py:88-93`, `stored.py:48-79`), and so do the API filter (`services/api/neurosphere_api/admin/sources/connectors/router.py:48`) and the page (`frontend/src/features/admin/sources/types.ts:37-42`).
- The target shape already exists. The OTLP edge maps GenAI attributes to `TelemetryEvent` (`services/api/neurosphere_api/ingest/otlp_mapping.py:51-90,230-279`), and the contract has the fields this source can fill: ids, `span_kind`, `provider`, `model`, `outcome`, `duration_ms`, `token_breakdown`, `sampling`, `external_agent_id` (`packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:155-158,183-270`).
- The pattern for a polling source that enters through the front door is shipped: the gateway poller posts CloudEvents to `/api/v1/ingest/events` as a producer (`gateway_poll/poller.py:136-172,184-196`), a decision PRP-33 recorded as "authorization, kinds and audit are the ones every other source uses" (`PRPs/shipped/PRP-33-apim-gateway-observe.md:53`).

## Acceptance criteria
- [ ] Given the two new source kinds, When their query text is inspected, Then each is a module constant with no caller-supplied text, the time window travels only in the API `timespan` parameter, the workspace id is a validated GUID in the URL path, every projected column and every extracted attribute key is in a named allowlist, the `Properties` bag itself is never projected, and no name from the content denylist (clarification 4) appears in any template. A test fails if a template contains a format placeholder or a denylisted name.
- [ ] Given a recorded Log Analytics response with a model call, a tool call, an agent run, a failed call, a sampled row and a row with content attributes present in the source, When the rows are mapped, Then each becomes one `TelemetryEvent` with `event_id = "<trace id>:<span id>"`, `span_kind`, `provider`, `model`, `outcome`, `duration_ms`, token counts and `external_agent_id` set from the allowlisted attributes; missing values are null, never 0; no content value appears anywhere in the event; an unusable row is skipped and counted, never guessed.
- [ ] Given the role is configured for one workspace, When a tick runs, Then it queries only the window after the stored watermark (minus the re-read overlap), posts the events to the ingest edge as the registered producer, and commits the new watermark only after every batch was accepted; Given an ingest failure, a throttled first slice or a truncated slice, Then the watermark does not advance past what was accepted and the status says why.
- [ ] Given the same window is read twice (a restart, the overlap, a replay after an ingest failure), When the events pass the real ingestion pipeline, Then no second accepted record, aggregate contribution or ledger line exists (dedupe on customer, source and event id, `ingestion/models.py:54-62`).
- [ ] Given an event with `gen_ai.agent.id = support-bot` and an active alias for (`azure-monitor-ai`, `support-bot`), When it passes ingest, the pipeline, and the aggregates and catalog workers built with PRP-137's resolving sources, Then the call counts for the aliased agent; Given no alias, Then PRP-137's derived id and draft agent apply; the reader never sets `canonical_agent_id` itself.
- [ ] Given a stored `ConnectorConfig` of kind `azure_monitor_ai` created in the admin Connectors page with a workspace id, one domain and a Key Vault reference for the producer secret, When the workers restart, Then the role runs from the stored configuration only; a disabled or missing configuration idles the role; an invalid setting is a 422 with a pointer at creation. No key, connection string or instrumentation key is accepted anywhere, and the workspace is read with the workload identity only.
- [ ] Given each tick, Then a run status (`ok | partial | failed | idle | not_configured`, a reason code, last success time, counts of queries, rows, events posted, rows skipped) is stored through PRP-139's `StatusRecordingTick`; Given the workspace answers 401 or 403, Then the state is `failed` with reason `source_access_denied`, the role keeps running and no host, workspace id or token is stored. The Connectors page shows the row, and `GET /api/v1/sources/status` reports the Azure Monitor source as `connected`, `connected_no_data` or `failing` instead of the fixed `not_connected`.
- [ ] Given the guards (clarification 7), When a tick would exceed its query budget or its event budget, Then it stops, records `partial` with reason `query_budget_exhausted` or `event_budget_exhausted`, and resumes from the watermark next tick; a 429 is honoured through the connector's bounded backoff and recorded `rate_limited`; the role never loops and never queries more than the configured number of workspaces.
- [ ] Given a runtime cloud of `government`, Then the role refuses to query unless `allow_unverified_government` is set, uses only the Government host and scope, never falls back to Commercial, and a configuration or producer on another cloud is refused (`cloud_mismatch`); the classic Application Insights app-id API is not used in either cloud.
- [ ] Given `hosted_real_tenant.py verify` after the operator connected the source, Then row 4 is `PASS` only when at least one event of source `azure-monitor-ai` is visible through the API and the run status is `ok` or `partial`; otherwise `FAIL` or `OPEN` with a reason. Nothing in this PRP marks the row PASS without an operator run.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend lint, typecheck and tests, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated; the runbook lists the operator steps; the live gate is written OPEN with its commands.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | How the rows enter the product | Write to the archive directly; call the pipeline in process; post to the ingest edge | Post CloudEvents to `/api/v1/ingest/events` as a registered producer with an `application` source, the shipped gateway poller path (`gateway_poll/poller.py:136-196`). No side door: claims check, body dropping, rate limit, Event Hubs, `process_batch`, dedupe, archive and outbox are unchanged and unedited |
| 2 | Dedicated role or a `connector_runner` connector | Wait for PRP-117 (W26); a dedicated role now | A dedicated role `azure_monitor_ai` now, shaped like `gateway_poll`. PRP-117 may later wrap it as a descriptor; this PRP names the seams (settings class, tick, `last_status`) so that is a move, not a rewrite |
| 3 | Which API and tables | Classic app-id API; workspace query API | Workspace query API only (`POST {host}/v1/workspaces/{id}/query`, the path the gateway kinds use, `connector.py:340-343`). It has a Government host entry, the app-id API has none (`endpoints.py:47-54`). Tables: the workspace-based Application Insights span tables. Table and column names are UNVERIFIED (see below) |
| 4 | What is read | Everything in the span; an allowlist | An allowlist of columns and attribute keys. Never projected: the whole attribute bag, any content attribute or event (prompt, completion, input and output messages, system instructions, tool call arguments and results), dependency command text, target host, user and session ids, client IP, and the trace and exception message tables. The denylist is a tested constant |
| 5 | Agent identity | Resolve in the reader; leave to PRP-137 | Leave to PRP-137. The reader sets `external_agent_id` from `gen_ai.agent.id` only, the same single attribute the edge uses (`otlp_mapping.py:78`), and a stable `source_id`. ASSUMPTION: agent name is not used as an id |
| 6 | Link to Foundry-discovered agents | Automatic alias; steward declares | ASSUMPTION: not automatic here. PRP-137 keys aliases by source id, so an agent Foundry discovered under the Foundry source is not matched by telemetry under `azure-monitor-ai`; it appears as a derived draft until a steward declares an alias with PRP-137's route. Whether the Foundry agent id equals `gen_ai.agent.id` is UNVERIFIED; if the live gate proves it, a follow-up lets the Foundry poller write the second alias |
| 7 | Volume and cost guards | None; fixed; configurable with floors | ASSUMPTION for defaults, all bounded by validators: interval 300 s (floor 60), window per tick 3600 s, first-poll lookback 24 h (cap 7 days, no historical backfill), re-read overlap 600 s, at most 4 workspaces per configuration, at most 24 queries and 20 000 events per tick, connector row cap 10 000 per query with slice halving (`queries.py:29`, `connector.py:274-289`), ingest batches of 100 |
| 8 | Stored configuration kind | Reuse `otel` or `generic`; a new kind | A new `connector_kind` value `azure_monitor_ai`. It needs one additive enum line in the contract. AMENDED 2026-11-22 (owner sign-off at plan approval): PRP-99 had not started and its enum list does not carry the value, so item 6 adds it itself (additive values pass `tests/contracts/test_additive_only.py`); PRP-99 later stacks its own values on top. Item 6 is no longer `[serial-after: PRP-99]` |
| 9 | What identifies the source | Application Insights resource id; workspace id | ASSUMPTION: the workspace id (a GUID, not a secret), matching `MonitorSource` (`queries.py:117-129`). An optional `app_role_names` list filters rows after the query, in the mapper, so no value enters query text |
| 10 | Where the watermark lives | New container; the gateway registration; the runtime checkpoint store | `CosmosRuntimeCheckpointStore` in the existing `outbox-checkpoints` container, one key per workspace (`runtime/checkpoint.py:37-68`, built by `_runtime_checkpoints`, `factories.py:328-330`). No new container (`containers.py` is PRP-72's in W20) |
| 11 | Domain of the events | None; one per configuration | One domain per configuration (the `_single_domain` rule, `connector_config/stored.py:195-197`). PRP-137 needs a domain to create a draft agent |
| 12 | A workload that also pushes OTLP | Detect and merge; document | ASSUMPTION: documented, not detected. The same span read here and pushed to the edge has the same event id under two source ids and would count twice. The runbook says to use one path per workload |
| 13 | Sampling | Ignore; record | Record. When the row carries an item count above 1 the event gets `sampling.rate = 1 / count` and method `unknown`; counts are never multiplied up |

## Source: tables, fields and what must be confirmed on Microsoft Learn
The repository's verified notes cover only the query API, its limits and three `AppRequests` columns (`connectors/reference/azure-monitor/README.md:18-26`). Everything below about GenAI spans is UNVERIFIED and is a planning guess to be replaced by what Learn says. The orchestrator has the Learn tools; subagents do not, so the orchestrator verifies and pastes the facts into the briefs. Each confirmed fact goes into the README with its URL and date; an item that cannot be confirmed is not coded and is written as a gap.

Bounded query set (two templates, no others):

| Kind | Reads (UNVERIFIED names) | Purpose |
|---|---|---|
| `APP_GENAI_DEPENDENCIES` | `AppDependencies` rows that carry a GenAI operation attribute | model calls, tool calls, outbound and in-process agent steps |
| `APP_GENAI_REQUESTS` | `AppRequests` rows that carry a GenAI operation attribute | agent runs recorded as server spans |

Planned field map (all source names UNVERIFIED):

| `TelemetryEvent` | Source |
|---|---|
| `event_time` | `TimeGenerated` |
| `trace_id`, `span_id`, `parent_span_id`, `event_id` | `OperationId`, `Id`, `ParentId`; `event_id` is `<trace>:<span>` as at the edge (`otlp_mapping.py:259`); a row whose ids are not 32 and 16 hex is skipped and counted |
| `duration_ms` | `DurationMs` rounded down |
| `outcome` | `Success` (true, false, missing to `success`, `error`, `unknown`) |
| `span_kind` | `gen_ai.operation.name` through the edge's table (`otlp_mapping.py:81-90`) |
| `provider`, `model` | the edge's `PROVIDER_ATTRS` and `MODEL_ATTRS` names (`otlp_mapping.py:51-57`) |
| `token_breakdown` | the edge's four token attribute tuples (`otlp_mapping.py:58-76`) |
| `external_agent_id` | `gen_ai.agent.id` |
| `sampling` | `ItemCount` |
| `environment` | not read; stays `unknown` |

UNVERIFIED, to confirm before any query text is written:
1. The table names of workspace-based Application Insights for dependencies and requests, and each column used above with its type (`TimeGenerated`, `Id`, `OperationId`, `ParentId`, `Success`, `DurationMs`, `Properties`, `AppRoleName`, `ItemCount`, `_ResourceId`).
2. Which table a span lands in by span kind when exported by the Azure Monitor OpenTelemetry exporter and by Azure AI Foundry tracing (client, internal and server spans), so the two queries cover model calls, tool calls and agent runs and nothing is read twice.
3. Where span attributes land (the `Properties` dynamic column is the guess), whether dotted keys such as `gen_ai.request.model` are kept as written, and whether numeric attributes arrive as strings.
4. The GenAI semantic-convention attribute names and version emitted by Azure AI Foundry Agent Service, the Azure AI Projects and Inference SDK tracing, and the OpenAI SDK instrumentation Microsoft documents: operation name, provider (`gen_ai.provider.name` or `gen_ai.system`), request and response model, input, output, cached and reasoning tokens, `gen_ai.agent.id`, `gen_ai.agent.name`, tool name, error type.
5. Every attribute and event name that can carry content when the workload turns content recording on, and where it is stored (span attributes or the trace table), to complete the denylist.
6. The format of `OperationId`, `Id` and `ParentId` for OpenTelemetry-exported rows (W3C 32 and 16 hex is the guess).
7. The meaning of the item count column under sampling.
8. The least-privilege built-in role for the workload identity to query one workspace, whether table-level access can narrow it to the two tables, and whether reading Application Insights data through its workspace needs any role on the Application Insights resource. This is PRP-139's UNVERIFIED item 1; reuse its answer and its `logAnalyticsWorkspaceIds` assignment.
9. Query limits (the README records 200 requests per 30 s, 500 000 rows, about 100 MB, 10 minutes as observed 2026-10-17; re-confirm) and whether log queries cost money on the table plan in use (Analytics, Basic, Auxiliary).
10. Typical ingestion delay for these tables (the 5 minute margin is a configured choice, `connector.py:84-85`).
11. Government: the token scope for `api.loganalytics.us` (still UNVERIFIED in `endpoints.py:6-7`) and whether Foundry tracing to Application Insights exists in Azure Government.
12. Whether the Foundry agent id equals the `gen_ai.agent.id` span attribute (decides clarification 6's follow-up).

### Learn verification (orchestrator, 2026-11-22)
| # | Result | Source |
|---|---|---|
| 1 | CONFIRMED. `AppDependencies` and `AppRequests` both carry `TimeGenerated` datetime, `Id` string, `OperationId` string, `ParentId` string, `Success` bool, `DurationMs` real, `Properties` dynamic, `AppRoleName` string, `ItemCount` int, `_ResourceId` string. Both tables: Basic and Auxiliary plans not supported (Analytics only) | learn.microsoft.com/azure/azure-monitor/reference/tables/appdependencies, .../apprequests |
| 2 | CONFIRMED. Server spans land in requests; client, internal and other kinds land in dependencies (custom spans default to dependencies with type `InProc`) | .../azure-monitor/app/migrate-to-opentelemetry (terminology table), .../app/opentelemetry-add-modify |
| 3 | CONFIRMED. Span attributes are exported as custom properties into customDimensions (`Properties` in workspace tables) of requests and dependencies; dotted keys are kept (`customDimensions["gen_ai.conversation.id"]` in Microsoft's own queries); non-string values are serialized to strings | .../app/opentelemetry-add-modify; microsoft-copilot-studio/advanced-environment-level-agent-telemetry; JS and Python exporter READMEs (custom dimensions size limit) |
| 4 | CONFIRMED (semantic conventions have Development status). `gen_ai.operation.name` values `chat`, `text_completion`, `invoke_agent`, `execute_tool`; `gen_ai.provider.name`; `gen_ai.request.model`; `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`; `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.tool.name`. All are already in the edge tables (`otlp_mapping.py:51-90`) | azure/foundry/how-to/develop/langchain-traces; azure/foundry/observability/concepts/trace-agent-concept |
| 5 | CONFIRMED. Content attributes: `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `gen_ai.evaluation.explanation` (exporter truncation table); content recording is off by default (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`). Personal data also seen in span attributes: `user.id`, `user.email`, `user.name`, `client.address`, `enduser.id`, `enduser.pseudo.id`, `gen_ai.conversation.id`, `Status.message`. All go in `CONTENT_DENYLIST` | Python exporter README (custom properties truncation); azure/foundry/observability/how-to/trace-agent-client-side; Copilot Studio telemetry page |
| 6 | PARTLY CONFIRMED. OpenTelemetry trace id maps to Operation ID and span id to ID; W3C 32 and 16 hex for OpenTelemetry-exported rows. GAP: Copilot Studio environment telemetry writes GUID-form ids (`trace-<guid>`), which the hex rule skips and counts | migrate-to-opentelemetry; Copilot Studio telemetry page |
| 7 | CONFIRMED. `ItemCount` is the number of telemetry items represented by a single sample item | appdependencies table reference |
| 8 | CONFIRMED. Log Analytics Reader at the workspace for the Log Analytics Query API; Privileged Monitoring Data Reader as well when the tables are protected; table-level access exists (manage-access). No Application Insights resource role is listed for the workspace query API | azure-monitor/logs/api/register-app-for-token; azure/foundry/observability/how-to/trace-agent-setup |
| 9 | CONFIRMED. 500,000 records, about 104 MB, 10 minutes, 200 requests per 30 s per user or client IP; 5 concurrent Analytics queries per user, 429 after 3 minutes queued. Query charges on the Analytics plan: not stated in the pages read, stays UNVERIFIED | azure-monitor/fundamentals/service-limits |
| 10 | CONFIRMED. Most Application Insights data has under 5 minutes latency; Foundry says traces appear in 2 to 5 minutes | azure-monitor/app/application-insights-faq; trace-agent-framework |
| 11 | PARTLY. Government query host `api.loganalytics.us` confirmed; token audience for it and Foundry tracing in Government stay UNVERIFIED | azure-government/compare-azure-government-global-azure |
| 12 | UNVERIFIED. Foundry evaluation docs give `gen_ai.agent.id` the format `agent-name:version`; equality with the Foundry agent id is not stated | azure/foundry/observability/how-to/cloud-evaluation-deployed-interactions |
| new | GAP, out of scope. A newer workspace table `OTelSpans` (attributes in `Attributes` dynamic) exists for OpenTelemetry-native ingestion; this PRP does not read it | azure-monitor/reference/tables/otelspans |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-139-hosted-environment-real-tenant-data.md` (in `PRPs/shipped/` by then): sources table, clarifications 6, 7, 9 and 11, items 3, 4 and 6, the gate rows.
- `PRPs/backlog/PRP-137-telemetry-agent-identity-resolution.md`: clarifications 2 and 3, items 2 and 7.
- `connectors/reference/azure-monitor/neurosphere_connector_azure_monitor/{queries.py,connector.py,endpoints.py,auth.py,gateway_mapping.py}` and `README.md`; tests `test_apim_gateway_logs.py` and `test_watermark_semantics.py`.
- `services/workers/neurosphere_workers/ingestion/gateway_poll/{poller.py,settings.py}` and `services/workers/tests/gateway_poll/support.py`.
- `services/workers/neurosphere_workers/runtime/factories.py:317-353,1268-1330,1934-1947`, `runtime/roles.py`, `runtime/checkpoint.py`.
- `services/workers/neurosphere_workers/connector_config/{stored.py,validators.py,resolve.py}`.
- `packages/core/neurosphere_core/admin/connectors/service.py:51-57,140-180`.
- `services/api/neurosphere_api/ingest/otlp_mapping.py:44-112,230-279`, `ingest/service.py:70-82,274-390`, `ingest/auth.py:26-50`, `ingest/settings.py:28-32`.
- `packages/contracts/python/neurosphere_contracts/telemetry/v1/telemetry_event.py:63-80,101-118,143-274`.
- `packages/core/neurosphere_core/sources_status/**`, `services/workers/neurosphere_workers/sources_status/**`, `scripts/gates/hosted_real_tenant.py`, `docs/deploy/hosted-real-tenant.md` (all from PRP-139).
- `docs/connectors/coverage.md:24-34,62-70`, `docs/runbooks/connector-config.md`.

### Interfaces consumed
- Shipped: `AzureMonitorConnector.poll`, `PollBounds`, `PollResult`, `MonitorSource`, `ManagedIdentityTokenProvider`, `endpoints_for`; `IngestClient`; `CheckpointStore`; `PeriodicTick`, `_tick_role`; `ConnectorConfig`, `ConnectorConfigAdmin(validators=...)`, `load_stored_config`, the Key Vault secret reader; producer registrations with an `application` source (`ingest/auth.py:26,45`).
- PRP-139: `StatusRecordingTick`, `ConnectorRunStatus`, `summarize`, reason code `source_access_denied`, the workers identity's read role on the workspaces in `logAnalyticsWorkspaceIds`, `hosted_real_tenant.py access-plan` and `verify`, `dataMode = 'real-tenant'`.
- PRP-137: `ResolvingTraceEventSource` and the alias route. Nothing of PRP-137 is edited; the tests build its sources to prove the path.
- PRP-99 (same wave): the open-ended `connector_kind` enum; not waited for (amended 2026-11-22); item 6 adds the one value itself.

### Interfaces provided
- Connector: `SourceKind.APP_GENAI_DEPENDENCIES`, `SourceKind.APP_GENAI_REQUESTS`; `GENAI_COLUMNS`, `GENAI_ATTRIBUTE_KEYS`, `CONTENT_DENYLIST`; `map_genai_row(row, *, cloud, customer_id, source_id, domain_id, app_role_names=None) -> TelemetryEvent`.
- Worker package `neurosphere_workers.ingestion.azure_monitor_ai`: `AzureMonitorAiSettings` (`NS_AZURE_MONITOR_AI_*`), `AzureMonitorAiPoller` (`tick`, `last_status`), `build_azure_monitor_ai`; role name `azure_monitor_ai`; default producer id and source id `azure-monitor-ai`.
- Stored kind `azure_monitor_ai` with settings `workspace_ids`, `interval_seconds`, `window_seconds`, `lookback_seconds`, `overlap_seconds`, `max_queries_per_tick`, `max_events_per_tick`, `app_role_names`, `allow_unverified_government`, `producer_id`, `source_id`, `batch_size`, `api_base_url`, `managed_identity_client_id`.
- Reason codes `query_budget_exhausted`, `event_budget_exhausted`, `rate_limited`, `stalled`, `ingest_failed`, `cloud_mismatch`, `refused_government_unverified`.
- Consumers: PRP-82 (turns the role on in the everything-on profile), PRP-117 (may wrap the role as a descriptor), PRP-74, PRP-100 and PRP-134 (read the series the events create), PRP-109 (the deployed scenario).

### Patterns to match
- Fixed query constants and an allowlist test: `queries.py:59-86`, `connectors/reference/azure-monitor/tests/test_apim_gateway_logs.py`.
- Row to `TelemetryEvent` mapping in the connector package: `gateway_mapping.py:250-305`.
- Poll, map, post, then record: `gateway_poll/poller.py:259-345`; nothing raises out of a tick for an upstream failure (`poller.py:244-257`).
- Idle when unconfigured and refuse partial configuration: `factories.py:1281-1301`.
- Stored settings built from init arguments only: `connector_config/stored.py:83-110,200-207`; validator shape: `validators.py:49-53`.
- Government opt-in and no cross-cloud poll: `poller.py:260-268`.

### Gotchas
- The connector package cannot import the API package. The attribute name tables are copied into the connector and a parity test in `tests/unit/azure_monitor_ai/` asserts they equal the tuples in `otlp_mapping.py`, so the two cannot drift. `otlp_mapping.py` is read, never edited.
- `drop_body_fields` already runs on every row (`connector.py:254-256`) and again at the edge (`ingest/service.py:124`). It is a second net, not the control: the control is that content is never selected.
- `MonitorSource` needs a GUID (`queries.py:124-129`); the workspace id is the customer id of the workspace, not its ARM resource id.
- `tuple(BUILDERS) == ROLE_NAMES` is asserted (`services/workers/tests/worker_roles/test_roles.py:20-27,53`): add the role at the end of both, in the same commit, and never reorder.
- `all` now includes the role, so an unconfigured deployment must idle with one info line and write `not_configured`, as `gateway_poll` does.
- A stored configuration is read when the role starts; there is no hot reload (`docs/runbooks/connector-config.md`). The runbook restarts the workers after a console change.
- Setting names may not contain `key`, `token`, `secret`, `connection` and similar (`connector-config.schema.json:39-43`): the names in Interfaces provided were chosen to pass.
- The ingest edge limits a producer to 20 requests per second with a burst of 40 (`ingest/settings.py:31-32`); batches of 100 and the per-tick event cap keep the role far below it. Do not raise the limit.
- The watermark is by `TimeGenerated`; rows that arrive late are picked up by the overlap, and the overlap is safe only because event ids are deterministic. Do not derive an event id from anything but the trace and span ids.
- Evidence and logs hold counts, states and reason codes only: no workspace id, host, resource id or token (CodeQL also fails a PR that logs a secret-looking name).
- Agents cannot edit `.env.example`; new variables go in the completion note and the runbook.
- Test directories need unique names (`services/workers/tests/azure_monitor_ai_role`, `tests/unit/azure_monitor_ai`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/azure-monitor/**
  - services/workers/neurosphere_workers/ingestion/azure_monitor_ai/**
  - services/workers/tests/azure_monitor_ai_role/**
  - services/workers/neurosphere_workers/connector_config/stored.py
  - services/workers/neurosphere_workers/connector_config/validators.py
  - services/workers/neurosphere_workers/connector_config/resolve.py
  - services/workers/neurosphere_workers/connector_config/__init__.py
  - services/workers/tests/connector_config_worker/**
  - packages/core/neurosphere_core/admin/connectors/service.py
  - packages/core/tests/admin_connectors/**
  - packages/core/neurosphere_core/sources_status/**
  - packages/core/tests/sources_status_core/**
  - services/api/neurosphere_api/sources_status/models.py
  - services/api/tests/sources_status_api/test_source_status_routes.py
  - tests/security/authz/test_sources_status.py
  - services/api/neurosphere_api/admin/sources/connectors/router.py
  - services/api/tests/admin_connectors_api/**
  - tests/security/authz/test_admin_connectors.py
  - frontend/src/features/admin/sources/ConnectorsPage.tsx
  - frontend/src/features/admin/sources/types.ts
  - frontend/src/features/admin/sources/strings.ts
  - frontend/src/features/admin/sources/sources.test.tsx
  - frontend/tests/mock-api/features/admin-sources.ts
  - frontend/tests/mock-api/features/sourceStatus.ts
  - scripts/gates/hosted_real_tenant.py
  - scripts/gates/hosted_demo.py
  - tests/unit/hosted_real_tenant/**
  - tests/unit/hosted_demo/**
  - tests/unit/hosted_data_path/**
  - tests/unit/azure_monitor_ai/**
  - tests/integration/ingestion/test_azure_monitor_ai_pipeline.py
  - docs/runbooks/azure-monitor-ai-telemetry.md
  - docs/evidence/PRP-141/**
tier1:
  - infra/demo/main.bicep
  - infra/appservice/main.bicep
tier2_appends:
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/workers/tests/worker_roles/test_roles.py
  - docs/connectors/coverage.md
  - docs/runbooks/connector-config.md
  - docs/deploy/hosted-real-tenant.md
  - docs/evidence/PRP-139/README.md
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - tests/contracts/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/agent_identity/**
  - services/workers/neurosphere_workers/agent_identity/**
  - services/workers/neurosphere_workers/ingestion/pipeline.py
  - services/workers/neurosphere_workers/ingestion/gateway_poll/**
  - services/workers/neurosphere_workers/sources_status/**
  - services/api/neurosphere_api/ingest/**
  - services/api/neurosphere_api/sources_status/router.py
  - services/api/neurosphere_api/sources_status/service.py
  - infra/demo/modules/**
  - infra/helm/**
  - docker-compose.yml
  - Makefile
  - scripts/gates/g04_connectors_live.py
  - scripts/sandbox/**
  - .github/workflows/**
```
W20 fit. `packages/contracts/schemas/**` is PRP-99's Tier-1 file in W20 and PRP-99 owns all of `packages/contracts/**` and `tests/contracts/**` (`PRPs/EXECUTION-PLAN.md:635`). This PRP needs one enum value there, so `packages/contracts/**` and `tests/contracts/**` are in `must_not_touch` for every item except item 6, which edits exactly the lines it names (amended 2026-11-22: PRP-99 had not started, so item 6 no longer waits for it). No other Tier-1 file of W20 is needed: PRP-71 has `docker-compose.yml` and `Makefile`, PRP-72 has `stores/containers.py`, `infra/compose/cosmos-containers.json`, `infra/demo/modules/cosmos-data.bicep` and `runtime/builders/data.py` (`EXECUTION-PLAN.md:633-634`); the watermark reuses an existing container so none of them is touched, and PRP-71 holds the compose stack, so this PRP runs no emulator. `infra/demo/main.bicep` and `infra/appservice/main.bicep` have no owner in W20 (PRP-67 held them in W19, PRP-82 comes in W21); this PRP claims them for one role name in the real-tenant role list and nothing else. `runtime/factories.py` gets one import and one `BUILDERS` line (Tier 2); the builder lives in the new package. The files under `sources_status`, `admin/sources`, `hosted_real_tenant.py` and `hosted_demo.py` were PRP-139's and PRP-67's in earlier waves and have no W20 owner.

## Implementation blueprint

Parallelization: start items 1, 3 and 4 together (three lanes, no common file). Item 2 starts when item 1's mapper signature is merged in the lane. Item 5 needs 1 and 2. Item 6 needs 2 and 4 (amended 2026-11-22: no PRP-99 wait). Item 7 needs 2, 4 and 6. Item 8 last. Never more than four lanes. Before any lane starts, the orchestrator resolves the UNVERIFIED list against Microsoft Learn and pastes the confirmed table, column and attribute names into the briefs of items 1 and 2.

### Item 1 - GenAI query set and row mapping in the connector  [P]
- Deliverable: in `queries.py`, two `SourceKind` members and their fixed templates built only from the constants `GENAI_COLUMNS` and `GENAI_ATTRIBUTE_KEYS` (each attribute is extracted to its own named column; the attribute bag is not projected), ordered by time and capped with `MAX_ROWS`; `CONTENT_DENYLIST`. New `genai_mapping.py` with `map_genai_row` per the field map, the attribute tables copied from the edge, the hex id rule, the sampling rule, the optional `app_role_names` filter, and `ValueError` for an unusable row. Exports in `__init__.py`. README section with every confirmed Learn URL and date and the remaining gaps. Recorded fixtures under `tests/fixtures/` built from the confirmed schema (hand-built and labelled so until the live gate supplies a scrubbed real one).
- Owned files: `connectors/reference/azure-monitor/**`.
- Must NOT touch: the APIM templates, `gateway_mapping.py`, `endpoints.py` (Government stays unverified), `connector.py` beyond what a new workspace kind needs (none expected: workspace kinds already route by `APP_INSIGHTS_KINDS`, `connector.py:340-349`).
- Depends on: the verified names. If a name cannot be confirmed, that field is not mapped and the README says so.
- Acceptance criteria: the first two acceptance criteria; a row with content attributes in the fixture yields an event with none of their values (the fixture uses marker strings and the test searches the serialized event); tokens given as strings parse; a missing token is null; an id that is not hex skips the row; existing `connectors/reference/azure-monitor/tests` pass unchanged.
- Tests: `connectors/reference/azure-monitor/tests/test_genai_queries.py`, `test_genai_mapping.py`, `test_genai_privacy.py`.
- Pattern references: `queries.py:59-86`, `gateway_mapping.py:250-305`, `tests/test_apim_gateway_logs.py`.

### Item 2 - Worker role: poller, settings, watermark and guards
- Deliverable: package `ingestion/azure_monitor_ai/` with `settings.py` (`AzureMonitorAiSettings`, env prefix `NS_AZURE_MONITOR_AI_`, the bounds of clarification 7 as field limits, GUID check on each workspace id, `unconfigured` property), `poller.py` (`AzureMonitorAiPoller`: per workspace read the checkpoint, start at watermark minus overlap or at now minus lookback, call the connector with the two kinds, map, post in batches through `IngestClient`, commit the connector's `next_watermark` only after every batch was accepted; stop at the query or event budget; cloud and Government checks; `last_status` with state, reason and counts; nothing raises for an upstream failure), `build.py` (`build_azure_monitor_ai(cfg, lifetime)`: idle branch, refusal of partial configuration with `RoleConfigError`, checkpoint store, HTTP client, `StatusRecordingTick`, `PeriodicTick`), and the role registered at the end of `ROLE_NAMES` and `BUILDERS`. The builder reads the environment settings here; item 6 switches it to the stored resolver.
- Owned files: `services/workers/neurosphere_workers/ingestion/azure_monitor_ai/**`, `services/workers/tests/azure_monitor_ai_role/**`; Tier-2 lines in `runtime/roles.py`, `runtime/factories.py` (one import, one table line), `services/workers/tests/worker_roles/test_roles.py`.
- Must NOT touch: `gateway_poll/**` (import `IngestClient` and the connector factory from it, do not change them), `ingestion/pipeline.py`, any existing builder body in `factories.py`, `sources_status/**`.
- Depends on: item 1 (mapper signature); PRP-139 merged (`StatusRecordingTick`).
- Acceptance criteria: the watermark, guard, status and Government criteria; an unconfigured role under `all` idles and writes `not_configured`; a 401 or 403 from the workspace gives `failed` and `source_access_denied`; a store outage propagates so the supervisor restarts the role; no log line or status holds a workspace id or host (a test scans for GUIDs and URLs); existing `services/workers/tests/{worker_roles,gateway_poll}` pass with only the added role name.
- Tests: `services/workers/tests/azure_monitor_ai_role/test_poller.py`, `test_watermark_and_overlap.py`, `test_budgets.py`, `test_cloud_rules.py`, `test_default_noop.py`, `test_status.py` (fake `MonitorPort`, `httpx.MockTransport` for ingest, in-memory checkpoint store, injected clock).
- Pattern references: `gateway_poll/poller.py:85-125,244-345`, `gateway_poll/settings.py`, `factories.py:1281-1330`, `services/workers/tests/gateway_poll/support.py`.

### Item 3 - Role in the hosted real-tenant mode  [P]
- Deliverable: `azure_monitor_ai` added to the role list that `dataMode = 'real-tenant'` sets in `infra/demo/main.bicep` and `infra/appservice/main.bicep`, and to `CONNECTOR_ROLES` in `scripts/gates/hosted_demo.py` (`:85`). No new parameter and no new role assignment: the workspace read access is PRP-139's `logAnalyticsWorkspaceIds`, to which the operator adds the workspace behind the Application Insights resource. Goldens updated for that one name.
- Owned files: `infra/demo/main.bicep`, `infra/appservice/main.bicep`, `scripts/gates/hosted_demo.py` (the one tuple), `tests/unit/hosted_demo/**`, `tests/unit/hosted_data_path/**`.
- Must NOT touch: `infra/demo/modules/**`, `infra/helm/**` (Helm takes role names as values, `infra/helm/values.yaml:200-206`; the runbook gives the line), any other logic in `hosted_demo.py`.
- Depends on: PRP-139 merged. The role name is fixed by this PRP, so the lane does not wait for item 2.
- Acceptance criteria: the real-tenant render lists the four connector roles; the demo-mode render is unchanged; no setting carries a key or connection string; the role-assignment scope test from PRP-139 still passes.
- Tests: additions in `tests/unit/hosted_demo` and `tests/unit/hosted_data_path`; `tests/unit/gates/test_hosted_demo_flow.py` passes.
- Pattern references: the role list PRP-139 added to `infra/demo/main.bicep` (read it at session start), `scripts/gates/hosted_demo.py:462-467`.

### Item 4 - Source status for Azure Monitor  [P]
- Deliverable: in `neurosphere_core.sources_status`, the Azure Monitor source is computed from the run status and configuration of kind `azure_monitor_ai` like the other three sources (the fixed `not_connected` with `not_available_in_release` is removed), the new reason codes are registered with plain-language text, and the admin view carries the counts.
- Owned files: `packages/core/neurosphere_core/sources_status/**`, `packages/core/tests/sources_status_core/**`; AMENDED 2026-11-22 (owner sign-off): also `services/api/neurosphere_api/sources_status/models.py` (the connector-kind `Literal` gains `azure_monitor_ai`, nothing else), `services/api/tests/sources_status_api/test_source_status_routes.py` and `tests/security/authz/test_sources_status.py` (the assertions on the old reason), so the item merges green. `openapi.json` is regenerated in item 8.
- Must NOT touch: the rest of `services/api/neurosphere_api/sources_status/**` (routes return what `summarize` gives), the worker `sources_status` package.
- Depends on: PRP-139 merged.
- Acceptance criteria: the four states are reachable for the source in tests; a status of another customer is never read; no id, host or token in the summary.
- Tests: `packages/core/tests/sources_status_core/test_azure_monitor_source.py`; existing suite passes.
- Pattern references: PRP-139's `summarize` and its tests.

### Item 5 - Proof through the real pipeline with the resolver
- Deliverable: an in-process test that takes the recorded fixture, runs `map_genai_row`, wraps the events as the poller does, passes them through the real ingest service (`ingest_events` with a producer that has an `application` source), then `process_batch` with the ingestion fakes, then `AggregateProjection` and `CatalogProjection` built with PRP-137's resolving sources. Cases: alias present; no alias (derived id and draft); the same window twice (no duplicate); a content-bearing fixture row (no content in the archive record); a claim for another customer or cloud (403, nothing published). A parity test asserts the connector's attribute tables equal the edge's.
- Owned files: `tests/unit/azure_monitor_ai/**`, `tests/integration/ingestion/test_azure_monitor_ai_pipeline.py` (marker `integration`, emulator variant, local only).
- Must NOT touch: `tests/integration/ingestion/support.py`, anything of PRP-137.
- Depends on: items 1 and 2; PRP-137 merged.
- Acceptance criteria: the dedupe and agent identity criteria; the test fails if the poster bypasses the edge (checked once by posting a raw row).
- Tests: the files above. The emulator variant is not run in this wave (PRP-71 holds the stack); it is listed for a later local run.
- Pattern references: PRP-137 item 7; `services/workers/tests/ingestion`.

### Item 6 - Stored configuration kind and the admin page
- Deliverable (amended 2026-11-22, no longer waits for PRP-99): the value `azure_monitor_ai` in the `connector_kind` enum of `packages/contracts/schemas/admin/v1/connector-config.schema.json`, regenerated Python and TypeScript, one valid example, and the baseline rule PRP-99 set for additive enum values (if PRP-99 already carries the value, skip this step and say so). Then: `ALLOWED_SETTINGS` entry, `StoredAzureMonitorAiSettings`, `build_azure_monitor_ai` and `azure_monitor_ai_problem` in `stored.py`; a validator requiring a `key_vault_secret` reference in `validators.py`; `resolve_azure_monitor_ai_settings` in `resolve.py`, used by the builder of item 2; `"azure_monitor_ai": "application"` in `OBSERVATION_KINDS`; the kind in the API list filter (`router.py:48`); the kind in `CONNECTOR_KINDS`, the create form (workspace id, domain, intervals, producer and secret reference) and the "First sources" panel of the Connectors page, where the Azure Monitor row gets a Connect action and the access note (which role on the workspace, approved by the owner); mock API rows.
- Owned files: the contract lines above (only in this item), `connector_config/{stored,validators,resolve,__init__}.py`, `services/workers/tests/connector_config_worker/**`, `packages/core/neurosphere_core/admin/connectors/service.py` (one line), `packages/core/tests/admin_connectors/**`, `services/api/neurosphere_api/admin/sources/connectors/router.py`, `services/api/tests/admin_connectors_api/**`, `tests/security/authz/test_admin_connectors.py`, `frontend/src/features/admin/sources/{ConnectorsPage.tsx,types.ts,strings.ts,sources.test.tsx}`, `frontend/tests/mock-api/features/{admin-sources,sourceStatus}.ts`.
- Must NOT touch: any other contract schema; `frontend/src/features/admin/sources/routes.tsx`; navigation files.
- Depends on: items 2 and 4.
- Acceptance criteria: the stored-configuration criterion; an unknown setting, a non-GUID workspace id, more than four workspaces, an interval below the floor or a managed-identity credential in place of the secret reference is a 422 with a pointer; a producer on another cloud or with a non-application source is refused (`cross_cloud`, `producer_source_kind_mismatch`); only customer-level `config.manage` can create the configuration, and denials are audited; `python packages/contracts/scripts/generate.py --check` passes; axe passes on the page.
- Tests: additions to `connector_config_worker` (`test_stored.py`, `test_validators.py`, `test_resolve.py`, `test_factories_stored.py`), `admin_connectors`, `admin_connectors_api`, `tests/security/authz/test_admin_connectors.py`, `sources.test.tsx`.
- Pattern references: `stored.py:93-110,200-232`, `validators.py:49-53`, `resolve.py:136-154`, `ConnectorsPage.tsx` create form.

### Item 7 - Live gate, verify row and runbook
- Deliverable: `hosted_real_tenant.py verify` checks the Azure Monitor source (events of source `azure-monitor-ai` visible through the API with the operator's token, run status `ok` or `partial`) and writes `PASS`, `FAIL` or `OPEN` for row 4; `access-plan` text names the Application Insights workspace as a member of the workspace list. `docs/runbooks/azure-monitor-ai-telemetry.md`: what is read and never read, prerequisites (a workload that sends GenAI spans to a workspace-based Application Insights resource, content recording not required and not read), the access the owner approves, creating the producer and its Key Vault secret, connecting the source in the console, restarting the workers, reading the status and each reason code, the guards and how to change them, one path per workload, declaring an alias for an agent (PRP-137), Government limits, rollback. `docs/evidence/PRP-141/README.md`: the gate, what PASS needs, counts only. Added lines in `docs/connectors/coverage.md` (a caller row), `docs/runbooks/connector-config.md`, `docs/deploy/hosted-real-tenant.md` and `docs/evidence/PRP-139/README.md` (row 4 points here).
- Owned files: `scripts/gates/hosted_real_tenant.py`, `tests/unit/hosted_real_tenant/**`, the runbook, `docs/evidence/PRP-141/**`, the added lines.
- Must NOT touch: `g04_connectors_live.py`, other evidence folders.
- Depends on: items 2, 4 and 6.
- Acceptance criteria: the verify criterion with a fake API; every command in the runbook parses against the real parsers in an offline test; no placeholder looks like a real id; nothing is run against Azure.
- Tests: `tests/unit/hosted_real_tenant/test_verify_azure_monitor.py`, `test_runbook_commands_azure_monitor.py`, `tests/docs`.
- Pattern references: PRP-139 items 6 and 7.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends, `mkdocs.yml` nav line, regenerate Tier 3 (`openapi.json`, `docs/reference/**`, PRP index, status table, execution plan), changelog fragment `changelog.d/PRP-141-azure-monitor-ai-call-telemetry-reader.md`, the G04 note in `docs/RESEARCH-AND-GATES.md` (still OPEN), completion note with the OPEN live gate, the env vars for the operator, the UNVERIFIED items that stayed open, and the product check: can the owner connect the workspace in the console and see their own model calls per agent without editing a file?
- Owned files: Tier-2 lines, this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1 to 7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/azure-monitor services/workers/tests/azure_monitor_ai_role services/workers/tests/worker_roles services/workers/tests/gateway_poll services/workers/tests/connector_config_worker packages/core/tests/admin_connectors packages/core/tests/sources_status_core services/api/tests/admin_connectors_api services/api/tests/authz tests/security/authz tests/unit/azure_monitor_ai tests/unit/hosted_real_tenant tests/unit/hosted_demo tests/unit/hosted_data_path tests/unit/gates tests/contracts services/api/tests/test_openapi_drift.py tests/docs
python packages/contracts/scripts/generate.py --check
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
No emulator run in this wave (PRP-71 holds the compose stack). No cloud call: every Azure response is a recorded fixture and every HTTP client is a fake.

## Migration and rollback
One additive contract enum value; no data migration and no new container. The role is part of `all` and idles until configured, so existing deployments are unchanged. Events it posts are ordinary telemetry events under source `azure-monitor-ai`. Rollback: disable the stored configuration in the console and restart the workers (the role idles, the watermark stays), or remove the role name from the role list, or revert the PR. Events already ingested stay and age out with normal retention; they can be told apart by their source id. The workspace role assignment is removed with the line PRP-139's access evidence lists.

## Live and open gates
Gate "Azure Monitor AI call telemetry" (operator-run, `NS_LIVE_APPROVED=1`, the owner's approval of the workspace read assignment, a real-tenant deployment from PRP-139, Commercial only). OPEN: nothing here is run by this PRP. It is PASS only when `docs/evidence/PRP-141/` holds, from one environment:
1. The run status of the source is `ok` or `partial` and the event count is above zero. OPEN.
2. At least one model call from the owner's workload is visible on a dashboard with latency, outcome, model and token counts. OPEN.
3. At least one agent has a per-agent series, by alias or by derived id. OPEN.
4. A scan of the archived records of the run finds no content field. OPEN.
5. A scrubbed real response replaces the hand-built fixture, and each UNVERIFIED item is marked confirmed or corrected in the README. OPEN.
Passing this gate closes row 4 of PRP-139's gate (`PRP-139`, "Live and open gates"). Government is not part of this gate and stays unverified. G04 (`docs/connectors/coverage.md:9-19`) stays OPEN and is not replaced by this gate.

## NOT building
Content capture of any kind; classic Application Insights or the app-id query API; Azure Monitor metrics; arbitrary or generated queries, or a query setting an admin can type; instrumentation of customer workloads; cost records from spans; an automatic alias between Foundry agents and telemetry agents; detection of a workload that uses both the push path and this reader; a historical backfill beyond the lookback cap; more than one configuration of the kind per customer (the admin service allows one, `admin/connectors/service.py:14`); a Government live check; the connector runner wrapper (PRP-117); a new container, permission, route or navigation entry.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 5, 6, 7, 9 and 12 are ASSUMPTIONS for plan approval; twelve Azure facts are UNVERIFIED and are checked against Learn before item 1 starts)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | in-progress | implementer worktree (sonnet) | Learn names pasted into brief; dispatched 2026-11-22 |
| 2 | todo | | |
| 3 | in-progress | implementer worktree (sonnet) | dispatched 2026-11-22 |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | enum added here (amended) |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- UNVERIFIED items still open:
- Env vars for the operator:
- Follow-up issues:
- Product check (can the owner connect the workspace and see their own AI calls without editing files):
