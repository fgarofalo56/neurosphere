---
name: PRP-132-alert-rules-and-incidents
status: backlog
priority: P2
order: 132
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-05, NS-08
depends_on: [PRP-107-notification-channels-and-subscriptions, PRP-105-policy-engine-core, PRP-115-budget-evaluation-alerts-and-enforcement, PRP-110-governance-contracts-b]
wave: W30
branch: prp-132-alert-rules-incidents
allow_parallel: true
issues: []
---

# PRP-132: Alert rules and incidents

## Goal
Turn governance signals into something a team can own and close. An operator defines alert rules over four signal sources (policy violations, budget threshold events, anomaly recommendations, control-evidence gaps); a worker evaluates them, groups repeated signals into one incident per rule and subject, appends a timeline, and publishes `incident.opened` and `incident.updated` through the PRP-107 notification service so the right people hear about it. A person acknowledges, assigns, comments on and resolves an incident through audited API calls and a console page; every incident links to its evidence (violation, budget, recommendation, entity) and to the live map's incident view. It is for the on-call steward and SRE, and for PRP-133 (ticket references on incidents). It runs in W30 after PRP-127 (which declares the `alert_rules` and `incidents` containers), PRP-110 (contracts), PRP-105, PRP-107 and PRP-115.

Out of scope: the contracts (PRP-110: `alert-rule`, `incident`, `incident-timeline-entry`, `ticket-ref`); the containers (PRP-127, W30 stores owner); channels, outbox, senders and subscriptions (PRP-107); violations and exceptions (PRP-105); budget evaluation (PRP-115); creating tickets in an external system (PRP-133, which writes the `ticket-ref`); paging, on-call schedules and escalation chains to phones (not built, see NOT building); any automatic remediation (a fix is a proposed action through the executor, never started by an alert).

## Why
- There is no incident model and no alert rule: a search of `packages/core/neurosphere_core`, `services/api/neurosphere_api`, `services/workers/neurosphere_workers` and `packages/contracts/schemas` finds no incident type. The only "alert" in the platform is a stored threshold list that nothing evaluates (`packages/core/neurosphere_core/admin/platform/budgets.py:7`; PRP-115 fixes that part).
- Signals exist but end where they are written. Recommendations of kinds `cost_spike`, `latency_degradation` and `error_rate_degradation` are stored (`packages/contracts/schemas/recommendations/v1/recommendation.schema.json:39-47`, `packages/core/neurosphere_core/recommendations/store.py:36-60`) and only listed on a page. Control evidence has summary words `evidence_present`, `evidence_partial`, `no_evidence` (`packages/core/neurosphere_core/compliance/models.py:64-66`) and nothing watches them move. Violations arrive with PRP-105.
- Nothing reaches a person today (`packages/core/neurosphere_core/hitl/notify.py:80-138` stubs; HITL built without notifiers, `services/api/neurosphere_api/runtime/builders/data.py:542-548`); PRP-107 adds delivery. An incident without delivery is a table nobody reads.
- The map's incident view (PRP-77) shows impact for a failing node but has no incident to attach to: "during an incident, every downstream agent affected by a failing service" (original PRD 5d, quoted in `PRPs/backlog/PRP-77-live-map-filters-search-and-incident-view.md:28`) is a view with no record behind it.
- The write path for people exists: audited admin mutations with `If-Match` (`services/api/neurosphere_api/mcp/admin/router.py:96-198`, `packages/core/neurosphere_core/audit/repository.py:247-270` `run_audited_mutation`) and a customer-level guard (`services/api/neurosphere_api/actions/customer_control.py:91`). Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool", every gap planned; design gap G-g.

