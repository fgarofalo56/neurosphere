---
name: PRP-130-owner-reattestation-campaigns
status: backlog
priority: P2
order: 130
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-04, NS-08
depends_on: [PRP-105-policy-engine-core, PRP-107-notification-channels-and-subscriptions, PRP-110-governance-contracts-b, PRP-76-catalog-registration-completeness]
wave: W31
branch: prp-130-attestation-campaigns
allow_parallel: true
issues: []
---

# PRP-130: Owner re-attestation campaigns

## Goal
Turn the one-off "recertify an owner" button into a scheduled governance practice. A steward starts a campaign with a due date and a cadence; a worker creates one attestation obligation per in-scope subject (an owner for `owner_recertification`, an agent for `agent_attestation`), sends reminders and escalations through the PRP-107 notification service, marks obligations overdue, and routes non-responses to a HITL review. The accountable person records an attestation ("still owned", "still needed", "configuration reviewed", "retire requested"); an attested record is immutable. Overdue or never-attested becomes a policy rule evaluator (`required_attestation`) for PRP-105, and a campaign has an exportable evidence record for auditors. It is for domain stewards, agent owners and security auditors.

Out of scope: the contracts (PRP-110 owns `Attestation`, the notification event classes and PRP-99 the rule params); channels and delivery (PRP-107); policy storage, violations and exceptions (PRP-105); the register and containers (PRP-127 declares `attestations` and `attestation_campaigns`); retiring or deprecating an agent (a retire request only notifies and opens a review; lifecycle change stays with the existing deprecate path); per-person email (PRP-107 channels are group-addressed); lifecycle-engine registration of the new data class (a follow-up with PRP-83).

## Why
- `docs/PRD.md:17` promises "ownership recertification" as part of NS-02 lifecycle. What exists is a per-owner write: `CatalogService.recertify` stamps `recertified_at` and `recertify_by` (`services/api/neurosphere_api/catalog/service.py:369-395`), the route needs `catalog.curate` (`services/api/neurosphere_api/catalog/router.py:217`), and `due_recertifications` is a pull-only listing capped at 10 scan pages (`catalog/service.py:94,514-556`).
- Nothing schedules it: no worker role touches owners (`services/workers/neurosphere_workers/runtime/roles.py:18-30`), owners with no `recertify_by` "are not scheduled and not listed" (`catalog/service.py:522-525`), and no reminder or notification is sent (`packages/core/neurosphere_core/hitl/notify.py:80-138` stubs only; PRP-107 makes delivery real).
- Only owners can be recertified (`catalog/service.py:381-387`, `not_an_active_owner`); no per-agent attestation exists, and the lifecycle has no review state (`catalog/v1/common.schema.json:58-66`).
- The control library already counts owners overdue and recertified in window (`packages/core/neurosphere_core/compliance/sources/catalog.py:26-31`), so a campaign that keeps `recertify_by` current feeds evidence with no new source.
- PRP-99 defines `RequiredAttestationParams` and PRP-105 leaves `required_attestation` to PRP-130 through `RuleEvaluatorRegistry`; PRP-110 defines `Attestation` and the event classes `attestation_due` and `attestation_overdue`.
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool"; stale ownership is how agents become orphaned.

