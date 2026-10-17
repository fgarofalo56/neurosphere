# Connector coverage (PRP-09)

Status date: 2026-10-17. Every "observed" date below is the day the cited page was fetched while
writing this file. Rule for this document: **no invented APIs**. A target is "built" only if it
cites a documented API here; otherwise it is a documented gap.

## Gate status

**G04 (provider/API/license coverage) remains OPEN.** This file is the coverage inventory. No
live contract run against Azure Monitor, Foundry, or Azure Cost Management exports has happened
(live runs need `NS_LIVE_APPROVED=1` and an approved environment), so there is no evidence under
`docs/evidence/G04/`. Unbuilt targets stay open by design. Nothing here claims FedRAMP
authorization, ATO, or Commercial/Government parity: availability, feature maturity, and
authorization are separate gates.

## Coverage table

| Target | Status | Documented API (URL, observed) | Latency / granularity | Licence and limits | What would unlock it (if not built) |
|---|---|---|---|---|---|
| Azure Monitor / Application Insights / Log Analytics | built (PRP-09 item 4) | Azure Monitor Logs Query API: <https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview> (2026-10-17) | Per poll: freshness and coverage are reported by the connector; polling is bounded by window and page budget. Details are owned by item 4 and reconciled at merge. | Query API is rate- and size-limited; partial coverage is reported, never looped. Government availability: configuration only, not live-tested. | n/a |
| Microsoft Foundry (discovery) | built (PRP-09 item 5) | Foundry project data-plane REST reference, API version `v1` ("Agents - list agents" `GET {endpoint}/agents`, "Deployments - list" `GET {endpoint}/deployments`, scope `https://ai.azure.com/.default`): <https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/aiproject>; project endpoint form: <https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview>; Government endpoints and scope: <https://learn.microsoft.com/en-us/azure/foundry/concepts/foundry-azure-government>; Government Agent Service features: <https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-government> (all 2026-10-17) | Point-in-time snapshot of agents and model deployments; freshness lag is unknown (null), not measured. Each list is capped (default 500 items) and bounded by a page budget (default 10 pages); hitting either flags truncated and partial coverage. | Plain `httpx` against the documented REST paths; the Python `azure-ai-projects` SDK is not used because its transitive dependencies fail the repo licence gate. The agents list response is documented only as an object, so `data`/`has_more`/`last_id` are read defensively; deployments use the documented `PagedDeployment` (`value`, `nextLink`). The `Foundry-Features` preview opt-in header is never sent. 429 is retried with a capped backoff, then reported as `rate_limited`. Read-only, `advisory=true`. | n/a |
| Azure billing / Cost Management | built (PRP-09 item 5) | Cost Management exports (manifest, CSV or Parquet, partitioning, up to 24 h to complete): <https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-improved-exports>; cost details fields: <https://learn.microsoft.com/en-us/azure/cost-management-billing/automate/understand-usage-details-fields> (both 2026-10-17) | One row per usage day per resource per meter (as the export reports). Never apportioned below that. Export completion latency is documented as up to 24 h (a maximum, not a measured lag). | Reads CSV (plain or gzip) only; Parquet is reported `capability_unavailable`. Blank or unparseable cost is null, never 0. Actual vs amortized are separate exports declared by the operator; the file does not say which. Exports default to `estimated`; `invoiced` is an operator assertion for a closed period. Government availability of exports not verified; the manifest lists Commercial only. | n/a |
| Generic OpenTelemetry / CloudEvents | built (PRP-09 item 3) | OTLP specification: <https://opentelemetry.io/docs/specs/otlp/>; CloudEvents spec: <https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md> (both 2026-10-17) | Push; per-event. Details are owned by item 3 and reconciled at merge. | Prompt and response bodies dropped by default; missing fields are null. | n/a |
| Microsoft Graph / Microsoft 365 (Copilot usage) | not built | Admin-center Copilot usage report: <https://learn.microsoft.com/en-us/microsoft-365/admin/activity-reports/microsoft-365-copilot-usage>; Copilot APIs overview: <https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/copilot-apis-overview> (both 2026-10-17; located by search, not evaluated) | Not evaluated. | Not evaluated (permissions, tenant admin consent, retention, user-level privacy). | The specific Graph endpoint or Copilot API page with its permission scope, granularity (per user or aggregate), freshness, privacy treatment of user-level data, and GCC/GCC High availability, plus an admin-authorized test tenant. |
| GitHub Copilot reports | not built | GitHub REST docs, Copilot usage metrics: <https://docs.github.com/en/rest/copilot/copilot-usage-metrics> (page exists, 2026-10-17; content not evaluated) | Not evaluated. | Not evaluated (plan and org/enterprise admin requirement, retention). | A reviewed endpoint list with required token scope, plan eligibility, granularity, freshness, and GitHub Enterprise Server/Cloud with data residency availability, plus an authorized org. |
| Anthropic | not built | Usage and Cost Admin API: <https://platform.claude.com/docs/en/build-with-claude/usage-cost-api> (2026-10-17) | Documented time buckets of `1m`, `1h` or `1d`. | Needs an Admin API credential (not workspace keys); unavailable for individual accounts. Not built because PRP-09 builds only four reference connectors (clarification 2), not because the API is undocumented. | An approved Admin credential in the vault, a reviewed field list and error/rate-limit behavior, and an operator-approved live contract run. |
| Google (billing export) | not built | Cloud Billing export to BigQuery: <https://cloud.google.com/billing/docs/how-to/export-data-bigquery> (page exists, 2026-10-17; content not evaluated) | Not evaluated. | Not evaluated. Model-level (Gemini/Vertex) usage signals were not reviewed at all. | A reviewed export schema that identifies model/API usage, its granularity and delay, IAM scope, and an authorized project. |
| xAI | **GAP: not implemented** | None cited. The public docs landing page exists (<https://docs.x.ai/docs/overview>, 2026-10-17) but no usage or billing API was reviewed. | Unknown. | Unknown. | A documented, admin-authorized usage or billing API (URL, auth, fields, granularity, rate limits, terms). No code and no guessed endpoints exist. |
| Palantir | **GAP: not implemented** | None cited. No documented usage or cost API was identified or reviewed. | Unknown. | Unknown. | A documented, customer-authorized API for AI usage or cost with auth, schema, granularity and terms. No code and no guessed endpoints exist. |
| Cursor | **GAP: not implemented** | None relied on. An Admin API docs page exists (<https://cursor.com/docs/account/teams/admin-api>, 2026-10-17) whose navigation lists usage and spending sections; it was not reviewed for fields, auth, plan eligibility, rate limits or terms. | Unknown. | Unknown. | A review of that page's endpoints (auth, plan requirement, granularity, freshness, rate limits, terms) and an admin-authorized team. No code and no guessed endpoints exist. No endpoint agent or desktop collector will be built without consent. |
| Claude Code | not built (no dedicated connector) | Monitoring docs: <https://code.claude.com/docs/en/monitoring-usage> (page exists, 2026-10-17; not evaluated) | Not evaluated. | Not evaluated. | A reviewed mapping of the documented telemetry export to `TelemetryEvent` (it may be receivable by the generic OTel connector; that is not claimed here) and an admin-authorized deployment. |

## Foundry capability reporting by cloud

The discovery connector always returns the full capability list, never an empty list for an
absent capability. Source: Foundry Agent Service feature availability in Azure Government,
<https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-government>, observed
2026-10-17 (the PRP records the same findings retrieved 2026-10-06 and 2026-10-08).

| Capability | Azure Government |
|---|---|
| Prompt agents, code interpreter, file search, Azure AI Search, Azure Functions, function calling, MCP servers, OpenAPI tool | available |
| Workflows, custom code interpreter | preview |
| Hosted agents, voice prompt agents, web search, Grounding with Bing, image generation, browser automation, computer use, Microsoft Fabric tool, SharePoint tool, agent-to-agent (A2A) | unavailable (each with a reason and the source URL) |

Commercial capabilities are reported `unknown`: this connector did not enumerate the Commercial
matrix and does not guess. Government endpoint `https://{resource}.services.ai.azure.us/api/projects/{project}`
and token scope `https://ai.azure.us/.default` come from the pages above. The table is
documentation, not a live probe; Government behavior of the connector itself is untested (G04).

## Billing vs ledger variance

`build_variance_report` (billing package) compares billing aggregates with ledger estimates at
the granularity the export reports, and writes that granularity into the report. It compares; it
does not add billing to gateway/application observations. Null amounts stay null (variance
unknown, not 0), estimated and invoiced stay on separate lines, and different currencies are not
compared.
