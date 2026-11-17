---
name: PRP-115-budget-evaluation-alerts-and-enforcement
status: backlog
priority: P1
order: 115
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-03, NS-08
depends_on: [PRP-105-policy-engine-core, PRP-107-notification-channels-and-subscriptions, PRP-110-governance-contracts-b]
wave: W26
branch: prp-115-budget-evaluation
allow_parallel: true
issues: []
---

# PRP-115: Budget evaluation, alerts and proposed enforcement

## Goal
Make a stored budget do something. A new worker role evaluates every budget against the cost ledger (period to date, a run-rate projection, coverage), publishes threshold and projection events through the PRP-107 notification service so a person actually receives them, exposes the same status through a read route and a status panel on the Budgets screen, provides the `budget` rule kind to the PRP-105 policy engine, and, at the cut-off threshold, lets an authorized person turn the alert into a proposed `budget_cap_change` action that goes through the action executor with approval. Nothing is ever cut off automatically. It is for the finance owner and domain steward who set budgets in PRP-44 and heard nothing, and for PRP-132 (alert rules consume budget events) and PRP-134 (chargeback). It runs in W26 after PRP-105 (policy engine) and PRP-107 (delivery).

Out of scope: storing budgets (shipped PRP-44); the notification channels, outbox and senders (PRP-107); the policy engine and its other rule kinds (PRP-105); the gateway write path and policy fragments (shipped PRP-34, PRP-112 for compiled enforcement); a real gateway run (G17 manage gate stays OPEN, PRP-136); chargeback and cost-center views (PRP-134); anomaly detection on cost (shipped detectors, PRP-132 may alert on them).

## Why
- Budgets are stored only: "nothing evaluates a budget against spend or sends an alert" (`packages/core/neurosphere_core/admin/platform/budgets.py:7`; `services/api/neurosphere_api/admin/platform/__init__.py:6`). The contract text promises the opposite: "evaluated against the cost ledger by PRP-46" (`packages/contracts/schemas/admin/v1/budget.schema.json:5`); PRP-46 shipped cost-center attribution and left evaluation undone.
- The data to evaluate exists. The ledger folds cost per domain with `cost_center` (`packages/core/neurosphere_core/ledger/models.py:145,212`), filters by domain and cost center (`ledger/totals.py:44-60` `LedgerFilters`), and reports per-currency totals with coverage and unresolved counts (`totals.py:63-115`, `LedgerReader.totals` `:124-132`). A forecast helper exists but lives in the API package (`services/api/neurosphere_api/finops/service.py:262` `build_forecast`), so a worker cannot call it; the evaluator needs its own core computation.
- Not everything a budget can say is evaluable. `SpendBudget.tags_filter` narrows to cost rows whose tags contain every key and value (`budget.schema.json:5,37-40`), but the ledger stores no tags, only `cost_center` (a grep of `ledger/` finds no tag field). The evaluator must say so rather than silently ignore the filter.
- The enforcement pieces exist but nothing connects them to a budget. `budget_cap_change` is routed to the APIM write connector (`packages/core/neurosphere_core/actions/targets.py:65`); it rewrites a grant's token limits, with a diff grammar and a dry run (`connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/cap.py:1-35`); a new kind is approval-required by default (`services/api/neurosphere_api/actions/settings.py:35-59`); and the action service takes a caller that is a real principal, never a worker (`packages/core/neurosphere_core/actions/models.py:119-133`). So the cut-off must be a human-initiated proposal. Automatic cut-off would bypass maker-checker (design section 8, item 14).
- Original promise (`docs/PRD.md` NS-03 cost governance and the stored budgets of PRP-44): alerts at thresholds; today none reach anyone. Owner direction of 2026-11-16: "the ultimate team AI governance and auditing tool", every gap planned; design gap G-i/G-b.

