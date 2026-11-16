### Added
- PRP-48: role-gated route category (`require_role`), so `GET /api/v1/workspaces/{role}` is tenancy-bound and records a denial on `role_not_held`; `/me/domains` documents the empty-200 case and logs one count-only warning when the catalog page cap is hit.
- PRP-48: `require_deployment_admin` (`authz/deployment_scope.py`) gates every MCP admin route, deploy scan and plan, and the emergency-disable kill switch on the deployment-scoped admin assignment; `config.manage` in an ordinary domain no longer reaches them (403 `customer_scope_required` plus a denial record). Operators re-run `scripts/sandbox/sbx_grant_operator.py` on hosted environments.
- PRP-48: allowed catalog searches and dashboard reads append one `allowed` audit record (actor pseudonym, operation, domain, no query text); a failed audit write is logged and never blocks the read.
- PRP-48: `RESERVED_CHAIN_NAMES` and `is_reserved_chain_name` in core audit; a dotted `NS_AUTH_CUSTOMER_ID` fails the `authz` component with `customer_id_invalid`; denials whose member chain cannot be encoded fall back to `<customer>.authz-denials`.

### Changed
- PRP-48: injection corpus README states where consumer suites live and that the stub's `follow_instruction` abstains are vacuous until a real adapter exists.