## Acceptance criteria
- [ ] Given an active rule on source `policy_violation` with a minimum severity and a domain scope, When PRP-105 records a matching violation, Then within one evaluation interval exactly one incident is opened with the rule id, subject, severity, evidence ids, `opened_at` and a first timeline entry; an `incident.opened` notification reaches a local webhook receiver (real HTTP receiver in the integration test, signed body).
- [ ] Given the same subject signals again while the incident is open, Then no new incident is created: a timeline entry `signal_repeated` is appended (bounded, with a counter after 50) and `last_signal_at` moves; given the incident was resolved and the signal returns after the rule's cooldown, Then a new incident opens linked to the previous one.
- [ ] Given a budget threshold crossing (PRP-115), an anomaly recommendation of the three kinds above, and a control whose evidence summary falls from `evidence_present` to `no_evidence`, Then each opens an incident through its own source adapter; each adapter returns bounded signals with evidence ids only, never ledger lines, prompt text or secrets.
- [ ] Lifecycle: `open -> acknowledged -> resolved` plus `reopened`; acknowledge, assign (to a pseudonymous principal who holds `data.read` on the domain), comment and resolve are audited mutations with `If-Match`; a resolved incident rejects edits except `reopen`; an illegal transition is 409 with a reason code; comments are plain text capped at 2000 characters and never rendered as markup.
- [ ] Scope: Given two domains, Then a caller sees incidents, evidence ids and titles only of domains their derived scope allows, a foreign incident id is 404, a denial is recorded, and a notification is only delivered to subscriptions whose scope covers the incident's domain (PRP-107 rule); no notification body, timeline entry or log line contains captured content, a secret, or an entity title the audience cannot read.
- [ ] Rules are validated: an unknown source, a threshold outside its range, a cooldown under 60 seconds, more than 200 rules per customer, or a scope outside the caller's customer is 422; rules are versioned with `If-Match`, disabled rather than deleted, and every change is audited.
- [ ] The incident page lists, filters (status, severity, domain, source) and opens an incident with timeline, evidence links, owner and status; the map incident view links to the incident for a failing node when one is open, and the incident links to the map node (links only; no data copied into the map).
- [ ] The evaluator is restart-safe and idempotent: two workers racing on the same rule produce one incident (ETag claim), and a crash between opening and notifying re-publishes with the same dedup key and delivers once.
- [ ] With no rules or the role off, nothing changes; a malformed stored rule is skipped with a reason code and does not stop other rules.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend lint, typecheck and tests, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Signal sources at launch | Many; the four the design lists | Violations, budget events, anomaly recommendations, control-evidence gaps (design section 4, PRP-132 scope). Each is a small adapter behind one `SignalSource` protocol so later sources are additions |
| 2 | Meaning of "failed control" | Test result; evidence movement | ASSUMPTION: the control library has support statuses and an evidence summary word, no pass or fail result (`compliance/models.py:36-66`). A "failed control" signal is therefore a control whose summary word worsens (`evidence_present` to `evidence_partial` or `no_evidence`) between two evaluations; the adapter keeps the last seen word per control in the rule state document. If the owner means something else, only the adapter changes |
| 3 | How sources are read | Direct stores; bus | Read-only, bounded queries over each source's store through a system caller; no event bus exists. Anomaly recommendations are read from the `recommendations` container (`recommendations/cosmos_store.py:52`) through a small read-only query in the alerting package (the shipped store API is scope-based); ASSUMPTION |
| 4 | Incident grouping | Per signal; per rule and subject | One open incident per (rule, subject); repeats append to the timeline; cooldown after resolve (default 15 minutes) before a new one opens |
| 5 | Permissions | New permissions; existing | Rules: customer-level `config.manage` (same guard as PRP-107). Reading: `data.read` on the incident's domain. Acknowledge, assign, comment, resolve: a new permission `incident.manage` added to `permissions.py` and granted to `domain_steward`; the admin role does not get it (ASSUMPTION (GD-24, recommended default): admin does not also hold `incident.manage`; the role edit changes pinned role tests, listed in Gotchas) |
| 6 | Severity | Free; closed | Closed set `low`, `medium`, `high`, `critical` from the PRP-110 contract; a rule sets the severity, a source may raise it |
| 7 | Notification recipients | Per rule; by subscription | By PRP-107 subscriptions on PRP-110's event classes `incident_opened` and `incident_status_changed` (resolve and reopen are status changes; PRP-110 has no separate resolved class); a rule does not carry addresses |
| 8 | Ticket references | Here; PRP-133 | Display only here (`ticket-ref` list on the incident); PRP-133 creates them through the executor |
| 9 | Retention | Forever; policy | ASSUMPTION: incidents and timelines follow the container's TTL set by PRP-127 and the lifecycle engine; an incident under a legal hold is not purged (data class registration is PRP-127's file, this PRP asks for it) |
| 10 | Paging, on-call, phone | Build; not build | Not built; webhook and Teams cover chat-style alerting. Stated in the runbook |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-107-notification-channels-and-subscriptions.md` and `PRP-105-policy-engine-core.md` (when present) - "Interfaces provided": `NotificationPublisher`, event-class registry, violation store and `policy-violation` record.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` and `PRP-127-ai-system-register-tiering-and-impact-assessments.md` (when present) - the `alert-rule`, `incident`, `incident-timeline-entry` and `ticket-ref` names and the `alert_rules` and `incidents` container declarations.
- `packages/core/neurosphere_core/recommendations/store.py` and `cosmos_store.py:46-70` - recommendation shape and container name.
- `packages/core/neurosphere_core/compliance/models.py` and `bundle.py` - evidence summary words and how the bundle is built.
- `services/api/neurosphere_api/mcp/admin/router.py:96-198`, `packages/core/neurosphere_core/audit/repository.py:247-270`, `services/api/neurosphere_api/actions/customer_control.py:91` - audited mutation pattern and guard.
- `services/workers/neurosphere_workers/hitl_timers/worker.py`, `runtime/roles.py:18-30`, `runtime/factories.py:1867-1879` - worker role shape.
- `packages/core/neurosphere_core/auth/scope/permissions.py:70-135` - roles and permissions (and `packages/core/tests/auth/scope/test_roles.py`).
- `PRPs/backlog/PRP-77-live-map-filters-search-and-incident-view.md` - the map incident view this links to; `frontend/src/features/admin/review-policy/` - admin page pattern.

