---
name: PRP-127-ai-system-register-tiering-and-impact-assessments
status: backlog
priority: P2
order: 127
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-02, NS-04, NS-08
depends_on: [PRP-110-governance-contracts-b, PRP-108-agent-approval-gate-and-platform-control-actions]
wave: W30
branch: prp-127-ai-system-register
allow_parallel: true
issues: []
---

# PRP-127: AI system register, risk tiering and impact assessments

## Goal
Give a customer a register of its AI systems and a place to record, for each one, who decided how risky it is, on what answers, and a reviewed impact assessment. An AI system groups agents, agent versions and model deployments the catalog already knows (`AiSystem.member_ids`); a person answers a versioned questionnaire and records a tier (`RiskTierDetermination`); an assessment is a versioned document whose submission opens a HITL review. Everything is a customer record: the product stores who decided, when and on what evidence, and never computes or states that a system "is" high-risk, prohibited or compliant (owner decision GD-15). It is for domain stewards and risk owners, and it supplies PRP-129 (the CI gate reads register, tier and assessment status), PRP-131 (cards) and PRP-128 (tier-to-control hints). As the W30 stores owner it also declares the containers PRP-130 and PRP-132 consume.

Out of scope: the contracts (PRP-110 owns `risk/v1`; if its cut line moved them here, item 1 does them); framework identifiers and mappings (PRP-128); the CI check (PRP-129); owner attestations and campaigns (PRP-130); alert rules and incidents logic (PRP-132, which only gets its containers here); model and agent cards and safety records (PRP-131); approval of an AgentVersion for activation (PRP-108); any legal classification, certification or compliance statement (design section 8, item 10).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every gap planned; the design (`temp/audit/governance-core-design.md` G-f) finds "model card", "agent card", "risk tier", "EU AI Act" and "42001" have no hits in the tree.
- Lifecycle is only `draft`, `active`, `deprecated`, `retired` (`packages/contracts/schemas/catalog/v1/common.schema.json:58-66`); creation accepts only `draft` or `active` (`services/api/neurosphere_api/catalog/service.py:260-261`) and the only built transition is `deprecate` (`:341`). No approval, registration or assessment state exists anywhere.
- `docs/PRD.md:39` (NS-08) promises only "Map to applicable NIST 800-53 Rev 5 and agency requirements" and says nothing about AI-specific risk records; the AI risk register is new scope the owner added on 2026-11-16, not a restored promise.
- HITL can review it: `ReviewKind` has the insight kinds `relationship`, `evaluation_dispute`, `recommendation`, `policy_exception` (`packages/core/neurosphere_core/hitl/models.py:42-50`) and reviewers of insight kinds need `catalog.curate` (`hitl/policy.py:61-71`); nothing opens a review for a risk document.
- The control library exists to link to (`packages/core/neurosphere_core/compliance/loader.py:120-158`), and the no-claim scanner (`compliance/claims.py`) already refuses affirmative compliance wording.
- PRP-132 declares it needs `alert_rules` and `incidents` from this PRP, and PRP-130 needs containers that no PRP declares (correction, clarification 3).