## Acceptance criteria
- [ ] Given a steward with `attestation.manage` on a domain, When they create and activate a campaign (kind, subject selector, due date, optional cadence, reminder offsets, escalation days), Then the worker creates exactly one `pending` obligation per matching active subject (re-running creates none), each with `due_at`; subjects outside the caller's domain scope are never selected.
- [ ] Given an obligation, When the accountable person attests (`still_owned`, `still_needed`, `config_reviewed` or `retire_requested`), Then the record becomes `attested` with `attested_by` derived server-side and `attested_at`, an audit record names it, and it can never be modified, deleted or re-opened through any route or store call (`attestation_sealed`); a correction is a new attestation whose `evidence_ids` name the earlier one.
- [ ] Who may attest: for an agent, a principal that is the person owner linked by an `owned_by` edge, or a caller with `catalog.curate` in the domain when the owner is a group, team or service principal; for an owner record, the person it names or a `catalog.curate` caller. Anyone else gets 403 and a denial record; the agent's maker cannot be the sole attestor of their own submission when a different owner exists (documented rule, tested).
- [ ] An `owner_recertification` attestation results in the existing owner fields being stamped (`recertified_at`, `recertify_by`), so the PRP-56 `catalog_ownership` source reports it; `retire_requested` changes no lifecycle status and opens a review and a notification only.
- [ ] Reminders and escalation: Given reminder offsets, When the worker ticks past an offset, Then one `attestation_due` event is published per (obligation, offset) through the PRP-107 publisher with a dedup key, and re-running publishes none; past `due_at` the obligation becomes `overdue` and one `attestation_overdue` event with higher severity is published; the message carries ids, titles and links only.
- [ ] Non-response: after the escalation days one HITL item (kind `recommendation`, `action_kind` `attestation_overdue_review`) opens per overdue obligation, reviewed by a `catalog.curate` caller; approve records the obligation `waived` (the gap is recorded, reminders stop, nothing is marked attested), reject leaves it `overdue`; the review page shows the obligation, subject, owner and history (the context record).
- [ ] `required_attestation` evaluator: Given a published PRP-105 policy with that rule, When the evaluator runs, Then a subject with no `attested` record of the kind within `max_age_days` has an open violation with evidence ids, and attesting resolves it on the next run; `waived` does not satisfy the rule (only a PRP-105 exception suppresses it).
- [ ] Campaign evidence: `GET .../campaigns/{id}/evidence` (`evidence.read`) returns counts by status and the attestation ids, kinds, statuses, due and attested times and pseudonymous attestor ids with a `sha256` of the canonical bytes; no names, notes or entity titles; it carries no verdict or percentage and passes `scan_for_claims`.
- [ ] Scope and secrecy: reads are scope-filtered, a foreign id is 404, nothing in a notification, audit detail or log contains an owner name, address or note.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend typecheck and test, `validate_planning.py` pass; PR open, CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Campaign shape | Contract; core-local | PRP-110 has no campaign schema (design gap). ASSUMPTION: a core-local Pydantic model stored in `attestation_campaigns`, not a wire contract; a later contracts wave may promote it |
| 2 | Immutability | WORM store; application-level plus audit | Application-level: the store refuses any replace or delete of an `attested` or `waived` record, every transition is an audit record with a state digest (`audit_chain` is the tamper-evident part). Not claimed to be WORM |
| 3 | Recipients | Per-person address; group channel | PRP-107 channels are group-addressed (no per-person address). Reminders go to the domain's subscribed audience; the owner's own list is the "My attestations" page. Stated in the runbook |
| 4 | HITL kind for non-response | New kind; existing | ASSUMPTION (GD-47, recommended default): impact-assessment review and attestation non-response use the existing HITL `recommendation` kind with action kinds `impact_assessment_review` and `attestation_overdue_review`; no new HITL kind. Here: `attestation_overdue_review` (a new kind edits `hitl/models.py` and a contract, outside this PRP) |
| 5 | Meaning of waive | Satisfies the rule; records the gap | ASSUMPTION (GD-37, recommended default): waiving an attestation records the gap and keeps the related policy violation open unless a PRP-105 exception covers it. Here: reminders stop; there is one way to excuse a rule |
| 6 | Permissions | Reuse `catalog.curate`; new | ASSUMPTION: new `attestation.manage` (create, activate, close campaigns) to domain_steward and admin; attesting is ABAC by ownership plus `catalog.curate`; reading uses `data.read` |
| 7 | Applying the owner stamp | Caller; worker | ASSUMPTION: the `attestation` worker applies the stamp under its own derived scope (the PRP-108 pattern), retrying until `recertified_at` is at least `attested_at`; verify first whether the repository write needs `catalog.curate` for the caller (UNVERIFIED) |
| 8 | Lifecycle registration of the data class | Now; follow-up | Follow-up with PRP-83; records are retained (container has no TTL, PRP-127) |
| 9 | Event class names | PRP-110; registry data | Use PRP-110's `attestation_due` and `attestation_overdue`; PRP-107's registry mention of "classes as data" is satisfied by the contract list. Verify at execution |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/catalog/service.py:94-99,369-400,512-560` - `recertify`, `due_recertifications`, the owner fields.
- `services/api/neurosphere_api/catalog/router.py:210-240,336-350` - routes, `CurateAccess`.
- `packages/contracts/schemas/catalog/v1/owner.schema.json:42-117` and `owned_by.schema.json` - `owner_kind`, `principal_id`, `recertified_at`, `recertify_by`.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` ("Attestation", notification event classes), `PRP-99-governance-contracts-a.md` (`RequiredAttestationParams`), `PRP-107-notification-channels-and-subscriptions.md` (`NotificationPublisher`, dedup), `PRP-105-policy-engine-core.md` (`RuleEvaluator`, `RuleEvaluatorRegistry`), `PRP-127-ai-system-register-tiering-and-impact-assessments.md` (containers).
- `services/workers/neurosphere_workers/hitl_timers/worker.py` and `runtime/roles.py:18-30` - scheduled worker shape and role names.
- `packages/core/neurosphere_core/hitl/service.py:141-200,269-330` - `open_item`, `decide`.
- `packages/core/neurosphere_core/compliance/sources/catalog.py` - how recertification is counted today.
- `services/api/neurosphere_api/catalog/dependencies.py:97` - `entity_access`.