### Interfaces consumed
- PRP-110 (names from the design, section 3.3, UNVERIFIED until it merges): `alert-rule`, `incident`, `incident-timeline-entry`, `ticket-ref`.
- PRP-127: containers `alert_rules` and `incidents` (declared there, not here).
- PRP-105: violation records (read-only) with evidence ids, first and last seen.
- PRP-107: `NotificationPublisher.publish(...)` with a dedup key; event-class registry; recipients resolved there through scope.
- PRP-115: `evaluate_budget` and `crossed_thresholds` in `neurosphere_core.finops.budget_eval`, budget event classes.
- Shipped: `RecommendationStore` contract, compliance bundle, `run_audited_mutation`, `PermissionRechecker`.

### Interfaces provided
- Core `neurosphere_core.incidents`: `AlertRule` evaluation, `SignalSource` protocol and four adapters, `IncidentStore` (in-memory and Cosmos), incident state machine, `open_or_append`.
- Worker role `alerting` (new, in `ROLE_NAMES`).
- Routes under `/api/v1/incidents`: `GET` list, `GET /{id}`, `POST /{id}/acknowledge`, `/assign`, `/comment`, `/resolve`, `/reopen`; under `/api/v1/admin/alert-rules`: `GET`, `POST`, `GET|PUT /{id}`, `POST /{id}/disable`; `ETag` and `If-Match` on mutations.
- Permission `incident.manage`; audit operations `incident.*` and `alert_rule.*`.
- Publishes PRP-110's event classes `incident_opened` and `incident_status_changed` through PRP-107 (no class outside the contract).
- For PRP-133: `Incident.ticket_refs` append API and the `incident.ticket_linked` timeline entry kind.
- For PRP-77's map view: `GET /api/v1/incidents?entity_id=` filter returning open incidents for a node.

### Patterns to match
- Audited admin mutation with `If-Match`: `mcp/admin/router.py:96-198`.
- ETag-claimed worker tick: `hitl_timers/worker.py` (loser skips).
- Scope-filtered list with opaque cursor: `recommendations/store.py:48-75`.
- Admin page with list, detail and dialogs: `frontend/src/features/admin/review-policy/`.

