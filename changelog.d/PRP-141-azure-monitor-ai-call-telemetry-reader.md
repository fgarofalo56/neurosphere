### Added
- Azure Monitor AI call telemetry reader (PRP-141): a new worker role `azure_monitor_ai` reads
  GenAI spans (model calls, tool calls, agent runs) from the Log Analytics workspace behind a
  workspace-based Application Insights resource, with the deployment's managed identity, through
  two fixed queries (`AppDependencies`, `AppRequests`). Each row becomes a metadata-only
  `TelemetryEvent` (ids, span kind, provider, model, outcome, duration, tokens, sampling,
  external agent id) and is posted to the ingest edge as a registered producer, so authorization,
  dedupe, the archive and PRP-137's agent identity resolution are the ones every source uses.
  Prompt, response and tool-call content and personal data are never selected (tested allowlist
  and denylist).
- Watermark per workspace and span table, a re-read overlap, and per-tick query and event budgets
  with run status reasons `query_budget_exhausted`, `event_budget_exhausted`, `rate_limited`,
  `stalled`, `ingest_failed`, `cloud_mismatch`, `refused_government_unverified`,
  `source_unreachable` and `partial_results`.
- Stored connector kind `azure_monitor_ai` (additive `connector_kind` enum value) configured from
  the admin Connectors page, with a Key Vault producer secret reference; the role idles until it
  is configured.
- The sources status summary now computes the Azure Monitor source from the role's run status
  instead of reporting it as not available in this release.
- Real-tenant mode starts the role with the other three connector roles; `hosted_real_tenant.py
  verify` checks row 4 (Azure Monitor) and `access-plan` names the Application Insights
  workspace.
- Runbook `docs/runbooks/azure-monitor-ai-telemetry.md`; operator live gate in
  `docs/evidence/PRP-141/README.md` (OPEN).