## Acceptance criteria
- [ ] Given a steward with `risk.manage` on a domain, When they `POST /api/v1/risk/domains/{domain}/systems` with 1-64 member ids visible to them, Then the system is stored `draft`; a member id outside their scope, another domain or another cloud is refused (422 `member_not_visible`, same body as a missing id); registering moves `draft` to `registered` with an audit record; retiring is explicit and never edits the members' catalog lifecycle.
- [ ] Given the questionnaire template, When a person records a determination, Then `determined_by` is derived server-side from the caller (never from the body), `answers` must cover every required question (`unknown` allowed), the `tier` token is stored as given, and the record is append-only: a new determination supersedes by `current_determination_id`; nothing edits an old one.
- [ ] No response, UI string, audit detail, example or document states that a system "is" a tier or compliant: every rendering is of the form "Recorded as <tier> by <person> on <date>"; a test scans `strings.ts`, the runbook and the OpenAPI descriptions with `scan_for_claims` plus a deny-list of "is high-risk", "classified as", "compliant", "certified".
- [ ] Given an impact assessment draft, When the author submits version N, Then it becomes `in_review` and one HITL item (kind `recommendation`, `action_kind` `impact_assessment_review`) opens whose `subject_ref` names the assessment version; the author cannot decide it (self-review refused); an approval by a reviewer with `catalog.curate` seals the version `approved` (sections immutable; a change creates version N+1 and marks N `superseded`); a rejection returns it with the reviewer's reason.
- [ ] Section `control_ids` are checked against the shipped control library; an unknown id is refused (`unknown_control_id`); the library is only read.
- [ ] Reading any register, determination or assessment is scope-filtered; a foreign id is 404 and a denial is recorded; `risk.read` and `risk.manage` are in the inventories; the admin role cannot approve an assessment it authored.
- [ ] The seven containers `ai_systems`, `risk_determinations`, `impact_assessments`, `alert_rules`, `incidents`, `attestations`, `attestation_campaigns` are declared with their mirrors and parity tests pass; `incidents` accepts the PRP-132 timeline documents without a new container.
- [ ] If PRP-110 shipped without the `risk/v1`, `incidents/v1` schemas and `ticket_create`, item 1 delivers them (cut line) and `generate.py --check` passes; otherwise item 1 records "nothing to do".
- [ ] A runbook `docs/runbooks/risk-register.md` explains the register as the customer's record, with the wording rule; the frontend page lists systems, shows the recorded tier with who and when, and the assessment state.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend typecheck and test, `validate_planning.py` pass; PR open, CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | ASSUMPTION (GD-15, recommended default): the risk tier is the customer's recorded determination with the questionnaire as evidence; the product never states a legal classification | product computes; person records | Person records; the product never computes a tier from answers and never suggests one |
| 2 | Questionnaire content and tier vocabulary | EU AI Act classes written now; internal template | ASSUMPTION: a product-shipped `internal` template `ai-use-v1` in the product's own words (purpose, affected people, autonomy, human oversight, data sensitivity, external exposure); the tier token is chosen from the PRP-110 documented values and framework-specific vocabularies come from PRP-128 data fetched at execution, nothing from memory |
| 3 | ASSUMPTION: containers beyond the design list | four only; add three | This PRP declares `risk_determinations`, `attestations` and `attestation_campaigns` in addition to `ai_systems`, `impact_assessments`, `alert_rules`, `incidents`, because PRP-130 (W31) has no stores owner. Partition `/customer_id` + `/domain_id`, no default TTL (retention is lifecycle policy) |
| 4 | Is register/determination a governed action | executor; audited admin mutation | ASSUMPTION: audited mutation (`run_audited_mutation`). These records change no policy, capture, enforcement or external system, so the executor rule does not apply. Activating an AgentVersion stays PRP-108's approval |
| 5 | HITL kind for assessment review | new kind; existing insight kind | ASSUMPTION (GD-47, recommended default): impact-assessment review and attestation non-response use the existing HITL `recommendation` kind with action kinds `impact_assessment_review` and `attestation_overdue_review`; no new HITL kind. Here: `impact_assessment_review` (a new kind edits `hitl/models.py` and a contract enum, outside this PRP). Owner may ask for a dedicated kind later |
| 6 | Applying the review outcome | worker; read-repair | ASSUMPTION: idempotent, ETag-conditional "sync" run by the assessment read routes and by the PRP-129 reader, written with a system actor and audited (`risk.assessment_review_applied`); no new worker role |
| 7 | Self-review refusal | registry override; own check | Verify first whether `ReviewPolicyRegistry` can carry an override for `(recommendation, impact_assessment_review)` with `self_approval_forbidden` (`hitl/policy.py:74-95`); if not, the sync refuses to apply a decision made by the author and says so (UNVERIFIED) |
| 8 | Roles | ASSUMPTION | `risk.read` to viewer, analyst, domain_steward, admin and security_auditor; `risk.manage` to domain_steward and admin (admin drafts, a steward reviews) |
| 9 | Tiers that require an assessment | `high` by default; none | ASSUMPTION (GD-36, recommended default): no risk tier requires an approved impact assessment by default (`NS_RISK_ASSESSMENT_REQUIRED_TIERS` empty); the customer sets the list. Here: PRP-129 reads that setting; this PRP states no tier rule |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-110-governance-contracts-b.md` - "Interfaces provided" for `AiSystem`, `RiskTierDetermination`, `ImpactAssessment`, `SystemCard`, the cut line.
- `packages/core/neurosphere_core/hitl/service.py:141-200,269-330,505-521` and `hitl/policy.py:61-95` - `open_item`, `decide`, `_check_separation`, `ReviewPolicyRegistry.resolve`.
- `services/api/neurosphere_api/hitl/router.py` - how reviewers decide; the context-record gotcha below.
- `packages/core/neurosphere_core/compliance/loader.py:120-158`, `compliance/claims.py` - library read and claim scanner.
- `services/api/neurosphere_api/mcp/admin/router.py:96-198`, `packages/core/neurosphere_core/audit/repository.py:247-270` - audited admin mutation with `If-Match`.
- `packages/core/neurosphere_core/stores/containers.py:94-110` and `packages/core/tests/stores_registry/` - declaring a container and its parity tests.
- `packages/core/neurosphere_core/catalog/protocol.py:70-97`, `services/api/neurosphere_api/catalog/dependencies.py:97` (`entity_access`) - reading members through scope.
- `services/api/neurosphere_api/compliance/router.py` and `frontend/src/features/compliance/` - read API and page to imitate.
- `PRPs/backlog/PRP-108-agent-approval-gate-and-platform-control-actions.md`, `PRP-132-alert-rules-and-incidents.md` - what they expect from this PRP.

### Interfaces consumed
- PRP-110: `neurosphere_contracts.risk.v1` (`AiSystem`, `RiskTierDetermination`, `ImpactAssessment`, `SystemCard`, `Attestation`), `incidents.v1` (`AlertRule`, `Incident`), `policy.v1.RegistrationCheck*`. Names UNVERIFIED until merged; PRP-110 wins on any difference.
- PRP-108: `AgentVersion.approval` and `neurosphere_core.catalog.approval` (the registration check reads approval state; this PRP only displays it); the in-core `platform-control` target is not used here (clarification 4).
- Shipped: HITL service (PRP-17), `CatalogRepository` and `entity_access`, `run_audited_mutation`, `audited_read`, `Permission`/`Role` tables, control library (PRP-56, plus PRP-81 rows when present), `RouterRegistry`.

### Interfaces provided
- Core `neurosphere_core.risk`: `AiSystemStore`, `DeterminationStore`, `ImpactAssessmentStore` (each with `InMemory*` and `Cosmos*`), `QuestionnaireTemplate` and `AssessmentTemplate` loaders (YAML under `risk/templates/`), `RiskRegisterService`, `RiskRegisterReader.systems_containing(entity_id, scope)`, `.latest_determination(system_id)`, `.latest_assessment(system_id)` (read-only, used by PRP-129 and PRP-131), `sync_assessment_review(assessment)`.
- Containers (all declared here): `ai_systems`, `risk_determinations`, `impact_assessments`, `alert_rules`, `incidents`, `attestations`, `attestation_campaigns`.
- Permissions `Permission.RISK_READ = "risk.read"`, `Permission.RISK_MANAGE = "risk.manage"`.
- Routes under `/api/v1/risk`: `GET|POST /domains/{domain}/systems`, `GET|PUT /domains/{domain}/systems/{id}` (`If-Match`), `POST .../systems/{id}/register`, `POST .../systems/{id}/retire`, `GET|POST .../systems/{id}/determinations`, `GET|POST .../systems/{id}/assessments`, `PUT .../assessments/{aid}/versions/{v}` (draft), `POST .../assessments/{aid}/versions/{v}/submit`, `GET /questionnaires/{template_id}`.
- API builder `runtime/builders/risk.py` (`BUILDER`), optional component `risk_register`, `app.state.risk_register`, setting `NS_RISK_REGISTER_ENABLED` (default true) and `NS_RISK_REGISTER_BACKEND` (`cosmos|memory`, memory only under `NS_ENV=local`).
- Audit operations `risk.system_register`, `risk.system_update`, `risk.system_retire`, `risk.determination_record`, `risk.assessment_draft`, `risk.assessment_submit`, `risk.assessment_review_applied`.
- Canonical ids `<cloud>:<customer>:neurosphere:ai_system:<id>` and `...:impact_assessment:<id>`.

### Patterns to match
- Audited admin routes with `ETag`/`If-Match`: `services/api/neurosphere_api/mcp/admin/router.py:96-198`.
- Store with in-memory twin and Cosmos ETag replace: `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Read route with allowed-read audit: `services/api/neurosphere_api/compliance/router.py` (`audited_read`).
- Optional builder component reported in status: `services/api/neurosphere_api/runtime/builders/edge.py:17-27`.
- Page layout and strings module: `frontend/src/features/compliance/CompliancePage.tsx`, `strings.ts`.

