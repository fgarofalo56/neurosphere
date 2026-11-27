### Added
- Notification channels and subscriptions (PRP-107): a notification now leaves the system.
  Channels (`admin_kind: notification_channel`) are group-addressed and hold only Key Vault
  secret references for the endpoint and the signing key; subscriptions
  (`admin_kind: notification_subscription`) pick a channel, a domain, event classes, audience
  roles and a minimum severity.
- Durable outbox (`notification_outbox`) with de-duplication, bounded exponential retry (the
  `notifications` system setting: `max_attempts` 8, `retry_base_seconds` 30, capped at 15
  minutes) and states `pending`, `sending`, `delivered`, `failed`, `dead_lettered`,
  `suppressed`. Rows hold ids, a short title and a link, never a body or content.
- Recipient scope: a subscription is delivered only when its domain covers the event and its
  owner holds `data.read` there, checked at publish and again at delivery (`suppressed` with
  reason `scope` otherwise).
- Egress guard for every send: allowed host by DNS label, private and metadata address refusal,
  connection pinned to the vetted address, no redirects, body, response and time caps, the
  Government cloud boundary, and a local-sink exception for `NS_ENV=local` only.
- Generic webhook sender with `X-NeuroSphere-Signature` (HMAC-SHA256 over timestamp and body)
  and a Teams Workflows webhook sender (Adaptive Card; Commercial and GCC tenants only). Email is
  `not_built`: every verified transport needs a paid, operator-provisioned Azure Communication
  Services resource.
- Worker role `notifications` (opt-in through `NS_WORKER_ROLES`) with counters
  `ns.notifications.delivered`, `.suppressed`, `.failed`, `.tick_skipped`, `.audit_failed`.
- HITL assignment, escalation and expiry events and policy violation and exception events are
  published to the outbox; the audit-only notifier stubs are unchanged.
- Admin routes under `/api/v1/admin/notifications` (customer-level `config.manage`) and the page
  `/admin/notifications` with delivery status counts and a test-send button; the optional
  readiness component `notifications`.
- Runbook `docs/runbooks/notifications.md` and verification notes
  `docs/connectors/verification/notifications-teams.md` and `notifications-email.md`.
