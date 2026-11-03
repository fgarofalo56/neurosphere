# Feature to persona map

Status: draft. Every row is synthetic sandbox only. "Merged" means the route is in `frontend/src/app/route-manifest.json`.

| Feature | Route | Persona(s) | Script | Walkthrough | Merged |
|---|---|---|---|---|---|
| Persona workspace | `/workspaces/<persona>` | all five | each script, step 1 | `docs/walkthroughs/<persona>.md` | yes |
| Cost dashboard | `/dashboards/cost` | Viewer | [viewer](viewer.md) | `docs/walkthroughs/viewer.md` | yes |
| Latency dashboard | `/dashboards/latency` | Analyst | [analyst](analyst.md) | `docs/walkthroughs/analyst.md` | yes |
| Live map (browse only, no spike overlay) | `/map` | Viewer | [viewer](viewer.md) | `docs/walkthroughs/viewer.md` | yes |
| Catalog | `/catalog` | Viewer | [viewer](viewer.md) | `docs/walkthroughs/viewer.md` | yes |
| Trace replay | `/replay/traces` | Analyst | [analyst](analyst.md) | `docs/walkthroughs/analyst.md` | yes |
| Saved reports | `/reports` | Analyst | [analyst](analyst.md) | `docs/walkthroughs/analyst.md` | yes |
| Stale agents (dry-run and confirm mark-stale tool, needs `catalog.curate`; not on the demo path) | `/catalog/stale-agents` | Steward | [steward](steward.md), not on demo path | `docs/walkthroughs/steward.md` | yes |
| Recommendations and review | `/recommendations`, `/review`, `/review/item` | Steward | [steward](steward.md) | `docs/walkthroughs/steward.md` | yes |
| Execution control | `/admin/execution-control` | Admin | [admin](admin.md) | `docs/walkthroughs/admin.md` | yes |
| MCP administration | `/mcp-admin` | Admin | [admin](admin.md) | `docs/walkthroughs/admin.md` | yes |
| Sandbox status | `/sandbox` | Admin | [admin](admin.md) | `docs/walkthroughs/admin.md` | yes |
| Gateways and capability matrix | `/gateways`, `/deploy/capabilities` | Admin | [admin](admin.md) | `docs/walkthroughs/admin.md` | yes |
| Audit trail | `/audit` | Auditor | [auditor](auditor.md) | `docs/walkthroughs/auditor.md` | yes |
| Actions and reconciliation | `/actions`, `/reconciliation` | Steward (the Auditor role gets HTTP 403 on these screens) | none, not on demo path (see [auditor](auditor.md)) | `docs/walkthroughs/auditor.md` | yes |
| Governed copilot chat | none in route manifest | none | none | none | planned |
