# Connector configuration with credential references

The connector configuration API (PRP-42) lets an administrator configure the data-collection roles
(APIM gateway polling, Foundry discovery, billing export, and an OTel record) without setting 15 or
more `NS_GATEWAY_POLL_*`, `NS_FOUNDRY_DISCOVERY_*` and `NS_BILLING_EXPORT_*` variables per profile.
The worker roles read the stored configuration at startup; the environment stays the fallback.

A credential is stored as a **reference**, never a value: a Key Vault secret URI or the client id of
a managed identity. The roles that post to ingest (`gateway_poll`, `billing_export`) read their
producer secret from Key Vault at startup with the workload identity. Nothing secret is stored,
logged or returned.

For a hosted deployment that shows the tenant it runs in, follow `docs/deploy/hosted-real-tenant.md`.

## 1. Routes

All routes are under `/api/v1/admin/sources/connectors` and need **customer-level**
`config.manage` (held on the customer-control domain). A domain admin gets 403
`customer_scope_required`.

| Method | Path | Notes |
|---|---|---|
| POST | `` | create; 201 with `ETag`; `warnings` may list `producer_not_in_store` |
| GET | `?connector_kind=` | list |
| GET | `/{config_id}` | read, `ETag` |
| PUT | `/{config_id}` | replace, `If-Match` required |
| POST | `/{config_id}/enable`, `/{config_id}/disable` | `If-Match` required |
| DELETE | `/{config_id}` | retire (kept for audit), `If-Match` required |

The body is the `admin/v1` `ConnectorConfig`: `connector_id`, `connector_kind`
(`gateway_poll`, `foundry_discovery`, `billing_export`, `azure_monitor_ai`, `otel`), `domain_ids`, bounded scalar
`settings`, `credential` and `enabled`. One active configuration per kind.

A body the worker would refuse is a 422 with a field pointer and nothing is stored (for example a
`billing_export` without `manifest_blob`). Also refused: a secret-like setting name, nested
settings, a URL with userinfo or a query string, a Key Vault URI of the other cloud, and a
credential of the wrong kind (`gateway_poll` and `billing_export` need `key_vault_secret`;
`foundry_discovery` and `otel` take `managed_identity`, recorded and reported as
`credential_not_applied`). Settings per kind:

| Kind | Settings |
|---|---|
| `gateway_poll` | `api_base_url` (required), `interval_seconds`, `window_seconds`, `lookback_seconds`, `batch_size`, `producer_id`, `source_id`, `metrics_app_id`, `allow_unverified_government`, `managed_identity_client_id` |
| `foundry_discovery` | `projects` (`resource/project,...`, required), `interval_seconds`, `max_items`, `max_pages`; exactly one domain |
| `billing_export` | `storage_account_url`, `container`, `manifest_blob`, `api_base_url` (all required), `basis`, `interval_seconds`, `batch_size`, `producer_id`, `source_id`, `managed_identity_client_id`; exactly one domain; Commercial only |
| `azure_monitor_ai` | `workspace_ids` (1 to 4 GUIDs, required), the guards `interval_seconds`, `window_seconds`, `lookback_seconds`, `overlap_seconds`, `max_queries_per_tick`, `max_events_per_tick`, `batch_size`, `app_role_names`, `allow_unverified_government`, `producer_id`, `source_id`, `api_base_url`, `managed_identity_client_id`; exactly one domain; credential `key_vault_secret`; see `docs/runbooks/azure-monitor-ai-telemetry.md` |
| `otel` | `producer_id`, `source_id` (stored and validated; nothing consumes it yet) |

Gateway registrations stay in their own registry (`POST /domains/{d}/gateways`); a `gateway_poll`
config only selects which domains are polled. When `producer_id` is set, the config is checked
against the producer in the admin store: wrong cloud, a missing source or the wrong source kind
(`gateway` for polling, `billing` for billing export) is a 422; a producer that is not in the store
(for example a file-based one) is accepted with the warning `producer_not_in_store`.

Every change is audited on the customer chain `<customer>.admin-config` (`connector.create`,
`connector.replace`, `connector.enable`, `connector.disable`, `connector.retire`). The audit
records hold no setting value and no reference.

## 2. Key Vault role assignment (operator step)

Grant the **worker identity** the `Key Vault Secrets User` role on the vault that holds each
producer secret. The vault suffix must match the deployment cloud (`vault.azure.net` for
Commercial, `vault.usgovcloudapi.net` for Government). The secret is read with
`GET https://<vault>/secrets/<name>?api-version=7.4` over REST; there is no Key Vault library
dependency. If the read fails (403, 404, timeout) the role fails with
`connector_credential_unavailable`; no URI or value appears in any message or log line.

## 3. Restart to apply

A stored config is read when a worker role starts. There is no hot reload: after a change, restart
the workers (or the connector roles).

## 4. Environment fallback and rollback

| Variable | Meaning |
|---|---|
| `NS_WORKER_CONNECTOR_CONFIG_SOURCE` | `auto` (default): stored wins per kind, else the environment. `env`: ignore the store (rollback switch). `store`: ignore the environment. |
| `NS_WORKER_CONNECTOR_CONFIG_TIMEOUT_SECONDS` | Bound of the store read and of each Key Vault read (default 10). |

- No stored config for a kind, or a store read failure: the role behaves exactly as before
  (environment). A store failure is one log line, `connector_config_store_unavailable`, never a
  startup failure.
- A stored config with `enabled=false`: the role idles and does **not** fall back to the
  environment for that kind.
- A stored value cannot widen a Government guard: `billing_export` in Government still fails with
  `billing_export_cloud_unsupported`, and gateway metrics are still skipped.

Rollback: set `NS_WORKER_CONNECTOR_CONFIG_SOURCE=env` and restart. Stored documents are inert.

## 5. Known limits

- Real-tenant mode of the hosted deployment turns the connector roles on (PRP-139; `azure_monitor_ai` joined in PRP-141; see
  `docs/deploy/hosted-real-tenant.md`). The Helm profiles still do not run them; local proof uses
  emulators and in-memory twins. A real Key Vault read with stored config is an OPEN live gate.
- `foundry_discovery` authenticates with `DefaultAzureCredential`; its token provider takes no
  client id, so a `managed_identity` credential is recorded but not applied.
- The stored credential must be non-null: the shipped Cosmos twin of the store cannot read back a
  document whose null members were dropped on write (PRP-65 follow-up).