### Gotchas
- A HITL `ReviewItem` carries only an opaque `subject_ref`; reviewers need the assessment itself, so the page and a `GET` route are the context record (PRP-16 round-2 lesson). The review page must show the version, its sections and who authored it.
- Member checks go through the scope-filtered catalog; do not read members with a system caller on the request path, or a steward could register a system around agents they cannot see.
- Audit detail carries ids and reason codes only: never answer notes, section text or intended-use text (they are customer prose and may name people).
- `tier` and `framework` are open-ended in PRP-110: store unknown values, render them as given, never branch on a tier in product logic except PRP-129's configured list.
- Adding permissions and a builder pins tests: `packages/core/tests/auth/scope/test_roles.py`, `tests/security/authz/test_privileged_roles.py`, `services/api/tests/runtime_api/test_readiness.py`, the route inventories; list each update in the completion note.
- New test directories use unique names (`packages/core/tests/risk_register`, `services/api/tests/risk_api`).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/risk/**
  - packages/core/tests/risk_register/**
  - services/api/neurosphere_api/risk/**
  - services/api/neurosphere_api/runtime/builders/risk.py
  - services/api/tests/risk_api/**
  - frontend/src/features/risk/**
  - frontend/tests/mock-api/features/risk.ts
  - tests/security/authz/test_risk_register.py
  - docs/runbooks/risk-register.md
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
tier2_appends:
  - packages/core/neurosphere_core/auth/scope/permissions.py
  - packages/core/tests/auth/scope/test_roles.py
  - tests/security/authz/test_privileged_roles.py
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
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
  - packages/core/neurosphere_core/catalog/**
  - packages/core/neurosphere_core/compliance/**
  - packages/core/neurosphere_core/actions/**
  - services/api/neurosphere_api/runtime/builders/data.py
```
Item 1 is the only item allowed to edit `packages/contracts/**`, and only when the cut line applies.

## Implementation blueprint

Parallelization: item 1 first (may be a no-op), item 2 next (Tier-1); items 3 and 6 [P] after 2 (core and frontend share no file); 4 after 3; 5 after 4; 7 after 5; 8 last.

### Item 1 - Contracts cut-line check
- Deliverable: confirm PRP-110 shipped `risk/v1` (`AiSystem`, `RiskTierDetermination`, `ImpactAssessment`, `SystemCard`, `Attestation`), `incidents/v1` and `ticket_create`. If it did, write "nothing to do" in the completion note. If PRP-110 applied its cut line, add those schemas exactly as PRP-110's "Interfaces provided" names them, with examples, bindings and tests, and tell PRP-132 (`[serial-after: PRP-127]`) and PRP-129, PRP-131 in the completion note.
- Owned files: `packages/contracts/**`, `tests/contracts/test_governance_b_risk.py` (only when the cut line applies).
- Must NOT touch: anything else in contracts.
- Depends on: PRP-110 merged.
- Acceptance criteria: criterion 8.
- Tests: `tests/contracts`, `python packages/contracts/scripts/generate.py --check`.
- Pattern references: PRP-110 items 4 and 6.

### Item 2 - Container declarations (Tier-1)
- Deliverable: seven `ContainerSpec` rows, `infra/compose/cosmos-containers.json` regenerated by `export_json`, and the `cosmos-data.bicep` entries; no store code.
- Owned files: the three Tier-1 files; `packages/core/tests/stores_registry/` parity rows (additive).
- Depends on: item 1.
- Acceptance criteria: criterion 7; the export drift test passes.
- Tests: `packages/core/tests/stores_registry`.
- Pattern references: `stores/containers.py:94-110`; PRP-102 item 1 for the same mirrors.

### Item 3 - Core register, determination and assessment  [P]
- Deliverable: the stores with in-memory and Cosmos implementations (ETag replace, append-only determinations, sealed approved versions), the two shipped templates, `RiskRegisterService` (member visibility, state machines, wording rule), `sync_assessment_review`, the reader, and the `risk.read` / `risk.manage` permissions with the role map.
- Owned files: `packages/core/neurosphere_core/risk/**`, `packages/core/tests/risk_register/**`, the Tier-2 permission lines and role tests.
- Must NOT touch: HITL, catalog and compliance packages.
- Depends on: item 2.
- Acceptance criteria: criteria 1, 2, 4 (state part), 5; an approved version rejects replace; a determination cannot be edited; `answers` incomplete is refused.
- Tests: `packages/core/tests/risk_register/test_register.py`, `test_determination.py`, `test_assessment_states.py`, `test_review_sync.py`, `test_templates.py`.
- Pattern references: `mcp/cosmos_store.py:86-140`, `hitl/service.py:141-200`.

### Item 4 - API routes
- Deliverable: routers, models and dependencies for the routes in "Interfaces provided"; every mutation audited, `If-Match` required, reads via `audited_read`; submit opens the HITL item through `HitlService.open_item` and returns the item id.
- Owned files: `services/api/neurosphere_api/risk/**`, `services/api/tests/risk_api/**`.
- Depends on: item 3.
- Acceptance criteria: criteria 1, 2, 4, 6; foreign id 404; missing `If-Match` is `precondition_required`.
- Tests: `services/api/tests/risk_api/test_routes.py`, `test_review_flow.py`, `test_scope.py`.
- Pattern references: `mcp/admin/router.py:96-198`, `compliance/router.py`.

### Item 5 - Composition and status
- Deliverable: `runtime/builders/risk.py`, optional `risk_register` component with a reason code when Cosmos is absent, Tier-2 appends.
- Owned files: `runtime/builders/risk.py` plus the Tier-2 lines; update `services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py` and `runtime_data/data_helpers.py` where they pin builder order or component sets.
- Depends on: item 4.
- Acceptance criteria: with the setting off nothing changes; with an in-memory backend the routes work under `NS_ENV=local`.
- Tests: `services/api/tests/runtime_api`, `runtime_routes`, `runtime_data`, `runtime_gateway_builder`.
- Pattern references: `runtime/builders/edge.py:17-27`.

### Item 6 - Frontend  [P]
- Deliverable: `features/risk` with the systems list, system detail (members, recorded tier with who and when, determination history, questionnaire form, assessment editor and state), mock handlers, a11y route sample; strings module under the wording rule.
- Owned files: `frontend/src/features/risk/**`, `frontend/tests/mock-api/features/risk.ts`, Tier-2 frontend lines.
- Depends on: item 2 (shapes from PRP-110 bindings).
- Acceptance criteria: criteria 3 and 9; keyboard operable, no tier shown without who and when.
- Tests: `pnpm --filter @neurosphere/frontend test`, typecheck, e2e sample.
- Pattern references: `frontend/src/features/compliance/CompliancePage.tsx`.

### Item 7 - Authorization and wording negative suite
- Deliverable: ABAC cases for every route (no role, viewer on manage routes, wrong domain, wrong customer, wrong cloud, expired assignment), author-cannot-review, a leak test (no section text or notes in audit, logs, exceptions), and the wording scan.
- Owned files: `tests/security/authz/test_risk_register.py`.
- Depends on: item 5.
- Acceptance criteria: criteria 3, 4, 6.
- Tests: `tests/security/authz`.
- Pattern references: PRP-41 item 5.

### Item 8 - Integration and close-out
- Deliverable: runbook, Tier-2 inventories, rebase, Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), changelog fragment `changelog.d/PRP-127-ai-system-register.md`, completion note listing every provided name and the three extra containers.
- Owned files: `docs/runbooks/risk-register.md`, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
python packages/contracts/scripts/generate.py --check
uv run pytest -q packages/core/tests/risk_register packages/core/tests/stores_registry packages/core/tests/hitl packages/core/tests/auth packages/core/tests/compliance_lib services/api/tests/risk_api services/api/tests/runtime_api services/api/tests/runtime_routes services/api/tests/runtime_data services/api/tests/runtime_gateway_builder services/api/tests/authz tests/security/authz tests/contracts services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
Additive: seven new Cosmos containers (created by IaC outside local) and new documents only; no existing document changes. Turn off with `NS_RISK_REGISTER_ENABLED=false` (routes absent, component disabled with a reason code). Revert by `git revert` plus regenerating the export; leftover documents are inert. Hosted environments need the IaC change applied before the app starts with the feature on; a missing container is a readiness failure, not a silent create.

## Live and open gates
None run here: emulator and in-memory twins only. The hosted register page is shown by PRP-109/PRP-136 hosted runs, operator-approved and OPEN until evidenced.

## NOT building
Any statement or computation of a legal risk class, prohibited use or compliance (a tier is the customer's record); questionnaire or template editors; auto-suggested tiers; EU AI Act, ISO/IEC 42001 or NIST identifiers (PRP-128); the CI gate (PRP-129); attestations (PRP-130); cards and safety records (PRP-131); incident logic (PRP-132); a dedicated HITL review kind; PostgreSQL implementations of the new stores (the multi-cloud store PRPs add them); email or channel delivery of review requests beyond what PRP-107 already does for HITL.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 to 8 are ASSUMPTIONS for plan approval; row 7 is UNVERIFIED)

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
- Provided names (for PRP-129, 130, 131, 132 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: `NS_RISK_REGISTER_ENABLED`, `NS_RISK_REGISTER_BACKEND`.
- Follow-up issues:
- Product check (can an operator use it without editing files): the register page, determination form and assessment editor work in the console.