### Interfaces consumed
- PRP-110: `neurosphere_contracts.risk.v1.Attestation` {`attestation_id`, `subject_id`, `attestation_kind`, `campaign_id`, `statement_code`, `status` pending|attested|overdue|waived, `due_at`, `attested_by`, `attested_at`, `evidence_ids`}; notification classes `attestation_due`, `attestation_overdue`. UNVERIFIED until merged; PRP-110 wins.
- PRP-99: `RequiredAttestationParams` {`attestation_kind`, `max_age_days`}, `PolicyRuleKind` `required_attestation`.
- PRP-105: `RuleEvaluator`, `RuleEvaluatorRegistry.register`, violation store (read through the engine, written by the engine).
- PRP-107: `NotificationPublisher.publish(event)` with dedup key and window.
- PRP-127: containers `attestations` and `attestation_campaigns` (partition `/customer_id`, `/domain_id`), declared there.
- PRP-76: registration form owners and the catalog completeness view (the source of "agents without an owner").
- Shipped: `CatalogRepository`, `CatalogService.recertify`, HITL service, `audited_read`, `run_audited_mutation`.

### Interfaces provided
- Core `neurosphere_core.catalog.attestation`: `AttestationCampaign` (core-local), `CampaignStore`, `AttestationStore` (in-memory and Cosmos), `plan_campaign`, `plan_reminders`, `seal` rules, `RequiredAttestationEvaluator` (kind `required_attestation`), `campaign_evidence`; the plugin file `neurosphere_core.governance.policy.rule_plugins.required_attestation` (`build(ctx)`), discovered by PRP-105.
- Worker role `attestation` (new in `ROLE_NAMES`), builder `neurosphere_workers.attestation.assembly.build_attestation`, settings `NS_ATTESTATION_INTERVAL_SECONDS` (900), `NS_ATTESTATION_SUBJECT_BUDGET` (2000), `NS_ATTESTATION_TIME_BUDGET_SECONDS` (120).
- Permission `Permission.ATTESTATION_MANAGE = "attestation.manage"`.
- Routes under `/api/v1/catalog/attestations`: `GET|POST /domains/{domain}/campaigns`, `GET /domains/{domain}/campaigns/{id}`, `POST .../campaigns/{id}/activate`, `POST .../campaigns/{id}/close`, `GET .../campaigns/{id}/evidence`, `GET /domains/{domain}/obligations` (`?mine=true`), `GET /domains/{domain}/obligations/{id}`, `POST /domains/{domain}/obligations/{id}/attest`.
- Audit operations `attestation.campaign_create`, `attestation.campaign_activate`, `attestation.campaign_close`, `attestation.record`, `attestation.overdue`, `attestation.waive`, `attestation.escalate`, `attestation.owner_stamp`.
- Frontend `frontend/src/features/attestation/` (campaigns, campaign detail, "My attestations"); mock `frontend/tests/mock-api/features/attestation.ts`.

