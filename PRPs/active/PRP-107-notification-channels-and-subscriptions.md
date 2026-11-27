---
name: PRP-107-notification-channels-and-subscriptions
status: active
priority: P0
order: 107
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-08, NS-10
depends_on: [PRP-99-governance-contracts-a, PRP-102-encrypted-interaction-store-and-retention, PRP-105-policy-engine-core]
wave: W22
branch: prp-107-notification-channels
allow_parallel: true
issues: []
started: 2026-11-26
execution: session
max_lanes: 4
---

# PRP-107: Notification channels and subscriptions (a notification that reaches a person)

## Goal
Make a notification leave the system. Today the HITL notifier stubs write an audit record and send nothing, and neither production build wires a notifier at all. This PRP ships channel configuration (generic webhook with an HMAC signature, Teams webhook, email behind a verified transport), subscriptions by role or domain and event class, a durable outbox with retry and de-duplication, a delivery worker role, an egress guard (allowed hosts, address vetting, no redirects), and real `Notifier` implementations wired into HITL in the API and the worker builds. A recipient is resolved through authorization scope at publish time and again at delivery time, and a message carries ids, titles and links, never content or secrets. It is for the admin who configures channels, the reviewers and stewards who must hear about a review item or a violation, and for PRP-105 (violations), PRP-115 (budgets), PRP-130 (attestation reminders) and PRP-132 (incidents), which publish through it. It runs in W22 after PRP-99 (contracts) and PRP-102 (which declares the `notification_outbox` container).

Out of scope: the contracts (PRP-99 owns `notifications/v1`); the container declaration (PRP-102 is the W21 stores owner); events from budgets, incidents and attestation (PRP-115, PRP-132, PRP-130 call the publisher defined here; policy-violation events arrive through the PRP-105 sink that item 6 binds); per-person addressing through Microsoft Graph (not built, see NOT building); ticket creation (PRP-133); a live delivery to a real Teams tenant or mail server (operator-gated, handed to PRP-136).

## Why
- Nothing reaches a person. `Notifier`, `EmailNotifierStub` and `TeamsNotifierStub` only append an audit record and return status `recorded` (`packages/core/neurosphere_core/hitl/notify.py:80-138`; its own docstring says "Real delivery is out of scope", `:1-6`).
- The stubs are not even constructed in production: `HitlService(...)` is built with the default `notifiers=()` in the API (`services/api/neurosphere_api/runtime/builders/data.py:542-548`) and in the worker (`services/workers/neurosphere_workers/runtime/factories.py:536-543`); the only other constructor is the sandbox seed (`scripts/sandbox/sbx_seed_stack.py:633`). `HitlService._notify` returns 0 when there are none (`hitl/service.py:607-608`). The HITL timer worker therefore escalates silently.
- No sender exists in the tree: no SMTP, webhook or Graph client; `httpx` is a direct dependency (`pyproject.toml:21`) but nothing posts to a customer URL. The only vetted outbound path is the MCP client (`packages/core/neurosphere_core/mcp/ssrf.py:182` `vet_target`, pinned transport `services/api/neurosphere_api/mcp/client/transport.py:82`), which lives in the API package and cannot be imported by a worker.
- `docs/PRD.md:23` promises "SLA timers, reassignment, notifications and immutable decisions" for HITL; the notification half was recorded, never sent (PRP-17 clarification 6). The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every gap planned; a governance tool whose alerts nobody receives fails that.
- Principal policy documents hold only pseudonymous principal ids and role assignments, no address (`packages/core/neurosphere_core/auth/scope/policy.py:67-105`), so "who is the recipient" cannot be answered by an address lookup. Scope has to decide who may be told, and the channel carries the address.