## Acceptance criteria
- [ ] Given a monthly budget of 1000 USD for a domain with thresholds 50, 80, 100 and ledger spend of 820 USD in the month, When the evaluator runs, Then thresholds 50 and 80 are reported crossed, 100 is not, status shows `spent`, `percent`, `projected` (run-rate to month end, labelled a projection) and `coverage`; no float arithmetic is used for money (decimal strings and `Decimal`).
- [ ] Given a crossing, When the evaluator runs twice, Then exactly one event is published per (budget, period start, threshold), through the PRP-107 publisher with that dedup key; a delivery to a local webhook receiver is asserted end to end in an integration test (real HTTP receiver, signed body, no secret or ledger line item in it).
- [ ] The message carries budget id, domain, threshold, period, percent and a link; it carries no amounts beyond the percent and spent/limit figures the recipient may already read, and is only delivered to subscriptions whose scope covers the budget's domain (PRP-107 scope rule; test with a second domain).
- [ ] Coverage honesty: given ledger entries with unresolved price or unknown amounts, Then status shows the known amount as "at least", `coverage` below 1 and the count of unresolved entries; a threshold crossing on a known lower bound is published with `lower_bound: true`; a budget in a currency with no entries shows `no_data`, never 0 percent.
- [ ] Given a budget with `tags_filter` keys other than `cost_center`, Then status is `not_evaluable` with reason `ledger_has_no_tags` and no event is published; a filter with only `cost_center` maps to `LedgerFilters.cost_center`.
- [ ] `GET /api/v1/finops/budgets` and `/{budget_id}/status` return the same computation through `data.read` on the budget's domain; a caller without access gets 404 (no existence leak) and a denial record; lists are bounded and paged.
- [ ] Policy rule: a `budget` rule (params: budget id, threshold percent) registered with the PRP-105 evaluator reports a violation record with evidence (budget id, period, percent) when the threshold is crossed and clears when the period rolls over; with `enforcement: audit` nothing else happens.
- [ ] Proposed enforcement: Given the cut-off threshold (the highest configured, or a threshold the budget marks `cutoff`) is crossed, Then the page offers "Propose cap change" to a caller holding `action.propose` on the domain; the click drafts a `budget_cap_change` intent through `ActionService.draft` with the caller's identity, evidence (budget id, period, percent) and the existing diff grammar, requires approval by a different principal, shows the exact diff and dry run, and nothing is applied until approved and confirmed. A test proves no code path in the worker or evaluator calls draft, confirm or apply.
- [ ] Honesty: the proposal UI states that a budget is money and a grant cap is tokens, that no conversion is assumed, and that the proposed reduction is a percentage chosen by the person; Government shows the gateway as advisory-only as the connector does.
- [ ] With the role not enabled or no budgets stored, behaviour is as today; the worker never throws on a malformed stored budget (reason code and skip).
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend lint, typecheck and tests, `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where status lives | New container; compute on read | ASSUMPTION: no new container. Status is computed from the ledger on each evaluation and each read; "already announced" is tracked by the PRP-107 outbox dedup key. This needs the publisher to take a per-event-class dedup window of at least one period (366 days); item 2 states it as a requirement on PRP-107's publisher (UNVERIFIED until PRP-107 is written; if absent, record the gap and stop) |
| 2 | Projection method | The API forecast; run-rate | ASSUMPTION: linear run-rate (spend to date over elapsed days, extended to the period end), labelled a projection with the days of data used and hidden below 7 days of data; the API `build_forecast` is not importable from a worker, and a richer forecast is a follow-up |
| 3 | Period windows | Rolling; calendar | Calendar UTC month, quarter, year from `SpendBudget.period`; ASSUMPTION: no fiscal-year offset (follow-up if asked) |
| 4 | What counts as spend | Estimated; invoiced; authoritative | The ledger entry's authoritative amount (`LedgerEntry.authoritative_amount`), with coverage shown; estimated-only entries count and lower the coverage label |
| 5 | Currency | Convert; match | Match the budget currency only; no conversion; other currencies are ignored and counted |
| 6 | Cut-off threshold | New field on the budget; highest threshold | ASSUMPTION: the highest `thresholds_percent` value is the cut-off point; a per-threshold `cutoff` flag would be a PRP-110/PRP-99 contract change and is not made here |
| 7 | Who proposes | Worker; person | A person with `action.propose` (`auth/scope/permissions.py:85`). The worker only alerts. Approval needs `action.approve` by someone else (self-approval refused by the executor) |
| 8 | `target_version` and grant choice | Guess; read | The person picks a grant of the budget's domain; `target_version` is the live fragment ETag read through the existing action-target read path for `grant` targets (item 5 verifies the route; if no read path works locally, the proposal is drafted only against a fake connector in tests and live use stays OPEN with G17) |
| 9 | Event classes | One; several | Contract `NotificationEventClass` values: `budget_threshold_crossed` (PRP-99), `budget_projection_exceeds_limit` and `budget_not_evaluable` (PRP-110, W25). PRP-107 has no separate registry and refuses classes outside the contract |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/admin/platform/budgets.py` and `packages/contracts/schemas/admin/v1/budget.schema.json` - the stored shape and the rules.
- `packages/core/neurosphere_core/ledger/totals.py:27-132` and `ledger/store.py:25-45` - `TimeWindow`, `LedgerFilters`, `CurrencyTotal`, `LedgerReader`, `LedgerStore.list_entries`.
- `services/api/neurosphere_api/finops/router.py` and `finops/service.py:262-330` - the API forecast to imitate, not import.
- `services/api/neurosphere_api/admin/platform/budgets.py` and `frontend/src/features/admin/pricing/BudgetsPanel.tsx`, `hooks.ts` - the existing CRUD and panel.
- `packages/core/neurosphere_core/actions/targets.py:59-80`, `actions/service.py:206-300` (`draft`), `actions/models.py:119-190` (`ActionCaller`, `DraftRequest`), `services/api/neurosphere_api/actions/settings.py:35-59`.
- `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/cap.py:1-60` - the `budget_cap_change` diff grammar.
- `services/workers/neurosphere_workers/hitl_timers/worker.py`, `runtime/roles.py:18-30`, `runtime/factories.py:481,1867-1879` - role shape and the ledger Cosmos wiring.
- `PRPs/backlog/PRP-105-policy-engine-core.md` (if present) and `PRP-107-notification-channels-and-subscriptions.md` - "Interfaces provided".