### Patterns to match
- Scheduled worker with checkpoint-free ticks and an ETag race on the store: `services/workers/neurosphere_workers/hitl_timers/worker.py`.
- Role and builder registration: `services/workers/neurosphere_workers/runtime/roles.py:18-30`, the `BUILDERS` table at the end of `runtime/factories.py`.
- Audited mutation and `If-Match`: `services/api/neurosphere_api/mcp/admin/router.py:96-198`.
- Evidence counting with caps and `truncated`: `packages/core/neurosphere_core/compliance/sources/catalog.py`.
- Page layout: `frontend/src/features/review/ReviewQueuePage.tsx`.

### Gotchas
- A HITL item carries only an opaque `subject_ref`: the obligation page is the context record (PRP-16 round-2 lesson); the review UI must link to it.
- `recertify` expects the stored owner entity and ETag, and only an `active` owner (`catalog/service.py:381-387`); re-read before stamping and skip owners that became inactive.
- Owners with no `recertify_by` are not listed today (`catalog/service.py:522-525`); a campaign selects by entity type and tags, not by that field.
- `Owner.principal_id` is a pseudonymous person id or null; group, team and service-principal owners have none, which is why curators attest for them.
- The worker has no `IdentityScope`; it builds its own derived system scope as other roles do. Do not widen it past the campaign's domain.
- Reminders are at-least-once: dedup on (campaign, subject, offset); the PRP-107 dedup key must contain the cycle start so a cadence repeat is not suppressed.
- New role names and a builder pin tests: worker role-name tests, `services/api/tests/runtime_api/test_readiness.py`, the route inventories; list each update.
- New test directories get unique names (`packages/core/tests/attestation_core`, `services/workers/tests/attestation_worker`, `services/api/tests/attestation_api`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/catalog/attestation/**
  - packages/core/neurosphere_core/governance/policy/rule_plugins/required_attestation.py
  - packages/core/tests/attestation_core/**
  - services/workers/neurosphere_workers/attestation/**
  - services/workers/tests/attestation_worker/**
  - services/api/neurosphere_api/catalog/attestation/**
  - services/api/tests/attestation_api/**
  - frontend/src/features/attestation/**
  - frontend/tests/mock-api/features/attestation.ts
  - tests/security/authz/test_attestation_access.py
  - docs/runbooks/attestation-campaigns.md
tier1: []
tier2_appends:
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/hitl/**
  - packages/core/neurosphere_core/governance/policy/rules/**
  - packages/core/neurosphere_core/notifications/**
  - packages/core/neurosphere_core/compliance/**
  - packages/core/neurosphere_core/stores/containers.py
  - services/api/neurosphere_api/catalog/service.py
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/catalog/approval/**
  - services/api/neurosphere_api/catalog/access/**
  - frontend/src/features/catalog/**
```
The evaluator is exposed by the new plugin file `governance/policy/rule_plugins/required_attestation.py` (`build(ctx: RuleBuildContext) -> RuleEvaluator | None`), discovered by PRP-105's `RuleEvaluatorRegistry.discover`; no file owned by PRP-105 is edited and `policy_eval/assembly.py` is not in this PRP's ownership.

## Implementation blueprint

Parallelization: item 1 first; items 2 and 6 [P] after 1; 3 after 2; 4 after 2; 5 after 1 and 2; 7 after 3-6; 8 last.

### Item 1 - Models, stores and sealing
- Deliverable: `AttestationCampaign` model, `CampaignStore` and `AttestationStore` ports with in-memory and Cosmos implementations over the PRP-127 containers, the status machine (`pending -> attested | overdue | waived`, `overdue -> attested | waived`), sealing of `attested` and `waived`, deterministic obligation ids (campaign, subject, cycle) so creation is idempotent.
- Owned files: `packages/core/neurosphere_core/catalog/attestation/{models,store,cosmos_store,state}.py`, `packages/core/tests/attestation_core/**`.
- Depends on: PRP-110 and PRP-127 merged.
- Acceptance criteria: criteria 1 (idempotence), 2 (sealing), 9; a sealed record rejects replace and delete in both stores.
- Tests: `packages/core/tests/attestation_core/test_state.py`, `test_store.py`, `test_cosmos_store.py`, `test_sealing.py`.
- Pattern references: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.

### Item 2 - Planner, reminders, escalation and evidence  [P]
- Deliverable: pure functions: `plan_campaign` (subjects from a catalog snapshot, scope-filtered), `plan_reminders` (offsets, overdue, escalation, cycle-aware dedup keys), `campaign_evidence` (counts, ids, sha256, no names), cadence roll-over.
- Owned files: `packages/core/neurosphere_core/catalog/attestation/{planner,reminders,evidence}.py`, tests.
- Depends on: item 1.
- Acceptance criteria: criteria 1, 5, 8; planner output is a pure function of its inputs; evidence passes `scan_for_claims`.
- Tests: `packages/core/tests/attestation_core/test_planner.py`, `test_reminders.py`, `test_evidence.py`.
- Pattern references: `compliance/sources/catalog.py`, `hitl/timers.py`.

### Item 3 - `required_attestation` evaluator
- Deliverable: `RequiredAttestationEvaluator` (violation per subject without an `attested` record of the kind in `max_age_days`, evidence ids, truncation reason) exposed by a new plugin file `governance/policy/rule_plugins/required_attestation.py` whose `build(ctx)` builds the attestation store from `ctx` (or returns `None` when it is not configured), so the worker and the API both discover it and no shared assembly file is edited.
- Owned files: `packages/core/neurosphere_core/catalog/attestation/rule.py`, `packages/core/neurosphere_core/governance/policy/rule_plugins/required_attestation.py`, tests.
- Depends on: item 2; PRP-105 merged.
- Acceptance criteria: criterion 7; with the evaluator absent PRP-105 reports `evaluator_unavailable` as designed.
- Tests: `packages/core/tests/attestation_core/test_rule.py`, `services/workers/tests/attestation_worker/test_policy_registration.py`.
- Pattern references: PRP-105 evaluator modules for the seven kinds it ships.

### Item 4 - Worker role
- Deliverable: role `attestation` with `build_attestation`: tick materializes obligations, marks overdue, publishes reminders through `NotificationPublisher`, opens the HITL escalation item (kind `recommendation`, action kind `attestation_overdue_review`), applies the owner stamp, applies HITL outcomes (waive) idempotently, all under per-subject and time budgets; Tier-2 role and builder lines.
- Owned files: `services/workers/neurosphere_workers/attestation/**`, `services/workers/tests/attestation_worker/**`, Tier-2 lines.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 1, 4, 5, 6; a second worker racing loses on the ETag and skips; a budget overrun leaves a reason code, not a crash.
- Tests: `services/workers/tests/attestation_worker/test_tick.py`, `test_reminders_once.py`, `test_escalation.py`, `test_owner_stamp.py`; worker role-name tests.
- Pattern references: `hitl_timers/worker.py`, `runtime/roles.py:18-30`.

### Item 5 - API routes
- Deliverable: routers, dependencies and models for the routes in "Interfaces provided"; attest authorization by ownership (resolving owners through `owned_by` edges) or `catalog.curate`; `If-Match` on campaign changes; every mutation audited; evidence export route.
- Owned files: `services/api/neurosphere_api/catalog/attestation/**`, `services/api/tests/attestation_api/**`, Tier-2 route lines, the permission line and role tests.
- Depends on: items 1 and 2.
- Acceptance criteria: criteria 2, 3, 8, 9.
- Tests: `services/api/tests/attestation_api/test_campaigns.py`, `test_attest.py`, `test_scope.py`, `test_evidence_route.py`.
- Pattern references: `catalog/router.py:210-240`, `compliance/router.py`.

### Item 6 - Frontend  [P]
- Deliverable: campaigns list and detail (counts by status, overdue list), create form, "My attestations" with the attest dialog (statement choice), review context link; mock handlers; a11y sample.
- Owned files: `frontend/src/features/attestation/**`, `frontend/tests/mock-api/features/attestation.ts`, Tier-2 frontend lines.
- Depends on: item 1 (types).
- Acceptance criteria: keyboard operable; no owner names beyond what the catalog already shows; strings pass the claim scan.
- Tests: `pnpm --filter @neurosphere/frontend test`, typecheck, e2e sample.
- Pattern references: `frontend/src/features/review/ReviewQueuePage.tsx`.

### Item 7 - Authorization, immutability and delivery suite
- Deliverable: ABAC deny cases (no role, viewer, non-owner, wrong domain, wrong customer, expired assignment), a sealing test through every route and store call, a no-content test over notifications, audit and logs, and an end-to-end local test (campaign, reminder to a local sink, overdue, HITL waive, attest, rule violation resolves).
- Owned files: `tests/security/authz/test_attestation_access.py`, `tests/integration/attestation/**` (new; add the `integration` marker note: the python CI job skips it, so also keep unit equivalents).
- Depends on: items 3-6.
- Acceptance criteria: criteria 2, 3, 5, 6, 7, 9.
- Tests: `tests/security/authz`, `tests/integration/attestation`.
- Pattern references: PRP-41 item 5; PRP-132 item on end-to-end delivery.

### Item 8 - Integration and close-out
- Deliverable: runbook `docs/runbooks/attestation-campaigns.md` (cadence, reminders, group addressing, waive semantics, immutability caveat), Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), changelog fragment `changelog.d/PRP-130-owner-reattestation-campaigns.md`, completion note.
- Owned files: the runbook, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/attestation_core packages/core/tests/hitl packages/core/tests/auth packages/core/tests/compliance_lib services/workers/tests/attestation_worker services/api/tests/attestation_api services/api/tests/catalog_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/authz tests/security/authz tests/integration/attestation services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive: two containers declared by PRP-127, a worker role that is off unless listed in `NS_WORKER_ROLES` (the Helm chart keeps workers idle unless `workers.roles` is set), new routes and a permission. With no campaign nothing runs. Roll back by removing the role from `NS_WORKER_ROLES` and closing campaigns; reverting the PR removes the routes and the evaluator (PRP-105 then reports `required_attestation` unavailable). Existing owner recertification is unchanged throughout. Attested records already written stay readable.

## Live and open gates
None run: in-memory and emulator twins and a local notification sink only. A real delivery of a reminder to a Teams or webhook channel is PRP-107's gate (PRP-136); a hosted campaign run is shown by the hosted demo and is OPEN until an operator runs it.

## NOT building
Retiring or deprecating an agent from an attestation; per-person email or chat messages (PRP-107 is group-addressed); automatic attestation on someone's behalf; a campaign contract schema; a WORM store or cryptographic notarization (the audit chain is the tamper evidence); lifecycle-engine registration of the new data class; an owner-less-agent finder (PRP-76 completeness view); scoring or percentages of attestation coverage; any statement that an attestation makes an agent compliant, certified or authorized.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 4, 5, 6 and 7 are ASSUMPTIONS for plan approval; row 7 is UNVERIFIED)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: `NS_ATTESTATION_INTERVAL_SECONDS`, `NS_ATTESTATION_SUBJECT_BUDGET`, `NS_ATTESTATION_TIME_BUDGET_SECONDS`; add `attestation` to `NS_WORKER_ROLES`.
- Follow-up issues:
- Product check (can an operator use it without editing files): a steward creates a campaign in the console and an owner attests from "My attestations".
