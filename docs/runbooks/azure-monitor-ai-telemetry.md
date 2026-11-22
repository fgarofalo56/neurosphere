# Azure Monitor AI call telemetry

The `azure_monitor_ai` worker role (PRP-141) reads GenAI spans that a workload already sends to a
workspace-based Application Insights resource, and posts them to the ingest edge as ordinary
telemetry events under the source `azure-monitor-ai`. Nothing here was run against Azure: the live
gate is OPEN (`docs/evidence/PRP-141/README.md`). Commercial only for the gate; Government is below.

## 1. What is read and never read

Read, through the Log Analytics workspace query API, from the `AppDependencies` (client and
internal spans) and `AppRequests` (server spans) tables, with fixed queries:

- Columns: `TimeGenerated`, `Id`, `OperationId`, `ParentId`, `Success`, `DurationMs`, `ItemCount`,
  `AppRoleName`.
- Span attributes, each extracted by name from `Properties`: `gen_ai.operation.name`, the agent id
  (`gen_ai.agent.id`), provider, request model, input and output token counts, and cached and
  reasoning token counts. The list is the constant `GENAI_ATTRIBUTE_KEYS`; the attribute bag is
  never projected as a whole.

Never read (the tested constant `CONTENT_DENYLIST`): prompts, completions, input and output
messages, system instructions, tool definitions, tool call arguments and results, evaluation
explanations, `gen_ai.conversation.id`, user and end-user ids, email, name, client address,
`Status.message`, command text, target hosts and URLs, the trace, exception and event tables.
Content recording on the workload is **not required** and is never read; leave it off.

When a row carries `ItemCount` above 1 the event records `sampling.rate = 1 / count`; counts are
never multiplied up.

## 2. Prerequisites

- A workload that sends GenAI spans to a workspace-based Application Insights resource. Classic
  Application Insights and the app-id query API are not used.
- The tables are on the Analytics plan (Basic and Auxiliary are not supported).
- A real-tenant deployment (`docs/deploy/hosted-real-tenant.md`) with the workers running.
- Data arrives in about 2 to 5 minutes; a first run can report no events for a few minutes.

## 3. The access the owner approves

One role assignment, at the scope of **that workspace only** (the workspace behind the
Application Insights resource): **Log Analytics Data Reader**, a built-in role, definition id
`3b03c2da-16b3-4a49-8834-0f8130efdd3b`, for the workers identity. It is the role PRP-139 already
assigns for gateway logs. Add **Privileged Monitoring Data Reader** only if the tables are
protected (Learn: Log Analytics API access); the verified role table does not carry it, so the
owner assigns it by hand.

The workspace goes into the same list PRP-139 uses, `logAnalyticsWorkspaceIds`
(`--log-analytics-workspace-ids`), so the plan shows one row for it. The plan is offline and
changes nothing:

```bash
MSYS_NO_PATHCONV=1 python scripts/gates/hosted_real_tenant.py access-plan --log-analytics-workspace-ids <workspace-resource-id>
```

Approve and apply with `access-apply` exactly as in `docs/deploy/hosted-real-tenant.md`. A role
assignment can take up to 10 minutes to apply.

## 4. Create the producer and connect the source

1. In the console, create a producer with one source of kind `application` and source id
   `azure-monitor-ai`. Store its secret in Key Vault; keep the secret URI, never the value.
   Grant the workers identity `Key Vault Secrets User` on that vault
   (`docs/runbooks/connector-config.md` section 2).
2. Open Admin, Sources, Connectors, and connect the source `azure_monitor_ai`. Settings:
   `workspace_ids` (1 to 4 workspace GUIDs), one domain, `producer_id`, `source_id`
   (`azure-monitor-ai`), the credential as a `key_vault_secret` reference, and any guard from
   section 6. Only one configuration of this kind is allowed per customer.
3. **Restart the workers.** The stored configuration is read at start; there is no hot reload.
4. Wait one interval (default 5 minutes) and read the status (section 5).

For an env-mode deployment (`NS_WORKER_CONNECTOR_CONFIG_SOURCE=env`) set these on the workers
instead: `NS_AZURE_MONITOR_AI_WORKSPACE_IDS`, `NS_AZURE_MONITOR_AI_DOMAIN_ID`,
`NS_AZURE_MONITOR_AI_PRODUCER_SECRET` (a vault reference in production, never a literal),
`NS_AZURE_MONITOR_AI_PRODUCER_ID`, `NS_AZURE_MONITOR_AI_SOURCE_ID` and `NS_API_BASE_URL`, plus
the optional `NS_AZURE_MONITOR_AI_*` guards below. With none of them set the role idles. Setting
only some of them is refused at start.

Helm: the role name `azure_monitor_ai` goes in `workers.roles` (`NS_WORKER_ROLES`) of the values
file. It is part of `all`, but the chart does not run connector roles by default.