### Interfaces consumed
- Shipped (PRP-44): `BudgetAdmin.list`, `AdminConfigDocument` kind `budget`, `SpendBudget`.
- Shipped: `LedgerStore`, `LedgerReader`, `LedgerFilters`, `compute_totals`; `ActionService.draft`; `PermissionRechecker`; `ACTION_CONNECTORS["budget_cap_change"]`.
- PRP-107: `NotificationPublisher.publish(event class, customer, domain, entity ref, title, severity, link, dedup key)`, the dedup window per class (no event-class registry: classes are contract values). PRP-110: the two extra budget event classes.
- PRP-105: the rule-kind evaluator registry and violation record store; the design lists `model_allow_list`, `data_sensitivity_access`, `residency`, `required_owner`, `required_approval`, `registration_required` and `content_rule` there, and `budget` as a kind to be provided by this PRP. This PRP plugs in through PRP-105's extension point (`RuleBuildContext`, `RuleEvaluatorRegistry.discover`, one module in `governance/policy/rule_plugins/`).
- PRP-99: the `policy/v1` rule union entry for `budget` (design section 2.3).

### Interfaces provided
- Core `neurosphere_core.finops.budget_eval` (new package; creates `finops/__init__.py`, which PRP-134 later extends): `BudgetStatus`, `evaluate_budget(budget, ledger, now)`, `period_window(period, now)`, `crossed_thresholds`.
- Worker role `budget_eval` (new, in `ROLE_NAMES`).
- Routes: `GET /api/v1/finops/budgets`, `GET /api/v1/finops/budgets/{budget_id}/status`, `POST /api/v1/finops/budgets/{budget_id}/cutoff-proposal` (person, `action.propose`).
- Policy rule evaluator for kind `budget`.
- Event classes of clarification 9, consumed by PRP-132 alert rules.
- UI: `BudgetStatus.tsx` mounted on the Budgets screen.

### Patterns to match
- Pure windowed ledger computation: `ledger/totals.py:78-115` `compute_totals`.
- Domain-scoped read route with derived scope: `finops/router.py:40-75` (`ReadScope`, customer from scope only).
- Worker role with a periodic tick: `hitl_timers/worker.py`.
- Drafting through the service with the caller's identity: `services/api/neurosphere_api/actions/` routes (read the draft route first).

