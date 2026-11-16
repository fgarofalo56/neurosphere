---
name: PRP-106-policy-violations-and-exceptions-ui
status: backlog
priority: P0
order: 106
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-04, NS-06, NS-10
depends_on: [PRP-105-policy-engine-core]
wave: W23
branch: prp-106-policy-ui
allow_parallel: true
issues: []
---

# PRP-106: Governance policy, violations and exceptions UI

## Goal
Give stewards, admins and auditors the screens for the PRP-105 policy engine: a policies list; a policy page with its rules, version history and a version diff, its enforcement bindings and the point capability statement; a typed draft editor with one form per rule kind (never a free-text rule box); a violations list with evidence drill-down to the catalog graph, interaction metadata and audit; an exception request from a violation and the status of every exception; and, after PRP-108 merges, two proposal buttons (suspend the offending agent version, change a binding's enforcement mode). Every governed change is drafted as an action intent through the existing executor or opened as a HITL `policy_exception` item; the UI never writes a published state, a mode, a violation status or an exception decision itself. It is frontend work on the mock API, with route coverage in the real-stack and accessibility suites. It runs in W23 after PRP-105, beside PRP-104 (interaction explorer, merges first) and PRP-108 (platform-control, merges after this PRP's first six items).

Out of scope: the engine, stores, evaluator and routes (PRP-105); the platform-control target that executes publish, retire, mode change and suspend (PRP-108); the agent approval panel on the catalog page (PRP-108); the enforcement bindings page across all points and gateway apply (PRP-112, `frontend/src/features/governance/enforcement/**`) and its tool and MCP rows (PRP-113); the governance trail page (PRP-109, which adds its link to this PRP's violation page); interaction content (PRP-104; this PRP shows metadata ids only); copilot and MCP governance tools (PRP-116).

## Why
- There is no governance policy screen: `frontend/src/features/` has no `governance` directory, `frontend/src/app/appRoutes.ts:36-64` registers no policy or violation route, and the Governance nav group (`frontend/src/app/workspaceNav.ts:71-85`) has no policy entry. PRP-105 ships routes only; without this PRP a steward must call raw APIs (reference section 6 product check).
- HITL already has the `policy_exception` kind (`packages/core/neurosphere_core/hitl/models.py:41-52`, reviewer `catalog.curate`, `hitl/policy.py:70`) and the review queue renders it (`frontend/src/features/review/types.ts:7-16`), but nothing in the UI can open one.
- `docs/PRD.md:23`: "Route ... policy exceptions to scoped reviewers ... prohibit self-approval where configured." `docs/PRD.md:31`: "The same action API serves copilot, recommendation buttons, REST and MCP ... unsupported actions are advisory, not catalog-only pretend changes." The UI must use that one path.
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool", every gap planned; the governance-core design (`temp/audit/governance-core-design.md`, PRP-106 entry) scopes this UI and its section 8 lists what may not be claimed (no block outside the PRP-105 capability table).
- PRP-109's north-star chain assumes the violation page can propose the fix with the violation's canonical id as evidence (`PRPs/backlog/PRP-109-north-star-scenario-acceptance.md:47`); nothing else in W23 offers that button.

## Acceptance criteria
- [ ] Given a steward with `govpolicy.read` in domain D, When they open `/governance/policies?domain_id=D`, Then they see each policy with status, mode, severity, rule count and current version; a draft, a published and a retired policy each render; an empty domain shows the empty state; a 403 shows the forbidden state, not an error.
- [ ] The policy page shows rules (kind, applies-to, parameters as labelled read-only fields), the version list, a diff of any two versions (added, removed and changed rules and parameters), and every binding with point, target, mode and state, each with the capability statement for its point from the PRP-105 table; nothing on screen says a point blocks what the table says it cannot, and `sdk` always reads "cooperative, not a control".
- [ ] The draft editor offers one form per known rule kind with typed inputs matching the PRP-99 parameter schemas (bounded lists, enums as selects, numbers with min and max); unknown kinds (for example PRP-110's `identity_entitlement` before this UI learns it) are shown read-only with "no editor in this version"; kinds the server reports `evaluator_unavailable` show a warning. Save is `POST` (new) or `PUT .../draft` with `If-Match`; a 412 shows "changed by someone else, reload" and never overwrites.
- [ ] Publish and retire call PRP-105's routes and show the returned intent (state, kind `governance_policy_publish`, target, version) with a link to `/actions/detail`; the policy keeps showing `draft` until the server says otherwise. Before PRP-108 is merged the intent shows as advisory with the server's reason; the UI does not hide or restate it.
- [ ] The violations list filters by status, severity, policy and rule kind, paginates with the server cursor, and links each row to a violation page with subject, rule, first and last seen, occurrence count and evidence. Evidence links: `catalog_entity` to `/catalog/entity`, `relation` to `/catalog/edge`, `interaction_record` to PRP-104's `/interactions` (metadata only), `audit_record` to `/audit` for the domain with the id shown; other kinds show the id as text. No interaction text is fetched or rendered anywhere in this feature.
- [ ] Given a caller with `action.propose`, When they request an exception on an open violation (reason code from a list, bounded justification text, expiry no later than the server maximum), Then the PRP-105 `exception-requests` route is called, the returned HITL item id links to `/review/item`, and the exception appears as `requested`; the UI offers no approve or reject control for exceptions (decisions happen in the review queue by a `catalog.curate` reviewer); a self-review attempt is refused by the server and the message is shown.
- [ ] The exceptions list shows status, subject, rule, requester, expiry and review item for every exception the caller may read.
- [ ] `[serial-after: PRP-108]` From a violation whose subject is an agent version, "Propose suspension" drafts `agent_version_suspend` through PRP-108's suspend route with the violation's canonical id `<cloud>:<customer>:neurosphere:policy_violation:<id>` as evidence; from a binding, "Propose mode change" drafts `enforcement_mode_change` through the actions API with the PRP-105 diff grammar; both open `ChangeConfirmDialog` with the exact target, version and diff and say "NeuroSphere state change"; `enforce` is offered only for points whose capability says they can block.
- [ ] Every new route is in `route-manifest.json`, has an axe sample in `route-samples.ts` and an entry in the real-stack `routes.spec.ts` with its expected 403 and empty states; mock handlers serve every API path the pages call; lint, typecheck, unit tests and the e2e spec pass.
- PRP exit: frontend lint, typecheck, test, format and test:e2e pass; `validate_planning.py` passes; PR open with CI green (including `frontend-e2e`).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How exceptions are requested and decided | Edit the exception; action intent; HITL | HITL, as PRP-105 built it: the request route opens a `policy_exception` review item, a `catalog.curate` reviewer decides in the existing review queue, the evaluator reads the outcome. The UI has no exception write besides the request |
| 2 | Policy draft edits | Executor intent; direct draft write | Direct `POST`/`PUT .../draft` with `If-Match` (a draft governs nothing); publish, retire and mode change are executor intents (PRP-105 clarification 3) |
| 3 | Where the point capability text comes from | Server; frontend copy | ASSUMPTION: `capabilities.ts` mirrors PRP-105 `ENFORCEMENT_POINT_CAPABILITIES` (point, can block, what it blocks); a unit test pins the point list to the PRP-99 `EnforcementPoint` TypeScript type; if PRP-105's `GET /status` returns the table, the UI reads it instead and the copy is only the fallback. PRP-112 imports this module |
| 4 | Mode-change drafting route | New server route; generic actions route | Decided by the owner 2026-11-16 (GD-44): `enforcement_mode_change` is drafted through the generic `POST /api/v1/actions/domains/{domain}/intents` with PRP-105's `mode_change_diff` grammar; no dedicated route. Here: the UI sends the binding version, and PRP-108's handler validates the diff (`parse_mode_change_diff`) |
| 5 | Suspend evidence | Reason text; violation id as evidence | Violation canonical id in `evidence`: PRP-108's suspend route accepts an optional `evidence` list and copies it into the intent (PRP-108 "Interfaces provided"), which PRP-109's trail follows |
| 6 | Enforcement default | `audit`; `enforce` | Decided by the owner 2026-11-16 (GD-7): `audit` for every policy and point; `enforce` only by an approved action, per point |
| 7 | Exception approver | Several | ASSUMPTION: PRP-105 clarification 7 (requester `action.propose`; reviewer `catalog.curate`; no self-review) |
| 8 | Who sees policies | Several | Decided by the owner 2026-11-16 (GD-21): `govpolicy.read` is held by viewer, analyst, domain_steward, admin and security_auditor; `govpolicy.manage` (drafting and recording) by domain_steward and admin. Here: nav entries are shown to all and the API decides |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-105-policy-engine-core.md` "Interfaces provided" and acceptance criteria - every route, field and reason code this UI calls.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided", Policy section - `PolicyDefinition`, rule kinds and parameter types, `PolicyViolation`, `PolicyException`, `EnforcementBinding`.
- `frontend/src/features/compliance/` (`paths.ts`, `routes.tsx`, `data.ts`, `CompliancePage.tsx`, `ControlDetailPage.tsx`) - a list-plus-detail feature with light route modules.
- `frontend/src/api/query.tsx:51,93` - `createQueryHook`, `createMutationHook`.
- `frontend/src/features/admin/shared/useEtagMutation.ts` - ETag and `If-Match` mutation pattern.
- `frontend/src/features/governed-change/ChangeConfirmDialog.tsx` - exact target, version and diff confirmation.
- `frontend/src/features/actions/request.ts` - building a draft intent body on the client; `actions/routes.tsx` (`/actions/detail?intent_id=`).
- `frontend/src/features/review/routes.tsx` (`/review/item?item_id=`), `catalog/paths.ts:89` (`entityHref`), `curation/paths.ts:41` (`edgeHref`), `audit/paths.ts` (`audit_domain`).
- `frontend/src/app/appRoutes.ts`, `workspaceNav.ts`, `route-manifest.json`, `frontend/tests/mock-api/features/index.ts`, `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/real-stack/routes.spec.ts` - the registries.
- `frontend/tests/mock-api/features/compliance.ts` and `context.ts` - mock handler shape.

### Interfaces consumed
- PRP-105 routes under `/api/v1/governance/policy`: `GET|POST /domains/{domain}/policies`, `GET .../policies/{policy_id}` (`?version=`, `ETag`), `GET .../versions`, `PUT .../draft` (`If-Match`), `POST .../publish`, `POST .../retire` (intent view), `GET /domains/{domain}/violations`, `GET .../violations/{violation_id}`, `POST .../violations/{violation_id}/exception-requests`, `GET /domains/{domain}/exceptions`, `GET /domains/{domain}/bindings`, `GET /status`; reason codes `invalid_schema`, `stale_version`, `policy_published`, `rule_kind_unavailable`, `enforce_requires_mode_change`; `ENFORCEMENT_POINT_CAPABILITIES`; diff grammar `mode_change_diff`; canonical id `<cloud>:<customer>:neurosphere:policy_violation:<id>`.
- PRP-99 TypeScript bindings `packages/contracts/ts/src/policy/v1/*` (`PolicyDefinition`, `PolicyRule`, the nine `*Params`, `PolicyViolation`, `PolicyException`, `EnforcementBinding`, `EnforcementPoint`, `EnforcementMode`).
- PRP-104 (merges before this PRP in W23): app route `/interactions` (metadata view; verify the query parameter name for one interaction in its `paths.ts`).
- PRP-108 (serial item only): `POST /api/v1/catalog/approvals/domains/{domain}/agent-versions/{entity_id}/suspend`; platform-control executes `enforcement_mode_change` and `governance_policy_publish`.
- Shipped: actions API `POST /api/v1/actions/domains/{domain}/intents` (`services/api/neurosphere_api/actions/router.py:106-123`, body `DraftIntentBody` `actions/models.py:51-73`), the review queue pages, `ChangeConfirmDialog`.

### Interfaces provided
- App routes: `/governance/policies`, `/governance/policy` (`?domain_id=&policy_id=&version=`), `/governance/policy/edit` (`?domain_id=&policy_id=`; no id means new), `/governance/violations`, `/governance/violation` (`?domain_id=&violation_id=`), `/governance/exceptions`; nav entries "Policies", "Violations", "Policy exceptions" in the Governance group.
- `frontend/src/features/governance/policy/paths.ts`: `GOVPOLICY_API_PREFIX`, route constants, `policyHref`, `violationHref(domain, violationId)`, `exceptionsHref`.
- `frontend/src/features/governance/policy/capabilities.ts`: `POINT_CAPABILITIES` and `capabilityText(point)` (PRP-112 and PRP-113 import it for their binding rows).
- `ViolationLinks` slot in `ViolationPage.tsx` (an array of extra links); PRP-109 adds its "Governance trail" link (`/governance/trail?violation_id=`) there.
- Mock handlers `frontend/tests/mock-api/features/governance-policy.ts` with stable fixture ids (`POLICY_PII_ID`, `VIOLATION_OPEN_ID`, `EXCEPTION_REQUESTED_ID`) for later e2e specs.

### Patterns to match
- Light route module plus nav items: `frontend/src/features/compliance/routes.tsx` (whole file) and `paths.ts`.
- Query hooks over typed paths: `frontend/src/features/compliance/data.ts:1-40`.
- Client-built draft body with idempotency key and no client-side hash: `frontend/src/features/actions/request.ts:25-46`.
- Mock feature module dispatch: `frontend/tests/mock-api/features/index.ts:19-31` (add one entry; order before `catalog` is not needed, the prefix is `/api/v1/governance/policy`).
- Real-stack entry with expected 403: `frontend/tests/real-stack/routes.spec.ts:190-201` (compliance).

### Gotchas
- Shell and nav import only light modules (`paths.ts`, `routes.tsx`), never a feature `index.ts` (`workspaceNav.ts:1-3` comment).
- Fluent dialog tests: query with `hidden: true` (Tabster `aria-hidden`).
- Unknown counts or missing values are shown as "unknown", never 0 (compliance precedent).
- PRP-112 and PRP-113 own `frontend/src/features/governance/enforcement/**`; this PRP owns only `governance/policy/**`. PRP-109 owns `governance/trail/**` and adds its link through this PRP's `ViolationLinks` slot; PRP-108's Gotchas say the same.
- Playwright: unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` per worktree.
- Do not add a demo banner exception or a `NO_DATA` entry without a reason line; the seeded real stack has no published policy until PRP-109 seeds one, so list the violation and policy pages in `NO_DATA` with that reason (reported OPEN, not hidden).
- Mock fixtures use synthetic ids only; no fixture carries interaction text, and a test asserts the mock module has no `text`, `content`, `prompt` or `response` keys.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/features/governance/policy/**
  - frontend/tests/mock-api/features/governance-policy.ts
  - frontend/tests/mock-api/features/governance-policy.test.ts
  - frontend/tests/e2e/governance-policy/**
  - docs/runbooks/governance-policy.md
tier1: []
tier2_appends:
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
must_not_touch:
  - frontend/src/features/governance/enforcement/**
  - frontend/src/features/governance/trail/**
  - frontend/src/features/catalog/**
  - frontend/src/features/interactions/**
  - frontend/src/features/review/**
  - frontend/src/features/actions/**
  - frontend/src/app/Shell.tsx
  - frontend/tests/mock-api/server.ts
  - services/**
  - packages/**
```

## Implementation blueprint

Parallelization: item 1 first (paths, types, data hooks, mocks). Items 2, 3 and 4 [P] after item 1 (separate page files). Item 5 after 2 and 4. Item 6 after 2-5. Item 7 is `[serial-after: PRP-108]`. Item 8 last.

### Item 1 - Paths, data layer, capabilities and mock handlers
- Deliverable: `governance/policy/{paths,types,data,capabilities,strings}.ts` (typed query and mutation hooks for every PRP-105 route used, ETag capture, cursor pagination), `frontend/tests/mock-api/features/governance-policy.ts` (draft, published and retired policies with two versions, three bindings across points, open, excepted and resolved violations with each evidence kind, requested and approved exceptions, a 412 path, a 403 domain), handler registration line.
- Owned files: those modules, the mock module; Tier-2 `frontend/tests/mock-api/features/index.ts`.
- Must NOT touch: `frontend/tests/mock-api/server.ts`.
- Depends on: PRP-105 merged (routes and models).
- Acceptance criteria: hooks compile against the PRP-99 TS types; the capability test pins points to `EnforcementPoint`; the no-content fixture test passes.
- Tests: `frontend/src/features/governance/policy/data.test.ts`, `capabilities.test.ts`, `frontend/tests/mock-api/features/governance-policy.test.ts`.
- Pattern references: `features/compliance/data.ts`, `tests/mock-api/features/compliance.ts`.

### Item 2 - Policies list and policy page  [P]
- Deliverable: `PoliciesPage.tsx`, `PolicyPage.tsx` (rules, versions, version diff, bindings with capability text, publish and retire buttons showing the returned intent and its advisory state), `VersionDiff.tsx` (pure structural diff of two `PolicyDefinition` rule sets).
- Owned files: those components and their tests.
- Depends on: item 1.
- Acceptance criteria: criteria 1, 2 and 4.
- Tests: `frontend/src/features/governance/policy/policies.test.tsx`, `versionDiff.test.ts`.
- Pattern references: `features/compliance/CompliancePage.tsx`, `ControlDetailPage.tsx`.

### Item 3 - Typed draft editor  [P]
- Deliverable: `PolicyEditorPage.tsx` and `ruleForms/` (one form per kind: `model_allow_list`, `data_sensitivity_access`, `residency`, `budget`, `required_owner`, `required_attestation`, `required_approval`, `content_rule`, `registration_required`; `applies_to` sub-form; read-only fallback for unknown kinds); client validation mirrors schema bounds; save with `If-Match`.
- Owned files: the page, `ruleForms/**`, tests.
- Depends on: item 1.
- Acceptance criteria: criterion 3; a parameter outside bounds is blocked client-side and, if sent, the server 422 is shown with its reason code; no form has a free-text expression field.
- Tests: `frontend/src/features/governance/policy/editor.test.tsx`, `ruleForms/ruleForms.test.tsx`.
- Pattern references: `features/admin/shared/useEtagMutation.ts`, `features/admin/review-policy/ReviewPolicyPage.tsx`.

### Item 4 - Violations, evidence and exceptions  [P]
- Deliverable: `ViolationsPage.tsx`, `ViolationPage.tsx` (evidence list with the link rules of criterion 5, the `ViolationLinks` slot), `ExceptionRequestDialog.tsx`, `ExceptionsPage.tsx`.
- Owned files: those components and tests.
- Depends on: item 1.
- Acceptance criteria: criteria 5, 6 and 7.
- Tests: `frontend/src/features/governance/policy/violations.test.tsx`, `exceptions.test.tsx`.
- Pattern references: `features/curation/ReviewQueuePage.tsx`, `features/review/ReviewItemPage.tsx` (status rendering).

### Item 5 - Routes and navigation
- Deliverable: `governance/policy/routes.tsx` (`governancePolicyRoutes`, `governancePolicyNavItems`), `index.ts`; Tier-2 lines in `appRoutes.ts`, `workspaceNav.ts` (Governance group), `route-manifest.json` (six routes).
- Owned files: the two module files; Tier-2 lines.
- Depends on: items 2 and 4 (item 3's page is imported by path).
- Acceptance criteria: `route-manifest.test.ts`, `routes.test.tsx` and `nav-keys.test.tsx` pass.
- Tests: `frontend/src/app/route-manifest.test.ts` (existing), `frontend/src/features/governance/policy/routes.test.tsx`.
- Pattern references: `features/compliance/routes.tsx`, `app/appRoutes.ts:19-29`.

### Item 6 - E2E, accessibility and real-stack coverage
- Deliverable: Playwright spec on the mock API (list, open policy, diff versions, edit and save a draft, publish shows an intent, open a violation, follow each evidence link, request an exception, 412 and 403 states); axe samples for the six routes; real-stack entries with expected 403 for callers without `govpolicy.read` and `NO_DATA` reasons.
- Owned files: `frontend/tests/e2e/governance-policy/governance-policy.spec.ts`; Tier-2 `route-samples.ts`, `frontend/tests/real-stack/routes.spec.ts`.
- Depends on: item 5.
- Acceptance criteria: criterion 9.
- Tests: the spec; `frontend/tests/e2e/a11y`.
- Pattern references: `frontend/tests/e2e/compliance/compliance.spec.ts`, `route-samples.ts:211-222`.

### Item 7 - Proposal buttons  [serial-after: PRP-108]
- Deliverable: after PRP-108 merges and the branch is rebased: "Propose suspension" on agent-version violations (PRP-108 suspend route, violation id as evidence) and "Propose mode change" on bindings (actions API, PRP-105 diff grammar, `enforce` only where the capability allows), both through `ChangeConfirmDialog` labelled "NeuroSphere state change"; mock handlers and e2e cases.
- Owned files: `governance/policy/proposals/**`, additions to `ViolationPage.tsx` and `PolicyPage.tsx`, the mock module, the e2e spec.
- Must NOT touch: `frontend/src/features/catalog/approval/**` (PRP-108).
- Depends on: items 1-6 and PRP-108 merged.
- Acceptance criteria: criterion 8; a confirmation never shows "applied" before the executor reports it.
- Tests: `frontend/src/features/governance/policy/proposals/proposals.test.tsx`, e2e cases in the item-6 spec.
- Pattern references: `features/actions/request.ts`, `features/governed-change/ChangeConfirmDialog.tsx`.

### Item 8 - Integration and close-out
- Deliverable: a "Policy pages" section in `docs/runbooks/governance-policy.md` (PRP-105 created it; what each page shows, the capability table, how an exception is requested and decided, what is advisory until PRP-108); rebase; Tier-3 regeneration where touched (`PRPs/INDEX.md`, status table); changelog fragment; completion note with the product check (can a steward author, publish and see a violation, and request an exception, without raw API calls?).
- Owned files: the runbook section, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-7 (item 7 may be descoped and filed if PRP-108 slips; say so).
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
pnpm --filter @neurosphere/frontend test:e2e
uv run pytest -q tests/docs/test_nav_allowlist.py tests/docs/test_reference_coverage.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Real-stack run (manual gate, operator with a role): `frontend/tests/real-stack/routes.spec.ts` against `make stack-up`; when not run, OPEN.

## Migration and rollback
None: frontend only, no stored data or settings. Rollback is reverting the PR; the PRP-105 routes keep working without the UI.

## Live and open gates
None live. The real-stack route run is a manual operator gate (PRP-29 item 11 pattern) and is recorded OPEN when not run; the seeded real stack has no published policy until PRP-109.

## NOT building
An expression or rule-text editor (closed typed kinds only); editing a published policy in place; any button that approves or rejects an exception outside the review queue; any control that sets a mode, a status or a published state without an executor intent; showing captured interaction content; claiming that a point blocks anything the PRP-105 capability table says it cannot (the SDK guard is cooperative, not a security boundary; detective evaluation blocks nothing; no blocking inside third-party SaaS); the enforcement bindings page for all points (PRP-112); the governance trail (PRP-109); legal or compliance verdicts on a violation.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 3, 4, 5, 6, 7 and 8 are ASSUMPTIONS; PRP-105 names are final only when it ships)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | serial-after PRP-108 |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files or calling raw APIs):
