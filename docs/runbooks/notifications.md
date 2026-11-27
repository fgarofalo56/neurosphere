# Notification channels and subscriptions

Status date: 2026-11-27. This runbook covers notification delivery (PRP-107): channels,
subscriptions, the durable outbox, the `notifications` worker role, the egress guard and what a
message may contain. A notification is metadata about an event (ids, a short title, a link). It
never carries prompts, responses, tool arguments, query text, evidence values or secrets.

## What exists after PRP-107

| Piece | Where | State |
|---|---|---|
| Channel and subscription documents | `admin_config` kinds `notification_channel`, `notification_subscription` | Built |
| Outbox (memory and Cosmos `notification_outbox`) with de-duplication and retry | `neurosphere_core.notifications` | Built |
| Egress guard (allowed host, address vetting, pinned connect, no redirects, caps) | `neurosphere_core.notifications.egress` | Built |
| Generic signed webhook sender | `neurosphere_core.notifications.senders` | Built |
| Teams sender (Workflows webhook, Adaptive Card) | same | Built, `degraded`: Commercial and GCC tenants only |
| Email sender | none | `not_built`: needs a paid Azure Communication Services resource |
| Worker role `notifications` | `neurosphere_workers.notifications` | Built; runs when listed in `NS_WORKER_ROLES` |
| HITL events (`hitl_item_assigned`, `hitl_item_escalated`, `hitl_item_expiring`) | API and worker `HitlService` | Built; queued when a subscription matches |
| Policy violation events (`policy_violation_opened`, `policy_violation_resolved`, `policy_exception_decided`) | `policy_eval` worker through `violation_event_sink` | Built |
| Admin routes and the page `/admin/notifications` | `neurosphere_api.notifications`, `frontend/src/features/admin/notifications` | Built |
| Budget, attestation and incident events | PRP-115, PRP-130, PRP-132 call `NotificationPublisher.publish` | Planned |
| A real delivery to a Teams tenant, a customer webhook or a mail server | operator | OPEN (PRP-136) |

The verdicts for Teams and email, with sources, are in
`docs/connectors/verification/notifications-teams.md` and
`docs/connectors/verification/notifications-email.md`.

## Turning it on

1. Store the `notifications` system setting (`PUT /settings/notifications` under the system
   settings routes, see `docs/runbooks/system-settings.md`). It holds `egress_allowed_hosts`
   (bare hostnames; a channel host must equal an entry or be a DNS-label subdomain of one),
   `max_attempts` (default 8), `retry_base_seconds` (default 30, doubling, capped at 15 minutes
   between attempts) and `dedup_window_seconds` (default 900). Without this setting the create
   route answers 409 with reason `notifications_not_configured` and the worker skips its tick.
2. Put each channel endpoint in Key Vault as a secret: the webhook URL (or the Teams Workflows
   callback URL) as one secret, and for a generic webhook the signing key as another. A channel
   stores only the two Key Vault secret references (`endpoint_credential`, `hmac_credential`),
   never the values. The API and the worker read them at send time with their managed identity.
3. Create a channel and at least one subscription on the admin page (or the routes below).
4. List `notifications` in `NS_WORKER_ROLES` for the worker deployment. The compose and Helm
   role lists do not include it yet; the demo profile (PRP-109) enables it.
5. Use **Send test** on the channel to check the path end to end.

Stored settings apply at startup only (no hot reload), as for every system setting.

## Routes