## Acceptance criteria
- [ ] Given a webhook channel pointing at a local receiver and a subscription for event class `hitl_item_assigned` (PRP-99 `NotificationEventClass`) on a domain, When a review item is assigned in that domain, Then the receiver gets one POST within the configured retry window with a JSON body, an `X-NeuroSphere-Signature` HMAC header that verifies with the channel's secret, a stable `notification_id`, and the outbox row ends `delivered` with the HTTP status (no body stored). This is a test against a real local HTTP receiver, not a mock of the sender.
- [ ] Given the receiver answers 500 then 200, Then the row retries with bounded exponential backoff and ends `delivered` once; given it keeps failing, Then the row ends `failed` after the attempt cap with a reason code, a counter is raised and one audit record names the channel id, never the URL query or secret.
- [ ] Given the same logical event published twice (same dedup key), Then exactly one POST is sent.
- [ ] Recipient scope: Given a subscription whose domain scope does not include the event's domain, or whose owner no longer holds `data.read` on it when delivery runs (recheck through `PolicyPermissionRechecker`), Then nothing is sent and the row is `suppressed` with reason `scope`; an event about an entity the audience cannot see leaks neither its id nor its title (test with two domains and a channel scoped to one).
- [ ] Body rules: the message is built from a closed field set (event class, ids, entity title, domain id, severity, link, timestamp); a test publishes an event whose source record contains a credential-shaped string and a prompt-like field and asserts neither reaches the sent body, the outbox row, the audit record or any log line.
- [ ] Egress: Given a channel host not on its allowed-host list, a hostname that resolves to a blocked address, a redirect, a body larger than the cap, or a response slower than the timeout, Then the send is refused or aborted with a reason code and nothing is followed. Loopback is accepted only when `NS_ENV=local` and the channel is explicitly marked local sink (used by the tests).
- [ ] Teams and email senders exist only for what item 1 verified: a channel kind whose verification file says the API or transport is not available stays `not_built` in the admin page with the reason, and the create route refuses it; no code asserts a payload shape that item 1 did not record.
- [ ] HITL wiring: `HitlService` is built with the outbox notifier in the API and the worker, so assignment (`hitl/service.py:262`) and timer events (`:479`) publish; the audit-only stubs remain available and unchanged for tests.
- [ ] Secrets: channels store only a `CredentialReference` (Key Vault URI or managed identity), resolved at send time through the existing reader; no route, document, log, audit record or OpenAPI example contains a secret value (secret-name CodeQL rule respected).
- [ ] Admin: customer-level `config.manage` can create, update, disable, test-send and list channels and subscriptions; every other caller gets 403 and a denial record; the page shows per-channel delivery status counts and the last error reason.
- [ ] Government: a Government deployment accepts only channels whose allowed hosts are in the same cloud boundary list configured for it; a cross-boundary host is refused at create.
- PRP exit: touched suites, `tests/security/authz`, `tests/security/egress`, ruff, pyright, frontend lint and typecheck, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Teams and email mechanics | From memory; verify first | Verify-first (item 1). Teams webhook acceptance in the target tenant and cloud is design item U-5; a usable email transport without a new paid dependency is U-6; both UNVERIFIED here. Decided by the owner 2026-11-16 (GD-10): generic webhook and Teams webhook first; email after the transport is verified |
| 2 | Where recipients come from | Address per person; address per channel | ASSUMPTION: channels are group-addressed (a webhook URL, a Teams channel webhook, a distribution-list address held in channel config). Principal documents carry no address, and per-person lookup through Graph is unverified and not built. Scope still decides: a subscription is delivered only if its scope covers the event |
| 3 | Subscription scope vs the person | Trust the channel; recheck | A subscription records `created_by` and a domain list or role; at publish and again at delivery the owner's current permission is rechecked (fail closed). A removed owner suppresses the subscription |
| 4 | Where channels and subscriptions live | New container; `admin_config` kinds | `admin_config` documents of kinds `notification_channel` and `notification_subscription` (PRP-99 adds both to `admin_kind`, its clarification 3). This PRP adds the two lines to `ADMIN_KIND_MODELS` (`packages/core/neurosphere_core/admin/models.py:82`); PRP-105 added `enforcement_binding` there in W21 |
| 5 | What an outbox row records | Full payload; reference | The rendered body is not stored: the row holds event class, ids, channel id, state, attempt count, reason code and timestamps. The body is rebuilt from ids at send time through the scope check |
| 6 | `NotifierChannel` literal | Keep two values; widen | Widen `hitl/notify.py` `NotifierChannel` with `outbox` (one line) so the real notifier type-checks; the stubs are unchanged |
| 7 | Loopback receiver in tests | Disable the guard; local exception | `NS_ENV=local` plus PRP-99's `NotificationChannel.local_sink: true` with its `local_sink_url` (plain-HTTP loopback or compose service, no query or userinfo; `endpoint_credential` null) only. A channel with `local_sink: true` is refused on any other environment |
| 8 | HMAC | None; HMAC-SHA256 over the body with a timestamp header | HMAC-SHA256 with the channel's credential reference as key and a timestamp header; the algorithm is ours, not a vendor assertion |
| 9 | Retry budget | Unbounded; capped | The PRP-99 `NotificationsSetting` defaults: `max_attempts` 8, `retry_base_seconds` 30 doubling (ASSUMPTION: capped at 15 min between attempts), then `failed`; `dedup_window_seconds` 900 is the default window, overridden per event class by the publisher |
| 10 | Which events at launch | All | The HITL events mapped to PRP-99's `hitl_item_assigned`, `hitl_item_escalated`, `hitl_item_expiring`, the generic `publish()` API, and PRP-105's `policy_violation_opened`, `policy_violation_resolved`, `policy_exception_decided` through the `ViolationEventSink` binding (item 6). Event classes are exactly PRP-99's `NotificationEventClass` values plus PRP-110's additions; there is no separate registry, and a class outside the generated enum is refused at publish (`unknown_event_class`) |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/hitl/notify.py` and `hitl/service.py:255-270,470-485,603-630` - `Notifier`, `Notification`, `_notify`.
- `services/api/neurosphere_api/runtime/builders/data.py:520-548` and `services/workers/neurosphere_workers/runtime/factories.py:533-545,1867-1879` - HITL construction and the `BUILDERS` table.
- `packages/core/neurosphere_core/mcp/ssrf.py` and `services/api/neurosphere_api/mcp/client/transport.py:56-130` - vetting and the pinned backend to imitate (not import).
- `services/workers/neurosphere_workers/connector_config/keyvault.py:55-130` - `SecretReader.read(reference)`.
- `services/workers/neurosphere_workers/hitl_timers/worker.py` - worker role shape; `runtime/roles.py:18-30` - `ROLE_NAMES`.
- `packages/core/neurosphere_core/actions/recheck.py` (`PolicyPermissionRechecker`) and `actions/permissions.py:20` - the permission recheck port.
- `packages/core/neurosphere_core/admin/models.py:82-100` and `services/api/neurosphere_api/actions/customer_control.py:91` - kinds and the customer-level guard.
- `packages/contracts/schemas/admin/v1/credential-reference.schema.json` - the only way to name a credential.
- `packages/core/tests/hitl/test_notifier_stubs.py` - the test style for notifiers; `frontend/src/features/admin/review-policy/` - an admin page to imitate.

### Interfaces consumed
- PRP-99 ("Interfaces provided", Notifications; PRP-99 wins on any difference): `NotificationChannel` (`kind` `webhook`|`teams_webhook`|`email`, `allowed_host`, `endpoint_credential`, `hmac_credential`, `local_sink`, `local_sink_url`, `enabled`), `NotificationSubscription` (`event_classes`, `audience_roles`, `min_severity`), `NotificationDelivery` (container `notification_outbox`; `status` `pending`|`sending`|`delivered`|`failed`|`dead_lettered`|`suppressed`, `attempts`, `next_attempt_at`, `last_error_code`, no recipient and no body), `NotificationEventClass`; the `admin_kind` values `notification_channel`, `notification_subscription`; the `NotificationsSetting` member; the audit operation name `notification.delivery`. Item 2 reads the generated bindings.
- PRP-102: the `notification_outbox` container declaration (`stores/containers.py`, compose JSON, bicep), partition key as declared there.
- PRP-105 (W21): `ViolationEventSink` and the binding function `violation_event_sink(cfg, lifetime)` in `services/workers/neurosphere_workers/policy_eval/assembly.py`, which item 6 fills.
- PRP-137 (W19, merges earlier): events and violations name agents by canonical id; OTLP agents have one only once PRP-137 resolves `external_agent_id`. This PRP resolves nothing and passes on the subject id it is given.
- Shipped: `PolicyPermissionRechecker`, `SecretReader`, `vet_target`, `AuditRepository`, `run_audited_mutation`.

### Interfaces provided
- Core `neurosphere_core.notifications`: `NotificationPublisher.publish(event)` (event class, customer, domain, entity ref, title, severity, link, dedup key, and a dedup window set per event class: at least one period for PRP-115 budget events, so a crossing is announced once per period), `OutboxNotifier` (implements `Notifier`), `ChannelRegistry`, `SubscriptionResolver`, `OutboxStore` (in-memory and Cosmos), `EgressGuard`, sender protocol and three senders.
- Worker role `notifications` (new, in `ROLE_NAMES`) draining the outbox.
- Routes under `/api/v1/admin/notifications`: `GET|POST /channels`, `GET|PUT|DELETE /channels/{id}`, `POST /channels/{id}/test`, `GET|POST /subscriptions`, `GET /deliveries`; `ETag` and `If-Match` as the other admin routes.
- Audit operations `notification.channel.*`, `notification.subscription.*`, `notification.delivery`.
- `ViolationNotificationSink` (implements PRP-105 `ViolationEventSink` over `NotificationPublisher`), bound in PRP-105's `policy_eval/assembly.py` by item 6. Later publishers (PRP-115, 130, 132) call `NotificationPublisher.publish` with contract event classes; no registry to edit.

### Patterns to match
- Admin router with `If-Match`: `services/api/neurosphere_api/mcp/admin/router.py:96-198`.
- Worker role with a durable tick: `hitl_timers/worker.py`; claim by ETag like the timer worker.
- SSRF refusal reasons: `core/mcp/ssrf.py:100-182`; pinned connect: `transport.py:82-120`.
- Admin page: `frontend/src/features/admin/review-policy/`.

### Gotchas
- The worker cannot import `neurosphere_api`; the egress guard and pinned transport live in core. The API MCP transport uses `httpx2` and `httpcore2`; confirm which client the core sender should use against `pyproject.toml` pins before writing it (UNVERIFIED), and imitate the pinning, do not import it.
- The worker builds HITL with `_NoReviewerAuthorizer` (`factories.py:513-521`): fine for notifications, but the scope recheck needs the `PolicyPermissionRechecker` built at `factories.py:576`; share its construction, do not duplicate policy reads.
- Adding an API builder or component changes pinned tests: `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py` (component set and `default_builders` order); list the edits. A new worker role changes `ROLE_NAMES` pins (worker runtime tests) and the compose and Helm role lists (not this PRP; the demo profile in PRP-109 enables the role).
- Recorded is not delivered: keep the stubs' `recorded` semantics; only the outbox writes `delivered`, and only after a 2xx.
- Credential value never enters a log: the reader raises reason codes only (`keyvault.py:55`); keep that.
- UNVERIFIED externals (design U-5, U-6): Teams webhook acceptance, email transport availability. Not asserted anywhere in this PRP.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/notifications/**
  - packages/core/neurosphere_core/hitl/notify.py
  - packages/core/neurosphere_core/admin/models.py
  - packages/core/tests/notifications/**
  - services/workers/neurosphere_workers/notifications/**
  - services/workers/neurosphere_workers/policy_eval/assembly.py
  - services/workers/tests/policy_eval_worker/test_violation_notifications.py
  - services/api/neurosphere_api/notifications/**
  - services/api/neurosphere_api/runtime/builders/notifications.py
  - frontend/src/features/admin/notifications/**
  - services/api/tests/notifications_api/**
  - tests/security/egress/test_notification_egress.py
  - tests/integration/notifications/**
  - docs/connectors/verification/notifications-teams.md
  - docs/connectors/verification/notifications-email.md
  - docs/runbooks/notifications.md
tier1:
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - services/workers/neurosphere_workers/runtime/roles.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/mcp/**
  - services/api/neurosphere_api/mcp/**
```
W22 merge order: PRP-107 merges before PRP-103's item 7 (the last code item), which is `[serial-after: PRP-107]` and wires the `_lifecycle_targets` lines of `runtime/factories.py`, this PRP's Tier-1 file. No item here is `[serial-after: PRP-103]`, so there is no cycle.

