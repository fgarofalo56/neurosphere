# System status, first-run checklist and stored feature settings

The system administration API (PRP-45) answers three operator questions in one authenticated
place: what is configured, what is off and why, and what to do next. It also stores the runtime
feature settings that used to be environment variables plus a redeploy: the copilot model
endpoint, the evaluation judge, search, deployment scan, the NeuroSphere MCP server and
write-target entries.

All routes are under `/api/v1/admin/system` and need the **deployment-scoped admin**:
`config.manage` held on the customer-control domain
(`<cloud>:<customer>:neurosphere:domain:customer-control`). `config.manage` in an ordinary domain
is not enough: the answer is 403 `customer_scope_required` and the denial is recorded on the audit
trail. Reads need it too, because these settings act on the whole deployment.

| Method | Path | Notes |
|---|---|---|
| GET | `/status` | every component and startup step, environment probe codes |
| GET | `/checklist` | the first-run checklist below |
| GET | `/settings` | the six setting keys with source and revisions |
| GET | `/settings/{key}` | one key and its stored entries (`ETag` for single-document keys) |
| PUT | `/settings/{key}` | store a value; `If-Match` required; returns the diff and the revision |

## Status

`GET /status` lists every component of the composition registry (the one `/readyz` reads) with
`state` (`ok`, `failed`, `disabled`, `not_built`), `required`, the failure `reason` code and
`blocks_readiness`, plus the `cosmos_containers` startup step, the environment probe codes
(`cosmos`, `eventhubs`, `blob`: `ok`, `timeout`, `connection_refused`, `unavailable`) and the
state of the stored-settings read. The body holds names and reason codes only: never a
configuration value, a host or a secret.

## First-run checklist

`GET /checklist` returns one `FirstRunChecklistItem` (contract `admin/v1`) per entry. Status is
`complete`, `missing`, `disabled`, `not_applicable` or `error`; every status except `complete`
carries a reason code. The item ids are stable:

| Item id | Component | Complete when | Typical reasons otherwise |
|---|---|---|---|
| `optional.copilot` | `copilot` | the component is `ok` | `component_disabled`, `not_built`, a failure code |
| `optional.mcp_server` | `mcp_server` | as above | as above |
| `optional.ingest` | `ingest` | as above | as above |
| `optional.scan` | `scan` | as above | as above |
| `optional.gateway_plane` | `gateway_plane` | as above | as above |
| `optional.analytics_adapter` | `analytics_adapter` | as above | as above |
| `optional.policy_admin` | `policy_admin` | as above | as above |
| `optional.revocation_service` | `revocation_service` | as above | as above |
| `optional.admin_connectors` | `admin_connectors` | as above | as above |
| `optional.admin_producers` | `admin_producers` | as above | as above |
| `optional.admin_platform` | `admin_platform` | as above | as above |
| `optional.audit_siem` | `audit_siem` | as above | as above |
| `optional.admin_system` | `admin_system` | as above | as above |
| `optional.agent_matcher` | `agent_matcher` | as above | as above |
| `optional.sources_status` | `sources_status` | as above | as above |
| `optional.agent_identity` | `agent_identity` | as above | as above |
| `optional.interaction_capture` | `interaction_capture` | as above | as above |
| `optional.governance_policy` | `governance_policy` | as above | as above |
| `optional.notifications` | `notifications` | as above | as above |
| `ingest.producers` | `ingest` | ingestion is composed with producers | `ingest_producers_unconfigured` |
| `write_targets.registered` | `write_targets` | a write connector is registered | `write_targets_unconfigured`, `write_targets_stored_not_registered` |
| `stored_settings.store` | `admin_config` | the stored-settings read at startup succeeded | `stored_settings_unavailable`, `stored_settings_unconfigured` |
| `auth.customer_binding` | `authz` | `NS_AUTH_CUSTOMER_ID` is set | `local_default_customer` (not applicable, local only), `customer_id_missing` |

### Optional components

An optional component that is `disabled` is off on purpose; `failed` blocks readiness and names
the reason. Required components are in `/status`, not in the checklist.

### Ingest producers

Producers are managed in the producer admin (PRP-41, `/api/v1/admin/sources/producers`) and
ingest is configured as in `runbooks/ingest.md`.

### Write targets

Write targets are still registered from `NS_FOUNDRY_*` / `NS_APIM_*` (`runtime-composition.md`).
Entries stored under `write_targets` are validated and listed but **not registered yet**: PRP-54
turns them into registered connectors. The checklist reports `write_targets_stored_not_registered`
for that case.

### Stored settings store

The stored settings live in the `admin_config` Cosmos container (kind `system_setting`). If the
store cannot be read at startup (bounded timeout), every builder uses env and the item reports
`stored_settings_unavailable`: env is operator controlled, so a store outage cannot widen access.

