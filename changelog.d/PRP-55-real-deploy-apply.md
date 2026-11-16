### Added
- PRP-55: real deploy apply behind `NS_DEPLOY_APPLY_ENABLED`. A durable plan-approval store (`deploy_plan_approvals` Cosmos container, shared by API and workers), an allowlisted ARM provisioner (storage, Event Hubs, Log Analytics) with `neurosphere:created-by` tags, bounded LRO polling and the deployment cloud's management host, a bearer Fabric transport gated by the capability matrix, verify-by-change with register rows, customer binding, and `scripts/gates/deploy_apply_live.py` (refuses without `NS_LIVE_APPROVED=1`; the live run is OPEN, PRP-64). The Helm chart and App Service profile now pass the apply opt-in to the workers too, still off by default (PR #314).

### Changed
- Deploy plan approvals are no longer held in API memory: approve is create-only per customer and plan, and apply routes are async. Re-approve plans after upgrading.