## Implementation blueprint

### Item 1 - Verify-first: Teams and email  [P]
Deliverable: `docs/connectors/verification/notifications-teams.md` and `notifications-email.md` from the vendor documentation fetched at execution: URL, retrieval date, what a posted message needs, size limits, cloud availability (Commercial and Government), authentication, and the fallback. Anything not found is "not coded".
Owned files: those two files. Must NOT touch: code. Depends on: none.
Acceptance criteria: each channel kind has a verdict (`buildable`, `degraded`, `not_built`) with source; email names the transport options found and says which needs no new paid dependency.
Tests: none. Pattern references: `docs/connectors/coverage.md`.

### Item 2 - Core model, outbox and resolver
Deliverable: `notifications` package: bindings of PRP-99 contracts, `ChannelRegistry` and subscriptions over `admin_config`, `OutboxStore` (in-memory, Cosmos over the PRP-102 container), de-duplication, state machine over PRP-99's `NotificationDelivery.status` (`pending`, `sending`, `delivered`, `failed`, `dead_lettered`, `suppressed`), `SubscriptionResolver` with the scope rule, the closed-field message builder, the two `ADMIN_KIND_MODELS` lines.
Owned files: `packages/core/neurosphere_core/notifications/**`, `admin/models.py`, `packages/core/tests/notifications/**`.
Must NOT touch: contracts, stores file. Depends on: PRP-99, PRP-102 merged.
Acceptance criteria: dedup, scope suppression, closed-body and no-secret criteria at unit level.
Tests: `packages/core/tests/notifications/test_resolver.py`, `test_outbox.py`, `test_message_body.py` (new directory name unique). Pattern references: `hitl_cosmos` tests for Cosmos stores.

