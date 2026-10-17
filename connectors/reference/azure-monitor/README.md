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
