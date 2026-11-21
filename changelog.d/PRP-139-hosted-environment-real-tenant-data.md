### Added
- Hosted "real tenant" data mode (PRP-139): `infra/demo/main.bicep` and `infra/appservice/main.bicep`
  take `dataMode` (`demo` default, `real-tenant`) and `customerId`. Real-tenant mode sets the
  customer id on both sites, turns the `foundry_discovery`, `gateway_poll` and `billing_export`
  worker roles on and sets `NS_HOSTED_DATA_MODE`. Commercial only; Government is refused.
- Per-resource read access for the gateway path in `connector-rbac.bicep`: Log Analytics Data
  Reader for the workers identity on one workspace and API Management Service Reader for the API
  identity on one service, through the new `logAnalyticsWorkspaceIds` and `apimServiceIds`
  parameters. No assignment at resource-group or subscription scope.
- `scripts/gates/hosted_real_tenant.py` with `access-plan` (read-only plan of role assignments),
  `access-apply` (applies only assignments approved one by one), `bootstrap-worker` and `verify`
  (PASS, FAIL or OPEN per source; a source that is not connected is OPEN, never PASS).
- `scripts/gates/hosted_purge_synthetic.py` with `plan` and `apply`: a dry-run-first, confirmed
  removal of the synthetic estate, scoped to the retired synthetic customer, with counts-only
  evidence.
- Connector run status: each connector role stores the state, reason code, last success time and
  counts of its last run. `GET /api/v1/sources/status` gives any domain reader the state of the
  four first sources; `GET /api/v1/admin/sources/status` adds reason codes and counts for
  customer-level administrators.
- Connectors admin page: a "First sources" panel with a Connect action per source, a run status
  column with the reason in words, and a note on the access each source needs.
- Empty pages now say what is missing and link administrators to the Connectors page (others are
  told to ask an administrator), instead of a bare "no data" text or a placeholder.
- Runbook `docs/deploy/hosted-real-tenant.md` and the operator gate definition in
  `docs/evidence/PRP-139/README.md`. The gate is OPEN: nothing was run against Azure.

### Changed
- `scripts/gates/hosted_demo.py plan` and `deploy` now require `--data-mode`, and `--customer-id`
  reaches both the generated parameters and the registration. The `deploy-hosted.yml` pipeline
  reads the mode from the repository variable `NS_HOSTED_DATA_MODE` and fails when it is unset.
- `scripts/gates/hosted_demo_seed.py` requires `--demo-environment <deployment id>` and refuses a
  real-tenant registration, so a real environment cannot be re-seeded with synthetic data.