### Item 3 - Egress guard (opus implementer)
Deliverable: `EgressGuard`: allowed-host match (DNS-label, not substring), `vet_target`, pinned connect to the vetted address, no redirects, response and time caps, the local-sink rule, Government boundary list.
Owned files: `packages/core/neurosphere_core/notifications/egress.py`, `tests/security/egress/test_notification_egress.py`.
Must NOT touch: `core/mcp/**`. Depends on: item 2.
Acceptance criteria: the Egress criterion, including hostname-substring and redirect cases (CodeQL hostname-substring trap in memory notes).
Tests: that file plus unit tests in the package. Pattern references: `transport.py:82-120`, `tests/security/mcp/`.

### Item 4 - Senders
Deliverable: webhook sender (HMAC, timestamp header), Teams sender and email sender exactly as item 1 verified (or `not_built`), all through the guard; secrets read per send through `SecretReader`.
Owned files: `packages/core/neurosphere_core/notifications/senders/**`.
Must NOT touch: `keyvault.py`. Depends on: items 1-3.
Acceptance criteria: signature verifies; payload shapes match the verification files; unavailable kinds refuse creation.
Tests: `packages/core/tests/notifications/test_senders.py` plus `tests/integration/notifications/test_webhook_delivery.py` with a real local receiver (loopback allowed by the local-sink rule).
Pattern references: `core/tests/hitl/test_notifier_stubs.py`.