## 5. Read the status

Admin, Sources, Connectors shows the run state (`ok`, `partial`, `failed`, `idle`,
`not_configured`), a reason code and counts. The same data is at `GET /api/v1/admin/sources/status`
(`connectors[]`, kind `azure_monitor_ai`). Counts include `events_posted`; no id, host or value is
ever in a status.

| Reason code | Meaning and what to do |
|---|---|
| `source_access_denied` | The workers identity cannot read the workspace (401 or 403). Check the role and scope in section 3 and wait up to 10 minutes after assigning. |
| `source_unreachable` | The query API did not answer. Check network egress to the Log Analytics host; it retries on the next tick. |
| `ingest_failed` | The ingest edge refused or failed the batch. Check the producer, its secret and `NS_API_BASE_URL`. The watermark did not move, so nothing is lost. |
| `rate_limited` | The query API answered 429 (200 requests per 30 s per user). Completed slices are kept; raise the interval or lower the query budget. |
| `stalled` | A time slice stays truncated at the smallest size. The watermark holds, nothing is skipped; narrow the workload's output or the window. |
| `query_budget_exhausted` | The tick hit `max_queries_per_tick`. The rest is read on the next tick. |
| `event_budget_exhausted` | The tick hit `max_events_per_tick`. The rest is read on the next tick. |
| `partial_results` | Some workspaces or slices answered and others did not (state `partial`). |
| `cloud_mismatch` | The configuration or producer names the other cloud. Fix the cloud; nothing is rerouted. |
| `refused_government_unverified` | Government without the explicit opt-in (section 8). |
| `not_configured` | No stored or environment configuration; the role idles. |

## 6. The guards and how to change them

Defaults and bounds (settings `NS_AZURE_MONITOR_AI_*`, or the same names in the stored settings):

| Setting | Default | Bound |
|---|---|---|
| `interval_seconds` | 300 | at least 60 |
| `window_seconds` (span one poll reads) | 3600 | 60 to 86400 |
| `lookback_seconds` (first poll) | 86400 | 60 to 604800 (7 days); no backfill beyond |
| `overlap_seconds` (re-read before the watermark) | 600 | 0, and below `window_seconds` |
| `max_queries_per_tick` | 24 | 1 to 200 |
| `max_events_per_tick` | 20000 | 1 to 100000 |
| `batch_size` | 100 | 1 to 500 |
| `workspace_ids` | none | 1 to 4 GUIDs |
| `app_role_names` | all | optional list; other roles are skipped after the query |

Change a guard by replacing the stored configuration in the console, then restart the workers.
Re-reads are safe: event ids are deterministic, so the overlap does not double count.
The query cost on the Analytics plan is UNVERIFIED; keep the defaults until the live gate.

## 7. One path per workload, and agent aliases

A workload that **also pushes OTLP** to the ingest edge is counted twice: the same span has the
same event id under two source ids, and nothing detects it. Use one path per workload.

The reader sets the external agent id from `gen_ai.agent.id` only. An agent that Foundry discovered
is not matched automatically, because aliases are keyed by source id; until a steward declares one
it shows as a derived draft. Declare it with PRP-137's route
(`PUT /api/v1/agent-identity/domains/{domain}/aliases`, `docs/runbooks/agent-identity-resolution.md`)
with `source_id` `azure-monitor-ai`. Whether the Foundry agent id equals `gen_ai.agent.id` is
UNVERIFIED.

Rows from Copilot Studio environment telemetry use GUID-form ids and are skipped and counted, not
read. A row whose id is not W3C hex is skipped the same way.

## 8. Government

Not part of the live gate and unverified. The Government query host is documented, but its token
audience and Foundry tracing in Government are UNVERIFIED. The role refuses Government unless
`allow_unverified_government` is set explicitly (reason `refused_government_unverified`). Nothing
is ever routed to Commercial to fill a gap.

## 9. Verify

After the first run, with the operator signed in (`NS_LIVE_APPROVED=1` and the deployment id set;
see `docs/deploy/hosted-real-tenant.md`):

```bash
python scripts/gates/hosted_real_tenant.py verify --api-audience <api-audience>
```

Row 4 is PASS only when the run status is `ok` or `partial`, `events_posted` is above zero and the
latency dashboard shows a known point. A failed or idle run, or no events, is FAIL; not configured
or no approval is OPEN. No route filters events by source, so the check reads the admin source
status and the latency dashboard.

## 10. Rollback

Disable the stored configuration in the console and restart the workers: the role idles and the
watermark stays. Or remove `azure_monitor_ai` from `workers.roles`, or set
`NS_WORKER_CONNECTOR_CONFIG_SOURCE=env` with no `NS_AZURE_MONITOR_AI_*` variables. Events already
ingested stay and age out with normal retention; tell them apart by the source id
`azure-monitor-ai`. Remove the role assignment of section 3 with the access evidence line.