All under `/api/v1/admin/notifications`; every route needs customer-level `config.manage` and
any other caller gets 403 with a denial record. Writes need `If-Match` (missing: 422
`precondition_required`; stale: 409 `stale_version`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/channel-kinds` | each kind with `buildable`, `degraded` or `not_built` and the reason |
| GET, POST | `/channels` | list (with delivery status counts and the last error reason) or create |
| GET, PUT, DELETE | `/channels/{channel_id}` | read, replace, retire |
| POST | `/channels/{channel_id}/test` | synchronous test send; answers `ok`, `status_code`, `reason_code` |
| GET, POST | `/subscriptions` | list or create |
| GET, PUT, DELETE | `/subscriptions/{subscription_id}` | read, replace, retire |
| GET | `/deliveries` | outbox rows, filtered by `status` and `channel_id` |

Refusals keep the closed error taxonomy in `code` and the specific reason in `reason`: a
`not_built` kind is 409 `channel_kind_not_built`; a host off the allow-list, a channel from the
other cloud boundary or a local sink outside `NS_ENV=local` is 422 with the egress reason
(`host_not_allowed`, `cloud_boundary`, `local_sink_not_permitted`).

Audit operations: `notification.channel.create`, `.update`, `.delete`, `.test`,
`notification.subscription.create`, `.update`, `.delete`, and `notification.delivery` for a
delivery that ends `failed` (it names the channel id and the reason code, never the URL).

## Who is told (the scope rule)

Channels are group-addressed: the address lives in the channel's Key Vault secret, not in any
principal document, and there is no per-person delivery. Scope decides what a channel may hear:

- A subscription matches an event only when it is enabled, its channel is enabled, the customer
  and cloud match, its `domain_id` equals the event's domain, the event class is listed and the
  severity is at least `min_severity`.
- The subscription owner (the principal who last saved it) must hold `data.read` on that domain,
  checked when the event is published and again when the worker delivers it. A failed check at
  publish writes no row; at delivery the row ends `suppressed` with reason `scope`. A check that
  cannot run (policy store down) is retried, never treated as allowed.
- An event in a domain the subscription does not cover writes nothing against that channel, so
  neither the entity id nor its title reaches it.

## What a message contains

Exactly: `event_class`, `notification_id`, the subject ids, a redacted title (at most 160
characters), `domain_id`, `severity`, an application-relative `link` and a timestamp. The outbox
row stores the same metadata plus delivery state; the rendered body is never stored.

A generic webhook POST carries `X-NeuroSphere-Notification-Id`, `X-NeuroSphere-Timestamp` (unix
seconds) and `X-NeuroSphere-Signature: sha256=<hex>`, the HMAC-SHA256 of
`<timestamp>.<body>` keyed with the signing secret. A receiver should recompute it with a
constant-time compare and reject an old timestamp to stop replays
(`neurosphere_core.notifications.senders.verify_signature` is the reference). A Teams channel
gets the Adaptive Card envelope recorded in the verification file and no signature header.

A 2xx answer means "accepted by the receiver", not "read". 408, 429 and 5xx are retried with
backoff; other 4xx and egress refusals end the row `failed`.

## Egress rules

The guard refuses before connecting, with a reason code: a host off the allow-list or not equal
to the channel's `allowed_host`, a non-https URL, userinfo in the URL, a hostname resolving to a
private, loopback, link-local or metadata address, a body over 64 KiB (28 KB for Teams), and a
channel from another cloud boundary. It connects only to the address it vetted, never follows a
redirect, aborts a response over 16 KiB or a content-encoded response, and gives up after 10
seconds. A Government deployment accepts only hosts on its own configured list.

## Local sink (development only)

With `NS_ENV=local`, a channel may set `local_sink: true` and `local_sink_url` to a plain-HTTP
loopback or compose-service URL (no query string or userinfo); `endpoint_credential` is then
null. Any other environment refuses such a channel at create and at send. The integration test
`tests/integration/notifications_delivery/test_webhook_delivery.py` uses this path with a real
local receiver.

## Troubleshooting

| Symptom | Look at |
|---|---|
| Rows stay `pending` | Is `notifications` in `NS_WORKER_ROLES`? Is the `notifications` setting stored? Counter `ns.notifications.tick_skipped` |
| Rows end `suppressed` / `scope` | The subscription owner lost `data.read` on the domain, or the subscription or channel was disabled |
| Rows end `failed` | `last_error_code` on the row and the `notification.delivery` audit record; counter `ns.notifications.failed` |
| `credential_unavailable` | The workload identity cannot read the Key Vault secret, or the reference is wrong |
| `host_not_allowed` / `host_mismatch` | The endpoint host is not the channel's `allowed_host` or not on `egress_allowed_hosts` |
| `blocked_address` | The hostname resolves to a private or reserved address |

## Live gates (OPEN)

One real delivery per channel kind (a customer webhook receiver, a Teams Workflows webhook, an
email transport once built) needs an operator environment and `NS_LIVE_APPROVED=1`. None ran in
PRP-107; they are handed to PRP-136.