### Gotchas
- The shipped recommendation store lists by scope and domain; a worker has no `IdentityScope`. The adapter reads the container directly and read-only (clarification 3); it must still filter by customer and domain and never return a recommendation outside the rule's scope.
- Adding permission `incident.manage` and granting it to `domain_steward` edits `_STEWARD` (`permissions.py:98-103`); update `packages/core/tests/auth/scope/test_roles.py` and `tests/security/authz/test_privileged_roles.py` (Tier-2 lists in the reference) and keep admin without it.
- Titles are metadata but can reveal an entity to the wrong audience: render notification titles only after the PRP-107 scope check; the timeline stores ids and kinds, titles are resolved at read through the caller's scope.
- A violation or budget event that cleared is not an auto-resolve: a human resolves; the timeline records `signal_cleared` when the source stops reporting.
- A new worker role and routes change pinned tests: `services/api/tests/runtime_api/test_readiness.py`, route inventories, worker role-name tests; list the updates.
- Same-named test directories shadow each other: use the unique names in the items.
- UNVERIFIED until the named PRPs are written: every PRP-105, PRP-107, PRP-110, PRP-115 and PRP-127 name above.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/incidents/**
  - packages/core/tests/incidents/**
  - services/workers/neurosphere_workers/alerting/**
  - services/api/neurosphere_api/incidents/**
  - services/api/neurosphere_api/runtime/builders/incidents.py
  - services/api/tests/incidents_api/**
  - frontend/src/features/incidents/**
  - tests/integration/incidents/**
  - tests/security/authz/test_incident_access.py
  - docs/runbooks/incidents.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/authz/routes.py
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/notifications/**
  - packages/core/neurosphere_core/governance/policy/**
  - packages/core/neurosphere_core/finops/**
```

## Implementation blueprint

### Item 1 - Core incident model and stores  [serial-after: PRP-127]
Deliverable: bindings of the PRP-110 contracts, `IncidentStore` and `AlertRuleStore` ports with in-memory and Cosmos implementations over the PRP-127 containers, the state machine with legal transitions, bounded timeline append, `open_or_append` (grouping and cooldown), rule validation.
Owned files: `packages/core/neurosphere_core/incidents/**`, `packages/core/tests/incidents/**`.
Must NOT touch: contracts, stores file. Depends on: PRP-110 merged; `[serial-after: PRP-127]` (same wave W30; it declares the `alert_rules` and `incidents` containers), so PRP-127 merges first.
Acceptance criteria: grouping, cooldown, lifecycle and rule-validation criteria at unit level.
Tests: `packages/core/tests/incidents/test_state_machine.py`, `test_grouping.py`, `test_rules.py`, `test_cosmos_store.py` (new directory name unique). Pattern references: `hitl` store and tests for ETag claims.

### Item 2 - Signal sources
Deliverable: `SignalSource` protocol and four adapters (violations, budgets, anomaly recommendations, control-evidence movement) returning bounded `AlertSignal` records with evidence ids, domain, severity hint and dedup key; per-control last-word state.
Owned files: `packages/core/neurosphere_core/incidents/sources/**`.
Must NOT touch: the owning packages of each source. Depends on: item 1; PRP-105, PRP-115.
Acceptance criteria: source criterion, including no content or amounts beyond ids in signals.
Tests: `packages/core/tests/incidents/test_sources_*.py` with in-memory fakes of each source; a negative test with a credential-shaped string in a source record.
Pattern references: `recommendations/store.py:36-75`, `compliance/bundle.py`.

### Item 3 - Alerting worker role
Deliverable: worker `alerting` (evaluate active rules per customer on an interval, ETag claim, open or append, publish through `NotificationPublisher` with dedup keys `incident:<id>:<event>`), registered in `ROLE_NAMES` and `BUILDERS` through a new builder module.
Owned files: `services/workers/neurosphere_workers/alerting/**`, the role and builder lines.
Must NOT touch: other builders. Depends on: items 1, 2; PRP-107.
Acceptance criteria: restart-safety, race and no-rules criteria; first criterion end to end with in-memory stores.
Tests: `services/workers/neurosphere_workers/alerting/tests/test_alerting_worker.py` (new); role-name tests updated.
Pattern references: `hitl_timers/worker.py`.

### Item 4 - Incident and rule API  [P]
Deliverable: routes of "Interfaces provided", audited mutations, derived scope, permission `incident.manage` and its role grant, route inventories.
Owned files: `services/api/neurosphere_api/incidents/**`, `runtime/builders/incidents.py`, `services/api/tests/incidents_api/**`, `tests/security/authz/test_incident_access.py`.
Must NOT touch: `runtime/builders/data.py`. Depends on: item 1.
Acceptance criteria: lifecycle, scope and rule-validation criteria; 404 for foreign incidents; admin lacks `incident.manage`.
Tests: `services/api/tests/incidents_api/test_incident_routes.py`, `test_rule_routes.py`; updated readiness and builder-order pins.
Pattern references: `mcp/admin/router.py:96-198`.

### Item 5 - Console pages  [P]
Deliverable: incidents list and detail (timeline, evidence links, owner, status actions), alert-rule admin page; mock-api feature; a11y route samples.
Owned files: `frontend/src/features/incidents/**`.
Must NOT touch: shell files outside Tier-2 lines; the map feature. Depends on: item 4 (contract of routes).
Acceptance criteria: page criterion; status and severity not colour-only; keyboard operable dialogs.
Tests: component tests beside the page; `frontend/tests/e2e` route sample.
Pattern references: `frontend/src/features/admin/review-policy/`.

### Item 6 - Map link  [serial-after: PRP-77]
Deliverable: the incident view of the map shows "open incident" for a node with an open incident (read from `GET /api/v1/incidents?entity_id=`), and the incident page links to the node. One new small component in the map feature and one mount line in the incident-view file PRP-77 created; read that file first.
Owned files: one new file under `frontend/src/features/map/` named `IncidentLink.tsx` (new) and its test. Must NOT touch: anything else in the map feature. Depends on: PRP-77 merged (W24, so already true in W30), item 4.
Acceptance criteria: link criterion; a node with no open incident shows nothing.
Tests: component test; map suite unchanged. Pattern references: PRP-77's incident view.

### Item 7 - Integration and close-out
Deliverable: end-to-end local test (seeded violation, rule, subscription, local webhook receiver: incident opened once, notification delivered once, acknowledge and resolve audited, repeat appends); Tier-2 appends; runbook `docs/runbooks/incidents.md` (sources, grouping, what a notification contains, no paging); `openapi.json` and docs regeneration; changelog fragment `changelog.d/PRP-132-alert-rules-and-incidents.md`; completion note.
Owned files: `tests/integration/incidents/**`, runbook, fragment. Depends on: items 1-6.
Acceptance criteria: reference section 6; criterion 1 end to end.

## Validation gates
```bash
uv run pytest -q packages/core/tests/incidents packages/core/tests/auth packages/core/neurosphere_core/recommendations/tests packages/core/tests/compliance_lib services/workers/neurosphere_workers/alerting services/api/tests/incidents_api services/api/tests/runtime_api services/api/tests/authz tests/security/authz tests/integration/incidents
uv run ruff check packages services tests
uv run pyright
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
New containers (PRP-127) and a new permission; no change to existing documents. The `alerting` role is off unless listed in `NS_WORKER_ROLES`; with no rules nothing is created. Roll back by removing the role, disabling rules and reverting the PR; the role grant of `incident.manage` is removed with the revert. Existing incidents stay readable.

## Live and open gates
None for this PRP: delivery to a real channel is PRP-107's operator gate (PRP-136); the local webhook receiver proves delivery in CI. The hosted run belongs to the PRP-109 north-star and PRP-64 campaigns.

## NOT building
- Paging, on-call rotations, phone or SMS, and a guarantee that a human read the alert (a 2xx from a receiver means accepted, not read).
- Automatic remediation or auto-resolve; a fix is a proposed action through the executor (and a person resolves).
- Ticket creation (PRP-133) and any external incident-management integration.
- Alerting on arbitrary telemetry queries or user-written expressions: rules are typed parameters over the four sources (no generated query language).
- Statistical correlation or root-cause analysis; the incident links evidence and the map's impact view, nothing inferred.
- A blocking control of any third-party SaaS product: alerts observe and notify only.

## Definition of Ready check
- [x] Goal, Why and acceptance criteria are specific and testable.
- [x] Referenced paths verified in the worktree; new files marked (new) or listed under owns.
- [x] Dependencies named (PRP-127 declares the containers and shares wave W30, so item 1 is `[serial-after: PRP-127]` and it is not in `depends_on`); contract and neighbour names flagged UNVERIFIED until they exist.
- [x] Ownership block present; no Tier-1 files; Tier-2 lines only.

## Execution state
| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 Core model and stores | todo | | serial-after PRP-127 (same wave) |
| 2 Signal sources | todo | | |
| 3 Alerting worker role | todo | | |
| 4 Incident and rule API | todo | | |
| 5 Console pages | todo | | |
| 6 Map link | todo | | serial-after PRP-77 |
| 7 Integration and close-out | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