The unavailable snapshot is cached for the process lifetime: after a transient store outage at
startup, stored values apply only after another restart once the store is reachable.

### Customer binding

Outside `NS_ENV=local` the API needs `NS_AUTH_CUSTOMER_ID`; local runs fall back to the synthetic
sandbox customer.

## Stored settings

Six keys:

| Key | Applied by | Stored fields used | Env it replaces |
|---|---|---|---|
| `copilot` | API copilot builder | endpoint, deployment, API version; `enabled: false` = disabled | `NS_COPILOT_ENDPOINT`, `_DEPLOYMENT`, `_API_VERSION`, `_MODE` (region, model feature, SKU and scope stay env; an enabled stored value keeps the env mode or uses `approved_endpoint`) |
| `judge` | worker `evaluation` role | endpoint, deployment, API version; `enabled: false` = recorded-fixture judge | `NS_WORKER_EVAL_JUDGE`, `_JUDGE_ENDPOINT`, `_JUDGE_DEPLOYMENT`, `_JUDGE_API_VERSION` |
| `search` | API data builder (catalog search) | service (from the endpoint host), index; `enabled: false` = no search | `NS_SEARCH_PROVIDER`, `_SERVICE`, `_INDEX` (region and refresh stay env) |
| `scan` | API scan bootstrap | `enabled` (interval and scopes are stored for a scheduler) | `NS_SCAN_ENABLED` |
| `mcp_server` | API MCP builder | endpoint = resource URL; `enabled: false` = disabled | `NS_MCP_RESOURCE_SERVER_URL` (audiences, scope, hosts stay env) |
| `write_targets` | nobody yet (PRP-54) | one entry per `target_kind` (`apim`, `foundry`) | none yet |

**Precedence.** A stored value, when present and valid, is passed as init arguments to the same
settings class the builder already uses, so it beats env and the same validation runs. With no
stored value every builder behaves exactly as before (env).

**Restart rule.** Stored values apply at startup only; there is no hot reload. `/settings` shows
`stored_revision` (now) and `applied_revision` (when this process started); `restart_required` is
true while they differ. Restart the API (and the workers for `judge`) to apply. The worker reads
the store when the `evaluation` role starts; the API's `applied_revision` for `judge` is the API's
own start.

**Writing.** `PUT /settings/{key}` takes a `SystemSetting` body (contract `admin/v1`) whose
`setting_key` is the key (`write_target` for `write_targets`). Concurrency follows the catalog
convention: a missing `If-Match` is 422 `invalid_schema` (`if_match_required`), a stale one is 409
`stale_version`. When nothing is stored yet the `ETag` is `"absent"`; send it to create the value.
For `write_targets` the `If-Match` is the ETag of that `target_kind`'s entry (or `"absent"`).
Every write is audited on `<customer>.admin-config` (key, document id, version and the changed
pointers; never a value) and returns the diff. To turn a feature off, store it with
`enabled: false` and restart; to go back to env-only, revert this PRP (stored documents are then
ignored).

**Refusals (422, nothing stored).**

- a field whose name contains `KEY`, `SECRET` or `PASSWORD` (`credential_in_setting`), other than
  `setting_key` and a `credential.secret_uri` reference: credentials are references only (a Key
  Vault secret URI or a managed-identity client id), never values;
- a Commercial endpoint in a Government deployment or the reverse (`cross_cloud`), an unapproved
  model host (`endpoint_not_approved`), a search endpoint not on the deployment cloud's search
  suffix (`search_endpoint_invalid`), a Key Vault on another cloud's suffix;
- a Key Vault credential for `copilot` or `judge` (`managed_identity_required`): the model
  endpoints are called with the workload identity;
- a value the builder's own settings class refuses (`<key>_settings_invalid`, for example an MCP
  endpoint whose path is not `/mcp`).

Copilot prerequisites: an enabled stored `copilot` setting on an env mode of `disabled` is coerced
to `approved_endpoint`, which still needs the region, model feature and SKU env fields
(`NS_COPILOT_*`). On a bare deployment the PUT is refused with `copilot_settings_invalid` until
those env fields are set.

## Environment variables

No new `NS_*` variable. The stored-settings read uses the existing `NS_AUTH_CUSTOMER_ID`,
`NS_STORE_DATABASE`, `NS_STORE_COSMOS_ACCOUNT` (and `NS_COSMOS_KEY`/`NS_COSMOS_ENDPOINT` locally).

## OPEN (not run, not verified)

- A stored copilot or judge endpoint pointing at a real model is only exercised by PRP-64's G16
  judge item and a hosted copilot check, each needing an approved environment and
  `NS_LIVE_APPROVED=1`.
- The admin console pages are PRP-53 (status, checklist) and PRP-57 (feature settings).
