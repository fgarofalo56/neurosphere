# Audit search, export and the SIEM sink

This runbook covers the PRP-40 audit surfaces: the Event Hubs SIEM sink, the audit search and
export routes, the customer-wide denials view, and how failures before a scope exists are
audited. It's for the operator who configures the deployment and for the security auditor who
uses the routes.

## SIEM export

Every audit append is exported, after the record is durable, as one redacted JSON event to the
configured sink. The audit store is the system of record. A sink that fails never fails the
append. The failure is counted and shown on the status route, and the sink retries with the
next record.

| Variable | Values | Meaning |
|---|---|---|
| `NS_AUDIT_SIEM_SINK` | `none` (default), `stdout`, `file`, `eventhubs` | Which sink receives events |
| `NS_AUDIT_SIEM_FILE_PATH` | path | Required for `file`: JSON lines appended locally |
| `NS_AUDIT_SIEM_EVENTHUBS_NAMESPACE` | namespace name or host | Required for `eventhubs` outside `NS_ENV=local` |
| `NS_AUDIT_SIEM_EVENTHUBS_NAME` | hub name | Required for `eventhubs` |
| `NS_AUDIT_SIEM_EVENTHUBS_CLIENT_ID` | GUID | Optional user-assigned managed identity client id |

### Event Hubs

- Authentication is managed identity through `DefaultAzureCredential`. There's no key and no
  connection string outside `NS_ENV=local`. Locally the emulator connection string comes from
  `NS_EVENTHUBS_CONNECTION_STRING`, as for ingestion.
- Grant the API identity the **Azure Event Hubs Data Sender** role on the hub (or the
  namespace).
- The host is built from the deployment's cloud profile: `<namespace>.servicebus.windows.net`
  on Commercial and `<namespace>.servicebus.usgovcloudapi.net` on Government. A host from the
  other cloud is refused at startup (`audit_siem` `failed`, reason
  `audit_siem_settings_invalid`). Audit events never cross the Commercial/Government boundary.
- Each append sends one event batch, with a send timeout of 10 seconds. Microsoft Sentinel,
  Splunk and other SIEMs read from the hub with their own consumer group.

### Readiness and status

- Readiness component `audit_siem` is optional. It's `disabled` for sink `none`, `ok` when the
  sink was built, and `failed` with reason `audit_siem_settings_invalid` on a missing, invalid
  or cross-cloud setting. A failed optional component blocks readiness, so a misconfigured sink
  is visible. The `audit` component still composes without the sink.
- `GET /api/v1/audit/siem/status` (needs `audit.read` on the customer control domain) returns
  the sink kind, state, last success time, consecutive failures, totals and the last failure
  reason code (`sink_timeout`, `sink_auth_failed`, `sink_unavailable`, `sink_error`,
  `event_build_failed`). It never returns a host, hub name, key or exception text.
- To turn the sink off, set `NS_AUDIT_SIEM_SINK=none` and restart.

## Audit search

`GET /api/v1/audit/search` searches the audit chains of the domains the caller may audit.

- Permission: `audit.read`. With no `domain` filter, the search covers every domain where the
  caller holds `audit.read`. A named `domain` the caller can't read is 403
  `target_out_of_scope`, and the attempt is recorded.
- `since` and `until` (RFC 3339 with a zone) are required. `until` is exclusive. The window is
  capped at **31 days** (`MAX_SEARCH_WINDOW`). A larger window is 422 `range_too_large`.
- Filters: `domain` (repeatable, at most 50), `operation`, `kind` (`before`, `after`,
  `denied`), `outcome` (`succeeded`, `failed`, `rolled_back`), `actor` (a principal pseudonym
  `p-...`) and `correlation_id`. Every filter is pattern-checked and sent to Cosmos as a query
  parameter. No route accepts query text, SQL or a chain id.
- Results come newest first, `page_size` at most 500 (default 50), with an opaque
  `next_cursor`. A cursor is valid only for the same domains.
- Each chain is one Cosmos partition. A search runs one parameterized single-partition query
  per chain, with no cross-partition query.

## Audit export

`GET /api/v1/audit/export?format=ndjson|csv` takes the same filters and window as search.

- Permission: `audit.export` **and** `audit.read` on every domain it reads (the Security
  Auditor role holds both). A missing permission on any named domain is 403.
- The export is capped at **10000 rows** (`MAX_EXPORT_ROWS`). The `X-NeuroSphere-Export-Truncated:
  true` header says the cap was reached; narrow the window or filters and export again.
- Before any byte is streamed, an `audit.export` record is appended to the chain of every
  exported domain. The record holds the row count and format in its outcome detail and a digest
  of the filters as the subject state digest. It holds no record bodies. If that append fails,
  the export is refused with 503 and nothing is streamed.
- CSV cells that start with `=`, `+`, `-`, `@`, a tab or a carriage return are prefixed with `'`
  so a spreadsheet doesn't evaluate them as formulas.

## Denials view

`GET /api/v1/audit/denials` pages through `<customer>.authz-denials`: the denials whose target
was not a domain the caller belonged to, plus the identity-known failures before a scope existed.
That chain names other domains' targets, so it needs `audit.read` on the customer control domain
`<cloud>:<customer>:neurosphere:domain:customer-control`. A domain-only auditor gets 403
`customer_scope_required`. Grant it like any other role, as a time-bound `security_auditor`
assignment on the control domain.

## Failures before a scope exists

The decision below is recorded in PRP-40 (Clarification 3):

- **Identity known, scope not derived.** This covers a revoked principal (403
  `principal_revoked`), a policy-store or revocation-store outage (503) and an authorization
  timeout. The failure is appended to `<customer>.authz-denials` with the actor pseudonym, the
  failure reason code as the denial reason, and operation `authz.derive`. The scope hash is a
  fixed marker digest because no scope exists.
- **Unauthenticated (401).** No chain record is written: an anonymous caller could otherwise
  flood the hash chain. The failure is sent as a redacted `neurosphere.authn.v1` SIEM event (reason
  code only) and counted in-process per reason.
- Neither path changes an authorization decision. A failure to record is logged and the
  original 401, 403 or 503 is returned unchanged.

## Live checks (OPEN until run)

A live Event Hubs send needs `NS_LIVE_APPROVED=1`, an operator-approved namespace and the API
identity holding "Azure Event Hubs Data Sender". Commercial and Government live sends are OPEN.
They're handed to PRP-64.