### Item 5 - Delivery worker role
Deliverable: worker `notifications` (claim by ETag, send, retry, mark, audit, counters) registered in `ROLE_NAMES` and `BUILDERS` via a new builder module imported from `factories.py`.
Owned files: `services/workers/neurosphere_workers/notifications/**`, the `BUILDERS` line and the HITL wiring lines in `factories.py`.
Must NOT touch: other builders. Depends on: items 2, 4.
Acceptance criteria: retry, cap, restart-safety (a second worker does not double-send).
Tests: `services/workers/neurosphere_workers/notifications/tests/test_delivery_worker.py` (new); role-name tests updated.
Pattern references: `hitl_timers/worker.py`.

### Item 6 - HITL wiring, publisher and the violation-event binding
Deliverable: `OutboxNotifier` and `NotificationPublisher`; `HitlService` receives it in `data.py` and `factories.py`; `NotifierChannel` widened by one value. Violation-event binding (the only binding of PRP-105's `ViolationEventSink`): `ViolationNotificationSink` maps `opened`, `resolved` and `exception_decided` to `policy_violation_opened`, `policy_violation_resolved` and `policy_exception_decided` (ids, policy id, severity, the violation link; no evidence values), and the body of PRP-105's binding function `violation_event_sink(cfg, lifetime)` in `policy_eval/assembly.py` returns it when the notifications store is configured (no-op otherwise).
Owned files: `hitl/notify.py`, `runtime/builders/notifications.py` (new), the HITL construction lines of `data.py` and `factories.py`, the `violation_event_sink` function in `services/workers/neurosphere_workers/policy_eval/assembly.py`, `services/workers/tests/policy_eval_worker/test_violation_notifications.py` (new).
Must NOT touch: other lines of those files; any other PRP-105 file. Depends on: items 2, 5; PRP-105 merged (W21).
Acceptance criteria: HITL wiring criterion end to end with in-memory stores; stubs unchanged; a `policy_eval` tick that opens a violation on fakes writes one `pending` outbox row of class `policy_violation_opened` for a matching subscription, and a second tick writes none (dedup).
Tests: `services/api/tests/notifications_api/test_hitl_wiring.py`, `services/workers/tests/policy_eval_worker/test_violation_notifications.py`; updated readiness and builder-order pins.
Pattern references: `data.py:520-548`.

### Item 7 - Admin API and page
Deliverable: admin routes (permission `config.manage`, customer level), route inventories, mock-api feature, the admin page with delivery status and a test-send button.
Owned files: `services/api/neurosphere_api/notifications/**`, `frontend/src/features/admin/notifications/**`.
Must NOT touch: shell files outside the Tier-2 lines. Depends on: items 2, 6.
Acceptance criteria: Admin and Secrets criteria; keyboard and label accessibility like sibling pages.
Tests: `services/api/tests/notifications_api/test_admin_routes.py`, `tests/security/authz` additions, `frontend` component and e2e tests.
Pattern references: `frontend/src/features/admin/review-policy/`.

### Item 8 - Integration and close-out
Deliverable: Tier-2 appends, `openapi.json` and docs regeneration, runbook `docs/runbooks/notifications.md` (channels, scope rule, what a message contains, how to run the local sink), changelog fragment `changelog.d/PRP-107-notification-channels-and-subscriptions.md`, completion note.
Owned files: runbook, fragment. Depends on: items 1-7.
Acceptance criteria: reference section 6; live gates recorded OPEN.

## Validation gates
```bash
uv run pytest -q packages/core/tests/notifications packages/core/tests/hitl services/workers/neurosphere_workers/notifications services/workers/tests/policy_eval_worker services/api/tests/notifications_api services/api/tests/runtime_api services/api/tests/authz tests/security/egress tests/security/authz tests/integration/notifications
uv run ruff check packages services tests
uv run pyright
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
New `admin_config` kinds and the PRP-102 `notification_outbox` container, both additive. The worker role is off unless listed in `NS_WORKER_ROLES`; with no channels configured, `HitlService` behaves as before (nothing to send). Roll back by removing the role from `NS_WORKER_ROLES` and disabling channels; reverting the PR removes the wiring lines. Outbox rows hold no content and expire with a TTL set by the stores owner.

## Live and open gates
One real delivery per channel kind (a Teams tenant, a real webhook receiver, the email transport) needs `NS_LIVE_APPROVED=1` and an operator; recorded OPEN here and handed to PRP-136. The local webhook delivery in the acceptance criteria is not live and must pass in CI.

## NOT building
- Delivery to a person by name or per-person address (no Graph, no directory lookup; design U-7 unverified).
- Read or delivery receipts: a 2xx is "accepted by the receiver", not "read".
- Chat bots, two-way approval from a message, SMS or push.
- A guarantee that Teams or email works in Government: stated only if item 1 verifies it.
- Content in any message: no prompt, response, tool argument, query text or secret, ever.
- Digest or batching of notifications beyond de-duplication.

## Definition of Ready check
- [x] Goal, Why and acceptance criteria are specific and testable.
- [x] Referenced paths verified in the worktree; new files marked (new) or listed under owns.
- [x] Dependencies named; PRP-99 contract names and the `admin_kind` addition are flagged UNVERIFIED.
- [x] Ownership block present; Tier-1 lines in `data.py` and `factories.py` match the W22 owner assignment in the design.

## Execution state
| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 Verify-first Teams and email | merged | orchestrator (Learn MCP) | verdicts: `teams_webhook` degraded (Workflows; Commercial + GCC, not GCC High/DoD; connector webhooks retired May 2026), `email` not_built (needs paid ACS resource; SMTP not in Gov); docs-only, no tests; 2026-11-26 |
| 2 Core model, outbox, resolver | merged | worktree-agent-a4a8efd38cb6bddc3 | sonnet; c25e6c1c merged 6750c3f4; 274 passed (core notifications/admin/hitl), ruff+pyright clean, Snyk 0; owner = envelope `updated_by`; `audience_roles` applied as a scope check; delivered rows carry `last_error_code=http_<status>` (contract has no status field); also owns `packages/core/tests/admin/test_config_store.py` PENDING sets and the core `NotificationPublisher` (moved from item 6); 2026-11-26 |
| 3 Egress guard | merged | worktree-agent-a36cea3fc24b6eaa9 | opus; 8486e9de merged 39f40c31; 159 passed (security/egress + unit), ruff+pyright clean, Snyk 0; httpcore 1.x pinned backend; combined 433 passed after merge; 2026-11-26 |
| 4 Senders | merged | worktree-agent-a980f560008814ff2 | sonnet; b1f62d49 merged bd35abc2; 217 passed (core notifications + integration/notifications_delivery + security/egress), ruff+pyright clean, Snyk 0; webhook HMAC-SHA256 over timestamp.body, Teams Adaptive Card per item 1, email not_built; 2026-11-26 |
| 5 Delivery worker role | merged | worktree-agent-a5599c0049b0d6fff | sonnet; 0f08f58e merged 2286c2a0; 213 passed (worker + core + integration), ruff+pyright clean, Snyk 0; tests in `services/workers/tests/notifications_worker/` (repo convention, not inside the package); shared `runtime/rechecker.py` helper (new); audit subject is the channel, notification id in `target_version`; 2026-11-26 |
| 6 HITL wiring, publisher, violation-event binding | merged | worktree-agent-a8dd59149a4957aaa | sonnet; 497d0929 merged d2f39e0d; 500 passed on touched suites (only the manifest-count test red, owned by 7a), Snyk 0; API builder `notifications` runs after `authz`, before `data`; follow-up 31d2590c (orchestrator) makes the worker notifications imports lazy to clear CodeQL py/unsafe-cyclic-import; 2026-11-27 |
| 7 Admin API and page | merged | 7b e65834c7 (worktree-agent-abb9331906748f4b8), 7a 63c799fe merged 5a6a0e2b (worktree-agent-a0af3c2df63e25a4e), follow-up 9bb1e7d5 | sonnet; 7b page + mock API (vitest 283 and e2e 14 at agent; Snyk 5 false positives on label strings and test Key Vault URIs; also `frontend/tests/e2e/a11y/route-samples.ts`). 7a: 13 routes, minimal API Key Vault reader, outbox `count_deliveries`/`last_error_code`, inventories (manifest_calls, counts 60, real-stack routes.spec), openapi + docs reference regenerated (additions only), 23 Docker visual baselines regenerated; after merge 574 passed (notifications_api, runtime_routes, authz, security authz, demo_profile, core notifications, openapi drift), Snyk 0. Deviation: closed error taxonomy, so refusals are `code` capability_unavailable/invalid_schema with the specific `reason`; missing If-Match is 422 `precondition_required`, stale is 409 `stale_version`; 9bb1e7d5 makes the page show `reason` and the mock answer the same way (vitest 77, e2e 6); 2026-11-27 |
| 8 Integration and close-out | todo | | |

Execution deltas (2026-11-26): integration tests live in `tests/integration/notifications_delivery/` (not `notifications/`) to avoid the same-named test package clash with `packages/core/tests/notifications/`.

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