### Gotchas
- Money is a decimal string everywhere; do not parse to float; compare with `Decimal`. A budget `amount` and the totals' `Money` carry currency; mismatches are ignored, not converted.
- The ledger has no tags (Why); only `cost_center`.
- `LedgerStore.list_entries(customer_id, window)` is partitioned by customer only; the evaluator filters domain after the read. Bound the read by the period window and page it; a month of entries can be large (do not load the whole ledger).
- Evaluating at 100 percent of a budget that is already past its period: a rolled-over period starts a new dedup key, so old crossings never suppress new ones.
- `ActionCaller.principal_id` must be the real canonical principal id; never create a system caller to bypass this (acceptance test).
- A new `finops` core package: PRP-134 owns `finops/chargeback/**` later and must not recreate `finops/__init__.py`; this PRP creates it with an empty export list.
- Adding a role and routes changes pinned tests (`services/api/tests/runtime_api/test_readiness.py`, route inventories, worker role-name tests); list the edits.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/finops/__init__.py
  - packages/core/neurosphere_core/finops/budget_eval/**
  - packages/core/neurosphere_core/governance/policy/rule_plugins/budget.py
  - packages/core/tests/finops_budget_eval/**
  - services/workers/neurosphere_workers/budget_eval/**
  - services/api/neurosphere_api/finops/budgets/**
  - services/api/tests/finops_budgets_api/**
  - frontend/src/features/admin/pricing/BudgetStatus*.tsx
  - frontend/src/features/admin/pricing/BudgetsPanel.tsx
  - frontend/src/features/admin/pricing/hooks.ts
  - tests/integration/finops/test_budget_alert_delivery.py
  - docs/runbooks/budgets.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - frontend/tests/mock-api/features/index.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/admin/platform/budgets.py
  - packages/core/neurosphere_core/actions/**
  - connectors/reference/apim-gateway/**
  - packages/core/neurosphere_core/notifications/**
```

## Implementation blueprint

### Item 1 - Evaluation core
Deliverable: `finops/budget_eval`: `period_window`, `evaluate_budget` (spent, percent, projection, coverage, unresolved count, `lower_bound`, `not_evaluable`, `no_data`), `crossed_thresholds`; ledger read bounded by the period window and paged.
Owned files: `packages/core/neurosphere_core/finops/**`, `packages/core/tests/finops_budget_eval/**`.
Must NOT touch: ledger code. Depends on: none (PRP-44 and the ledger are shipped).
Acceptance criteria: criteria 1, 4, 5 at unit level; period rollover; decimal arithmetic.
Tests: `packages/core/tests/finops_budget_eval/test_periods.py`, `test_evaluate.py`, `test_coverage.py` (new directory name unique). Pattern references: `ledger/totals.py:78-115`.

### Item 2 - Evaluator worker role and event publishing
Deliverable: `budget_eval` worker (lists budgets per customer through the admin-config repository, evaluates, publishes through `NotificationPublisher` with dedup key `budget:<id>:<period start>:<threshold>` and a window of one period), registered in `ROLE_NAMES` and `BUILDERS` through a new builder module; event classes are contract values (clarification 9), nothing is registered. Uses PRP-107's per-event-class dedup window (PRP-107 "Interfaces provided"); stop if the publisher cannot take one.
Owned files: `services/workers/neurosphere_workers/budget_eval/**`, the `ROLE_NAMES` and `BUILDERS` lines.
Must NOT touch: notifications package. Depends on: item 1; PRP-107.
Acceptance criteria: criteria 2, 3 and the idempotence part of 1; malformed budget never throws.
Tests: `services/workers/neurosphere_workers/budget_eval/tests/test_budget_worker.py` (new); worker role-name tests updated.
Pattern references: `hitl_timers/worker.py`.

### Item 3 - Status API  [P]
Deliverable: list and status routes over the shared core function; derived scope; 404 without access.
Owned files: `services/api/neurosphere_api/finops/budgets/**`, `services/api/tests/finops_budgets_api/**`.
Must NOT touch: `finops/router.py` and `finops/service.py` (not owned; the forecast is not reused). Depends on: item 1.
Acceptance criteria: criterion 6.
Tests: `services/api/tests/finops_budgets_api/test_status_routes.py`; route inventory lines.
Pattern references: `finops/router.py:40-75`.

### Item 4 - Budget policy rule  [P]
Deliverable: the `budget` rule evaluator in `finops/budget_eval/policy_rule.py`, plugged in through PRP-105's extension point: one new plugin module `governance/policy/rule_plugins/budget.py` whose `build(ctx: RuleBuildContext)` builds the ledger reader from `ctx` and returns the evaluator (or `None` when the ledger is not configured, so `budget` stays `evaluator_unavailable`). No PRP-105 file is edited; worker and API pick it up through `RuleEvaluatorRegistry.discover`.
Owned files: `packages/core/neurosphere_core/finops/budget_eval/policy_rule.py`, `packages/core/neurosphere_core/governance/policy/rule_plugins/budget.py` (new).
Must NOT touch: any other file under `governance/policy/**`. Depends on: items 1, PRP-105, PRP-99.
Acceptance criteria: criterion 7.
Tests: `packages/core/tests/finops_budget_eval/test_policy_rule.py`.
Pattern references: the evaluators PRP-105 ships.

### Item 5 - Proposed cap change
Deliverable: `POST .../cutoff-proposal` drafting through `ActionService.draft` with the caller's identity; grant choice and target-version read through the existing grant target read path (verify the route first); evidence refs; no worker or evaluator import of the action service.
Owned files: `services/api/neurosphere_api/finops/budgets/proposal.py`.
Must NOT touch: `packages/core/neurosphere_core/actions/**`, the connector. Depends on: items 1, 3.
Acceptance criteria: criteria 8 and 9 (API part); a static test that the worker package never imports `neurosphere_core.actions.service`.
Tests: `services/api/tests/finops_budgets_api/test_cutoff_proposal.py` with the in-memory action service and a fake write connector; `tests/security/authz` case for a caller without `action.propose` and for self-approval refusal.
Pattern references: the existing actions draft route and `packages/core/tests/actions` fakes.

### Item 6 - Budget status UI
Deliverable: `BudgetStatus.tsx` on the Budgets screen: per budget bar with thresholds, spent, projection, coverage and not-evaluable reason, the propose button and the honesty text; hooks and mock-api feature.
Owned files: `frontend/src/features/admin/pricing/BudgetStatus*.tsx`, `BudgetsPanel.tsx`, `hooks.ts`.
Must NOT touch: shell files outside Tier-2 lines. Depends on: items 3, 5.
Acceptance criteria: criteria 8 and 9 (UI part); status not colour-only; keyboard reachable.
Tests: component tests beside the panel, extend `pricing.test.tsx`; e2e a11y route sample line.
Pattern references: `frontend/src/features/admin/pricing/BudgetsPanel.tsx`.

### Item 7 - Integration and close-out
Deliverable: end-to-end local test (seeded ledger, budget, subscription, local webhook receiver; assert one signed delivery, no repeat, no leak, the proposal path ends at `drafted`); Tier-2 appends; runbook `docs/runbooks/budgets.md`; `openapi.json` and docs regeneration; changelog fragment `changelog.d/PRP-115-budget-evaluation-alerts-and-enforcement.md`; completion note.
Owned files: `tests/integration/finops/test_budget_alert_delivery.py`, runbook, fragment. Depends on: items 1-6.
Acceptance criteria: criterion 2 end to end; reference section 6.

## Validation gates
```bash
uv run pytest -q packages/core/tests/finops_budget_eval packages/core/tests/ledger packages/core/tests/admin_platform services/workers/neurosphere_workers/budget_eval services/api/tests/finops_budgets_api services/api/tests/finops_api services/api/tests/admin_platform_api services/api/tests/runtime_api services/api/tests/authz tests/security/authz tests/integration/finops
uv run ruff check packages services tests
uv run pyright
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
No schema change and no new container (clarification 1). The role is off unless listed in `NS_WORKER_ROLES`; routes are read-only except the proposal draft. Roll back by removing the role and reverting the PR; announced thresholds stay in the outbox dedup window and are not re-sent after a re-enable within the period.

## Live and open gates
A real gateway cap change after approval needs the G17 APIM manage gate (`NS_LIVE_APPROVED=1`, operator) and stays OPEN, recorded for PRP-136; a real channel delivery is PRP-107's gate. Everything else runs locally with fakes and a local receiver.

## NOT building
- Automatic cut-off of any kind, or any "stop spending at the budget" guarantee; a proposal is a person's decision, approved by a second person.
- A conversion from money to tokens; the product proposes a percentage reduction of existing limits and says so.
- Tag-based budgets (the ledger has no tags), fiscal calendars, rolling windows, multi-currency conversion.
- A statistical forecast; the run-rate projection is labelled as such.
- Per-user or per-agent budgets (domain budgets only, as stored; the ledger carries no agent id, and per-agent data would also need PRP-137's resolved agent ids for OTLP agents).

## Definition of Ready check
- [x] Goal, Why and acceptance criteria are specific and testable.
- [x] Referenced paths verified in the worktree; new files marked (new) or listed under owns.
- [x] Dependencies named; PRP-105's extension point and PRP-107's per-class dedup window are taken from their "Interfaces provided".
- [x] Ownership block present; Tier-2 lines only; the pricing files are owned by no other backlog PRP.

## Execution state
| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 Evaluation core | todo | | |
| 2 Worker role and publishing | todo | | |
| 3 Status API | todo | | |
| 4 Budget policy rule | todo | | plugin module via PRP-105 discover |
| 5 Proposed cap change | todo | | |
| 6 Budget status UI | todo | | |
| 7 Integration and close-out | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
